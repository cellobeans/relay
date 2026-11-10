# Relay — instructions for Claude Code

## What this project is
Relay is a webhook delivery service. Tenants register HTTP endpoints, send events to Relay, and Relay delivers each event to every matching endpoint. Deliveries are HMAC-signed, retried with exponential backoff, and moved to a dead-letter state after the last attempt. Dead events can be replayed.

This is a portfolio project for backend SDE job applications. The owner (Tanush) is new to backend development. He must be able to **explain every file and every design decision in an interview**, so understanding matters more than speed or cleverness.

## How to work with me
- **One milestone at a time.** PLAN.md lists the milestones. Do only the milestone I name, then stop. Never start the next one without being asked.
- **Prefer simple code.** Pick the boring, readable option. No abstractions "for later", no extra features, no frameworks beyond the stack below. If something non-obvious is needed, add a one-line comment saying *why*.
- **After each milestone, give me a short report in this format:**
  1. **What we built.** 3–5 plain-English sentences, no jargon left unexplained.
  2. **File tour.** One line per new or changed file saying what it's for.
  3. **Design decisions.** Each choice we made, the alternative, and why we went this way.
  4. **How to see it working.** Exact commands or curl calls I can run myself.
  5. **Quiz me.** Ask 3 interview-style questions about this milestone. Wait for my answers, then correct or deepen them. Don't give the answers first.
- **Before writing code for a milestone, briefly explain the concept** (e.g., what an idempotency key is) in under 10 lines, then build.
- **Commit at the end of each milestone** with a conventional message (`feat: ...`, `test: ...`, `chore: ...`). Don't push unless I ask.
- If a command fails, explain the error in plain words before fixing it.
- Never commit secrets. Config comes from environment variables (`.env` locally, gitignored; `.env.example` committed).

## Stack (don't add to this without asking)
- Python 3.12, dependencies managed with `uv`
- FastAPI, Pydantic v2
- PostgreSQL 16, SQLAlchemy 2.0 (async, asyncpg), Alembic for migrations
- Redis 7, `arq` for background jobs
- `httpx` for outbound HTTP
- pytest, pytest-asyncio, httpx AsyncClient for tests
- ruff for lint and format
- Docker + Docker Compose for local running; GitHub Actions for CI
- k6 for load testing

## Layout
```
app/
  main.py            # FastAPI app, router registration
  config.py          # settings from env (pydantic-settings)
  db.py              # async engine + session dependency
  models.py          # SQLAlchemy models
  schemas.py         # Pydantic request/response models
  auth.py            # API key + admin token dependencies
  routers/           # tenants.py, endpoints.py, events.py, health.py
  services/          # signing.py, backoff.py, delivery.py
  worker.py          # arq WorkerSettings + delivery job
receiver/            # tiny mock receiver that verifies signatures and fails X% of requests
migrations/          # alembic
tests/
loadtest/            # k6 scripts
docker-compose.yml
Dockerfile
```

## Conventions
- All timestamps are UTC (`timestamptz`).
- IDs are UUIDs.
- API keys: shown to the user once; store only a SHA-256 hash.
- HTTP errors use FastAPI `HTTPException` with clear `detail` messages.
- Every DB schema change goes through an Alembic migration. Never `create_all` in app code.

## Useful commands (keep this section up to date as the project grows)
- `cp .env.example .env`: one-time setup, then set a real `POSTGRES_PASSWORD` (and the same one in `DATABASE_URL`)
- `docker compose up --build`: run everything
- `curl localhost:8000/healthz`: check the API can reach Postgres and Redis
- `docker compose logs -f api worker`: follow logs
- `docker compose down`: stop everything (add `-v` to also wipe the database)
- `docker compose up --build -d --wait`: rebuild after code changes (the image copies the code, so edits need a rebuild)
- `uv run alembic revision --autogenerate -m "<what changed>"`: write a migration from model changes (runs on the Mac so the file lands in the repo; read it before applying)
- `docker compose exec api alembic upgrade head`: apply migrations
- `./scripts/demo_setup.sh`: create a demo tenant + endpoint pointing at the mock receiver (API key goes to `.demo.env`)
- `FAIL_RATE=50 docker compose up -d --no-deps receiver`: make the mock receiver fail 50% of requests
- `RETRY_DELAYS='[1,2,3,4]' docker compose up -d`: retry after seconds instead of minutes (for demos)
- `uv run pytest`: run tests
- `uv run ruff check . && uv run ruff format .`: lint and format
