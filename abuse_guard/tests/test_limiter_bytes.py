"""Tests for the limiter's response parser with real-Redis payloads.

``redis.Redis`` with ``decode_responses=False`` returns Lua arrays of
``bytes`` for string fields and ``int`` for numeric fields. The
limiter must accept that shape, decode the bounded string fields as
UTF-8 and reject anything that is not the documented shape so a
permissive response cannot bypass the gate.
"""

from __future__ import annotations

from typing import Any

import pytest

from abuse_guard.config import GuardConfig
from abuse_guard.limiter import (
    DecisionOutcome,
    LimiterError,
    RedisLimiter,
    _decode_bounded_string,
    ping,
)


class BytesRedis:
    """Stub that mirrors the ``decode_responses=False`` Redis wire format."""

    def __init__(self, payload: list[Any] | None = None) -> None:
        self._payload = payload
        self._fail_next = False
        self._always_fail = False
        self.scripts: list[str] = []

    def fail_next(self) -> None:
        self._fail_next = True

    def always_fail(self) -> None:
        self._always_fail = True

    def eval(
        self,
        script: str,
        numkeys: int,
        *keys_and_args: Any,
    ):
        self.scripts.append(script)
        if self._always_fail:
            raise RuntimeError("redis offline")
        if self._fail_next:
            self._fail_next = False
            raise RuntimeError("simulated redis failure")
        if "PING" in script:
            return b"PONG"
        if self._payload is None:
            raise RuntimeError("no payload configured")
        return self._payload


def _config() -> GuardConfig:
    return GuardConfig(
        redis_url="redis://localhost:6379/0",
        bearer_token="test-token-123456",
        hash_secret="test-hash-secret",
        email_window_seconds=60,
        email_max=1,
        ip_window_seconds=900,
        ip_max=5,
        pair_window_seconds=3600,
        pair_max=3,
        port=8000,
    )


def test_decode_bounded_string_accepts_bytes() -> None:
    assert _decode_bounded_string(b"allowed", limit=16) == "allowed"
    assert _decode_bounded_string("denied", limit=16) == "denied"
    assert _decode_bounded_string(b"", limit=16) == ""


def test_decode_bounded_string_rejects_oversized_bytes() -> None:
    with pytest.raises(LimiterError):
        _decode_bounded_string(b"a" * 17, limit=16)


def test_decode_bounded_string_rejects_invalid_utf8() -> None:
    with pytest.raises(LimiterError):
        _decode_bounded_string(b"\xff\xfe", limit=16)


def test_decode_bounded_string_rejects_unsupported_types() -> None:
    for value in (None, 1, 1.5, [], {"k": "v"}, object()):
        with pytest.raises(LimiterError):
            _decode_bounded_string(value, limit=16)


def test_limiter_accepts_realistic_bytes_payload_on_allow() -> None:
    redis = BytesRedis(payload=[b"allowed", b"", 1, 60])
    limiter = RedisLimiter(client=redis, config=_config())
    outcome = limiter.check(raw_email="owner@example.com", raw_ip="203.0.113.10")
    assert outcome == DecisionOutcome(
        allowed=True, reason="", email_count=1, count_ttl=60
    )


def test_limiter_accepts_realistic_bytes_payload_on_deny() -> None:
    redis = BytesRedis(payload=[b"denied", b"email", 2, 30])
    limiter = RedisLimiter(client=redis, config=_config())
    outcome = limiter.check(raw_email="owner@example.com", raw_ip="203.0.113.10")
    assert outcome == DecisionOutcome(
        allowed=False, reason="email", email_count=2, count_ttl=30
    )


def test_limiter_accepts_decoded_responses_when_already_strings() -> None:
    redis = BytesRedis(payload=["allowed", "", 1, 60])
    limiter = RedisLimiter(client=redis, config=_config())
    outcome = limiter.check(raw_email="owner@example.com", raw_ip="203.0.113.10")
    assert outcome.allowed is True


def test_limiter_rejects_unknown_decision_bytes() -> None:
    redis = BytesRedis(payload=[b"unknown", b"", 1, 60])
    limiter = RedisLimiter(client=redis, config=_config())
    with pytest.raises(LimiterError):
        limiter.check(raw_email="owner@example.com", raw_ip="203.0.113.10")


def test_limiter_rejects_unknown_reason_bytes() -> None:
    redis = BytesRedis(payload=[b"denied", b"bogus", 2, 30])
    limiter = RedisLimiter(client=redis, config=_config())
    with pytest.raises(LimiterError):
        limiter.check(raw_email="owner@example.com", raw_ip="203.0.113.10")


def test_limiter_rejects_pair_reason_when_no_ip() -> None:
    redis = BytesRedis(payload=[b"denied", b"pair", 2, 60])
    limiter = RedisLimiter(client=redis, config=_config())
    with pytest.raises(LimiterError):
        limiter.check(raw_email="owner@example.com", raw_ip=None)


def test_limiter_rejects_short_array() -> None:
    redis = BytesRedis(payload=[b"allowed", b"", 1])
    limiter = RedisLimiter(client=redis, config=_config())
    with pytest.raises(LimiterError):
        limiter.check(raw_email="owner@example.com", raw_ip="203.0.113.10")


def test_limiter_rejects_negative_count_bytes() -> None:
    redis = BytesRedis(payload=[b"allowed", b"", -1, 60])
    limiter = RedisLimiter(client=redis, config=_config())
    with pytest.raises(LimiterError):
        limiter.check(raw_email="owner@example.com", raw_ip="203.0.113.10")


def test_limiter_rejects_oversized_decision_bytes() -> None:
    redis = BytesRedis(payload=[b"a" * 17, b"", 1, 60])
    limiter = RedisLimiter(client=redis, config=_config())
    with pytest.raises(LimiterError):
        limiter.check(raw_email="owner@example.com", raw_ip="203.0.113.10")


def test_limiter_rejects_decision_as_int() -> None:
    redis = BytesRedis(payload=[1, b"", 1, 60])
    limiter = RedisLimiter(client=redis, config=_config())
    with pytest.raises(LimiterError):
        limiter.check(raw_email="owner@example.com", raw_ip="203.0.113.10")


def test_limiter_raises_redis_unavailable_on_bytes_exception() -> None:
    redis = BytesRedis()
    redis.always_fail()
    limiter = RedisLimiter(client=redis, config=_config())
    with pytest.raises(LimiterError) as exc:
        limiter.check(raw_email="owner@example.com", raw_ip="203.0.113.10")
    assert exc.value.code == "redis_unavailable"


def test_ping_accepts_bytes_response() -> None:
    redis = BytesRedis(payload=None)
    assert ping(redis) is True


def test_ping_accepts_string_response() -> None:
    class StringRedis:
        def eval(self, script, numkeys, *keys_and_args):
            return "PONG"

    assert ping(StringRedis()) is True


def test_ping_rejects_unknown_payload() -> None:
    class OtherRedis:
        def eval(self, script, numkeys, *keys_and_args):
            return 1

    assert ping(OtherRedis()) is False


def test_ping_raises_limiter_error_on_redis_failure() -> None:
    redis = BytesRedis()
    redis.always_fail()
    with pytest.raises(LimiterError) as exc:
        ping(redis)
    assert exc.value.code == "redis_unavailable"
