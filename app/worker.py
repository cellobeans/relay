import logging
import uuid

import httpx
from arq import cron
from arq.connections import RedisSettings

from app.config import settings
from app.services import delivery

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


async def startup(ctx: dict) -> None:
    # One shared HTTP client: it reuses TCP connections between deliveries to the same host.
    ctx["http"] = httpx.AsyncClient(timeout=10.0)


async def shutdown(ctx: dict) -> None:
    await ctx["http"].aclose()


async def deliver(ctx: dict, attempt_id: str) -> None:
    # ctx["redis"] is arq's own Redis pool, used to schedule a retry if this attempt fails.
    await delivery.deliver_attempt(uuid.UUID(attempt_id), ctx["http"], ctx["redis"])


async def requeue_stuck(ctx: dict) -> None:
    await delivery.requeue_stuck_attempts(ctx["redis"])


class WorkerSettings:
    """arq reads this class: which jobs exist and which Redis to pull them from."""

    functions = [deliver]
    # Every minute (unique=True by default: with several workers, only one runs each tick).
    cron_jobs = [cron(requeue_stuck, second=0)]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    # Deliveries spend nearly all their time waiting on the network, so one process can
    # usefully run many at once (asyncio switches between them while each one waits).
    max_jobs = 50
    # Don't keep job results in Redis. The database is the record of what happened, and a kept
    # result would block requeue_stuck from re-enqueueing that job id for an hour.
    keep_result = 0
