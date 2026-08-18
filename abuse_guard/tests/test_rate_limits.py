"""Rate-limit denial tests for the ``POST /check`` endpoint."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from abuse_guard.app import create_app
from abuse_guard.tests.conftest import _build_config, auth_headers, payload


def test_email_window_denies_second_request(client):
    first = client.post("/check", json=payload(), headers=auth_headers())
    assert first.status_code == 200
    assert first.json()["allowed"] is True

    second = client.post("/check", json=payload(), headers=auth_headers())
    assert second.status_code == 200
    body = second.json()
    assert set(body.keys()) == {"allowed", "decision_id"}
    assert body["allowed"] is False
    assert body["decision_id"]


def test_denial_response_does_not_leak_reason(client):
    first = client.post("/check", json=payload(), headers=auth_headers())
    assert first.status_code == 200
    second = client.post("/check", json=payload(), headers=auth_headers())
    body = second.json()
    forbidden = {
        "email",
        "remote_ip",
        "ip",
        "reason",
        "count",
        "counter",
        "ttl",
        "redis_url",
        "token",
        "limit",
        "window",
        "dimension",
    }
    assert forbidden.isdisjoint(body.keys())


def test_different_email_is_allowed(client):
    response = client.post(
        "/check",
        json=payload(email="first@example.com"),
        headers=auth_headers(),
    )
    assert response.status_code == 200
    assert response.json()["allowed"] is True
    response = client.post(
        "/check",
        json=payload(email="second@example.com"),
        headers=auth_headers(),
    )
    assert response.status_code == 200
    assert response.json()["allowed"] is True


def test_ip_limit_denies_when_exceeded(guard_config, fake_redis):
    config = _build_config(email_max=10, ip_max=2)
    app = create_app(config=config, redis_client=fake_redis)
    with TestClient(app) as client:
        headers = auth_headers()
        for index in range(2):
            response = client.post(
                "/check",
                json=payload(email=f"user{index}@example.com"),
                headers=headers,
            )
            assert response.status_code == 200
            assert response.json()["allowed"] is True
        response = client.post(
            "/check",
            json=payload(email="user2@example.com"),
            headers=headers,
        )
        assert response.status_code == 200
        assert response.json()["allowed"] is False


def test_pair_limit_denies_when_exceeded(guard_config, fake_redis):
    config = _build_config(email_max=10, pair_max=2)
    app = create_app(config=config, redis_client=fake_redis)
    with TestClient(app) as client:
        headers = auth_headers()
        for _ in range(2):
            response = client.post("/check", json=payload(), headers=headers)
            assert response.status_code == 200
            assert response.json()["allowed"] is True
        response = client.post("/check", json=payload(), headers=headers)
        assert response.status_code == 200
        assert response.json()["allowed"] is False


def test_counter_is_per_identifier(guard_config, fake_redis):
    config = _build_config(email_max=10, ip_max=10, pair_max=10)
    app = create_app(config=config, redis_client=fake_redis)
    with TestClient(app) as client:
        response = client.post(
            "/check",
            json=payload(email="first@example.com"),
            headers=auth_headers(),
        )
        assert response.status_code == 200
        assert response.json()["allowed"] is True
        response = client.post(
            "/check",
            json=payload(
                email="first@example.com",
                remote_ip="198.51.100.20",
            ),
            headers=auth_headers(),
        )
        assert response.status_code == 200
        assert response.json()["allowed"] is True
        assert any(
            key.startswith("abuse_guard:v1:ip:") for key in fake_redis._counters
        )


def test_denial_does_not_increment_other_buckets(guard_config, fake_redis):
    config = _build_config(email_max=1, ip_max=10, pair_max=10)
    app = create_app(config=config, redis_client=fake_redis)
    with TestClient(app) as client:
        client.post("/check", json=payload(), headers=auth_headers())
        ip_count_after_first = sum(
            value
            for key, value in fake_redis._counters.items()
            if key.startswith("abuse_guard:v1:ip:")
        )
        client.post("/check", json=payload(), headers=auth_headers())
        ip_count_after_second = sum(
            value
            for key, value in fake_redis._counters.items()
            if key.startswith("abuse_guard:v1:ip:")
        )
        assert ip_count_after_first == 1
        assert ip_count_after_second == 1


def test_authentication_rejection_does_not_touch_redis(client, fake_redis):
    before = sum(fake_redis._counters.values())
    response = client.post(
        "/check",
        json=payload(),
        headers={"Authorization": "Bearer wrong"},
    )
    assert response.status_code == 403
    assert sum(fake_redis._counters.values()) == before


def test_invalid_body_does_not_touch_redis(client, fake_redis):
    before = sum(fake_redis._counters.values())
    response = client.post(
        "/check",
        json={"email": "owner@example.com", "action": "login"},
        headers=auth_headers(),
    )
    assert response.status_code == 400
    assert sum(fake_redis._counters.values()) == before


@pytest.mark.parametrize("email", ["owner@example.com", "OWNER@example.com"])
def test_email_normalization_treats_case_as_same(client, email):
    first = client.post("/check", json=payload(email=email), headers=auth_headers())
    second = client.post(
        "/check",
        json=payload(email=email.lower()),
        headers=auth_headers(),
    )
    assert first.status_code == 200
    assert first.json()["allowed"] is True
    assert second.status_code == 200
    assert second.json()["allowed"] is False


def test_email_with_whitespace_is_normalized(client):
    response = client.post(
        "/check",
        json=payload(email="  owner@example.com  "),
        headers=auth_headers(),
    )
    assert response.status_code == 200
    assert response.json()["allowed"] is True
