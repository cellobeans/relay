from contextlib import asynccontextmanager

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import FastAPI

from app.config import settings
from app.db import engine
from app.routers import endpoints, events, health, tenants


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Runs once at startup: one shared Redis connection pool, used to enqueue jobs (and by
    # /healthz to ping Redis). arq's pool is a regular Redis client with job helpers added.
    app.state.arq = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    yield
    # Runs once at shutdown: close connections cleanly.
    await app.state.arq.aclose()
    await engine.dispose()


app = FastAPI(title="Relay", lifespan=lifespan)
app.include_router(health.router)
app.include_router(tenants.router)
app.include_router(endpoints.router)
app.include_router(events.router)
