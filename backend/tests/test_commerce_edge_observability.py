"""Focused tests for the ``commerce_installation_inbound_outcome``
core catalogue entry.

The tests cover:

* the closed outcome vocabulary (``accepted``, ``duplicate``,
  ``rejected``, ``unreachable``);
* the closed reason vocabulary (eleven bounded tokens) and the
  required/absent rule that ties ``reason`` to the outcome;
* the dual-component contract: the catalogue and parser accept
  ``commerce_installation_ingress`` and
  ``commerce_installation_adapter`` and reject every other
  component;
* ``http_status`` is allowed only for the adapter ``unreachable``
  outcome and must be a bounded integer;
* ``build_event`` / ``parse_event`` reject unknown fields, free-form
  reasons, sensitive values, identifiers and PII;
* the existing ``backend.cli.query_production_logs`` Railway parser
  round-trips both edge components.
"""
from __future__ import annotations

import io
import json
import unittest

from backend.observability import (
    COMPONENT_COMMERCE_INSTALLATION_ADAPTER,
    COMPONENT_COMMERCE_INSTALLATION_INGRESS,
    EVENT_COMMERCE_INSTALLATION_INBOUND_OUTCOME,
    SCHEMA_VERSION,
    EventValidationError,
    build_event,
    emit_event,
    parse_event,
)

SENSITIVE_SENTINELS = (
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
)


class CatalogueConstantsTest(unittest.TestCase):
    def test_event_name_is_stable(self) -> None:
        self.assertEqual(
            EVENT_COMMERCE_INSTALLATION_INBOUND_OUTCOME,
            "commerce_installation_inbound_outcome",
        )

    def test_components_are_documented(self) -> None:
        self.assertEqual(
            COMPONENT_COMMERCE_INSTALLATION_INGRESS,
            "commerce_installation_ingress",
        )
        self.assertEqual(
            COMPONENT_COMMERCE_INSTALLATION_ADAPTER,
            "commerce_installation_adapter",
        )


class CatalogueOutcomeTest(unittest.TestCase):
    def test_accepted_round_trips_without_reason(self) -> None:
        payload = build_event(
            event=EVENT_COMMERCE_INSTALLATION_INBOUND_OUTCOME,
            component=COMPONENT_COMMERCE_INSTALLATION_INGRESS,
            outcome="accepted",
        )
        self.assertEqual(payload["event"], EVENT_COMMERCE_INSTALLATION_INBOUND_OUTCOME)
        self.assertEqual(payload["outcome"], "accepted")
        self.assertEqual(payload["component"], COMPONENT_COMMERCE_INSTALLATION_INGRESS)
        self.assertEqual(payload["schema_version"], int(SCHEMA_VERSION))
        self.assertNotIn("reason", payload)
        self.assertNotIn("http_status", payload)

    def test_duplicate_round_trips_without_reason(self) -> None:
        payload = build_event(
            event=EVENT_COMMERCE_INSTALLATION_INBOUND_OUTCOME,
            component=COMPONENT_COMMERCE_INSTALLATION_ADAPTER,
            outcome="duplicate",
        )
        self.assertEqual(payload["outcome"], "duplicate")
        self.assertNotIn("reason", payload)

    def test_rejected_requires_closed_reason(self) -> None:
        payload = build_event(
            event=EVENT_COMMERCE_INSTALLATION_INBOUND_OUTCOME,
            component=COMPONENT_COMMERCE_INSTALLATION_INGRESS,
            outcome="rejected",
            reason="unknown_destination",
        )
        self.assertEqual(payload["outcome"], "rejected")
        self.assertEqual(payload["reason"], "unknown_destination")

    def test_unreachable_round_trips_with_reason(self) -> None:
        payload = build_event(
            event=EVENT_COMMERCE_INSTALLATION_INBOUND_OUTCOME,
            component=COMPONENT_COMMERCE_INSTALLATION_ADAPTER,
            outcome="unreachable",
            reason="core_http_failure",
        )
        self.assertEqual(payload["outcome"], "unreachable")
        self.assertEqual(payload["reason"], "core_http_failure")

    def test_unknown_outcome_is_rejected(self) -> None:
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_COMMERCE_INSTALLATION_INBOUND_OUTCOME,
                component=COMPONENT_COMMERCE_INSTALLATION_INGRESS,
                outcome="mystery",
            )


class CatalogueReasonTest(unittest.TestCase):
    def _build(self, outcome: str, reason: str | None) -> dict:
        return build_event(
            event=EVENT_COMMERCE_INSTALLATION_INBOUND_OUTCOME,
            component=COMPONENT_COMMERCE_INSTALLATION_INGRESS,
            outcome=outcome,
            reason=reason,
        )

    def test_each_closed_reason_round_trips_for_rejected(self) -> None:
        for reason in (
            "signature_rejected",
            "invalid_form",
            "missing_comercio_id",
            "core_http_failure",
            "core_invalid_response",
            "unknown_destination",
            "shared_channel_not_supported",
            "channel_commerce_mismatch",
            "unknown_client",
            "unavailable_commerce",
            "invalid_context",
        ):
            with self.subTest(reason=reason):
                payload = self._build("rejected", reason)
                self.assertEqual(payload["reason"], reason)

    def test_each_closed_reason_round_trips_for_unreachable(self) -> None:
        for reason in (
            "signature_rejected",
            "core_http_failure",
            "core_invalid_response",
        ):
            with self.subTest(reason=reason):
                payload = self._build("unreachable", reason)
                self.assertEqual(payload["reason"], reason)

    def test_rejected_without_reason_is_rejected(self) -> None:
        with self.assertRaises(EventValidationError):
            self._build("rejected", None)

    def test_unreachable_without_reason_is_rejected(self) -> None:
        with self.assertRaises(EventValidationError):
            self._build("unreachable", None)

    def test_accepted_with_reason_is_rejected(self) -> None:
        with self.assertRaises(EventValidationError):
            self._build("accepted", "unknown_client")

    def test_duplicate_with_reason_is_rejected(self) -> None:
        with self.assertRaises(EventValidationError):
            self._build("duplicate", "unknown_client")

    def test_unknown_reason_token_is_rejected(self) -> None:
        with self.assertRaises(EventValidationError):
            self._build("rejected", "free_form_text")

    def test_reason_with_pii_is_rejected(self) -> None:
        with self.assertRaises(EventValidationError):
            self._build("rejected", "+5491100000000")
        with self.assertRaises(EventValidationError):
            self._build("rejected", "SM-ABC-XYZ")

    def test_failure_category_is_rejected_for_this_event(self) -> None:
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_COMMERCE_INSTALLATION_INBOUND_OUTCOME,
                component=COMPONENT_COMMERCE_INSTALLATION_INGRESS,
                failure_category="validation",
            )

    def test_recognition_fields_are_rejected_for_this_event(self) -> None:
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_COMMERCE_INSTALLATION_INBOUND_OUTCOME,
                component=COMPONENT_COMMERCE_INSTALLATION_INGRESS,
                outcome="accepted",
                configured_mode="fuzzy",
            )

    def test_pending_context_fields_are_rejected_for_this_event(self) -> None:
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_COMMERCE_INSTALLATION_INBOUND_OUTCOME,
                component=COMPONENT_COMMERCE_INSTALLATION_INGRESS,
                outcome="accepted",
                context_kind="product_selection",
            )

    def test_optional_fields_outside_allowlist_are_rejected(self) -> None:
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_COMMERCE_INSTALLATION_INBOUND_OUTCOME,
                component=COMPONENT_COMMERCE_INSTALLATION_INGRESS,
                outcome="accepted",
                outbox_id=42,
            )
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_COMMERCE_INSTALLATION_INBOUND_OUTCOME,
                component=COMPONENT_COMMERCE_INSTALLATION_INGRESS,
                outcome="accepted",
                provider_code="twilio",
            )
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_COMMERCE_INSTALLATION_INBOUND_OUTCOME,
                component=COMPONENT_COMMERCE_INSTALLATION_INGRESS,
                outcome="accepted",
                exception_type="ValueError",
            )


class CatalogueComponentTest(unittest.TestCase):
    def test_core_component_is_accepted(self) -> None:
        payload = build_event(
            event=EVENT_COMMERCE_INSTALLATION_INBOUND_OUTCOME,
            component=COMPONENT_COMMERCE_INSTALLATION_INGRESS,
            outcome="accepted",
        )
        self.assertEqual(
            payload["component"], COMPONENT_COMMERCE_INSTALLATION_INGRESS
        )

    def test_adapter_component_is_accepted(self) -> None:
        payload = build_event(
            event=EVENT_COMMERCE_INSTALLATION_INBOUND_OUTCOME,
            component=COMPONENT_COMMERCE_INSTALLATION_ADAPTER,
            outcome="accepted",
        )
        self.assertEqual(
            payload["component"], COMPONENT_COMMERCE_INSTALLATION_ADAPTER
        )

    def test_unknown_component_is_rejected(self) -> None:
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_COMMERCE_INSTALLATION_INBOUND_OUTCOME,
                component="commerce_installation_somebody",
                outcome="accepted",
            )
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_COMMERCE_INSTALLATION_INBOUND_OUTCOME,
                component="twilio_callback",
                outcome="accepted",
            )

    def test_empty_component_is_rejected(self) -> None:
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_COMMERCE_INSTALLATION_INBOUND_OUTCOME,
                component="",
                outcome="accepted",
            )


class CatalogueHttpStatusTest(unittest.TestCase):
    def test_http_status_allowed_for_adapter_unreachable(self) -> None:
        payload = build_event(
            event=EVENT_COMMERCE_INSTALLATION_INBOUND_OUTCOME,
            component=COMPONENT_COMMERCE_INSTALLATION_ADAPTER,
            outcome="unreachable",
            reason="core_http_failure",
            http_status=502,
        )
        self.assertEqual(payload["http_status"], 502)

    def test_http_status_rejected_for_core_component(self) -> None:
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_COMMERCE_INSTALLATION_INBOUND_OUTCOME,
                component=COMPONENT_COMMERCE_INSTALLATION_INGRESS,
                outcome="unreachable",
                reason="core_http_failure",
                http_status=502,
            )

    def test_http_status_rejected_for_non_unreachable_outcome(self) -> None:
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_COMMERCE_INSTALLATION_INBOUND_OUTCOME,
                component=COMPONENT_COMMERCE_INSTALLATION_ADAPTER,
                outcome="rejected",
                reason="signature_rejected",
                http_status=502,
            )

    def test_http_status_out_of_range_is_rejected(self) -> None:
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_COMMERCE_INSTALLATION_INBOUND_OUTCOME,
                component=COMPONENT_COMMERCE_INSTALLATION_ADAPTER,
                outcome="unreachable",
                reason="core_http_failure",
                http_status=99,
            )
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_COMMERCE_INSTALLATION_INBOUND_OUTCOME,
                component=COMPONENT_COMMERCE_INSTALLATION_ADAPTER,
                outcome="unreachable",
                reason="core_http_failure",
                http_status=600,
            )

    def test_http_status_must_be_integer(self) -> None:
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_COMMERCE_INSTALLATION_INBOUND_OUTCOME,
                component=COMPONENT_COMMERCE_INSTALLATION_ADAPTER,
                outcome="unreachable",
                reason="core_http_failure",
                http_status="502",  # type: ignore[arg-type]
            )
        with self.assertRaises(EventValidationError):
            build_event(
                event=EVENT_COMMERCE_INSTALLATION_INBOUND_OUTCOME,
                component=COMPONENT_COMMERCE_INSTALLATION_ADAPTER,
                outcome="unreachable",
                reason="core_http_failure",
                http_status=True,
            )


class ParseEventRoundTripTest(unittest.TestCase):
    def test_core_event_round_trips_through_parse_event(self) -> None:
        buf = io.StringIO()
        emit_event(
            event=EVENT_COMMERCE_INSTALLATION_INBOUND_OUTCOME,
            component=COMPONENT_COMMERCE_INSTALLATION_INGRESS,
            outcome="rejected",
            reason="unknown_client",
            stream=buf,
        )
        parsed = parse_event(buf.getvalue().rstrip("\n"))
        self.assertEqual(
            parsed["component"], COMPONENT_COMMERCE_INSTALLATION_INGRESS
        )
        self.assertEqual(parsed["outcome"], "rejected")
        self.assertEqual(parsed["reason"], "unknown_client")

    def test_adapter_event_round_trips_through_parse_event(self) -> None:
        buf = io.StringIO()
        emit_event(
            event=EVENT_COMMERCE_INSTALLATION_INBOUND_OUTCOME,
            component=COMPONENT_COMMERCE_INSTALLATION_ADAPTER,
            outcome="unreachable",
            reason="core_http_failure",
            http_status=503,
            stream=buf,
        )
        parsed = parse_event(buf.getvalue().rstrip("\n"))
        self.assertEqual(
            parsed["component"], COMPONENT_COMMERCE_INSTALLATION_ADAPTER
        )
        self.assertEqual(parsed["http_status"], 503)

    def test_parse_event_rejects_unknown_component(self) -> None:
        line = json.dumps(
            {
                "event": EVENT_COMMERCE_INSTALLATION_INBOUND_OUTCOME,
                "component": "commerce_installation_other",
                "schema_version": int(SCHEMA_VERSION),
                "outcome": "accepted",
                "timestamp": "2024-01-01T00:00:00+00:00",
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        with self.assertRaises(EventValidationError):
            parse_event(line)

    def test_parse_event_rejects_unknown_keys(self) -> None:
        line = json.dumps(
            {
                "event": EVENT_COMMERCE_INSTALLATION_INBOUND_OUTCOME,
                "component": COMPONENT_COMMERCE_INSTALLATION_INGRESS,
                "schema_version": int(SCHEMA_VERSION),
                "outcome": "accepted",
                "timestamp": "2024-01-01T00:00:00+00:00",
                "phone": "+5491100000000",
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        with self.assertRaises(EventValidationError):
            parse_event(line)

    def test_parse_event_rejects_free_form_reason(self) -> None:
        line = json.dumps(
            {
                "event": EVENT_COMMERCE_INSTALLATION_INBOUND_OUTCOME,
                "component": COMPONENT_COMMERCE_INSTALLATION_INGRESS,
                "schema_version": int(SCHEMA_VERSION),
                "outcome": "rejected",
                "reason": "free_form_text",
                "timestamp": "2024-01-01T00:00:00+00:00",
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        with self.assertRaises(EventValidationError):
            parse_event(line)

    def test_parse_event_rejects_wrong_schema_version(self) -> None:
        line = json.dumps(
            {
                "event": EVENT_COMMERCE_INSTALLATION_INBOUND_OUTCOME,
                "component": COMPONENT_COMMERCE_INSTALLATION_INGRESS,
                "schema_version": 2,
                "outcome": "accepted",
                "timestamp": "2024-01-01T00:00:00+00:00",
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        with self.assertRaises(EventValidationError):
            parse_event(line)


class RailwayParserCompatibilityTest(unittest.TestCase):
    """The Railway query CLI parser must accept both components."""

    def test_core_event_is_accepted_by_query_production_logs(self) -> None:
        from backend.cli.query_production_logs import (
            _extract_event_from_line,
        )

        line = json.dumps(
            {
                "event": EVENT_COMMERCE_INSTALLATION_INBOUND_OUTCOME,
                "component": COMPONENT_COMMERCE_INSTALLATION_INGRESS,
                "schema_version": int(SCHEMA_VERSION),
                "outcome": "rejected",
                "reason": "unknown_client",
                "timestamp": "2024-01-01T00:00:00+00:00",
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        parsed = _extract_event_from_line(line)
        self.assertIsNotNone(parsed)
        self.assertEqual(
            parsed["component"], COMPONENT_COMMERCE_INSTALLATION_INGRESS
        )

    def test_adapter_event_is_accepted_by_query_production_logs(self) -> None:
        from backend.cli.query_production_logs import (
            _extract_event_from_line,
        )

        line = json.dumps(
            {
                "event": EVENT_COMMERCE_INSTALLATION_INBOUND_OUTCOME,
                "component": COMPONENT_COMMERCE_INSTALLATION_ADAPTER,
                "schema_version": int(SCHEMA_VERSION),
                "outcome": "unreachable",
                "reason": "core_http_failure",
                "http_status": 502,
                "timestamp": "2024-01-01T00:00:00+00:00",
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        parsed = _extract_event_from_line(line)
        self.assertIsNotNone(parsed)
        self.assertEqual(
            parsed["component"], COMPONENT_COMMERCE_INSTALLATION_ADAPTER
        )

    def test_unknown_component_is_rejected_by_query_production_logs(
        self,
    ) -> None:
        from backend.cli.query_production_logs import (
            UnparseableRailwayOutputError,
            _extract_event_from_line,
        )

        line = json.dumps(
            {
                "event": EVENT_COMMERCE_INSTALLATION_INBOUND_OUTCOME,
                "component": "commerce_installation_other",
                "schema_version": int(SCHEMA_VERSION),
                "outcome": "accepted",
                "timestamp": "2024-01-01T00:00:00+00:00",
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        with self.assertRaises(UnparseableRailwayOutputError):
            _extract_event_from_line(line)


class CataloguePrivacyTest(unittest.TestCase):
    def _emitted_payload(self, **kwargs) -> dict:
        buf = io.StringIO()
        ok = emit_event(
            event=EVENT_COMMERCE_INSTALLATION_INBOUND_OUTCOME,
            component=COMPONENT_COMMERCE_INSTALLATION_INGRESS,
            stream=buf,
            **kwargs,
        )
        self.assertTrue(ok)
        return json.loads(buf.getvalue().rstrip("\n"))

    def test_emitted_event_carries_no_pii(self) -> None:
        payload = self._emitted_payload(outcome="rejected", reason="unknown_client")
        serialized = json.dumps(payload, sort_keys=True)
        for sentinel in SENSITIVE_SENTINELS:
            self.assertNotIn(sentinel, serialized)

    def test_emitted_event_carries_no_identifier_payload_or_signature(self) -> None:
        payload = self._emitted_payload(
            outcome="rejected", reason="signature_rejected"
        )
        forbidden_fields = (
            "instalacion_id", "comercio_id", "canal_id",
            "cliente_id", "receipt_id", "cuerpo",
            "from_e164", "to_e164", "message_sid",
            "phone", "body", "token", "credential",
            "signature", "url", "x-twilio-signature",
        )
        for forbidden in forbidden_fields:
            self.assertNotIn(forbidden, payload)
        self.assertEqual(
            set(payload.keys()),
            {
                "component",
                "event",
                "outcome",
                "reason",
                "schema_version",
                "timestamp",
            },
        )

    def test_emitted_event_carries_no_exception_text(self) -> None:
        payload = self._emitted_payload(outcome="rejected", reason="invalid_context")
        serialized = json.dumps(payload, sort_keys=True)
        self.assertNotIn("Traceback", serialized)
        self.assertNotIn("Exception", serialized)
        self.assertNotIn("ValueError", serialized)


class CatalogueEmissionFailureTest(unittest.TestCase):
    """An emitter failure must NOT mutate the surrounding caller."""

    def test_invalid_event_does_not_raise(self) -> None:
        buf = io.StringIO()
        ok = emit_event(
            event=EVENT_COMMERCE_INSTALLATION_INBOUND_OUTCOME,
            component="not_a_component",
            outcome="accepted",
            stream=buf,
        )
        self.assertFalse(ok)
        # Only a degraded event should have been written.
        content = buf.getvalue().strip()
        self.assertIn("observability_emit_failed", content)

    def test_invalid_outcome_does_not_raise(self) -> None:
        buf = io.StringIO()
        ok = emit_event(
            event=EVENT_COMMERCE_INSTALLATION_INBOUND_OUTCOME,
            component=COMPONENT_COMMERCE_INSTALLATION_INGRESS,
            outcome="mystery",
            stream=buf,
        )
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main(verbosity=2)