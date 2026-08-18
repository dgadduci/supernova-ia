"""Distributed Redis rate limiter for the abuse guard service.

The limiter:

* derives keyed hashes from normalized email and remote IP using
  ``ABUSE_GUARD_HASH_SECRET`` so raw identifiers never become
  persistent key material;
* evaluates the email, IP and email+IP windows atomically against the
  configured limits through a single Lua script registered as
  ``LUA_INCREMENT_AND_CHECK``;
* never falls back to an in-memory store; if the Redis client raises,
  the caller must treat the decision as unavailable.

The module exposes a small :class:`RedisLimiter` interface. Production
code passes a real ``redis.Redis`` client; the test suite injects a
fake transport that mirrors the same :func:`eval` signature.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from typing import Any, Protocol

from abuse_guard.config import (
    GuardConfig,
    normalize_email,
    normalize_remote_ip,
)

KEY_PREFIX = "abuse_guard:v1"
ACCEPTED_ACTION = "magic_link"

LUA_INCREMENT_AND_CHECK = """
-- KEYS: email_key, ip_key, pair_key
-- ARGV: email_max, email_window, ip_max, ip_window, pair_max, pair_window
local email_key = KEYS[1]
local ip_key = KEYS[2]
local pair_key = KEYS[3]

local email_max = tonumber(ARGV[1])
local email_window = tonumber(ARGV[2])
local ip_max = tonumber(ARGV[3])
local ip_window = tonumber(ARGV[4])
local pair_max = tonumber(ARGV[5])
local pair_window = tonumber(ARGV[6])

local function bump(key, max, window)
    local current = redis.call('INCR', key)
    if current == 1 then
        redis.call('EXPIRE', key, window)
    end
    local ttl = redis.call('TTL', key)
    if ttl < 0 then
        redis.call('EXPIRE', key, window)
        ttl = window
    end
    if current > max then
        return {0, current, ttl}
    end
    return {1, current, ttl}
end

local email = bump(email_key, email_max, email_window)
if email[1] == 0 then
    return {'denied', 'email', email[2], email[3]}
end

if ip_key ~= '' then
    local ip = bump(ip_key, ip_max, ip_window)
    if ip[1] == 0 then
        return {'denied', 'ip', ip[2], ip[3]}
    end
end

if pair_key ~= '' then
    local pair = bump(pair_key, pair_max, pair_window)
    if pair[1] == 0 then
        return {'denied', 'pair', pair[2], pair[3]}
    end
end

return {'allowed', '', email[2], email[3]}
"""


class RedisProtocol(Protocol):
    """Protocol matching the subset of :class:`redis.Redis` we use."""

    def eval(
        self,
        script: str,
        numkeys: int,
        *keys_and_args: Any,
    ) -> Any: ...


class LimiterError(RuntimeError):
    """Raised when the limiter cannot decide the request safely."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class DecisionOutcome:
    """The bounded decision returned by the limiter."""

    allowed: bool
    reason: str
    email_count: int
    count_ttl: int


def _hash_identifier(secret: bytes, scope: str, identifier: str) -> str:
    """Return ``hex(HMAC-SHA256(secret, scope || ":" || identifier))``."""

    payload = f"{scope}:{identifier}".encode()
    return hmac.new(secret, payload, hashlib.sha256).hexdigest()


def build_keys(
    *,
    raw_email: str,
    raw_ip: str | None,
    hash_secret: str,
) -> tuple[str, str | None, str | None]:
    """Return the bounded Redis keys for a request.

    The keys are deterministic HMAC outputs; the limiter never stores
    raw identifiers. The pair key is only returned when the IP is
    present, otherwise both ``ip_key`` and ``pair_key`` are ``None``.
    """

    secret = hash_secret.encode("utf-8")
    email_key = f"{KEY_PREFIX}:email:{_hash_identifier(secret, 'email', raw_email)}"
    if raw_ip is None:
        return email_key, None, None
    ip_key = f"{KEY_PREFIX}:ip:{_hash_identifier(secret, 'ip', raw_ip)}"
    pair_key = (
        f"{KEY_PREFIX}:pair:{_hash_identifier(secret, 'pair', raw_email + '|' + raw_ip)}"
    )
    return email_key, ip_key, pair_key


class RedisLimiter:
    """Atomic Redis-backed limiter for the magic-link flow."""

    def __init__(
        self,
        *,
        client: RedisProtocol,
        config: GuardConfig,
    ) -> None:
        self._client = client
        self._config = config

    def check(
        self,
        *,
        raw_email: str,
        raw_ip: str | None,
    ) -> DecisionOutcome:
        """Increment the applicable buckets and return the decision.

        Raises :class:`LimiterError` when the request is unsafe to
        decide or the underlying Redis call fails. Callers must
        translate that error into a fail-closed response.
        """

        email = normalize_email(raw_email)
        ip = normalize_remote_ip(raw_ip)
        if not email:
            raise LimiterError("invalid_email")
        email_key, ip_key, pair_key = build_keys(
            raw_email=email,
            raw_ip=ip,
            hash_secret=self._config.hash_secret,
        )
        keys = [
            email_key,
            ip_key if ip_key is not None else "",
            pair_key if pair_key is not None else "",
        ]
        args = [
            self._config.email_max,
            self._config.email_window_seconds,
            self._config.ip_max,
            self._config.ip_window_seconds,
            self._config.pair_max,
            self._config.pair_window_seconds,
        ]
        try:
            result = self._client.eval(
                LUA_INCREMENT_AND_CHECK,
                3,
                *keys,
                *args,
            )
        except Exception as exc:
            raise LimiterError("redis_unavailable") from exc
        return self._parse_result(result, has_ip=ip_key is not None)

    @staticmethod
    def _parse_result(
        result: Any,
        *,
        has_ip: bool,
    ) -> DecisionOutcome:
        decision, reason, count_int, ttl_int = RedisLimiter._coerce_result(
            result, has_ip=has_ip
        )
        if decision == "allowed":
            return DecisionOutcome(
                allowed=True,
                reason="",
                email_count=count_int,
                count_ttl=ttl_int,
            )
        return DecisionOutcome(
            allowed=False,
            reason=reason,
            email_count=count_int,
            count_ttl=ttl_int,
        )

    @staticmethod
    def _coerce_result(
        result: Any,
        *,
        has_ip: bool,
    ) -> tuple[str, str, int, int]:
        """Validate ``result`` and return its decoded parts.

        The Lua script returns a Lua array that the Redis client
        converts to a Python list of bulk strings or, when
        ``decode_responses=False`` is configured, a list of ``bytes``
        plus integer values. The function decodes the bounded string
        fields as UTF-8 and rejects anything that is not the documented
        shape so a permissive response cannot bypass the limiter.
        """

        if not isinstance(result, (list, tuple)) or len(result) != 4:
            raise LimiterError("malformed_result")
        decision_raw, reason_raw, count, ttl = result
        decision = _decode_bounded_string(decision_raw, limit=16)
        if decision not in {"allowed", "denied"}:
            raise LimiterError("malformed_result")
        try:
            count_int = int(count)
            ttl_int = int(ttl)
        except (TypeError, ValueError) as exc:
            raise LimiterError("malformed_result") from exc
        if count_int < 0 or ttl_int < 0:
            raise LimiterError("malformed_result")
        if decision == "allowed":
            return "allowed", "", count_int, ttl_int
        reason = _decode_bounded_string(reason_raw, limit=16)
        if reason not in {"email", "ip", "pair"}:
            raise LimiterError("malformed_result")
        if reason in {"ip", "pair"} and not has_ip:
            raise LimiterError("malformed_result")
        return "denied", reason, count_int, ttl_int


def _decode_bounded_string(value: Any, *, limit: int) -> str:
    """Decode ``value`` as a bounded UTF-8 string.

    Real Redis returns ``bytes`` for any Lua string when the client is
    configured with ``decode_responses=False``. ``str`` is also
    accepted for tests and for clients configured with
    ``decode_responses=True``. Anything else — including ``None``,
    numbers, dicts, or oversized payloads — is rejected so the
    limiter never trusts an unexpected shape.
    """

    if isinstance(value, bytes):
        if len(value) > limit:
            raise LimiterError("malformed_result")
        try:
            decoded = value.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise LimiterError("malformed_result") from exc
        return decoded
    if isinstance(value, str):
        if len(value) > limit:
            raise LimiterError("malformed_result")
        return value
    raise LimiterError("malformed_result")


def ping(client: RedisProtocol) -> bool:
    """Return ``True`` when ``client`` answers a safe PING command.

    The function only inspects the boolean result; it never logs or
    returns the underlying transport or credentials.
    """

    try:
        response = client.eval("return redis.call('PING')", 0)
    except Exception as exc:
        raise LimiterError("redis_unavailable") from exc
    if isinstance(response, bytes):
        return response == b"PONG"
    if isinstance(response, str):
        return response == "PONG"
    return False


__all__ = [
    "ACCEPTED_ACTION",
    "LUA_INCREMENT_AND_CHECK",
    "DecisionOutcome",
    "LimiterError",
    "RedisLimiter",
    "RedisProtocol",
    "build_keys",
    "ping",
]
