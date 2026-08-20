"""Twilio-shaped synthetic identifiers.

The emulator generates two bounded identifiers:

* ``MessageSid`` — the canonical ``SM[hex]`` identifier used by
  Twilio's outbound Messages API response. The format mirrors the
  documented Twilio shape so the typed result keeps its existing
  contract;
* ``AccountSid`` — the canonical ``AC[hex]`` identifier generated at
  emulator startup. It is read-only after construction so the rest of
  the code can rely on a stable value.

Both helpers are pure: they never log the identifier, never persist it
and never call the real Twilio service. ``MessageSid`` is unique per
call so a duplicate inbound can never collide with a synthetic SID.
"""
from __future__ import annotations

import secrets

_ACCOUNT_SID_PREFIX: str = "AC"
_MESSAGE_SID_PREFIX: str = "SM"
_ACCOUNT_SID_HEX_LENGTH: int = 32
_MESSAGE_SID_HEX_LENGTH: int = 32


def generate_message_sid() -> str:
    """Return a unique synthetic ``SM[hex]`` identifier.

    The function uses :func:`secrets.token_hex` so the identifier
    cannot be predicted from another identifier in the same process.
    The output follows the documented Twilio shape so the typed
    downstream code accepts it verbatim.
    """
    return _MESSAGE_SID_PREFIX + secrets.token_hex(_MESSAGE_SID_HEX_LENGTH // 2)


def is_well_formed_account_sid(value: str) -> bool:
    """Return ``True`` when ``value`` matches the canonical shape.

    The validator exists so the bounded inbound control surface can
    confirm an operator-supplied value before persisting it. The
    function does NOT consult the network.
    """
    if not isinstance(value, str):
        return False
    if not value.startswith(_ACCOUNT_SID_PREFIX):
        return False
    tail = value[len(_ACCOUNT_SID_PREFIX):]
    if len(tail) != _ACCOUNT_SID_HEX_LENGTH:
        return False
    return all(ch in "0123456789abcdefABCDEF" for ch in tail)


def account_sid_prefix(value: str) -> str:
    """Return a short non-secret prefix of the account SID.

    The prefix is the only safe identifier the emulator exposes in
    structured logs and the bounded JSON sinks. It cannot leak the
    full SID or the auth token.
    """
    if not isinstance(value, str) or not value:
        return "short"
    if not value.startswith(_ACCOUNT_SID_PREFIX):
        return "short"
    tail = value[len(_ACCOUNT_SID_PREFIX):]
    if len(tail) < 6:
        return "short"
    return f"tail-{tail[-6:]}"


__all__ = [
    "account_sid_prefix",
    "generate_message_sid",
    "is_well_formed_account_sid",
]