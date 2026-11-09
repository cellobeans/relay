# Relay — build plan (Claude Code)

**Goal:** a working, tested webhook delivery service on GitHub within about a week, which Tanush can explain end to end.

**How to use this file**
1. Create an empty repo folder, put `CLAUDE.md` and `PLAN.md` in it, run `git init`, open Claude Code there.
2. For each milestone, paste the **Prompt** into Claude Code.
3. Check the **Done when** items yourself. Don't take Claude's word for it; run the commands.
4. Answer the quiz Claude asks at the end of each milestone *before* moving on. If you can't answer, ask it to explain again.
5. Tick the milestone off here and commit.

**Before you start (Mac):** install Docker Desktop, `uv` (`brew install uv`), and k6 (`brew install k6`).

---

## M0 — Scaffold (≈1 hr)

**Prompt**
> Read CLAUDE.md and PLAN.md. Do milestone M0 only: scaffold the project with the layout in CLAUDE.md. Set up uv with the stack's dependencies, a Dockerfile for the app, and docker-compose.yml with services `api`, `worker`, `postgres`, `redis`, and `receiver` (receiver can be a placeholder for now). Add config via pydantic-settings, an async SQLAlchemy session, Alembic configured for async, ruff, `.env.example`, `.gitignore`, and a `GET /healthz` that checks both Postgres and Redis. Before coding, explain in under 10 lines what each compose service is for.

**Done when**
- [ ] `docker compose up --build` starts all services without errors
- [ ] `curl localhost:8000/healthz` returns OK with DB and Redis both reachable
- [ ] You can explain why the API and the worker are separate processes

---

## M1 — Tenants, API keys, endpoints (≈1.5 hrs)

**Prompt**
> Do milestone M1 only. Add models + an Alembic migration for `tenants` (id, name, api_key_hash, created_at) and `endpoints` (id, tenant_id, url, secret, event_types as a text array, active, created_at). Add `POST /admin/tenants`, protected by an `ADMIN_TOKEN` env var, that creates a tenant and returns its API key exactly once. Add an API-key auth dependency (`Authorization: Bearer <key>`, compared by SHA-256 hash). Add tenant-scoped CRUD for endpoints: create (generates a signing secret, returned once), list, get, deactivate. A tenant must never see another tenant's endpoints. First explain how API-key hashing works and why we never store the raw key.

**Done when**
- [ ] You can create a tenant, then create and list endpoints with its key using curl
- [ ] A wrong key gets 401; tenant B can't read tenant A's endpoint (404)
- [ ] You can explain why the key is hashed and what "tenant-scoped" means in the queries

---

## M2 — Event ingestion with idempotency (≈1.5 hrs)

**Prompt**
> Do milestone M2 only. Add `events` (id, tenant_id, type, payload jsonb, idempotency_key, created_at) with a unique constraint on (tenant_id, idempotency_key), and `delivery_attempts` (id, event_id, endpoint_id, attempt_no, status [pending/succeeded/failed/dead], response_code, error, latency_ms, next_retry_at, created_at). Add `POST /events` requiring an `Idempotency-Key` header: a repeated key returns the original event with 200 instead of creating a duplicate (201 for new). On a new event, create one pending delivery row per active endpoint subscribed to that event type. Don't enqueue jobs yet. Add `GET /events/{id}` showing the event and its deliveries. Explain idempotency and why the DB constraint, not application code, guarantees it.

**Done when**
- [ ] Posting the same event twice with the same key creates one row
- [ ] Deliveries are created only for endpoints subscribed to that event type
- [ ] You can explain what goes wrong under concurrent requests if you only check "does it exist?" in code

---

## M3 — Worker, signed delivery, mock receiver (≈2 hrs)

**Prompt**
> Do milestone M3 only. After creating delivery rows in `POST /events`, enqueue one arq job per delivery. The worker job loads the delivery, POSTs the event payload to the endpoint URL with httpx (10s timeout) and headers `X-Relay-Timestamp` and `X-Relay-Signature` = hex HMAC-SHA256 of `"{timestamp}.{raw_body}"` using the endpoint secret. Record status, response code, and latency. Put signing in `services/signing.py` with both `sign()` and `verify()` (constant-time comparison). Build `receiver/` as a tiny FastAPI app that verifies the signature, rejects timestamps older than 5 minutes, and fails a configurable percentage of requests via an env var (`FAIL_RATE`). For now, failures are just recorded as `failed`; no retries yet. Explain HMAC signing and how the timestamp prevents replay attacks.

**Done when**
- [ ] An event posted to Relay shows up in the receiver's logs with a valid signature
- [ ] Tampering with the body makes the receiver reject it
- [ ] You can explain the full flow from `POST /events` to the receiver, out loud, without notes

---

## M4 — Retries, backoff, dead-letter, replay (≈2 hrs)

**Prompt**
> Do milestone M4 only. On failure (timeout, connection error, 5xx, or 429), schedule a retry with exponential backoff plus jitter: delays roughly 5s, 30s, 2m, 10m, 1h, max 5 attempts, then mark the delivery `dead`. Don't retry on other 4xx. Put the schedule and the retry decision in `services/backoff.py` as pure functions. Use arq's deferred jobs for scheduling. Record every attempt. Add `POST /events/{id}/replay` that re-enqueues dead deliveries for that event. For local testing, make the backoff delays configurable so they can be seconds instead of minutes. Explain why jitter matters and what at-least-once delivery means for receivers.

**Done when**
- [ ] With `FAIL_RATE=50`, you see deliveries retry and some eventually succeed
- [ ] With `FAIL_RATE=100`, deliveries end up `dead`, and replay sends them again
- [ ] You can explain what happens if the worker crashes mid-delivery

---

## M5 — Tests + CI (≈1.5 hrs)

**Prompt**
> Do milestone M5 only. Write unit tests for signing (sign/verify, tampered body, old timestamp), backoff (schedule, retry classification), and integration tests against real Postgres and Redis: auth rejection, tenant isolation, idempotent ingestion, and an end-to-end delivery to a stubbed receiver. Add a GitHub Actions workflow that runs ruff and pytest with Postgres and Redis as service containers, and builds the Docker image. Explain the difference between the unit and integration tests you wrote.

**Done when**
- [ ] `uv run pytest` passes locally
- [ ] CI is green on GitHub
- [ ] You can explain why integration tests use a real database instead of mocks

---

## M6 — Load test + README (≈2 hrs)

**Prompt**
> Do milestone M6 only. Write a k6 script in `loadtest/` that ramps up `POST /events` and reports throughput, p95 ingest latency, and error rate. Add a small script or endpoint query to compute p95 delivery latency from `delivery_attempts`. Help me run it locally and record the results with my machine specs. Then write the README: one-paragraph pitch, Mermaid architecture diagram, quickstart, curl examples, a "Design decisions" section (idempotency, HMAC + timestamp, backoff + jitter, at-least-once, why arq), a load-test results table, and "What's next". Use only the real numbers from my run.

**Done when**
- [ ] You have real numbers: events/sec, p95 ingest, p95 delivery, error rate
- [ ] A stranger could clone the repo and run it in 5 minutes using the README
- [ ] The repo is public and pinned on your GitHub profile

**Optional (only if under 2 hrs):** deploy to Azure Container Apps with Bicep + GitHub Actions OIDC, reusing your FastAPI-on-Azure setup. Shut it down after demos to save credits.

---

## M7 — Interview drill (≈1 hr, do it twice)

**Prompt**
> Act as an interviewer for a backend SDE fresher role. I built this project. Ask me one question at a time about Relay: architecture, each design decision, failure scenarios, scaling to 100× load, database indexes, and what I'd change. Push back when my answers are vague. At the end, list my weakest areas and what to re-read in the code.

**Done when**
- [ ] You can answer these without notes:
  - Why at-least-once and not exactly-once? How should receivers handle duplicates?
  - What happens if the worker crashes mid-delivery?
  - Why is idempotency enforced by a DB constraint?
  - How do HMAC + timestamp stop spoofed and replayed requests?
  - Why jitter in backoff?
  - Which indexes exist, and what breaks first at 100× load?

---

## Resume bullet (fill in your numbers after M6)

> **Relay — Webhook Delivery Service** · Python, FastAPI, PostgreSQL, Redis, Docker, GitHub Actions · [GitHub link]
> - Built a multi-tenant webhook delivery service with HMAC-signed payloads, idempotent event ingestion, and exponential-backoff retries with a dead-letter queue and replay.
> - Sustained __ events/sec at p95 delivery latency of __ ms in k6 load tests; CI runs unit and integration tests against real Postgres and Redis.

After this, add PostgreSQL, Redis, and Docker to your skills line. You can now explain them.
