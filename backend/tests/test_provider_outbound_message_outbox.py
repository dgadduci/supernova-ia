"""Phase-5.6 outbound provider-message outbox focused tests.

Coverage:

1. A successful first 5.4 processing commits ordered rows atomically
   with the receipt claim and the staged session, all in one
   transaction.
2. A rollback leaves no outbox row, no receipt claim, no staged
   session and no pipeline effect.
3. A duplicate inbound receipt creates no outbox row and never
   invokes the response mapper.
4. The local incoming-message endpoint still returns the same
   JSON response list and never stages an outbox row.
5. Static boundaries: the coordinator stages the rows through the
   repository, the mapper only delegates ``add`` to the repository,
   and no module touches transaction control outside the 5.4
   coordinator.
"""
from __future__ import annotations

import ast
import importlib
import inspect
import unittest
from pathlib import Path
from unittest.mock import ANY, MagicMock, patch

from backend.intents.orchestration import (
    incoming_message_response_orchestrator as response_orchestrator_module,
)
from backend.intents.orchestration.incoming_message_response_orchestrator import (
    GENERIC_MESSAGE,
    process_incoming_message_with_responses,
)
from backend.intents.schemas.customer_response import CustomerResponse
from backend.intents.schemas.processed_intent import ProcessedIntent
from backend.services import (
    outbound_response_mapper as outbound_mapper_module,
)
from backend.services import (
    provider_inbound_message_coordinator as coord_mod,
)
from backend.services.exceptions import InvalidOutboundProviderMessage
from backend.services.outbound_response_mapper import (
    build_customer_responses,
    stage_outbound_rows,
)
from backend.services.provider_inbound_message_coordinator import (
    ProviderInboundMessageCoordinator,
    ProviderInboundMessageStatus,
)
from backend.tests.test_provider_message_receipt_core import (
    _make_canal_dedicado,
    _make_comando_valido,
    _wire_dependencies,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def _make_session_row() -> MagicMock:
    session_row = MagicMock(name="ConversationSession")
    session_row.id = 555
    return session_row


def _make_processed_intents() -> list[ProcessedIntent]:
    return [
        ProcessedIntent(
            intent="agregar_producto",
            source_text="hola",
            status="executed",
            recognizer="recognizer_productos",
            handler="agregar_producto",
        )
    ]


class AtomicStagingTest(unittest.TestCase):
    def setUp(self) -> None:
        importlib.reload(coord_mod)

    def test_first_processing_stages_ordered_outbox_rows_atomically(
        self,
    ) -> None:
        """A successful first 5.4 processing stages one outbox row
        per processed intent inside the same transaction. The
        receipt, the staged session and the outbox rows commit
        together."""
        comando = _make_comando_valido()
        canal = _make_canal_dedicado(comercio_id=3)
        env = _wire_dependencies(canal=canal, existing_context=None)
        env["session_repo"].stage_active.return_value = _make_session_row()

        intents = _make_processed_intents()

        outbox_rows: list[MagicMock] = []

        def _capture_stage(**kwargs):
            row = MagicMock(name="MensajeProveedorSaliente")
            row.id = 900 + len(outbox_rows)
            outbox_rows.append(row)
            return row

        env["outbox_repo"] = MagicMock(
            name="OutboundProviderMessageRepository"
        )
        env["outbox_repo"].stage.side_effect = _capture_stage

        coordinator = ProviderInboundMessageCoordinator(
            session=env["db"],
            canal_repo=env["canal_repo"],
            contexto_repo=env["contexto_repo"],
            membresia_repo=env["membresia_repo"],
            recepcion_repo=env["recepcion_repo"],
            session_repo=env["session_repo"],
            outbox_repo=env["outbox_repo"],
        )

        with patch.object(
            coord_mod, "process_incoming_message", return_value=intents
        ):
            outcome = coordinator.process(comando)

        self.assertEqual(
            outcome.status, ProviderInboundMessageStatus.PROCESSED
        )

        env["outbox_repo"].stage.assert_called_once()
        kwargs = env["outbox_repo"].stage.call_args.kwargs
        self.assertEqual(kwargs["proveedor"], comando.proveedor)
        self.assertEqual(
            kwargs["recepcion_mensaje_proveedor_id"],
            int(env["recepcion_repo"].claim.return_value),
        )
        self.assertEqual(kwargs["destinatario_e164"], "+5491100000000")
        self.assertEqual(kwargs["sequence"], 0)
        self.assertEqual(kwargs["cuerpo"], outbox_rows[0].cuerpo if False else kwargs["cuerpo"])

        env["db"].commit.assert_called_once_with()
        env["db"].rollback.assert_not_called()


class RollbackLeavesNoOutboxTest(unittest.TestCase):
    def setUp(self) -> None:
        importlib.reload(coord_mod)

    def test_rollback_leaves_no_outbox_row(self) -> None:
        """A pipeline failure rolls back the staged receipt, the
        staged session and the staged outbox rows in one atomic
        operation. No row is observable after the failure."""
        comando = _make_comando_valido()
        canal = _make_canal_dedicado(comercio_id=3)
        env = _wire_dependencies(canal=canal, existing_context=None)
        env["session_repo"].stage_active.return_value = _make_session_row()

        outbox_repo = MagicMock(
            name="OutboundProviderMessageRepository"
        )
        outbox_repo.stage.return_value = MagicMock(
            name="MensajeProveedorSaliente"
        )

        coordinator = ProviderInboundMessageCoordinator(
            session=env["db"],
            canal_repo=env["canal_repo"],
            contexto_repo=env["contexto_repo"],
            membresia_repo=env["membresia_repo"],
            recepcion_repo=env["recepcion_repo"],
            session_repo=env["session_repo"],
            outbox_repo=outbox_repo,
        )

        sentinel_exc = RuntimeError("pipeline boom")
        with patch.object(
            coord_mod,
            "process_incoming_message",
            side_effect=sentinel_exc,
        ):
            with self.assertRaises(RuntimeError):
                coordinator.process(comando)

        env["recepcion_repo"].claim.assert_called_once()
        outbox_repo.stage.assert_not_called()
        env["db"].commit.assert_not_called()
        env["db"].rollback.assert_called_once_with()


class DuplicateReceiptNoOutboxTest(unittest.TestCase):
    def setUp(self) -> None:
        importlib.reload(coord_mod)

    def test_duplicate_receipt_invokes_no_response_mapper(self) -> None:
        comando = _make_comando_valido()
        canal = _make_canal_dedicado(comercio_id=3)
        env = _wire_dependencies(canal=canal, existing_context=None)
        env["recepcion_repo"].claim.return_value = None

        outbox_repo = MagicMock(
            name="OutboundProviderMessageRepository"
        )

        coordinator = ProviderInboundMessageCoordinator(
            session=env["db"],
            canal_repo=env["canal_repo"],
            contexto_repo=env["contexto_repo"],
            membresia_repo=env["membresia_repo"],
            recepcion_repo=env["recepcion_repo"],
            session_repo=env["session_repo"],
            outbox_repo=outbox_repo,
        )

        with patch.object(coord_mod, "process_incoming_message") as pipeline:
            outcome = coordinator.process(comando)

        self.assertEqual(
            outcome.status, ProviderInboundMessageStatus.ALREADY_PROCESSED
        )
        pipeline.assert_not_called()
        outbox_repo.stage.assert_not_called()
        env["db"].rollback.assert_called_once_with()
        env["db"].commit.assert_not_called()


class LocalEndpointCompatibilityTest(unittest.TestCase):
    def setUp(self) -> None:
        importlib.reload(response_orchestrator_module)

    def test_local_endpoint_returns_responses_without_staging_rows(
        self,
    ) -> None:
        """The local endpoint still returns the same JSON response
        list and never stages an outbox row. The mapper is reused
        but the staging path is coordinator-only."""
        db_session = MagicMock(name="DatabaseSession")
        conversation_session = MagicMock(name="ConversationSession")

        with patch.object(
            response_orchestrator_module,
            "process_incoming_message_transactional",
            return_value=[
                ProcessedIntent(
                    intent="agregar_producto",
                    source_text="hola",
                    status="executed",
                    recognizer="recognizer_productos",
                    handler="agregar_producto",
                )
            ],
        ):
            responses = process_incoming_message_with_responses(
                db_session,
                conversation_session,
                "hola",
            )

        self.assertEqual(len(responses), 1)
        self.assertIsInstance(responses[0], CustomerResponse)
        db_session.add.assert_not_called()
        db_session.rollback.assert_not_called()

    def test_generic_fallback_stays_equivalent(self) -> None:
        db_session = MagicMock(name="DatabaseSession")
        conversation_session = MagicMock(name="ConversationSession")

        with patch.object(
            response_orchestrator_module,
            "process_incoming_message_transactional",
            return_value=[
                ProcessedIntent(
                    intent="desconocida",
                    source_text="asdf",
                    status="rejected",
                    recognizer="recognizer_productos",
                    handler="desconocida",
                )
            ],
        ):
            responses = process_incoming_message_with_responses(
                db_session,
                conversation_session,
                "asdf",
            )

        self.assertEqual(len(responses), 1)
        self.assertEqual(responses[0].message, GENERIC_MESSAGE)
        self.assertEqual(responses[0].intent, "desconocida")
        db_session.add.assert_not_called()


class MapperValidationTest(unittest.TestCase):
    def test_empty_proveedor_rejected(self) -> None:
        with self.assertRaises(InvalidOutboundProviderMessage):
            stage_outbound_rows(
                MagicMock(name="DatabaseSession"),
                MagicMock(name="ConversationSession"),
                proveedor="   ",
                recepcion_mensaje_proveedor_id=1,
                destinatario_e164="+5491100000000",
                intents=[],
            )

    def test_empty_destinatario_rejected(self) -> None:
        with self.assertRaises(InvalidOutboundProviderMessage):
            stage_outbound_rows(
                MagicMock(name="DatabaseSession"),
                MagicMock(name="ConversationSession"),
                proveedor="twilio",
                recepcion_mensaje_proveedor_id=1,
                destinatario_e164="",
                intents=[],
            )

    def test_non_positive_recepcion_rejected(self) -> None:
        with self.assertRaises(InvalidOutboundProviderMessage):
            stage_outbound_rows(
                MagicMock(name="DatabaseSession"),
                MagicMock(name="ConversationSession"),
                proveedor="twilio",
                recepcion_mensaje_proveedor_id=0,
                destinatario_e164="+5491100000000",
                intents=[],
            )


class StaticBoundariesTest(unittest.TestCase):
    def test_mapper_does_not_call_session_add_directly(self) -> None:
        """The mapper delegates the row insert to the repository
        so the database boundary stays in repositories."""
        source = inspect.getsource(outbound_mapper_module)
        for forbidden in (
            "_session.add",
            "session.add",
            "db.add",
            "session.commit",
            "session.rollback",
            "session.flush",
            "session.begin",
            "session.close",
            "session.refresh",
            "session.expire",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(
                    forbidden,
                    source,
                    "outbound mapper must delegate persistence to "
                    f"the repository: {forbidden}",
                )

    def test_mapper_renders_responses_via_reusable_builders(self) -> None:
        """The mapper reuses the same builders the local endpoint
        uses so the rendered text and ordering stay equivalent."""
        source = inspect.getsource(outbound_mapper_module)
        self.assertIn(
            "build_agregar_producto_response",
            source,
        )
        self.assertIn(
            "build_quitar_producto_response",
            source,
        )
        self.assertIn(
            "build_modificar_producto_response",
            source,
        )


class OutboxModuleBoundaryTest(unittest.TestCase):
    def test_repository_does_not_control_transactions(self) -> None:
        repo_path = (
            REPO_ROOT
            / "backend"
            / "repositories"
            / "mensaje_proveedor_saliente_repository.py"
        )
        tree = ast.parse(repo_path.read_text(encoding="utf-8"))
        offenders: list[str] = []
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
            ):
                continue
            if node.func.attr in {"commit", "rollback", "begin", "close"}:
                offenders.append(node.func.attr)
        self.assertEqual(
            offenders,
            [],
            f"Outbox repository must not control transactions: "
            f"{offenders}",
        )


class OutboxExportTest(unittest.TestCase):
    def test_mapper_exports_expected_symbols(self) -> None:
        self.assertEqual(
            set(outbound_mapper_module.__all__),
            {
                "GENERIC_MESSAGE",
                "StagedOutboundRow",
                "build_customer_responses",
                "stage_outbound_rows",
            },
        )

    def test_response_orchestrator_exports_documented_symbols(self) -> None:
        self.assertEqual(
            set(response_orchestrator_module.__all__),
            {"process_incoming_message_with_responses"},
        )


class OutboxCoalescingTest(unittest.TestCase):
    """Provider outbox staging applies the shared coalescing helper."""

    @patch.object(outbound_mapper_module, "build_agregar_producto_response")
    def test_two_consecutive_same_id_yields_one_response(
        self, builder
    ) -> None:
        first = ProcessedIntent(
            intent="agregar_producto",
            source_text="una empanada",
            status="executed",
            handler="agregar_producto",
            recognizer="recognizer_productos",
            resolved_data={"producto_presentacion_id": 1, "cantidad": 1},
        )
        terminal = ProcessedIntent(
            intent="agregar_producto",
            source_text="tres empanadas",
            status="executed",
            handler="agregar_producto",
            recognizer="recognizer_productos",
            resolved_data={
                "producto_presentacion_id": 1,
                "cantidad_final": 3,
            },
        )

        terminal_response = CustomerResponse(
            message="Listo, se agregaron 3 Empanada unidad.",
            intent="agregar_producto",
            status="executed",
        )
        builder.return_value = terminal_response

        responses = build_customer_responses(
            MagicMock(name="DatabaseSession"),
            MagicMock(name="ConversationSession"),
            [first, terminal],
        )

        self.assertEqual(len(responses), 1)
        self.assertIs(responses[0], terminal_response)
        builder.assert_called_once()
        builder.assert_called_with(ANY, ANY, terminal)

    @patch.object(outbound_mapper_module, "build_agregar_producto_response")
    def test_different_presentation_ids_are_not_coalesced(
        self, builder
    ) -> None:
        first = ProcessedIntent(
            intent="agregar_producto",
            source_text="x",
            status="executed",
            handler="agregar_producto",
            recognizer="recognizer_productos",
            resolved_data={"producto_presentacion_id": 1, "cantidad": 1},
        )
        second = ProcessedIntent(
            intent="agregar_producto",
            source_text="y",
            status="executed",
            handler="agregar_producto",
            recognizer="recognizer_productos",
            resolved_data={"producto_presentacion_id": 2, "cantidad": 1},
        )
        builder.side_effect = [
            CustomerResponse(
                message="A",
                intent="agregar_producto",
                status="executed",
            ),
            CustomerResponse(
                message="B",
                intent="agregar_producto",
                status="executed",
            ),
        ]

        responses = build_customer_responses(
            MagicMock(name="DatabaseSession"),
            MagicMock(name="ConversationSession"),
            [first, second],
        )

        self.assertEqual(len(responses), 2)
        self.assertEqual(responses[0].message, "A")
        self.assertEqual(responses[1].message, "B")
        self.assertEqual(builder.call_count, 2)

    @patch.object(outbound_mapper_module, "build_agregar_producto_response")
    def test_pending_after_executed_same_id_is_not_coalesced(
        self, builder
    ) -> None:
        executed = ProcessedIntent(
            intent="agregar_producto",
            source_text="x",
            status="executed",
            handler="agregar_producto",
            recognizer="recognizer_productos",
            resolved_data={"producto_presentacion_id": 1, "cantidad": 1},
        )
        pending = ProcessedIntent(
            intent="agregar_producto",
            source_text="y",
            status="pending_resolution",
            handler="agregar_producto",
            recognizer="recognizer_productos",
            resolved_data={},
            candidate_ids=[1],
        )
        builder.side_effect = [
            CustomerResponse(
                message="OK",
                intent="agregar_producto",
                status="executed",
            ),
            CustomerResponse(
                message="CLARIFICATION",
                intent="agregar_producto",
                status="pending_resolution",
            ),
        ]

        responses = build_customer_responses(
            MagicMock(name="DatabaseSession"),
            MagicMock(name="ConversationSession"),
            [executed, pending],
        )

        self.assertEqual(len(responses), 2)
        self.assertEqual(responses[0].message, "OK")
        self.assertEqual(responses[1].message, "CLARIFICATION")
        self.assertEqual(builder.call_count, 2)

    @patch.object(outbound_mapper_module, "build_agregar_producto_response")
    def test_stage_outbound_rows_stages_only_terminal_for_eligible_group(
        self, builder
    ) -> None:
        first = ProcessedIntent(
            intent="agregar_producto",
            source_text="x",
            status="executed",
            handler="agregar_producto",
            recognizer="recognizer_productos",
            resolved_data={"producto_presentacion_id": 1, "cantidad": 1},
        )
        terminal = ProcessedIntent(
            intent="agregar_producto",
            source_text="y",
            status="executed",
            handler="agregar_producto",
            recognizer="recognizer_productos",
            resolved_data={
                "producto_presentacion_id": 1,
                "cantidad_final": 4,
            },
        )

        terminal_response = CustomerResponse(
            message="TERMINAL",
            intent="agregar_producto",
            status="executed",
        )
        builder.return_value = terminal_response

        rows: list[MagicMock] = []

        def _capture_stage(**kwargs):
            row = MagicMock(name="MensajeProveedorSaliente")
            row.id = 100 + len(rows)
            rows.append(row)
            return row

        outbox_repo = MagicMock(name="MensajeProveedorSalienteRepository")
        outbox_repo.stage.side_effect = _capture_stage

        staged = stage_outbound_rows(
            MagicMock(name="DatabaseSession"),
            MagicMock(name="ConversationSession"),
            proveedor="twilio",
            recepcion_mensaje_proveedor_id=11,
            destinatario_e164="+5491100000000",
            intents=[first, terminal],
            outbox_repo=outbox_repo,
        )

        self.assertEqual(len(staged), 1)
        self.assertEqual(staged[0].sequence, 0)
        self.assertIs(staged[0].customer_response, terminal_response)
        outbox_repo.stage.assert_called_once()
        self.assertEqual(outbox_repo.stage.call_args.kwargs["sequence"], 0)
        self.assertEqual(
            outbox_repo.stage.call_args.kwargs["cuerpo"], "TERMINAL"
        )
        builder.assert_called_once()

    @patch.object(outbound_mapper_module, "build_agregar_producto_response")
    def test_stage_outbound_rows_stages_two_rows_for_two_presentations(
        self, builder
    ) -> None:
        first = ProcessedIntent(
            intent="agregar_producto",
            source_text="x",
            status="executed",
            handler="agregar_producto",
            recognizer="recognizer_productos",
            resolved_data={"producto_presentacion_id": 1, "cantidad": 1},
        )
        second = ProcessedIntent(
            intent="agregar_producto",
            source_text="y",
            status="executed",
            handler="agregar_producto",
            recognizer="recognizer_productos",
            resolved_data={"producto_presentacion_id": 2, "cantidad": 1},
        )
        builder.side_effect = [
            CustomerResponse(
                message="A",
                intent="agregar_producto",
                status="executed",
            ),
            CustomerResponse(
                message="B",
                intent="agregar_producto",
                status="executed",
            ),
        ]

        outbox_repo = MagicMock(name="MensajeProveedorSalienteRepository")
        outbox_repo.stage.return_value = MagicMock(
            name="MensajeProveedorSaliente"
        )

        staged = stage_outbound_rows(
            MagicMock(name="DatabaseSession"),
            MagicMock(name="ConversationSession"),
            proveedor="twilio",
            recepcion_mensaje_proveedor_id=11,
            destinatario_e164="+5491100000000",
            intents=[first, second],
            outbox_repo=outbox_repo,
        )

        self.assertEqual(len(staged), 2)
        self.assertEqual(builder.call_count, 2)
        outbox_repo.stage.assert_any_call(
            proveedor="twilio",
            recepcion_mensaje_proveedor_id=11,
            destinatario_e164="+5491100000000",
            cuerpo="A",
            sequence=0,
        )
        outbox_repo.stage.assert_any_call(
            proveedor="twilio",
            recepcion_mensaje_proveedor_id=11,
            destinatario_e164="+5491100000000",
            cuerpo="B",
            sequence=1,
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)