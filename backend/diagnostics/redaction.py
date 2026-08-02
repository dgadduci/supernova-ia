from __future__ import annotations

_REDACTED_KEYS = {
    "password",
    "token",
    "api_key",
    "authorization",
    "secret",
    "database_url",
    "DATABASE_URL",
    "Authorization",
    "X-API-Key",
    "X-API-KEY",
}
_REDACTED_KEYS_NORMALIZED = {key.casefold() for key in _REDACTED_KEYS}


def redact(value: object) -> object:
    if isinstance(value, dict):
        redacted: dict[object, object] = {}
        for key, item in value.items():
            if str(key).casefold() in _REDACTED_KEYS_NORMALIZED:
                redacted[key] = "<redacted>"
            else:
                redacted[key] = redact(item)
        return redacted
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact(item) for item in value)
    return value


__all__ = ["redact"]
