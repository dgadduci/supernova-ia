"""Configuration tests for the ``abuse_guard.config`` module."""

from __future__ import annotations

import os

import pytest

from abuse_guard.config import (
    ConfigError,
    GuardConfig,
    is_valid_email,
    load_config,
    normalize_email,
    normalize_remote_ip,
)


def _full_env(**overrides: str) -> dict[str, str]:
    env = {
        "REDIS_URL": "redis://localhost:6379/0",
        "ABUSE_GUARD_TOKEN": "guard-test-token-123456",
        "ABUSE_GUARD_HASH_SECRET": "guard-hash-secret-abcdef",
    }
    env.update(overrides)
    return env


def test_load_config_with_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in _full_env().items():
        monkeypatch.setenv(key, value)
    for name in (
        "ABUSE_EMAIL_WINDOW_SECONDS",
        "ABUSE_EMAIL_MAX",
        "ABUSE_IP_WINDOW_SECONDS",
        "ABUSE_IP_MAX",
        "ABUSE_PAIR_WINDOW_SECONDS",
        "ABUSE_PAIR_MAX",
        "PORT",
    ):
        monkeypatch.delenv(name, raising=False)
    config = load_config()
    assert config.email_window_seconds == 60
    assert config.email_max == 1
    assert config.ip_window_seconds == 900
    assert config.ip_max == 5
    assert config.pair_window_seconds == 3600
    assert config.pair_max == 3
    assert config.port == 8000


def test_load_config_from_explicit_mapping() -> None:
    config = load_config(_full_env())
    assert isinstance(config, GuardConfig)
    assert config.bearer_token == "guard-test-token-123456"


def test_missing_redis_url_raises() -> None:
    env = _full_env()
    env.pop("REDIS_URL")
    with pytest.raises(ConfigError) as exc:
        load_config(env)
    assert exc.value.code == "missing:REDIS_URL"


def test_blank_token_raises() -> None:
    env = _full_env(ABUSE_GUARD_TOKEN="   ")
    with pytest.raises(ConfigError) as exc:
        load_config(env)
    assert exc.value.code == "missing:ABUSE_GUARD_TOKEN"


def test_short_token_raises() -> None:
    env = _full_env(ABUSE_GUARD_TOKEN="short")
    with pytest.raises(ConfigError) as exc:
        load_config(env)
    assert exc.value.code == "invalid:ABUSE_GUARD_TOKEN"


def test_invalid_integer_raises() -> None:
    env = _full_env(ABUSE_EMAIL_MAX="not-a-number")
    with pytest.raises(ConfigError) as exc:
        load_config(env)
    assert exc.value.code == "invalid:ABUSE_EMAIL_MAX"


def test_negative_limit_raises() -> None:
    env = _full_env(ABUSE_EMAIL_MAX="0")
    with pytest.raises(ConfigError) as exc:
        load_config(env)
    assert exc.value.code == "out_of_range:ABUSE_EMAIL_MAX"


def test_out_of_range_window_raises() -> None:
    env = _full_env(ABUSE_EMAIL_WINDOW_SECONDS="1000000")
    with pytest.raises(ConfigError) as exc:
        load_config(env)
    assert exc.value.code == "out_of_range:ABUSE_EMAIL_WINDOW_SECONDS"


def test_invalid_port_raises() -> None:
    env = _full_env(PORT="not-a-port")
    with pytest.raises(ConfigError) as exc:
        load_config(env)
    assert exc.value.code == "invalid:PORT"


def test_out_of_range_port_raises() -> None:
    env = _full_env(PORT="70000")
    with pytest.raises(ConfigError) as exc:
        load_config(env)
    assert exc.value.code == "out_of_range:PORT"


def test_is_valid_email_accepts_canonical() -> None:
    assert is_valid_email("Owner@Example.com") is True
    assert is_valid_email("user.name+tag@sub.example.co") is True


def test_is_valid_email_rejects_invalid() -> None:
    for value in [None, "", "   ", "missing-at", "a@", "@b.com", "a@b", "a b@c.com"]:
        assert is_valid_email(value) is False, value


def test_normalize_email_trims_and_lowers() -> None:
    assert normalize_email("  Owner@Example.COM  ") == "owner@example.com"


def test_normalize_remote_ip_returns_none_or_stripped() -> None:
    assert normalize_remote_ip(None) is None
    assert normalize_remote_ip(12345) is None
    assert normalize_remote_ip("") is None
    assert normalize_remote_ip("   ") is None
    assert normalize_remote_ip(" 203.0.113.10 ") == "203.0.113.10"
    assert normalize_remote_ip("a b") is None
    assert normalize_remote_ip("x" * 200) is None


def test_load_config_restores_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "REDIS_URL",
        "ABUSE_GUARD_TOKEN",
        "ABUSE_GUARD_HASH_SECRET",
        "ABUSE_EMAIL_MAX",
        "PORT",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("REDIS_URL", "original-redis")
    env = _full_env(ABUSE_EMAIL_MAX="3")
    load_config(env)
    assert os.environ.get("REDIS_URL") == "original-redis"
    assert os.environ.get("ABUSE_EMAIL_MAX") is None
