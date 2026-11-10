"""Shared test setup: a real Postgres database and Redis, both separate from your dev data.

- Database: `relay_test` on the same Postgres server (dropped and rebuilt with Alembic migrations
  at the start of every run, so the migrations themselves are tested too).
- Redis: database 15 (dev uses 0).
In CI, TEST_DATABASE_URL and TEST_REDIS_URL are set by the workflow. Locally they're derived
from your .env, so the compose stack must be running (`docker compose up -d postgres redis`).
"""

import asyncio
import os
from pathlib import Path

import asyncpg
import pytest
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[2]


def _dev_database_url() -> str:
    for line in (ROOT / ".env").read_text().splitlines():
        if line.startswith("DATABASE_URL="):
            return line.split("=", 1)[1]
    raise RuntimeError("Set TEST_DATABASE_URL or add DATABASE_URL to .env")


TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL") or str(
    make_url(_dev_database_url()).set(database="relay_test").render_as_string(hide_password=False)
)
# Guard rail: the tests empty every table, so refuse to run against anything but a test DB.
assert make_url(TEST_DATABASE_URL).database.endswith("_test"), "tests need a *_test database"

# Settings are read when app.config is first imported, so these must be set before that.
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ["REDIS_URL"] = os.environ.get("TEST_REDIS_URL", "redis://localhost:6379/15")
os.environ["ADMIN_TOKEN"] = "test-admin-token"
os.environ["RETRY_DELAYS"] = "[5, 30, 120, 600]"

import httpx  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from arq import create_pool  # noqa: E402
from arq.connections import RedisSettings  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.config import settings  # noqa: E402
from app.db import engine  # noqa: E402
from app.main import app  # noqa: E402


async def _recreate_test_database() -> None:
    url = make_url(TEST_DATABASE_URL)
    conn = await asyncpg.connect(
        user=url.username, password=url.password, host=url.host, port=url.port, database="postgres"
    )
    try:
        await conn.execute(f'DROP DATABASE IF EXISTS "{url.database}" WITH (FORCE)')
        await conn.execute(f'CREATE DATABASE "{url.database}"')
    finally:
        await conn.close()


@pytest.fixture(scope="session", autouse=True)
def database_schema():
    """Once per run: fresh test database, built by running every migration (never create_all)."""
    asyncio.run(_recreate_test_database())
    command.upgrade(Config(str(ROOT / "alembic.ini")), "head")


@pytest.fixture
async def arq():
    pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    yield pool
    await pool.aclose()


@pytest.fixture(autouse=True)
async def clean_state(arq):
    """Every test starts with empty tables and an empty Redis database."""
    async with engine.begin() as conn:
        await conn.execute(
            text("TRUNCATE tenants, endpoints, events, delivery_attempts RESTART IDENTITY CASCADE")
        )
    await arq.flushdb()
    yield


@pytest.fixture
async def client():
    """An HTTP client that calls the FastAPI app in-process (no server), with startup run."""
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://relay.test") as c:
            yield c
