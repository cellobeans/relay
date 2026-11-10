"""HMAC-SHA256 webhook signatures. Pure functions: no database, no network, easy to test.

The signed message is "{timestamp}.{raw_body}". Including the timestamp means an attacker can't
change it without breaking the signature, so receivers can safely reject old requests.
"""

import hashlib
import hmac
import time

DEFAULT_TOLERANCE_SECONDS = 5 * 60


def sign(secret: str, timestamp: int, body: bytes) -> str:
    message = f"{timestamp}.".encode() + body
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def verify(
    secret: str,
    timestamp: str | int,
    body: bytes,
    signature: str,
    tolerance_seconds: int = DEFAULT_TOLERANCE_SECONDS,
    now: float | None = None,
) -> bool:
    """True only if the signature matches AND the timestamp is within the tolerance window."""
    try:
        ts = int(timestamp)
    except (TypeError, ValueError):
        return False

    now = time.time() if now is None else now
    # Reject old timestamps (replays) and far-future ones (clock games) alike.
    if abs(now - ts) > tolerance_seconds:
        return False

    # Constant-time comparison so response timing doesn't leak how many characters matched.
    return hmac.compare_digest(sign(secret, ts, body), signature)
