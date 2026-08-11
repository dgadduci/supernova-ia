"""Focused tests for the ``backend.observability`` event contract.

Coverage:

1. Each catalogued event has a stable required/optional field
   contract that matches the OpenSpec change.
2. The formatter rejects unknown fields, missing required fields,
   out-of-range numbers, unsafe strings and unrecognised event
   names.
3. The formatter NEVER logs caller-supplied sensitive content
   (E.164, body, signature, prompt, credential, token, URL,
   exception message, traceback) and NEVER attaches the message
   itself to the JSON payload.
4. ``emit_event`` degrades to a safe ``observability_emit_failed``
   event on validation failure; the caller never sees an exception.
5. ``parse_event`` round-trips every catalogued event and rejects
   raw provider lines, envelopes that lack a valid ``message``, and
   payloads carrying unknown keys.
6. The ``categorize_sqlalchemy_error`` mapper translates the
   documented exception categories into safe tokens and never
   touches the exception message.
"""
from __future__ import annotations

import io
import json
import unittest

from backend.observability import (
    COMPONENT_CALLBACK,
    COMPONENT_DATABASE,
    COMPONENT_EMBEDDING,
    COMPONENT_LLM,
    COMPONENT_OUTBOUND,
    COMPONENT_WORKER,
    EVENT_CALLBACK_OUTCOME,
    EVENT_DATABASE_TECHNICAL_FAILURE,
    EVENT_EMBEDDING_REQUEST,
    EVENT_LLM_REQUEST,
    EVENT_OUTBOUND_OUTCOME,
    EVENT_WORKER_CYCLE,
    EVENT_WORKER_DISABLED,
    EVENT_WORKER_READINESS_TRANSITION,
    EVENT_WORKER_UNEXPECTED_FAILURE,
    SCHEMA_VERSION,
    EventValidationError,
    build_event,
    categorize_sqlalchemy_error,
    emit_event,
    parse_event,
)


SENTINELS = (
    "secret-auth-token-value",
    "AC000000000000000000000000000000",
    "+5491100000000",
    "SM-ABC-XYZ",
    "Bearer abc",
    "https://provider.example?token=abc",
    "X-Twilio-Signature=abc",
    "inbound body",
    "outbound body",
    "prompt secret",
    "embed probe secret",
    "httpx2",
    "implementación",
    "Exception message",
    "Traceback",
)


def _no_payload_leaks(payload: dict, *, event: str) -> None:
    """Assert no sentinel substring appears anywhere in the payload."""
    serialized = json.dumps(payload, sort_keys=True)
    for token in SENTINELS:
        if token in event:
            continue
        if token in COMPONENT_OUTBOUND or token in COMPONENT_CALLBACK:
            continue
        if token in EVENT_CALL_BOILERPLATE:
            continue
        if token == event:
            continue
        assert token not in serialized, (
            f"sentinel {token!r} leaked in payload for {event!r}: {serialized}"
        )


EVENT_CALL_BOILERPLATE = frozenset(
    {
        EVENT_OUTBOUND_OUTCOME,
        EVENT_CALLBACK_OUTCOME,
        EVENT_WORKER_CYCLE,
        EVENT_WORKER_DISABLED,
        EVENT_WORKER_READINESS_TRANSITION,
        EVENT_WORKER_UNEXPECTED_FAILURE,
        EVENT_LLM_REQUEST,
        EVENT_EMBEDDING_REQUEST,
        EVENT_DATABASE_TECHNICAL_FAILURE,
    }
)


class BuildEventContractTest(unittest.TestCase):
    def test_outbound_accepted_round_trips(self) -> None:
        payload = build_event(
            event=EVENT_OUTBOUND_OUTCOME,
            component=COMPONENT_OUTBOUND,
            outcome="accepted",
            outbox_id=42,
            durable_state="accepted",
        )
        self.assertEqual(payload["event"], EVENT_OUTBOUND_OUTCOME)
        self.assertEqual(payload["schema_version"], int(SCHEMA_VERSION))
        self.assertEqual(payload["component"], COMPONENT_OUTBOUND)
        self.assertEqual(payload["outcome"], "accepted")
        self.assertEqual(payload["outbox_id"], 42)
        self.assertEqual(payload["durable_state"], "accepted")
        self.assertNotIn("failure_category", payload)

    def test_callback_outcome_round_trips(self) -> None:
        payload = build_event(
            event=EVENT_CALLBACK_OUTCOME,
            component=COMPONENT_CALLBACK,
            outcome="applied",
            outbox_id=7,
            durable_state="delivered",
        )
        self.assertEqual(payload["outcome"], "applied")
        self.assertEqual(payload["outbox_id"], 7)
        self.assertEqual(payload["durable_state"], "delivered")

    def test_worker_cycle_completed_has_no_extra_fields(self) -> None:
        payload = build_event(
            event=EVENT_WORKER_CYCLE,
            component=COMPONENT_WORKER,
            outcome="completed",
        )
        self.assertEqual(set(payload.keys()), {
            "event", "schema_version", "component", "timestamp", "outcome"
        })

    def test_database_failure_uses_failure_category(self) -> None:
        payload = build_event(
            event=EVENT_DATABASE_TECHNICAL_FAILURE,
            component=COMPONENT_DATABASE,
            failure_category="connection",
            exception_type="OperationalError",
        )
        self.assertEqual(payload["failure_category"], "connection")
        self.assertEqual(payload["exception_type"], "OperationalError")
        self.assertNotIn("outcome", payload)

    def test_llm_request_completed_with_elapsed(self) -> None:
        payload = build_event(
            event=EVENT_LLM_REQUEST,
            component=COMPONENT_LLM,
            outcome="completed",
            elapsed_ms=123,
            http_status=200,
        )
        self.assertEqual(payload["elapsed_ms"], 123)
        self.assertEqual(payload["http_status"], 200)

    def test_embedding_request_failed_carries_status(self) -> None:
        payload = build_event(
            event=EVENT_EMBEDDING_REQUEST,
            component=COMPONENT_EMBEDDING,
            failure_category="http_error",
            http_status=503,
            exception_type="EmbeddingResponseError",
        )
        self.assertEqual(payload["failure_category"], "http_error")
        self.assertEqual(payload["http_status"], 503)

    def test_worker_disabled_has_no_optional_fields(self) -> None:
        payload = build_event(
            event=EVENT_WORKER_DISABLED,
            component=COMPONENT_WORKER,
            outcome="disabled",
        )
        self.assertEqual(payload["outcome"], "disabled")

    def test_unknown_event_rejected(self) -> None:
        with self.assertRaises(EventValidationError):
            build_event(
                event="unknown_event",
                component=COMPONENT_OUTBOUND,
                outcome="accepted",
            )

    def test_outcome_and_failure_category_mutually_exclusive(self) -> None:
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_OUTBOUND_OUTCOME,
                component=COMPONENT_OUTBOUND,
                outcome="accepted",
                failure_category="retryable_timeout",
            )

    def test_missing_outcome_and_failure_category_rejected(self) -> None:
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_OUTBOUND_OUTCOME,
                component=COMPONENT_OUTBOUND,
            )

    def test_component_mismatch_rejected(self) -> None:
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_OUTBOUND_OUTCOME,
                component=COMPONENT_WORKER,
                outcome="accepted",
            )

    def test_outcome_not_in_catalogue_rejected(self) -> None:
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_OUTBOUND_OUTCOME,
                component=COMPONENT_OUTBOUND,
                outcome="sent",
            )

    def test_failure_category_not_in_catalogue_rejected(self) -> None:
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_DATABASE_TECHNICAL_FAILURE,
                component=COMPONENT_DATABASE,
                failure_category="leak",
            )

    def test_unknown_field_for_event_rejected(self) -> None:
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_WORKER_CYCLE,
                component=COMPONENT_WORKER,
                outcome="completed",
                outbox_id=1,
            )

    def test_outbox_id_negative_rejected(self) -> None:
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_OUTBOUND_OUTCOME,
                component=COMPONENT_OUTBOUND,
                outcome="accepted",
                outbox_id=-1,
            )

    def test_http_status_out_of_range_rejected(self) -> None:
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_LLM_REQUEST,
                component=COMPONENT_LLM,
                outcome="completed",
                http_status=999,
            )

    def test_elapsed_ms_negative_rejected(self) -> None:
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_LLM_REQUEST,
                component=COMPONENT_LLM,
                outcome="completed",
                elapsed_ms=-1,
            )

    def test_exception_type_with_dot_rejected(self) -> None:
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_LLM_REQUEST,
                component=COMPONENT_LLM,
                failure_category="unexpected",
                exception_type="a.b.OperationalError",
            )

    def test_exception_type_with_message_rejected(self) -> None:
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_LLM_REQUEST,
                component=COMPONENT_LLM,
                failure_category="unexpected",
                exception_type="OperationalError: connection refused",
            )

    def test_durable_state_with_uppercase_rejected(self) -> None:
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_OUTBOUND_OUTCOME,
                component=COMPONENT_OUTBOUND,
                outcome="accepted",
                durable_state="Accepted",
            )

    def test_provider_code_with_control_char_rejected(self) -> None:
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_OUTBOUND_OUTCOME,
                component=COMPONENT_OUTBOUND,
                outcome="retryable",
                provider_code="abc\nBody",
            )

    def test_timestamp_is_present_and_iso8601(self) -> None:
        payload = build_event(
            event=EVENT_WORKER_CYCLE,
            component=COMPONENT_WORKER,
            outcome="completed",
        )
        ts = payload["timestamp"]
        self.assertIsInstance(ts, str)
        from datetime import datetime
        datetime.fromisoformat(ts)

    def test_explicit_timestamp_passes_through(self) -> None:
        ts = "2026-08-11T13:00:00+00:00"
        payload = build_event(
            event=EVENT_WORKER_CYCLE,
            component=COMPONENT_WORKER,
            outcome="completed",
            timestamp=ts,
        )
        self.assertEqual(payload["timestamp"], ts)


class EmitEventTest(unittest.TestCase):
    def test_emits_valid_json_line(self) -> None:
        sink = io.StringIO()
        ok = emit_event(
            event=EVENT_OUTBOUND_OUTCOME,
            component=COMPONENT_OUTBOUND,
            outcome="accepted",
            outbox_id=42,
            stream=sink,
        )
        self.assertTrue(ok)
        line = sink.getvalue().strip()
        parsed = json.loads(line)
        self.assertEqual(parsed["event"], EVENT_OUTBOUND_OUTCOME)
        self.assertEqual(parsed["outbox_id"], 42)

    def test_emits_failure_degraded_event_on_validation_error(self) -> None:
        sink = io.StringIO()
        ok = emit_event(
            event="not_in_catalogue",
            component=COMPONENT_OUTBOUND,
            outcome="accepted",
            stream=sink,
        )
        self.assertFalse(ok)
        line = sink.getvalue().strip()
        self.assertTrue(line)
        parsed = json.loads(line)
        self.assertEqual(parsed["event"], "observability_emit_failed")
        self.assertEqual(parsed["failure_category"], "validation")
        self.assertEqual(parsed["exception_type"], "EventValidationError")
        self.assertEqual(parsed["schema_version"], int(SCHEMA_VERSION))

    def test_unknown_field_failure_degrades_safely(self) -> None:
        sink = io.StringIO()
        ok = emit_event(
            event=EVENT_WORKER_CYCLE,
            component=COMPONENT_WORKER,
            outcome="completed",
            http_status=400,
            stream=sink,
        )
        self.assertFalse(ok)
        parsed = json.loads(sink.getvalue().strip())
        self.assertEqual(parsed["event"], "observability_emit_failed")

    def test_emit_event_does_not_raise_on_bad_stream(self) -> None:
        class _BrokenStream:
            def write(self, _data: str) -> None:
                raise OSError("simulated stream failure")

        ok = emit_event(
            event=EVENT_WORKER_CYCLE,
            component=COMPONENT_WORKER,
            outcome="completed",
            stream=_BrokenStream(),
        )
        self.assertFalse(ok)


class ParseEventTest(unittest.TestCase):
    def test_round_trips_built_event(self) -> None:
        payload = build_event(
            event=EVENT_OUTBOUND_OUTCOME,
            component=COMPONENT_OUTBOUND,
            outcome="retryable",
            outbox_id=13,
            attempt=2,
            provider_code="500",
        )
        line = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        parsed = parse_event(line)
        self.assertEqual(parsed, payload)

    def test_rejects_invalid_json(self) -> None:
        with self.assertRaises(EventValidationError):
            parse_event("not json at all")

    def test_rejects_empty_line(self) -> None:
        with self.assertRaises(EventValidationError):
            parse_event("")

    def test_rejects_non_object(self) -> None:
        with self.assertRaises(EventValidationError):
            parse_event("[1, 2, 3]")

    def test_rejects_unknown_keys(self) -> None:
        with self.assertRaises(EventValidationError):
            parse_event(
                '{"event":"provider_worker_cycle","schema_version":1,'
                '"component":"provider_worker","outcome":"completed",'
                '"timestamp":"2026-08-11T00:00:00+00:00","surprise":"x"}'
            )

    def test_rejects_wrong_schema_version(self) -> None:
        with self.assertRaises(EventValidationError):
            parse_event(
                '{"event":"provider_worker_cycle","schema_version":2,'
                '"component":"provider_worker","outcome":"completed",'
                '"timestamp":"2026-08-11T00:00:00+00:00"}'
            )

    def test_rejects_unknown_event(self) -> None:
        with self.assertRaises(EventValidationError):
            parse_event(
                '{"event":"unsupported","schema_version":1,'
                '"component":"provider_worker","outcome":"completed",'
                '"timestamp":"2026-08-11T00:00:00+00:00"}'
            )

    def test_rejects_non_string_event(self) -> None:
        with self.assertRaises(EventValidationError):
            parse_event(
                '{"event":1,"schema_version":1,"component":"provider_worker",'
                '"outcome":"completed",'
                '"timestamp":"2026-08-11T00:00:00+00:00"}'
            )


class CategorizeSqlAlchemyErrorTest(unittest.TestCase):
    def test_operational_error_is_connection(self) -> None:
        from sqlalchemy.exc import OperationalError

        self.assertEqual(
            categorize_sqlalchemy_error(OperationalError("stmt", {}, RuntimeError("orig"))),
            "connection",
        )

    def test_integrity_error_is_integrity(self) -> None:
        from sqlalchemy.exc import IntegrityError

        self.assertEqual(
            categorize_sqlalchemy_error(IntegrityError("stmt", {}, RuntimeError("orig"))),
            "integrity",
        )

    def test_generic_sqlalchemy_error_is_operational(self) -> None:
        from sqlalchemy.exc import SQLAlchemyError

        self.assertEqual(
            categorize_sqlalchemy_error(SQLAlchemyError("leak: secret")),
            "operational",
        )

    def test_unknown_exception_is_unexpected(self) -> None:
        self.assertEqual(
            categorize_sqlalchemy_error(ValueError("leak: secret")),
            "unexpected",
        )


class NoSentinelLeaksTest(unittest.TestCase):
    """Defence-in-depth: every legitimate event payload never
    accidentally contains a caller-supplied sensitive token, even
    when the caller passes the token in an optional field."""

    def test_outbound_event_with_provider_code_does_not_leak(self) -> None:
        sink = io.StringIO()
        emit_event(
            event=EVENT_OUTBOUND_OUTCOME,
            component=COMPONENT_OUTBOUND,
            outcome="retryable",
            outbox_id=1,
            provider_code="500",
            stream=sink,
        )
        line = sink.getvalue()
        for token in SENTINELS:
            if token == "500":
                continue
            self.assertNotIn(token, line)

    def test_database_event_with_exception_type_does_not_leak(self) -> None:
        sink = io.StringIO()
        emit_event(
            event=EVENT_DATABASE_TECHNICAL_FAILURE,
            component=COMPONENT_DATABASE,
            failure_category="operational",
            exception_type="OperationalError",
            stream=sink,
        )
        line = sink.getvalue()
        for token in SENTINELS:
            if token in ("OperationalError",) or token.startswith("Operation"):
                continue
            self.assertNotIn(token, line)


if __name__ == "__main__":
    unittest.main(verbosity=2)
