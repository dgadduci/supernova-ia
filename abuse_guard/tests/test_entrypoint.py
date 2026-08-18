"""Tests for the wired production entry point.

The service must never start with ``redis_client=None``. The
``abuse_guard.__main__.build_app`` factory loads the fail-closed
configuration, builds the Redis client and produces a FastAPI app
whose ``/ready`` endpoint reports readiness and whose ``/check``
endpoint routes through the limiter.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from abuse_guard.__main__ import build_app
from abuse_guard.tests.conftest import (
    VALID_HASH_SECRET,
    VALID_TOKEN,
    FakeRedis,
    auth_headers,
    payload,
)


def _set_full_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("ABUSE_GUARD_TOKEN", VALID_TOKEN)
    monkeypatch.setenv("ABUSE_GUARD_HASH_SECRET", VALID_HASH_SECRET)
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


def test_build_app_wires_config_and_redis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeRedis()
    _set_full_env(monkeypatch)
    app = build_app(redis_client_factory=lambda url: fake)
    assert isinstance(app, FastAPI)
    with TestClient(app) as client:
        ready = client.get("/ready")
        assert ready.status_code == 200
        assert ready.json() == {"status": "ready"}
        response = client.post("/check", json=payload(), headers=auth_headers())
        assert response.status_code == 200
        assert response.json()["allowed"] is True
        assert fake._counters  # the limiter actually invoked Redis


def test_build_app_propagates_redis_url_to_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, str] = {}
    fake = FakeRedis()

    def factory(url: str) -> FakeRedis:
        captured["url"] = url
        return fake

    _set_full_env(monkeypatch)
    monkeypatch.setenv("REDIS_URL", "redis://10.0.0.5:6379/1")
    app = build_app(redis_client_factory=factory)
    assert captured["url"] == "redis://10.0.0.5:6379/1"
    with TestClient(app) as client:
        response = client.get("/ready")
        assert response.status_code == 200


def test_build_app_fails_closed_when_factory_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_full_env(monkeypatch)

    def factory(_url: str) -> object:
        raise RuntimeError("redis init failed")

    app = build_app(redis_client_factory=factory)
    with TestClient(app) as client:
        ready = client.get("/ready")
        assert ready.status_code == 503
        check = client.post("/check", json=payload(), headers=auth_headers())
        assert check.status_code == 503


def test_build_app_fails_closed_when_config_invalid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("ABUSE_GUARD_TOKEN", raising=False)
    monkeypatch.delenv("ABUSE_GUARD_HASH_SECRET", raising=False)
    app = build_app(redis_client_factory=lambda _url: FakeRedis())
    with TestClient(app) as client:
        ready = client.get("/ready")
        assert ready.status_code == 503
        check = client.post("/check", json=payload(), headers=auth_headers())
        assert check.status_code == 503


def test_dockerfile_uses_wired_entrypoint() -> None:
    """The container must not start ``abuse_guard.app:app`` directly."""

    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "Dockerfile"
    text = path.read_text(encoding="utf-8")
    assert "uvicorn abuse_guard.app:app" not in text
    assert "python -m abuse_guard" in text


def test_module_level_app_is_unwired_by_default() -> None:
    """The bare ``abuse_guard.app:app`` must not bring up a real client."""

    from abuse_guard.app import app as module_app

    with TestClient(module_app) as client:
        ready = client.get("/ready")
        assert ready.status_code == 503
        check = client.post("/check", json=payload(), headers=auth_headers())
        assert check.status_code == 503
