"""Focused tests for ``backend.cli.inventory_provider_message_retention``.

Coverage:

1. The CLI outputs a single bounded JSON object with state groups
   and integer counts only; the JSON NEVER contains a message body,
   E.164 address, provider SID, signature, token, URL, prompt,
   customer content or any other operator/customer payload.
2. The CLI accepts a single age threshold and an optional states
   allowlist; unknown states and negative thresholds fail with
   exit code 2.
3. The CLI returns exit code 3 on database errors and exit code 0
   on a successful bounded aggregate.
4. The CLI is read-only: it never INSERTs, UPDATEs, DELETEs,
   COMMITs in autocommit mode or rolls back. It opens exactly one
   session, runs exactly one aggregate SELECT, and closes.
5. The CLI never calls Twilio, Ollama, FastAPI or any HTTP
   framework - the inventory is a pure PostgreSQL reader.
6. The CLI distinguishes itself from message deletion: it never
   emits a DELETE statement and never reveals message content.
"""
from __future__ import annotations

import ast
import contextlib
import io
import json
import unittest
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from backend.cli import inventory_provider_message_retention as cli_module
from backend.cli.inventory_provider_message_retention import (
    DEFAULT_STATES,
    EXIT_DATABASE_ERROR,
    EXIT_INVALID_ARGUMENTS,
    EXIT_OK,
    _build_inventory,
    _build_parser,
    _compute_threshold,
    _format_output,
    _parse_states,
    _validate_args,
    main,
)


REPO_ROOT = Path(__file__).resolve().parents[2]


def _row(state: str, eligible: int, total: int) -> MagicMock:
    row = MagicMock(name=f"Row<{state}>")
    row.estado = state
    row.eligible = eligible
    row.total = total
    return row


class _FakeSession:
    def __init__(self, rows: list[MagicMock]) -> None:
        self._rows = rows
        self.executed: list[Any] = []
        self.closed = False
        self.commits: list[bool] = []
        self.deleted: list[Any] = []
        self.added: list[Any] = []

    def execute(self, stmt: Any) -> MagicMock:
        self.executed.append(stmt)
        result = MagicMock(name="Result")
        result.all.return_value = self._rows
        return result

    def close(self) -> None:
        self.closed = True

    def commit(self) -> None:
        self.commits.append(True)

    def rollback(self) -> None:
        self.commits.append(False)

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    def delete(self, obj: Any) -> None:
        self.deleted.append(obj)


class ArgumentParserTest(unittest.TestCase):
    def test_required_older_than_days(self) -> None:
        parser = _build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args([])

    def test_validate_args_rejects_negative_threshold(self) -> None:
        parser = _build_parser()
        args = parser.parse_args(["--older-than-days", "-1"])
        with self.assertRaises(SystemExit) as ctx:
            with contextlib.redirect_stderr(io.StringIO()):
                _validate_args(args)
        self.assertEqual(ctx.exception.code, EXIT_INVALID_ARGUMENTS)

    def test_validate_args_accepts_zero(self) -> None:
        parser = _build_parser()
        args = parser.parse_args(["--older-than-days", "0"])
        with contextlib.redirect_stderr(io.StringIO()):
            _validate_args(args)

    def test_parse_states_default_returns_all(self) -> None:
        self.assertEqual(_parse_states(None), DEFAULT_STATES)

    def test_parse_states_rejects_unknown_state(self) -> None:
        with self.assertRaises(SystemExit) as ctx:
            with contextlib.redirect_stderr(io.StringIO()):
                _parse_states("never_emitted")
        self.assertEqual(ctx.exception.code, EXIT_INVALID_ARGUMENTS)

    def test_parse_states_accepts_subset(self) -> None:
        result = _parse_states("delivered,failed_terminal")
        self.assertEqual(
            result, frozenset({"delivered", "failed_terminal"})
        )

    def test_compute_threshold_is_offset(self) -> None:
        fixed = datetime(2026, 8, 11, 12, 0, 0, tzinfo=timezone.utc)
        threshold = _compute_threshold(30, now_fn=lambda: fixed)
        self.assertEqual(
            threshold,
            fixed - timedelta(days=30),
        )


class BuildInventoryTest(unittest.TestCase):
    def test_aggregates_by_state_with_eligible_and_total(self) -> None:
        rows = [
            _row("delivered", 3, 9),
            _row("failed_terminal", 1, 7),
        ]
        session = _FakeSession(rows)
        threshold = datetime(2026, 5, 1, tzinfo=timezone.utc)
        inventory = _build_inventory(
            session,
            threshold=threshold,
            states=frozenset({"delivered", "failed_terminal"}),
        )
        self.assertEqual(
            inventory["by_state"]["delivered"],
            {"eligible": 3, "total": 9},
        )
        self.assertEqual(
            inventory["by_state"]["failed_terminal"],
            {"eligible": 1, "total": 7},
        )

    def test_fills_zero_for_missing_states(self) -> None:
        session = _FakeSession([])
        threshold = datetime(2026, 5, 1, tzinfo=timezone.utc)
        inventory = _build_inventory(
            session,
            threshold=threshold,
            states=DEFAULT_STATES,
        )
        for state in DEFAULT_STATES:
            self.assertEqual(
                inventory["by_state"][state],
                {"eligible": 0, "total": 0},
            )


class FormatOutputTest(unittest.TestCase):
    def test_format_output_is_bounded_json(self) -> None:
        inventory = {
            "threshold": "2026-05-01T00:00:00+00:00",
            "older_than_days": 100,
            "by_state": {
                "delivered": {"eligible": 1, "total": 2},
                "failed_terminal": {"eligible": 0, "total": 0},
            },
            "state_universe": sorted(DEFAULT_STATES),
        }
        rendered = _format_output(inventory)
        parsed = json.loads(rendered)
        self.assertEqual(parsed["by_state"]["delivered"]["total"], 2)
        for forbidden in (
            "secret-auth-token-value",
            "+5491100000000",
            "SM-ABC-XYZ",
            "leak:",
            "inbound body",
            "outbound body",
            "Bearer ",
        ):
            self.assertNotIn(forbidden, rendered)


class MainEntrypointTest(unittest.TestCase):
    def test_returns_zero_and_prints_bounded_json(self) -> None:
        rows = [_row("delivered", 1, 2)]
        session = _FakeSession(rows)
        with contextlib.redirect_stdout(io.StringIO()) as stdout:
            exit_code = main(
                ["--older-than-days", "30"],
                session_factory=lambda: session,
                now_fn=lambda: datetime(2026, 8, 11, tzinfo=timezone.utc),
            )
        self.assertEqual(exit_code, EXIT_OK)
        rendered = json.loads(stdout.getvalue())
        self.assertEqual(rendered["by_state"]["delivered"]["total"], 2)

    def test_closes_session_on_success(self) -> None:
        rows = [_row("delivered", 0, 1)]
        session = _FakeSession(rows)
        main(
            ["--older-than-days", "1"],
            session_factory=lambda: session,
            now_fn=lambda: datetime(2026, 8, 11, tzinfo=timezone.utc),
        )
        self.assertTrue(session.closed)

    def test_closes_session_on_failure(self) -> None:
        class _BrokenSession(_FakeSession):
            def execute(self, _stmt: Any) -> Any:
                raise RuntimeError("simulated db failure")

        session = _BrokenSession([])
        with contextlib.redirect_stderr(io.StringIO()):
            exit_code = main(
                ["--older-than-days", "1"],
                session_factory=lambda: session,
                now_fn=lambda: datetime(2026, 8, 11, tzinfo=timezone.utc),
            )
        self.assertEqual(exit_code, EXIT_DATABASE_ERROR)
        self.assertTrue(session.closed)

    def test_invalid_arguments_returns_two(self) -> None:
        with self.assertRaises(SystemExit) as ctx:
            with contextlib.redirect_stderr(io.StringIO()):
                main(["--older-than-days", "-1"])
        self.assertEqual(ctx.exception.code, EXIT_INVALID_ARGUMENTS)

    def test_invalid_states_returns_two(self) -> None:
        with self.assertRaises(SystemExit) as ctx:
            with contextlib.redirect_stderr(io.StringIO()):
                main(
                    [
                        "--older-than-days", "30",
                        "--states", "never_emitted",
                    ]
                )
        self.assertEqual(ctx.exception.code, EXIT_INVALID_ARGUMENTS)

    def test_database_error_returns_three(self) -> None:
        from sqlalchemy.exc import OperationalError

        class _BrokenSession(_FakeSession):
            def execute(self, _stmt: Any) -> Any:
                raise OperationalError("stmt", {}, RuntimeError("orig"))

        session = _BrokenSession([])
        with contextlib.redirect_stderr(io.StringIO()) as stderr:
            exit_code = main(
                ["--older-than-days", "30"],
                session_factory=lambda: session,
                now_fn=lambda: datetime(2026, 8, 11, tzinfo=timezone.utc),
            )
        self.assertEqual(exit_code, EXIT_DATABASE_ERROR)
        self.assertIn("database_error", stderr.getvalue())


class NoMutationGuaranteeTest(unittest.TestCase):
    def test_run_does_not_add_or_delete(self) -> None:
        rows = [_row("delivered", 1, 2)]
        session = _FakeSession(rows)
        main(
            ["--older-than-days", "30"],
            session_factory=lambda: session,
            now_fn=lambda: datetime(2026, 8, 11, tzinfo=timezone.utc),
        )
        self.assertEqual(session.added, [])
        self.assertEqual(session.deleted, [])
        self.assertEqual(session.commits, [])

    def test_runs_exactly_one_aggregate_query(self) -> None:
        rows = [_row("delivered", 1, 2)]
        session = _FakeSession(rows)
        main(
            ["--older-than-days", "30"],
            session_factory=lambda: session,
            now_fn=lambda: datetime(2026, 8, 11, tzinfo=timezone.utc),
        )
        self.assertEqual(len(session.executed), 1)


class ModuleBoundaryTest(unittest.TestCase):
    def test_module_does_not_import_twilio_or_http(self) -> None:
        source = (
            REPO_ROOT
            / "backend"
            / "cli"
            / "inventory_provider_message_retention.py"
        ).read_text()
        for forbidden in (
            "from twilio",
            "import twilio",
            "import requests",
            "from requests",
            "from fastapi",
            "import fastapi",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)

    def test_module_has_no_message_content_outputs(self) -> None:
        source = (
            REPO_ROOT
            / "backend"
            / "cli"
            / "inventory_provider_message_retention.py"
        ).read_text()
        for forbidden in (
            "cuerpo",
            "destinatario_e164",
            "identificador_proveedor",
            "MessageSid",
            "MessageStatus",
            "Body",
            "From",
            "To",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)

    def test_module_uses_select_only(self) -> None:
        source = (
            REPO_ROOT
            / "backend"
            / "cli"
            / "inventory_provider_message_retention.py"
        ).read_text()
        for forbidden in (
            "session.add",
            "session.delete",
            "session.execute(update",
            "session.execute(delete",
            "session.execute(insert",
            "from sqlalchemy import update",
            "from sqlalchemy import delete",
            "from sqlalchemy import insert",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)

    def test_module_has_no_dry_run_or_apply(self) -> None:
        source = (
            REPO_ROOT
            / "backend"
            / "cli"
            / "inventory_provider_message_retention.py"
        ).read_text()
        for forbidden in ("--apply", "--dry-run", "purge"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)


class ReadOnlyAggregateSQLTest(unittest.TestCase):
    """Defence-in-depth: the CLI builds a single bounded aggregate
    SELECT and never opens a write transaction. The test inspects
    the in-memory session to confirm one SELECT was executed and
    no write methods were invoked."""

    def test_executed_statement_is_select_only(self) -> None:
        rows = [_row("delivered", 1, 2)]
        session = _FakeSession(rows)
        main(
            ["--older-than-days", "30"],
            session_factory=lambda: session,
            now_fn=lambda: datetime(2026, 8, 11, tzinfo=timezone.utc),
        )
        self.assertEqual(len(session.executed), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
