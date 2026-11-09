import logging

from fastapi import FastAPI, Request

# Placeholder mock receiver. In M3 it will verify signatures and fail FAIL_RATE% of requests.
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("receiver")

app = FastAPI(title="Relay mock receiver")


@app.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok"}


@app.post("/webhook")
async def webhook(request: Request) -> dict:
    body = await request.body()
    log.info("received %d bytes: %s", len(body), body[:200])
    return {"received": True}
