"""Mock receiver: plays the part of a tenant's server so we can watch Relay deliver.

It does what a careful real receiver should: verify the signature and timestamp before trusting
anything. It can also fail on purpose (FAIL_RATE percent of requests) to exercise retries.
"""

import logging
import os
import random
from typing import Annotated

from fastapi import FastAPI, Header, HTTPException, Request

from app.services.signing import verify

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("receiver")

# The endpoint's signing secret (returned by Relay when the endpoint was created).
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")
FAIL_RATE = float(os.environ.get("FAIL_RATE", "0"))  # 0-100

app = FastAPI(title="Relay mock receiver")


@app.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok", "fail_rate": FAIL_RATE, "secret_configured": bool(WEBHOOK_SECRET)}


@app.post("/webhook")
async def webhook(
    request: Request,
    x_relay_timestamp: Annotated[str | None, Header()] = None,
    x_relay_signature: Annotated[str | None, Header()] = None,
    x_relay_event_id: Annotated[str | None, Header()] = None,
) -> dict:
    body = await request.body()  # the raw bytes, exactly as signed; never re-serialised JSON

    if not WEBHOOK_SECRET:
        raise HTTPException(500, "WEBHOOK_SECRET is not configured on the receiver")
    if not x_relay_timestamp or not x_relay_signature:
        log.warning("rejected: missing signature headers")
        raise HTTPException(401, "Missing X-Relay-Timestamp or X-Relay-Signature")
    if not verify(WEBHOOK_SECRET, x_relay_timestamp, body, x_relay_signature):
        log.warning("rejected event %s: bad signature or stale timestamp", x_relay_event_id)
        raise HTTPException(401, "Invalid signature or timestamp outside the 5 minute window")

    if random.uniform(0, 100) < FAIL_RATE:
        log.info("simulated failure for event %s", x_relay_event_id)
        raise HTTPException(500, "Simulated failure (FAIL_RATE)")

    log.info("verified event %s: %s", x_relay_event_id, body[:200].decode(errors="replace"))
    return {"ok": True}
