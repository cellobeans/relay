"""Integration tests for the HTTP API, against a real Postgres and Redis."""

import asyncio
import hashlib

from sqlalchemy import func, select

from app.db import SessionLocal
from app.models import Event, Tenant
from tests.integration.helpers import (
    ADMIN_HEADERS,
    create_endpoint,
    create_tenant,
    post_event,
)


async def test_healthz_reports_both_dependencies(client):
    res = await client.get("/healthz")
    assert res.status_code == 200
    assert res.json() == {"status": "ok", "database": "ok", "redis": "ok"}


# --- Auth --------------------------------------------------------------------------------


async def test_missing_wrong_and_malformed_keys_are_rejected(client):
    assert (await client.get("/endpoints")).status_code == 401
    wrong = {"Authorization": "Bearer rly_not-a-real-key"}
    assert (await client.get("/endpoints", headers=wrong)).status_code == 401
    malformed = {"Authorization": "rly_missing-bearer-prefix"}
    assert (await client.get("/endpoints", headers=malformed)).status_code == 401


async def test_admin_route_needs_admin_token_not_a_tenant_key(client):
    tenant_headers = await create_tenant(client)
    body = {"name": "x"}
    assert (await client.post("/admin/tenants", json=body)).status_code == 401
    res = await client.post("/admin/tenants", json=body, headers=tenant_headers)
    assert res.status_code == 401
    res = await client.post("/admin/tenants", json=body, headers=ADMIN_HEADERS)
    assert res.status_code == 201


async def test_only_the_hash_of_the_api_key_is_stored(client):
    res = await client.post("/admin/tenants", json={"name": "Acme"}, headers=ADMIN_HEADERS)
    api_key = res.json()["api_key"]
    async with SessionLocal() as session:
        tenant = await session.scalar(select(Tenant))
    assert tenant.api_key_hash == hashlib.sha256(api_key.encode()).hexdigest()
    assert api_key not in tenant.api_key_hash


# --- Tenant isolation ----------------------------------------------------------------------


async def test_tenant_cannot_see_or_touch_another_tenants_data(client):
    a = await create_tenant(client, "A")
    b = await create_tenant(client, "B")
    endpoint = await create_endpoint(client, a)
    event = (await post_event(client, a)).json()

    assert (await client.get(f"/endpoints/{endpoint['id']}", headers=a)).status_code == 200
    # To B, A's resources look exactly like ones that don't exist.
    assert (await client.get(f"/endpoints/{endpoint['id']}", headers=b)).status_code == 404
    res = await client.post(f"/endpoints/{endpoint['id']}/deactivate", headers=b)
    assert res.status_code == 404
    assert (await client.get("/endpoints", headers=b)).json() == []
    assert (await client.get(f"/events/{event['id']}", headers=b)).status_code == 404
    assert (await client.post(f"/events/{event['id']}/replay", headers=b)).status_code == 404

    # And B's attempt to deactivate didn't change anything.
    assert (await client.get(f"/endpoints/{endpoint['id']}", headers=a)).json()["active"]


async def test_signing_secret_is_returned_only_on_create(client):
    a = await create_tenant(client)
    endpoint = await create_endpoint(client, a)
    assert endpoint["secret"].startswith("whsec_")
    listed = (await client.get("/endpoints", headers=a)).json()
    fetched = (await client.get(f"/endpoints/{endpoint['id']}", headers=a)).json()
    assert "secret" not in listed[0]
    assert "secret" not in fetched


# --- Idempotent ingestion ------------------------------------------------------------------


async def _event_count() -> int:
    async with SessionLocal() as session:
        return await session.scalar(select(func.count()).select_from(Event))


async def test_same_idempotency_key_returns_original_event(client):
    a = await create_tenant(client)
    first = await post_event(client, a, key="order-1", payload={"order_id": 1})
    repeat = await post_event(client, a, key="order-1", payload={"order_id": 999})

    assert first.status_code == 201
    assert repeat.status_code == 200
    assert repeat.json()["id"] == first.json()["id"]
    assert repeat.json()["payload"] == {"order_id": 1}  # the original, not the new body
    assert await _event_count() == 1


async def test_concurrent_requests_with_same_key_create_one_event(client):
    # The case a "does it exist? then insert" check in Python gets wrong: all of these
    # requests are in flight at the same time. The unique constraint makes it safe.
    a = await create_tenant(client)
    await create_endpoint(client, a)
    responses = await asyncio.gather(*(post_event(client, a, key="race") for _ in range(10)))

    assert sorted(r.status_code for r in responses) == [200] * 9 + [201]
    assert len({r.json()["id"] for r in responses}) == 1
    assert await _event_count() == 1
    assert len(responses[0].json()["deliveries"]) == 1  # and only one delivery, too


async def test_same_key_for_different_tenants_is_two_events(client):
    a = await create_tenant(client, "A")
    b = await create_tenant(client, "B")
    assert (await post_event(client, a, key="shared")).status_code == 201
    assert (await post_event(client, b, key="shared")).status_code == 201
    assert await _event_count() == 2


async def test_idempotency_key_header_is_required(client):
    a = await create_tenant(client)
    res = await client.post("/events", json={"type": "x", "payload": {}}, headers=a)
    assert res.status_code == 422


async def test_deliveries_only_for_active_subscribed_endpoints(client):
    a = await create_tenant(client)
    subscribed = await create_endpoint(client, a, ["order.created", "order.paid"])
    await create_endpoint(client, a, ["order.paid"])  # different event type
    inactive = await create_endpoint(client, a, ["order.created"])
    await client.post(f"/endpoints/{inactive['id']}/deactivate", headers=a)
    other_tenant = await create_tenant(client, "B")
    await create_endpoint(client, other_tenant, ["order.created"])  # someone else's endpoint

    event = (await post_event(client, a, type_="order.created")).json()

    assert [d["endpoint_id"] for d in event["deliveries"]] == [subscribed["id"]]
    assert event["deliveries"][0]["status"] == "pending"


async def test_each_new_delivery_is_enqueued_as_a_job(client, arq):
    a = await create_tenant(client)
    await create_endpoint(client, a)
    event = (await post_event(client, a)).json()

    attempt_id = event["deliveries"][0]["id"]
    assert await arq.exists(f"arq:job:delivery:{attempt_id}")
    assert await arq.zcard("arq:queue") == 1

    # A repeated request must not enqueue the delivery again.
    await post_event(client, a)
    assert await arq.zcard("arq:queue") == 1
