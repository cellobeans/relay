"""Retry policy as pure functions: no database, no clock, no network, so they're easy to test."""

import random
from collections.abc import Callable, Sequence

JITTER = 0.2  # each delay is randomised by up to ±20%


def should_retry(status_code: int | None) -> bool:
    """Is this failure worth retrying?

    None means no HTTP response at all (timeout, connection refused, DNS error): the receiver
    may be briefly down, so retry. 5xx means the receiver's server broke; 429 means "slow down".
    Other 4xx (400, 401, 404...) mean our request itself is rejected, and sending the exact same
    request again would get the same answer, so we don't retry those.
    """
    if status_code is None:
        return True
    return status_code == 429 or status_code >= 500


def max_attempts(delays: Sequence[float]) -> int:
    """One first try, plus one retry per configured delay."""
    return len(delays) + 1


def retry_delay(
    attempt_no: int,
    delays: Sequence[float],
    rand: Callable[[], float] = random.random,
) -> float:
    """Seconds to wait after attempt number `attempt_no` (1-based) fails.

    Jitter spreads out retries: without it, every delivery that failed during the same outage
    would retry at the same instant and hit the recovering receiver all at once.
    `rand` is a parameter so tests can pass a fixed value instead of real randomness.
    """
    base = delays[attempt_no - 1]
    return base * (1 - JITTER + 2 * JITTER * rand())
