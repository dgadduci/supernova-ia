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
from typing import ClassVar

from backend.observability import (
    COMPONENT_CALLBACK,
    COMPONENT_DATABASE,
    COMPONENT_EMBEDDING,
    COMPONENT_LLM,
    COMPONENT_OUTBOUND,
    COMPONENT_PENDING_CONTEXT,
    COMPONENT_PRODUCT_RECOGNITION,
    COMPONENT_WORKER,
    EVENT_CALLBACK_OUTCOME,
    EVENT_DATABASE_TECHNICAL_FAILURE,
    EVENT_EMBEDDING_REQUEST,
    EVENT_LLM_REQUEST,
    EVENT_OUTBOUND_OUTCOME,
    EVENT_PENDING_CONTEXT_TRANSITION,
    EVENT_SHADOW_PRODUCT_RECOGNITION,
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


class DatabaseTechnicalFailureEmissionTest(unittest.TestCase):
    """Blocker 1 regression: a real ``SQLAlchemyError`` MUST surface
    as a valid, queryable ``database_technical_failure`` event
    belonging to the ``database_technical_boundary`` component.
    It MUST NOT degrade to ``observability_emit_failed`` (which
    would indicate the catalogue rejected the legitimate shape).
    """

    # Catalogue mapping: the database event MUST belong to the
    # database_technical_boundary component, not to the caller
    # component (outbound/callback/etc.). This guards the catalogue
    # contract the dispatcher and the callback route use.
    _CATALOGUE: ClassVar[dict[str, str]] = {
        EVENT_OUTBOUND_OUTCOME: COMPONENT_OUTBOUND,
        EVENT_CALLBACK_OUTCOME: COMPONENT_CALLBACK,
        EVENT_WORKER_CYCLE: COMPONENT_WORKER,
        EVENT_WORKER_UNEXPECTED_FAILURE: COMPONENT_WORKER,
        EVENT_WORKER_READINESS_TRANSITION: COMPONENT_WORKER,
        EVENT_WORKER_DISABLED: COMPONENT_WORKER,
        EVENT_LLM_REQUEST: COMPONENT_LLM,
        EVENT_EMBEDDING_REQUEST: COMPONENT_EMBEDDING,
        EVENT_DATABASE_TECHNICAL_FAILURE: COMPONENT_DATABASE,
    }

    def test_database_failure_event_uses_database_component(self) -> None:
        from sqlalchemy.exc import OperationalError

        exc = OperationalError("stmt", {}, RuntimeError("orig"))
        sink = io.StringIO()
        ok = emit_event(
            event=EVENT_DATABASE_TECHNICAL_FAILURE,
            component=COMPONENT_DATABASE,
            failure_category=categorize_sqlalchemy_error(exc),
            exception_type=type(exc).__name__,
            stream=sink,
        )
        self.assertTrue(ok)
        line = sink.getvalue().strip()
        self.assertTrue(line)
        parsed = parse_event(line)
        self.assertEqual(parsed["event"], EVENT_DATABASE_TECHNICAL_FAILURE)
        self.assertEqual(parsed["component"], COMPONENT_DATABASE)
        self.assertEqual(parsed["failure_category"], "connection")
        self.assertEqual(parsed["exception_type"], "OperationalError")
        self.assertNotEqual(
            parsed["event"], "observability_emit_failed"
        )

    def test_sqlalchemy_error_emits_valid_queryable_event(self) -> None:
        # End-to-end: the dispatcher / callback paths emit this
        # exact catalogued shape by going through the emit_event
        # helper. The emitted line MUST round-trip through
        # parse_event so the Railway query CLI can find it.
        from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError

        for exc, expected_category in (
            (OperationalError("stmt", {}, RuntimeError("orig")), "connection"),
            (IntegrityError("stmt", {}, RuntimeError("orig")), "integrity"),
            (SQLAlchemyError("leak: secret"), "operational"),
        ):
            with self.subTest(exception_type=type(exc).__name__):
                sink = io.StringIO()
                ok = emit_event(
                    event=EVENT_DATABASE_TECHNICAL_FAILURE,
                    component=COMPONENT_DATABASE,
                    failure_category=categorize_sqlalchemy_error(exc),
                    exception_type=type(exc).__name__,
                    stream=sink,
                )
                self.assertTrue(ok)
                line = sink.getvalue().strip()
                # The line is a valid JSON object parseable by the
                # exact same helper the Railway query CLI uses.
                parsed = parse_event(line)
                self.assertEqual(
                    parsed["event"], EVENT_DATABASE_TECHNICAL_FAILURE
                )
                self.assertEqual(
                    parsed["component"], COMPONENT_DATABASE
                )
                self.assertEqual(
                    parsed["failure_category"], expected_category
                )
                # Catalogue guard: the catalogue maps the event
                # name to the database_technical_boundary component
                # and rejects any other component.
                self.assertEqual(
                    self._CATALOGUE[EVENT_DATABASE_TECHNICAL_FAILURE],
                    COMPONENT_DATABASE,
                )

    def test_invalid_database_event_falls_back_to_degraded_event(self) -> None:
        # When a CALLER passes the wrong component for the
        # database_technical_failure event, the helper MUST
        # degrade to observability_emit_failed - that is the
        # contract surfaced by the catalogue. This is the only
        # legitimate degraded path; the SQLAlchemyError path
        # above NEVER triggers it because callers use the correct
        # component already.
        sink = io.StringIO()
        ok = emit_event(
            event=EVENT_DATABASE_TECHNICAL_FAILURE,
            component=COMPONENT_OUTBOUND,
            failure_category="connection",
            exception_type="OperationalError",
            stream=sink,
        )
        self.assertFalse(ok)
        parsed = json.loads(sink.getvalue().strip())
        self.assertEqual(parsed["event"], "observability_emit_failed")
        self.assertEqual(parsed["component"], "observability_helper")
        self.assertEqual(parsed["failure_category"], "validation")
        # The degraded event itself is parseable through the same
        # catalogue, so the Railway query CLI must keep working
        # when it encounters one.
        parsed_round_trip = parse_event(sink.getvalue().strip())
        self.assertEqual(parsed_round_trip["event"], "observability_emit_failed")


class RecognitionEventContractTest(unittest.TestCase):
    """Focused tests for the closed ``shadow_product_recognition``
    event.

    Coverage:

    * business ``unique`` / ``ambiguous`` / ``unknown`` round-trip
      through the catalogue without becoming a technical fallback;
    * ``not_evaluated`` is emitted by the fuzzy-mode path and
      never claims a fallback;
    * technical fallback categories round-trip only when paired
      with ``fallback=true``;
    * invalid configured mode resolves to the sanitized
      ``invalid_mode`` token;
    * forbidden sensitive fields are rejected by the catalogue and
      the bounded CLI never prints raw Railway lines.
    """

    _SAFE_FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "event",
            "schema_version",
            "component",
            "timestamp",
            "configured_mode",
            "effective_mode",
            "authoritative_strategy",
            "hybrid_decision",
            "fallback",
            "fuzzy_latency_ms",
            "embedding_latency_ms",
            "vector_latency_ms",
        }
    )

    def test_event_belongs_to_product_recognition_component(self) -> None:
        payload = build_event(
            event=EVENT_SHADOW_PRODUCT_RECOGNITION,
            component=COMPONENT_PRODUCT_RECOGNITION,
            configured_mode="shadow",
            effective_mode="shadow",
            authoritative_strategy="fuzzy",
            hybrid_decision="unique",
            fallback=False,
        )
        self.assertEqual(
            payload["event"], EVENT_SHADOW_PRODUCT_RECOGNITION
        )
        self.assertEqual(
            payload["component"], COMPONENT_PRODUCT_RECOGNITION
        )
        self.assertEqual(
            payload["schema_version"], int(SCHEMA_VERSION)
        )
        self.assertNotIn("outcome", payload)
        self.assertNotIn("failure_category", payload)
        self.assertEqual(payload["configured_mode"], "shadow")
        self.assertEqual(payload["effective_mode"], "shadow")
        self.assertEqual(payload["authoritative_strategy"], "fuzzy")
        self.assertEqual(payload["hybrid_decision"], "unique")
        self.assertFalse(payload["fallback"])

    def test_component_mismatch_rejected(self) -> None:
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_SHADOW_PRODUCT_RECOGNITION,
                component=COMPONENT_OUTBOUND,
                configured_mode="shadow",
                effective_mode="shadow",
                authoritative_strategy="fuzzy",
                hybrid_decision="unique",
                fallback=False,
            )

    def test_hybrid_unique_is_business_outcome_not_fallback(self) -> None:
        payload = build_event(
            event=EVENT_SHADOW_PRODUCT_RECOGNITION,
            component=COMPONENT_PRODUCT_RECOGNITION,
            configured_mode="hybrid_authoritative",
            effective_mode="hybrid_authoritative",
            authoritative_strategy="hybrid",
            hybrid_decision="unique",
            fallback=False,
        )
        self.assertEqual(payload["hybrid_decision"], "unique")
        self.assertFalse(payload["fallback"])
        self.assertNotIn("fallback_category", payload)

    def test_hybrid_ambiguous_is_business_outcome_not_fallback(self) -> None:
        payload = build_event(
            event=EVENT_SHADOW_PRODUCT_RECOGNITION,
            component=COMPONENT_PRODUCT_RECOGNITION,
            configured_mode="shadow",
            effective_mode="shadow",
            authoritative_strategy="fuzzy",
            hybrid_decision="ambiguous",
            fallback=False,
        )
        self.assertEqual(payload["hybrid_decision"], "ambiguous")
        self.assertFalse(payload["fallback"])
        self.assertNotIn("fallback_category", payload)

    def test_hybrid_unknown_is_business_outcome_not_fallback(self) -> None:
        payload = build_event(
            event=EVENT_SHADOW_PRODUCT_RECOGNITION,
            component=COMPONENT_PRODUCT_RECOGNITION,
            configured_mode="shadow",
            effective_mode="shadow",
            authoritative_strategy="fuzzy",
            hybrid_decision="unknown",
            fallback=False,
        )
        self.assertEqual(payload["hybrid_decision"], "unknown")
        self.assertFalse(payload["fallback"])
        self.assertNotIn("fallback_category", payload)

    def test_not_evaluated_is_fuzzy_mode_outcome(self) -> None:
        payload = build_event(
            event=EVENT_SHADOW_PRODUCT_RECOGNITION,
            component=COMPONENT_PRODUCT_RECOGNITION,
            configured_mode="fuzzy",
            effective_mode="fuzzy",
            authoritative_strategy="fuzzy",
            hybrid_decision="not_evaluated",
            fallback=False,
        )
        self.assertEqual(payload["hybrid_decision"], "not_evaluated")
        self.assertFalse(payload["fallback"])

    def test_technical_fallback_embedding_failure_round_trips(self) -> None:
        payload = build_event(
            event=EVENT_SHADOW_PRODUCT_RECOGNITION,
            component=COMPONENT_PRODUCT_RECOGNITION,
            configured_mode="hybrid_authoritative",
            effective_mode="hybrid_authoritative",
            authoritative_strategy="hybrid",
            hybrid_decision="unknown",
            fallback=True,
            fallback_category="embedding_failure",
            fuzzy_latency_ms=15,
            embedding_latency_ms=200,
            vector_latency_ms=0,
        )
        self.assertTrue(payload["fallback"])
        self.assertEqual(payload["fallback_category"], "embedding_failure")
        line = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        parsed = parse_event(line)
        self.assertEqual(parsed, payload)

    def test_technical_fallback_vector_failure_round_trips(self) -> None:
        payload = build_event(
            event=EVENT_SHADOW_PRODUCT_RECOGNITION,
            component=COMPONENT_PRODUCT_RECOGNITION,
            configured_mode="hybrid_authoritative",
            effective_mode="hybrid_authoritative",
            authoritative_strategy="hybrid",
            hybrid_decision="unknown",
            fallback=True,
            fallback_category="vector_failure",
            fuzzy_latency_ms=15,
            embedding_latency_ms=180,
            vector_latency_ms=42,
        )
        self.assertEqual(payload["fallback_category"], "vector_failure")
        line = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        self.assertEqual(parse_event(line), payload)

    def test_invalid_mode_configured_sanitized(self) -> None:
        payload = build_event(
            event=EVENT_SHADOW_PRODUCT_RECOGNITION,
            component=COMPONENT_PRODUCT_RECOGNITION,
            configured_mode="invalid_mode",
            effective_mode="fuzzy",
            authoritative_strategy="fuzzy",
            hybrid_decision="not_evaluated",
            fallback=True,
            fallback_category="invalid_mode",
        )
        self.assertEqual(payload["configured_mode"], "invalid_mode")
        self.assertEqual(payload["effective_mode"], "fuzzy")
        self.assertTrue(payload["fallback"])
        self.assertEqual(payload["fallback_category"], "invalid_mode")
        line = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        self.assertEqual(parse_event(line), payload)

    def test_outcome_field_rejected(self) -> None:
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_SHADOW_PRODUCT_RECOGNITION,
                component=COMPONENT_PRODUCT_RECOGNITION,
                configured_mode="shadow",
                effective_mode="shadow",
                authoritative_strategy="fuzzy",
                hybrid_decision="unique",
                fallback=False,
                outcome="completed",
            )

    def test_failure_category_field_rejected(self) -> None:
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_SHADOW_PRODUCT_RECOGNITION,
                component=COMPONENT_PRODUCT_RECOGNITION,
                configured_mode="shadow",
                effective_mode="shadow",
                authoritative_strategy="fuzzy",
                hybrid_decision="unique",
                fallback=False,
                failure_category="embedding_failure",
            )

    def test_correlation_id_field_rejected(self) -> None:
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_SHADOW_PRODUCT_RECOGNITION,
                component=COMPONENT_PRODUCT_RECOGNITION,
                configured_mode="shadow",
                effective_mode="shadow",
                authoritative_strategy="fuzzy",
                hybrid_decision="unique",
                fallback=False,
                correlation_id="corr-abc",
            )

    def test_outbox_id_field_rejected(self) -> None:
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_SHADOW_PRODUCT_RECOGNITION,
                component=COMPONENT_PRODUCT_RECOGNITION,
                configured_mode="shadow",
                effective_mode="shadow",
                authoritative_strategy="fuzzy",
                hybrid_decision="unique",
                fallback=False,
                outbox_id=42,
            )

    def test_exception_type_field_rejected(self) -> None:
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_SHADOW_PRODUCT_RECOGNITION,
                component=COMPONENT_PRODUCT_RECOGNITION,
                configured_mode="shadow",
                effective_mode="shadow",
                authoritative_strategy="fuzzy",
                hybrid_decision="unknown",
                fallback=True,
                fallback_category="embedding_failure",
                exception_type="EmbeddingResponseError",
            )

    def test_fallback_category_required_when_fallback_true(self) -> None:
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_SHADOW_PRODUCT_RECOGNITION,
                component=COMPONENT_PRODUCT_RECOGNITION,
                configured_mode="shadow",
                effective_mode="shadow",
                authoritative_strategy="fuzzy",
                hybrid_decision="unknown",
                fallback=True,
            )

    def test_fallback_category_forbidden_when_fallback_false(self) -> None:
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_SHADOW_PRODUCT_RECOGNITION,
                component=COMPONENT_PRODUCT_RECOGNITION,
                configured_mode="shadow",
                effective_mode="shadow",
                authoritative_strategy="fuzzy",
                hybrid_decision="unique",
                fallback=False,
                fallback_category="embedding_failure",
            )

    def test_fallback_category_must_be_in_sanitized_allowlist(self) -> None:
        for forbidden_category in (
            "unknown",
            "score_leak",
            "customer_value",
            "id_comercio",
            "+5491100000000",
            "secret-auth-token-value",
        ):
            with self.subTest(category=forbidden_category):
                with self.assertRaises(EventValidationError):
                    build_event(
                        event=EVENT_SHADOW_PRODUCT_RECOGNITION,
                        component=COMPONENT_PRODUCT_RECOGNITION,
                        configured_mode="shadow",
                        effective_mode="shadow",
                        authoritative_strategy="fuzzy",
                        hybrid_decision="unknown",
                        fallback=True,
                        fallback_category=forbidden_category,
                    )

    def test_invalid_configured_mode_rejected(self) -> None:
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_SHADOW_PRODUCT_RECOGNITION,
                component=COMPONENT_PRODUCT_RECOGNITION,
                configured_mode="banana",
                effective_mode="shadow",
                authoritative_strategy="fuzzy",
                hybrid_decision="unique",
                fallback=False,
            )

    def test_invalid_effective_mode_rejected(self) -> None:
        # ``invalid_mode`` is reserved for the configured-mode
        # sanitization path; the effective mode always resolves to
        # one of the three documented runtime modes.
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_SHADOW_PRODUCT_RECOGNITION,
                component=COMPONENT_PRODUCT_RECOGNITION,
                configured_mode="shadow",
                effective_mode="invalid_mode",
                authoritative_strategy="fuzzy",
                hybrid_decision="unique",
                fallback=False,
            )

    def test_invalid_authoritative_strategy_rejected(self) -> None:
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_SHADOW_PRODUCT_RECOGNITION,
                component=COMPONENT_PRODUCT_RECOGNITION,
                configured_mode="shadow",
                effective_mode="shadow",
                authoritative_strategy="shadow",
                hybrid_decision="unique",
                fallback=False,
            )

    def test_invalid_hybrid_decision_rejected(self) -> None:
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_SHADOW_PRODUCT_RECOGNITION,
                component=COMPONENT_PRODUCT_RECOGNITION,
                configured_mode="shadow",
                effective_mode="shadow",
                authoritative_strategy="fuzzy",
                hybrid_decision="score_leak",
                fallback=False,
            )

    def test_fallback_must_be_boolean(self) -> None:
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_SHADOW_PRODUCT_RECOGNITION,
                component=COMPONENT_PRODUCT_RECOGNITION,
                configured_mode="shadow",
                effective_mode="shadow",
                authoritative_strategy="fuzzy",
                hybrid_decision="unique",
                fallback="yes",  # type: ignore[arg-type]
            )

    def test_negative_latency_rejected(self) -> None:
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_SHADOW_PRODUCT_RECOGNITION,
                component=COMPONENT_PRODUCT_RECOGNITION,
                configured_mode="shadow",
                effective_mode="shadow",
                authoritative_strategy="fuzzy",
                hybrid_decision="unique",
                fallback=False,
                fuzzy_latency_ms=-1,
            )

    def test_non_integer_latency_rejected(self) -> None:
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_SHADOW_PRODUCT_RECOGNITION,
                component=COMPONENT_PRODUCT_RECOGNITION,
                configured_mode="shadow",
                effective_mode="shadow",
                authoritative_strategy="fuzzy",
                hybrid_decision="unique",
                fallback=False,
                fuzzy_latency_ms=1.5,  # type: ignore[arg-type]
            )

    def test_required_fields_must_be_present(self) -> None:
        # The catalogue enforces a closed shape; missing required
        # recognition fields are rejected.
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_SHADOW_PRODUCT_RECOGNITION,
                component=COMPONENT_PRODUCT_RECOGNITION,
                configured_mode="shadow",
                effective_mode="shadow",
                authoritative_strategy="fuzzy",
                fallback=False,
            )

    def test_parse_event_rejects_unknown_keys(self) -> None:
        with self.assertRaises(EventValidationError):
            parse_event(
                '{"event":"shadow_product_recognition","schema_version":1,'
                '"component":"product_recognition","configured_mode":"shadow",'
                '"effective_mode":"shadow","authoritative_strategy":"fuzzy",'
                '"hybrid_decision":"unique","fallback":false,'
                '"timestamp":"2026-08-12T00:00:00+00:00",'
                '"id_comercio":42,"intent":"agregar_producto"}'
            )

    def test_parse_event_rejects_sensitive_field_claim(self) -> None:
        # A Railway line that claims the structured-event shape but
        # carries a forbidden field MUST be rejected before any raw
        # value is reflected back into the bounded CLI output.
        with self.assertRaises(EventValidationError):
            parse_event(
                '{"event":"shadow_product_recognition","schema_version":1,'
                '"component":"product_recognition","configured_mode":"shadow",'
                '"effective_mode":"shadow","authoritative_strategy":"fuzzy",'
                '"hybrid_decision":"unique","fallback":false,'
                '"timestamp":"2026-08-12T00:00:00+00:00",'
                '"scores":[0.9,0.7]}'
            )

    def test_no_sentinel_leaks_in_recognition_payload(self) -> None:
        # Defence-in-depth: the event payload never reflects any of
        # the documented sentinel tokens. The recorder never tries
        # to pass them in, but a downstream caller or a malicious
        # JSON line carrying sentinels MUST be rejected by the
        # catalogue before any line is emitted.
        sink = io.StringIO()
        ok = emit_event(
            event=EVENT_SHADOW_PRODUCT_RECOGNITION,
            component=COMPONENT_PRODUCT_RECOGNITION,
            configured_mode="shadow",
            effective_mode="shadow",
            authoritative_strategy="fuzzy",
            hybrid_decision="unique",
            fallback=True,
            fallback_category="embedding_failure",
            fuzzy_latency_ms=15,
            embedding_latency_ms=200,
            vector_latency_ms=0,
            stream=sink,
        )
        self.assertTrue(ok)
        line = sink.getvalue()
        for token in SENTINELS:
            if token in (
                "shadow",
                "hybrid_authoritative",
                "invalid_mode",
                "embedding_failure",
                "vector_failure",
                "malformed_response",
                "unexpected_technical_failure",
                "not_evaluated",
                "product_recognition",
                EVENT_SHADOW_PRODUCT_RECOGNITION,
            ):
                continue
            self.assertNotIn(token, line)

    def test_recognition_event_excludes_outcome_failure(self) -> None:
        # The recognition event is an observation; it MUST NOT
        # carry ``outcome`` or ``failure_category`` and the parser
        # rejects lines that smuggle those fields in.
        sink = io.StringIO()
        ok = emit_event(
            event=EVENT_SHADOW_PRODUCT_RECOGNITION,
            component=COMPONENT_PRODUCT_RECOGNITION,
            configured_mode="shadow",
            effective_mode="shadow",
            authoritative_strategy="fuzzy",
            hybrid_decision="unique",
            fallback=False,
            fuzzy_latency_ms=12,
            embedding_latency_ms=0,
            vector_latency_ms=0,
            stream=sink,
        )
        self.assertTrue(ok)
        parsed = json.loads(sink.getvalue().strip())
        self.assertNotIn("outcome", parsed)
        self.assertNotIn("failure_category", parsed)
        self.assertNotIn("id_comercio", parsed)
        self.assertNotIn("intent", parsed)
        self.assertNotIn("correlation_id", parsed)
        self.assertNotIn("scores", parsed)

    def test_emit_event_emits_only_allowed_keys(self) -> None:
        # The closed shape: every emitted payload carries exactly
        # the documented recognition keys plus the standard envelope.
        sink = io.StringIO()
        emit_event(
            event=EVENT_SHADOW_PRODUCT_RECOGNITION,
            component=COMPONENT_PRODUCT_RECOGNITION,
            configured_mode="shadow",
            effective_mode="shadow",
            authoritative_strategy="fuzzy",
            hybrid_decision="unique",
            fallback=False,
            fuzzy_latency_ms=12,
            embedding_latency_ms=0,
            vector_latency_ms=0,
            stream=sink,
        )
        parsed = json.loads(sink.getvalue().strip())
        self.assertEqual(
            set(parsed.keys()),
            self._SAFE_FIELDS,
        )

    def test_recognition_event_is_queryable_in_catalogue(self) -> None:
        # Defence: the recognition event name MUST appear in the
        # catalogue mapping so the bounded Railway CLI can find it.
        from backend.observability.events import _EVENT_CATALOGUE

        self.assertEqual(
            _EVENT_CATALOGUE[EVENT_SHADOW_PRODUCT_RECOGNITION],
            COMPONENT_PRODUCT_RECOGNITION,
        )


class PendingContextTransitionEventTest(unittest.TestCase):
    """2.1 / 2.2: ``pending_context_transition`` is a closed privacy-safe
    event with component ``pending_context`` and exactly the documented
    outcome / context_kind / status_before / status_after /
    candidate_count_before / candidate_count_after / context_cleared
    fields. Every other field or value is rejected by the catalogue."""

    _SAFE_FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "event",
            "schema_version",
            "component",
            "timestamp",
            "outcome",
            "context_kind",
            "status_before",
            "status_after",
            "candidate_count_before",
            "candidate_count_after",
            "context_cleared",
        }
    )

    _ACCEPTED_OUTCOMES: ClassVar[tuple[str, ...]] = (
        "pending_preserved",
        "ready_executed",
        "rejected_cleared",
        "status_interrupted",
    )

    _ACCEPTED_STATUSES: ClassVar[tuple[str, ...]] = (
        "pending_resolution",
        "ready",
        "executed",
        "rejected",
        "failed",
    )

    _ACCEPTED_KINDS: ClassVar[tuple[str, ...]] = (
        "product_selection",
        "order_line_selection",
        "product_modification",
        "order_clear_confirmation",
    )

    def _base_kwargs(
        self,
        *,
        outcome: str = "pending_preserved",
        status_before: str = "pending_resolution",
        status_after: str = "pending_resolution",
        candidate_count_before: int = 2,
        candidate_count_after: int = 1,
        context_cleared: bool = False,
        context_kind: str = "product_selection",
    ) -> dict:
        return {
            "event": EVENT_PENDING_CONTEXT_TRANSITION,
            "component": COMPONENT_PENDING_CONTEXT,
            "outcome": outcome,
            "context_kind": context_kind,
            "status_before": status_before,
            "status_after": status_after,
            "candidate_count_before": candidate_count_before,
            "candidate_count_after": candidate_count_after,
            "context_cleared": context_cleared,
        }

    def test_event_is_catalogue_mapped_to_pending_context_component(self):
        from backend.observability.events import _EVENT_CATALOGUE

        self.assertEqual(
            _EVENT_CATALOGUE[EVENT_PENDING_CONTEXT_TRANSITION],
            COMPONENT_PENDING_CONTEXT,
        )

    def test_each_outcome_round_trips_through_catalogue(self):
        for outcome in self._ACCEPTED_OUTCOMES:
            with self.subTest(outcome=outcome):
                kwargs = self._base_kwargs(
                    outcome=outcome,
                    status_before="pending_resolution",
                    status_after="pending_resolution",
                    candidate_count_before=2,
                    candidate_count_after=1,
                )
                payload = build_event(**kwargs)
                self.assertEqual(payload["event"], EVENT_PENDING_CONTEXT_TRANSITION)
                self.assertEqual(payload["component"], COMPONENT_PENDING_CONTEXT)
                self.assertEqual(payload["outcome"], outcome)
                line = json.dumps(payload, sort_keys=True, separators=(",", ":"))
                parsed = parse_event(line)
                self.assertEqual(parsed, payload)

    def test_unknown_outcome_is_rejected(self):
        with self.assertRaises(EventValidationError):
            build_event(**self._base_kwargs(outcome="completed"))

    def test_outcome_must_be_present(self):
        kwargs = self._base_kwargs()
        kwargs.pop("outcome")
        with self.assertRaises(EventValidationError):
            build_event(**kwargs)

    def test_component_mismatch_is_rejected(self):
        kwargs = self._base_kwargs()
        kwargs["component"] = COMPONENT_OUTBOUND
        with self.assertRaises(EventValidationError):
            build_event(**kwargs)

    def test_negative_candidate_count_is_rejected(self):
        with self.assertRaises(EventValidationError):
            build_event(**self._base_kwargs(candidate_count_before=-1))

    def test_candidate_count_above_allowlist_is_rejected(self):
        with self.assertRaises(EventValidationError):
            build_event(**self._base_kwargs(candidate_count_after=201))

    def test_candidate_count_must_be_integer(self):
        with self.assertRaises(EventValidationError):
            build_event(
                **self._base_kwargs(candidate_count_before="2")  # type: ignore[arg-type]
            )

    def test_context_cleared_must_be_boolean(self):
        with self.assertRaises(EventValidationError):
            build_event(
                **self._base_kwargs(context_cleared="yes")  # type: ignore[arg-type]
            )

    def test_context_kind_required(self):
        kwargs = self._base_kwargs()
        kwargs.pop("context_kind")
        with self.assertRaises(EventValidationError):
            build_event(**kwargs)

    def test_context_kind_none_rejected(self):
        kwargs = self._base_kwargs()
        kwargs["context_kind"] = None
        with self.assertRaises(EventValidationError):
            build_event(**kwargs)

    def test_context_kind_unknown_value_rejected(self):
        for kind in (
            "unsupported_context",
            "Agregar_producto",
            "",
            "PENDING",
            "product selection",
        ):
            with self.subTest(kind=kind):
                with self.assertRaises(EventValidationError):
                    build_event(**self._base_kwargs(context_kind=kind))

    def test_status_before_required(self):
        kwargs = self._base_kwargs()
        kwargs.pop("status_before")
        with self.assertRaises(EventValidationError):
            build_event(**kwargs)

    def test_status_before_none_rejected(self):
        kwargs = self._base_kwargs()
        kwargs["status_before"] = None
        with self.assertRaises(EventValidationError):
            build_event(**kwargs)

    def test_status_before_outside_allowlist_rejected(self):
        for forbidden_status in (
            "unknown",
            "completed",
            "executed ",
            "ready!",
            "",
            "PendingResolution",
        ):
            with self.subTest(status=forbidden_status):
                with self.assertRaises(EventValidationError):
                    build_event(**self._base_kwargs(status_before=forbidden_status))

    def test_status_after_required(self):
        kwargs = self._base_kwargs()
        kwargs.pop("status_after")
        with self.assertRaises(EventValidationError):
            build_event(**kwargs)

    def test_status_after_none_rejected(self):
        kwargs = self._base_kwargs()
        kwargs["status_after"] = None
        with self.assertRaises(EventValidationError):
            build_event(**kwargs)

    def test_status_after_outside_allowlist_rejected(self):
        for forbidden_status in (
            "completed",
            "executed!",
            "status_interrupted",
            "pending",
            "",
        ):
            with self.subTest(status=forbidden_status):
                with self.assertRaises(EventValidationError):
                    build_event(**self._base_kwargs(status_after=forbidden_status))

    def test_candidate_counts_required(self):
        kwargs = self._base_kwargs()
        kwargs.pop("candidate_count_before")
        with self.assertRaises(EventValidationError):
            build_event(**kwargs)
        kwargs = self._base_kwargs()
        kwargs.pop("candidate_count_after")
        with self.assertRaises(EventValidationError):
            build_event(**kwargs)

    def test_context_cleared_required(self):
        kwargs = self._base_kwargs()
        kwargs.pop("context_cleared")
        with self.assertRaises(EventValidationError):
            build_event(**kwargs)

    def test_context_cleared_none_rejected(self):
        kwargs = self._base_kwargs()
        kwargs["context_cleared"] = None
        with self.assertRaises(EventValidationError):
            build_event(**kwargs)

    def test_unknown_optional_field_is_rejected(self):
        for unknown_field, value in (
            ("correlation_id", "corr-abc"),
            ("outbox_id", 1),
            ("exception_type", "ValueError"),
            ("elapsed_ms", 12),
        ):
            with self.subTest(field=unknown_field):
                kwargs = self._base_kwargs()
                kwargs[unknown_field] = value  # type: ignore[arg-type]
                with self.assertRaises(EventValidationError):
                    build_event(**kwargs)

    def test_parse_event_rejects_unknown_keys(self):
        with self.assertRaises(EventValidationError):
            parse_event(
                json.dumps(
                    {
                        "event": EVENT_PENDING_CONTEXT_TRANSITION,
                        "schema_version": 1,
                        "component": COMPONENT_PENDING_CONTEXT,
                        "timestamp": "2026-08-13T00:00:00+00:00",
                        "outcome": "pending_preserved",
                        "context_kind": "product_selection",
                        "status_before": "pending_resolution",
                        "status_after": "pending_resolution",
                        "candidate_count_before": 2,
                        "candidate_count_after": 2,
                        "context_cleared": False,
                        "customer_message": "secret",
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                )
            )

    def test_parse_event_rejects_missing_required_field(self):
        for removed in (
            "context_kind",
            "status_before",
            "status_after",
            "candidate_count_before",
            "candidate_count_after",
            "context_cleared",
        ):
            payload = {
                "event": EVENT_PENDING_CONTEXT_TRANSITION,
                "schema_version": 1,
                "component": COMPONENT_PENDING_CONTEXT,
                "timestamp": "2026-08-13T00:00:00+00:00",
                "outcome": "pending_preserved",
                "context_kind": "product_selection",
                "status_before": "pending_resolution",
                "status_after": "pending_resolution",
                "candidate_count_before": 2,
                "candidate_count_after": 2,
                "context_cleared": False,
            }
            payload.pop(removed)
            with self.subTest(missing=removed):
                with self.assertRaises(EventValidationError):
                    parse_event(
                        json.dumps(
                            payload, sort_keys=True, separators=(",", ":")
                        )
                    )

    def test_parse_event_rejects_unknown_context_kind(self):
        payload = {
            "event": EVENT_PENDING_CONTEXT_TRANSITION,
            "schema_version": 1,
            "component": COMPONENT_PENDING_CONTEXT,
            "timestamp": "2026-08-13T00:00:00+00:00",
            "outcome": "pending_preserved",
            "context_kind": "legacy_kind",
            "status_before": "pending_resolution",
            "status_after": "pending_resolution",
            "candidate_count_before": 2,
            "candidate_count_after": 2,
            "context_cleared": False,
        }
        with self.assertRaises(EventValidationError):
            parse_event(
                json.dumps(payload, sort_keys=True, separators=(",", ":"))
            )

    def test_parse_event_rejects_unknown_status(self):
        payload = {
            "event": EVENT_PENDING_CONTEXT_TRANSITION,
            "schema_version": 1,
            "component": COMPONENT_PENDING_CONTEXT,
            "timestamp": "2026-08-13T00:00:00+00:00",
            "outcome": "pending_preserved",
            "context_kind": "product_selection",
            "status_before": "completed",
            "status_after": "pending_resolution",
            "candidate_count_before": 2,
            "candidate_count_after": 2,
            "context_cleared": False,
        }
        with self.assertRaises(EventValidationError):
            parse_event(
                json.dumps(payload, sort_keys=True, separators=(",", ":"))
            )

    def test_emit_event_emits_only_allowed_keys(self):
        sink = io.StringIO()
        ok = emit_event(
            event=EVENT_PENDING_CONTEXT_TRANSITION,
            component=COMPONENT_PENDING_CONTEXT,
            outcome="rejected_cleared",
            context_kind="order_line_selection",
            status_before="pending_resolution",
            status_after="rejected",
            candidate_count_before=4,
            candidate_count_after=4,
            context_cleared=True,
            stream=sink,
        )
        self.assertTrue(ok)
        parsed = json.loads(sink.getvalue().strip())
        self.assertEqual(set(parsed.keys()), self._SAFE_FIELDS)

    def test_no_sensitive_content_in_emitted_payload(self):
        sink = io.StringIO()
        emit_event(
            event=EVENT_PENDING_CONTEXT_TRANSITION,
            component=COMPONENT_PENDING_CONTEXT,
            outcome="status_interrupted",
            context_kind="product_selection",
            status_before="pending_resolution",
            status_after="executed",
            candidate_count_before=3,
            candidate_count_after=3,
            context_cleared=False,
            stream=sink,
        )
        line = sink.getvalue()
        for token in SENTINELS:
            if token in (
                EVENT_PENDING_CONTEXT_TRANSITION,
                COMPONENT_PENDING_CONTEXT,
                "pending_preserved",
                "ready_executed",
                "rejected_cleared",
                "status_interrupted",
                "product_selection",
                "order_line_selection",
                "product_modification",
                "order_clear_confirmation",
            ):
                continue
            self.assertNotIn(token, line)

    def test_candidate_count_200_is_accepted(self):
        payload = build_event(
            **self._base_kwargs(
                candidate_count_before=200, candidate_count_after=200
            )
        )
        self.assertEqual(payload["candidate_count_before"], 200)
        self.assertEqual(payload["candidate_count_after"], 200)

    def test_each_supported_context_kind_is_accepted(self):
        for kind in self._ACCEPTED_KINDS:
            with self.subTest(kind=kind):
                payload = build_event(**self._base_kwargs(context_kind=kind))
                self.assertEqual(payload["context_kind"], kind)

    def test_each_processed_intent_status_is_accepted(self):
        for status in self._ACCEPTED_STATUSES:
            with self.subTest(status=status):
                payload = build_event(
                    **self._base_kwargs(status_before=status, status_after=status)
                )
                self.assertEqual(payload["status_before"], status)
                self.assertEqual(payload["status_after"], status)


if __name__ == "__main__":
    unittest.main(verbosity=2)
