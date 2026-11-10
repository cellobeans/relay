"""Small helpers shared by the integration tests."""

import httpx

ADMIN_HEADERS = {"Authorization": "Bearer test-admin-token"}


async def create_tenant(client: httpx.AsyncClient, name: str = "Acme") -> dict[str, str]:
    """Create a tenant and return the headers that authenticate as it."""
    res = await client.post("/admin/tenants", json={"name": name}, headers=ADMIN_HEADERS)
    assert res.status_code == 201, res.text
    return {"Authorization": f"Bearer {res.json()['api_key']}"}


async def create_endpoint(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    event_types: list[str] | None = None,
    url: str = "http://receiver.test/webhook",
) -> dict:
    res = await client.post(
        "/endpoints",
        json={"url": url, "event_types": event_types or ["order.created"]},
        headers=headers,
    )
    assert res.status_code == 201, res.text
    return res.json()


async def post_event(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    key: str = "key-1",
    type_: str = "order.created",
    payload: dict | None = None,
) -> httpx.Response:
    return await client.post(
        "/events",
        json={"type": type_, "payload": payload or {"order_id": 1}},
        headers={**headers, "Idempotency-Key": key},
    )
