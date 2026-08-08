"""Phase-7.4 provider-message acceptance core tests.

Focused coverage for the acceptance boundary only:

* first acceptance (commits receipt + one pending work item);
* duplicate idempotency (second delivery returns
  ``already_processed`` and never stages a second work item);
* concurrent claim semantics (the ``ON CONFLICT DO NOTHING
  RETURNING`` empty-result is treated as ``already_processed`` and
  never as a second acceptance);
* dedicated and selected-shared authority, including the
  ``comercio_id_cambio_pendiente`` pending-only invariant;
* rollback atomicity (technical failure rolls back receipt and
  staged work item without leaking half-committed state);
* static boundaries (only the coordinator owns ``commit`` /
  ``rollback``; the coordinator never invokes the pipeline,
  classifier or recognizer during acceptance).

The acceptance boundary MUST NOT invoke the classifier, recognizer,
session/pedido staging, message pipeline, response mapping or
outbound mapper. Deferred processing is exercised in
``test_run_inbound_processing_cli.py`` and the integration tests.
"""
from __future__ import annotations

import ast
import importlib
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from backend.models.canal_whatsapp import CanalWhatsappMode
from backend.repositories.session_repository import SessionRepository
from backend.services import provider_inbound_message_coordinator as coord_mod
from backend.services.exceptions import (
    InvalidProviderInboundMessageCommand,
)
from backend.services.provider_inbound_message_coordinator import (
    ProviderInboundMessageCommand,
    ProviderInboundMessageCoordinator,
    ProviderInboundMessageStatus,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
COORD_PATH = (
    REPO_ROOT
    / "backend"
    / "services"
    / "provider_inbound_message_coordinator.py"
)
RECEPCION_REPO_PATH = (
    REPO_ROOT
    / "backend"
    / "repositories"
    / "recepcion_mensaje_proveedor_repository.py"
)
SESSION_REPO_PATH = (
    REPO_ROOT
    / "backend"
    / "repositories"
    / "session_repository.py"
)


def _make_comando_valido(
    *,
    canal_id: int = 1,
    cliente_id: int = 2,
    comercio_id: int = 3,
    proveedor: str = "twilio",
    identificador: str = "SM-ABC",
    mensaje: str = "hola",
    destinatario_e164: str = "+5491100000000",
) -> ProviderInboundMessageCommand:
    return ProviderInboundMessageCommand(
        proveedor=proveedor,
        identificador_recepcion=identificador,
        canal_id=canal_id,
        cliente_id=cliente_id,
        comercio_id=comercio_id,
        mensaje=mensaje,
        destinatario_e164=destinatario_e164,
    )


def _make_canal_dedicado(comercio_id: int) -> MagicMock:
    canal = MagicMock(name="CanalWhatsapp")
    canal.id = 1
    canal.activo = True
    canal.mode = CanalWhatsappMode.DEDICATED
    canal.id_comercio_exclusivo = comercio_id
    return canal


def _make_canal_compartido() -> MagicMock:
    canal = MagicMock(name="CanalWhatsapp")
    canal.id = 11
    canal.activo = True
    canal.mode = CanalWhatsappMode.SHARED
    canal.id_comercio_exclusivo = None
    return canal


def _build_db_lookup(
    *,
    cliente: MagicMock | None,
    comercio: MagicMock | None,
    estado: MagicMock | None,
):
    """Return a ``session.get``-style callable for the supplied
    (cliente, comercio, estado) mocks."""

    def _lookup(cls, ident):
        name = cls.__name__
        if name == "Cliente" and cliente is not None and ident == cliente.id:
            return cliente
        if name == "Comercio" and comercio is not None and ident == comercio.id:
            return comercio
        if (
            name == "EstadoComercio"
            and estado is not None
            and ident == estado.id
        ):
            return estado
        return None

    return _lookup


def _wire_dependencies(
    *,
    canal: MagicMock,
    existing_context: MagicMock | None,
    membership_present: bool = True,
) -> dict[str, MagicMock]:
    cliente = MagicMock(name="Cliente")
    cliente.id = 2
    cliente.activo = True
    comercio = MagicMock(name="Comercio")
    comercio.id = 3
    comercio.estado_id = 99
    estado = MagicMock(name="EstadoComercio")
    estado.id = 99
    estado.estado = "ACTIVO"

    db_session = MagicMock(name="DatabaseSession")
    db_session.get.side_effect = _build_db_lookup(
        cliente=cliente, comercio=comercio, estado=estado
    )

    canal_repo = MagicMock(name="CanalWhatsappRepository")
    canal_repo.find_by_id.return_value = canal

    contexto_repo = MagicMock(
        name="ContextoClienteCanalWhatsappRepository"
    )
    contexto_repo.find_by_canal_and_cliente.return_value = existing_context

    membresia_repo = MagicMock(
        name="ComercioCanalCompartidoRepository"
    )
    if membership_present:
        default_membership = MagicMock(
            name="ActiveComercioCanalCompartido"
        )
        default_membership.id = 777
        default_membership.canal_id = canal.id
        default_membership.comercio_id = 3
        default_membership.activo = True
        membresia_repo.find_active_by_canal_and_comercio.return_value = (
            default_membership
        )
    else:
        membresia_repo.find_active_by_canal_and_comercio.return_value = (
            None
        )

    recepcion_repo = MagicMock(
        name="RecepcionMensajeProveedorRepository"
    )
    recepcion_repo.claim.return_value = 1

    procesamiento_repo = MagicMock(
        name="ProcesamientoMensajeProveedorRepository"
    )
    staged_work = MagicMock(name="StagedProcesamiento")
    staged_work.id = 555
    procesamiento_repo.stage.return_value = staged_work

    session_repo = MagicMock(name="SessionRepository")

    pedido_repo = MagicMock(name="PedidoRepository")

    outbox_repo = MagicMock(name="MensajeProveedorSalienteRepository")

    coordinator = ProviderInboundMessageCoordinator(
        session=db_session,
        canal_repo=canal_repo,
        contexto_repo=contexto_repo,
        membresia_repo=membresia_repo,
        recepcion_repo=recepcion_repo,
        procesamiento_repo=procesamiento_repo,
        session_repo=session_repo,
        pedido_repo=pedido_repo,
        outbox_repo=outbox_repo,
    )
    return {
        "coordinator": coordinator,
        "db": db_session,
        "recepcion_repo": recepcion_repo,
        "procesamiento_repo": procesamiento_repo,
        "session_repo": session_repo,
        "pedido_repo": pedido_repo,
        "outbox_repo": outbox_repo,
        "canal_repo": canal_repo,
        "contexto_repo": contexto_repo,
        "membresia_repo": membresia_repo,
        "staged_work": staged_work,
    }


class CommandValidationTest(unittest.TestCase):
    def test_empty_proveedor_rejected(self) -> None:
        with self.assertRaises(InvalidProviderInboundMessageCommand):
            ProviderInboundMessageCommand(
                proveedor="",
                identificador_recepcion="x",
                canal_id=1,
                cliente_id=2,
                comercio_id=3,
                mensaje="hola",
                destinatario_e164="+5491100000000",
            )

    def test_non_positive_canal_id_rejected(self) -> None:
        with self.assertRaises(InvalidProviderInboundMessageCommand):
            ProviderInboundMessageCommand(
                proveedor="twilio",
                identificador_recepcion="x",
                canal_id=0,
                cliente_id=2,
                comercio_id=3,
                mensaje="hola",
                destinatario_e164="+5491100000000",
            )

    def test_non_positive_cliente_id_rejected(self) -> None:
        with self.assertRaises(InvalidProviderInboundMessageCommand):
            ProviderInboundMessageCommand(
                proveedor="twilio",
                identificador_recepcion="x",
                canal_id=1,
                cliente_id=-1,
                comercio_id=3,
                mensaje="hola",
                destinatario_e164="+5491100000000",
            )

    def test_non_positive_comercio_id_rejected(self) -> None:
        with self.assertRaises(InvalidProviderInboundMessageCommand):
            ProviderInboundMessageCommand(
                proveedor="twilio",
                identificador_recepcion="x",
                canal_id=1,
                cliente_id=2,
                comercio_id=0,
                mensaje="hola",
                destinatario_e164="+5491100000000",
            )

    def test_whitespace_only_mensaje_rejected(self) -> None:
        with self.assertRaises(InvalidProviderInboundMessageCommand):
            ProviderInboundMessageCommand(
                proveedor="twilio",
                identificador_recepcion="x",
                canal_id=1,
                cliente_id=2,
                comercio_id=3,
                mensaje="   ",
                destinatario_e164="+5491100000000",
            )

    def test_bool_ids_rejected(self) -> None:
        with self.assertRaises(InvalidProviderInboundMessageCommand):
            ProviderInboundMessageCommand(
                proveedor="twilio",
                identificador_recepcion="x",
                canal_id=True,  # type: ignore[arg-type]
                cliente_id=2,
                comercio_id=3,
                mensaje="hola",
                destinatario_e164="+5491100000000",
            )

    def test_empty_destinatario_rejected(self) -> None:
        with self.assertRaises(InvalidProviderInboundMessageCommand):
            ProviderInboundMessageCommand(
                proveedor="twilio",
                identificador_recepcion="x",
                canal_id=1,
                cliente_id=2,
                comercio_id=3,
                mensaje="hola",
                destinatario_e164="   ",
            )


class FirstAcceptanceHappyPathTest(unittest.TestCase):
    def setUp(self) -> None:
        importlib.reload(coord_mod)

    def test_dedicated_first_acceptance_commits_once(self) -> None:
        comando = _make_comando_valido()
        canal = _make_canal_dedicado(comercio_id=3)
        env = _wire_dependencies(canal=canal, existing_context=None)

        with patch.object(coord_mod, "process_incoming_message") as pipeline:
            outcome = env["coordinator"].accept(comando)

        self.assertEqual(
            outcome.status,
            ProviderInboundMessageStatus.ACCEPTED,
        )
        self.assertEqual(outcome.resolution_source, "first_processing")
        self.assertEqual(outcome.proveedor, comando.proveedor)
        self.assertEqual(
            outcome.identificador_recepcion,
            comando.identificador_recepcion,
        )
        self.assertEqual(outcome.receipt_id, 1)
        self.assertEqual(outcome.procesamiento_id, 555)

        env["recepcion_repo"].claim.assert_called_once_with(
            comando.proveedor,
            comando.identificador_recepcion,
            comando.canal_id,
            comando.cliente_id,
            comando.comercio_id,
        )
        env["procesamiento_repo"].stage.assert_called_once_with(
            recepcion_mensaje_proveedor_id=1,
            mensaje=comando.mensaje,
        )

        pipeline.assert_not_called()
        env["session_repo"].stage_active.assert_not_called()
        env["pedido_repo"].stage_draft_for_session.assert_not_called()
        env["outbox_repo"].stage.assert_not_called()

        env["db"].commit.assert_called_once_with()
        env["db"].rollback.assert_not_called()
        env["db"].begin.assert_not_called()
        env["db"].refresh.assert_not_called()
        env["db"].expire.assert_not_called()

    def test_acceptance_never_invokes_pipeline(self) -> None:
        """The acceptance boundary MUST NOT import or call the
        classifier, recognizer, session staging, message pipeline,
        response mapper or outbound mapper.
        """
        comando = _make_comando_valido()
        canal = _make_canal_dedicado(comercio_id=3)
        env = _wire_dependencies(canal=canal, existing_context=None)

        with patch.object(
            coord_mod, "process_incoming_message"
        ) as pipeline, patch.object(
            coord_mod, "stage_outbound_rows"
        ) as outbound_mapper:
            env["coordinator"].accept(comando)

        pipeline.assert_not_called()
        outbound_mapper.assert_not_called()


class DuplicateReceiptIdempotencyTest(unittest.TestCase):
    def setUp(self) -> None:
        importlib.reload(coord_mod)

    def test_duplicate_receipt_returns_already_processed_and_rolls_back(
        self,
    ) -> None:
        comando = _make_comando_valido()
        canal = _make_canal_dedicado(comercio_id=3)
        env = _wire_dependencies(canal=canal, existing_context=None)
        env["recepcion_repo"].claim.return_value = None

        with patch.object(
            coord_mod, "process_incoming_message"
        ) as pipeline:
            outcome = env["coordinator"].accept(comando)

        self.assertEqual(
            outcome.status,
            ProviderInboundMessageStatus.ALREADY_PROCESSED,
        )
        self.assertEqual(
            outcome.resolution_source, "duplicate_receipt"
        )
        self.assertIsNone(outcome.receipt_id)
        self.assertIsNone(outcome.procesamiento_id)

        pipeline.assert_not_called()
        env["procesamiento_repo"].stage.assert_not_called()
        env["session_repo"].stage_active.assert_not_called()
        env["outbox_repo"].stage.assert_not_called()

        env["db"].rollback.assert_called_once_with()
        env["db"].commit.assert_not_called()
        env["db"].flush.assert_not_called()
        env["db"].begin.assert_not_called()


class ConcurrentClaimPipelineNeverInvokedTest(unittest.TestCase):
    def setUp(self) -> None:
        importlib.reload(coord_mod)

    def test_concurrent_loser_never_invokes_pipeline(self) -> None:
        comando = _make_comando_valido()
        canal = _make_canal_dedicado(comercio_id=3)
        env = _wire_dependencies(canal=canal, existing_context=None)
        env["recepcion_repo"].claim.return_value = None

        with patch.object(coord_mod, "process_incoming_message") as pipeline:
            outcome_a = env["coordinator"].accept(comando)
            outcome_b = env["coordinator"].accept(comando)

        self.assertEqual(
            outcome_a.status,
            ProviderInboundMessageStatus.ALREADY_PROCESSED,
        )
        self.assertEqual(
            outcome_b.status,
            ProviderInboundMessageStatus.ALREADY_PROCESSED,
        )
        pipeline.assert_not_called()
        env["procesamiento_repo"].stage.assert_not_called()
        env["session_repo"].stage_active.assert_not_called()
        self.assertEqual(env["db"].commit.call_count, 0)
        self.assertEqual(env["db"].rollback.call_count, 2)


class SharedChannelAuthorityTest(unittest.TestCase):
    def setUp(self) -> None:
        importlib.reload(coord_mod)

    def test_shared_selected_commerce_first_acceptance(self) -> None:
        comando = _make_comando_valido()
        canal = _make_canal_compartido()
        context = MagicMock(name="ContextoClienteCanalWhatsapp")
        context.comercio_id_seleccionado = 3
        context.comercio_id_cambio_pendiente = None
        context.mensaje_original_pendiente = None
        env = _wire_dependencies(
            canal=canal, existing_context=context
        )

        with patch.object(
            coord_mod, "process_incoming_message"
        ) as pipeline:
            outcome = env["coordinator"].accept(comando)

        self.assertEqual(
            outcome.status,
            ProviderInboundMessageStatus.ACCEPTED,
        )
        pipeline.assert_not_called()
        env["db"].commit.assert_called_once_with()
        env["db"].rollback.assert_not_called()

    def test_shared_missing_context_returns_invalid_context(self) -> None:
        comando = _make_comando_valido()
        canal = _make_canal_compartido()
        env = _wire_dependencies(
            canal=canal, existing_context=None
        )

        with patch.object(coord_mod, "process_incoming_message") as pipeline:
            outcome = env["coordinator"].accept(comando)

        self.assertEqual(
            outcome.status,
            ProviderInboundMessageStatus.INVALID_CONTEXT,
        )
        self.assertEqual(
            outcome.resolution_source, "missing_shared_context"
        )
        pipeline.assert_not_called()
        env["recepcion_repo"].claim.assert_not_called()
        env["procesamiento_repo"].stage.assert_not_called()
        env["session_repo"].stage_active.assert_not_called()
        env["db"].commit.assert_not_called()
        env["db"].rollback.assert_not_called()

    def test_shared_pending_only_target_is_invalid_context(self) -> None:
        comando = _make_comando_valido()
        canal = _make_canal_compartido()
        context = MagicMock(name="ContextoClienteCanalWhatsapp")
        context.comercio_id_seleccionado = None
        context.comercio_id_cambio_pendiente = 3
        context.mensaje_original_pendiente = "guardame la pizza"
        env = _wire_dependencies(
            canal=canal, existing_context=context
        )

        with patch.object(coord_mod, "process_incoming_message") as pipeline:
            outcome = env["coordinator"].accept(comando)

        self.assertEqual(
            outcome.status,
            ProviderInboundMessageStatus.INVALID_CONTEXT,
        )
        self.assertEqual(
            outcome.resolution_source, "pending_only_target"
        )
        pipeline.assert_not_called()
        env["recepcion_repo"].claim.assert_not_called()
        env["procesamiento_repo"].stage.assert_not_called()

    def test_shared_selected_mismatch_returns_invalid_context(self) -> None:
        comando = _make_comando_valido(comercio_id=3)
        canal = _make_canal_compartido()
        context = MagicMock(name="ContextoClienteCanalWhatsapp")
        context.comercio_id_seleccionado = 4
        context.comercio_id_cambio_pendiente = None
        context.mensaje_original_pendiente = None
        env = _wire_dependencies(
            canal=canal, existing_context=context
        )

        with patch.object(coord_mod, "process_incoming_message") as pipeline:
            outcome = env["coordinator"].accept(comando)

        self.assertEqual(
            outcome.status,
            ProviderInboundMessageStatus.INVALID_CONTEXT,
        )
        self.assertEqual(
            outcome.resolution_source, "selected_authority_mismatch"
        )
        pipeline.assert_not_called()
        env["recepcion_repo"].claim.assert_not_called()
        env["procesamiento_repo"].stage.assert_not_called()
        env["db"].commit.assert_not_called()

    def test_shared_selected_with_revoked_membership_returns_invalid_context(
        self,
    ) -> None:
        """Selected commerce is no longer an active member of the
        shared channel.

        ``ContextoClienteCanalWhatsapp.comercio_id_seleccionado`` still
        references the commerce, but its
        ``ComercioCanalCompartido`` membership has been revoked (or
        never existed). The coordinator MUST refuse to claim a
        receipt, stage a work item or invoke the pipeline.
        """
        comando = _make_comando_valido(comercio_id=3)
        canal = _make_canal_compartido()
        context = MagicMock(name="ContextoClienteCanalWhatsapp")
        context.comercio_id_seleccionado = 3
        context.comercio_id_cambio_pendiente = None
        context.mensaje_original_pendiente = None
        env = _wire_dependencies(
            canal=canal,
            existing_context=context,
            membership_present=False,
        )

        with patch.object(
            coord_mod, "process_incoming_message"
        ) as pipeline:
            outcome = env["coordinator"].accept(comando)

        self.assertEqual(
            outcome.status,
            ProviderInboundMessageStatus.INVALID_CONTEXT,
        )
        self.assertEqual(
            outcome.resolution_source, "revoked_shared_membership"
        )
        env["membresia_repo"].find_active_by_canal_and_comercio.assert_called_once_with(
            comando.canal_id, comando.comercio_id
        )
        pipeline.assert_not_called()
        env["recepcion_repo"].claim.assert_not_called()
        env["procesamiento_repo"].stage.assert_not_called()
        env["session_repo"].stage_active.assert_not_called()
        env["db"].commit.assert_not_called()
        env["db"].rollback.assert_not_called()
        env["db"].flush.assert_not_called()
        env["db"].begin.assert_not_called()


class DedicatedChannelAuthorityTest(unittest.TestCase):
    def setUp(self) -> None:
        importlib.reload(coord_mod)

    def test_dedicated_authority_mismatch_returns_invalid_context(
        self,
    ) -> None:
        comando = _make_comando_valido(comercio_id=3)
        canal = _make_canal_dedicado(comercio_id=999)
        env = _wire_dependencies(canal=canal, existing_context=None)

        with patch.object(coord_mod, "process_incoming_message") as pipeline:
            outcome = env["coordinator"].accept(comando)

        self.assertEqual(
            outcome.status,
            ProviderInboundMessageStatus.INVALID_CONTEXT,
        )
        self.assertEqual(
            outcome.resolution_source, "dedicated_authority"
        )
        pipeline.assert_not_called()
        env["recepcion_repo"].claim.assert_not_called()
        env["procesamiento_repo"].stage.assert_not_called()
        env["session_repo"].stage_active.assert_not_called()
        env["db"].commit.assert_not_called()

    def test_inactive_channel_returns_invalid_context(self) -> None:
        comando = _make_comando_valido()
        canal = _make_canal_dedicado(comercio_id=3)
        canal.activo = False
        env = _wire_dependencies(canal=canal, existing_context=None)

        with patch.object(coord_mod, "process_incoming_message") as pipeline:
            outcome = env["coordinator"].accept(comando)

        self.assertEqual(
            outcome.status,
            ProviderInboundMessageStatus.INVALID_CONTEXT,
        )
        self.assertEqual(
            outcome.resolution_source, "channel_lookup"
        )
        pipeline.assert_not_called()
        env["recepcion_repo"].claim.assert_not_called()
        env["db"].commit.assert_not_called()

    def test_missing_client_returns_invalid_context(self) -> None:
        comando = _make_comando_valido(cliente_id=999)
        canal = _make_canal_dedicado(comercio_id=3)
        env = _wire_dependencies(canal=canal, existing_context=None)

        with patch.object(coord_mod, "process_incoming_message") as pipeline:
            outcome = env["coordinator"].accept(comando)

        self.assertEqual(
            outcome.status,
            ProviderInboundMessageStatus.INVALID_CONTEXT,
        )
        self.assertEqual(
            outcome.resolution_source, "client_lookup"
        )
        pipeline.assert_not_called()
        env["recepcion_repo"].claim.assert_not_called()
        env["db"].commit.assert_not_called()
        env["db"].rollback.assert_not_called()

    def test_inactive_commerce_returns_invalid_context(self) -> None:
        comando = _make_comando_valido()
        canal = _make_canal_dedicado(comercio_id=3)
        env = _wire_dependencies(canal=canal, existing_context=None)

        def _lookup(cls, ident):
            if cls.__name__ == "Cliente" and ident == 2:
                cliente = MagicMock()
                cliente.id = 2
                cliente.activo = True
                return cliente
            return None

        env["db"].get.side_effect = _lookup

        with patch.object(coord_mod, "process_incoming_message") as pipeline:
            outcome = env["coordinator"].accept(comando)

        self.assertEqual(
            outcome.status,
            ProviderInboundMessageStatus.INVALID_CONTEXT,
        )
        self.assertEqual(
            outcome.resolution_source, "unavailable_commerce"
        )
        pipeline.assert_not_called()
        env["recepcion_repo"].claim.assert_not_called()
        env["db"].commit.assert_not_called()


class RollbackAtomicityTest(unittest.TestCase):
    def setUp(self) -> None:
        importlib.reload(coord_mod)

    def test_repository_stage_error_rolls_back_full_acceptance(
        self,
    ) -> None:
        """A failure raised while staging the work item (after the
        receipt claim) must roll back the entire coordinator
        transaction. No receipt or work row remains durable.
        """
        comando = _make_comando_valido()
        canal = _make_canal_dedicado(comercio_id=3)
        env = _wire_dependencies(canal=canal, existing_context=None)

        sentinel_exc = RuntimeError("work staging primitive raised")
        env["procesamiento_repo"].stage.side_effect = sentinel_exc

        with patch.object(coord_mod, "process_incoming_message") as pipeline:
            with self.assertRaises(RuntimeError) as ctx:
                env["coordinator"].accept(comando)

        self.assertIs(ctx.exception, sentinel_exc)
        env["recepcion_repo"].claim.assert_called_once()
        env["procesamiento_repo"].stage.assert_called_once()
        pipeline.assert_not_called()
        env["session_repo"].stage_active.assert_not_called()
        env["outbox_repo"].stage.assert_not_called()
        env["db"].commit.assert_not_called()
        env["db"].rollback.assert_called_once_with()

    def test_failed_acceptance_rolls_back_and_allows_retry(
        self,
    ) -> None:
        """A failed first attempt must not be treated as
        ``already_processed`` by a later valid retry.
        """
        comando = _make_comando_valido()
        canal = _make_canal_dedicado(comercio_id=3)
        env = _wire_dependencies(canal=canal, existing_context=None)
        env["procesamiento_repo"].stage.side_effect = RuntimeError(
            "boom"
        )

        with patch.object(
            coord_mod, "process_incoming_message"
        ) as pipeline:
            with self.assertRaises(RuntimeError):
                env["coordinator"].accept(comando)

        self.assertEqual(env["db"].rollback.call_count, 1)
        self.assertEqual(env["db"].commit.call_count, 0)

        env["procesamiento_repo"].stage.side_effect = None

        with patch.object(
            coord_mod, "process_incoming_message"
        ) as pipeline:
            outcome = env["coordinator"].accept(comando)

        self.assertEqual(
            outcome.status,
            ProviderInboundMessageStatus.ACCEPTED,
        )
        self.assertEqual(env["db"].commit.call_count, 1)
        self.assertEqual(env["db"].rollback.call_count, 1)
        pipeline.assert_not_called()


class StaticBoundariesTest(unittest.TestCase):
    """AST-level invariants: only the coordinator class owns
    ``commit`` / ``rollback`` / ``begin``; the coordinator never
    imports HTTP routers, FastAPI, the Twilio SDK, TwiML, outbound
    delivery or response delivery. The 5.5 / 5.6 phases own those.
    """

    def test_coordinator_is_only_commit_caller(self) -> None:
        tree = _parse(COORD_PATH)
        offenders: list[str] = []
        allowed = {
            "accept",
            "claim_due_processing",
            "process_lease",
            "_accept_locked",
            "_process_locked",
            "_finalize_failure",
            "_finalize_terminal",
        }
        for node in ast.walk(tree):
            if not isinstance(
                node,
                (ast.FunctionDef, ast.AsyncFunctionDef),
            ):
                continue
            for call in ast.walk(node):
                if not (
                    isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Attribute)
                    and call.func.attr in {"commit", "rollback"}
                ):
                    continue
                if node.name not in allowed:
                    offenders.append(node.name)
        self.assertEqual(
            offenders,
            [],
            f"Only the coordinator may invoke commit/rollback; offenders: {offenders}",
        )

    def test_coordinator_does_not_import_http_or_twilio(self) -> None:
        tree = _parse(COORD_PATH)
        names = {
            node.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Name)
        }
        forbidden = {
            "fastapi",
            "starlette",
            "twilio",
            "TwiML",
            "MessagingResponse",
            "RequestValidator",
            "twilio_request_validator",
        }
        leaked = forbidden & names
        self.assertEqual(
            leaked,
            set(),
            f"Coordinator must not import provider/HTTP/TwiML symbols: {leaked}",
        )

    def test_recepcion_repository_does_not_control_transaction(self) -> None:
        tree = _parse(RECEPCION_REPO_PATH)
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
            ):
                continue
            self.assertNotIn(
                node.func.attr,
                {"commit", "rollback", "begin", "flush", "close"},
                "RecepcionMensajeProveedorRepository must not control transactions",
            )

    def test_session_stage_helper_does_not_flush_or_commit(self) -> None:
        tree = _parse(SESSION_REPO_PATH)
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
            ):
                continue
            if node.func.attr not in {
                "flush",
                "commit",
                "rollback",
                "begin",
            }:
                continue
            enclosing = _enclosing_function(node, tree)
            self.assertIsNotNone(
                enclosing,
                "transaction-control call must live in a function",
            )
            self.assertIsNotNone(enclosing)
            if enclosing is not None:
                self.assertNotEqual(
                    enclosing.name,
                    "stage_active",
                    "stage_active MUST NOT flush or commit",
                )


def _parse(path: Path) -> ast.Module:
    with open(path, encoding="utf-8") as fh:
        return ast.parse(fh.read())


def _enclosing_function(
    node: ast.AST, root: ast.AST
) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    for parent in ast.walk(root):
        if not isinstance(
            parent, (ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            continue
        for child in ast.walk(parent):
            if child is node:
                return parent
    return None


class StageActiveHelperTest(unittest.TestCase):
    """``SessionRepository.stage_active`` returns the existing active
    session when one exists and adds a new pending row when one does
    not, without invoking ``flush``.
    """

    def test_stage_returns_existing_without_adding(self) -> None:
        from backend.models.session import EstadoSession

        existing = MagicMock(name="ExistingConversationSession")
        existing.id = 11
        existing.estado_session = EstadoSession.ACTIVA
        existing.context_type = "order_line_selection"

        db_session = MagicMock(name="DatabaseSession")

        class _StandaloneRepo(SessionRepository):
            def __init__(self) -> None:
                self._session = db_session
                self._existing = existing

            def get_active_by_comercio_cliente(
                self, id_comercio: int, id_cliente: int
            ):
                return self._existing

        result = _StandaloneRepo().stage_active(
            id_comercio=3, id_cliente=2
        )

        self.assertIs(result, existing)
        db_session.add.assert_not_called()
        db_session.flush.assert_not_called()
        db_session.commit.assert_not_called()
        db_session.rollback.assert_not_called()

    def test_stage_creates_pending_row_without_flushing(self) -> None:
        from backend.models.session import EstadoSession

        db_session = MagicMock(name="DatabaseSession")

        class _StandaloneRepo(SessionRepository):
            def __init__(self) -> None:
                self._session = db_session

            def get_active_by_comercio_cliente(
                self, id_comercio: int, id_cliente: int
            ):
                return None

        result = _StandaloneRepo().stage_active(
            id_comercio=3, id_cliente=2
        )

        db_session.add.assert_called_once()
        db_session.flush.assert_not_called()
        db_session.commit.assert_not_called()
        db_session.rollback.assert_not_called()
        self.assertEqual(result.estado_session, EstadoSession.ACTIVA)
        self.assertIsNone(result.id_pedido)


if __name__ == "__main__":
    unittest.main(verbosity=2)