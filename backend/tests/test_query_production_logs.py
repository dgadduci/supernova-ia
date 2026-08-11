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
        # The operator's --limit must be applied to the SOURCE
        # query (Railway's --lines) so the platform returns at most
        # that many historical lines, not just the array cap.
        self.assertIn("--lines", cmd)
        lines_index = cmd.index("--lines")
        self.assertEqual(cmd[lines_index + 1], str(DEFAULT_LIMIT))

    def test_build_railway_command_uses_custom_limit(self) -> None:
        parser = _build_parser()
        args = parser.parse_args(
            [
                "--project", "p1",
                "--environment", "e1",
                "--service", "s1",
                "--limit", "37",
            ]
        )
        cmd = _build_railway_command(args)
        lines_index = cmd.index("--lines")
        self.assertEqual(cmd[lines_index + 1], "37")

    def test_build_railway_command_passes_since_when_supplied(self) -> None:
        parser = _build_parser()
        args = parser.parse_args(
            [
                "--project", "p1",
                "--environment", "e1",
                "--service", "s1",
                "--since", "2026-08-11T10:00:00Z",
            ]
        )
        cmd = _build_railway_command(args)
        self.assertIn("--since", cmd)
        since_index = cmd.index("--since")
        self.assertEqual(cmd[since_index + 1], "2026-08-11T10:00:00Z")

    def test_build_railway_command_omits_since_when_absent(self) -> None:
        parser = _build_parser()
        args = parser.parse_args(
            ["--project", "p1", "--environment", "e1", "--service", "s1"]
        )
        cmd = _build_railway_command(args)
        self.assertNotIn("--since", cmd)

    def test_build_railway_command_does_not_push_event_to_filter(self) -> None:
        # Railway's --filter is a text-search on the envelope
        # ``message`` field, which is empty for our structured
        # events. Pushing ``--event`` as ``--filter`` therefore
        # returns zero matches from Railway even when the events
        # are present, so the CLI applies ``--event`` ONLY as a
        # local filter on the parsed events and MUST NOT forward
        # it to Railway.
        parser = _build_parser()
        args = parser.parse_args(
            [
                "--project", "p1",
                "--environment", "e1",
                "--service", "s1",
                "--event", "outbound_attempt_outcome",
            ]
        )
        cmd = _build_railway_command(args)
        self.assertNotIn(
            "--filter",
            cmd,
            f"Railway command must not push --event to --filter; "
            f"got cmd={cmd!r}",
        )
        # ``--event`` value must never reach the source command
        # under any flag name; the local filter chain handles it.
        self.assertNotIn("outbound_attempt_outcome", cmd)

    def test_build_railway_command_omits_filter_when_event_absent(self) -> None:
        parser = _build_parser()
        args = parser.parse_args(
            ["--project", "p1", "--environment", "e1", "--service", "s1"]
        )
        cmd = _build_railway_command(args)
        self.assertNotIn("--filter", cmd)

    def test_build_railway_command_keeps_lines_and_since_with_event(self) -> None:
        # ``--lines`` and ``--since`` are the only source-side
        # filters the CLI forwards to Railway. They MUST stay
        # present even when ``--event`` is set so the source query
        # remains bounded.
        parser = _build_parser()
        args = parser.parse_args(
            [
                "--project", "p1",
                "--environment", "e1",
                "--service", "s1",
                "--limit", "5",
                "--since", "2026-08-11T10:00:00Z",
                "--event", "outbound_attempt_outcome",
            ]
        )
        cmd = _build_railway_command(args)
        self.assertIn("--lines", cmd)
        lines_index = cmd.index("--lines")
        self.assertEqual(cmd[lines_index + 1], "5")
        self.assertIn("--since", cmd)
        since_index = cmd.index("--since")
        self.assertEqual(cmd[since_index + 1], "2026-08-11T10:00:00Z")
        self.assertNotIn("--filter", cmd)

    def test_build_railway_command_uses_only_supported_flags(self) -> None:
        # Defensive: the CLI must never invent flags Railway does
        # not document. Anything that looks suspicious (single
        # dash with multiple letters, etc.) is caught here.
        parser = _build_parser()
        args = parser.parse_args(
            [
                "--project", "p1",
                "--environment", "e1",
                "--service", "s1",
                "--limit", "5",
                "--since", "2026-08-11T10:00:00Z",
                "--event", "outbound_attempt_outcome",
            ]
        )
        cmd = _build_railway_command(args)
        allowed_flags = {
            "logs",
            "--project",
            "--environment",
            "--service",
            "--json",
            "--lines",
            "--since",
        }
        for token in cmd:
            if token == RAILWAY_BINARY:
                continue
            if token in {"p1", "e1", "s1", "5", "2026-08-11T10:00:00Z"}:
                continue
            if token.startswith("--"):
                self.assertIn(
                    token,
                    allowed_flags,
                    f"unsupported Railway flag in cmd: {cmd}",
                )

    def test_validate_args_rejects_unsafe_event_token(self) -> None:
        parser = _build_parser()
        args = parser.parse_args(
            [
                "--project", "p1",
                "--environment", "e1",
                "--service", "s1",
                "--event", "not a catalogue token",
            ]
        )
        with self.assertRaises(SystemExit) as ctx:
            with contextlib.redirect_stderr(io.StringIO()):
                _validate_args(args)
        self.assertEqual(ctx.exception.code, EXIT_INVALID_ARGUMENTS)

    def test_validate_args_rejects_event_with_quote(self) -> None:
        # ``--event`` is matched exactly against the ``event``
        # attribute on the parsed events (see ``_match_event``) and
        # the catalogue is a closed alphanumeric allowlist. An
        # event name carrying characters outside that allowlist
        # could never match a real event and would also defeat the
        # safe-content contract; the validation rejects it up
        # front so the CLI never accepts a non-catalogue token.
        parser = _build_parser()
        args = parser.parse_args(
            [
                "--project", "p1",
                "--environment", "e1",
                "--service", "s1",
                "--event", 'he"llo',
            ]
        )
        with self.assertRaises(SystemExit) as ctx:
            with contextlib.redirect_stderr(io.StringIO()):
                _validate_args(args)
        self.assertEqual(ctx.exception.code, EXIT_INVALID_ARGUMENTS)

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
        # Railway promised a JSON contract via --json; non-JSON is a
        # contract violation and exits with the documented code.
        completed = _FakeCompletedProcess(stdout="not a json line\n")
        with self.assertRaises(UnparseableRailwayOutputError):
            _parse_lines_into_events(completed)

    def test_skips_envelope_without_message(self) -> None:
        # A plain Railway envelope (access log, deploy metadata,
        # etc.) without a ``message`` field is NOT a structured
        # event and is skipped silently.
        envelope = {"timestamp": "2026-08-11T10:00:00Z"}
        completed = _FakeCompletedProcess(
            stdout=json.dumps(envelope) + "\n"
        )
        events = _parse_lines_into_events(completed)
        self.assertEqual(events, [])

    def test_skips_envelope_with_non_json_message(self) -> None:
        # An envelope whose ``message`` is free-form stdout/stderr
        # is also skipped silently.
        envelope = {
            "timestamp": "2026-08-11T10:00:00Z",
            "message": "INFO:twilio_outbound:dispatch ready",
        }
        completed = _FakeCompletedProcess(
            stdout=json.dumps(envelope, sort_keys=True) + "\n"
        )
        events = _parse_lines_into_events(completed)
        self.assertEqual(events, [])

    def test_skips_envelope_with_unrelated_json_message(self) -> None:
        # An envelope whose ``message`` is JSON but NOT our event
        # shape (e.g., a third-party library JSON dump) is skipped.
        envelope = {
            "timestamp": "2026-08-11T10:00:00Z",
            "message": json.dumps(
                {"level": "info", "logger": "uvicorn", "msg": "ready"}
            ),
        }
        completed = _FakeCompletedProcess(
            stdout=json.dumps(envelope, sort_keys=True) + "\n"
        )
        events = _parse_lines_into_events(completed)
        self.assertEqual(events, [])

    def test_rejects_envelope_with_invalid_structured_message(self) -> None:
        # An envelope whose ``message`` claims to be a structured
        # event (carries event + schema_version) but violates the
        # contract IS surfaced as an unparseable-output failure.
        envelope = {
            "timestamp": "2026-08-11T10:00:00Z",
            "message": json.dumps(
                {
                    "event": "ghost_event",
                    "schema_version": 1,
                    "component": "provider_worker",
                    "outcome": "completed",
                    "timestamp": "2026-08-11T10:00:00+00:00",
                }
            ),
        }
        completed = _FakeCompletedProcess(
            stdout=json.dumps(envelope, sort_keys=True) + "\n"
        )
        with self.assertRaises(UnparseableRailwayOutputError):
            _parse_lines_into_events(completed)

    def test_mixed_railway_output_returns_only_structured_events(self) -> None:
        # Real Railway output interleaves access logs, prior
        # catalogued ``provider_worker_cycle`` events, free-form
        # stdout and our structured events. The CLI must return
        # only the catalogued events and skip the rest silently.
        structured_event = _valid_event()
        previous_cycle = _valid_event(
            event="provider_worker_cycle",
            component="provider_worker",
            outcome="completed",
            timestamp="2026-08-11T09:55:00+00:00",
        )
        stdout = "\n".join(
            [
                json.dumps(
                    {
                        "timestamp": "2026-08-11T09:55:10Z",
                        "stream": "stdout",
                        "message": "INFO sqlalchemy.engine created engine",
                    },
                    sort_keys=True,
                ),
                json.dumps(
                    {
                        "timestamp": "2026-08-11T09:55:11Z",
                        "stream": "stdout",
                        "message": json.dumps(previous_cycle),
                    },
                    sort_keys=True,
                ),
                json.dumps(
                    {
                        "timestamp": "2026-08-11T09:55:12Z",
                        "stream": "stdout",
                        "message": "INFO uvicorn server listening",
                    },
                    sort_keys=True,
                ),
                json.dumps(structured_event, sort_keys=True),
                "",
            ]
        )
        completed = _FakeCompletedProcess(stdout=stdout)
        events = _parse_lines_into_events(completed)
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["event"], "provider_worker_cycle")
        self.assertEqual(events[1]["event"], "outbound_attempt_outcome")

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
        assert parsed is not None
        self.assertEqual(parsed["event"], event["event"])

    def test_direct_event_with_railway_envelope_fields(self) -> None:
        # Real Railway --json output augments every JSON log line
        # with ``level`` (always ``"info"``) and ``message`` (empty
        # for structured events) platform envelope fields. The CLI
        # must recognise the line as our event AND strip those
        # platform fields so the catalogue contract stays strict.
        event = _valid_event()
        line_payload = {
            **event,
            "level": "info",
            "message": "",
        }
        line = json.dumps(line_payload, sort_keys=True, separators=(",", ":"))
        parsed = _extract_event_from_line(line)
        assert parsed is not None
        self.assertEqual(parsed["event"], event["event"])
        self.assertEqual(parsed["outcome"], event["outcome"])
        self.assertNotIn("level", parsed)
        self.assertNotIn("message", parsed)

    def test_envelope(self) -> None:
        event = _valid_event()
        envelope = {"message": json.dumps(event, sort_keys=True)}
        line = json.dumps(envelope, sort_keys=True)
        parsed = _extract_event_from_line(line)
        assert parsed is not None
        self.assertEqual(parsed["event"], event["event"])

    def test_envelope_wrapping_railway_envelope_around_inner_event(self) -> None:
        # If Railway wraps the structured event under a top-level
        # ``message`` field (e.g. when a future deployment shape
        # changes), the inner event still parses cleanly because the
        # platform-level ``level`` / ``message`` fields on the outer
        # envelope do not collide with the catalogue.
        event = _valid_event()
        outer = {
            "level": "info",
            "message": json.dumps(event, sort_keys=True, separators=(",", ":")),
            "timestamp": "2026-08-11T10:00:00Z",
        }
        line = json.dumps(outer, sort_keys=True, separators=(",", ":"))
        parsed = _extract_event_from_line(line)
        assert parsed is not None
        self.assertEqual(parsed["event"], event["event"])
        self.assertNotIn("level", parsed)
        self.assertNotIn("message", parsed)

    def test_skip_silently_for_access_log_envelope(self) -> None:
        envelope = {"timestamp": "2026-08-11T10:00:00Z", "stream": "stdout"}
        line = json.dumps(envelope, sort_keys=True)
        self.assertIsNone(_extract_event_from_line(line))

    def test_skip_silently_for_free_form_message_envelope(self) -> None:
        envelope = {
            "timestamp": "2026-08-11T10:00:00Z",
            "message": "INFO:twilio_outbound:dispatch ready",
        }
        line = json.dumps(envelope, sort_keys=True)
        self.assertIsNone(_extract_event_from_line(line))

    def test_unparseable_for_envelope_with_invalid_structured_message(self) -> None:
        envelope = {
            "timestamp": "2026-08-11T10:00:00Z",
            "message": json.dumps(
                {
                    "event": "ghost_event",
                    "schema_version": 1,
                    "component": "provider_worker",
                    "outcome": "completed",
                    "timestamp": "2026-08-11T10:00:00+00:00",
                }
            ),
        }
        line = json.dumps(envelope, sort_keys=True)
        with self.assertRaises(UnparseableRailwayOutputError):
            _extract_event_from_line(line)

    def test_unparseable_for_non_json_line(self) -> None:
        with self.assertRaises(UnparseableRailwayOutputError):
            _extract_event_from_line("not a json line at all")


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
        # An envelope whose ``message`` claims to be a structured
        # event but violates the contract IS a contract violation
        # and surfaces as exit 4.
        envelope = {
            "timestamp": "2026-08-11T10:00:00Z",
            "message": json.dumps(
                {
                    "event": "ghost_event",
                    "schema_version": 1,
                    "component": "provider_worker",
                    "outcome": "completed",
                    "timestamp": "2026-08-11T10:00:00+00:00",
                }
            ),
        }
        runner = MagicMock(
            return_value=_FakeCompletedProcess(
                stdout=json.dumps(envelope) + "\n"
            )
        )
        with contextlib.redirect_stderr(io.StringIO()):
            exit_code = main(self._args(), runner=runner)
        self.assertEqual(exit_code, EXIT_RAILWAY_UNPARSEABLE)

    def test_access_log_envelope_returns_zero_with_bounded_events(self) -> None:
        # An envelope without a structured ``message`` MUST be
        # skipped: it must not turn into exit 4, and the CLI must
        # only return the catalogued events it actually finds.
        access_log = {
            "timestamp": "2026-08-11T10:00:00Z",
            "stream": "stdout",
        }
        event = _valid_event()
        stdout_text = (
            json.dumps(access_log, sort_keys=True)
            + "\n"
            + json.dumps(event, sort_keys=True)
            + "\n"
        )
        runner = MagicMock(
            return_value=_FakeCompletedProcess(stdout=stdout_text)
        )
        with contextlib.redirect_stdout(io.StringIO()) as stdout:
            exit_code = main(self._args(), runner=runner)
        self.assertEqual(exit_code, EXIT_OK)
        rendered = json.loads(stdout.getvalue())
        self.assertEqual(rendered["count"], 1)
        self.assertEqual(
            rendered["events"][0]["event"], "outbound_attempt_outcome"
        )

    def test_railway_envelope_event_returns_zero_with_stripped_fields(
        self,
    ) -> None:
        # Real Railway --json output augments structured events with
        # ``level`` and ``message`` platform envelope fields. The
        # CLI must still treat the line as our catalogued event and
        # MUST strip those platform fields before returning the
        # event in the bounded array, otherwise the catalogue
        # contract would leak Railway metadata into operator output.
        event = _valid_event(outbox_id=77)
        augmented_event = {
            **event,
            "level": "info",
            "message": "",
        }
        stdout_text = (
            json.dumps(augmented_event, sort_keys=True) + "\n"
        )
        runner = MagicMock(
            return_value=_FakeCompletedProcess(stdout=stdout_text)
        )
        with contextlib.redirect_stdout(io.StringIO()) as stdout:
            exit_code = main(self._args(), runner=runner)
        self.assertEqual(exit_code, EXIT_OK)
        rendered = stdout.getvalue()
        parsed = json.loads(rendered)
        self.assertEqual(parsed["count"], 1)
        returned_event = parsed["events"][0]
        # The platform fields never reach the returned event - the
        # CLI returns the original application payload.
        self.assertNotIn("level", returned_event)
        self.assertNotIn("message", returned_event)
        self.assertEqual(
            returned_event["event"], "outbound_attempt_outcome"
        )
        self.assertEqual(returned_event["outbox_id"], 77)

    def test_real_railway_mixed_output_is_parsed(self) -> None:
        # Defensive: a small reproducible slice of the actual
        # Railway --json output the platform returns for our app
        # deployment must produce a successful exit code with the
        # bounded catalogued events returned and the platform-level
        # ``level`` / ``message`` fields stripped. The slice mixes
        # wrapped free-form stdout lines with structured events that
        # carry Railway's envelope fields.
        wrapped_text = (
            '{"level":"info","message":"sent=0 retry_scheduled=0 '
            'failed_terminal=0 no_due_row=1 technical_failure=0 '
            'total=1","timestamp":"2026-08-11T10:00:00Z"}'
        )
        worker_cycle = (
            '{"level":"info","message":"","event":"provider_worker_cycle",'
            '"outcome":"completed","schema_version":1,'
            '"component":"provider_worker",'
            '"timestamp":"2026-08-11T10:00:00+00:00"}'
        )
        outbound_event = (
            '{"level":"info","message":"","event":"outbound_attempt_outcome",'
            '"outcome":"no_due_row","schema_version":1,'
            '"component":"outbound_dispatch",'
            '"timestamp":"2026-08-11T10:00:01+00:00"}'
        )
        stdout_text = (
            wrapped_text + "\n"
            + worker_cycle + "\n"
            + outbound_event + "\n"
        )
        runner = MagicMock(
            return_value=_FakeCompletedProcess(stdout=stdout_text)
        )
        with contextlib.redirect_stdout(io.StringIO()) as stdout:
            exit_code = main(
                self._args(event="outbound_attempt_outcome"),
                runner=runner,
            )
        self.assertEqual(exit_code, EXIT_OK)
        rendered = json.loads(stdout.getvalue())
        self.assertEqual(rendered["count"], 1)
        self.assertEqual(
            rendered["events"][0]["event"], "outbound_attempt_outcome"
        )
        self.assertNotIn("level", rendered["events"][0])
        self.assertNotIn("message", rendered["events"][0])
        # The wrapped free-form stdout line must NEVER be reflected
        # back into operator-facing output.
        self.assertNotIn("sent=0", rendered)

    def test_mixed_railway_output_returns_only_structured_events(self) -> None:
        # The CLI must skip plain Railway envelopes / free-form
        # stdout silently while returning only catalogued events.
        previous_cycle = json.dumps(
            _valid_event(
                event="provider_worker_cycle",
                component="provider_worker",
                outcome="completed",
                timestamp="2026-08-11T09:55:00+00:00",
            )
        )
        target_event = _valid_event()
        stdout_text = (
            json.dumps(
                {
                    "timestamp": "2026-08-11T09:55:10Z",
                    "stream": "stdout",
                    "message": "INFO sqlalchemy.engine created engine",
                },
                sort_keys=True,
            )
            + "\n"
            + json.dumps(
                {
                    "timestamp": "2026-08-11T09:55:11Z",
                    "stream": "stdout",
                    "message": previous_cycle,
                },
                sort_keys=True,
            )
            + "\n"
            + json.dumps(target_event, sort_keys=True)
            + "\n"
        )
        runner = MagicMock(
            return_value=_FakeCompletedProcess(stdout=stdout_text)
        )
        with contextlib.redirect_stdout(io.StringIO()) as stdout:
            exit_code = main(
                self._args(event="provider_worker_cycle"), runner=runner
            )
        self.assertEqual(exit_code, EXIT_OK)
        rendered = json.loads(stdout.getvalue())
        self.assertEqual(rendered["count"], 1)
        self.assertEqual(
            rendered["events"][0]["event"], "provider_worker_cycle"
        )
        self.assertNotIn("sqlalchemy", stdout.getvalue())

    def test_event_filter_is_applied_locally_on_mixed_output(self) -> None:
        # Reproduces the production failure mode: Railway returns a
        # mix of structured events (with the catalogue fields as
        # top-level attributes and an empty ``message`` envelope)
        # and free-form stdout lines. The CLI MUST apply ``--event``
        # locally after parsing so the bounded array contains only
        # the requested event name; Railway's source-side text
        # search cannot see our catalogue fields, so the CLI never
        # relies on it.
        outbound_event = _valid_event()
        worker_cycle = _valid_event(
            event="provider_worker_cycle",
            component="provider_worker",
            outcome="completed",
            timestamp="2026-08-11T09:55:00+00:00",
        )
        stdout_text = "\n".join(
            [
                json.dumps(
                    {
                        "level": "info",
                        "message": "provider_worker_cycle cycle_index=1",
                        "timestamp": "2026-08-11T09:55:09Z",
                    },
                    sort_keys=True,
                ),
                json.dumps(worker_cycle, sort_keys=True),
                json.dumps(outbound_event, sort_keys=True),
                json.dumps(
                    {
                        "level": "info",
                        "message": (
                            "mensaje_id=70 outcome=sent identificador_proveedor="
                            "SM829a1718b0ef28ec760d7ff79e480722"
                            " durable_state=accepted"
                        ),
                        "timestamp": "2026-08-11T09:55:13Z",
                    },
                    sort_keys=True,
                ),
                "",
            ]
        )
        runner = MagicMock(
            return_value=_FakeCompletedProcess(stdout=stdout_text)
        )
        with contextlib.redirect_stdout(io.StringIO()) as stdout:
            exit_code = main(
                self._args(event="outbound_attempt_outcome"), runner=runner
            )
        self.assertEqual(exit_code, EXIT_OK)
        rendered = json.loads(stdout.getvalue())
        self.assertEqual(rendered["count"], 1)
        self.assertEqual(
            rendered["events"][0]["event"], "outbound_attempt_outcome"
        )
        self.assertEqual(
            rendered["filter"]["event"], "outbound_attempt_outcome"
        )
        # The free-form lines and the unrelated worker_cycle must
        # not appear in the bounded array; the raw SID and any
        # other sensitive identifier must never be reflected back.
        joined = stdout.getvalue()
        self.assertNotIn("SM829a1718b0ef28ec760d7ff79e480722", joined)
        self.assertNotIn("provider_worker_cycle", joined)

    def test_event_filter_does_not_pass_event_name_to_railway(self) -> None:
        # Defensive: when ``--event`` is supplied, the operator's
        # event token MUST NOT appear anywhere in the Railway
        # subprocess argument list. Otherwise Railway's text search
        # would always return zero matches and the operator would
        # see a misleading empty array.
        captured_cmd: dict[str, list[str]] = {}

        def _runner(cmd: list[str], **_kwargs: Any) -> Any:
            captured_cmd["cmd"] = list(cmd)
            return _FakeCompletedProcess(stdout="")

        with contextlib.redirect_stdout(io.StringIO()):
            exit_code = main(
                self._args(event="outbound_attempt_outcome"),
                runner=_runner,
            )
        self.assertEqual(exit_code, EXIT_OK)
        cmd = captured_cmd["cmd"]
        self.assertNotIn("--filter", cmd)
        self.assertNotIn("outbound_attempt_outcome", cmd)

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
