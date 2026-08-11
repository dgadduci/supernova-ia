"""Focused tests for ``backend.cli.query_production_logs``.

Coverage:

1. The CLI builds the documented ``railway logs`` command with
   explicit ``--project``, ``--environment`` and ``--service``
   selection.
2. The CLI distinguishes the documented exit categories:
   - success / no results (exit 0);
   - invalid arguments (exit 2);
   - Railway invocation failure (exit 3);
   - unparseable provider output (exit 4).
3. The CLI parses Railway output line-by-line and rejects any line
   that is not a valid structured event. The raw failing line is
   NEVER printed back to the operator.
4. The CLI applies ``--since``, ``--event``, ``--level`` and
   ``--limit`` filters in order and never reflects unsafe string
   values into the output.
5. The CLI never opens a database session, never imports SQLAlchemy
   and never calls Twilio/LLM/Ollama.
6. The CLI stdlib boundary test: the module does not import
   ``sqlalchemy``, ``twilio`` or any HTTP framework.
"""
from __future__ import annotations

import ast
import contextlib
import io
import json
import subprocess
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from backend.cli import query_production_logs as cli_module
from backend.cli.query_production_logs import (
    DEFAULT_LIMIT,
    EXIT_INVALID_ARGUMENTS,
    EXIT_OK,
    EXIT_RAILWAY_INVOCATION_FAILED,
    EXIT_RAILWAY_UNPARSEABLE,
    MAX_LIMIT,
    RAILWAY_BINARY,
    RAILWAY_LOGS_SUBCOMMAND,
    RAILWAY_TIMEOUT_SECONDS,
    RailwayInvocationError,
    UnparseableRailwayOutputError,
    _build_parser,
    _build_railway_command,
    _extract_event_from_line,
    _format_output,
    _match_event,
    _parse_lines_into_events,
    _run_railway,
    _validate_args,
    main,
)


REPO_ROOT = Path(__file__).resolve().parents[2]


def _valid_event(
    *,
    event: str = "outbound_attempt_outcome",
    outcome: str | None = "accepted",
    failure_category: str | None = None,
    component: str = "outbound_dispatch",
    outbox_id: int | None = None,
    timestamp: str = "2026-08-11T10:00:00+00:00",
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "event": event,
        "schema_version": 1,
        "component": component,
        "timestamp": timestamp,
    }
    if outcome is not None and failure_category is None:
        payload["outcome"] = outcome
    if failure_category is not None:
        payload["failure_category"] = failure_category
        payload.pop("outcome", None)
    if outbox_id is not None:
        payload["outbox_id"] = outbox_id
    return payload


class _FakeCompletedProcess:
    def __init__(self, *, stdout: str, returncode: int = 0) -> None:
        self.stdout = stdout
        self.returncode = returncode


class ArgumentParserTest(unittest.TestCase):
    def test_required_arguments(self) -> None:
        parser = _build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args([])

    def test_build_railway_command_has_explicit_selection(self) -> None:
        parser = _build_parser()
        args = parser.parse_args(
            ["--project", "p1", "--environment", "e1", "--service", "s1"]
        )
        cmd = _build_railway_command(args)
        self.assertEqual(cmd[0], RAILWAY_BINARY)
        self.assertEqual(cmd[1], RAILWAY_LOGS_SUBCOMMAND)
        self.assertIn("--project", cmd)
        self.assertIn("p1", cmd)
        self.assertIn("--environment", cmd)
        self.assertIn("e1", cmd)
        self.assertIn("--service", cmd)
        self.assertIn("s1", cmd)
        self.assertIn("--json", cmd)

    def test_level_accepts_only_info_or_error(self) -> None:
        parser = _build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(
                [
                    "--project", "p1",
                    "--environment", "e1",
                    "--service", "s1",
                    "--level", "warning",
                ]
            )

    def test_validate_args_rejects_empty_project(self) -> None:
        parser = _build_parser()
        args = parser.parse_args(
            ["--project", "", "--environment", "e1", "--service", "s1"]
        )
        with self.assertRaises(SystemExit) as ctx:
            with contextlib.redirect_stderr(io.StringIO()):
                _validate_args(args)
        self.assertEqual(ctx.exception.code, EXIT_INVALID_ARGUMENTS)

    def test_validate_args_rejects_limit_out_of_range(self) -> None:
        parser = _build_parser()
        args = parser.parse_args(
            [
                "--project", "p1",
                "--environment", "e1",
                "--service", "s1",
                "--limit", str(MAX_LIMIT + 1),
            ]
        )
        with self.assertRaises(SystemExit) as ctx:
            with contextlib.redirect_stderr(io.StringIO()):
                _validate_args(args)
        self.assertEqual(ctx.exception.code, EXIT_INVALID_ARGUMENTS)

    def test_validate_args_rejects_non_integer_limit(self) -> None:
        parser = _build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(
                [
                    "--project", "p1",
                    "--environment", "e1",
                    "--service", "s1",
                    "--limit", "abc",
                ]
            )

    def test_validate_args_rejects_invalid_since(self) -> None:
        parser = _build_parser()
        args = parser.parse_args(
            [
                "--project", "p1",
                "--environment", "e1",
                "--service", "s1",
                "--since", "not-a-date",
            ]
        )
        with self.assertRaises(SystemExit) as ctx:
            with contextlib.redirect_stderr(io.StringIO()):
                _validate_args(args)
        self.assertEqual(ctx.exception.code, EXIT_INVALID_ARGUMENTS)

    def test_validate_args_accepts_iso8601_with_z(self) -> None:
        parser = _build_parser()
        args = parser.parse_args(
            [
                "--project", "p1",
                "--environment", "e1",
                "--service", "s1",
                "--since", "2026-08-11T10:00:00Z",
            ]
        )
        with contextlib.redirect_stderr(io.StringIO()):
            _validate_args(args)


class RunRailwayTest(unittest.TestCase):
    def test_run_railway_returns_completed(self) -> None:
        runner = MagicMock(return_value=_FakeCompletedProcess(stdout=""))
        completed = _run_railway(
            _build_parser().parse_args(
                ["--project", "p1", "--environment", "e1", "--service", "s1"]
            ),
            runner=runner,
        )
        self.assertEqual(completed.stdout, "")
        runner.assert_called_once()

    def test_run_railway_raises_on_non_zero(self) -> None:
        runner = MagicMock(
            return_value=_FakeCompletedProcess(stdout="", returncode=1)
        )
        with self.assertRaises(RailwayInvocationError):
            _run_railway(
                _build_parser().parse_args(
                    [
                        "--project", "p1",
                        "--environment", "e1",
                        "--service", "s1",
                    ]
                ),
                runner=runner,
            )

    def test_run_railway_raises_on_missing_binary(self) -> None:
        def runner(*_args: Any, **_kwargs: Any) -> Any:
            raise FileNotFoundError("railway")

        with self.assertRaises(RailwayInvocationError):
            _run_railway(
                _build_parser().parse_args(
                    [
                        "--project", "p1",
                        "--environment", "e1",
                        "--service", "s1",
                    ]
                ),
                runner=runner,
            )

    def test_run_railway_raises_on_timeout(self) -> None:
        def runner(*_args: Any, **_kwargs: Any) -> Any:
            raise subprocess.TimeoutExpired(cmd="railway", timeout=1)

        with self.assertRaises(RailwayInvocationError):
            _run_railway(
                _build_parser().parse_args(
                    [
                        "--project", "p1",
                        "--environment", "e1",
                        "--service", "s1",
                    ]
                ),
                runner=runner,
            )

    def test_run_railway_propagates_unexpected_subprocess_error(self) -> None:
        def runner(*_args: Any, **_kwargs: Any) -> Any:
            raise RuntimeError("boom")

        with self.assertRaises(RailwayInvocationError):
            _run_railway(
                _build_parser().parse_args(
                    [
                        "--project", "p1",
                        "--environment", "e1",
                        "--service", "s1",
                    ]
                ),
                runner=runner,
            )

    def test_run_railway_default_runner_uses_timeout(self) -> None:
        with self.assertRaises(RailwayInvocationError):
            _run_railway(
                _build_parser().parse_args(
                    [
                        "--project", "p1",
                        "--environment", "e1",
                        "--service", "s1",
                    ]
                )
            )


class ParseLinesTest(unittest.TestCase):
    def test_parses_direct_event_line(self) -> None:
        event = _valid_event()
        line = json.dumps(event, sort_keys=True, separators=(",", ":"))
        completed = _FakeCompletedProcess(stdout=line + "\n")
        events = _parse_lines_into_events(completed)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event"], "outbound_attempt_outcome")

    def test_parses_envelope_with_message(self) -> None:
        event = _valid_event()
        envelope = {
            "timestamp": "2026-08-11T10:00:00Z",
            "stream": "stdout",
            "message": json.dumps(event, sort_keys=True, separators=(",", ":")),
        }
        completed = _FakeCompletedProcess(
            stdout=json.dumps(envelope, sort_keys=True) + "\n"
        )
        events = _parse_lines_into_events(completed)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event"], "outbound_attempt_outcome")

    def test_rejects_unparseable_raw_line(self) -> None:
        completed = _FakeCompletedProcess(stdout="not a json line\n")
        with self.assertRaises(UnparseableRailwayOutputError):
            _parse_lines_into_events(completed)

    def test_rejects_envelope_without_message(self) -> None:
        envelope = {"timestamp": "2026-08-11T10:00:00Z"}
        completed = _FakeCompletedProcess(
            stdout=json.dumps(envelope) + "\n"
        )
        with self.assertRaises(UnparseableRailwayOutputError):
            _parse_lines_into_events(completed)

    def test_rejects_envelope_with_invalid_message(self) -> None:
        envelope = {
            "timestamp": "2026-08-11T10:00:00Z",
            "message": "not a json",
        }
        completed = _FakeCompletedProcess(
            stdout=json.dumps(envelope) + "\n"
        )
        with self.assertRaises(UnparseableRailwayOutputError):
            _parse_lines_into_events(completed)

    def test_skips_empty_lines(self) -> None:
        event = _valid_event()
        stdout = (
            "\n"
            + json.dumps(event, sort_keys=True, separators=(",", ":"))
            + "\n\n"
        )
        completed = _FakeCompletedProcess(stdout=stdout)
        events = _parse_lines_into_events(completed)
        self.assertEqual(len(events), 1)


class ExtractEventTest(unittest.TestCase):
    def test_direct_event(self) -> None:
        event = _valid_event()
        line = json.dumps(event, sort_keys=True, separators=(",", ":"))
        parsed = _extract_event_from_line(line)
        self.assertEqual(parsed["event"], event["event"])

    def test_envelope(self) -> None:
        event = _valid_event()
        envelope = {"message": json.dumps(event, sort_keys=True)}
        line = json.dumps(envelope, sort_keys=True)
        parsed = _extract_event_from_line(line)
        self.assertEqual(parsed["event"], event["event"])


class FiltersTest(unittest.TestCase):
    def test_match_event_filters_by_event(self) -> None:
        parser = _build_parser()
        args = parser.parse_args(
            [
                "--project", "p1",
                "--environment", "e1",
                "--service", "s1",
                "--event", "outbound_attempt_outcome",
            ]
        )
        event = _valid_event(event="outbound_attempt_outcome")
        self.assertTrue(_match_event(event, args))
        other = _valid_event(event="twilio_callback_outcome")
        self.assertFalse(_match_event(other, args))

    def test_match_event_info_level_excludes_failure(self) -> None:
        parser = _build_parser()
        args = parser.parse_args(
            [
                "--project", "p1",
                "--environment", "e1",
                "--service", "s1",
                "--level", "info",
            ]
        )
        info = _valid_event(outcome="accepted")
        failure = _valid_event(
            event="provider_worker_unexpected_failure",
            component="provider_worker",
            failure_category="worker_exception",
        )
        self.assertTrue(_match_event(info, args))
        self.assertFalse(_match_event(failure, args))

    def test_match_event_error_level_excludes_outcome(self) -> None:
        parser = _build_parser()
        args = parser.parse_args(
            [
                "--project", "p1",
                "--environment", "e1",
                "--service", "s1",
                "--level", "error",
            ]
        )
        info = _valid_event(outcome="accepted")
        failure = _valid_event(
            event="provider_worker_unexpected_failure",
            component="provider_worker",
            failure_category="worker_exception",
        )
        self.assertFalse(_match_event(info, args))
        self.assertTrue(_match_event(failure, args))

    def test_match_event_since_filter(self) -> None:
        parser = _build_parser()
        args = parser.parse_args(
            [
                "--project", "p1",
                "--environment", "e1",
                "--service", "s1",
                "--since", "2026-08-11T09:00:00+00:00",
            ]
        )
        before = _valid_event(timestamp="2026-08-11T08:00:00+00:00")
        after = _valid_event(timestamp="2026-08-11T10:00:00+00:00")
        self.assertFalse(_match_event(before, args))
        self.assertTrue(_match_event(after, args))


class FormatOutputTest(unittest.TestCase):
    def test_format_output_is_safe_bounded_json(self) -> None:
        parser = _build_parser()
        args = parser.parse_args(
            [
                "--project", "p1",
                "--environment", "e1",
                "--service", "s1",
                "--event", "outbound_attempt_outcome",
                "--level", "info",
                "--limit", "5",
            ]
        )
        rendered = _format_output([_valid_event()], args)
        parsed = json.loads(rendered)
        self.assertEqual(parsed["count"], 1)
        self.assertEqual(parsed["limit"], 5)
        self.assertEqual(parsed["events"][0]["outcome"], "accepted")
        self.assertEqual(
            parsed["filter"]["event"], "outbound_attempt_outcome"
        )
        self.assertEqual(parsed["filter"]["level"], "info")
        for forbidden in (
            "secret-auth-token-value",
            "+5491100000000",
            "leak:",
            "Bearer ",
        ):
            self.assertNotIn(forbidden, rendered)


class MainEntrypointTest(unittest.TestCase):
    def _args(
        self,
        *,
        event: str = "outbound_attempt_outcome",
    ) -> list[str]:
        return [
            "--project", "p1",
            "--environment", "e1",
            "--service", "s1",
            "--event", event,
        ]

    def test_success_returns_zero_and_prints_bounded_json(self) -> None:
        payload = _valid_event(outbox_id=42)
        runner = MagicMock(
            return_value=_FakeCompletedProcess(
                stdout=json.dumps(payload, sort_keys=True) + "\n"
            )
        )
        with contextlib.redirect_stdout(io.StringIO()) as stdout:
            exit_code = main(self._args(), runner=runner)
        self.assertEqual(exit_code, EXIT_OK)
        rendered = json.loads(stdout.getvalue())
        self.assertEqual(rendered["count"], 1)
        self.assertEqual(rendered["events"][0]["outbox_id"], 42)

    def test_no_results_returns_zero_with_empty_array(self) -> None:
        runner = MagicMock(return_value=_FakeCompletedProcess(stdout=""))
        with contextlib.redirect_stdout(io.StringIO()) as stdout:
            exit_code = main(self._args(event="never_emitted"), runner=runner)
        self.assertEqual(exit_code, EXIT_OK)
        rendered = json.loads(stdout.getvalue())
        self.assertEqual(rendered["count"], 0)
        self.assertEqual(rendered["events"], [])

    def test_invalid_arguments_returns_two(self) -> None:
        with self.assertRaises(SystemExit) as ctx:
            with contextlib.redirect_stderr(io.StringIO()):
                main(["--project", "", "--environment", "", "--service", ""])
        self.assertEqual(ctx.exception.code, EXIT_INVALID_ARGUMENTS)

    def test_railway_invocation_failure_returns_three(self) -> None:
        def runner(*_args: Any, **_kwargs: Any) -> Any:
            raise FileNotFoundError("railway")

        with contextlib.redirect_stderr(io.StringIO()) as stderr:
            exit_code = main(self._args(), runner=runner)
        self.assertEqual(exit_code, EXIT_RAILWAY_INVOCATION_FAILED)
        self.assertIn("railway_invocation_failed", stderr.getvalue())

    def test_unparseable_output_returns_four_without_raw_line(self) -> None:
        runner = MagicMock(
            return_value=_FakeCompletedProcess(
                stdout="secret-auth-token-value leak\n"
            )
        )
        with contextlib.redirect_stderr(io.StringIO()) as stderr:
            with contextlib.redirect_stdout(io.StringIO()) as stdout:
                exit_code = main(self._args(), runner=runner)
        self.assertEqual(exit_code, EXIT_RAILWAY_UNPARSEABLE)
        self.assertIn("railway_unparseable_output", stderr.getvalue())
        self.assertNotIn("secret-auth-token-value", stdout.getvalue())
        self.assertNotIn("secret-auth-token-value", stderr.getvalue())

    def test_unparseable_envelope_returns_four(self) -> None:
        envelope = {"timestamp": "x", "message": "not json"}
        runner = MagicMock(
            return_value=_FakeCompletedProcess(
                stdout=json.dumps(envelope) + "\n"
            )
        )
        with contextlib.redirect_stderr(io.StringIO()):
            exit_code = main(self._args(), runner=runner)
        self.assertEqual(exit_code, EXIT_RAILWAY_UNPARSEABLE)

    def test_limit_caps_output(self) -> None:
        events = [
            _valid_event(
                outbox_id=i,
                timestamp=f"2026-08-11T10:00:0{i}+00:00",
            )
            for i in range(5)
        ]
        stdout_text = "\n".join(
            json.dumps(ev, sort_keys=True) for ev in events
        )
        runner = MagicMock(
            return_value=_FakeCompletedProcess(stdout=stdout_text + "\n")
        )
        with contextlib.redirect_stdout(io.StringIO()) as stdout:
            exit_code = main(
                self._args() + ["--limit", "2"], runner=runner
            )
        self.assertEqual(exit_code, EXIT_OK)
        rendered = json.loads(stdout.getvalue())
        self.assertEqual(rendered["count"], 2)


class ModuleBoundaryTest(unittest.TestCase):
    def test_module_does_not_import_sqlalchemy(self) -> None:
        source = (REPO_ROOT / "backend" / "cli" / "query_production_logs.py").read_text()
        tree = ast.parse(source)
        names = {
            node.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Name)
        }
        forbidden = {"SQLAlchemyError", "Session", "create_engine"}
        leaked = forbidden & names
        self.assertEqual(leaked, set(), f"leaked sqlalchemy symbols: {leaked}")

    def test_module_does_not_import_twilio_or_requests(self) -> None:
        source = (REPO_ROOT / "backend" / "cli" / "query_production_logs.py").read_text()
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

    def test_module_has_no_db_session(self) -> None:
        source = (REPO_ROOT / "backend" / "cli" / "query_production_logs.py").read_text()
        for forbidden in ("get_session", "session_factory", "_SessionLocal"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)

    def test_module_has_no_http_endpoint(self) -> None:
        source = (REPO_ROOT / "backend" / "cli" / "query_production_logs.py").read_text()
        for forbidden in ("@app.", "@router.", "FastAPI(", "APIRouter("):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)


class DefaultLimitTest(unittest.TestCase):
    def test_default_limit_is_bounded(self) -> None:
        self.assertEqual(DEFAULT_LIMIT, 100)
        self.assertEqual(MAX_LIMIT, 1000)

    def test_railway_command_uses_default_json_flag(self) -> None:
        parser = _build_parser()
        args = parser.parse_args(
            ["--project", "p1", "--environment", "e1", "--service", "s1"]
        )
        cmd = _build_railway_command(args)
        self.assertIn("--json", cmd)

    def test_timeout_is_bounded(self) -> None:
        self.assertGreaterEqual(RAILWAY_TIMEOUT_SECONDS, 1)
        self.assertLessEqual(RAILWAY_TIMEOUT_SECONDS, 300)


if __name__ == "__main__":
    unittest.main(verbosity=2)
