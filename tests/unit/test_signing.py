"""Unit tests: pure functions, no database or network."""

from app.services.signing import sign, verify

SECRET = "whsec_test"
TS = 1_700_000_000
BODY = b'{"order_id":1}'


def test_sign_matches_reference_value():
    # Computed independently with: printf '1700000000.{"order_id":1}' |
    #   openssl dgst -sha256 -hmac whsec_test
    # Pins the exact message format "{timestamp}.{body}" that receivers rely on.
    assert sign(SECRET, TS, BODY) == (
        "393a834ff737d8a5ef182be00b6558b278e4629fba58ecc59b60966bdff183a9"
    )


def test_verify_accepts_valid_signature():
    assert verify(SECRET, TS, BODY, sign(SECRET, TS, BODY), now=TS)


def test_verify_accepts_timestamp_as_header_string():
    assert verify(SECRET, str(TS), BODY, sign(SECRET, TS, BODY), now=TS)


def test_verify_rejects_tampered_body():
    signature = sign(SECRET, TS, BODY)
    assert not verify(SECRET, TS, b'{"order_id":2}', signature, now=TS)


def test_verify_rejects_wrong_secret():
    signature = sign("someone-elses-secret", TS, BODY)
    assert not verify(SECRET, TS, BODY, signature, now=TS)


def test_verify_rejects_changed_timestamp():
    # An attacker can't refresh an old request's timestamp: it's part of what was signed.
    signature = sign(SECRET, TS, BODY)
    assert not verify(SECRET, TS + 60, BODY, signature, now=TS + 60)


def test_verify_window_is_five_minutes():
    signature = sign(SECRET, TS, BODY)
    assert verify(SECRET, TS, BODY, signature, now=TS + 299)
    assert not verify(SECRET, TS, BODY, signature, now=TS + 301)  # replayed too late
    assert not verify(SECRET, TS, BODY, signature, now=TS - 301)  # dated in the future


def test_verify_rejects_garbage_timestamp():
    assert not verify(SECRET, "not-a-number", BODY, sign(SECRET, TS, BODY), now=TS)
