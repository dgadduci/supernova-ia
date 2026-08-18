"""Limiter unit tests for hashing, TTL, atomicity and Redis failure."""

from __future__ import annotations

import threading

import pytest

from abuse_guard.config import (
    normalize_email,
    normalize_remote_ip,
)
from abuse_guard.limiter import (
    KEY_PREFIX,
    LimiterError,
    RedisLimiter,
    build_keys,
    ping,
)
from abuse_guard.tests.conftest import FakeRedis, _build_config


def _limiter(fake_redis: FakeRedis, **overrides: object) -> RedisLimiter:
    config = _build_config(**overrides)  # type: ignore[arg-type]
    return RedisLimiter(client=fake_redis, config=config)


def test_keys_are_hashed_and_prefixed() -> None:
    email_key, ip_key, pair_key = build_keys(
        raw_email="owner@example.com",
        raw_ip="203.0.113.10",
        hash_secret="secret-abc",
    )
    assert email_key.startswith(f"{KEY_PREFIX}:email:")
    assert ip_key is not None and ip_key.startswith(f"{KEY_PREFIX}:ip:")
    assert pair_key is not None and pair_key.startswith(f"{KEY_PREFIX}:pair:")
    # Raw identifiers should not appear in the key material.
    for key in (email_key, ip_key, pair_key):
        assert "owner" not in key
        assert "example.com" not in key
        assert "203.0.113.10" not in key


def test_keys_change_when_hash_secret_changes() -> None:
    email_a, _, _ = build_keys(
        raw_email="owner@example.com",
        raw_ip=None,
        hash_secret="secret-a",
    )
    email_b, _, _ = build_keys(
        raw_email="owner@example.com",
        raw_ip=None,
        hash_secret="secret-b",
    )
    assert email_a != email_b


def test_keys_normalize_email_case_and_whitespace() -> None:
    key_a, _, _ = build_keys(
        raw_email=normalize_email("  Owner@Example.com  "),
        raw_ip=None,
        hash_secret="secret",
    )
    key_b, _, _ = build_keys(
        raw_email=normalize_email("owner@example.com"),
        raw_ip=None,
        hash_secret="secret",
    )
    assert key_a == key_b


def test_keys_with_no_ip_omit_ip_and_pair() -> None:
    email_key, ip_key, pair_key = build_keys(
        raw_email="owner@example.com",
        raw_ip=None,
        hash_secret="secret",
    )
    assert ip_key is None
    assert pair_key is None
    assert email_key.startswith(f"{KEY_PREFIX}:email:")


def test_keys_with_non_string_ip_omit_ip_and_pair() -> None:
    email_key, ip_key, pair_key = build_keys(
        raw_email="owner@example.com",
        raw_ip=normalize_remote_ip("   "),
        hash_secret="secret",
    )
    assert email_key.startswith(f"{KEY_PREFIX}:email:")
    assert ip_key is None
    assert pair_key is None


def test_limiter_returns_allowed_on_first_call(fake_redis: FakeRedis) -> None:
    limiter = _limiter(fake_redis)
    outcome = limiter.check(raw_email="owner@example.com", raw_ip="203.0.113.10")
    assert outcome.allowed is True
    assert outcome.reason == ""


def test_limiter_returns_denied_on_email_repeat(fake_redis: FakeRedis) -> None:
    limiter = _limiter(fake_redis)
    limiter.check(raw_email="owner@example.com", raw_ip="203.0.113.10")
    outcome = limiter.check(raw_email="owner@example.com", raw_ip="203.0.113.10")
    assert outcome.allowed is False
    assert outcome.reason == "email"


def test_limiter_returns_denied_on_ip_overflow(fake_redis: FakeRedis) -> None:
    limiter = _limiter(fake_redis, ip_max=2)
    for index in range(2):
        outcome = limiter.check(
            raw_email=f"user{index}@example.com",
            raw_ip="203.0.113.10",
        )
        assert outcome.allowed is True
    outcome = limiter.check(
        raw_email="user2@example.com",
        raw_ip="203.0.113.10",
    )
    assert outcome.allowed is False
    assert outcome.reason == "ip"


def test_limiter_returns_denied_on_pair_overflow(fake_redis: FakeRedis) -> None:
    limiter = _limiter(fake_redis, email_max=10, pair_max=2)
    for _ in range(2):
        outcome = limiter.check(
            raw_email="owner@example.com",
            raw_ip="203.0.113.10",
        )
        assert outcome.allowed is True
    outcome = limiter.check(
        raw_email="owner@example.com",
        raw_ip="203.0.113.10",
    )
    assert outcome.allowed is False
    assert outcome.reason == "pair"


def test_limiter_propagates_redis_failure_as_limiter_error(
    fake_redis: FakeRedis,
) -> None:
    limiter = _limiter(fake_redis)
    fake_redis.fail_next()
    with pytest.raises(LimiterError) as exc:
        limiter.check(raw_email="owner@example.com", raw_ip="203.0.113.10")
    assert exc.value.code == "redis_unavailable"


def test_limiter_rejects_malformed_result(fake_redis: FakeRedis) -> None:
    limiter = _limiter(fake_redis)
    fake_redis.force_next_result([1, 2, 3])
    with pytest.raises(LimiterError):
        limiter.check(raw_email="owner@example.com", raw_ip="203.0.113.10")


def test_ping_returns_true_for_pong(fake_redis: FakeRedis) -> None:
    assert ping(fake_redis) is True


def test_ping_raises_when_redis_fails(fake_redis: FakeRedis) -> None:
    fake_redis.fail_next()
    with pytest.raises(LimiterError) as exc:
        ping(fake_redis)
    assert exc.value.code == "redis_unavailable"


def test_atomic_under_concurrent_calls(fake_redis: FakeRedis) -> None:
    limiter = _limiter(fake_redis)
    outcomes: list[bool] = []
    lock = threading.Lock()

    def worker() -> None:
        outcome = limiter.check(
            raw_email="owner@example.com",
            raw_ip="203.0.113.10",
        )
        with lock:
            outcomes.append(outcome.allowed)

    threads = [threading.Thread(target=worker) for _ in range(20)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sum(1 for allowed in outcomes if allowed) == 1
    assert sum(1 for allowed in outcomes if not allowed) == len(outcomes) - 1


def test_ttl_is_stored_on_first_use(fake_redis: FakeRedis) -> None:
    limiter = _limiter(fake_redis, email_window_seconds=60)
    limiter.check(raw_email="owner@example.com", raw_ip="203.0.113.10")
    email_key = build_keys(
        raw_email="owner@example.com",
        raw_ip="203.0.113.10",
        hash_secret="guard-hash-secret-abcdef",
    )[0]
    assert fake_redis._ttls[email_key] == 60


def test_ttl_uses_pair_window(fake_redis: FakeRedis) -> None:
    limiter = _limiter(fake_redis, pair_window_seconds=1234)
    limiter.check(raw_email="owner@example.com", raw_ip="203.0.113.10")
    pair_key = build_keys(
        raw_email="owner@example.com",
        raw_ip="203.0.113.10",
        hash_secret="guard-hash-secret-abcdef",
    )[2]
    assert fake_redis._ttls[pair_key] == 1234


def test_ttl_uses_ip_window(fake_redis: FakeRedis) -> None:
    limiter = _limiter(fake_redis, ip_window_seconds=555)
    limiter.check(raw_email="owner@example.com", raw_ip="203.0.113.10")
    ip_key = build_keys(
        raw_email="owner@example.com",
        raw_ip="203.0.113.10",
        hash_secret="guard-hash-secret-abcdef",
    )[1]
    assert fake_redis._ttls[ip_key] == 555


def test_no_pure_in_memory_fallback() -> None:
    """The limiter must not maintain an in-memory counter."""

    fresh = FakeRedis()
    limiter = _limiter(fresh)
    limiter.check(raw_email="owner@example.com", raw_ip="203.0.113.10")
    # Build a brand-new Redis instance and ensure the limiter sees no
    # carryover state.
    other = FakeRedis()
    other_config = _build_config()
    fresh_limiter = RedisLimiter(client=other, config=other_config)
    outcome = fresh_limiter.check(
        raw_email="owner@example.com",
        raw_ip="203.0.113.10",
    )
    assert outcome.allowed is True
