"""Unit tests: pure functions, no database or network."""

import pytest

from app.services.backoff import max_attempts, retry_delay, should_retry

DELAYS = [5, 30, 120, 600]


@pytest.mark.parametrize("status_code", [None, 429, 500, 502, 503, 504])
def test_retries_timeouts_server_errors_and_rate_limits(status_code):
    assert should_retry(status_code)


@pytest.mark.parametrize("status_code", [400, 401, 403, 404, 410, 422])
def test_does_not_retry_other_client_errors(status_code):
    assert not should_retry(status_code)


def test_max_attempts_is_first_try_plus_one_per_delay():
    assert max_attempts(DELAYS) == 5


def test_delay_without_jitter_follows_schedule():
    # rand=0.5 lands exactly in the middle of the jitter range, i.e. no jitter.
    assert [retry_delay(n, DELAYS, rand=lambda: 0.5) for n in range(1, 5)] == DELAYS


def test_jitter_stays_within_twenty_percent():
    assert retry_delay(1, DELAYS, rand=lambda: 0.0) == pytest.approx(4.0)  # 5s - 20%
    assert retry_delay(1, DELAYS, rand=lambda: 1.0) == pytest.approx(6.0)  # 5s + 20%
    assert retry_delay(4, DELAYS, rand=lambda: 1.0) == pytest.approx(720.0)  # 600s + 20%


def test_real_jitter_spreads_retries_out():
    delays = {retry_delay(2, DELAYS) for _ in range(50)}
    assert all(24 <= d <= 36 for d in delays)
    assert len(delays) > 40  # nearly all different: retries don't all land at the same instant
