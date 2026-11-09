from contextlib import asynccontextmanager

from fastapi import FastAPI
from redis.asyncio import Redis

from app.config import settings
from app.db import engine
from app.routers import endpoints, health, tenants


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Runs once at startup: open one shared Redis client for the whole app.
    app.state.redis = Redis.from_url(settings.redis_url)
    yield
    # Runs once at shutdown: close connections cleanly.
    await app.state.redis.aclose()
    await engine.dispose()


app = FastAPI(title="Relay", lifespan=lifespan)
app.include_router(health.router)
app.include_router(tenants.router)
app.include_router(endpoints.router)
