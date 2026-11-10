import logging
import uuid

import httpx
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
    await delivery.deliver_attempt(uuid.UUID(attempt_id), ctx["http"])


class WorkerSettings:
    """arq reads this class: which jobs exist and which Redis to pull them from."""

    functions = [deliver]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    # Deliveries spend nearly all their time waiting on the network, so one process can
    # usefully run many at once (asyncio switches between them while each one waits).
    max_jobs = 50
