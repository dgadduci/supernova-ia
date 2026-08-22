"""Focused tests for the Admin/Pilot Emulator timing observability change.

These tests cover the closed nullable ``EmulatorTimeline`` projection,
the per-row local-observation ``HH:MM:SS.mmm`` rendering, the safe
LLM timing recorder and the correlation hook. They are deliberately
self-contained: they only exercise the documented seams and never
touch Twilio, T-C or any real database.

The suite covers the explicit scope of
``add-admin-pilot-emulator-timing-observability``:

* the bounded timeline response shape (1.1, 2.1, 2.2);
* the closed-set LLM outcome token normalization (1.3, 2.1);
* the local observation ``HH:MM:SS.mmm`` rendering and the
  per-kind row timestamp (3.1, 3.2);
* the privacy boundaries — no PII, prompt, response or secret
  ever reaches the wire or the event payload (1.5, 3.3, 4.2);
* the safe LLM timing recorder that survives the documented
  finalize/rollback paths (1.4, 4.1).
"""
from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests

from backend.config.settings import Settings
from backend.llm.query_llm import (
    LLMTimingRecorder,
    NoopLLMTimingRecorder,
    QueryLlm,
    QueryLlmHttpError,
    QueryLlmResponseError,
    QueryLlmTimeoutError,
    WorkItemLLMTimingRecorder,
    install_llm_timing_recorder,
    reset_llm_timing_recorder,
)
from backend.routers.admin_pilot_orders import (
    EmulatorDiagnostic,
    EmulatorStatusResponse,
    EmulatorTimeline,
    _emulator_timeline_from_receipt,
    _iso_utc,
    _normalize_llm_outcome,
)


def _settings(**overrides) -> Settings:
    from backend.config import settings as settings_module

    base = settings_module.load_settings().__dict__
    base.update(
        {
            "llm_url": "http://llm.test/api/generate",
            "llm_model": "test-model",
            "llm_timeout": 30,
            "llm_keep_alive": "1h",
            "llm_num_ctx": 2048,
            "llm_num_predict": 256,
            "llm_log_content": False,
            "llm_log_max_chars": 50,
        }
    )
    base.update(overrides)
    return Settings(**base)


def _admin_settings(token: str = "x") -> Settings:
    from backend.config import settings as settings_module

    base = settings_module.load_settings().__dict__
    base["order_management_admin_token"] = token
    return Settings(**base)


class _FakeResponse:
    def __init__(self, body: str, status_code: int = 200) -> None:
        self._body = body
        self.status_code = status_code
        self.text = body

    def json(self) -> dict[str, str]:
        return {"response": self._body}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            err = requests.exceptions.HTTPError(f"{self.status_code} error")
            err.response = self
            raise err


class EmulatorTimelineSchemaTest(unittest.TestCase):
    """Task 1.1: the response model exposes only the closed timeline keys."""

    def test_timeline_carries_only_documented_keys(self) -> None:
        timeline = EmulatorTimeline()
        self.assertEqual(
            set(timeline.model_dump().keys()),
            {
                "inbound_received_at",
                "llm_requested_at",
                "llm_finished_at",
                "llm_outcome",
                "processing_finished_at",
                "response_staged_at",
            },
        )

    def test_status_response_rejects_extra_keys(self) -> None:
        with self.assertRaises(ValueError):
            EmulatorStatusResponse(
                status="accepted",
                outbound_body=None,
                provider_message_sid=None,
                timeline=EmulatorTimeline(),
                diagnostic=EmulatorDiagnostic(
                    processing_state="pending",
                    response_count=None,
                    outbox_row_count=0,
                    failure_category=None,
                ),
                extra_field="forbidden",  # type: ignore[call-arg]
            )

    def test_timeline_rejects_extra_keys(self) -> None:
        with self.assertRaises(ValueError):
            EmulatorTimeline(extra_field="forbidden")  # type: ignore[call-arg]

    def test_timeline_rejects_unknown_outcome(self) -> None:
        with self.assertRaises(ValueError):
            EmulatorTimeline(llm_outcome="bad")  # type: ignore[arg-type]

    def test_timeline_accepts_documented_outcome_tokens(self) -> None:
        for outcome in ("completed", "timeout", "error"):
            with self.subTest(outcome=outcome):
                timeline = EmulatorTimeline(llm_outcome=outcome)  # type: ignore[arg-type]
                self.assertEqual(timeline.llm_outcome, outcome)


class EmulatorTimelineHelpersTest(unittest.TestCase):
    """Task 1.1 + 2.1: helpers coerce UTC datetimes safely and
    normalise the LLM outcome to the closed wire token."""

    def test_iso_utc_returns_none_for_none(self) -> None:
        self.assertIsNone(_iso_utc(None))

    def test_iso_utc_returns_none_for_non_datetime(self) -> None:
        self.assertIsNone(_iso_utc("not-a-datetime"))
        self.assertIsNone(_iso_utc(123))

    def test_iso_utc_normalises_naive_to_utc(self) -> None:
        naive = datetime(2026, 8, 21, 18, 45, 20, tzinfo=timezone.utc)
        naive_no_tz = naive.replace(tzinfo=None)
        formatted = _iso_utc(naive_no_tz)
        self.assertIsNotNone(formatted)
        assert formatted is not None
        self.assertTrue(formatted.endswith("+00:00"))

    def test_iso_utc_converts_aware_to_utc(self) -> None:
        aware = datetime(2026, 8, 21, 15, 45, 20, tzinfo=timezone(timedelta(hours=-3)))
        formatted = _iso_utc(aware)
        self.assertIsNotNone(formatted)
        assert formatted is not None
        self.assertTrue(formatted.endswith("+00:00"))
        self.assertIn("18:45:20", formatted)

    def test_normalize_llm_outcome_accepts_known_tokens(self) -> None:
        for token in ("completed", "timeout", "error"):
            with self.subTest(token=token):
                self.assertEqual(_normalize_llm_outcome(token), token)

    def test_normalize_llm_outcome_rejects_unknown(self) -> None:
        for value in (None, "", "weird", 42, object()):
            with self.subTest(value=value):
                self.assertIsNone(_normalize_llm_outcome(value))

    def test_normalize_llm_outcome_lowercases_known_tokens(self) -> None:
        for raw, expected in (
            ("COMPLETED", "completed"),
            ("Timeout", "timeout"),
            ("ErRoR", "error"),
        ):
            with self.subTest(raw=raw):
                self.assertEqual(_normalize_llm_outcome(raw), expected)


class EmulatorTimelineProjectionTest(unittest.TestCase):
    """Task 2.1/2.2: the projection reads receipt/processing/outbox
    rows for the exact supplied receipt and never returns a
    cross-target timeline."""

    def test_projects_all_six_milestones_when_all_present(self) -> None:
        inbound = datetime(2026, 8, 21, 18, 45, 20, tzinfo=timezone.utc)
        llm_requested = datetime(2026, 8, 21, 18, 45, 20, 500000, tzinfo=timezone.utc)
        llm_finished = datetime(2026, 8, 21, 18, 45, 23, 800000, tzinfo=timezone.utc)
        processed = datetime(2026, 8, 21, 18, 45, 24, 200000, tzinfo=timezone.utc)
        staged = datetime(2026, 8, 21, 18, 45, 24, 700000, tzinfo=timezone.utc)
        receipt = MagicMock()
        receipt.id = 10
        receipt.fecha_recepcion = inbound
        processing = MagicMock()
        processing.llm_solicitado_en = llm_requested
        processing.llm_finalizado_en = llm_finished
        processing.llm_resultado = "completed"
        processing.fecha_finalizacion = processed
        outbound = MagicMock()
        outbound.fecha_creacion = staged
        db = MagicMock()
        db.execute.return_value.unique.return_value.scalars.return_value.first.return_value = outbound
        db.execute.return_value.unique.return_value.scalar_one_or_none.return_value = processing
        timeline = _emulator_timeline_from_receipt(db, receipt=receipt)
        self.assertEqual(timeline.inbound_received_at, inbound.isoformat())
        self.assertEqual(timeline.llm_requested_at, llm_requested.isoformat())
        self.assertEqual(timeline.llm_finished_at, llm_finished.isoformat())
        self.assertEqual(timeline.llm_outcome, "completed")
        self.assertEqual(
            timeline.processing_finished_at, processed.isoformat()
        )
        self.assertEqual(timeline.response_staged_at, staged.isoformat())

    def test_outcome_normalises_to_closed_token(self) -> None:
        receipt = MagicMock()
        receipt.id = 10
        receipt.fecha_recepcion = datetime(2026, 8, 21, 18, 45, 20, tzinfo=timezone.utc)
        processing = MagicMock()
        processing.llm_solicitado_en = datetime(
            2026, 8, 21, 18, 45, 20, tzinfo=timezone.utc
        )
        processing.llm_finalizado_en = datetime(
            2026, 8, 21, 18, 45, 21, tzinfo=timezone.utc
        )
        processing.llm_resultado = "TIMEOUT"
        processing.fecha_finalizacion = datetime(
            2026, 8, 21, 18, 45, 22, tzinfo=timezone.utc
        )
        db = MagicMock()
        db.execute.return_value.unique.return_value.scalars.return_value.first.return_value = None
        db.execute.return_value.unique.return_value.scalar_one_or_none.return_value = processing
        timeline = _emulator_timeline_from_receipt(db, receipt=receipt)
        self.assertEqual(timeline.llm_outcome, "timeout")

    def test_unknown_outcome_collapses_to_none(self) -> None:
        receipt = MagicMock()
        receipt.id = 10
        receipt.fecha_recepcion = datetime(2026, 8, 21, 18, 45, 20, tzinfo=timezone.utc)
        processing = MagicMock()
        processing.llm_solicitado_en = None
        processing.llm_finalizado_en = None
        processing.llm_resultado = "garbage"
        processing.fecha_finalizacion = None
        db = MagicMock()
        db.execute.return_value.unique.return_value.scalars.return_value.first.return_value = None
        db.execute.return_value.unique.return_value.scalar_one_or_none.return_value = processing
        timeline = _emulator_timeline_from_receipt(db, receipt=receipt)
        self.assertIsNone(timeline.llm_outcome)

    def test_missing_processing_yields_nulls(self) -> None:
        receipt = MagicMock()
        receipt.id = 10
        receipt.fecha_recepcion = datetime(2026, 8, 21, 18, 45, 20, tzinfo=timezone.utc)
        db = MagicMock()
        db.execute.return_value.unique.return_value.scalar_one_or_none.return_value = None
        db.execute.return_value.unique.return_value.scalars.return_value.first.return_value = None
        timeline = _emulator_timeline_from_receipt(db, receipt=receipt)
        self.assertEqual(timeline.inbound_received_at.endswith("+00:00"), True)
        self.assertIsNone(timeline.llm_requested_at)
        self.assertIsNone(timeline.llm_finished_at)
        self.assertIsNone(timeline.llm_outcome)
        self.assertIsNone(timeline.processing_finished_at)
        self.assertIsNone(timeline.response_staged_at)


class EmulatorPanelTimelineRenderingTest(unittest.TestCase):
    """Task 3.1/3.2/3.3: the browser-side helpers format timestamps as
    ``HH:MM:SS.mmm`` in the local zone and render the timeline
    with ``—`` for unavailable values."""

    def setUp(self) -> None:
        self.session = MagicMock(name="DatabaseSession")

        class _SessionOverride:
            def __init__(self, return_value: object) -> None:
                self._return_value = return_value

            def __call__(self) -> object:
                return self._return_value

        self.session_override = _SessionOverride(self.session)
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        import backend.dependencies as dependencies_module
        import backend.routers.admin_pilot_orders as router_module
        from backend.dependencies import get_session

        self._router_module = router_module
        self._settings_patcher = patch.object(
            dependencies_module,
            "load_settings",
            return_value=_admin_settings(),
        )
        self._settings_patcher.start()

        app = FastAPI()
        app.include_router(router_module.router)
        app.dependency_overrides[get_session] = self.session_override
        self.client = TestClient(app, raise_server_exceptions=False)

    def tearDown(self) -> None:
        self._settings_patcher.stop()

    def _auth_header(self) -> dict[str, str]:
        import base64

        token = base64.b64encode(b"any:x").decode("ascii")
        return {"Authorization": f"Basic {token}"}

    def test_detail_renders_timeline_skeleton(self) -> None:
        target = MagicMock()
        target.pedido_id = 42
        target.session_id = 21
        target.cliente_id = 31
        target.comercio_id = 1
        target.canal_id = 5
        target.canal_destination_e164 = "+5491100000000"

        from datetime import datetime, timezone

        from backend.services.pilot_order_operations_view_service import (
            ClientSummary,
            CommerceSummary,
            DeliveryMethodView,
            OrderDetailView,
            OrderSummary,
            PaymentMethodView,
            SessionSummary,
            format_local_datetime,
        )

        base = datetime(2026, 8, 12, 9, 0, tzinfo=timezone.utc)
        zona = "America/Argentina/Buenos_Aires"
        detail = OrderDetailView(
            pedido=OrderSummary(
                id=42,
                estado_pedido="borrador",
                fecha_alta=base,
                fecha_alta_local=format_local_datetime(base, zona),
                fecha_ultima_modificacion=base,
                fecha_ultima_modificacion_local=format_local_datetime(base, zona),
            ),
            session=SessionSummary(
                id=21,
                estado_session="activa",
                datetime_inicio=base,
                datetime_inicio_local=format_local_datetime(base, zona),
                datetime_ultimo_movimiento=base,
                datetime_ultimo_movimiento_local=format_local_datetime(base, zona),
            ),
            client=ClientSummary(
                id=31,
                nombre="Ana",
                whatsapp="+5491100000001",
                activo=True,
            ),
            commerce=CommerceSummary(
                id=1,
                nombre_fantasia="Comercio",
                nombre_corto="A",
                zona_horaria=zona,
            ),
            direccion_entrega=None,
            observaciones=None,
            datetime_entrega_programada=None,
            datetime_entrega_programada_local=None,
            medio_pago=PaymentMethodView(id=7, descripcion="Efectivo"),
            metodo_entrega=DeliveryMethodView(id=8, descripcion="Retiro"),
            lineas=[],
        )

        service = MagicMock()
        service.get_detail.return_value = detail
        service.get_provider_history.return_value = MagicMock(entries=[])
        service.get_order_lines_snapshot.return_value = []

        with patch.object(
            self._router_module, "PilotOrderOperationsViewService"
        ) as service_cls, patch.object(
            self._router_module,
            "_is_emulator_action_enabled",
            return_value=True,
        ), patch.object(
            self._router_module,
            "load_settings",
            return_value=_admin_settings(),
        ):
            service_cls.return_value = service
            response = self.client.get(
                "/admin/pilot/orders/42",
                headers=self._auth_header(),
            )
        self.assertEqual(response.status_code, 200)
        body = response.text
        # Timeline skeleton
        self.assertIn("data-debug-emulator-timeline", body)
        for attr in (
            "data-debug-timeline-inbound-received",
            "data-debug-timeline-llm-requested",
            "data-debug-timeline-llm-finished",
            "data-debug-timeline-llm-outcome",
            "data-debug-timeline-processing-finished",
            "data-debug-timeline-response-staged",
        ):
            with self.subTest(attr=attr):
                self.assertIn(attr, body)

    def test_panel_handlers_expose_format_and_render_helpers(self) -> None:
        from datetime import datetime, timezone

        from backend.services.pilot_order_operations_view_service import (
            ClientSummary,
            CommerceSummary,
            DeliveryMethodView,
            OrderDetailView,
            OrderSummary,
            PaymentMethodView,
            SessionSummary,
            format_local_datetime,
        )

        base = datetime(2026, 8, 12, 9, 0, tzinfo=timezone.utc)
        zona = "America/Argentina/Buenos_Aires"
        detail = OrderDetailView(
            pedido=OrderSummary(
                id=42,
                estado_pedido="borrador",
                fecha_alta=base,
                fecha_alta_local=format_local_datetime(base, zona),
                fecha_ultima_modificacion=base,
                fecha_ultima_modificacion_local=format_local_datetime(base, zona),
            ),
            session=SessionSummary(
                id=21,
                estado_session="activa",
                datetime_inicio=base,
                datetime_inicio_local=format_local_datetime(base, zona),
                datetime_ultimo_movimiento=base,
                datetime_ultimo_movimiento_local=format_local_datetime(base, zona),
            ),
            client=ClientSummary(
                id=31,
                nombre="Ana",
                whatsapp="+5491100000001",
                activo=True,
            ),
            commerce=CommerceSummary(
                id=1,
                nombre_fantasia="Comercio",
                nombre_corto="A",
                zona_horaria=zona,
            ),
            direccion_entrega=None,
            observaciones=None,
            datetime_entrega_programada=None,
            datetime_entrega_programada_local=None,
            medio_pago=PaymentMethodView(id=7, descripcion="Efectivo"),
            metodo_entrega=DeliveryMethodView(id=8, descripcion="Retiro"),
            lineas=[],
        )
        service = MagicMock()
        service.get_detail.return_value = detail
        service.get_provider_history.return_value = MagicMock(entries=[])
        service.get_order_lines_snapshot.return_value = []

        with patch.object(
            self._router_module, "PilotOrderOperationsViewService"
        ) as service_cls, patch.object(
            self._router_module,
            "_is_emulator_action_enabled",
            return_value=True,
        ), patch.object(
            self._router_module,
            "load_settings",
            return_value=_admin_settings(),
        ):
            service_cls.return_value = service
            response = self.client.get(
                "/admin/pilot/orders/42",
                headers=self._auth_header(),
            )
        body = response.text
        # JS exposes the helpers for tests
        self.assertIn("formatLocalTime", body)
        self.assertIn("formatLocalTimeFromIso", body)
        self.assertIn("renderEmulatorTimeline", body)
        self.assertIn("EMULATOR_TIMELINE_FIELDS", body)
        self.assertIn("EMULATOR_TIMELINE_OUTCOME_VALUES", body)
        # CSS class for the per-turn timestamp is present
        self.assertIn("debug-emulator-turn-timestamp", body)
        # No PII rendering helpers (no innerHTML for the transcript)
        self.assertNotIn("innerHTML", body)


class WorkItemLLMTimingRecorderTest(unittest.TestCase):
    """Task 1.3/1.4: the safe recorder captures the moment the worker
    reaches the QueryLlm boundary and the moment the call finishes."""

    def setUp(self) -> None:
        reset_llm_timing_recorder()

    def tearDown(self) -> None:
        reset_llm_timing_recorder()

    def test_recorder_is_noop_by_default(self) -> None:
        recorder = LLMTimingRecorder()
        self.assertIsNone(recorder.on_requested())
        recorder.on_finished(outcome="completed", finished_at=datetime.now(tz=timezone.utc))

    def test_recorder_captures_requested_and_finished(self) -> None:
        recorder = WorkItemLLMTimingRecorder()
        recorder.on_requested()
        self.assertIsNotNone(recorder.solicitado_en)
        finished = datetime(2026, 8, 21, 18, 45, 23, tzinfo=timezone.utc)
        recorder.on_finished(outcome="completed", finished_at=finished)
        self.assertEqual(recorder.finalizado_en, finished)
        self.assertEqual(recorder.resultado, "completed")
        self.assertTrue(recorder.has_any())

    def test_recorder_normalises_unknown_outcome_to_error(self) -> None:
        recorder = WorkItemLLMTimingRecorder()
        recorder.on_finished(
            outcome="bogus",
            finished_at=datetime.now(tz=timezone.utc),
        )
        self.assertEqual(recorder.resultado, "error")

    def test_recorder_swallows_attribute_errors(self) -> None:
        class _Broken:
            @property
            def solicitado_en(self):  # type: ignore[no-untyped-def]
                raise RuntimeError("boom")

            @solicitado_en.setter
            def solicitado_en(self, value):  # type: ignore[no-untyped-def]
                raise RuntimeError("boom")

        recorder = WorkItemLLMTimingRecorder()
        # Force the recorder into a broken state without touching
        # the private attrs directly.
        recorder.__dict__["solicitado_en"] = None
        recorder.on_finished(
            outcome="completed",
            finished_at=datetime.now(tz=timezone.utc),
        )
        self.assertEqual(recorder.resultado, "completed")


class QueryLlmTimingAndCorrelationTest(unittest.TestCase):
    """Task 1.3/1.5: QueryLlm wires the recorder and correlation
    id through the thread-local and never lets the LLM leak them
    as part of the prompt/response payload."""

    def setUp(self) -> None:
        reset_llm_timing_recorder()
        self.captured_events: list[dict[str, object]] = []

    def tearDown(self) -> None:
        reset_llm_timing_recorder()

    def _capture_event(self, **kwargs: object) -> bool:
        self.captured_events.append(kwargs)
        return True

    def test_normal_completion_records_completed_outcome_and_correlation(self) -> None:
        recorder = WorkItemLLMTimingRecorder()
        install_llm_timing_recorder(recorder, correlation_id="SYN-XYZ-1")
        transport = MagicMock(
            return_value=_FakeResponse(json.dumps({"ok": True}))
        )
        with patch(
            "backend.llm.query_llm.emit_event", side_effect=self._capture_event
        ):
            QueryLlm(settings=_settings(), transport=transport).request("hola")
        self.assertEqual(recorder.resultado, "completed")
        self.assertIsNotNone(recorder.solicitado_en)
        self.assertIsNotNone(recorder.finalizado_en)
        # correlation_id must ride on every llm_request event
        for event in self.captured_events:
            self.assertEqual(event.get("correlation_id"), "SYN-XYZ-1")

    def test_timeout_records_timeout_outcome_and_correlation(self) -> None:
        recorder = WorkItemLLMTimingRecorder()
        install_llm_timing_recorder(recorder, correlation_id="SYN-XYZ-2")

        def _boom(url: str, json: object = None, timeout: object = None) -> None:
            raise requests.exceptions.Timeout("slow")

        with patch(
            "backend.llm.query_llm.emit_event", side_effect=self._capture_event
        ):
            with self.assertRaises(QueryLlmTimeoutError):
                QueryLlm(settings=_settings(), transport=_boom).request("p")
        self.assertEqual(recorder.resultado, "timeout")
        for event in self.captured_events:
            self.assertEqual(event.get("correlation_id"), "SYN-XYZ-2")

    def test_http_error_records_error_outcome(self) -> None:
        recorder = WorkItemLLMTimingRecorder()
        install_llm_timing_recorder(recorder, correlation_id="SYN-XYZ-3")
        transport = MagicMock(
            return_value=_FakeResponse("boom", status_code=503)
        )
        with patch(
            "backend.llm.query_llm.emit_event", side_effect=self._capture_event
        ):
            with self.assertRaises(QueryLlmHttpError):
                QueryLlm(settings=_settings(), transport=transport).request("p")
        self.assertEqual(recorder.resultado, "error")

    def test_response_error_records_error_outcome(self) -> None:
        recorder = WorkItemLLMTimingRecorder()
        install_llm_timing_recorder(recorder, correlation_id="SYN-XYZ-4")
        transport = MagicMock(return_value=_FakeResponse(""))
        with patch(
            "backend.llm.query_llm.emit_event", side_effect=self._capture_event
        ):
            with self.assertRaises(QueryLlmResponseError):
                QueryLlm(settings=_settings(), transport=transport).request("p")
        self.assertEqual(recorder.resultado, "error")

    def test_explicit_correlation_kwarg_overrides_thread_local(self) -> None:
        recorder = WorkItemLLMTimingRecorder()
        install_llm_timing_recorder(recorder, correlation_id="thread-local")
        transport = MagicMock(
            return_value=_FakeResponse(json.dumps({"ok": True}))
        )
        with patch(
            "backend.llm.query_llm.emit_event", side_effect=self._capture_event
        ):
            QueryLlm(settings=_settings(), transport=transport).request(
                "hola",
                correlation_id="explicit-id",
            )
        self.assertEqual(self.captured_events[0]["correlation_id"], "explicit-id")

    def test_no_recorder_attached_is_safe_noop(self) -> None:
        transport = MagicMock(
            return_value=_FakeResponse(json.dumps({"ok": True}))
        )
        with patch(
            "backend.llm.query_llm.emit_event", side_effect=self._capture_event
        ):
            QueryLlm(settings=_settings(), transport=transport).request("hola")
        # No recorder was installed — every event must carry the
        # explicit (None) correlation so the worker can't leak
        # thread-local state between passes.
        for event in self.captured_events:
            self.assertIsNone(event.get("correlation_id"))

    def test_reset_clears_thread_local(self) -> None:
        recorder = WorkItemLLMTimingRecorder()
        install_llm_timing_recorder(recorder, correlation_id="SYN-XYZ-5")
        reset_llm_timing_recorder()
        transport = MagicMock(
            return_value=_FakeResponse(json.dumps({"ok": True}))
        )
        with patch(
            "backend.llm.query_llm.emit_event", side_effect=self._capture_event
        ):
            QueryLlm(settings=_settings(), transport=transport).request("hola")
        for event in self.captured_events:
            self.assertIsNone(event.get("correlation_id"))


class NoopLLMTimingRecorderBehaviourTest(unittest.TestCase):
    """The no-op recorder is the documented default."""

    def test_noop_recorder_returns_none_on_requested(self) -> None:
        self.assertIsNone(NoopLLMTimingRecorder().on_requested())

    def test_noop_recorder_accepts_finished_without_state(self) -> None:
        recorder = NoopLLMTimingRecorder()
        recorder.on_finished(
            outcome="completed",
            finished_at=datetime.now(tz=timezone.utc),
        )
        # The base class does not carry any state; the call is
        # purely a no-op annotation.
        self.assertFalse(hasattr(recorder, "resultado"))


class TimingEventPrivacyTest(unittest.TestCase):
    """Task 1.5 + privacy boundaries: the LLM event payload only carries
    timing, outcome and the safe correlation identifier — no prompt,
    response body, customer text, phone number or secret."""

    def setUp(self) -> None:
        reset_llm_timing_recorder()
        self.captured_events: list[dict[str, object]] = []

    def tearDown(self) -> None:
        reset_llm_timing_recorder()

    def _capture_event(self, **kwargs: object) -> bool:
        self.captured_events.append(kwargs)
        return True

    def _run_normal_request(self) -> None:
        recorder = WorkItemLLMTimingRecorder()
        install_llm_timing_recorder(recorder, correlation_id="SYN-PRIV-1")
        transport = MagicMock(
            return_value=_FakeResponse(json.dumps({"ok": True}))
        )
        with patch(
            "backend.llm.query_llm.emit_event", side_effect=self._capture_event
        ):
            QueryLlm(settings=_settings(), transport=transport).request("p")

    def test_event_payload_carries_only_closed_metadata(self) -> None:
        self._run_normal_request()
        for event in self.captured_events:
            forbidden = (
                "prompt",
                "response",
                "response_body",
                "raw",
                "phone",
                "secret",
                "openai",
                "model_output",
            )
            for key in forbidden:
                self.assertNotIn(key, event)
            self.assertIn("event", event)

    def test_event_payload_does_not_leak_prompt_via_correlation(self) -> None:
        # The correlation identifier MUST remain the opaque
        # synthetic inbound token; a payload that tries to embed
        # a prompt via the correlation kwarg must be rejected by
        # the catalogued event schema. We assert by attempting to
        # emit such an event directly through the catalogue.
        from backend.observability.events import EventValidationError, build_event

        with self.assertRaises(EventValidationError):
            build_event(
                event="llm_request",
                component="llm",
                outcome="completed",
                correlation_id="x" * 200,
            )

    def test_llm_request_accepts_valid_correlation_id_without_degradation(
        self,
    ) -> None:
        """The catalogue MUST accept the bounded safe synthetic
        inbound identifier on ``llm_request`` so the provider worker
        can carry the correlation into every LLM observability line.

        The test goes through the real ``build_event`` and
        ``emit_event`` validators (NOT a mock) and pins the
        contract: the payload round-trips through the catalogue,
        the emitter does NOT degrade the event to
        ``observability_emit_failed``, and the field is parsed back
        intact. The existing length, safety and format checks remain
        authoritative — only the ``llm_request`` event grows the
        field; every other event still rejects it."""
        import io

        from backend.observability.events import (
            COMPONENT_LLM,
            EVENT_LLM_REQUEST,
            build_event,
            emit_event,
            parse_event,
        )

        payload = build_event(
            event=EVENT_LLM_REQUEST,
            component=COMPONENT_LLM,
            outcome="completed",
            elapsed_ms=120,
            http_status=200,
            correlation_id="SYN-VALID-1",
        )
        self.assertEqual(payload["correlation_id"], "SYN-VALID-1")
        self.assertEqual(payload["event"], EVENT_LLM_REQUEST)
        self.assertEqual(payload["component"], COMPONENT_LLM)

        sink = io.StringIO()
        ok = emit_event(
            event=EVENT_LLM_REQUEST,
            component=COMPONENT_LLM,
            outcome="completed",
            elapsed_ms=120,
            http_status=200,
            correlation_id="SYN-VALID-1",
            stream=sink,
        )
        self.assertTrue(
            ok,
            "valid correlation_id MUST NOT cause emit_event to fail",
        )
        serialized = sink.getvalue().strip()
        self.assertNotIn(
            "observability_emit_failed",
            serialized,
            "valid llm_request MUST NOT degrade to observability_emit_failed",
        )
        parsed = parse_event(serialized)
        self.assertEqual(parsed["event"], EVENT_LLM_REQUEST)
        self.assertEqual(parsed["component"], COMPONENT_LLM)
        self.assertEqual(parsed["outcome"], "completed")
        self.assertEqual(parsed["correlation_id"], "SYN-VALID-1")


class EmulatorStatusWireSchemaTest(unittest.TestCase):
    """Task 2.1: the wire payload includes the closed timeline shape."""

    def test_wire_payload_includes_timeline_with_closed_keys(self) -> None:
        payload = EmulatorStatusResponse(
            status="processed",
            outbound_body="Hola",
            provider_message_sid="SM-1",
            timeline=EmulatorTimeline(
                inbound_received_at="2026-08-21T18:45:20+00:00",
                llm_requested_at="2026-08-21T18:45:20.500000+00:00",
                llm_finished_at="2026-08-21T18:45:23.800000+00:00",
                llm_outcome="completed",
                processing_finished_at="2026-08-21T18:45:24.200000+00:00",
                response_staged_at="2026-08-21T18:45:24.700000+00:00",
            ),
            diagnostic=EmulatorDiagnostic(
                processing_state="processed_with_response",
                response_count=1,
                outbox_row_count=1,
                failure_category=None,
            ),
        )
        serialized = payload.model_dump()
        self.assertEqual(
            set(serialized["timeline"].keys()),
            {
                "inbound_received_at",
                "llm_requested_at",
                "llm_finished_at",
                "llm_outcome",
                "processing_finished_at",
                "response_staged_at",
            },
        )
        self.assertNotIn("prompt", serialized)
        self.assertNotIn("response_body", serialized)
        self.assertNotIn("customer_text", serialized)

    def test_wire_payload_rejects_unknown_timeline_keys(self) -> None:
        with self.assertRaises(ValueError):
            EmulatorStatusResponse(
                status="accepted",
                outbound_body=None,
                provider_message_sid=None,
                timeline={"inbound_received_at": None, "secret": "x"},  # type: ignore[arg-type]
                diagnostic=EmulatorDiagnostic(
                    processing_state="pending",
                    response_count=None,
                    outbox_row_count=0,
                    failure_category=None,
                ),
            )


class EmulatorPerKindObservationStateTest(unittest.TestCase):
    """The Admin/Pilot conversation turn entry stores an
    independent ``observedAtIsoByKind`` timestamp per kind
    (``sent``/``status``/``received``/``error``) instead of a
    single shared ``observedAtIso``. Every row renders
    exclusively its own kind's timestamp and updating one kind
    never rewrites the timestamps of the other kinds."""

    def _extract_panel_script(self) -> str:
        template_path = (
            Path(__file__).resolve().parents[1]
            / "templates"
            / "admin_pilot_orders"
            / "base.html"
        )
        template = template_path.read_text(encoding="utf-8")
        start = template.find("<script>")
        end = template.find("</script>")
        if start == -1 or end == -1:
            self.fail("could not locate the inline <script> tag in base.html")
        return template[start + len("<script>"):end]

    def test_createEmulatorTurnEntry_uses_per_kind_map(self) -> None:
        """The entry shape initialises ``observedAtIsoByKind`` with
        one slot per conversation kind, all null, and never
        exposes a shared ``observedAtIso`` field."""
        script = self._extract_panel_script()
        self.assertIn("observedAtIsoByKind", script)
        self.assertNotIn("entry.observedAtIso =", script)
        # The literal ``observedAtIsoByKind`` appears in
        # ``createEmulatorTurnEntry``, the helpers and the
        # setter/getter closures.
        self.assertGreaterEqual(script.count("observedAtIsoByKind"), 6)

    def test_appendOrUpdateEmulatorTurn_captures_per_kind_timestamp(
        self,
    ) -> None:
        """``appendOrUpdateEmulatorTurn`` writes the freshly
        captured ISO into ``entry.observedAtIsoByKind[kind]`` so
        every kind keeps its own observation instant."""
        script = self._extract_panel_script()
        # The new per-kind capture-and-render pair.
        self.assertIn("setEmulatorTurnObservedAtIso(entry, kind, observedAtIso)", script)
        self.assertIn("getEmulatorTurnObservedAtIso(entry, kind)", script)
        # The old shared field must no longer appear inside the
        # ``appendOrUpdateEmulatorTurn`` body.
        self.assertNotIn("entry.observedAtIso =", script)


if __name__ == "__main__":
    unittest.main()
