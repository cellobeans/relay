"""Sending one delivery attempt and recording the result. Called by the arq worker."""

import json
import logging
import time
import uuid
from datetime import UTC, datetime, timedelta

import httpx
from arq.connections import ArqRedis
from sqlalchemy import func, select

from app.config import settings
from app.db import SessionLocal
from app.models import DeliveryAttempt, DeliveryStatus, Endpoint, Event
from app.services.backoff import max_attempts, retry_delay, should_retry
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


async def deliver_attempt(attempt_id: uuid.UUID, http: httpx.AsyncClient, arq: ArqRedis) -> None:
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

    # Step 3: record the outcome and, if it failed, decide: retry later, or give up (dead).
    retry: DeliveryAttempt | None = None
    delay = 0.0
    async with SessionLocal() as session:
        attempt = await session.get(DeliveryAttempt, attempt_id)
        if attempt is None or attempt.status != DeliveryStatus.pending:
            return
        now = datetime.now(UTC)
        attempt.response_code = response_code
        attempt.error = error
        attempt.latency_ms = latency_ms
        attempt.completed_at = now

        delays = settings.retry_delays
        if error is None:
            attempt.status = DeliveryStatus.succeeded
        elif (
            endpoint.active
            and should_retry(response_code)
            and attempt.attempt_no < max_attempts(delays)
        ):
            attempt.status = DeliveryStatus.failed
            delay = retry_delay(attempt.attempt_no, delays)
            # The retry is its own row, so every attempt stays in the history.
            retry = DeliveryAttempt(
                event_id=attempt.event_id,
                endpoint_id=attempt.endpoint_id,
                attempt_no=attempt.attempt_no + 1,
                next_retry_at=now + timedelta(seconds=delay),
            )
            session.add(retry)
        else:
            attempt.status = DeliveryStatus.dead
        await session.commit()

    if retry is not None:
        # A deferred job: arq holds it in Redis and runs it once `delay` seconds have passed.
        await enqueue_delivery(arq, retry.id, defer_by=delay)

    log.info(
        "attempt %s (#%d) for event %s -> %s (%s, %d ms)%s",
        attempt_id,
        attempt.attempt_no,
        event.id,
        attempt.status,
        response_code or error,
        latency_ms,
        f", retry in {delay:.1f}s" if retry else "",
    )


async def requeue_stuck_attempts(arq: ArqRedis) -> int:
    """Safety net: enqueue pending attempts that are overdue but have no job.

    That happens if Redis was unreachable just after a row was committed, or if Redis lost its
    data. Re-enqueueing one that does have a job is harmless (same job id, so arq ignores it).
    """
    grace = datetime.now(UTC) - timedelta(minutes=1)
    async with SessionLocal() as session:
        ids = await session.scalars(
            select(DeliveryAttempt.id)
            .where(
                DeliveryAttempt.status == DeliveryStatus.pending,
                func.coalesce(DeliveryAttempt.next_retry_at, DeliveryAttempt.created_at) < grace,
            )
            .limit(1000)
        )
        ids = list(ids)
    for attempt_id in ids:
        await enqueue_delivery(arq, attempt_id)
    if ids:
        log.warning("re-enqueued %d overdue pending attempts", len(ids))
    return len(ids)
