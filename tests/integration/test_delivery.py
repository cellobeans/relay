"""End-to-end delivery tests: real database and Redis, with a stubbed receiver.

The receiver is an httpx.MockTransport: requests the worker makes are handed to a Python
function instead of going over the network. That function checks the signature exactly like a
real receiver would, so these tests cover the whole path from POST /events to a verified
webhook, without needing the receiver container.
"""

import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal
from app.models import DeliveryAttempt, DeliveryStatus
from app.services.delivery import deliver_attempt, requeue_stuck_attempts
from app.services.signing import verify
from tests.integration.helpers import create_endpoint, create_tenant, post_event


class StubReceiver:
    """Records every request and answers with the next queued response."""

    def __init__(self, secret: str, responses: list[int | Exception]):
        self.secret = secret
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        outcome = self.responses.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return httpx.Response(outcome)

    def signature_valid(self, request: httpx.Request) -> bool:
        return verify(
            self.secret,
            request.headers["X-Relay-Timestamp"],
            request.content,
            request.headers["X-Relay-Signature"],
        )


async def _setup(client) -> tuple[dict, dict, dict]:
    """A tenant with one endpoint and one posted event. Returns (headers, endpoint, event)."""
    headers = await create_tenant(client)
    endpoint = await create_endpoint(client, headers)
    event = (await post_event(client, headers, payload={"order_id": 42})).json()
    return headers, endpoint, event


async def _attempts(event_id: str) -> list[DeliveryAttempt]:
    async with SessionLocal() as session:
        result = await session.scalars(
            select(DeliveryAttempt)
            .where(DeliveryAttempt.event_id == uuid.UUID(event_id))
            .order_by(DeliveryAttempt.attempt_no)
        )
        return list(result)


async def _deliver(attempt_id, receiver: StubReceiver, arq) -> None:
    async with httpx.AsyncClient(transport=httpx.MockTransport(receiver)) as http:
        await deliver_attempt(attempt_id, http, arq)


async def test_successful_delivery_is_signed_and_recorded(client, arq):
    _, endpoint, event = await _setup(client)
    receiver = StubReceiver(endpoint["secret"], [200])

    await _deliver(uuid.UUID(event["deliveries"][0]["id"]), receiver, arq)

    [request] = receiver.requests
    assert str(request.url) == endpoint["url"]
    assert receiver.signature_valid(request)
    assert request.headers["X-Relay-Event-Id"] == event["id"]
    assert request.headers["X-Relay-Event-Type"] == "order.created"
    assert request.content == b'{"order_id":42}'

    [attempt] = await _attempts(event["id"])
    assert attempt.status == DeliveryStatus.succeeded
    assert attempt.response_code == 200
    assert attempt.latency_ms is not None
    assert attempt.completed_at is not None


async def test_tampered_body_fails_verification(client, arq):
    _, endpoint, event = await _setup(client)
    receiver = StubReceiver(endpoint["secret"], [200])
    await _deliver(uuid.UUID(event["deliveries"][0]["id"]), receiver, arq)

    [request] = receiver.requests
    tampered = httpx.Request(
        "POST", request.url, headers=request.headers, content=b'{"order_id":43}'
    )
    assert not receiver.signature_valid(tampered)


@pytest.mark.parametrize(
    "failure", [500, 503, 429, httpx.ConnectError("refused"), httpx.ReadTimeout("slow")]
)
async def test_retryable_failure_schedules_a_deferred_retry(client, arq, failure):
    _, endpoint, event = await _setup(client)
    await arq.flushdb()  # drop the job POST /events enqueued, so we can see only the retry
    receiver = StubReceiver(endpoint["secret"], [failure])

    before = datetime.now(UTC)
    await _deliver(uuid.UUID(event["deliveries"][0]["id"]), receiver, arq)

    first, retry = await _attempts(event["id"])
    assert first.status == DeliveryStatus.failed
    assert first.error
    assert retry.status == DeliveryStatus.pending
    assert retry.attempt_no == 2
    # First retry delay is 5s ±20%.
    assert before + timedelta(seconds=4) <= retry.next_retry_at
    assert retry.next_retry_at <= datetime.now(UTC) + timedelta(seconds=6)
    # The retry job is in Redis, scheduled for the future (arq scores jobs by run time in ms).
    [(job_id, score)] = await arq.zrange("arq:queue", 0, -1, withscores=True)
    assert job_id.decode() == f"delivery:{retry.id}"
    assert score > datetime.now(UTC).timestamp() * 1000


@pytest.mark.parametrize("status_code", [400, 401, 404, 410])
async def test_client_errors_are_not_retried(client, arq, status_code):
    _, endpoint, event = await _setup(client)
    receiver = StubReceiver(endpoint["secret"], [status_code])

    await _deliver(uuid.UUID(event["deliveries"][0]["id"]), receiver, arq)

    [attempt] = await _attempts(event["id"])
    assert attempt.status == DeliveryStatus.dead
    assert attempt.response_code == status_code


async def test_gives_up_after_last_attempt_then_replay_sends_again(client, arq, monkeypatch):
    monkeypatch.setattr(settings, "retry_delays", [0.01])  # 2 attempts in total
    headers, endpoint, event = await _setup(client)
    receiver = StubReceiver(endpoint["secret"], [500, 500, 200])

    await _deliver(uuid.UUID(event["deliveries"][0]["id"]), receiver, arq)
    first, second = await _attempts(event["id"])
    await _deliver(second.id, receiver, arq)

    attempts = await _attempts(event["id"])
    assert [a.status for a in attempts] == [DeliveryStatus.failed, DeliveryStatus.dead]

    res = await client.post(f"/events/{event['id']}/replay", headers=headers)
    assert res.json() == {"replayed": 1}
    replayed = (await _attempts(event["id"]))[-1]
    assert replayed.attempt_no == 3
    assert replayed.status == DeliveryStatus.pending
    assert await arq.exists(f"arq:job:delivery:{replayed.id}")

    await _deliver(replayed.id, receiver, arq)
    assert (await _attempts(event["id"]))[-1].status == DeliveryStatus.succeeded
    # Nothing is dead any more, so a second replay does nothing.
    res = await client.post(f"/events/{event['id']}/replay", headers=headers)
    assert res.json() == {"replayed": 0}


async def test_running_a_job_twice_sends_only_once(client, arq):
    # arq is at-least-once: after a crash a job can run again. A finished attempt is skipped.
    _, endpoint, event = await _setup(client)
    receiver = StubReceiver(endpoint["secret"], [200, 200])
    attempt_id = uuid.UUID(event["deliveries"][0]["id"])

    await _deliver(attempt_id, receiver, arq)
    await _deliver(attempt_id, receiver, arq)

    assert len(receiver.requests) == 1


async def test_deactivated_endpoint_is_not_called(client, arq):
    headers, endpoint, event = await _setup(client)
    await client.post(f"/endpoints/{endpoint['id']}/deactivate", headers=headers)
    receiver = StubReceiver(endpoint["secret"], [])

    await _deliver(uuid.UUID(event["deliveries"][0]["id"]), receiver, arq)

    assert receiver.requests == []
    [attempt] = await _attempts(event["id"])
    assert attempt.status == DeliveryStatus.dead


async def test_sweep_requeues_overdue_pending_attempts_only(client, arq):
    _, _, event = await _setup(client)
    await arq.flushdb()  # simulate the job being lost (Redis failed after the DB commit)
    attempt_id = uuid.UUID(event["deliveries"][0]["id"])

    assert await requeue_stuck_attempts(arq) == 0  # brand new: still within the grace period

    async with SessionLocal() as session:
        attempt = await session.get(DeliveryAttempt, attempt_id)
        attempt.created_at = datetime.now(UTC) - timedelta(minutes=5)
        await session.commit()

    assert await requeue_stuck_attempts(arq) == 1
    assert await arq.exists(f"arq:job:delivery:{attempt_id}")
