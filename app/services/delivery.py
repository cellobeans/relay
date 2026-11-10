"""Sending one delivery attempt and recording the result. Called by the arq worker."""

import json
import logging
import time
import uuid
from datetime import UTC, datetime

import httpx
from arq.connections import ArqRedis
from sqlalchemy import select

from app.db import SessionLocal
from app.models import DeliveryAttempt, DeliveryStatus, Endpoint, Event
from app.services.signing import sign

log = logging.getLogger("relay.delivery")

JOB_NAME = "deliver"


async def enqueue_delivery(
    arq: ArqRedis, attempt_id: uuid.UUID, defer_by: float | None = None
) -> None:
    # The job id is derived from the attempt id, and arq ignores a job whose id is already
    # queued. So enqueueing the same attempt twice is harmless: it is still sent only once.
    await arq.enqueue_job(
        JOB_NAME, str(attempt_id), _job_id=f"delivery:{attempt_id}", _defer_by=defer_by
    )


async def deliver_attempt(attempt_id: uuid.UUID, http: httpx.AsyncClient) -> None:
    # Step 1: load what we need, then release the DB connection before the slow network call,
    # so 50 in-flight deliveries don't hold 50 database connections for up to 10s each.
    async with SessionLocal() as session:
        row = (
            await session.execute(
                select(DeliveryAttempt, Event, Endpoint)
                .join(Event, Event.id == DeliveryAttempt.event_id)
                .join(Endpoint, Endpoint.id == DeliveryAttempt.endpoint_id)
                .where(DeliveryAttempt.id == attempt_id)
            )
        ).first()
    if row is None:
        log.warning("attempt %s not found, skipping", attempt_id)
        return
    attempt, event, endpoint = row
    if attempt.status != DeliveryStatus.pending:
        # Jobs can run more than once (e.g. after a worker crash); never re-send a finished one.
        log.info("attempt %s already %s, skipping", attempt_id, attempt.status)
        return

    # Step 2: send it.
    response_code: int | None = None
    error: str | None = None
    latency_ms = 0
    if not endpoint.active:
        error = "endpoint is deactivated"
    else:
        # Serialise once and sign exactly these bytes; the receiver verifies the raw body it got.
        body = json.dumps(event.payload, separators=(",", ":")).encode()
        timestamp = int(time.time())
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "Relay-Webhooks/0.1",
            # Same id on every retry of this event, so receivers can drop duplicates.
            "X-Relay-Event-Id": str(event.id),
            "X-Relay-Event-Type": event.type,
            "X-Relay-Timestamp": str(timestamp),
            "X-Relay-Signature": sign(endpoint.secret, timestamp, body),
        }
        start = time.perf_counter()
        try:
            response = await http.post(endpoint.url, content=body, headers=headers)
            response_code = response.status_code
            if not response.is_success:
                error = f"HTTP {response_code}"
        except httpx.HTTPError as exc:  # timeout, connection refused, DNS failure, ...
            error = f"{type(exc).__name__}: {exc}"[:500]
        latency_ms = int((time.perf_counter() - start) * 1000)

    # Step 3: record the outcome.
    async with SessionLocal() as session:
        attempt = await session.get(DeliveryAttempt, attempt_id)
        if attempt is None or attempt.status != DeliveryStatus.pending:
            return
        attempt.response_code = response_code
        attempt.error = error
        attempt.latency_ms = latency_ms
        attempt.completed_at = datetime.now(UTC)
        attempt.status = DeliveryStatus.succeeded if error is None else DeliveryStatus.failed
        await session.commit()

    log.info(
        "attempt %s for event %s -> %s (%s, %d ms)",
        attempt_id,
        event.id,
        attempt.status,
        response_code or error,
        latency_ms,
    )
