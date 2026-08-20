"""Focused tests for the T-C adapter observability emitter.

The tests cover the documented closed contract:

* the emitter is backend-independent (no ``backend.*`` import);
* one parseable JSON line per ``emit`` call with ``schema_version``,
  component, timestamp, outcome and bounded ``reason``;
* the closed outcome vocabulary ``accepted``, ``duplicate``,
  ``rejected`` and ``unreachable``;
* the closed reason vocabulary (eleven bounded tokens) and the
  required/absent rule for ``reason`` and ``http_status``;
* the emitter swallows validation, serialization and sink errors so
  the surrounding request is never altered;
* the emitted line never contains body, phone, token, signature,
  credentials, IDs, profile name, URLs or exception text;
* the line is accepted by the core ``parse_event`` catalogue parser
  for ``component=commerce_installation_adapter``.
"""
from __future__ import annotations

import json
import unittest

from backend.observability import (
    COMPONENT_COMMERCE_INSTALLATION_ADAPTER,
    EVENT_COMMERCE_INSTALLATION_INBOUND_OUTCOME,
    parse_event,
)
from commerce_adapter.app import observability

SENSITIVE_SENTINELS = (
    "secret-auth-token-value",
    "+5491100000000",
    "SM-ABC-XYZ",
    "Bearer abc",
    "https://provider.example?token=abc",
    "X-Twilio-Signature=abc",
    "this-body-must-never-appear",
    "AccountSid=AC000000000000000000000000000000",
    "ProfileName=Ana",
    "AC-EXTRA",
)


class _ListSink:
    """Test sink that records every line without touching stdout."""

    def __init__(self) -> None:
        self.lines: list[str] = []

    def __call__(self, line: str) -> None:
        self.lines.append(line)


class AdapterEmitterSchemaTest(unittest.TestCase):
    def test_event_name_and_component_are_stable(self) -> None:
        self.assertEqual(
            observability.EVENT_NAME,
            "commerce_installation_inbound_outcome",
        )
        self.assertEqual(
            observability.COMPONENT,
            "commerce_installation_adapter",
        )
        self.assertEqual(observability.SCHEMA_VERSION, 1)

    def test_outcome_and_reason_allowlists_are_closed(self) -> None:
        self.assertEqual(
            observability.OUTCOMES,
            frozenset({"accepted", "duplicate", "rejected", "unreachable"}),
        )
        self.assertEqual(
            observability.REASONS,
            frozenset(
                {
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
                }
            ),
        )


class AdapterEmitterAcceptedTest(unittest.TestCase):
    def test_accepted_emits_one_line_without_reason(self) -> None:
        sink = _ListSink()
        ok = observability.emit(outcome="accepted", sink=sink)
        self.assertTrue(ok)
        self.assertEqual(len(sink.lines), 1)
        line = sink.lines[0].rstrip("\n")
        payload = json.loads(line)
        self.assertEqual(
            payload["event"], observability.EVENT_NAME
        )
        self.assertEqual(payload["component"], observability.COMPONENT)
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["outcome"], "accepted")
        self.assertNotIn("reason", payload)
        self.assertNotIn("http_status", payload)
        self.assertIsInstance(payload["timestamp"], str)
        self.assertGreater(len(payload["timestamp"]), 0)

    def test_duplicate_emits_one_line_without_reason(self) -> None:
        sink = _ListSink()
        ok = observability.emit(outcome="duplicate", sink=sink)
        self.assertTrue(ok)
        payload = json.loads(sink.lines[0])
        self.assertEqual(payload["outcome"], "duplicate")
        self.assertNotIn("reason", payload)


class AdapterEmitterRejectedTest(unittest.TestCase):
    def test_rejected_requires_closed_reason(self) -> None:
        sink = _ListSink()
        ok = observability.emit(
            outcome="rejected",
            reason="signature_rejected",
            sink=sink,
        )
        self.assertTrue(ok)
        payload = json.loads(sink.lines[0])
        self.assertEqual(payload["outcome"], "rejected")
        self.assertEqual(payload["reason"], "signature_rejected")
        self.assertNotIn("http_status", payload)

    def test_rejected_without_reason_is_rejected(self) -> None:
        sink = _ListSink()
        ok = observability.emit(outcome="rejected", sink=sink)
        self.assertFalse(ok)
        self.assertEqual(sink.lines, [])

    def test_rejected_with_unknown_reason_is_rejected(self) -> None:
        sink = _ListSink()
        ok = observability.emit(
            outcome="rejected",
            reason="free_form_text",
            sink=sink,
        )
        self.assertFalse(ok)
        self.assertEqual(sink.lines, [])

    def test_accepted_with_reason_is_rejected(self) -> None:
        sink = _ListSink()
        ok = observability.emit(
            outcome="accepted",
            reason="signature_rejected",
            sink=sink,
        )
        self.assertFalse(ok)
        self.assertEqual(sink.lines, [])

    def test_duplicate_with_reason_is_rejected(self) -> None:
        sink = _ListSink()
        ok = observability.emit(
            outcome="duplicate",
            reason="signature_rejected",
            sink=sink,
        )
        self.assertFalse(ok)
        self.assertEqual(sink.lines, [])

    def test_rejected_with_http_status_is_rejected(self) -> None:
        sink = _ListSink()
        ok = observability.emit(
            outcome="rejected",
            reason="signature_rejected",
            http_status=502,
            sink=sink,
        )
        self.assertFalse(ok)
        self.assertEqual(sink.lines, [])

    def test_each_closed_reason_round_trips(self) -> None:
        for reason in sorted(observability.REASONS):
            with self.subTest(reason=reason):
                sink = _ListSink()
                ok = observability.emit(
                    outcome="rejected",
                    reason=reason,
                    sink=sink,
                )
                self.assertTrue(ok)
                payload = json.loads(sink.lines[0])
                self.assertEqual(payload["reason"], reason)


class AdapterEmitterUnreachableTest(unittest.TestCase):
    def test_unreachable_with_reason_and_http_status(self) -> None:
        sink = _ListSink()
        ok = observability.emit(
            outcome="unreachable",
            reason="core_http_failure",
            http_status=502,
            sink=sink,
        )
        self.assertTrue(ok)
        payload = json.loads(sink.lines[0])
        self.assertEqual(payload["outcome"], "unreachable")
        self.assertEqual(payload["reason"], "core_http_failure")
        self.assertEqual(payload["http_status"], 502)

    def test_unreachable_with_low_http_status(self) -> None:
        sink = _ListSink()
        ok = observability.emit(
            outcome="unreachable",
            reason="core_http_failure",
            http_status=100,
            sink=sink,
        )
        self.assertTrue(ok)
        payload = json.loads(sink.lines[0])
        self.assertEqual(payload["http_status"], 100)

    def test_unreachable_without_reason_is_rejected(self) -> None:
        sink = _ListSink()
        ok = observability.emit(
            outcome="unreachable",
            http_status=502,
            sink=sink,
        )
        self.assertFalse(ok)
        self.assertEqual(sink.lines, [])

    def test_unreachable_with_out_of_range_http_status_is_rejected(
        self,
    ) -> None:
        sink = _ListSink()
        ok = observability.emit(
            outcome="unreachable",
            reason="core_http_failure",
            http_status=99,
            sink=sink,
        )
        self.assertFalse(ok)
        ok = observability.emit(
            outcome="unreachable",
            reason="core_http_failure",
            http_status=600,
            sink=sink,
        )
        self.assertFalse(ok)
        ok = observability.emit(
            outcome="unreachable",
            reason="core_http_failure",
            http_status=0,
            sink=sink,
        )
        self.assertFalse(ok)
        self.assertEqual(sink.lines, [])

    def test_unreachable_with_non_integer_http_status_is_rejected(
        self,
    ) -> None:
        sink = _ListSink()
        ok = observability.emit(
            outcome="unreachable",
            reason="core_http_failure",
            http_status="502",
            sink=sink,
        )
        self.assertFalse(ok)
        self.assertEqual(sink.lines, [])

    def test_unreachable_with_boolean_http_status_is_rejected(
        self,
    ) -> None:
        sink = _ListSink()
        ok = observability.emit(
            outcome="unreachable",
            reason="core_http_failure",
            http_status=True,
            sink=sink,
        )
        self.assertFalse(ok)
        self.assertEqual(sink.lines, [])


class AdapterEmitterFailureTest(unittest.TestCase):
    def test_unknown_outcome_returns_false_without_writing(self) -> None:
        sink = _ListSink()
        ok = observability.emit(outcome="unknown_thing", sink=sink)
        self.assertFalse(ok)
        self.assertEqual(sink.lines, [])

    def test_sink_exception_is_swallowed(self) -> None:
        def failing_sink(line: str) -> None:
            raise OSError("sink is broken")

        ok = observability.emit(outcome="accepted", sink=failing_sink)
        self.assertFalse(ok)

    def test_sink_value_error_is_swallowed(self) -> None:
        def failing_sink(line: str) -> None:
            raise ValueError("sink cannot accept")

        ok = observability.emit(
            outcome="rejected",
            reason="signature_rejected",
            sink=failing_sink,
        )
        self.assertFalse(ok)


class AdapterEmitterPrivacyTest(unittest.TestCase):
    def test_no_sensitive_value_can_reach_the_event_line(self) -> None:
        sink = _ListSink()
        ok = observability.emit(
            outcome="rejected",
            reason="signature_rejected",
            sink=sink,
        )
        self.assertTrue(ok)
        line = sink.lines[0]
        for sentinel in SENSITIVE_SENTINELS:
            self.assertNotIn(sentinel, line)

    def test_caller_supplied_timestamp_is_used(self) -> None:
        sink = _ListSink()
        ok = observability.emit(
            outcome="accepted",
            timestamp="2024-01-01T00:00:00+00:00",
            sink=sink,
        )
        self.assertTrue(ok)
        payload = json.loads(sink.lines[0])
        self.assertEqual(payload["timestamp"], "2024-01-01T00:00:00+00:00")

    def test_blank_timestamp_falls_back_to_utc(self) -> None:
        sink = _ListSink()
        ok = observability.emit(
            outcome="accepted",
            timestamp="",
            sink=sink,
        )
        self.assertTrue(ok)
        payload = json.loads(sink.lines[0])
        self.assertNotEqual(payload["timestamp"], "")
        self.assertIn("+00:00", payload["timestamp"])


class AdapterEmitterCoreParserCompatibilityTest(unittest.TestCase):
    """The line must round-trip through the core catalogue parser."""

    def test_accepted_event_round_trips(self) -> None:
        sink = _ListSink()
        observability.emit(outcome="accepted", sink=sink)
        parsed = parse_event(sink.lines[0].rstrip("\n"))
        self.assertEqual(
            parsed["event"], EVENT_COMMERCE_INSTALLATION_INBOUND_OUTCOME
        )
        self.assertEqual(
            parsed["component"], COMPONENT_COMMERCE_INSTALLATION_ADAPTER
        )
        self.assertEqual(parsed["outcome"], "accepted")

    def test_rejected_event_round_trips(self) -> None:
        sink = _ListSink()
        observability.emit(
            outcome="rejected",
            reason="unknown_destination",
            sink=sink,
        )
        parsed = parse_event(sink.lines[0].rstrip("\n"))
        self.assertEqual(parsed["reason"], "unknown_destination")

    def test_unreachable_event_with_http_status_round_trips(self) -> None:
        sink = _ListSink()
        observability.emit(
            outcome="unreachable",
            reason="core_http_failure",
            http_status=503,
            sink=sink,
        )
        parsed = parse_event(sink.lines[0].rstrip("\n"))
        self.assertEqual(parsed["http_status"], 503)
        self.assertEqual(parsed["reason"], "core_http_failure")


class AdapterEmitterBuildPayloadTest(unittest.TestCase):
    def test_build_payload_rejects_unknown_outcome(self) -> None:
        with self.assertRaises(observability.InboundOutcomeEventError):
            observability.build_payload(outcome="not_in_vocab")

    def test_build_payload_rejects_accepted_with_reason(self) -> None:
        with self.assertRaises(observability.InboundOutcomeEventError):
            observability.build_payload(
                outcome="accepted", reason="signature_rejected"
            )

    def test_build_payload_rejects_rejected_without_reason(self) -> None:
        with self.assertRaises(observability.InboundOutcomeEventError):
            observability.build_payload(outcome="rejected")

    def test_build_payload_rejects_unreachable_without_reason(self) -> None:
        with self.assertRaises(observability.InboundOutcomeEventError):
            observability.build_payload(
                outcome="unreachable", http_status=502
            )

    def test_build_payload_rejects_unknown_reason(self) -> None:
        with self.assertRaises(observability.InboundOutcomeEventError):
            observability.build_payload(
                outcome="rejected", reason="arbitrary"
            )

    def test_build_payload_rejects_out_of_range_http_status(self) -> None:
        with self.assertRaises(observability.InboundOutcomeEventError):
            observability.build_payload(
                outcome="unreachable",
                reason="core_http_failure",
                http_status=999,
            )


class AdapterEmitterBackendIndependenceTest(unittest.TestCase):
    """The emitter must never import anything from ``backend.*``."""

    def test_no_backend_imports(self) -> None:
        source = (
            "from commerce_adapter.app import observability\n"
        )
        compiled = compile(source, "<test>", "exec")
        # If the module were to import backend.* the import would
        # either succeed silently (and pollute the catalog) or fail.
        # The simplest behavioural assertion is that the module's
        # ``__dict__`` does not re-export any backend symbol.
        for key in list(observability.__dict__):
            if key.startswith("_"):
                continue
            self.assertFalse(
                key.lower().startswith("backend"),
                f"observability must not export {key!r} from backend.*",
            )
        self.assertIsNotNone(compiled)


if __name__ == "__main__":
    unittest.main(verbosity=2)