"""Contract tests for the ``POST /check`` endpoint."""

from __future__ import annotations

import pytest

from abuse_guard.tests.conftest import auth_headers, payload


def test_valid_request_returns_allow_with_decision_id(client):
    response = client.post("/check", json=payload(), headers=auth_headers())
    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {"allowed", "decision_id"}
    assert body["allowed"] is True
    assert isinstance(body["decision_id"], str)
    assert body["decision_id"].strip()
    assert response.headers.get("content-type", "").startswith("application/json")


def test_response_excludes_sensitive_fields(client):
    response = client.post("/check", json=payload(), headers=auth_headers())
    body = response.json()
    forbidden = {
        "email",
        "remote_ip",
        "ip",
        "count",
        "counter",
        "ttl",
        "reason",
        "redis_url",
        "token",
        "raw",
        "internal",
    }
    assert forbidden.isdisjoint(body.keys())


def test_missing_authorization_header_returns_401(client):
    response = client.post("/check", json=payload())
    assert response.status_code == 401
    assert response.json() == {"detail": "unauthorized"}


def test_malformed_authorization_returns_401(client):
    response = client.post(
        "/check",
        json=payload(),
        headers={"Authorization": "Token foo"},
    )
    assert response.status_code == 401


def test_wrong_token_returns_403(client):
    response = client.post(
        "/check",
        json=payload(),
        headers={"Authorization": "Bearer not-the-real-token"},
    )
    assert response.status_code == 403
    assert response.json() == {"detail": "forbidden"}


def test_empty_token_returns_401(client):
    response = client.post(
        "/check",
        json=payload(),
        headers={"Authorization": "Bearer "},
    )
    assert response.status_code == 401


def test_invalid_json_body_returns_400(client):
    response = client.post(
        "/check",
        data="not-json",
        headers={**auth_headers(), "Content-Type": "application/json"},
    )
    assert response.status_code == 400


def test_object_body_returns_400(client):
    response = client.post(
        "/check",
        json=["not", "an", "object"],
        headers=auth_headers(),
    )
    assert response.status_code == 400


def test_missing_email_returns_400(client):
    response = client.post(
        "/check",
        json={"action": "magic_link"},
        headers=auth_headers(),
    )
    assert response.status_code == 400


def test_invalid_email_returns_400(client):
    response = client.post(
        "/check",
        json=payload(email="not-an-email"),
        headers=auth_headers(),
    )
    assert response.status_code == 400


def test_missing_action_returns_400(client):
    response = client.post(
        "/check",
        json={"email": "owner@example.com"},
        headers=auth_headers(),
    )
    assert response.status_code == 400


def test_unsupported_action_returns_400(client):
    response = client.post(
        "/check",
        json=payload(action="login"),
        headers=auth_headers(),
    )
    assert response.status_code == 400


def test_remote_ip_optional(client):
    response = client.post(
        "/check",
        json=payload(remote_ip=None),
        headers=auth_headers(),
    )
    assert response.status_code == 200
    assert response.json()["allowed"] is True


def test_empty_remote_ip_treated_as_missing(client):
    response = client.post(
        "/check",
        json=payload(remote_ip="   "),
        headers=auth_headers(),
    )
    assert response.status_code == 200
    assert response.json()["allowed"] is True


def test_non_string_remote_ip_returns_400(client):
    response = client.post(
        "/check",
        json={**payload(), "remote_ip": 12345},
        headers=auth_headers(),
    )
    assert response.status_code == 400


def test_request_without_remote_ip_does_not_require_ip(client, fake_redis):
    response = client.post(
        "/check",
        json={"email": "owner@example.com", "action": "magic_link"},
        headers=auth_headers(),
    )
    assert response.status_code == 200
    assert response.json()["allowed"] is True
    assert not any(
        key.startswith("abuse_guard:v1:ip:") for key in fake_redis._counters
    )


def test_decision_id_is_not_derived_from_email(client):
    responses = []
    for _ in range(3):
        responses.append(
            client.post(
                "/check",
                json=payload(email="owner@example.com"),
                headers=auth_headers(),
            )
        )
    # First allowed, subsequent denied — but we only need the identifier
    # values from the allow path here.
    ids = [
        response.json()["decision_id"]
        for response in responses
        if response.json()["allowed"] is True
    ]
    assert ids, "expected at least one allow"
    for value in ids:
        assert "owner" not in value
        assert "example" not in value
        assert "@" not in value


@pytest.mark.parametrize("email", ["", "   ", "missing-at-sign", "a@", "@b.com"])
def test_malformed_email_payload_returns_400(client, email):
    response = client.post(
        "/check",
        json=payload(email=email),
        headers=auth_headers(),
    )
    assert response.status_code == 400
