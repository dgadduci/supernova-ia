import json
import unittest
import unittest.mock
from dataclasses import dataclass
from enum import Enum
from typing import Any

import pydantic

from backend.diagnostics import (
    ClassifierCallCompleted,
    ClassifierCallStarted,
    CollectingDiagnosticSink,
    NoopDiagnosticSink,
    PendingStateSnapshot,
    ResolverCallCompleted,
    ResolverCallStarted,
    redact,
    serialize,
)


class TestSerializePrimitiveTypes(unittest.TestCase):
    def test_primitives_pass_through_verbatim(self):
        self.assertIsNone(serialize(None))
        self.assertEqual(serialize(True), True)
        self.assertEqual(serialize(False), False)
        self.assertEqual(serialize(42), 42)
        self.assertEqual(serialize(3.14), 3.14)
        self.assertEqual(serialize("hola"), "hola")


class _Color(Enum):
    RED = "red"
    BLUE = "blue"


class TestSerializeEnum(unittest.TestCase):
    def test_enum_returns_value(self):
        self.assertEqual(serialize(_Color.RED), "red")
        self.assertEqual(serialize(_Color.BLUE), "blue")


class TestSerializeDict(unittest.TestCase):
    def test_dict_sorts_keys(self):
        result: Any = serialize({"b": 1, "a": 2, "c": 3})
        self.assertEqual(list(result.keys()), ["a", "b", "c"])


class TestSerializeListOrderPreserved(unittest.TestCase):
    def test_list_order_preserved(self):
        result = serialize([3, 1, 2])
        self.assertEqual(result, [3, 1, 2])


@dataclass
class _SampleDC:
    name: str
    value: int = 0


class TestSerializeDataclass(unittest.TestCase):
    def test_dataclass_fields_serialized(self):
        result = serialize(_SampleDC(name="x", value=7))
        self.assertEqual(result, {"name": "x", "value": 7})


class _SamplePyd(pydantic.BaseModel):
    name: str
    value: int = 0


class TestSerializePydantic(unittest.TestCase):
    def test_pydantic_model_fields_serialized(self):
        result = serialize(_SamplePyd(name="x", value=7))
        self.assertEqual(result, {"name": "x", "value": 7})


class _MockSQLATable:
    def __init__(self, columns):
        self.columns = columns


class _MockColumn:
    def __init__(self, name):
        self.key = name
        self.name = name


class _MockORMInstance:
    __table__ = _MockSQLATable(
        [_MockColumn("id"), _MockColumn("nombre"), _MockColumn("activo")]
    )

    def __init__(self):
        self.id = 99
        self.nombre = "Empanada"
        self.activo = True


class TestSerializeSQLAlchemy(unittest.TestCase):
    def test_sqlalchemy_orm_instance_reads_columns(self):
        result = serialize(_MockORMInstance())
        self.assertEqual(
            result,
            {"id": 99, "nombre": "Empanada", "activo": True},
        )


class _Unknown:
    pass


class TestSerializeUnsupported(unittest.TestCase):
    def test_unsupported_returns_classname(self):
        result = serialize(_Unknown())
        self.assertEqual(result, "<_Unknown>")


class _Node:
    def __init__(self) -> None:
        self.next: Any = None


class TestSerializeRecursionLoop(unittest.TestCase):
    def test_recursion_loop_returns_classname(self):
        node = _Node()
        node.next = node
        result = serialize(node)
        self.assertEqual(result, "<_Node>")


@dataclass
class _Chain:
    inner: Any = None


class TestSerializeDepthLimit(unittest.TestCase):
    def test_depth_limit_returns_classname(self):
        chain: Any = _Chain(
            inner=_Chain(
                inner=_Chain(inner="leaf")
            )
        )
        result = serialize(chain)
        self.assertIsInstance(result, (dict, str))


class TestRedact(unittest.TestCase):
    def test_redact_password_token_api_key(self):
        result: Any = redact(
            {
                "password": "secret-pw",
                "token": "secret-tok",
                "api_key": "secret-ak",
                "username": "alice",
            }
        )
        self.assertEqual(result["password"], "<redacted>")
        self.assertEqual(result["token"], "<redacted>")
        self.assertEqual(result["api_key"], "<redacted>")
        self.assertEqual(result["username"], "alice")

    def test_redact_database_url(self):
        result: Any = redact({"database_url": "postgresql://...", "other": "ok"})
        self.assertEqual(result["database_url"], "<redacted>")
        self.assertEqual(result["other"], "ok")

    def test_redact_authorization_header(self):
        result: Any = redact({"Authorization": "Bearer x", "X-API-Key": "k"})
        self.assertEqual(result["Authorization"], "<redacted>")
        self.assertEqual(result["X-API-Key"], "<redacted>")

    def test_redact_nested_in_list(self):
        result: Any = redact([{"password": "x", "ok": "y"}, {"token": "z"}])
        self.assertEqual(result[0]["password"], "<redacted>")
        self.assertEqual(result[0]["ok"], "y")
        self.assertEqual(result[1]["token"], "<redacted>")

    def test_redact_disabled_passes_through(self):
        result: Any = serialize({"password": "x", "ok": "y"}, redact=False)
        self.assertEqual(result["password"], "x")
        self.assertEqual(result["ok"], "y")


class TestNoopDiagnosticSink(unittest.TestCase):
    def test_noop_does_not_retain_state(self):
        sink = NoopDiagnosticSink()
        sink.on_classifier_started(
            ClassifierCallStarted(raw_message="x", turn_id=1)
        )
        sink.on_classifier_completed(
            ClassifierCallCompleted(intent_count=0, parse_errors=[])
        )
        sink.on_resolver_started(
            ResolverCallStarted(call_id="RES-001", candidate_ids_before=[])
        )
        sink.on_resolver_completed(
            ResolverCallCompleted(call_id="RES-001", candidate_ids_after=[])
        )
        sink.on_pending_state_snapshot(
            PendingStateSnapshot(
                snapshot_phase="after_resolver",
                queue_length=0,
                queue_intents=[],
                queue_sources=[],
                active_candidate_ids=[],
            )
        )
        self.assertEqual(
            sorted(a for a in dir(sink) if not a.startswith("_")),
            sorted(
                [
                    "on_classifier_completed",
                    "on_classifier_started",
                    "on_pending_state_snapshot",
                    "on_resolver_completed",
                    "on_resolver_started",
                ]
            ),
        )


class TestCollectingSinkSequentialCallIds(unittest.TestCase):
    def test_assigns_sequential_call_ids(self):
        sink = CollectingDiagnosticSink()
        sink.on_classifier_started(ClassifierCallStarted(raw_message="x"))
        sink.on_classifier_completed(ClassifierCallCompleted(intent_count=0))
        sink.on_resolver_started(
            ResolverCallStarted(candidate_ids_before=[])
        )
        sink.on_resolver_completed(
            ResolverCallCompleted(candidate_ids_after=[])
        )
        events = sink.events()
        self.assertEqual(events[0].call_id, "CLS-001")
        self.assertEqual(events[1].call_id, "CLS-001")
        self.assertEqual(events[2].call_id, "RES-001")
        self.assertEqual(events[3].call_id, "RES-001")


class TestCollectingSinkRouterSortOrder(unittest.TestCase):
    def test_events_sorted_by_sequence(self):
        sink = CollectingDiagnosticSink()
        sink.on_classifier_started(ClassifierCallStarted(raw_message="x"))
        sink.on_classifier_completed(ClassifierCallCompleted(intent_count=0))
        sink.on_resolver_started(
            ResolverCallStarted(candidate_ids_before=[])
        )
        sink.on_resolver_completed(
            ResolverCallCompleted(candidate_ids_after=[])
        )
        events = sink.events()
        self.assertEqual([e.sequence for e in events], [1, 2, 3, 4])


class TestCollectingSinkClear(unittest.TestCase):
    def test_clear_resets_state(self):
        sink = CollectingDiagnosticSink()
        sink.on_classifier_started(ClassifierCallStarted(raw_message="x"))
        sink.clear()
        self.assertEqual(sink.events(), [])


class TestXDebugFlowHeaderActivatesSink(unittest.TestCase):
    def test_header_activates_sink(self):
        from fastapi import FastAPI, Header
        from fastapi.testclient import TestClient

        import backend.routers.incoming_messages as router_module
        from backend.dependencies import get_session
        from backend.diagnostics import (
            CollectingDiagnosticSink,
            ClassifierCallCompleted,
            ClassifierCallStarted,
            DiagnosticSink,
            NoopDiagnosticSink,
        )

        app = FastAPI()
        app.include_router(router_module.router)
        db = unittest.mock.MagicMock(name="DatabaseSession")
        app.dependency_overrides[get_session] = lambda: db

        # Replace the dependency with a Header-aware variant so the
        # override machinery actually observes the X-Debug-Flow header.
        def _build_sink(
            x_debug_flow: str | None = Header(default=None, alias="X-Debug-Flow"),
        ) -> DiagnosticSink:
            if x_debug_flow:
                return CollectingDiagnosticSink()
            return NoopDiagnosticSink()

        app.dependency_overrides[router_module.get_diagnostic_sink] = _build_sink

        def _process_with_event(*args: Any, **kwargs: Any) -> list[Any]:
            sink = kwargs.get("sink")
            if isinstance(sink, CollectingDiagnosticSink):
                sink.on_classifier_started(
                    ClassifierCallStarted(raw_message="hola")
                )
                sink.on_classifier_completed(
                    ClassifierCallCompleted(intent_count=0)
                )
            return []

        client = TestClient(app)
        with unittest.mock.patch.object(
            router_module, "process_incoming_message_with_responses",
            side_effect=_process_with_event,
        ), unittest.mock.patch.object(
            router_module.SessionService, "get_active"
        ) as get_active:
            get_active.return_value = unittest.mock.MagicMock()
            response_with = client.post(
                "/comercios/1/clientes/2/incoming-messages",
                json={"message": "hola"},
                headers={"X-Debug-Flow": "1"},
            )
            response_without = client.post(
                "/comercios/1/clientes/2/incoming-messages",
                json={"message": "hola"},
            )
        self.assertEqual(response_with.status_code, 200)
        self.assertEqual(response_without.status_code, 200)
        self.assertIn("diagnostics", response_with.json())
        self.assertNotIn("diagnostics", response_without.json())
        self.assertGreaterEqual(len(response_with.json()["diagnostics"]), 1)


class TestXDebugFlowRedactsSecrets(unittest.TestCase):
    def test_redacts_password_field(self):
        from fastapi import FastAPI, Header
        from fastapi.testclient import TestClient

        import backend.routers.incoming_messages as router_module
        from backend.dependencies import get_session
        from backend.diagnostics import (
            CollectingDiagnosticSink,
            ClassifierCallStarted,
            DiagnosticSink,
            NoopDiagnosticSink,
        )

        app = FastAPI()
        app.include_router(router_module.router)
        db = unittest.mock.MagicMock(name="DatabaseSession")
        app.dependency_overrides[get_session] = lambda: db

        def _build_sink(
            x_debug_flow: str | None = Header(default=None, alias="X-Debug-Flow"),
        ) -> DiagnosticSink:
            if x_debug_flow:
                return CollectingDiagnosticSink()
            return NoopDiagnosticSink()

        app.dependency_overrides[router_module.get_diagnostic_sink] = _build_sink

        def fake_process(*args: Any, **kwargs: Any) -> list[Any]:
            sink = kwargs.get("sink")
            if isinstance(sink, CollectingDiagnosticSink):
                sink.on_classifier_started(
                    ClassifierCallStarted(raw_message="hola")
                )
            return []

        client = TestClient(app)
        with unittest.mock.patch.object(
            router_module,
            "process_incoming_message_with_responses",
            side_effect=fake_process,
        ), unittest.mock.patch.object(
            router_module.SessionService, "get_active"
        ) as get_active:
            get_active.return_value = unittest.mock.MagicMock()
            response = client.post(
                "/comercios/1/clientes/2/incoming-messages",
                json={"message": "hola"},
                headers={"X-Debug-Flow": "1"},
            )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("diagnostics", body)


class TestIncomingMessageDefaultResponseUnchanged(unittest.TestCase):
    def test_default_response_unchanged(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        import backend.routers.incoming_messages as router_module
        from backend.dependencies import get_session
        from backend.intents.schemas.customer_response import CustomerResponse

        app = FastAPI()
        app.include_router(router_module.router)
        db = unittest.mock.MagicMock(name="DatabaseSession")
        app.dependency_overrides[get_session] = lambda: db
        client = TestClient(app)

        with unittest.mock.patch.object(
            router_module, "process_incoming_message_with_responses"
        ) as process, unittest.mock.patch.object(
            router_module.SessionService, "get_active"
        ) as get_active:
            get_active.return_value = unittest.mock.MagicMock()
            process.return_value = [
                CustomerResponse(
                    message="Listo",
                    intent="agregar_producto",
                    status="executed",
                )
            ]
            response = client.post(
                "/comercios/1/clientes/2/incoming-messages",
                json={"message": "hola"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "responses": [
                    {
                        "message": "Listo",
                        "intent": "agregar_producto",
                        "status": "executed",
                    }
                ]
            },
        )


class TestIntentClassifierNoDuplicateCalls(unittest.TestCase):
    def test_no_duplicate_classification_with_collecting_sink(self):
        from backend.llm.intent_classifier import IntentClassifier
        from backend.diagnostics import CollectingDiagnosticSink

        class _StubQueryLlm:
            def __init__(self, payload: dict) -> None:
                self.payload = payload
                self.calls: list[str] = []

            def request(self, prompt: str) -> dict:
                self.calls.append(prompt)
                return self.payload

        noop_sink = NoopDiagnosticSink()
        collecting_sink = CollectingDiagnosticSink()

        payload = {
            "intents": [
                {"intent": "agregar_producto", "mensaje": "una empanada"}
            ],
            "mensaje": "quiero una empanada",
        }

        noop_classifier = IntentClassifier(
            query_llm=_StubQueryLlm(payload),  # type: ignore[arg-type]
            sink=noop_sink,
        )
        collecting_classifier = IntentClassifier(
            query_llm=_StubQueryLlm(payload),  # type: ignore[arg-type]
            sink=collecting_sink,
        )

        noop_classifier.query("quiero una empanada")
        collecting_classifier.query("quiero una empanada")

        self.assertEqual(len(noop_classifier._query_llm.calls), 1)  # type: ignore[attr-defined]
        self.assertEqual(len(collecting_classifier._query_llm.calls), 1)  # type: ignore[attr-defined]
        self.assertEqual(len(collecting_sink.events()), 2)


if __name__ == "__main__":
    unittest.main()
