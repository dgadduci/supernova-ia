"""Shared pytest fixtures for the ``abuse_guard`` test suite.

The fixtures give every test a fail-closed
:class:`abuse_guard.config.GuardConfig`, a deterministic fake Redis
client that evaluates the limiter's Lua script, and a FastAPI
``TestClient`` ready to invoke against the service.

The fake transport mirrors the Lua script directly so the limit
semantics are exercised without any Redis dependency. The fake is
purpose-built: it does not exist in production code and is not
imported by the application module.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from abuse_guard.app import create_app
from abuse_guard.config import GuardConfig
from abuse_guard.limiter import (
    LUA_INCREMENT_AND_CHECK,
    build_keys,
    normalize_email,
    normalize_remote_ip,
)

VALID_TOKEN = "guard-test-token-123456"
VALID_HASH_SECRET = "guard-hash-secret-abcdef"


def _build_config(**overrides: Any) -> GuardConfig:
    base: dict[str, Any] = {
        "redis_url": "redis://localhost:6379/0",
        "bearer_token": VALID_TOKEN,
        "hash_secret": VALID_HASH_SECRET,
        "email_window_seconds": 60,
        "email_max": 1,
        "ip_window_seconds": 900,
        "ip_max": 5,
        "pair_window_seconds": 3600,
        "pair_max": 3,
        "port": 8000,
    }
    base.update(overrides)
    return GuardConfig(**base)


class FakeRedis:
    """Deterministic Redis stub that mirrors the limiter Lua script."""

    def __init__(self) -> None:
        self._counters: dict[str, int] = {}
        self._ttls: dict[str, int] = {}
        self._fail_next = False
        self._forced_result: Any = None
        self._lock = threading.Lock()

    def fail_next(self) -> None:
        self._fail_next = True

    def force_next_result(self, value: Any) -> None:
        self._forced_result = value

    def script_load(self, _script: str) -> str:
        return "fake"

    def keys(self, pattern: str) -> list[bytes]:
        return [key.encode("utf-8") for key in sorted(self._counters) if _match(pattern, key)]

    def ttl(self, key: str) -> int:
        return self._ttls.get(key, -2)

    def get(self, key: str) -> bytes | None:
        value = self._counters.get(key)
        if value is None:
            return None
        return str(value).encode("utf-8")

    def eval(
        self,
        script: str,
        numkeys: int,
        *keys_and_args: Any,
    ):
        with self._lock:
            if self._fail_next:
                self._fail_next = False
                raise RuntimeError("simulated redis failure")
            if self._forced_result is not None:
                value = self._forced_result
                self._forced_result = None
                return value
            if "PING" in script:
                return b"PONG"
            if numkeys != 3:
                raise RuntimeError("bad numkeys")
            if script != LUA_INCREMENT_AND_CHECK:
                raise RuntimeError("unexpected script")
            email_key, ip_key, pair_key = keys_and_args[:numkeys]
            (email_max, email_window, ip_max, ip_window, pair_max, pair_window) = (
                int(value) for value in keys_and_args[numkeys:]
            )

            def _bump(key: str, max_v: int, window: int) -> tuple[int, int, int]:
                if not key:
                    return 1, 0, 0
                current = self._counters.get(key, 0) + 1
                self._counters[key] = current
                if key not in self._ttls:
                    self._ttls[key] = window
                if current > max_v:
                    return 0, current, self._ttls[key]
                return 1, current, self._ttls[key]

            allowed, count, ttl = _bump(email_key, email_max, email_window)
            if allowed == 0:
                return [b"denied", b"email", count, ttl]
            if ip_key:
                allowed, count, ttl = _bump(ip_key, ip_max, ip_window)
                if allowed == 0:
                    return [b"denied", b"ip", count, ttl]
            if pair_key:
                allowed, count, ttl = _bump(pair_key, pair_max, pair_window)
                if allowed == 0:
                    return [b"denied", b"pair", count, ttl]
            return [b"allowed", b"", count, ttl]


def _match(pattern: str, key: str) -> bool:
    if not pattern.endswith("*"):
        return pattern == key
    return key.startswith(pattern[:-1])


@pytest.fixture
def fake_redis() -> FakeRedis:
    return FakeRedis()


@pytest.fixture
def guard_config() -> GuardConfig:
    return _build_config()


@pytest.fixture
def app(guard_config: GuardConfig, fake_redis: FakeRedis) -> Iterator[FastAPI]:
    application = create_app(config=guard_config, redis_client=fake_redis)
    yield application


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


def auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {VALID_TOKEN}"}


def payload(
    email: str = "owner@example.com",
    remote_ip: str | None = "203.0.113.10",
    action: str = "magic_link",
) -> dict[str, Any]:
    body: dict[str, Any] = {"email": email, "action": action}
    if remote_ip is not None:
        body["remote_ip"] = remote_ip
    return body


def bucket_keys(
    config: GuardConfig,
    email: str,
    remote_ip: str | None,
) -> tuple[str, str | None, str | None]:
    return build_keys(
        raw_email=normalize_email(email),
        raw_ip=normalize_remote_ip(remote_ip),
        hash_secret=config.hash_secret,
    )


__all__ = [
    "VALID_HASH_SECRET",
    "VALID_TOKEN",
    "FakeRedis",
    "auth_headers",
    "bucket_keys",
    "payload",
]
