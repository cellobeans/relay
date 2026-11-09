from arq.connections import RedisSettings

from app.config import settings


async def ping(ctx: dict) -> str:
    # Placeholder job: arq refuses to start with zero jobs. Replaced by the delivery job in M3.
    return "pong"


class WorkerSettings:
    """arq reads this class: which jobs exist and which Redis to pull them from."""

    functions = [ping]
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
