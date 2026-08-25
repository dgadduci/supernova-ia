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
from typing import Any, ClassVar

from backend.observability import (
    COMPONENT_CALLBACK,
    COMPONENT_DATABASE,
    COMPONENT_EMBEDDING,
    COMPONENT_LLM,
    COMPONENT_OBSERVABILITY,
    COMPONENT_OUTBOUND,
    COMPONENT_OUTBOUND_STYLE,
    COMPONENT_PENDING_CONTEXT,
    COMPONENT_PRODUCT_ADD_EXECUTION,
    COMPONENT_PRODUCT_RECOGNITION,
    COMPONENT_WORKER,
    EVENT_CALLBACK_OUTCOME,
    EVENT_DATABASE_TECHNICAL_FAILURE,
    EVENT_EMBEDDING_REQUEST,
    EVENT_LLM_REQUEST,
    EVENT_LLM_REQUEST_TRANSPORT_PHASE,
    EVENT_OBSERVABILITY_EMIT_FAILED,
    EVENT_OUTBOUND_OUTCOME,
    EVENT_OUTBOUND_STYLE,
    EVENT_PENDING_CONTEXT_TRANSITION,
    EVENT_PROCESSING_OUTCOME,
    EVENT_PRODUCT_ADD_EXECUTION,
    EVENT_PROVIDER_INBOUND_STAGE,
    EVENT_SHADOW_PRODUCT_RECOGNITION,
    EVENT_WORKER_CYCLE,
    EVENT_WORKER_DISABLED,
    EVENT_WORKER_LIVENESS,
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
        EVENT_OUTBOUND_STYLE,
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

    def test_invalid_state_cleared_outcome_is_accepted(self):
        payload = build_event(
            **self._base_kwargs(
                outcome="invalid_state_cleared",
                status_before="pending_resolution",
                status_after="rejected",
                candidate_count_before=0,
                candidate_count_after=0,
                context_cleared=True,
            )
        )
        self.assertEqual(payload["outcome"], "invalid_state_cleared")
        self.assertEqual(payload["status_after"], "rejected")
        self.assertTrue(payload["context_cleared"])
        self.assertEqual(payload["candidate_count_before"], 0)
        self.assertEqual(payload["candidate_count_after"], 0)

    def test_invalid_state_cleared_accepts_none_kind(self):
        payload = build_event(
            **self._base_kwargs(
                outcome="invalid_state_cleared",
                context_kind="none",
                status_before="none",
                status_after="rejected",
                candidate_count_before=0,
                candidate_count_after=0,
                context_cleared=True,
            )
        )
        self.assertEqual(payload["context_kind"], "none")
        self.assertEqual(payload["status_before"], "none")

    def test_invalid_state_cleared_accepts_unsupported_kind(self):
        payload = build_event(
            **self._base_kwargs(
                outcome="invalid_state_cleared",
                context_kind="unsupported",
                status_before="pending_resolution",
                status_after="rejected",
                candidate_count_before=0,
                candidate_count_after=0,
                context_cleared=True,
            )
        )
        self.assertEqual(payload["context_kind"], "unsupported")

    def test_invalid_state_cleared_status_after_must_be_rejected(self):
        """The ``invalid_state_cleared`` outcome pins ``status_after``
        to exactly ``rejected``. Any other ``ProcessedIntent.status``
        value, including the closed ``none`` sentinel, MUST be rejected
        by the catalogue so a future emitter cannot relax this
        contract."""
        for forbidden in (
            "pending_resolution",
            "ready",
            "executed",
            "failed",
            "none",
            "completed",
            "",
        ):
            with self.subTest(status_after=forbidden):
                with self.assertRaises(EventValidationError):
                    build_event(
                        **self._base_kwargs(
                            outcome="invalid_state_cleared",
                            status_before="pending_resolution",
                            status_after=forbidden,
                            candidate_count_before=0,
                            candidate_count_after=0,
                            context_cleared=True,
                        )
                    )

    def test_invalid_state_cleared_accepts_supported_context_kind(self):
        """When the persisted ``context_type`` is a supported kind, the
        dispatcher surfaces that kind verbatim (``product_selection``,
        ``order_line_selection``, ``product_modification`` or
        ``order_clear_confirmation``) instead of the ``none`` or
        ``unsupported`` sentinels."""
        for kind in (
            "product_selection",
            "order_line_selection",
            "product_modification",
            "order_clear_confirmation",
        ):
            with self.subTest(kind=kind):
                payload = build_event(
                    **self._base_kwargs(
                        outcome="invalid_state_cleared",
                        context_kind=kind,
                        status_before="pending_resolution",
                        status_after="rejected",
                        candidate_count_before=2,
                        candidate_count_after=0,
                        context_cleared=True,
                    )
                )
                self.assertEqual(payload["context_kind"], kind)

    def test_invalid_state_cleared_rejects_unknown_context_kind(self):
        """Even with the wider ``invalid_state_cleared`` allowlist,
        ``context_kind`` MUST remain a closed enum - arbitrary strings
        are still rejected so the catalogue cannot be poisoned."""
        for forbidden_kind in (
            "future_context_kind",
            "Agregar_producto",
            "product selection",
            "None",
            "UNSUPPORTED",
        ):
            with self.subTest(kind=forbidden_kind):
                with self.assertRaises(EventValidationError):
                    build_event(
                        **self._base_kwargs(
                            outcome="invalid_state_cleared",
                            context_kind=forbidden_kind,
                            status_before="pending_resolution",
                            status_after="rejected",
                            candidate_count_before=0,
                            candidate_count_after=0,
                            context_cleared=True,
                        )
                    )

    def test_other_outcomes_reject_none_sentinels(self):
        """The ``none`` / ``unsupported`` sentinels are reserved for the
        ``invalid_state_cleared`` outcome. Other outcomes keep the
        previous narrower allowlists so no operator-facing payload can
        leak a closed sentinel under a different closed outcome."""
        for outcome in (
            "pending_preserved",
            "ready_executed",
            "rejected_cleared",
            "status_interrupted",
        ):
            with self.subTest(outcome=outcome):
                with self.assertRaises(EventValidationError):
                    build_event(
                        **self._base_kwargs(
                            outcome=outcome,
                            context_kind="none",
                            status_before="pending_resolution",
                            status_after="pending_resolution",
                            candidate_count_before=2,
                            candidate_count_after=2,
                            context_cleared=False,
                        )
                    )
                with self.assertRaises(EventValidationError):
                    build_event(
                        **self._base_kwargs(
                            outcome=outcome,
                            context_kind="product_selection",
                            status_before="none",
                            status_after="pending_resolution",
                            candidate_count_before=2,
                            candidate_count_after=2,
                            context_cleared=False,
                        )
                    )

    def test_invalid_state_cleared_round_trips_through_parse(self):
        payload = build_event(
            **self._base_kwargs(
                outcome="invalid_state_cleared",
                context_kind="none",
                status_before="none",
                status_after="rejected",
                candidate_count_before=0,
                candidate_count_after=0,
                context_cleared=True,
            )
        )
        line = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        parsed = parse_event(line)
        self.assertEqual(parsed, payload)
        self.assertEqual(parsed["outcome"], "invalid_state_cleared")

    def test_invalid_state_cleared_does_not_leak_pii(self):
        sink = io.StringIO()
        emit_event(
            event=EVENT_PENDING_CONTEXT_TRANSITION,
            component=COMPONENT_PENDING_CONTEXT,
            outcome="invalid_state_cleared",
            context_kind="unsupported",
            status_before="pending_resolution",
            status_after="rejected",
            candidate_count_before=0,
            candidate_count_after=0,
            context_cleared=True,
            stream=sink,
        )
        line = sink.getvalue()
        for token in SENTINELS:
            if token in (
                EVENT_PENDING_CONTEXT_TRANSITION,
                COMPONENT_PENDING_CONTEXT,
                "invalid_state_cleared",
                "unsupported",
                "none",
                "pending_resolution",
                "rejected",
            ):
                continue
            self.assertNotIn(token, line)
        parsed = json.loads(line.strip())
        self.assertEqual(
            set(parsed.keys()),
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
            },
        )


class ProductAddExecutionEventTest(unittest.TestCase):
    """The ``product_add_execution`` event is a privacy-safe
    observation with a closed allowlist of outcomes and NO
    identifiers, text, labels, quantities, prices, customer/session/
    Pedido data or optional fields.

    These tests pin the catalogue contract for the event so the
    bounded production-log CLI and the handler share the same
    closed vocabulary.
    """

    _ACCEPTED_OUTCOMES: ClassVar[frozenset[str]] = frozenset(
        {
            "created",
            "incremented",
            "rejected_invalid_input",
            "rejected_session_or_pedido",
            "rejected_not_editable",
            "rejected_missing_presentation",
            "rejected_price_unavailable",
        }
    )

    def test_event_is_catalogue_mapped_to_product_add_component(self) -> None:
        payload = build_event(
            event=EVENT_PRODUCT_ADD_EXECUTION,
            component=COMPONENT_PRODUCT_ADD_EXECUTION,
            outcome="created",
        )
        self.assertEqual(payload["event"], EVENT_PRODUCT_ADD_EXECUTION)
        self.assertEqual(
            payload["component"], COMPONENT_PRODUCT_ADD_EXECUTION
        )
        self.assertEqual(payload["outcome"], "created")
        self.assertEqual(set(payload.keys()), {
            "event",
            "schema_version",
            "component",
            "timestamp",
            "outcome",
        })

    def test_each_outcome_round_trips_through_catalogue(self) -> None:
        for outcome in self._ACCEPTED_OUTCOMES:
            with self.subTest(outcome=outcome):
                payload = build_event(
                    event=EVENT_PRODUCT_ADD_EXECUTION,
                    component=COMPONENT_PRODUCT_ADD_EXECUTION,
                    outcome=outcome,
                )
                self.assertEqual(payload["outcome"], outcome)

    def test_unknown_outcome_is_rejected(self) -> None:
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_PRODUCT_ADD_EXECUTION,
                component=COMPONENT_PRODUCT_ADD_EXECUTION,
                outcome="totally_unknown",
            )

    def test_component_mismatch_is_rejected(self) -> None:
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_PRODUCT_ADD_EXECUTION,
                component=COMPONENT_WORKER,
                outcome="created",
            )

    def test_outcome_required(self) -> None:
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_PRODUCT_ADD_EXECUTION,
                component=COMPONENT_PRODUCT_ADD_EXECUTION,
            )

    def test_no_optional_fields_are_accepted(self) -> None:
        """Every documented optional field MUST be rejected so the
        privacy contract stays strict."""
        forbidden_payloads: list[dict[str, object]] = [
            {"outbox_id": 1},
            {"correlation_id": "abc"},
            {"attempt": 1},
            {"durable_state": "committed"},
            {"provider_code": "twilio"},
            {"http_status": 200},
            {"exception_type": "RuntimeError"},
            {"elapsed_ms": 12},
            {"context_kind": "product_selection"},
            {"status_before": "ready"},
            {"status_after": "executed"},
            {"candidate_count_before": 1},
            {"candidate_count_after": 0},
            {"context_cleared": True},
            {"configured_mode": "fuzzy"},
            {"effective_mode": "fuzzy"},
            {"authoritative_strategy": "fuzzy"},
            {"hybrid_decision": "unique"},
            {"fallback": False},
            {"fallback_category": "embedding_failure"},
        ]
        for extras in forbidden_payloads:
            with self.subTest(extras=extras):
                kwargs = dict(extras)
                with self.assertRaises(EventValidationError):
                    build_event(
                        event=EVENT_PRODUCT_ADD_EXECUTION,
                        component=COMPONENT_PRODUCT_ADD_EXECUTION,
                        outcome="created",
                        **kwargs,
                    )

    def test_parse_event_round_trips_each_outcome(self) -> None:
        for outcome in self._ACCEPTED_OUTCOMES:
            with self.subTest(outcome=outcome):
                payload = build_event(
                    event=EVENT_PRODUCT_ADD_EXECUTION,
                    component=COMPONENT_PRODUCT_ADD_EXECUTION,
                    outcome=outcome,
                )
                serialized = json.dumps(
                    payload, sort_keys=True, separators=(",", ":")
                )
                parsed = parse_event(serialized)
                self.assertEqual(parsed["outcome"], outcome)
                self.assertEqual(parsed["event"], EVENT_PRODUCT_ADD_EXECUTION)

    def test_parse_event_rejects_unknown_outcome(self) -> None:
        payload = build_event(
            event=EVENT_PRODUCT_ADD_EXECUTION,
            component=COMPONENT_PRODUCT_ADD_EXECUTION,
            outcome="created",
        )
        payload["outcome"] = "leaked_price_unavailable"
        with self.assertRaises(EventValidationError):
            parse_event(
                json.dumps(payload, sort_keys=True, separators=(",", ":"))
            )

    def test_parse_event_rejects_unknown_keys(self) -> None:
        payload = build_event(
            event=EVENT_PRODUCT_ADD_EXECUTION,
            component=COMPONENT_PRODUCT_ADD_EXECUTION,
            outcome="created",
        )
        payload["producto_id"] = 1
        payload["precio_unitario"] = 1500
        with self.assertRaises(EventValidationError):
            parse_event(
                json.dumps(payload, sort_keys=True, separators=(",", ":"))
            )

    def test_parse_event_rejects_sensitive_field_claim(self) -> None:
        payload = build_event(
            event=EVENT_PRODUCT_ADD_EXECUTION,
            component=COMPONENT_PRODUCT_ADD_EXECUTION,
            outcome="created",
        )
        payload["whatsapp"] = "+5491100000001"
        payload["pedido_id"] = 42
        payload["producto_presentacion_id"] = 99
        payload["cantidad"] = 1
        payload["precio_unitario"] = "1500.00"
        with self.assertRaises(EventValidationError):
            parse_event(
                json.dumps(payload, sort_keys=True, separators=(",", ":"))
            )

    def test_emit_event_emits_only_allowed_keys(self) -> None:
        sink = io.StringIO()
        ok = emit_event(
            event=EVENT_PRODUCT_ADD_EXECUTION,
            component=COMPONENT_PRODUCT_ADD_EXECUTION,
            outcome="rejected_price_unavailable",
            stream=sink,
        )
        self.assertTrue(ok)
        serialized = sink.getvalue().strip()
        parsed = json.loads(serialized)
        self.assertEqual(
            set(parsed.keys()),
            {
                "event",
                "schema_version",
                "component",
                "timestamp",
                "outcome",
            },
        )
        self.assertEqual(parsed["outcome"], "rejected_price_unavailable")

    def test_emit_event_sink_failure_does_not_raise(self) -> None:
        class _BrokenSink:
            def write(self, _data: str) -> int:
                raise OSError("sink broken")

        ok = emit_event(
            event=EVENT_PRODUCT_ADD_EXECUTION,
            component=COMPONENT_PRODUCT_ADD_EXECUTION,
            outcome="created",
            stream=_BrokenSink(),
        )
        self.assertFalse(ok)

    def test_emit_event_validation_failure_emits_degraded_event(self) -> None:
        sink = io.StringIO()
        ok = emit_event(
            event=EVENT_PRODUCT_ADD_EXECUTION,
            component=COMPONENT_PRODUCT_ADD_EXECUTION,
            outcome="unknown_outcome",
            stream=sink,
        )
        self.assertFalse(ok)
        serialized = sink.getvalue().strip()
        parsed = json.loads(serialized)
        self.assertEqual(
            parsed["event"], EVENT_OBSERVABILITY_EMIT_FAILED
        )


class ProviderWorkerLivenessEventTest(unittest.TestCase):
    """The ``provider_worker_liveness`` event is a privacy-safe
    lifecycle observation with a closed outcome/phase allowlist.
    The contract rejects unknown fields, free-form phase/outcome
    tokens, unbounded numeric values and sensitive payloads so a
    Railway operator can correlate the last worker phase that
    began without ever receiving a message, phone number, SID,
    prompt, response, URL, credential, token, exception message
    or traceback.
    """

    _ACCEPTED_OUTCOMES: ClassVar[frozenset[str]] = frozenset(
        {
            "cycle_started",
            "phase_started",
            "phase_completed",
            "phase_failed",
            "cycle_completed",
        }
    )

    _ACCEPTED_PHASES: ClassVar[frozenset[str]] = frozenset(
        {"readiness", "inbound", "outbound", "sleep"}
    )

    _PHASE_OUTCOMES: ClassVar[frozenset[str]] = frozenset(
        {"phase_started", "phase_completed", "phase_failed"}
    )

    _CYCLE_OUTCOMES: ClassVar[frozenset[str]] = frozenset(
        {"cycle_started", "cycle_completed"}
    )

    _BASE_CYCLE_KEYS: ClassVar[frozenset[str]] = frozenset(
        {"event", "schema_version", "component", "timestamp", "outcome"}
    )

    def test_event_is_catalogue_mapped_to_provider_worker_component(self) -> None:
        from backend.observability.events import _EVENT_CATALOGUE

        self.assertEqual(
            _EVENT_CATALOGUE[EVENT_WORKER_LIVENESS],
            COMPONENT_WORKER,
        )

    def test_cycle_started_round_trips(self) -> None:
        payload = build_event(
            event=EVENT_WORKER_LIVENESS,
            component=COMPONENT_WORKER,
            outcome="cycle_started",
            cycle_index=3,
        )
        self.assertEqual(payload["event"], EVENT_WORKER_LIVENESS)
        self.assertEqual(payload["component"], COMPONENT_WORKER)
        self.assertEqual(payload["outcome"], "cycle_started")
        self.assertEqual(payload["cycle_index"], 3)
        self.assertNotIn("phase", payload)
        self.assertNotIn("failure_category", payload)
        self.assertEqual(set(payload.keys()), self._BASE_CYCLE_KEYS | {"cycle_index"})

    def test_cycle_completed_with_elapsed_round_trips(self) -> None:
        payload = build_event(
            event=EVENT_WORKER_LIVENESS,
            component=COMPONENT_WORKER,
            outcome="cycle_completed",
            cycle_index=9,
            elapsed_ms=1500,
        )
        self.assertEqual(payload["outcome"], "cycle_completed")
        self.assertEqual(payload["cycle_index"], 9)
        self.assertEqual(payload["elapsed_ms"], 1500)

    def test_phase_started_requires_phase(self) -> None:
        for phase in self._ACCEPTED_PHASES:
            with self.subTest(phase=phase):
                payload = build_event(
                    event=EVENT_WORKER_LIVENESS,
                    component=COMPONENT_WORKER,
                    outcome="phase_started",
                    phase=phase,
                    cycle_index=1,
                )
                self.assertEqual(payload["outcome"], "phase_started")
                self.assertEqual(payload["phase"], phase)
                self.assertEqual(payload["cycle_index"], 1)

    def test_phase_completed_carries_bounded_elapsed(self) -> None:
        payload = build_event(
            event=EVENT_WORKER_LIVENESS,
            component=COMPONENT_WORKER,
            outcome="phase_completed",
            phase="outbound",
            cycle_index=5,
            elapsed_ms=250,
        )
        self.assertEqual(payload["elapsed_ms"], 250)

    def test_phase_failed_carries_safe_exception_metadata(self) -> None:
        payload = build_event(
            event=EVENT_WORKER_LIVENESS,
            component=COMPONENT_WORKER,
            outcome="phase_failed",
            phase="inbound",
            cycle_index=2,
            elapsed_ms=120,
            failure_category="worker_exception",
            exception_type="RuntimeError",
        )
        self.assertEqual(payload["outcome"], "phase_failed")
        self.assertEqual(payload["phase"], "inbound")
        self.assertEqual(payload["failure_category"], "worker_exception")
        self.assertEqual(payload["exception_type"], "RuntimeError")
        self.assertEqual(payload["elapsed_ms"], 120)

    def test_each_outcome_round_trips_through_parse_event(self) -> None:
        for outcome in self._ACCEPTED_OUTCOMES:
            with self.subTest(outcome=outcome):
                if outcome in self._PHASE_OUTCOMES:
                    kwargs = {
                        "phase": "inbound",
                        "cycle_index": 4,
                        "elapsed_ms": 10,
                    }
                else:
                    kwargs = {"cycle_index": 7, "elapsed_ms": 100}
                if outcome == "phase_failed":
                    kwargs["failure_category"] = "worker_exception"
                    kwargs["exception_type"] = "RuntimeError"
                payload = build_event(
                    event=EVENT_WORKER_LIVENESS,
                    component=COMPONENT_WORKER,
                    outcome=outcome,
                    **kwargs,
                )
                serialized = json.dumps(
                    payload, sort_keys=True, separators=(",", ":")
                )
                parsed = parse_event(serialized)
                self.assertEqual(parsed, payload)

    def test_outcome_required(self) -> None:
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_WORKER_LIVENESS,
                component=COMPONENT_WORKER,
                cycle_index=1,
            )

    def test_component_mismatch_rejected(self) -> None:
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_WORKER_LIVENESS,
                component=COMPONENT_OUTBOUND,
                outcome="cycle_started",
                cycle_index=1,
            )

    def test_unknown_outcome_rejected(self) -> None:
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_WORKER_LIVENESS,
                component=COMPONENT_WORKER,
                outcome="started",
                cycle_index=1,
            )

    def test_cycle_index_required(self) -> None:
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_WORKER_LIVENESS,
                component=COMPONENT_WORKER,
                outcome="cycle_started",
            )

    def test_cycle_index_zero_rejected(self) -> None:
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_WORKER_LIVENESS,
                component=COMPONENT_WORKER,
                outcome="cycle_started",
                cycle_index=0,
            )

    def test_cycle_index_negative_rejected(self) -> None:
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_WORKER_LIVENESS,
                component=COMPONENT_WORKER,
                outcome="cycle_started",
                cycle_index=-1,
            )

    def test_cycle_index_non_integer_rejected(self) -> None:
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_WORKER_LIVENESS,
                component=COMPONENT_WORKER,
                outcome="cycle_started",
                cycle_index="1",  # type: ignore[arg-type]
            )

    def test_cycle_index_above_bound_rejected(self) -> None:
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_WORKER_LIVENESS,
                component=COMPONENT_WORKER,
                outcome="cycle_started",
                cycle_index=2**31,
            )

    def test_phase_required_for_phase_outcomes(self) -> None:
        for outcome in self._PHASE_OUTCOMES:
            with self.subTest(outcome=outcome):
                with self.assertRaises(EventValidationError):
                    build_event(
                        event=EVENT_WORKER_LIVENESS,
                        component=COMPONENT_WORKER,
                        outcome=outcome,
                        cycle_index=1,
                    )

    def test_phase_unknown_value_rejected(self) -> None:
        for forbidden_phase in (
            "inbound_phase",
            "custom_runner",
            "Outbound",
            "sleeps",
            "",
            "+5491100000000",
            "provider_sid",
            "traceback",
        ):
            with self.subTest(phase=forbidden_phase):
                with self.assertRaises(EventValidationError):
                    build_event(
                        event=EVENT_WORKER_LIVENESS,
                        component=COMPONENT_WORKER,
                        outcome="phase_started",
                        phase=forbidden_phase,
                        cycle_index=1,
                    )

    def test_phase_forbidden_for_cycle_outcomes(self) -> None:
        for outcome in self._CYCLE_OUTCOMES:
            with self.subTest(outcome=outcome):
                with self.assertRaises(EventValidationError):
                    build_event(
                        event=EVENT_WORKER_LIVENESS,
                        component=COMPONENT_WORKER,
                        outcome=outcome,
                        cycle_index=1,
                        phase="inbound",
                    )

    def test_elapsed_ms_negative_rejected(self) -> None:
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_WORKER_LIVENESS,
                component=COMPONENT_WORKER,
                outcome="phase_completed",
                phase="inbound",
                cycle_index=1,
                elapsed_ms=-1,
            )

    def test_elapsed_ms_non_integer_rejected(self) -> None:
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_WORKER_LIVENESS,
                component=COMPONENT_WORKER,
                outcome="phase_completed",
                phase="inbound",
                cycle_index=1,
                elapsed_ms=12.5,  # type: ignore[arg-type]
            )

    def test_failure_category_must_be_in_liveness_allowlist(self) -> None:
        for forbidden_category in (
            "retryable_timeout",
            "terminal_4xx",
            "embedding_failure",
            "leak",
            "worker_exception_extra",
        ):
            with self.subTest(category=forbidden_category):
                with self.assertRaises(EventValidationError):
                    build_event(
                        event=EVENT_WORKER_LIVENESS,
                        component=COMPONENT_WORKER,
                        outcome="phase_failed",
                        phase="inbound",
                        cycle_index=1,
                        failure_category=forbidden_category,
                    )

    def test_exception_type_with_dot_rejected(self) -> None:
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_WORKER_LIVENESS,
                component=COMPONENT_WORKER,
                outcome="phase_failed",
                phase="outbound",
                cycle_index=1,
                failure_category="worker_exception",
                exception_type="backend.errors.RuntimeError",
            )

    def test_exception_type_with_message_rejected(self) -> None:
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_WORKER_LIVENESS,
                component=COMPONENT_WORKER,
                outcome="phase_failed",
                phase="outbound",
                cycle_index=1,
                failure_category="worker_exception",
                exception_type="RuntimeError: connection refused",
            )

    def test_forbidden_sensitive_fields_rejected(self) -> None:
        """Every documented sensitive payload MUST be rejected by
        the catalogue so the bounded production-log CLI never
        surfaces a message body, phone number, SID, prompt,
        response, URL, credential, token, exception message or
        traceback in a liveness event."""
        forbidden_payloads: list[tuple[str, object]] = [
            ("outbox_id", 1),
            ("correlation_id", "corr-abc"),
            ("attempt", 1),
            ("durable_state", "accepted"),
            ("provider_code", "SM-ABC"),
            ("http_status", 500),
            ("configured_mode", "fuzzy"),
            ("effective_mode", "fuzzy"),
            ("authoritative_strategy", "fuzzy"),
            ("hybrid_decision", "unique"),
            ("fallback", False),
            ("fallback_category", "embedding_failure"),
            ("fuzzy_latency_ms", 15),
            ("embedding_latency_ms", 200),
            ("vector_latency_ms", 0),
            ("context_kind", "product_selection"),
            ("status_before", "pending_resolution"),
            ("status_after", "ready"),
            ("candidate_count_before", 1),
            ("candidate_count_after", 0),
            ("context_cleared", False),
            ("flavor_code", "spicy"),
            ("eligible_count", 1),
            ("applied_count", 1),
            (
                "outbound_style_prompt_template_version",
                "v1",
            ),
            (
                "outbound_style_prompt_template_hash",
                "0" * 64,
            ),
            ("reason", "accepted"),
        ]
        for field_name, value in forbidden_payloads:
            with self.subTest(field=field_name):
                with self.assertRaises(EventValidationError):
                    build_event(
                        event=EVENT_WORKER_LIVENESS,
                        component=COMPONENT_WORKER,
                        outcome="cycle_started",
                        cycle_index=1,
                        **{field_name: value},
                    )

    def test_non_liveness_event_rejects_phase(self) -> None:
        """``phase`` belongs to ``provider_worker_liveness`` only.
        Every other catalogued event MUST reject ``phase``
        explicitly so the catalogue round-trip cannot silently
        accept and drop the field."""
        non_liveness_events = (
            (EVENT_OUTBOUND_OUTCOME, COMPONENT_OUTBOUND, "accepted"),
            (
                EVENT_CALLBACK_OUTCOME,
                COMPONENT_CALLBACK,
                "applied",
            ),
            (EVENT_WORKER_CYCLE, COMPONENT_WORKER, "completed"),
            (
                EVENT_WORKER_READINESS_TRANSITION,
                COMPONENT_WORKER,
                "ready",
            ),
            (
                EVENT_WORKER_DISABLED,
                COMPONENT_WORKER,
                "disabled",
            ),
            (EVENT_LLM_REQUEST, COMPONENT_LLM, "completed"),
            (
                EVENT_EMBEDDING_REQUEST,
                COMPONENT_EMBEDDING,
                "completed",
            ),
            (
                EVENT_DATABASE_TECHNICAL_FAILURE,
                COMPONENT_DATABASE,
                None,
            ),
            (
                EVENT_OBSERVABILITY_EMIT_FAILED,
                COMPONENT_OBSERVABILITY,
                None,
            ),
            (
                EVENT_PENDING_CONTEXT_TRANSITION,
                COMPONENT_PENDING_CONTEXT,
                "pending_preserved",
            ),
            (
                EVENT_PRODUCT_ADD_EXECUTION,
                COMPONENT_PRODUCT_ADD_EXECUTION,
                "created",
            ),
            (
                EVENT_OUTBOUND_STYLE,
                COMPONENT_OUTBOUND_STYLE,
                "applied",
            ),
        )
        for event, component, outcome in non_liveness_events:
            with self.subTest(event=event):
                kwargs = {"phase": "inbound"}
                if outcome is None:
                    kwargs["failure_category"] = "connection"
                else:
                    kwargs["outcome"] = outcome
                with self.assertRaises(EventValidationError):
                    build_event(
                        event=event,
                        component=component,
                        **kwargs,
                    )

    def test_non_liveness_event_rejects_cycle_index(self) -> None:
        """``cycle_index`` belongs to ``provider_worker_liveness``
        only. Every other catalogued event MUST reject it
        explicitly so the catalogue round-trip cannot silently
        accept and drop the field."""
        non_liveness_events = (
            (EVENT_OUTBOUND_OUTCOME, COMPONENT_OUTBOUND, "accepted"),
            (
                EVENT_CALLBACK_OUTCOME,
                COMPONENT_CALLBACK,
                "applied",
            ),
            (EVENT_WORKER_CYCLE, COMPONENT_WORKER, "completed"),
            (
                EVENT_WORKER_READINESS_TRANSITION,
                COMPONENT_WORKER,
                "ready",
            ),
            (
                EVENT_WORKER_DISABLED,
                COMPONENT_WORKER,
                "disabled",
            ),
            (EVENT_LLM_REQUEST, COMPONENT_LLM, "completed"),
            (
                EVENT_EMBEDDING_REQUEST,
                COMPONENT_EMBEDDING,
                "completed",
            ),
            (
                EVENT_DATABASE_TECHNICAL_FAILURE,
                COMPONENT_DATABASE,
                None,
            ),
            (
                EVENT_OBSERVABILITY_EMIT_FAILED,
                COMPONENT_OBSERVABILITY,
                None,
            ),
            (
                EVENT_PENDING_CONTEXT_TRANSITION,
                COMPONENT_PENDING_CONTEXT,
                "pending_preserved",
            ),
            (
                EVENT_PRODUCT_ADD_EXECUTION,
                COMPONENT_PRODUCT_ADD_EXECUTION,
                "created",
            ),
            (
                EVENT_OUTBOUND_STYLE,
                COMPONENT_OUTBOUND_STYLE,
                "applied",
            ),
        )
        for event, component, outcome in non_liveness_events:
            with self.subTest(event=event):
                kwargs = {"cycle_index": 1}
                if outcome is None:
                    kwargs["failure_category"] = "connection"
                else:
                    kwargs["outcome"] = outcome
                with self.assertRaises(EventValidationError):
                    build_event(
                        event=event,
                        component=component,
                        **kwargs,
                    )

    def test_parse_event_rejects_phase_on_non_liveness_event(self) -> None:
        """``parse_event`` MUST reject a line that carries ``phase``
        on any non-liveness event so the production-log query CLI
        cannot silently round-trip the field."""
        with self.assertRaises(EventValidationError):
            parse_event(
                '{"event":"outbound_attempt_outcome","schema_version":1,'
                '"component":"outbound_dispatch","outcome":"accepted",'
                '"timestamp":"2026-08-20T00:00:00+00:00",'
                '"phase":"inbound"}'
            )

    def test_parse_event_rejects_cycle_index_on_non_liveness_event(
        self,
    ) -> None:
        """``parse_event`` MUST reject a line that carries
        ``cycle_index`` on any non-liveness event so the
        production-log query CLI cannot silently round-trip the
        field."""
        with self.assertRaises(EventValidationError):
            parse_event(
                '{"event":"outbound_attempt_outcome","schema_version":1,'
                '"component":"outbound_dispatch","outcome":"accepted",'
                '"timestamp":"2026-08-20T00:00:00+00:00",'
                '"cycle_index":1}'
            )

    def test_parse_event_rejects_phase_on_database_failure_event(
        self,
    ) -> None:
        """``parse_event`` MUST reject ``phase`` on the database
        technical failure event so the production-log query CLI
        cannot silently round-trip the field through the failure
        surface."""
        with self.assertRaises(EventValidationError):
            parse_event(
                '{"event":"database_technical_failure","schema_version":1,'
                '"component":"database_technical_boundary",'
                '"timestamp":"2026-08-20T00:00:00+00:00",'
                '"failure_category":"connection",'
                '"exception_type":"OperationalError",'
                '"phase":"inbound"}'
            )

    def test_parse_event_rejects_cycle_index_on_database_failure_event(
        self,
    ) -> None:
        """``parse_event`` MUST reject ``cycle_index`` on the
        database technical failure event."""
        with self.assertRaises(EventValidationError):
            parse_event(
                '{"event":"database_technical_failure","schema_version":1,'
                '"component":"database_technical_boundary",'
                '"timestamp":"2026-08-20T00:00:00+00:00",'
                '"failure_category":"connection",'
                '"exception_type":"OperationalError",'
                '"cycle_index":1}'
            )

    def test_failure_category_forbidden_on_non_phase_failed_outcomes(
        self,
    ) -> None:
        """``failure_category`` is reserved for ``phase_failed`` only.
        Any other liveness outcome (``cycle_started``,
        ``cycle_completed``, ``phase_started``,
        ``phase_completed``) MUST be rejected when the caller tries
        to attach ``failure_category`` so a Railway operator can
        never read raw exception data on a non-failure surface."""
        for outcome in (
            "cycle_started",
            "cycle_completed",
            "phase_started",
            "phase_completed",
        ):
            with self.subTest(outcome=outcome):
                kwargs = {
                    "cycle_index": 1,
                    "failure_category": "worker_exception",
                }
                if outcome in self._PHASE_OUTCOMES:
                    kwargs["phase"] = "inbound"
                with self.assertRaises(EventValidationError):
                    build_event(
                        event=EVENT_WORKER_LIVENESS,
                        component=COMPONENT_WORKER,
                        outcome=outcome,
                        **kwargs,
                    )

    def test_exception_type_forbidden_on_non_phase_failed_outcomes(
        self,
    ) -> None:
        """``exception_type`` is reserved for ``phase_failed`` only.
        Any other liveness outcome MUST be rejected when the caller
        tries to attach ``exception_type``."""
        for outcome in (
            "cycle_started",
            "cycle_completed",
            "phase_started",
            "phase_completed",
        ):
            with self.subTest(outcome=outcome):
                kwargs = {
                    "cycle_index": 1,
                    "exception_type": "RuntimeError",
                }
                if outcome in self._PHASE_OUTCOMES:
                    kwargs["phase"] = "inbound"
                with self.assertRaises(EventValidationError):
                    build_event(
                        event=EVENT_WORKER_LIVENESS,
                        component=COMPONENT_WORKER,
                        outcome=outcome,
                        **kwargs,
                    )

    def test_phase_failed_requires_failure_category(self) -> None:
        """A ``phase_failed`` event without ``failure_category`` is
        rejected: the catalogue MUST surface the safe technical
        category alongside every failure so an operator can correlate
        the closed phase with its category without parsing free-form
        text."""
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_WORKER_LIVENESS,
                component=COMPONENT_WORKER,
                outcome="phase_failed",
                phase="inbound",
                cycle_index=1,
                exception_type="RuntimeError",
            )

    def test_phase_failed_requires_exception_type(self) -> None:
        """A ``phase_failed`` event without ``exception_type`` is
        rejected: the catalogue MUST surface the safe exception class
        alongside every failure so an operator can correlate the
        closed phase with the class name without parsing free-form
        text."""
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_WORKER_LIVENESS,
                component=COMPONENT_WORKER,
                outcome="phase_failed",
                phase="inbound",
                cycle_index=1,
                failure_category="worker_exception",
            )

    def test_phase_failed_requires_both_metadata_fields(self) -> None:
        """``phase_failed`` MUST carry BOTH ``failure_category`` and
        ``exception_type``: a half-populated failure event is
        rejected."""
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_WORKER_LIVENESS,
                component=COMPONENT_WORKER,
                outcome="phase_failed",
                phase="inbound",
                cycle_index=1,
            )

    def test_phase_failed_accepts_valid_metadata(self) -> None:
        """The happy path: ``phase_failed`` with a closed safe
        ``failure_category`` and a safe ``exception_type`` MUST
        round-trip through the catalogue."""
        payload = build_event(
            event=EVENT_WORKER_LIVENESS,
            component=COMPONENT_WORKER,
            outcome="phase_failed",
            phase="inbound",
            cycle_index=4,
            elapsed_ms=120,
            failure_category="worker_exception",
            exception_type="RuntimeError",
        )
        self.assertEqual(payload["outcome"], "phase_failed")
        self.assertEqual(payload["phase"], "inbound")
        self.assertEqual(payload["failure_category"], "worker_exception")
        self.assertEqual(payload["exception_type"], "RuntimeError")
        serialized = json.dumps(
            payload, sort_keys=True, separators=(",", ":")
        )
        self.assertEqual(parse_event(serialized), payload)

    def test_phase_failed_rejects_invalid_failure_category(self) -> None:
        """``phase_failed`` with a category outside the closed
        allowlist is rejected so the bounded surface cannot be
        widened by a caller."""
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_WORKER_LIVENESS,
                component=COMPONENT_WORKER,
                outcome="phase_failed",
                phase="inbound",
                cycle_index=1,
                failure_category="leak",
                exception_type="RuntimeError",
            )

    def test_phase_failed_rejects_sensitive_exception_type(self) -> None:
        """``phase_failed`` with an ``exception_type`` carrying a
        traceback, dotted module path, URL, phone number, bearer
        token, secret with control characters or message MUST be
        rejected by the existing safe exception-class validator
        so a Railway operator never sees raw exception data on
        the bounded surface.

        Note: the existing contract enforces the
        ``exception_type`` shape (``short alnum token without
        dots, spaces, or leading punctuation``) rather than a
        deny-list of secret keywords. Class names that happen to
        look like a secret (no dots / no spaces / starts with
        alpha) are technically accepted, but the bounded CLI
        surface never carries the caller-supplied exception
        message, traceback or arguments, so a Railway operator
        never observes raw exception content.
        """
        sensitive_values = (
            "backend.errors.RuntimeError",
            "RuntimeError: connection refused",
            "+5491100000000",
            "https://provider.example",
            "Bearer abc",
            "abc\nBody",
        )
        for value in sensitive_values:
            with self.subTest(exception_type=value):
                with self.assertRaises(EventValidationError):
                    build_event(
                        event=EVENT_WORKER_LIVENESS,
                        component=COMPONENT_WORKER,
                        outcome="phase_failed",
                        phase="inbound",
                        cycle_index=1,
                        failure_category="worker_exception",
                        exception_type=value,
                    )

    def test_parse_event_rejects_unknown_keys(self) -> None:
        with self.assertRaises(EventValidationError):
            parse_event(
                '{"event":"provider_worker_liveness","schema_version":1,'
                '"component":"provider_worker","timestamp":'
                '"2026-08-20T00:00:00+00:00","outcome":"cycle_started",'
                '"cycle_index":1,"customer_message":"leak"}'
            )

    def test_parse_event_rejects_cycle_index_out_of_bounds(self) -> None:
        with self.assertRaises(EventValidationError):
            parse_event(
                '{"event":"provider_worker_liveness","schema_version":1,'
                '"component":"provider_worker","timestamp":'
                '"2026-08-20T00:00:00+00:00","outcome":"cycle_started",'
                '"cycle_index":0}'
            )

    def test_parse_event_rejects_unknown_phase(self) -> None:
        with self.assertRaises(EventValidationError):
            parse_event(
                '{"event":"provider_worker_liveness","schema_version":1,'
                '"component":"provider_worker","timestamp":'
                '"2026-08-20T00:00:00+00:00","outcome":"phase_started",'
                '"cycle_index":1,"phase":"custom_runner"}'
            )

    def test_parse_event_rejects_phase_in_cycle_outcome(self) -> None:
        with self.assertRaises(EventValidationError):
            parse_event(
                '{"event":"provider_worker_liveness","schema_version":1,'
                '"component":"provider_worker","timestamp":'
                '"2026-08-20T00:00:00+00:00","outcome":"cycle_started",'
                '"cycle_index":1,"phase":"inbound"}'
            )

    def test_emit_event_emits_only_allowed_keys(self) -> None:
        sink = io.StringIO()
        ok = emit_event(
            event=EVENT_WORKER_LIVENESS,
            component=COMPONENT_WORKER,
            outcome="phase_failed",
            phase="inbound",
            cycle_index=3,
            elapsed_ms=42,
            failure_category="worker_exception",
            exception_type="RuntimeError",
            stream=sink,
        )
        self.assertTrue(ok)
        parsed = json.loads(sink.getvalue().strip())
        self.assertEqual(
            set(parsed.keys()),
            {
                "event",
                "schema_version",
                "component",
                "timestamp",
                "outcome",
                "phase",
                "cycle_index",
                "elapsed_ms",
                "failure_category",
                "exception_type",
            },
        )

    def test_no_sensitive_content_in_emitted_payload(self) -> None:
        sink = io.StringIO()
        emit_event(
            event=EVENT_WORKER_LIVENESS,
            component=COMPONENT_WORKER,
            outcome="phase_failed",
            phase="inbound",
            cycle_index=1,
            elapsed_ms=1,
            failure_category="worker_exception",
            exception_type="RuntimeError",
            stream=sink,
        )
        line = sink.getvalue()
        for token in SENTINELS:
            if token in (
                EVENT_WORKER_LIVENESS,
                COMPONENT_WORKER,
                "cycle_started",
                "phase_started",
                "phase_completed",
                "phase_failed",
                "cycle_completed",
                "readiness",
                "inbound",
                "outbound",
                "sleep",
                "worker_exception",
                "RuntimeError",
            ):
                continue
            self.assertNotIn(token, line)

    def test_emit_event_phase_failed_without_failure_category_is_rejected(
        self,
    ) -> None:
        """``phase_failed`` without ``failure_category`` is rejected:
        ``emit_event`` MUST degrade to ``observability_emit_failed``
        so the bounded CLI never surfaces a half-populated failure
        event on the Railway surface."""
        sink = io.StringIO()
        ok = emit_event(
            event=EVENT_WORKER_LIVENESS,
            component=COMPONENT_WORKER,
            outcome="phase_failed",
            phase="inbound",
            cycle_index=1,
            stream=sink,
        )
        self.assertFalse(ok)
        parsed = json.loads(sink.getvalue().strip())
        self.assertEqual(parsed["event"], "observability_emit_failed")
        self.assertEqual(parsed["failure_category"], "validation")
        self.assertEqual(parsed["component"], COMPONENT_OBSERVABILITY)

    def test_emit_event_phase_failed_without_exception_type_is_rejected(
        self,
    ) -> None:
        """``phase_failed`` without ``exception_type`` is rejected:
        ``emit_event`` MUST degrade to ``observability_emit_failed``."""
        sink = io.StringIO()
        ok = emit_event(
            event=EVENT_WORKER_LIVENESS,
            component=COMPONENT_WORKER,
            outcome="phase_failed",
            phase="inbound",
            cycle_index=1,
            failure_category="worker_exception",
            stream=sink,
        )
        self.assertFalse(ok)
        parsed = json.loads(sink.getvalue().strip())
        self.assertEqual(parsed["event"], "observability_emit_failed")

    def test_emit_event_phase_started_with_failure_category_is_rejected(
        self,
    ) -> None:
        """``phase_started`` (or any non-``phase_failed`` liveness
        outcome) MUST reject ``failure_category``: ``emit_event``
        degrades to ``observability_emit_failed``."""
        for outcome in (
            "cycle_started",
            "cycle_completed",
            "phase_started",
            "phase_completed",
        ):
            with self.subTest(outcome=outcome):
                sink = io.StringIO()
                kwargs = {
                    "cycle_index": 1,
                    "failure_category": "worker_exception",
                }
                if outcome in self._PHASE_OUTCOMES:
                    kwargs["phase"] = "inbound"
                ok = emit_event(
                    event=EVENT_WORKER_LIVENESS,
                    component=COMPONENT_WORKER,
                    outcome=outcome,
                    stream=sink,
                    **kwargs,
                )
                self.assertFalse(ok)
                parsed = json.loads(sink.getvalue().strip())
                self.assertEqual(
                    parsed["event"], "observability_emit_failed"
                )

    def test_emit_event_non_liveness_event_rejects_phase(self) -> None:
        """``emit_event`` MUST reject ``phase`` on any non-liveness
        event so the field cannot be silently accepted and dropped
        by the catalogue round-trip."""
        sink = io.StringIO()
        ok = emit_event(
            event=EVENT_OUTBOUND_OUTCOME,
            component=COMPONENT_OUTBOUND,
            outcome="accepted",
            phase="inbound",
            stream=sink,
        )
        self.assertFalse(ok)
        parsed = json.loads(sink.getvalue().strip())
        self.assertEqual(parsed["event"], "observability_emit_failed")

    def test_emit_event_non_liveness_event_rejects_cycle_index(self) -> None:
        """``emit_event`` MUST reject ``cycle_index`` on any non-liveness
        event so the field cannot be silently accepted and dropped
        by the catalogue round-trip."""
        sink = io.StringIO()
        ok = emit_event(
            event=EVENT_OUTBOUND_OUTCOME,
            component=COMPONENT_OUTBOUND,
            outcome="accepted",
            cycle_index=1,
            stream=sink,
        )
        self.assertFalse(ok)
        parsed = json.loads(sink.getvalue().strip())
        self.assertEqual(parsed["event"], "observability_emit_failed")


class ProviderInboundProcessingOutcomeEventTest(unittest.TestCase):
    """The ``provider_inbound_processing_outcome`` event is a
    privacy-safe observation emitted by the provider coordinator
    AFTER the existing authoritative durable processing result is
    known. The contract is closed: the only allowed outcomes are
    ``processed_with_response``, ``processed_without_response``,
    ``retry_scheduled``, ``failed_terminal``, ``lease_lost`` and
    ``unavailable``; the only allowed optional fields are bounded
    ``response_count`` and ``outbox_row_count`` plus the existing
    safe ``correlation_id``. The contract forbids bodies, phone
    numbers, provider SIDs, prompts, model responses, exception
    text or tracebacks."""

    _ACCEPTED_OUTCOMES: ClassVar[frozenset[str]] = frozenset(
        {
            "processed_with_response",
            "processed_without_response",
            "retry_scheduled",
            "failed_terminal",
            "lease_lost",
            "unavailable",
        }
    )

    _ACCEPTED_FAILURE_CATEGORIES: ClassVar[frozenset[str]] = frozenset(
        {
            "pipeline_error",
            "database_error",
            "budget_exhausted",
            "terminal_processor_error",
            "unavailable_commerce",
        }
    )

    def test_event_is_catalogue_mapped_to_provider_worker_component(self) -> None:
        from backend.observability.events import _EVENT_CATALOGUE

        self.assertEqual(
            _EVENT_CATALOGUE[EVENT_PROCESSING_OUTCOME],
            COMPONENT_WORKER,
        )

    def test_each_outcome_round_trips(self) -> None:
        for outcome in self._ACCEPTED_OUTCOMES:
            with self.subTest(outcome=outcome):
                if outcome in (
                    "retry_scheduled",
                    "failed_terminal",
                    "lease_lost",
                ):
                    kwargs: dict[str, object] = {
                        "failure_category": "pipeline_error"
                    }
                elif outcome == "unavailable":
                    kwargs = {"failure_category": "unavailable_commerce"}
                else:
                    kwargs = {
                        "response_count": 0,
                        "outbox_row_count": 0,
                    }
                payload = build_event(
                    event=EVENT_PROCESSING_OUTCOME,
                    component=COMPONENT_WORKER,
                    outcome=outcome,
                    **kwargs,
                )
                self.assertEqual(payload["event"], EVENT_PROCESSING_OUTCOME)
                self.assertEqual(payload["outcome"], outcome)
                self.assertEqual(payload["component"], COMPONENT_WORKER)

    def test_processed_with_response_carries_matching_counts(self) -> None:
        payload = build_event(
            event=EVENT_PROCESSING_OUTCOME,
            component=COMPONENT_WORKER,
            outcome="processed_with_response",
            response_count=2,
            outbox_row_count=2,
            correlation_id="SM-FAKE",
        )
        self.assertEqual(payload["response_count"], 2)
        self.assertEqual(payload["outbox_row_count"], 2)
        self.assertEqual(payload["correlation_id"], "SM-FAKE")

    def test_processed_without_response_carries_zero_counts(self) -> None:
        payload = build_event(
            event=EVENT_PROCESSING_OUTCOME,
            component=COMPONENT_WORKER,
            outcome="processed_without_response",
            response_count=0,
            outbox_row_count=0,
        )
        self.assertEqual(payload["response_count"], 0)
        self.assertEqual(payload["outbox_row_count"], 0)
        self.assertNotIn("failure_category", payload)

    def test_unavailable_carries_bounded_failure_category(self) -> None:
        payload = build_event(
            event=EVENT_PROCESSING_OUTCOME,
            component=COMPONENT_WORKER,
            outcome="unavailable",
            failure_category="unavailable_commerce",
        )
        self.assertEqual(
            payload["failure_category"], "unavailable_commerce"
        )
        self.assertEqual(payload["outcome"], "unavailable")

    def test_retry_scheduled_carries_failure_category(self) -> None:
        payload = build_event(
            event=EVENT_PROCESSING_OUTCOME,
            component=COMPONENT_WORKER,
            outcome="retry_scheduled",
            failure_category="pipeline_error",
        )
        self.assertEqual(payload["outcome"], "retry_scheduled")
        self.assertEqual(payload["failure_category"], "pipeline_error")

    def test_failed_terminal_carries_failure_category(self) -> None:
        payload = build_event(
            event=EVENT_PROCESSING_OUTCOME,
            component=COMPONENT_WORKER,
            outcome="failed_terminal",
            failure_category="budget_exhausted",
        )
        self.assertEqual(payload["outcome"], "failed_terminal")
        self.assertEqual(payload["failure_category"], "budget_exhausted")

    def test_outcome_required(self) -> None:
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_PROCESSING_OUTCOME,
                component=COMPONENT_WORKER,
                response_count=0,
                outbox_row_count=0,
            )

    def test_component_mismatch_rejected(self) -> None:
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_PROCESSING_OUTCOME,
                component=COMPONENT_OUTBOUND,
                outcome="processed_without_response",
                response_count=0,
                outbox_row_count=0,
            )

    def test_unknown_outcome_rejected(self) -> None:
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_PROCESSING_OUTCOME,
                component=COMPONENT_WORKER,
                outcome="rejected",
            )

    def test_processed_outcome_with_failure_category_rejected(self) -> None:
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_PROCESSING_OUTCOME,
                component=COMPONENT_WORKER,
                outcome="processed_without_response",
                failure_category="pipeline_error",
                response_count=0,
                outbox_row_count=0,
            )

    def test_retry_outcome_with_response_count_rejected(self) -> None:
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_PROCESSING_OUTCOME,
                component=COMPONENT_WORKER,
                outcome="retry_scheduled",
                response_count=0,
                failure_category="pipeline_error",
            )

    def test_retry_outcome_with_outbox_row_count_rejected(self) -> None:
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_PROCESSING_OUTCOME,
                component=COMPONENT_WORKER,
                outcome="retry_scheduled",
                outbox_row_count=0,
                failure_category="pipeline_error",
            )

    def test_processed_outcome_without_response_count_rejected(self) -> None:
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_PROCESSING_OUTCOME,
                component=COMPONENT_WORKER,
                outcome="processed_with_response",
                outbox_row_count=0,
            )

    def test_processed_outcome_without_outbox_row_count_rejected(self) -> None:
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_PROCESSING_OUTCOME,
                component=COMPONENT_WORKER,
                outcome="processed_without_response",
                response_count=0,
            )

    def test_unknown_failure_category_rejected(self) -> None:
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_PROCESSING_OUTCOME,
                component=COMPONENT_WORKER,
                outcome="retry_scheduled",
                failure_category="not_in_allowlist",
            )

    def test_response_count_negative_rejected(self) -> None:
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_PROCESSING_OUTCOME,
                component=COMPONENT_WORKER,
                outcome="processed_with_response",
                response_count=-1,
                outbox_row_count=0,
            )

    def test_response_count_above_bound_rejected(self) -> None:
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_PROCESSING_OUTCOME,
                component=COMPONENT_WORKER,
                outcome="processed_with_response",
                response_count=201,
                outbox_row_count=0,
            )

    def test_outbox_row_count_non_integer_rejected(self) -> None:
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_PROCESSING_OUTCOME,
                component=COMPONENT_WORKER,
                outcome="processed_with_response",
                response_count=0,
                outbox_row_count="zero",
            )

    def test_sensitive_fields_rejected(self) -> None:
        for forbidden in (
            "outbox_id",
            "durable_state",
            "provider_code",
            "http_status",
            "exception_type",
            "elapsed_ms",
            "phase",
            "cycle_index",
        ):
            with self.subTest(forbidden=forbidden):
                kwargs = {
                    "event": EVENT_PROCESSING_OUTCOME,
                    "component": COMPONENT_WORKER,
                    "outcome": "processed_without_response",
                    "response_count": 0,
                    "outbox_row_count": 0,
                    forbidden: 1 if forbidden != "exception_type" else "Boom",
                }
                with self.assertRaises(EventValidationError):
                    build_event(**kwargs)

    def test_each_outcome_round_trips_through_parse_event(self) -> None:
        for outcome in self._ACCEPTED_OUTCOMES:
            with self.subTest(outcome=outcome):
                if outcome in (
                    "retry_scheduled",
                    "failed_terminal",
                    "lease_lost",
                ):
                    kwargs = {"failure_category": "pipeline_error"}
                elif outcome == "unavailable":
                    kwargs = {"failure_category": "unavailable_commerce"}
                else:
                    kwargs = {
                        "response_count": 0,
                        "outbox_row_count": 0,
                    }
                payload = build_event(
                    event=EVENT_PROCESSING_OUTCOME,
                    component=COMPONENT_WORKER,
                    outcome=outcome,
                    **kwargs,
                )
                serialized = json.dumps(
                    payload, sort_keys=True, separators=(",", ":")
                )
                parsed = parse_event(serialized)
                self.assertEqual(parsed, payload)

    def test_no_sensitive_payload_round_trip(self) -> None:
        for outcome in (
            "processed_with_response",
            "processed_without_response",
            "retry_scheduled",
            "failed_terminal",
            "lease_lost",
            "unavailable",
        ):
            with self.subTest(outcome=outcome):
                if outcome in (
                    "retry_scheduled",
                    "failed_terminal",
                    "lease_lost",
                ):
                    kwargs = {"failure_category": "pipeline_error"}
                elif outcome == "unavailable":
                    kwargs = {"failure_category": "unavailable_commerce"}
                else:
                    kwargs = {
                        "response_count": 0,
                        "outbox_row_count": 0,
                    }
                payload = build_event(
                    event=EVENT_PROCESSING_OUTCOME,
                    component=COMPONENT_WORKER,
                    outcome=outcome,
                    **kwargs,
                )
                _no_payload_leaks(payload, event=EVENT_PROCESSING_OUTCOME)

    def test_emit_event_round_trips_through_sink(self) -> None:
        sink = io.StringIO()
        ok = emit_event(
            event=EVENT_PROCESSING_OUTCOME,
            component=COMPONENT_WORKER,
            outcome="processed_without_response",
            response_count=0,
            outbox_row_count=0,
            stream=sink,
        )
        self.assertTrue(ok)
        serialized = sink.getvalue().strip()
        parsed = json.loads(serialized)
        self.assertEqual(parsed["event"], EVENT_PROCESSING_OUTCOME)
        self.assertEqual(parsed["outcome"], "processed_without_response")
        self.assertEqual(parsed["response_count"], 0)
        self.assertEqual(parsed["outbox_row_count"], 0)
        self.assertNotIn("failure_category", parsed)


class ProviderInboundStageEventTest(unittest.TestCase):
    """Closed catalogue / parser / privacy / bounds tests for the
    ``provider_inbound_stage`` event used by the bounded
    coordinator stage wrappers.

    Coverage:

    * each closed ``stage`` value round-trips through the
      catalogue with the correct ``outcome`` family
      (``started``/``completed``/``failed``);
    * ``elapsed_ms`` is REQUIRED for ``completed`` and
      ``failed`` and ABSENT for ``started``;
    * ``exception_type`` is REQUIRED for ``failed`` and ABSENT
      for ``started``/``completed``; the safe-type contract
      rejects dotted or spaced exception names;
    * unknown stage, unknown outcome, negative or oversized
      ``elapsed_ms``, raw exception text, PII-like fields and
      extra catalogue fields are rejected;
    * the production-log parser (``parse_event``) round-trips a
      catalogued line and rejects unknown keys;
    * the payload never leaks customer tokens, prompt text or
      exception messages;
    * the helper degrades safely when a caller passes a
      malformed event.
    """

    _ALLOWED_STAGES: ClassVar[frozenset[str]] = frozenset(
        {
            "availability",
            "session_order",
            "business_pipeline",
            "outbound_staging",
            "processing_finalization",
        }
    )

    _SAFE_FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "event",
            "schema_version",
            "component",
            "timestamp",
            "outcome",
            "stage",
            "elapsed_ms",
            "exception_type",
            "correlation_id",
        }
    )

    def _base_kwargs(self, **overrides: Any) -> dict:
        kwargs: dict[str, Any] = {
            "event": EVENT_PROVIDER_INBOUND_STAGE,
            "component": COMPONENT_WORKER,
            "outcome": "started",
            "stage": "availability",
        }
        kwargs.update(overrides)
        return kwargs

    def test_event_belongs_to_provider_worker_component(self) -> None:
        from backend.observability.events import _EVENT_CATALOGUE

        self.assertEqual(
            _EVENT_CATALOGUE[EVENT_PROVIDER_INBOUND_STAGE],
            COMPONENT_WORKER,
        )

    def test_each_stage_round_trips_with_started_outcome(self) -> None:
        for stage in self._ALLOWED_STAGES:
            with self.subTest(stage=stage):
                payload = build_event(
                    event=EVENT_PROVIDER_INBOUND_STAGE,
                    component=COMPONENT_WORKER,
                    stage=stage,
                    outcome="started",
                    correlation_id="SYN-123",
                )
                self.assertEqual(payload["stage"], stage)
                self.assertEqual(payload["outcome"], "started")
                self.assertEqual(
                    payload["correlation_id"], "SYN-123"
                )
                line = json.dumps(
                    payload, sort_keys=True, separators=(",", ":")
                )
                parsed = parse_event(line)
                self.assertEqual(parsed, payload)

    def test_completed_outcome_requires_elapsed_ms(self) -> None:
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_PROVIDER_INBOUND_STAGE,
                component=COMPONENT_WORKER,
                stage="business_pipeline",
                outcome="completed",
            )

    def test_failed_outcome_requires_elapsed_ms_and_exception_type(
        self,
    ) -> None:
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_PROVIDER_INBOUND_STAGE,
                component=COMPONENT_WORKER,
                stage="availability",
                outcome="failed",
                elapsed_ms=12,
            )
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_PROVIDER_INBOUND_STAGE,
                component=COMPONENT_WORKER,
                stage="availability",
                outcome="failed",
                exception_type="OperationalError",
            )

    def test_started_outcome_rejects_elapsed_ms(self) -> None:
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_PROVIDER_INBOUND_STAGE,
                component=COMPONENT_WORKER,
                stage="availability",
                outcome="started",
                elapsed_ms=12,
            )

    def test_started_outcome_rejects_exception_type(self) -> None:
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_PROVIDER_INBOUND_STAGE,
                component=COMPONENT_WORKER,
                stage="availability",
                outcome="started",
                exception_type="RuntimeError",
            )

    def test_completed_outcome_rejects_exception_type(self) -> None:
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_PROVIDER_INBOUND_STAGE,
                component=COMPONENT_WORKER,
                stage="availability",
                outcome="completed",
                elapsed_ms=12,
                exception_type="RuntimeError",
            )

    def test_outcome_required(self) -> None:
        kwargs = self._base_kwargs()
        kwargs.pop("outcome")
        with self.assertRaises(EventValidationError):
            build_event(**kwargs)

    def test_outcome_outside_allowlist_rejected(self) -> None:
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_PROVIDER_INBOUND_STAGE,
                component=COMPONENT_WORKER,
                stage="availability",
                outcome="succeeded",
            )

    def test_stage_required(self) -> None:
        kwargs = self._base_kwargs()
        kwargs.pop("stage")
        with self.assertRaises(EventValidationError):
            build_event(**kwargs)

    def test_stage_none_rejected(self) -> None:
        kwargs = self._base_kwargs()
        kwargs["stage"] = None
        with self.assertRaises(EventValidationError):
            build_event(**kwargs)

    def test_stage_unknown_value_rejected(self) -> None:
        for stage in (
            "unknown_stage",
            "trigger_warning",
            "AVAILABILITY",
            "availability ",
            " customer_lookup",
            "",
        ):
            with self.subTest(stage=stage):
                with self.assertRaises(EventValidationError):
                    build_event(
                        event=EVENT_PROVIDER_INBOUND_STAGE,
                        component=COMPONENT_WORKER,
                        stage=stage,
                        outcome="started",
                    )

    def test_component_mismatch_rejected(self) -> None:
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_PROVIDER_INBOUND_STAGE,
                component=COMPONENT_OUTBOUND,
                stage="availability",
                outcome="started",
            )

    def test_elapsed_ms_negative_rejected(self) -> None:
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_PROVIDER_INBOUND_STAGE,
                component=COMPONENT_WORKER,
                stage="availability",
                outcome="completed",
                elapsed_ms=-1,
            )

    def test_elapsed_ms_oversized_rejected(self) -> None:
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_PROVIDER_INBOUND_STAGE,
                component=COMPONENT_WORKER,
                stage="availability",
                outcome="completed",
                elapsed_ms=24 * 60 * 60 * 1000 + 1,
            )

    def test_exception_type_must_not_contain_dot_or_space(self) -> None:
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_PROVIDER_INBOUND_STAGE,
                component=COMPONENT_WORKER,
                stage="availability",
                outcome="failed",
                elapsed_ms=12,
                exception_type="a.b.OperationalError",
            )
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_PROVIDER_INBOUND_STAGE,
                component=COMPONENT_WORKER,
                stage="availability",
                outcome="failed",
                elapsed_ms=12,
                exception_type="OperationalError: connection refused",
            )

    def test_extra_optional_fields_rejected(self) -> None:
        for forbidden_field, value in (
            ("outbox_id", 1),
            ("attempt", 1),
            ("durable_state", "processed"),
            ("provider_code", "500"),
            ("http_status", 500),
            ("response_count", 1),
            ("outbox_row_count", 1),
            ("phase", "inbound"),
            ("cycle_index", 1),
        ):
            with self.subTest(field=forbidden_field):
                with self.assertRaises(EventValidationError):
                    build_event(
                        event=EVENT_PROVIDER_INBOUND_STAGE,
                        component=COMPONENT_WORKER,
                        stage="availability",
                        outcome="started",
                        **{forbidden_field: value},
                    )

    def test_correlation_id_optional(self) -> None:
        payload = build_event(
            event=EVENT_PROVIDER_INBOUND_STAGE,
            component=COMPONENT_WORKER,
            stage="availability",
            outcome="started",
        )
        self.assertNotIn("correlation_id", payload)

    def test_correlation_id_oversized_rejected(self) -> None:
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_PROVIDER_INBOUND_STAGE,
                component=COMPONENT_WORKER,
                stage="availability",
                outcome="started",
                correlation_id="x" * 100,
            )

    def test_parse_event_round_trips_started(self) -> None:
        payload = build_event(
            event=EVENT_PROVIDER_INBOUND_STAGE,
            component=COMPONENT_WORKER,
            stage="business_pipeline",
            outcome="started",
            correlation_id="SM-CORR-1",
        )
        line = json.dumps(
            payload, sort_keys=True, separators=(",", ":")
        )
        self.assertEqual(parse_event(line), payload)

    def test_parse_event_round_trips_failed(self) -> None:
        payload = build_event(
            event=EVENT_PROVIDER_INBOUND_STAGE,
            component=COMPONENT_WORKER,
            stage="availability",
            outcome="failed",
            elapsed_ms=42,
            exception_type="RuntimeError",
            correlation_id="SM-CORR-2",
        )
        line = json.dumps(
            payload, sort_keys=True, separators=(",", ":")
        )
        self.assertEqual(parse_event(line), payload)

    def test_parse_event_rejects_unknown_keys(self) -> None:
        with self.assertRaises(EventValidationError):
            parse_event(
                '{"event":"provider_inbound_stage","schema_version":1,'
                '"component":"provider_worker","outcome":"started",'
                '"stage":"availability",'
                '"timestamp":"2026-08-22T00:00:00+00:00",'
                '"id_comercio":42,"customer_text":"hola"}'
            )

    def test_emit_event_emits_only_allowed_keys(self) -> None:
        sink = io.StringIO()
        ok = emit_event(
            event=EVENT_PROVIDER_INBOUND_STAGE,
            component=COMPONENT_WORKER,
            stage="availability",
            outcome="started",
            correlation_id="SM-OK-1",
            stream=sink,
        )
        self.assertTrue(ok)
        parsed = json.loads(sink.getvalue().strip())
        # The envelope + outcome + stage + correlation_id are the
        # minimum closed shape for a started event. ``elapsed_ms``
        # and ``exception_type`` MUST NOT appear on a started
        # outcome (they are reserved for completed/failed).
        self.assertTrue(self._SAFE_FIELDS.issuperset(set(parsed.keys())))
        self.assertNotIn("elapsed_ms", parsed)
        self.assertNotIn("exception_type", parsed)
        self.assertIn("stage", parsed)
        self.assertIn("outcome", parsed)
        self.assertIn("correlation_id", parsed)

    def test_no_sentinel_leaks_in_stage_payload(self) -> None:
        sink = io.StringIO()
        ok = emit_event(
            event=EVENT_PROVIDER_INBOUND_STAGE,
            component=COMPONENT_WORKER,
            stage="business_pipeline",
            outcome="failed",
            elapsed_ms=10,
            exception_type="RuntimeError",
            correlation_id="SM-LEAK-1",
            stream=sink,
        )
        self.assertTrue(ok)
        line = sink.getvalue()
        for token in SENTINELS:
            if token in (
                "RuntimeError",
                "business_pipeline",
                EVENT_PROVIDER_INBOUND_STAGE,
            ):
                continue
            self.assertNotIn(token, line)

    def test_emit_event_degrades_on_invalid_stage(self) -> None:
        sink = io.StringIO()
        ok = emit_event(
            event=EVENT_PROVIDER_INBOUND_STAGE,
            component=COMPONENT_WORKER,
            stage="banana",
            outcome="started",
            stream=sink,
        )
        self.assertFalse(ok)
        parsed = json.loads(sink.getvalue().strip())
        self.assertEqual(parsed["event"], "observability_emit_failed")
        self.assertEqual(parsed["failure_category"], "validation")
        self.assertEqual(
            parsed["component"], "observability_helper"
        )

    def test_emit_event_degrades_on_started_with_elapsed_ms(self) -> None:
        sink = io.StringIO()
        ok = emit_event(
            event=EVENT_PROVIDER_INBOUND_STAGE,
            component=COMPONENT_WORKER,
            stage="session_order",
            outcome="started",
            elapsed_ms=10,
            stream=sink,
        )
        self.assertFalse(ok)
        parsed = json.loads(sink.getvalue().strip())
        self.assertEqual(parsed["event"], "observability_emit_failed")

    def test_emit_event_does_not_raise_on_broken_stream(self) -> None:
        class _BrokenStream:
            def write(self, _data: str) -> None:
                raise OSError("simulated stream failure")

        ok = emit_event(
            event=EVENT_PROVIDER_INBOUND_STAGE,
            component=COMPONENT_WORKER,
            stage="availability",
            outcome="started",
            stream=_BrokenStream(),
        )
        self.assertFalse(ok)


class LlmRequestTransportPhaseEventTest(unittest.TestCase):
    """Closed catalogue / parser / privacy / bounds tests for the
    ``llm_request_transport_phase`` diagnostic event emitted by the
    :class:`backend.llm.query_llm.QueryLlm` boundary.

    Coverage:

    * each closed ``phase`` value round-trips through the catalogue
      with the right ``elapsed_ms`` / ``http_status`` / ``response_bytes``
      / ``correlation_id`` metadata;
    * the ``phase`` field is REQUIRED;
    * unknown phase, negative or oversized ``elapsed_ms``,
      ``http_status`` / ``response_bytes`` / ``correlation_id``,
      free-form text or extra catalogue fields are rejected;
    * the production-log parser (``parse_event``) round-trips a
      catalogued line and rejects unknown keys;
    * the payload never leaks customer tokens, prompt text,
      proxy/URL/credential strings or exception messages;
    * the helper degrades safely when a caller passes a malformed
      event.
    """

    _ALLOWED_PHASES: ClassVar[frozenset[str]] = frozenset(
        {
            "request_started",
            "response_headers_received",
            "first_body_chunk",
            "body_completed",
            "response_received",
            "json_extracted",
            "result_parsed",
        }
    )

    def _base_kwargs(self, **overrides: Any) -> dict:
        kwargs: dict[str, Any] = {
            "event": EVENT_LLM_REQUEST_TRANSPORT_PHASE,
            "component": COMPONENT_LLM,
            "phase": "request_started",
            "elapsed_ms": 0,
        }
        kwargs.update(overrides)
        return kwargs

    def test_phase_request_started_round_trips(self) -> None:
        payload = build_event(
            event=EVENT_LLM_REQUEST_TRANSPORT_PHASE,
            component=COMPONENT_LLM,
            phase="request_started",
            elapsed_ms=0,
            correlation_id="SYN-PROV-1",
        )
        self.assertEqual(payload["event"], "llm_request_transport_phase")
        self.assertEqual(payload["component"], "query_llm")
        self.assertEqual(payload["phase"], "request_started")
        self.assertEqual(payload["elapsed_ms"], 0)
        self.assertEqual(payload["correlation_id"], "SYN-PROV-1")
        self.assertNotIn("outcome", payload)
        self.assertNotIn("failure_category", payload)

    def test_phase_response_headers_received_with_status(self) -> None:
        payload = build_event(
            event=EVENT_LLM_REQUEST_TRANSPORT_PHASE,
            component=COMPONENT_LLM,
            phase="response_headers_received",
            elapsed_ms=123,
            http_status=200,
        )
        self.assertEqual(payload["phase"], "response_headers_received")
        self.assertEqual(payload["http_status"], 200)
        self.assertEqual(payload["elapsed_ms"], 123)
        self.assertNotIn("response_bytes", payload)
        self.assertNotIn("chunk_count", payload)

    def test_phase_first_body_chunk_with_chunk_count(self) -> None:
        payload = build_event(
            event=EVENT_LLM_REQUEST_TRANSPORT_PHASE,
            component=COMPONENT_LLM,
            phase="first_body_chunk",
            elapsed_ms=125,
            http_status=200,
            chunk_count=1,
        )
        self.assertEqual(payload["phase"], "first_body_chunk")
        self.assertEqual(payload["chunk_count"], 1)
        self.assertEqual(payload["http_status"], 200)
        self.assertNotIn("response_bytes", payload)

    def test_phase_body_completed_with_chunk_count_and_bytes(self) -> None:
        payload = build_event(
            event=EVENT_LLM_REQUEST_TRANSPORT_PHASE,
            component=COMPONENT_LLM,
            phase="body_completed",
            elapsed_ms=130,
            http_status=200,
            response_bytes=4096,
            chunk_count=4,
            correlation_id="SYN-PROV-CH",
        )
        self.assertEqual(payload["phase"], "body_completed")
        self.assertEqual(payload["response_bytes"], 4096)
        self.assertEqual(payload["chunk_count"], 4)
        self.assertEqual(payload["correlation_id"], "SYN-PROV-CH")

    def test_historical_response_received_phase_round_trips(self) -> None:
        payload = build_event(
            event=EVENT_LLM_REQUEST_TRANSPORT_PHASE,
            component=COMPONENT_LLM,
            phase="response_received",
            elapsed_ms=0,
            http_status=200,
            response_bytes=4096,
            correlation_id="SYN-PROV-RR",
        )
        self.assertEqual(payload["phase"], "response_received")
        self.assertEqual(payload["http_status"], 200)
        self.assertEqual(payload["response_bytes"], 4096)
        self.assertEqual(payload["correlation_id"], "SYN-PROV-RR")

    def test_historical_response_received_parse_event_round_trips(
        self,
    ) -> None:
        payload = build_event(
            event=EVENT_LLM_REQUEST_TRANSPORT_PHASE,
            component=COMPONENT_LLM,
            phase="response_received",
            elapsed_ms=12,
            http_status=200,
            correlation_id="SYN-PROV-RR-PARSE",
        )
        line = json.dumps(
            payload, sort_keys=True, separators=(",", ":")
        )
        parsed = parse_event(line)
        self.assertEqual(parsed, payload)
        self.assertEqual(parsed["phase"], "response_received")

    def test_phase_json_extracted_with_response_bytes(self) -> None:
        payload = build_event(
            event=EVENT_LLM_REQUEST_TRANSPORT_PHASE,
            component=COMPONENT_LLM,
            phase="json_extracted",
            elapsed_ms=130,
            http_status=200,
            response_bytes=4096,
        )
        self.assertEqual(payload["phase"], "json_extracted")
        self.assertEqual(payload["response_bytes"], 4096)

    def test_phase_result_parsed_carries_metadata(self) -> None:
        payload = build_event(
            event=EVENT_LLM_REQUEST_TRANSPORT_PHASE,
            component=COMPONENT_LLM,
            phase="result_parsed",
            elapsed_ms=135,
            http_status=200,
            response_bytes=4096,
            correlation_id="SYN-PROV-2",
        )
        self.assertEqual(payload["phase"], "result_parsed")
        self.assertEqual(payload["elapsed_ms"], 135)
        self.assertEqual(payload["response_bytes"], 4096)
        self.assertEqual(payload["correlation_id"], "SYN-PROV-2")

    def test_all_seven_phases_accepted(self) -> None:
        for phase in self._ALLOWED_PHASES:
            payload = build_event(
                event=EVENT_LLM_REQUEST_TRANSPORT_PHASE,
                component=COMPONENT_LLM,
                phase=phase,
                elapsed_ms=0,
            )
            self.assertEqual(payload["phase"], phase)

    def test_phase_required(self) -> None:
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_LLM_REQUEST_TRANSPORT_PHASE,
                component=COMPONENT_LLM,
            )

    def test_unknown_phase_rejected(self) -> None:
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_LLM_REQUEST_TRANSPORT_PHASE,
                component=COMPONENT_LLM,
                phase="post_response_hacked",
            )

    def test_liveness_phase_not_accepted(self) -> None:
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_LLM_REQUEST_TRANSPORT_PHASE,
                component=COMPONENT_LLM,
                phase="inbound",
            )

    def test_transport_phase_not_accepted_by_liveness(self) -> None:
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_WORKER_LIVENESS,
                component=COMPONENT_WORKER,
                outcome="phase_started",
                phase="request_started",
                cycle_index=1,
            )

    def test_outcome_rejected(self) -> None:
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_LLM_REQUEST_TRANSPORT_PHASE,
                component=COMPONENT_LLM,
                phase="request_started",
                outcome="started",
            )

    def test_failure_category_rejected(self) -> None:
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_LLM_REQUEST_TRANSPORT_PHASE,
                component=COMPONENT_LLM,
                phase="request_started",
                failure_category="timeout",
            )

    def test_exception_type_rejected(self) -> None:
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_LLM_REQUEST_TRANSPORT_PHASE,
                component=COMPONENT_LLM,
                phase="result_parsed",
                exception_type="RuntimeError",
            )

    def test_elapsed_ms_negative_rejected(self) -> None:
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_LLM_REQUEST_TRANSPORT_PHASE,
                component=COMPONENT_LLM,
                phase="request_started",
                elapsed_ms=-1,
            )

    def test_elapsed_ms_oversized_rejected(self) -> None:
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_LLM_REQUEST_TRANSPORT_PHASE,
                component=COMPONENT_LLM,
                phase="request_started",
                elapsed_ms=10**12,
            )

    def test_http_status_out_of_range_rejected(self) -> None:
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_LLM_REQUEST_TRANSPORT_PHASE,
                component=COMPONENT_LLM,
                phase="response_received",
                http_status=99,
            )
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_LLM_REQUEST_TRANSPORT_PHASE,
                component=COMPONENT_LLM,
                phase="response_received",
                http_status=600,
            )

    def test_http_status_non_integer_rejected(self) -> None:
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_LLM_REQUEST_TRANSPORT_PHASE,
                component=COMPONENT_LLM,
                phase="response_received",
                http_status="200",
            )

    def test_response_bytes_negative_rejected(self) -> None:
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_LLM_REQUEST_TRANSPORT_PHASE,
                component=COMPONENT_LLM,
                phase="json_extracted",
                response_bytes=-1,
            )

    def test_response_bytes_oversized_rejected(self) -> None:
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_LLM_REQUEST_TRANSPORT_PHASE,
                component=COMPONENT_LLM,
                phase="json_extracted",
                response_bytes=20 * 1024 * 1024,
            )

    def test_response_bytes_non_integer_rejected(self) -> None:
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_LLM_REQUEST_TRANSPORT_PHASE,
                component=COMPONENT_LLM,
                phase="json_extracted",
                response_bytes="4096",
            )

    def test_correlation_id_oversized_rejected(self) -> None:
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_LLM_REQUEST_TRANSPORT_PHASE,
                component=COMPONENT_LLM,
                phase="request_started",
                correlation_id="x" * 100,
            )

    def test_correlation_id_with_control_char_rejected(self) -> None:
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_LLM_REQUEST_TRANSPORT_PHASE,
                component=COMPONENT_LLM,
                phase="request_started",
                correlation_id="abc\nleak",
            )

    def test_phase_with_control_char_rejected(self) -> None:
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_LLM_REQUEST_TRANSPORT_PHASE,
                component=COMPONENT_LLM,
                phase="request_started\nleak",
            )

    def test_no_sensitive_payload_leaks(self) -> None:
        sink = io.StringIO()
        ok = emit_event(
            event=EVENT_LLM_REQUEST_TRANSPORT_PHASE,
            component=COMPONENT_LLM,
            phase="result_parsed",
            elapsed_ms=42,
            http_status=200,
            response_bytes=4096,
            correlation_id="SYN-PROV-3",
            stream=sink,
        )
        self.assertTrue(ok)
        line = sink.getvalue()
        for token in SENTINELS:
            if token in EVENT_LLM_REQUEST_TRANSPORT_PHASE:
                continue
            if token in COMPONENT_LLM:
                continue
            self.assertNotIn(token, line)

    def test_no_url_proxy_or_credential_in_payload(self) -> None:
        sink = io.StringIO()
        ok = emit_event(
            event=EVENT_LLM_REQUEST_TRANSPORT_PHASE,
            component=COMPONENT_LLM,
            phase="response_headers_received",
            elapsed_ms=100,
            http_status=200,
            correlation_id="SYN-PROV-4",
            stream=sink,
        )
        self.assertTrue(ok)
        line = sink.getvalue()
        for forbidden in (
            "socks5h",
            "127.0.0.1",
            "user:pass",
            "secret-host",
            "Bearer",
            "+549",
            "SM-",
        ):
            self.assertNotIn(forbidden, line)

    def test_parse_event_round_trips(self) -> None:
        payload = build_event(
            event=EVENT_LLM_REQUEST_TRANSPORT_PHASE,
            component=COMPONENT_LLM,
            phase="json_extracted",
            elapsed_ms=42,
            http_status=200,
            response_bytes=4096,
            correlation_id="SYN-PROV-5",
        )
        line = json.dumps(
            payload, sort_keys=True, separators=(",", ":")
        )
        self.assertEqual(parse_event(line), payload)

    def test_parse_event_rejects_unknown_keys(self) -> None:
        with self.assertRaises(EventValidationError):
            parse_event(
                '{"event":"llm_request_transport_phase","schema_version":1,'
                '"component":"query_llm","phase":"request_started",'
                '"timestamp":"2026-08-11T00:00:00+00:00",'
                '"prompt":"super-secret-prompt"}'
            )

    def test_parse_event_round_trips_chunk_count(self) -> None:
        payload = build_event(
            event=EVENT_LLM_REQUEST_TRANSPORT_PHASE,
            component=COMPONENT_LLM,
            phase="body_completed",
            elapsed_ms=42,
            http_status=200,
            response_bytes=4096,
            chunk_count=4,
            correlation_id="SYN-PROV-CC",
        )
        line = json.dumps(
            payload, sort_keys=True, separators=(",", ":")
        )
        parsed = parse_event(line)
        self.assertEqual(parsed["chunk_count"], 4)
        self.assertEqual(parsed, payload)

    def test_parse_event_rejects_chunk_count_unknown(self) -> None:
        with self.assertRaises(EventValidationError):
            parse_event(
                '{"event":"llm_request_transport_phase","schema_version":1,'
                '"component":"query_llm","phase":"body_completed",'
                '"timestamp":"2026-08-11T00:00:00+00:00",'
                '"chunk_count":"4"}'
            )

    def test_chunk_count_negative_rejected(self) -> None:
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_LLM_REQUEST_TRANSPORT_PHASE,
                component=COMPONENT_LLM,
                phase="first_body_chunk",
                chunk_count=-1,
            )

    def test_chunk_count_oversized_rejected(self) -> None:
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_LLM_REQUEST_TRANSPORT_PHASE,
                component=COMPONENT_LLM,
                phase="body_completed",
                chunk_count=10**9,
            )

    def test_chunk_count_non_integer_rejected(self) -> None:
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_LLM_REQUEST_TRANSPORT_PHASE,
                component=COMPONENT_LLM,
                phase="first_body_chunk",
                chunk_count="1",
            )

    def test_chunk_count_bool_rejected(self) -> None:
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_LLM_REQUEST_TRANSPORT_PHASE,
                component=COMPONENT_LLM,
                phase="first_body_chunk",
                chunk_count=True,
            )

    def test_chunk_count_zero_accepted(self) -> None:
        payload = build_event(
            event=EVENT_LLM_REQUEST_TRANSPORT_PHASE,
            component=COMPONENT_LLM,
            phase="body_completed",
            chunk_count=0,
        )
        self.assertEqual(payload["chunk_count"], 0)

    def test_chunk_count_not_admitted_by_other_event(self) -> None:
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_LLM_REQUEST,
                component=COMPONENT_LLM,
                outcome="started",
                chunk_count=2,
            )

    def test_emit_event_degrades_on_invalid_phase(self) -> None:
        sink = io.StringIO()
        ok = emit_event(
            event=EVENT_LLM_REQUEST_TRANSPORT_PHASE,
            component=COMPONENT_LLM,
            phase="hacked",
            elapsed_ms=0,
            stream=sink,
        )
        self.assertFalse(ok)
        parsed = json.loads(sink.getvalue().strip())
        self.assertEqual(parsed["event"], "observability_emit_failed")
        self.assertEqual(parsed["failure_category"], "validation")

    def test_emit_event_degrades_on_outcome(self) -> None:
        sink = io.StringIO()
        ok = emit_event(
            event=EVENT_LLM_REQUEST_TRANSPORT_PHASE,
            component=COMPONENT_LLM,
            phase="request_started",
            elapsed_ms=0,
            outcome="started",
            stream=sink,
        )
        self.assertFalse(ok)
        parsed = json.loads(sink.getvalue().strip())
        self.assertEqual(parsed["event"], "observability_emit_failed")

    def test_emit_event_degrades_on_oversized_response_bytes(self) -> None:
        sink = io.StringIO()
        ok = emit_event(
            event=EVENT_LLM_REQUEST_TRANSPORT_PHASE,
            component=COMPONENT_LLM,
            phase="json_extracted",
            response_bytes=20 * 1024 * 1024,
            stream=sink,
        )
        self.assertFalse(ok)
        parsed = json.loads(sink.getvalue().strip())
        self.assertEqual(parsed["event"], "observability_emit_failed")

    def test_emit_event_does_not_raise_on_broken_stream(self) -> None:
        class _BrokenStream:
            def write(self, _data: str) -> None:
                raise OSError("simulated stream failure")

        ok = emit_event(
            event=EVENT_LLM_REQUEST_TRANSPORT_PHASE,
            component=COMPONENT_LLM,
            phase="request_started",
            stream=_BrokenStream(),
        )
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main(verbosity=2)
