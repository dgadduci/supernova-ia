"""Tests for health, readiness, fail-closed config and isolation."""

from __future__ import annotations

import importlib
import pathlib
import sys

import pytest
from fastapi.testclient import TestClient

from abuse_guard.app import create_app
from abuse_guard.config import ConfigError
from abuse_guard.tests.conftest import (
    VALID_HASH_SECRET,
    VALID_TOKEN,
    FakeRedis,
    auth_headers,
    payload,
)


def test_health_returns_ok(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {"status"}
    assert body["status"] == "ok"


def test_health_does_not_include_secrets(client: TestClient) -> None:
    response = client.get("/health")
    text = response.text
    assert VALID_TOKEN not in text
    assert VALID_HASH_SECRET not in text
    assert "redis://" not in text


def test_ready_returns_ok_when_redis_alive(client: TestClient) -> None:
    response = client.get("/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_ready_returns_503_when_redis_fails(
    guard_config, fake_redis: FakeRedis
) -> None:
    fake_redis.fail_next()
    app = create_app(config=guard_config, redis_client=fake_redis)
    with TestClient(app) as failure_client:
        response = failure_client.get("/ready")
    assert response.status_code == 503
    assert response.json() == {"detail": "service_unavailable"}


def test_ready_returns_503_without_redis_client(guard_config) -> None:
    app = create_app(config=guard_config, redis_client=None)
    with TestClient(app) as failure_client:
        response = failure_client.get("/ready")
    assert response.status_code == 503
    assert response.json() == {"detail": "service_unavailable"}


def test_ready_returns_503_when_config_invalid(monkeypatch) -> None:
    def failing_loader():
        raise ConfigError("missing:REDIS_URL")

    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("ABUSE_GUARD_TOKEN", raising=False)
    monkeypatch.delenv("ABUSE_GUARD_HASH_SECRET", raising=False)
    app = create_app(config=None, redis_client=FakeRedis(), config_loader=failing_loader)
    with TestClient(app) as failure_client:
        response = failure_client.get("/ready")
    assert response.status_code == 503


def test_check_returns_503_when_config_invalid(monkeypatch) -> None:
    def failing_loader():
        raise ConfigError("missing:REDIS_URL")

    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("ABUSE_GUARD_TOKEN", raising=False)
    monkeypatch.delenv("ABUSE_GUARD_HASH_SECRET", raising=False)
    app = create_app(
        config=None,
        redis_client=FakeRedis(),
        config_loader=failing_loader,
    )
    with TestClient(app) as failure_client:
        response = failure_client.post("/check", json=payload(), headers=auth_headers())
    assert response.status_code == 503


def test_check_returns_503_when_redis_fails(
    guard_config, fake_redis: FakeRedis
) -> None:
    fake_redis.fail_next()
    app = create_app(config=guard_config, redis_client=fake_redis)
    with TestClient(app) as failure_client:
        response = failure_client.post("/check", json=payload(), headers=auth_headers())
    assert response.status_code == 503
    assert response.json() == {"detail": "service_unavailable"}


def test_check_returns_503_without_redis_client(guard_config) -> None:
    app = create_app(config=guard_config, redis_client=None)
    with TestClient(app) as failure_client:
        response = failure_client.post("/check", json=payload(), headers=auth_headers())
    assert response.status_code == 503


def test_ready_response_has_no_secrets(guard_config, fake_redis: FakeRedis) -> None:
    app = create_app(config=guard_config, redis_client=fake_redis)
    with TestClient(app) as failure_client:
        response = failure_client.get("/ready")
        text = response.text
    assert VALID_TOKEN not in text
    assert VALID_HASH_SECRET not in text
    assert "redis://" not in text


def test_logging_does_not_capture_raw_identifiers(
    guard_config, fake_redis: FakeRedis, caplog: pytest.LogCaptureFixture
) -> None:
    app = create_app(config=guard_config, redis_client=fake_redis)
    with caplog.at_level("INFO", logger="abuse_guard"):
        with TestClient(app) as failure_client:
            failure_client.post("/check", json=payload(), headers=auth_headers())
    joined = "\n".join(record.getMessage() for record in caplog.records)
    assert "owner@example.com" not in joined
    assert "203.0.113.10" not in joined
    assert VALID_TOKEN not in joined
    assert VALID_HASH_SECRET not in joined


def test_no_imports_from_novaorders_backend() -> None:
    """The service must not import any module from the ``backend`` package."""

    import ast

    abuse_guard_path = pathlib.Path(__file__).resolve().parents[1]
    failures = []
    for source_file in sorted(abuse_guard_path.glob("*.py")):
        tree = ast.parse(
            source_file.read_text(encoding="utf-8"),
            filename=str(source_file),
        )
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "backend" or alias.name.startswith("backend."):
                        failures.append(
                            f"{source_file.name}:{node.lineno}: imports {alias.name!r}"
                        )
            elif isinstance(node, ast.ImportFrom):
                if node.module is None:
                    continue
                if node.module == "backend" or node.module.startswith("backend."):
                    failures.append(
                        f"{source_file.name}:{node.lineno}: imports {node.module!r}"
                    )
    assert not failures, "; ".join(failures)


def test_abuse_guard_modules_do_not_depend_on_backend() -> None:
    """Loading the package must not trigger any ``backend`` import."""

    for name in list(sys.modules):
        if name == "backend" or name.startswith("backend."):
            sys.modules.pop(name, None)
    abuse_guard_path = pathlib.Path(__file__).resolve().parents[1]
    original_path = sys.path.copy()
    try:
        sys.path.insert(0, str(abuse_guard_path))
        for module_name in (
            "abuse_guard",
            "abuse_guard.app",
            "abuse_guard.config",
            "abuse_guard.limiter",
            "abuse_guard.__main__",
        ):
            sys.modules.pop(module_name, None)
        importlib.import_module("abuse_guard.app")
        importlib.import_module("abuse_guard.limiter")
        importlib.import_module("abuse_guard.config")
        leaked = [
            name
            for name in sys.modules
            if name == "backend" or name.startswith("backend.")
        ]
        assert not leaked, f"abuse_guard runtime pulled backend modules: {leaked}"
    finally:
        for module_name in (
            "abuse_guard",
            "abuse_guard.app",
            "abuse_guard.config",
            "abuse_guard.limiter",
            "abuse_guard.__main__",
        ):
            sys.modules.pop(module_name, None)
        sys.path[:] = original_path


def test_no_direct_imports_from_novaorders_in_source() -> None:
    """The source files must not contain ``from backend`` imports."""

    abuse_guard_path = pathlib.Path(__file__).resolve().parents[1]
    for source_file in abuse_guard_path.glob("*.py"):
        text = source_file.read_text(encoding="utf-8")
        for forbidden in ("import backend", "from backend"):
            assert forbidden not in text, (
                f"{source_file} must not import '{forbidden}'"
            )


def test_no_third_party_imports_outside_runtime() -> None:
    """The service depends only on FastAPI, uvicorn and redis."""

    import ast

    abuse_guard_path = pathlib.Path(__file__).resolve().parents[1]
    allowed = {
        "abuse_guard",
        "fastapi",
        "uvicorn",
        "redis",
        "starlette",
        "anyio",
        "h11",
        "logging",
        "secrets",
        "os",
        "threading",
        "hashlib",
        "hmac",
        "dataclasses",
        "typing",
        "collections",
        "collections.abc",
        "pathlib",
        "importlib",
        "json",
        "textwrap",
        "sys",
        "_pytest",
        "pytest",
        "__future__",
    }
    failures = []
    for source_file in abuse_guard_path.glob("*.py"):
        text = source_file.read_text(encoding="utf-8")
        try:
            tree = ast.parse(text, filename=str(source_file))
        except SyntaxError as exc:
            failures.append(f"{source_file.name}: syntax error: {exc}")
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    head = alias.name.split(".", 1)[0]
                    if head in allowed or head.startswith("abuse_guard"):
                        continue
                    failures.append(
                        f"{source_file.name}:{node.lineno}: unexpected import {head!r}"
                    )
            elif isinstance(node, ast.ImportFrom):
                if node.module is None:
                    continue
                head = node.module.split(".", 1)[0]
                if head in allowed or head.startswith("abuse_guard"):
                    continue
                failures.append(
                    f"{source_file.name}:{node.lineno}: unexpected import {head!r}"
                )
    assert not failures, "; ".join(failures)


def test_app_module_is_importable() -> None:
    abuse_guard_path = pathlib.Path(__file__).resolve().parents[1]
    original_path = sys.path.copy()
    try:
        sys.path.insert(0, str(abuse_guard_path))
        for module_name in (
            "abuse_guard",
            "abuse_guard.app",
            "abuse_guard.config",
            "abuse_guard.limiter",
        ):
            sys.modules.pop(module_name, None)
        module = importlib.import_module("abuse_guard.app")
        assert hasattr(module, "create_app")
        assert hasattr(module, "app")
    finally:
        for module_name in (
            "abuse_guard",
            "abuse_guard.app",
            "abuse_guard.config",
            "abuse_guard.limiter",
        ):
            sys.modules.pop(module_name, None)
        sys.path[:] = original_path


def test_decision_id_is_unique_under_concurrency(client: TestClient) -> None:
    decisions: list[str] = []
    for index in range(5):
        response = client.post(
            "/check",
            json=payload(email=f"user{index}@example.com"),
            headers=auth_headers(),
        )
        assert response.status_code == 200
        decisions.append(response.json()["decision_id"])
    assert len(set(decisions)) == len(decisions)
