"""Operator CLI: read-only inventory of durable provider-message records.

The CLI reports counts grouped by state and age eligibility. It is
the only operator-facing surface allowed to inspect durable
provider-message records for retention decisions.

The CLI is intentionally narrow:

* it never inserts, updates, deletes or commits database rows;
* it never calls Twilio, Ollama or any provider network surface;
* it never exposes message text, destination E.164 addresses,
  provider SIDs, signatures, tokens or any other customer/business
  payload - only safe state names and integer counts;
* it accepts a single age threshold (``--older-than-days``) and an
  optional allowlist of states to include.

Output is a single JSON object on stdout.

Exit codes:

* ``0`` success - the JSON output is printed;
* ``2`` invalid arguments;
* ``3`` database error (engine unreachable, migration missing, etc.).
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session as SqlSession

from backend.dependencies import _SessionLocal
from backend.models.mensaje_proveedor_saliente import (
    MensajeProveedorSaliente,
    OutboundProviderMessageState,
)

logger = logging.getLogger(__name__)


EXIT_OK = 0
EXIT_INVALID_ARGUMENTS = 2
EXIT_DATABASE_ERROR = 3


SESSION_FACTORY: Callable[[], SqlSession] = _SessionLocal


DEFAULT_STATES: frozenset[str] = frozenset(
    state.value
    for state in (
        OutboundProviderMessageState.PENDING,
        OutboundProviderMessageState.LEASED,
        OutboundProviderMessageState.ACCEPTED,
        OutboundProviderMessageState.RETRYABLE,
        OutboundProviderMessageState.DELIVERED,
        OutboundProviderMessageState.FAILED_TERMINAL,
    )
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m backend.cli.inventory_provider_message_retention",
        description=(
            "Read-only inventory of durable provider-message records. "
            "Reports counts grouped by state and age eligibility without "
            "revealing message content and without mutating records."
        ),
    )
    parser.add_argument(
        "--older-than-days",
        type=int,
        required=True,
        help=(
            "Age threshold in days. Records older than this are reported "
            "as 'eligible' for a future retention decision. Must be a "
            "non-negative integer."
        ),
    )
    parser.add_argument(
        "--states",
        default=None,
        help=(
            "Optional comma-separated list of states to include. "
            "Default: all durable states."
        ),
    )
    return parser


def _parse_states(value: str | None) -> frozenset[str]:
    if value is None:
        return DEFAULT_STATES
    states = frozenset(
        token.strip()
        for token in value.split(",")
        if token.strip()
    )
    if not states:
        return DEFAULT_STATES
    invalid = sorted(states - DEFAULT_STATES)
    if invalid:
        print(
            f"invalid_arguments: unknown states {invalid}; allowed: "
            f"{sorted(DEFAULT_STATES)}",
            file=sys.stderr,
        )
        raise SystemExit(EXIT_INVALID_ARGUMENTS)
    return states


def _validate_args(args: argparse.Namespace) -> None:
    if args.older_than_days < 0:
        print(
            f"invalid_arguments: --older-than-days must be non-negative "
            f"(got {args.older_than_days})",
            file=sys.stderr,
        )
        raise SystemExit(EXIT_INVALID_ARGUMENTS)


def _compute_threshold(
    older_than_days: int, *, now_fn: Callable[[], datetime] | None = None
) -> datetime:
    clock = now_fn if now_fn is not None else lambda: datetime.now(
        tz=timezone.utc
    )
    return clock() - timedelta(days=int(older_than_days))


def _build_inventory(
    session: SqlSession,
    *,
    threshold: datetime,
    states: frozenset[str],
) -> dict[str, Any]:
    eligible_expr = func.sum(
        case(
            (
                MensajeProveedorSaliente.fecha_creacion < threshold,
                1,
            ),
            else_=0,
        )
    ).label("eligible")
    total_expr = func.count().label("total")
    stmt = (
        select(
            MensajeProveedorSaliente.estado,
            eligible_expr,
            total_expr,
        )
        .where(MensajeProveedorSaliente.estado.in_(sorted(states)))
        .group_by(MensajeProveedorSaliente.estado)
    )
    rows = session.execute(stmt).all()
    by_state: dict[str, dict[str, int]] = {}
    for row in rows:
        by_state[str(row.estado)] = {
            "eligible": int(row.eligible),
            "total": int(row.total),
        }
    for state in sorted(states):
        by_state.setdefault(state, {"eligible": 0, "total": 0})
    return {
        "threshold": threshold.isoformat(),
        "older_than_days": int(
            (
                datetime.now(tz=timezone.utc) - threshold
            ).total_seconds()
            // 86400
        ),
        "by_state": by_state,
        "state_universe": sorted(DEFAULT_STATES),
    }


def _format_output(inventory: dict[str, Any]) -> str:
    return json.dumps(inventory, sort_keys=True, separators=(",", ":"))


def main(
    argv: Sequence[str] | None = None,
    *,
    session_factory: Callable[[], SqlSession] | None = None,
    now_fn: Callable[[], datetime] | None = None,
) -> int:
    """Run the read-only inventory CLI.

    The CLI opens one short-lived session using the supplied factory
    (default ``_SessionLocal``), runs a single aggregate SELECT and
    closes the session. It NEVER mutates rows, NEVER opens a
    transaction, and NEVER calls Twilio/LLM/Ollama.
    """
    parser = _build_parser()
    args = parser.parse_args(argv)
    _validate_args(args)
    states = _parse_states(args.states)
    factory = session_factory if session_factory is not None else SESSION_FACTORY
    threshold = _compute_threshold(args.older_than_days, now_fn=now_fn)

    session = factory()
    try:
        inventory = _build_inventory(
            session, threshold=threshold, states=states
        )
    except SQLAlchemyError as exc:
        print(
            f"database_error: {type(exc).__name__}",
            file=sys.stderr,
        )
        return EXIT_DATABASE_ERROR
    except (OSError, ValueError, TypeError, RuntimeError, KeyError) as exc:
        print(
            f"inventory_failed: {type(exc).__name__}",
            file=sys.stderr,
        )
        return EXIT_DATABASE_ERROR
    finally:
        session.close()

    print(_format_output(inventory))
    return EXIT_OK


__all__ = [
    "DEFAULT_STATES",
    "EXIT_DATABASE_ERROR",
    "EXIT_INVALID_ARGUMENTS",
    "EXIT_OK",
    "SESSION_FACTORY",
    "main",
]


if __name__ == "__main__":
    sys.exit(main())
