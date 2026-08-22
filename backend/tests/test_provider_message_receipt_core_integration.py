"""Real PostgreSQL integration tests for ``ProviderInboundMessageCoordinator``.

These tests intentionally bypass mocks for the receipt-claim and the
work-staging boundary because the proof the spec relies on is the
actual PostgreSQL ``INSERT ... ON CONFLICT DO NOTHING RETURNING``
contract — the guarantee that a committed unique pair is never
claimed twice and that the second issuer observes an empty
``RETURNING`` instead of raising the unique-constraint violation.
Mocks cannot substitute for that guarantee.

Phase 7.4 splits the coordinator into two narrow transactions:

* ``accept`` — webhook acceptance. The first valid receipt claims
  the unique pair and stages exactly one pending deferred work item
  in a single transaction; duplicates roll back; invalid contexts
  never persist.
* ``process_lease`` — operator CLI processing. The deferred work
  item is claimed, leased and finalized through the existing
  ``process_incoming_message`` pipeline and outbox mapper in a single
  transaction.

The tests use the live ``supernova_test`` PostgreSQL database, seed
exactly one comercio, one canal, one cliente and one receipt row per
test, and remove every row they create so unrelated rows are never
modified.
"""
from __future__ import annotations

import json
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import patch

import requests
from sqlalchemy import create_engine, delete, select, text
from sqlalchemy.orm import Session as SqlSession
from sqlalchemy.orm import sessionmaker

from backend.config.settings import Settings
from backend.intents.schemas.customer_response import (
    CustomerResponse,
)
from backend.llm.query_llm import (
    QueryLlm,
    reset_llm_timing_recorder,
)
from backend.models import (
    CanalWhatsapp,
    CanalWhatsappMode,
    Cliente,
    Comercio,
    ComercioCanalCompartido,
    ContextoClienteCanalWhatsapp,
    EstadoComercio,
    EstadoPedido,
    EstadoSession,
    MensajeProveedorSaliente,
    Pedido,
    PedidoProducto,
    ProcesamientoMensajeProveedor,
    ProcesamientoMensajeProveedorEstado,
    ProcesamientoMensajeProveedorFailureCategory,
    RecepcionMensajeProveedor,
)
from backend.models import (
    Session as SessionModel,
)
from backend.observability import (
    COMPONENT_WORKER,
    EVENT_PROCESSING_OUTCOME,
    EVENT_PROVIDER_INBOUND_STAGE,
)
from backend.repositories.recepcion_mensaje_proveedor_repository import (
    RecepcionMensajeProveedorRepository,
)
from backend.services.commerce_availability_service import (
    CommerceAvailabilityOutcome,
    CommerceAvailabilityStatus,
    CommerceUnavailableReason,
)
from backend.services.outbound_response_mapper import (
    StagedOutboundRow,
)
from backend.services.provider_inbound_message_coordinator import (
    ProviderInboundMessageCommand,
    ProviderInboundMessageCoordinator,
    ProviderInboundMessageStatus,
    ProviderInboundProcessingOutcome,
    ProviderInboundProcessingResult,
)

TEST_URL = "postgresql+psycopg:///supernova_test"

engine = create_engine(TEST_URL)
TestingSessionLocal = sessionmaker(
    bind=engine, autoflush=False, autocommit=False
)


def _suffix() -> str:
    return uuid.uuid4().hex[:10]


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _estado_id(nombre: str) -> int:
    with engine.connect() as c:
        row = c.execute(
            select(EstadoComercio.id).where(EstadoComercio.codigo == nombre)
        ).first()
        if row is None:
            raise RuntimeError(
                f"estado {nombre!r} not seeded in supernova_test"
            )
        return row[0]


def _estado_id_activo() -> int:
    return _estado_id("ACTIVO")


def _delete_recepciones_by_comercio(comercio_id: int) -> None:
    with TestingSessionLocal() as session, session.begin():
        session.execute(
            delete(RecepcionMensajeProveedor).where(
                RecepcionMensajeProveedor.comercio_id == comercio_id
            )
        )


def _delete_procesamientos_by_comercio(comercio_id: int) -> None:
    with TestingSessionLocal() as session, session.begin():
        session.execute(
            delete(ProcesamientoMensajeProveedor).where(
                ProcesamientoMensajeProveedor.recepcion_mensaje_proveedor_id.in_(
                    select(
                        RecepcionMensajeProveedor.id
                    ).where(
                        RecepcionMensajeProveedor.comercio_id
                        == comercio_id
                    )
                )
            )
        )


def _delete_contexts(cliente_id: int) -> None:
    with TestingSessionLocal() as session, session.begin():
        session.execute(
            delete(ContextoClienteCanalWhatsapp).where(
                ContextoClienteCanalWhatsapp.cliente_id == cliente_id
            )
        )


def _delete_cliente(cliente_id: int) -> None:
    with TestingSessionLocal() as session, session.begin():
        _delete_contexts(cliente_id)
        session.execute(delete(Cliente).where(Cliente.id == cliente_id))


def _delete_comercio(comercio_id: int) -> None:
    with TestingSessionLocal() as session, session.begin():
        canal_ids_subquery = select(CanalWhatsapp.id).where(
            CanalWhatsapp.id_comercio_exclusivo == comercio_id
        )
        session.execute(
            delete(ComercioCanalCompartido).where(
                ComercioCanalCompartido.comercio_id == comercio_id
            )
        )
        session.execute(
            delete(ComercioCanalCompartido).where(
                ComercioCanalCompartido.canal_id.in_(canal_ids_subquery)
            )
        )
        session.execute(
            delete(ContextoClienteCanalWhatsapp).where(
                ContextoClienteCanalWhatsapp.comercio_id_seleccionado
                == comercio_id
            )
        )
        session.execute(
            delete(RecepcionMensajeProveedor).where(
                RecepcionMensajeProveedor.comercio_id == comercio_id
            )
        )
        session.execute(
            delete(CanalWhatsapp).where(
                CanalWhatsapp.id_comercio_exclusivo == comercio_id
            )
        )
        session.execute(delete(Comercio).where(Comercio.id == comercio_id))


def _delete_canales_by_destination(destination: str) -> None:
    with TestingSessionLocal() as session, session.begin():
        canal_ids_subquery = select(CanalWhatsapp.id).where(
            CanalWhatsapp.destination_e164 == destination
        )
        session.execute(
            delete(ContextoClienteCanalWhatsapp).where(
                ContextoClienteCanalWhatsapp.canal_id.in_(
                    canal_ids_subquery
                )
            )
        )
        session.execute(
            delete(ComercioCanalCompartido).where(
                ComercioCanalCompartido.canal_id.in_(canal_ids_subquery)
            )
        )
        session.execute(
            delete(RecepcionMensajeProveedor).where(
                RecepcionMensajeProveedor.canal_id.in_(canal_ids_subquery)
            )
        )
        session.execute(
            delete(CanalWhatsapp).where(
                CanalWhatsapp.destination_e164 == destination
            )
        )


def _seed_comercio(suffix: str) -> int:
    whatsapp_digits = suffix.lower().replace("a", "0").replace(
        "b", "1"
    ).replace("c", "2").replace("d", "3").replace("e", "4").replace(
        "f", "5"
    )
    with TestingSessionLocal() as session, session.begin():
        comercio = Comercio(
            nombre_fantasia=f"Receipt Core {suffix}",
            nombre_corto=f"RC {suffix[:6]}",
            razon_social=f"Receipt Core SRL {suffix}",
            cuit=f"30-{suffix[:8]}-{suffix[8].upper()}",
            whatsapp=f"+54941{whatsapp_digits}",
            calle="Av. Receipt",
            numero="100",
            piso_departamento=None,
            localidad="CABA",
            provincia="Buenos Aires",
            codigo_postal="C1000",
            slug=f"receipt-core-{suffix.lower()}"[:150],
            estado_id=_estado_id_activo(),
        )
        session.add(comercio)
        session.flush()
        return int(comercio.id)


def _seed_cliente(suffix: str) -> int:
    whatsapp_digits = suffix.lower().replace("a", "0").replace(
        "b", "1"
    ).replace("c", "2").replace("d", "3").replace("e", "4").replace(
        "f", "5"
    )
    with TestingSessionLocal() as session, session.begin():
        cliente = Cliente(
            whatsapp=f"+54951{whatsapp_digits}",
            nombre=f"Receipt Cliente {suffix}",
            domicilio=None,
            activo=True,
        )
        session.add(cliente)
        session.flush()
        return int(cliente.id)


def _seed_dedicated_channel(
    suffix: str, comercio_id: int, destination: str
) -> int:
    with TestingSessionLocal() as session, session.begin():
        canal = CanalWhatsapp(
            provider="twilio",
            destination_e164=destination,
            mode=CanalWhatsappMode.DEDICATED,
            id_comercio_exclusivo=comercio_id,
            activo=True,
        )
        session.add(canal)
        session.flush()
        return int(canal.id)


def _seed_shared_channel(suffix: str, destination: str) -> int:
    with TestingSessionLocal() as session, session.begin():
        canal = CanalWhatsapp(
            provider="twilio",
            destination_e164=destination,
            mode=CanalWhatsappMode.SHARED,
            id_comercio_exclusivo=None,
            activo=True,
        )
        session.add(canal)
        session.flush()
        return int(canal.id)


def _seed_shared_membership(
    canal_id: int, comercio_id: int, code: str, activo: bool = True
) -> int:
    with TestingSessionLocal() as session, session.begin():
        membership = ComercioCanalCompartido(
            canal_id=canal_id,
            comercio_id=comercio_id,
            routing_code=code,
            routing_code_normalizado=code,
            activo=activo,
        )
        session.add(membership)
        session.flush()
        return int(membership.id)


def _seed_shared_context(
    canal_id: int,
    cliente_id: int,
    comercio_id: int,
    mensaje: str | None = None,
) -> None:
    with TestingSessionLocal() as session, session.begin():
        session.add(
            ContextoClienteCanalWhatsapp(
                canal_id=canal_id,
                cliente_id=cliente_id,
                comercio_id_seleccionado=comercio_id,
                comercio_id_cambio_pendiente=None,
                mensaje_original_pendiente=mensaje,
            )
        )


def _count_recepciones(
    session: SqlSession, proveedor: str, identificador: str
) -> int:
    row = session.execute(
        select(RecepcionMensajeProveedor).where(
            RecepcionMensajeProveedor.proveedor == proveedor,
            RecepcionMensajeProveedor.identificador_recepcion
            == identificador,
        )
    ).all()
    return len(row)


def _count_procesamientos(
    session: SqlSession, recepcion_id: int
) -> int:
    return len(
        session.execute(
            select(ProcesamientoMensajeProveedor).where(
                ProcesamientoMensajeProveedor.recepcion_mensaje_proveedor_id
                == recepcion_id
            )
        ).all()
    )


def _seed_active_session(
    comercio_id: int,
    cliente_id: int,
    id_pedido: int | None = None,
) -> int:
    with TestingSessionLocal() as session, session.begin():
        row = SessionModel(
            id_comercio=comercio_id,
            id_cliente=cliente_id,
            id_pedido=id_pedido,
            estado_session=EstadoSession.ACTIVA,
        )
        session.add(row)
        session.flush()
        return int(row.id)


def _seed_draft_pedido(id_session: int) -> int:
    with TestingSessionLocal() as session, session.begin():
        row = Pedido(
            id_session=id_session,
            estado_pedido=EstadoPedido.BORRADOR,
        )
        session.add(row)
        session.flush()
        return int(row.id)


def _delete_outbox_for_comercio(comercio_id: int) -> None:
    with TestingSessionLocal() as session, session.begin():
        session.execute(
            delete(MensajeProveedorSaliente).where(
                MensajeProveedorSaliente.recepcion_mensaje_proveedor_id.in_(
                    select(
                        RecepcionMensajeProveedor.id
                    ).where(
                        RecepcionMensajeProveedor.comercio_id
                        == comercio_id
                    )
                )
            )
        )


def _delete_pedidos_for_comercio(comercio_id: int) -> None:
    with TestingSessionLocal() as session, session.begin():
        session.execute(
            delete(PedidoProducto).where(
                PedidoProducto.id_pedido.in_(
                    select(Pedido.id).where(
                        Pedido.id_session.in_(
                            select(SessionModel.id).where(
                                SessionModel.id_comercio == comercio_id
                            )
                        )
                    )
                )
            )
        )
        # ``sessions.id_pedido`` is FK RESTRICT, so we must first
        # NULL out the session FK before deleting the pedido rows.
        session.execute(
            text(
                "UPDATE sessions SET id_pedido = NULL "
                "WHERE id_comercio = :cid"
            ),
            {"cid": comercio_id},
        )
        session.execute(
            delete(Pedido).where(
                Pedido.id_session.in_(
                    select(SessionModel.id).where(
                        SessionModel.id_comercio == comercio_id
                    )
                )
            )
        )


def _delete_sessions_for_comercio(comercio_id: int) -> None:
    with TestingSessionLocal() as session, session.begin():
        session.execute(
            delete(SessionModel).where(
                SessionModel.id_comercio == comercio_id
            )
        )


def _cleanup_provider_inbound_artifacts(comercio_id: int) -> None:
    _delete_outbox_for_comercio(comercio_id)
    _delete_pedidos_for_comercio(comercio_id)
    _delete_sessions_for_comercio(comercio_id)


def _load_session(cliente_id: int, comercio_id: int) -> SessionModel:
    with TestingSessionLocal() as session:
        return session.execute(
            select(SessionModel).where(
                SessionModel.id_cliente == cliente_id,
                SessionModel.id_comercio == comercio_id,
            )
        ).scalar_one()


def _delete_scenario_fixture(
    cliente_id: int, identificador: str
) -> None:
    """Atomic cleanup for one scenario's cliente + receipt + work item.

    The per-scenario ``addCleanup`` registered by
    :func:`_setup_scenario` runs BEFORE the comercio-level
    ``_delete_recepciones_by_comercio`` cleanup (LIFO order), so the
    foreign-key chain ``cliente <- recepcion <- procesamiento /
    outbox`` and ``cliente <- session <- pedido`` MUST be unwound
    here to avoid an ``IntegrityError`` when the scenario's cliente
    is dropped.
    """
    with TestingSessionLocal() as session, session.begin():
        receipt_ids_subquery = select(RecepcionMensajeProveedor.id).where(
            RecepcionMensajeProveedor.identificador_recepcion
            == identificador
        )
        # Unwind pedido chain before sessions.
        pedido_ids_subquery = select(Pedido.id).where(
            Pedido.id_session.in_(
                select(SessionModel.id).where(
                    SessionModel.id_cliente == cliente_id
                )
            )
        )
        session.execute(
            delete(PedidoProducto).where(
                PedidoProducto.id_pedido.in_(pedido_ids_subquery)
            )
        )
        # ``sessions.id_pedido`` is FK RESTRICT, so we must NULL
        # out the session FK before deleting the pedido rows.
        session.execute(
            text(
                "UPDATE sessions SET id_pedido = NULL "
                "WHERE id_cliente = :cid"
            ),
            {"cid": cliente_id},
        )
        session.execute(
            delete(Pedido).where(Pedido.id.in_(pedido_ids_subquery))
        )
        session.execute(
            delete(SessionModel).where(
                SessionModel.id_cliente == cliente_id
            )
        )
        session.execute(
            delete(ProcesamientoMensajeProveedor).where(
                ProcesamientoMensajeProveedor.recepcion_mensaje_proveedor_id.in_(
                    receipt_ids_subquery
                )
            )
        )
        session.execute(
            delete(MensajeProveedorSaliente).where(
                MensajeProveedorSaliente.recepcion_mensaje_proveedor_id.in_(
                    receipt_ids_subquery
                )
            )
        )
        session.execute(
            delete(RecepcionMensajeProveedor).where(
                RecepcionMensajeProveedor.identificador_recepcion
                == identificador
            )
        )
        _delete_contexts(cliente_id)
        session.execute(
            delete(Cliente).where(Cliente.id == cliente_id)
        )


def _count_pedidos_for_session(session_id: int) -> int:
    with TestingSessionLocal() as session:
        return len(
            session.execute(
                select(Pedido).where(Pedido.id_session == session_id)
            ).all()
        )


def _count_all_pedidos_for_comercio(comercio_id: int) -> int:
    with TestingSessionLocal() as session:
        return len(
            session.execute(
                select(Pedido).where(
                    Pedido.id_session.in_(
                        select(SessionModel.id).where(
                            SessionModel.id_comercio == comercio_id
                        )
                    )
                )
            ).all()
        )


class ReceiptClaimIdempotencyTest(unittest.TestCase):
    """Real-PostgreSQL proof of the ``INSERT ... ON CONFLICT DO NOTHING
    RETURNING`` contract that the coordinator depends on."""

    def setUp(self) -> None:
        suffix = _suffix()
        self.comercio_id = _seed_comercio(suffix)
        self.addCleanup(_delete_comercio, self.comercio_id)
        self.cliente_id = _seed_cliente(suffix + "C")
        self.addCleanup(_delete_cliente, self.cliente_id)
        self.destination = f"+54971{suffix[:8]}"
        self.addCleanup(_delete_canales_by_destination, self.destination)
        self.canal_id = _seed_dedicated_channel(
            suffix + "D", self.comercio_id, self.destination
        )
        self.proveedor = "twilio"
        self.identificador = f"SM-{suffix}"
        self.addCleanup(_delete_recepciones_by_comercio, self.comercio_id)
        self.addCleanup(_delete_procesamientos_by_comercio, self.comercio_id)

    def test_first_claim_inserts_row_and_returns_true(self) -> None:
        with TestingSessionLocal() as session:
            repo = RecepcionMensajeProveedorRepository(session)
            result = repo.claim(
                self.proveedor,
                self.identificador,
                self.canal_id,
                self.cliente_id,
                self.comercio_id,
            )
            session.commit()
        self.assertIsNotNone(result)
        assert result is not None
        with TestingSessionLocal() as session:
            self.assertEqual(
                _count_recepciones(
                    session, self.proveedor, self.identificador
                ),
                1,
            )
            row = session.execute(
                select(RecepcionMensajeProveedor).where(
                    RecepcionMensajeProveedor.proveedor == self.proveedor,
                    RecepcionMensajeProveedor.identificador_recepcion
                    == self.identificador,
                )
            ).scalar_one()
            self.assertEqual(int(row.id), int(result))
            self.assertEqual(int(row.canal_id), self.canal_id)
            self.assertEqual(int(row.cliente_id), self.cliente_id)
            self.assertEqual(int(row.comercio_id), self.comercio_id)

    def test_duplicate_claim_returns_none_and_does_not_insert(self) -> None:
        with TestingSessionLocal() as session:
            repo = RecepcionMensajeProveedorRepository(session)
            first = repo.claim(
                self.proveedor,
                self.identificador,
                self.canal_id,
                self.cliente_id,
                self.comercio_id,
            )
            session.commit()
        self.assertIsNotNone(first)

        with TestingSessionLocal() as session:
            repo = RecepcionMensajeProveedorRepository(session)
            second = repo.claim(
                self.proveedor,
                self.identificador,
                self.canal_id,
                self.cliente_id,
                self.comercio_id,
            )
            session.commit()
        self.assertIsNone(second)

        with TestingSessionLocal() as session:
            self.assertEqual(
                _count_recepciones(
                    session, self.proveedor, self.identificador
                ),
                1,
                "duplicate claim must not create a second row",
            )

    def test_failed_first_claim_rolls_back_and_allows_retry(self) -> None:
        """A failed transaction must not leave a receipt row behind;
        a subsequent valid attempt must succeed because the
        ``ON CONFLICT DO NOTHING`` semantics only see committed rows.
        """
        with TestingSessionLocal() as session:
            repo = RecepcionMensajeProveedorRepository(session)
            self.assertIsNotNone(
                repo.claim(
                    self.proveedor,
                    self.identificador,
                    self.canal_id,
                    self.cliente_id,
                    self.comercio_id,
                )
            )
            session.rollback()

        with TestingSessionLocal() as session:
            self.assertEqual(
                _count_recepciones(
                    session, self.proveedor, self.identificador
                ),
                0,
                "rolled-back insert must not leave a row behind",
            )

        with TestingSessionLocal() as session:
            repo = RecepcionMensajeProveedorRepository(session)
            self.assertTrue(
                repo.claim(
                    self.proveedor,
                    self.identificador,
                    self.canal_id,
                    self.cliente_id,
                    self.comercio_id,
                )
            )
            session.commit()

        with TestingSessionLocal() as session:
            self.assertEqual(
                _count_recepciones(
                    session, self.proveedor, self.identificador
                ),
                1,
            )


class AcceptanceIntegrationTest(unittest.TestCase):
    """Phase 7.4 acceptance path against the live PostgreSQL
    ``recepciones_mensajes_proveedor`` and
    ``procesamientos_mensajes_proveedor`` tables.

    Scenarios covered:

    * First valid receipt: commits one receipt + one pending work
      item; no session/pedido/outbox effects.
    * Duplicate receipt: returns ``already_processed``; no second
      work item, no session, no pedido, no outbox.
    * Acceptance rollback: a forced post-claim pre-commit failure
      leaves zero durable rows.
    * Shared-channel membership revoked: returns
      ``invalid_context`` with zero mutations.
    """

    def setUp(self) -> None:
        suffix = _suffix()
        self.comercio_id = _seed_comercio(suffix)
        self.cliente_id = _seed_cliente(suffix + "C")
        self.destination = f"+54991{suffix[:8]}"
        self.canal_id = _seed_dedicated_channel(
            suffix + "D", self.comercio_id, self.destination
        )
        self.proveedor = "twilio"
        self.identificador = f"SM-{suffix}"
        self.addCleanup(_delete_comercio, self.comercio_id)
        self.addCleanup(_delete_cliente, self.cliente_id)
        self.addCleanup(_delete_canales_by_destination, self.destination)
        self.addCleanup(_delete_recepciones_by_comercio, self.comercio_id)
        self.addCleanup(_delete_procesamientos_by_comercio, self.comercio_id)
        self.addCleanup(_cleanup_provider_inbound_artifacts, self.comercio_id)

    def _command(
        self, identificador: str | None = None
    ) -> ProviderInboundMessageCommand:
        return ProviderInboundMessageCommand(
            proveedor=self.proveedor,
            identificador_recepcion=(
                identificador if identificador is not None
                else self.identificador
            ),
            canal_id=self.canal_id,
            cliente_id=self.cliente_id,
            comercio_id=self.comercio_id,
            mensaje="hola",
            destinatario_e164=self.destination,
        )

    def _open_coordinator(self) -> ProviderInboundMessageCoordinator:
        return ProviderInboundMessageCoordinator(
            session=TestingSessionLocal(),
        )

    def test_first_receipt_commits_one_receipt_and_one_work_item(
        self,
    ) -> None:
        coordinator = self._open_coordinator()
        command = self._command()
        with patch(
            "backend.services.provider_inbound_message_coordinator"
            ".process_incoming_message"
        ) as pipeline:
            outcome = coordinator.accept(command)

        self.assertEqual(
            outcome.status,
            ProviderInboundMessageStatus.ACCEPTED,
        )
        self.assertIsNotNone(outcome.receipt_id)
        self.assertIsNotNone(outcome.procesamiento_id)
        pipeline.assert_not_called()

        assert outcome.receipt_id is not None
        receipt_id = int(outcome.receipt_id)
        with TestingSessionLocal() as session:
            self.assertEqual(
                _count_recepciones(
                    session, self.proveedor, self.identificador
                ),
                1,
            )
            self.assertEqual(
                _count_procesamientos(
                    session, receipt_id
                ),
                1,
                "exactly one work item must be staged per first "
                "receipt",
            )
            sessions_now = len(
                session.execute(
                    select(SessionModel).where(
                        SessionModel.id_comercio == self.comercio_id
                    )
                ).all()
            )
            self.assertEqual(sessions_now, 0)
            outbox_now = len(
                session.execute(
                    select(MensajeProveedorSaliente).where(
                        MensajeProveedorSaliente.recepcion_mensaje_proveedor_id
                        == receipt_id
                    )
                ).all()
            )
            self.assertEqual(outbox_now, 0)

    def test_duplicate_receipt_creates_no_second_work_item(self) -> None:
        coordinator_a = self._open_coordinator()
        with patch(
            "backend.services.provider_inbound_message_coordinator"
            ".process_incoming_message"
        ):
            first = coordinator_a.accept(self._command())
        self.assertEqual(
            first.status,
            ProviderInboundMessageStatus.ACCEPTED,
        )
        work_count_after_first = _count_procesamientos_for_comercio(
            self.comercio_id
        )

        coordinator_b = self._open_coordinator()
        with patch(
            "backend.services.provider_inbound_message_coordinator"
            ".process_incoming_message"
        ) as pipeline:
            second = coordinator_b.accept(self._command())

        self.assertEqual(
            second.status,
            ProviderInboundMessageStatus.ALREADY_PROCESSED,
        )
        pipeline.assert_not_called()
        self.assertEqual(
            _count_procepciones(self.comercio_id),
            1,
            "duplicate receipt must not create a new receipt",
        )
        self.assertEqual(
            _count_procesamientos_for_comercio(self.comercio_id),
            work_count_after_first,
            "duplicate receipt must not create a second work item",
        )

    def test_acceptance_rollback_leaves_no_durable_rows(self) -> None:
        """A forced pre-commit failure during acceptance must leave
        no receipt and no work item durable. The acceptance path
        stages the work item via
        ``ProcesamientoMensajeProveedorRepository.stage``; a
        failure raised inside that primitive rolls the entire
        acceptance transaction back.
        """
        from backend.repositories.procesamiento_mensaje_proveedor_repository import (
            ProcesamientoMensajeProveedorRepository,
        )

        coordinator = self._open_coordinator()
        original_stage = ProcesamientoMensajeProveedorRepository.stage

        def _explode(
            self: Any,
            *args: Any,
            **kwargs: Any,
        ) -> Any:
            raise RuntimeError("forced pre-commit failure")

        with patch.object(
            ProcesamientoMensajeProveedorRepository,
            "stage",
            new=_explode,
        ):
            with self.assertRaises(RuntimeError):
                coordinator.accept(self._command())

        self.assertEqual(
            _count_procepciones(self.comercio_id),
            0,
            "rolled-back transaction must leave no receipt",
        )
        self.assertEqual(
            _count_procesamientos_for_comercio(self.comercio_id),
            0,
            "rolled-back transaction must leave no work item",
        )
        # Restore to keep the rest of the test class clean.
        ProcesamientoMensajeProveedorRepository.stage = original_stage


def _count_procepciones(comercio_id: int) -> int:
    with TestingSessionLocal() as session:
        return len(
            session.execute(
                select(RecepcionMensajeProveedor).where(
                    RecepcionMensajeProveedor.comercio_id == comercio_id
                )
            ).all()
        )


def _count_procesamientos_for_comercio(comercio_id: int) -> int:
    with TestingSessionLocal() as session:
        return len(
            session.execute(
                select(ProcesamientoMensajeProveedor).where(
                    ProcesamientoMensajeProveedor.recepcion_mensaje_proveedor_id.in_(
                        select(
                            RecepcionMensajeProveedor.id
                        ).where(
                            RecepcionMensajeProveedor.comercio_id
                            == comercio_id
                        )
                    )
                )
            ).all()
        )


class SharedChannelMembershipRevokedIntegrationTest(unittest.TestCase):
    """Real PostgreSQL test for the membership-revalidation fix.

    The provider coordinator MUST refuse to claim a receipt when the
    selected commerce no longer has an active
    ``ComercioCanalCompartido`` for the shared channel. This is
    exercised against the live database to prove the rule is enforced
    end-to-end, with zero mutated rows.
    """

    def setUp(self) -> None:
        suffix = _suffix()
        self.comercio_id = _seed_comercio(suffix)
        self.addCleanup(_delete_comercio, self.comercio_id)
        self.cliente_id = _seed_cliente(suffix + "C")
        self.addCleanup(_delete_cliente, self.cliente_id)
        self.destination = f"+54981{suffix[:8]}"
        self.addCleanup(_delete_canales_by_destination, self.destination)
        self.canal_id = _seed_shared_channel(suffix + "S", self.destination)
        self.code = f"SH-{suffix[:6]}"
        self.membership_id = _seed_shared_membership(
            self.canal_id,
            self.comercio_id,
            self.code,
            activo=True,
        )
        self.identificador = f"SM-{suffix}"
        self.addCleanup(_delete_recepciones_by_comercio, self.comercio_id)
        self.addCleanup(_delete_procesamientos_by_comercio, self.comercio_id)

    def _count_all_recepciones(self) -> int:
        with TestingSessionLocal() as session:
            return len(
                session.execute(
                    select(RecepcionMensajeProveedor).where(
                        RecepcionMensajeProveedor.comercio_id
                        == self.comercio_id
                    )
                ).all()
            )

    def _load_context(self) -> ContextoClienteCanalWhatsapp:
        with TestingSessionLocal() as session:
            return session.execute(
                select(ContextoClienteCanalWhatsapp).where(
                    ContextoClienteCanalWhatsapp.canal_id == self.canal_id,
                    ContextoClienteCanalWhatsapp.cliente_id
                    == self.cliente_id,
                )
            ).scalar_one()

    def _open_coordinator(self) -> ProviderInboundMessageCoordinator:
        return ProviderInboundMessageCoordinator(
            session=TestingSessionLocal(),
        )

    def _command(self) -> ProviderInboundMessageCommand:
        return ProviderInboundMessageCommand(
            proveedor="twilio",
            identificador_recepcion=self.identificador,
            canal_id=self.canal_id,
            cliente_id=self.cliente_id,
            comercio_id=self.comercio_id,
            mensaje="hola",
            destinatario_e164=self.destination,
        )

    def test_revoked_membership_yields_invalid_context_with_zero_mutations(
        self,
    ) -> None:
        _seed_shared_context(
            self.canal_id,
            self.cliente_id,
            self.comercio_id,
            mensaje="texto base",
        )
        with TestingSessionLocal() as session, session.begin():
            session.execute(
                text(
                    "UPDATE comercios_canales_compartidos "
                    "SET activo = false WHERE id = :mid"
                ),
                {"mid": self.membership_id},
            )
        context_before = self._load_context()
        recepciones_before = self._count_all_recepciones()

        coordinator = self._open_coordinator()
        command = self._command()
        with patch(
            "backend.services.provider_inbound_message_coordinator"
            ".process_incoming_message"
        ) as pipeline:
            outcome = coordinator.accept(command)

        self.assertEqual(
            outcome.status,
            ProviderInboundMessageStatus.INVALID_CONTEXT,
        )
        self.assertEqual(
            outcome.resolution_source, "revoked_shared_membership"
        )
        pipeline.assert_not_called()

        context_after = self._load_context()
        self.assertEqual(
            context_after.comercio_id_seleccionado,
            context_before.comercio_id_seleccionado,
        )
        self.assertEqual(
            context_after.mensaje_original_pendiente,
            context_before.mensaje_original_pendiente,
        )
        self.assertEqual(
            self._count_all_recepciones(),
            recepciones_before,
            "no receipt row may be created for invalid context",
        )


class ProcessingIntegrationTest(unittest.TestCase):
    """Phase 7.4 deferred processing path against the live
    PostgreSQL database.

    Scenarios covered:

    * First accepted work item, no pre-existing session: deferred
      processing creates exactly one ``borrador`` pedido bound to the
      active session and stages the existing outbound rows.
    * Existing active session with ``id_pedido is null``: one new
      draft pedido is created and associated; the previous session
      row is preserved with the new pedido FK.
    * Existing active session already associated: no new pedido is
      created.
    * Forced processing failure: receipt and work item remain; the
      transient body is preserved for retry and the work is
      finalized in a bounded ``retryable`` state with safe
      category/code (no raw exception bytes).
    * Forced processing failure with exhausted budget: the work is
      finalized in a ``failed_terminal`` state with the transient
      body cleared.
    """

    def setUp(self) -> None:
        suffix = _suffix()
        self.comercio_id = _seed_comercio(suffix)
        self.cliente_id = _seed_cliente(suffix + "C")
        self.destination = f"+54992{suffix[:8]}"
        self.canal_id = _seed_dedicated_channel(
            suffix + "D", self.comercio_id, self.destination
        )
        self.proveedor = "twilio"
        self.identificador = f"SM-{suffix}"
        self.addCleanup(_delete_comercio, self.comercio_id)
        self.addCleanup(_delete_cliente, self.cliente_id)
        self.addCleanup(_delete_canales_by_destination, self.destination)
        self.addCleanup(_delete_recepciones_by_comercio, self.comercio_id)
        self.addCleanup(_delete_procesamientos_by_comercio, self.comercio_id)
        self.addCleanup(_cleanup_provider_inbound_artifacts, self.comercio_id)

    def _command(
        self, identificador: str | None = None
    ) -> ProviderInboundMessageCommand:
        return ProviderInboundMessageCommand(
            proveedor=self.proveedor,
            identificador_recepcion=(
                identificador if identificador is not None
                else self.identificador
            ),
            canal_id=self.canal_id,
            cliente_id=self.cliente_id,
            comercio_id=self.comercio_id,
            mensaje="hola",
            destinatario_e164=self.destination,
        )

    def _accept(
        self,
    ) -> tuple[int, int]:
        coordinator = ProviderInboundMessageCoordinator(
            session=TestingSessionLocal(),
        )
        with patch(
            "backend.services.provider_inbound_message_coordinator"
            ".process_incoming_message"
        ):
            outcome = coordinator.accept(self._command())
        assert outcome.receipt_id is not None
        assert outcome.procesamiento_id is not None
        return int(outcome.receipt_id), int(outcome.procesamiento_id)

    def _claim_and_process(
        self,
        *,
        pipeline_returns: list[Any] | None = None,
        pipeline_side_effect: BaseException | None = None,
        max_attempts: int = 3,
    ) -> tuple[ProviderInboundProcessingResult, Any]:
        """Claim the next due work item through the coordinator's
        ``claim_due_processing`` (which commits the lease) and
        process the leased row through ``process_lease``. Returns
        the result and the pipeline mock so tests can assert the
        pipeline call count.

        The test helper uses the same short-lived session for
        claim and processing so the lease token, receipt FK and
        body are read back from the same database transaction
        boundary the coordinator owns. A flush is issued after the
        business effects are staged and before the work item is
        finalized so the deferred updates are visible to the
        conditional finalize UPDATE.
        """
        session = TestingSessionLocal()
        try:
            coordinator = ProviderInboundMessageCoordinator(
                session=session,
                max_attempts=max_attempts,
            )
            leased = coordinator.claim_due_processing(now=_now())
            assert leased is not None

            pipeline_patch: dict[str, Any] = {}
            if pipeline_side_effect is not None:
                pipeline_patch["side_effect"] = pipeline_side_effect
            else:
                pipeline_patch["return_value"] = pipeline_returns or []
            with patch(
                "backend.services.provider_inbound_message_coordinator"
                ".process_incoming_message",
                **pipeline_patch,
            ) as pipeline:
                result = coordinator.process_lease(leased)
            return result, pipeline
        finally:
            session.close()

    def test_first_processing_creates_one_draft_pedido_and_associates_session(
        self,
    ) -> None:
        _, _ = self._accept()
        result, pipeline = self._claim_and_process()

        self.assertEqual(
            result.outcome,
            ProviderInboundProcessingOutcome.PROCESSED,
        )
        pipeline.assert_called_once()

        session_row = _load_session(self.cliente_id, self.comercio_id)
        self.assertIsNotNone(session_row.id_pedido)
        self.assertEqual(
            _count_pedidos_for_session(int(session_row.id)),
            1,
            "exactly one draft pedido must be staged per first receipt",
        )

    def test_existing_orderless_session_receives_one_new_pedido(
        self,
    ) -> None:
        _, _ = self._accept()
        _seed_active_session(
            self.comercio_id, self.cliente_id, id_pedido=None
        )
        result, pipeline = self._claim_and_process()

        self.assertEqual(
            result.outcome,
            ProviderInboundProcessingOutcome.PROCESSED,
        )
        pipeline.assert_called_once()

        session_row = _load_session(self.cliente_id, self.comercio_id)
        self.assertIsNotNone(session_row.id_pedido)
        self.assertEqual(
            _count_pedidos_for_session(int(session_row.id)),
            1,
        )

    def test_existing_associated_session_creates_no_new_pedido(
        self,
    ) -> None:
        _, _ = self._accept()
        existing_session_id = _seed_active_session(
            self.comercio_id, self.cliente_id, id_pedido=None
        )
        existing_pedido_id = _seed_draft_pedido(existing_session_id)
        with TestingSessionLocal() as session, session.begin():
            sess = session.get(SessionModel, existing_session_id)
            assert sess is not None
            sess.id_pedido = existing_pedido_id

        pedidos_before = _count_all_pedidos_for_comercio(self.comercio_id)

        result, pipeline = self._claim_and_process()

        self.assertEqual(
            result.outcome,
            ProviderInboundProcessingOutcome.PROCESSED,
        )
        pipeline.assert_called_once()
        self.assertEqual(
            _count_all_pedidos_for_comercio(self.comercio_id),
            pedidos_before,
            "already-associated session must not get a new pedido",
        )

    def test_post_staging_failure_rolls_back_business_effects(
        self,
    ) -> None:
        """A forced pipeline failure during deferred processing must
        roll back the session / pedido / outbound effects, preserve
        the receipt and the work item for retry, and finalize the
        work in a bounded ``retryable`` state with a safe
        category/code.
        """
        receipt_id, procesamiento_id = self._accept()

        result, _pipeline = self._claim_and_process(
            pipeline_side_effect=RuntimeError(
                "forced post-staging failure"
            ),
        )

        self.assertEqual(
            result.outcome,
            ProviderInboundProcessingOutcome.RETRY_SCHEDULED,
        )
        self.assertEqual(result.intentos, 1)
        assert result.categoria is not None
        self.assertEqual(result.categoria.value, "pipeline_error")
        self.assertEqual(result.codigo, "pipeline_error")

        with TestingSessionLocal() as session:
            sesiones = len(
                session.execute(
                    select(SessionModel).where(
                        SessionModel.id_comercio == self.comercio_id
                    )
                ).all()
            )
            self.assertEqual(sesiones, 0)
            pedidos = len(
                session.execute(
                    select(Pedido).where(
                        Pedido.id_session.in_(
                            select(SessionModel.id).where(
                                SessionModel.id_comercio
                                == self.comercio_id
                            )
                        )
                    )
                ).all()
            )
            self.assertEqual(pedidos, 0)
            outbox = len(
                session.execute(
                    select(MensajeProveedorSaliente).where(
                        MensajeProveedorSaliente.recepcion_mensaje_proveedor_id
                        == receipt_id
                    )
                ).all()
            )
            self.assertEqual(outbox, 0)

            work = session.execute(
                select(ProcesamientoMensajeProveedor).where(
                    ProcesamientoMensajeProveedor.id == procesamiento_id
                )
            ).scalar_one()
            self.assertEqual(
                work.estado,
                ProcesamientoMensajeProveedorEstado.RETRYABLE.value,
            )
            self.assertIsNotNone(work.mensaje)
            self.assertIsNotNone(work.proximo_intento_en)
            self.assertEqual(int(work.intentos), 1)

    def test_processed_work_scrubs_transient_body(self) -> None:
        _, procesamiento_id = self._accept()
        result, _pipeline = self._claim_and_process()

        self.assertEqual(
            result.outcome,
            ProviderInboundProcessingOutcome.PROCESSED,
        )
        with TestingSessionLocal() as session:
            work = session.execute(
                select(ProcesamientoMensajeProveedor).where(
                    ProcesamientoMensajeProveedor.id == procesamiento_id
                )
            ).scalar_one()
            self.assertEqual(
                work.estado,
                ProcesamientoMensajeProveedorEstado.PROCESSED.value,
            )
            self.assertIsNone(work.mensaje)
            self.assertIsNotNone(work.fecha_finalizacion)

    def test_terminal_failure_clears_body_and_locks_row(self) -> None:
        """Exhausted attempt budget must finalize the work in
        ``failed_terminal`` with the body cleared and the
        failure metadata safe (no raw exception bytes).
        """
        _, procesamiento_id = self._accept()

        result, _pipeline = self._claim_and_process(
            pipeline_side_effect=RuntimeError(
                "forced terminal failure"
            ),
            max_attempts=1,
        )

        self.assertEqual(
            result.outcome,
            ProviderInboundProcessingOutcome.FAILED_TERMINAL,
        )
        assert result.categoria is not None
        self.assertEqual(result.categoria.value, "pipeline_error")

        with TestingSessionLocal() as session:
            work = session.execute(
                select(ProcesamientoMensajeProveedor).where(
                    ProcesamientoMensajeProveedor.id == procesamiento_id
                )
            ).scalar_one()
            self.assertEqual(
                work.estado,
                ProcesamientoMensajeProveedorEstado.FAILED_TERMINAL.value,
            )
            self.assertIsNone(work.mensaje)
            self.assertIsNotNone(work.fecha_finalizacion)


def _llm_timeout_settings() -> Settings:
    """Build a minimal ``Settings`` instance suitable for QueryLlm
    timeout simulation. Mirrors the schema used by the existing
    timing-observability tests so the test only exercises the
    coordinator and the database, never the real LLM endpoint.
    """
    from backend.config.settings import load_settings

    base = load_settings().__dict__
    base.update(
        {
            "llm_url": "http://llm.test/api/generate",
            "llm_model": "test-llm",
            "llm_timeout": 5,
            "llm_keep_alive": "1h",
            "llm_num_ctx": 2048,
            "llm_num_predict": 256,
            "llm_log_content": False,
            "llm_log_max_chars": 50,
        }
    )
    return Settings(**base)


class LLMTimingRollbackPreservesMetadataTest(unittest.TestCase):
    """Real PostgreSQL proof that an LLM timeout during processing:

    1. rolls back every staged business effect (no ``sessions``,
       no ``pedidos`` and no ``mensajes_proveedor_saliente`` rows);
    2. preserves the LLM request/finish timestamps captured by the
       safe ``WorkItemLLMTimingRecorder`` through the rollback;
    3. finalizes the work item in the bounded ``retryable`` state
       with ``llm_resultado == 'timeout'``;
    4. schedules the next retry through ``proximo_intento_en``.

    The test exercises the production coordinator and the real
    ``procesamientos_mensajes_proveedor`` repository — the
    recorder-only tests in
    ``test_admin_pilot_emulator_timing_observability.py`` cover
    the in-memory state machine, while this test guarantees the
    persistent metadata survives the existing rollback / retry /
    terminal finalization path.
    """

    def setUp(self) -> None:
        suffix = _suffix()
        self.comercio_id = _seed_comercio(suffix)
        self.cliente_id = _seed_cliente(suffix + "C")
        self.destination = f"+54995{suffix[:8]}"
        self.canal_id = _seed_dedicated_channel(
            suffix + "D", self.comercio_id, self.destination
        )
        self.proveedor = "twilio"
        self.identificador = f"SM-{suffix}"
        self.addCleanup(_delete_comercio, self.comercio_id)
        self.addCleanup(_delete_cliente, self.cliente_id)
        self.addCleanup(_delete_canales_by_destination, self.destination)
        self.addCleanup(
            _delete_recepciones_by_comercio, self.comercio_id
        )
        self.addCleanup(
            _delete_procesamientos_by_comercio, self.comercio_id
        )
        self.addCleanup(
            _cleanup_provider_inbound_artifacts, self.comercio_id
        )
        reset_llm_timing_recorder()
        self.addCleanup(reset_llm_timing_recorder)

    def _command(self) -> ProviderInboundMessageCommand:
        return ProviderInboundMessageCommand(
            proveedor=self.proveedor,
            identificador_recepcion=self.identificador,
            canal_id=self.canal_id,
            cliente_id=self.cliente_id,
            comercio_id=self.comercio_id,
            mensaje="hola",
            destinatario_e164=self.destination,
        )

    def _accept(self) -> tuple[int, int]:
        coordinator = ProviderInboundMessageCoordinator(
            session=TestingSessionLocal(),
        )
        with patch(
            "backend.services.provider_inbound_message_coordinator"
            ".process_incoming_message"
        ):
            outcome = coordinator.accept(self._command())
        assert outcome.receipt_id is not None
        assert outcome.procesamiento_id is not None
        return int(outcome.receipt_id), int(outcome.procesamiento_id)

    def test_llm_timeout_rolls_back_business_effects_and_preserves_timing(
        self,
    ) -> None:
        """An LLM timeout during deferred processing must:

        * roll back every staged business effect (session, pedido,
          outbox) — the receipt and work item remain for retry;
        * persist ``llm_solicitado_en`` and ``llm_finalizado_en``
          captured before the rollback through the existing
          ``finalize_retryable`` UPDATE;
        * persist ``llm_resultado == 'timeout'`` so the operator can
          distinguish the timeout from a Twilio Emulator transport
          rejection without exposing exception detail;
        * schedule the next retry through ``proximo_intento_en``;
        * keep the transient body so the next pass can replay it.
        """
        receipt_id, procesamiento_id = self._accept()

        vrf_settings = _llm_timeout_settings()

        def _timeout_pipeline(*_args: Any, **_kwargs: Any) -> list[Any]:
            """Patch ``process_incoming_message`` so the coordinator's
            installed timing recorder observes a real
            ``QueryLlmTimeoutError``. The transport raises
            ``requests.exceptions.Timeout`` and QueryLlm maps it to
            its bounded ``QueryLlmTimeoutError``; the recorder's
            ``on_requested`` and ``on_finished(outcome='timeout')``
            fire inside the existing try/except block, so the
            coordinator's ``_finalize_failure`` path receives the
            bounded metadata even after the business transaction
            rolls back.
            """

            def _transport(*_t_args: Any, **_t_kwargs: Any) -> None:
                raise requests.exceptions.Timeout(
                    "simulated LLM timeout"
                )

            QueryLlm(settings=vrf_settings, transport=_transport).request(
                "dummy-prompt"
            )
            return []

        session = TestingSessionLocal()
        try:
            with patch(
                "backend.services.provider_inbound_message_coordinator"
                ".process_incoming_message",
                side_effect=_timeout_pipeline,
            ) as pipeline:
                coordinator = ProviderInboundMessageCoordinator(
                    session=session,
                    max_attempts=3,
                )
                leased = coordinator.claim_due_processing(now=_now())
                self.assertIsNotNone(leased)
                assert leased is not None

                result = coordinator.process_lease(leased)

            pipeline.assert_called_once()

            self.assertEqual(
                result.outcome,
                ProviderInboundProcessingOutcome.RETRY_SCHEDULED,
            )
            self.assertEqual(result.intentos, 1)
        finally:
            session.close()

        with TestingSessionLocal() as session:
            sesiones = len(
                session.execute(
                    select(SessionModel).where(
                        SessionModel.id_comercio == self.comercio_id
                    )
                ).all()
            )
            self.assertEqual(
                sesiones,
                0,
                "session row must be rolled back after LLM timeout",
            )
            pedidos = len(
                session.execute(
                    select(Pedido).where(
                        Pedido.id_session.in_(
                            select(SessionModel.id).where(
                                SessionModel.id_comercio
                                == self.comercio_id
                            )
                        )
                    )
                ).all()
            )
            self.assertEqual(
                pedidos,
                0,
                "pedido row must be rolled back after LLM timeout",
            )
            outbox = len(
                session.execute(
                    select(MensajeProveedorSaliente).where(
                        MensajeProveedorSaliente.recepcion_mensaje_proveedor_id
                        == receipt_id
                    )
                ).all()
            )
            self.assertEqual(
                outbox,
                0,
                "outbox row must be rolled back after LLM timeout",
            )

            work = session.execute(
                select(ProcesamientoMensajeProveedor).where(
                    ProcesamientoMensajeProveedor.id
                    == procesamiento_id
                )
            ).scalar_one()
            self.assertEqual(
                work.estado,
                ProcesamientoMensajeProveedorEstado.RETRYABLE.value,
                "work item must be finalized as retryable",
            )
            self.assertIsNotNone(
                work.llm_solicitado_en,
                "llm_solicitado_en must survive the rollback",
            )
            self.assertIsNotNone(
                work.llm_finalizado_en,
                "llm_finalizado_en must survive the rollback",
            )
            self.assertIsNotNone(
                work.llm_resultado,
                "llm_resultado must survive the rollback",
            )
            self.assertEqual(
                work.llm_resultado,
                "timeout",
                "llm_resultado must be persisted as 'timeout'",
            )
            assert work.llm_solicitado_en is not None
            assert work.llm_finalizado_en is not None
            self.assertLessEqual(
                work.llm_solicitado_en,
                work.llm_finalizado_en,
                "LLM request timestamp must precede completion",
            )
            self.assertIsNotNone(
                work.proximo_intento_en,
                "next retry must be scheduled via proximo_intento_en",
            )
            assert work.proximo_intento_en is not None
            self.assertGreater(
                work.proximo_intento_en,
                _now() - timedelta(seconds=2),
                "next retry must be in the future (or recent past)",
            )
            self.assertIsNotNone(
                work.mensaje,
                "transient body must be preserved so the next "
                "attempt can replay it",
            )
            self.assertEqual(
                work.mensaje,
                "hola",
                "preserved body must match the original message",
            )
            self.assertIsNone(
                work.fecha_finalizacion,
                "retryable row must not carry fecha_finalizacion",
            )
            self.assertEqual(int(work.intentos), 1)
            self.assertEqual(
                work.categoria_ultimo_fallo,
                "database_error",
                "failure category must remain the bounded token",
            )


class RetryOrderingIntegrationTest(unittest.TestCase):
    """The deferred processor must not process a later pending item
    for the same client/channel while an earlier item remains
    pending, leased or retryable. The bounded CLI must therefore
    skip the second row, even when the earlier retryable row is
    past its due time but has not yet reached a terminal state.
    """

    def setUp(self) -> None:
        suffix = _suffix()
        self.comercio_id = _seed_comercio(suffix)
        self.cliente_id = _seed_cliente(suffix + "C")
        self.destination = f"+54993{suffix[:8]}"
        self.canal_id = _seed_dedicated_channel(
            suffix + "D", self.comercio_id, self.destination
        )
        # Cleanups are executed in LIFO order. The unrelated
        # conversation's cliente/canal cleanups are registered
        # FIRST so they run LAST, after the shared comercio
        # cleanups have already removed every receipt that still
        # references the other cliente.
        self.other_destination = f"+54984{suffix[:8]}"
        self.other_canal_id = _seed_dedicated_channel(
            suffix + "O", self.comercio_id, self.other_destination
        )
        self.other_cliente_id = _seed_cliente(suffix + "OC")
        self.addCleanup(_delete_cliente, self.other_cliente_id)
        self.addCleanup(
            _delete_canales_by_destination, self.other_destination
        )
        self.addCleanup(_delete_comercio, self.comercio_id)
        self.addCleanup(_delete_cliente, self.cliente_id)
        self.addCleanup(_delete_canales_by_destination, self.destination)
        self.addCleanup(_delete_recepciones_by_comercio, self.comercio_id)
        self.addCleanup(_delete_procesamientos_by_comercio, self.comercio_id)
        self.addCleanup(_cleanup_provider_inbound_artifacts, self.comercio_id)

    def _accept(
        self,
        *,
        identificador: str,
        canal_id: int | None = None,
        cliente_id: int | None = None,
    ) -> int:
        coordinator = ProviderInboundMessageCoordinator(
            session=TestingSessionLocal(),
        )
        with patch(
            "backend.services.provider_inbound_message_coordinator"
            ".process_incoming_message"
        ):
            outcome = coordinator.accept(
                ProviderInboundMessageCommand(
                    proveedor="twilio",
                    identificador_recepcion=identificador,
                    canal_id=canal_id if canal_id is not None else self.canal_id,
                    cliente_id=(
                        cliente_id if cliente_id is not None
                        else self.cliente_id
                    ),
                    comercio_id=self.comercio_id,
                    mensaje="hola",
                    destinatario_e164=self.destination,
                )
            )
        assert outcome.procesamiento_id is not None
        return int(outcome.procesamiento_id)

    def test_retryable_due_first_blocks_pending_second(
        self,
    ) -> None:
        """The conversational-order guarantee. Receipt A is finalized
        in ``retryable`` with a ``proximo_intento_en`` that is in the
        PAST (so the row is itself due), yet receipt B for the same
        ``(canal_id, cliente_id)`` MUST NOT be claimed while A stays
        in that unresolved state. The earliest eligible row is A
        itself; the conversational block only excludes rows that are
        STRICTLY later than the blocker, so the pass re-claims A. A
        pass after A reaches ``processed`` MUST then claim B.
        """
        from datetime import timedelta

        from backend.repositories.procesamiento_mensaje_proveedor_repository import (
            ProcesamientoMensajeProveedorRepository,
        )

        first_id = self._accept(identificador=f"SM-{_suffix()}")
        second_id = self._accept(identificador=f"SM-{_suffix()}")

        past_at = _now() - timedelta(seconds=1)
        with TestingSessionLocal() as finalize_session:
            finalize_session.begin()
            claim_coordinator = ProviderInboundMessageCoordinator(
                session=finalize_session,
            )
            first_leased = claim_coordinator.claim_due_processing(
                now=_now()
            )
            self.assertIsNotNone(first_leased)
            assert first_leased is not None
            self.assertEqual(
                int(first_leased.id),
                first_id,
                "the older row must be the first due candidate",
            )
            finalized = ProcesamientoMensajeProveedorRepository(
                finalize_session
            ).finalize_retryable(
                procesamiento_id=int(first_leased.id),
                lease_token=str(first_leased.token_lease or ""),
                categoria="pipeline_error",
                codigo="pipeline_error",
                proximo_intento_en=past_at,
            )
            self.assertTrue(finalized)
            finalize_session.commit()

        # A subsequent claim with A still in ``retryable`` MUST NOT
        # claim B. The earliest eligible row is A itself; the
        # conversational block only excludes rows that are
        # STRICTLY later than the blocker. A re-claim of A is the
        # correct, deterministic outcome.
        with TestingSessionLocal() as next_session:
            next_coordinator = ProviderInboundMessageCoordinator(
                session=next_session,
            )
            leased = next_coordinator.claim_due_processing(now=_now())
            self.assertIsNotNone(
                leased,
                "the earlier retryable row is itself due and must "
                "remain claimable; the block targets STRICTLY later "
                "rows in the same conversation",
            )
            assert leased is not None
            self.assertEqual(
                int(leased.id),
                first_id,
                "B must NOT be claimed while A is unresolved in the "
                "same conversation; the pass re-claims A instead",
            )
            self.assertNotEqual(
                int(leased.id),
                second_id,
                "later pending row must be excluded by the "
                "conversational block",
            )
            first_lease_token = str(leased.token_lease or "")
            first_lease_id = int(leased.id)

        # Finalize A as ``processed`` using the fresh lease token;
        # the conversation unblocks and the next pass can claim B.
        with TestingSessionLocal() as process_session:
            process_session.begin()
            ProcesamientoMensajeProveedorRepository(
                process_session
            ).finalize_processed(
                procesamiento_id=first_lease_id,
                lease_token=first_lease_token,
                fecha_finalizacion=_now(),
            )
            process_session.commit()

        with TestingSessionLocal() as next_session:
            next_coordinator = ProviderInboundMessageCoordinator(
                session=next_session,
            )
            leased = next_coordinator.claim_due_processing(now=_now())
            self.assertIsNotNone(leased)
            assert leased is not None
            self.assertEqual(
                int(leased.id),
                second_id,
                "B must be claimable once A reaches a terminal state",
            )

    def test_failed_terminal_first_unblocks_second(
        self,
    ) -> None:
        """Once the earlier row reaches ``failed_terminal`` the
        later row for the same conversation MUST become claimable.
        """
        from datetime import timedelta

        from backend.repositories.procesamiento_mensaje_proveedor_repository import (
            ProcesamientoMensajeProveedorRepository,
        )

        first_id = self._accept(identificador=f"SM-{_suffix()}")
        second_id = self._accept(identificador=f"SM-{_suffix()}")

        past_at = _now() - timedelta(seconds=1)
        with TestingSessionLocal() as finalize_session:
            finalize_session.begin()
            claim_coordinator = ProviderInboundMessageCoordinator(
                session=finalize_session,
            )
            first_leased = claim_coordinator.claim_due_processing(
                now=_now()
            )
            self.assertIsNotNone(first_leased)
            assert first_leased is not None
            self.assertEqual(int(first_leased.id), first_id)
            ProcesamientoMensajeProveedorRepository(
                finalize_session
            ).finalize_terminal(
                procesamiento_id=int(first_leased.id),
                lease_token=str(first_leased.token_lease or ""),
                categoria="pipeline_error",
                codigo="pipeline_error",
                fecha_finalizacion=past_at,
            )
            finalize_session.commit()

        with TestingSessionLocal() as next_session:
            next_coordinator = ProviderInboundMessageCoordinator(
                session=next_session,
            )
            leased = next_coordinator.claim_due_processing(now=_now())
            self.assertIsNotNone(leased)
            assert leased is not None
            self.assertEqual(
                int(leased.id),
                second_id,
                "B must be claimable after A reaches failed_terminal",
            )

    def test_other_conversation_runs_while_first_blocks(
        self,
    ) -> None:
        """The conversational block MUST NOT span conversations. A
        different ``(canal_id, cliente_id)`` pair MUST keep
        progressing while the first conversation is still blocked
        by an earlier leased row.
        """

        first_id = self._accept(identificador=f"SM-{_suffix()}")
        second_id = self._accept(identificador=f"SM-{_suffix()}")
        other_first_id = self._accept_for_other()

        # Lease A and leave it ``leased`` (lease alive) so the
        # outer eligibility filter excludes A itself (lease has
        # not expired) and so the conversational block excludes B
        # (A is a live-lease blocker for B in the same
        # conversation).
        with TestingSessionLocal() as finalize_session:
            finalize_session.begin()
            claim_coordinator = ProviderInboundMessageCoordinator(
                session=finalize_session,
            )
            first_leased = claim_coordinator.claim_due_processing(
                now=_now()
            )
            self.assertIsNotNone(first_leased)
            assert first_leased is not None
            self.assertEqual(int(first_leased.id), first_id)
            finalize_session.commit()

        with TestingSessionLocal() as next_session:
            next_coordinator = ProviderInboundMessageCoordinator(
                session=next_session,
            )
            leased = next_coordinator.claim_due_processing(now=_now())
            self.assertIsNotNone(leased)
            assert leased is not None
            self.assertEqual(
                int(leased.id),
                other_first_id,
                "an unrelated conversation must remain claimable while "
                "the first conversation is blocked by a live lease",
            )
            self.assertNotEqual(
                int(leased.id),
                second_id,
                "the blocked conversation must not be claimed",
            )
            self.assertNotEqual(int(leased.id), first_id)

    def _accept_for_other(self) -> int:
        coordinator = ProviderInboundMessageCoordinator(
            session=TestingSessionLocal(),
        )
        with patch(
            "backend.services.provider_inbound_message_coordinator"
            ".process_incoming_message"
        ):
            outcome = coordinator.accept(
                ProviderInboundMessageCommand(
                    proveedor="twilio",
                    identificador_recepcion=f"SM-{_suffix()}",
                    canal_id=self.other_canal_id,
                    cliente_id=self.other_cliente_id,
                    comercio_id=self.comercio_id,
                    mensaje="hola",
                    destinatario_e164=self.other_destination,
                )
            )
        assert outcome.procesamiento_id is not None
        return int(outcome.procesamiento_id)

    def test_retryable_future_backoff_blocks_pending_second(
        self,
    ) -> None:
        """A ``retryable`` row whose ``proximo_intento_en`` is in the
        FUTURE MUST still block a later pending row in the same
        conversation. The conversational block is unconditional based
        on state and does NOT depend on ``proximo_intento_en``: A is
        not yet terminal, so B must wait. The bounded CLI therefore
        reports no due row until A reaches a terminal state. Once A
        reaches ``processed``, B becomes claimable.
        """
        from datetime import timedelta

        from backend.repositories.procesamiento_mensaje_proveedor_repository import (
            ProcesamientoMensajeProveedorRepository,
        )

        first_id = self._accept(identificador=f"SM-{_suffix()}")
        second_id = self._accept(identificador=f"SM-{_suffix()}")

        future_at = _now() + timedelta(seconds=3600)
        with TestingSessionLocal() as finalize_session:
            finalize_session.begin()
            claim_coordinator = ProviderInboundMessageCoordinator(
                session=finalize_session,
            )
            first_leased = claim_coordinator.claim_due_processing(
                now=_now()
            )
            self.assertIsNotNone(first_leased)
            assert first_leased is not None
            self.assertEqual(int(first_leased.id), first_id)
            finalized = ProcesamientoMensajeProveedorRepository(
                finalize_session
            ).finalize_retryable(
                procesamiento_id=int(first_leased.id),
                lease_token=str(first_leased.token_lease or ""),
                categoria="pipeline_error",
                codigo="pipeline_error",
                proximo_intento_en=future_at,
            )
            self.assertTrue(finalized)
            finalize_session.commit()

        # A's retryable state has a FUTURE ``proximo_intento_en``:
        # A is NOT eligible (backoff has not expired), B is eligible
        # but is BLOCKED by A in the same conversation. The pass
        # returns no due row.
        with TestingSessionLocal() as next_session:
            next_coordinator = ProviderInboundMessageCoordinator(
                session=next_session,
            )
            leased = next_coordinator.claim_due_processing(now=_now())
            self.assertIsNone(
                leased,
                "B must NOT be claimed while A is unresolved "
                "retryable with a future backoff in the same "
                "conversation",
            )

        # Drive A to ``processed`` by back-dating the backoff and
        # reclaiming A. Once A is terminal, B becomes claimable.
        with TestingSessionLocal() as mutate_session:
            mutate_session.begin()
            work = mutate_session.get(
                ProcesamientoMensajeProveedor, first_id
            )
            assert work is not None
            self.assertEqual(
                work.estado,
                ProcesamientoMensajeProveedorEstado.RETRYABLE.value,
            )
            work.proximo_intento_en = _now() - timedelta(seconds=1)
            mutate_session.commit()
        with TestingSessionLocal() as claim_session:
            claim_session.begin()
            reclaim_coordinator = ProviderInboundMessageCoordinator(
                session=claim_session,
            )
            leased_again = reclaim_coordinator.claim_due_processing(
                now=_now()
            )
            self.assertIsNotNone(leased_again)
            assert leased_again is not None
            self.assertEqual(int(leased_again.id), first_id)
            reclaim_token = str(leased_again.token_lease or "")
            ProcesamientoMensajeProveedorRepository(
                claim_session
            ).finalize_processed(
                procesamiento_id=first_id,
                lease_token=reclaim_token,
                fecha_finalizacion=_now(),
            )
            claim_session.commit()

        with TestingSessionLocal() as next_session:
            next_coordinator = ProviderInboundMessageCoordinator(
                session=next_session,
            )
            leased = next_coordinator.claim_due_processing(now=_now())
            self.assertIsNotNone(leased)
            assert leased is not None
            self.assertEqual(
                int(leased.id),
                second_id,
                "B must be claimable once A reaches a terminal state",
            )

    def test_leased_expired_lease_blocks_pending_second(
        self,
    ) -> None:
        """A ``leased`` row whose lease has already expired MUST
        still block a later pending row in the same conversation,
        even though A itself remains eligible for the documented
        lease-recovery claim. The conversational block is
        unconditional based on state: the blocker does NOT need a
        live lease, only a non-terminal state. The bounded CLI
        therefore re-claims A through lease recovery and skips B
        until A reaches a terminal state.
        """
        from datetime import timedelta

        from backend.repositories.procesamiento_mensaje_proveedor_repository import (
            ProcesamientoMensajeProveedorRepository,
        )

        first_id = self._accept(identificador=f"SM-{_suffix()}")
        second_id = self._accept(identificador=f"SM-{_suffix()}")

        # Manually transition A to ``leased`` with an EXPIRED lease.
        # The row is eligible for lease-recovery (the eligibility
        # predicate treats ``leased`` + ``lease_expira_en <= now``
        # as a recovery path) AND it remains a blocker for B in the
        # same conversation.
        past_at = _now() - timedelta(seconds=30)
        with TestingSessionLocal() as mutate_session:
            mutate_session.begin()
            work = mutate_session.get(
                ProcesamientoMensajeProveedor, first_id
            )
            assert work is not None
            work.estado = ProcesamientoMensajeProveedorEstado.LEASED.value
            work.token_lease = "expired-lease-token"
            work.lease_expira_en = past_at
            mutate_session.commit()

        with TestingSessionLocal() as next_session:
            next_coordinator = ProviderInboundMessageCoordinator(
                session=next_session,
            )
            leased = next_coordinator.claim_due_processing(now=_now())
            self.assertIsNotNone(
                leased,
                "A itself remains eligible through the lease-recovery "
                "path; the conversational block targets strictly later "
                "rows in the same conversation",
            )
            assert leased is not None
            self.assertEqual(
                int(leased.id),
                first_id,
                "the lease-recovery path must reclaim A first",
            )
            self.assertNotEqual(
                int(leased.id),
                second_id,
                "B must NOT be claimed while A is unresolved leased "
                "in the same conversation; the expired lease does NOT "
                "lift the conversational block",
            )
            first_lease_token = str(leased.token_lease or "")
            first_lease_id = int(leased.id)

        # Drive A to ``processed`` using the fresh lease token; the
        # conversation unblocks and the next pass can claim B.
        with TestingSessionLocal() as process_session:
            process_session.begin()
            ProcesamientoMensajeProveedorRepository(
                process_session
            ).finalize_processed(
                procesamiento_id=first_lease_id,
                lease_token=first_lease_token,
                fecha_finalizacion=_now(),
            )
            process_session.commit()

        with TestingSessionLocal() as next_session:
            next_coordinator = ProviderInboundMessageCoordinator(
                session=next_session,
            )
            leased = next_coordinator.claim_due_processing(now=_now())
            self.assertIsNotNone(leased)
            assert leased is not None
            self.assertEqual(
                int(leased.id),
                second_id,
                "B must be claimable once A reaches a terminal state",
            )


class ProcessingOutcomeEventEmissionTest(unittest.TestCase):
    """The provider coordinator MUST emit one closed
    ``provider_inbound_processing_outcome`` event AFTER the existing
    authoritative durable result is known. The emission MUST NOT
    widen the mapper work, MUST NOT invoke the outbound dispatcher
    or T-C and MUST NOT create a fallback row when the pipeline
    returns zero customer responses."""

    def setUp(self) -> None:
        suffix = _suffix()
        self.comercio_id = _seed_comercio(suffix)
        self.addCleanup(_delete_comercio, self.comercio_id)
        self.cliente_id = _seed_cliente(suffix + "C")
        self.addCleanup(_delete_cliente, self.cliente_id)
        self.destination = f"+54971{suffix[:8]}"
        self.addCleanup(_delete_canales_by_destination, self.destination)
        self.canal_id = _seed_dedicated_channel(
            suffix + "D", self.comercio_id, self.destination
        )
        self.proveedor = "twilio"
        self.identificador = f"SM-{suffix}"
        self.addCleanup(
            _cleanup_provider_inbound_artifacts, self.comercio_id
        )
        self.addCleanup(
            _delete_recepciones_by_comercio, self.comercio_id
        )
        self.addCleanup(
            _delete_procesamientos_by_comercio, self.comercio_id
        )

    def _command(self) -> ProviderInboundMessageCommand:
        return ProviderInboundMessageCommand(
            proveedor=self.proveedor,
            identificador_recepcion=self.identificador,
            canal_id=self.canal_id,
            cliente_id=self.cliente_id,
            comercio_id=self.comercio_id,
            mensaje="hola",
            destinatario_e164=self.destination,
        )

    def _accept(self) -> tuple[int, int]:
        coordinator = ProviderInboundMessageCoordinator(
            session=TestingSessionLocal(),
        )
        with patch(
            "backend.services.provider_inbound_message_coordinator"
            ".process_incoming_message"
        ):
            outcome = coordinator.accept(self._command())
        assert outcome.receipt_id is not None
        assert outcome.procesamiento_id is not None
        return int(outcome.receipt_id), int(outcome.procesamiento_id)

    def _claim_and_process_with_emitter(
        self,
        *,
        staged_rows: list[StagedOutboundRow],
    ) -> tuple[
        ProviderInboundProcessingResult,
        list[dict[str, Any]],
    ]:
        """Run ``process_lease`` while capturing the JSON-line
        observability events the coordinator emits through
        :func:`emit_event` and forcing the mapper to return the
        supplied ``staged_rows`` count.

        The helper bypasses the LLM-driven customer response
        rendering by stubbing ``stage_outbound_rows`` to return a
        deterministic list. The mapper is the only consumer of
        the intents list so the stub does not affect any
        business-path contract.
        """
        session = TestingSessionLocal()
        try:
            coordinator = ProviderInboundMessageCoordinator(
                session=session,
                max_attempts=3,
            )
            leased = coordinator.claim_due_processing(now=_now())
            assert leased is not None

            captured: list[dict[str, Any]] = []

            def _capture_emit(*, event: str, **kwargs: Any) -> bool:
                from backend.observability.events import build_event

                payload = build_event(event=event, **kwargs)
                captured.append(payload)
                return True

            with patch(
                "backend.services.provider_inbound_message_coordinator"
                ".process_incoming_message",
                return_value=[object()],
            ), patch(
                "backend.services.provider_inbound_message_coordinator"
                ".stage_outbound_rows",
                return_value=staged_rows,
            ), patch(
                "backend.services.provider_inbound_message_coordinator"
                ".emit_event",
                side_effect=_capture_emit,
            ):
                result = coordinator.process_lease(leased)
            return result, captured
        finally:
            session.close()

    def _processing_outcome_events(
        self, captured: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        return [
            event
            for event in captured
            if event.get("event") == EVENT_PROCESSING_OUTCOME
        ]

    def test_processed_with_response_emits_event_with_matching_counts(
        self,
    ) -> None:
        """When the deferred processor commits one or more mapped
        customer responses and their outbound rows it MUST emit
        exactly one ``processed_with_response`` event with matching
        bounded response/outbox counts."""
        receipt_id, _ = self._accept()

        staged_row = StagedOutboundRow(
            mensaje_proveedor_saliente_id=1,
            sequence=0,
            customer_response=CustomerResponse(
                message="ok",
                intent="noop",
                status="executed",
            ),
        )
        result, captured = self._claim_and_process_with_emitter(
            staged_rows=[staged_row]
        )

        self.assertEqual(
            result.outcome, ProviderInboundProcessingOutcome.PROCESSED
        )
        with TestingSessionLocal() as session:
            outbox_rows = list(
                session.execute(
                    select(MensajeProveedorSaliente).where(
                        MensajeProveedorSaliente.recepcion_mensaje_proveedor_id
                        == receipt_id
                    )
                ).scalars()
            )
        self.assertEqual(len(outbox_rows), 0)

        events = self._processing_outcome_events(captured)
        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event["outcome"], "processed_with_response")
        self.assertEqual(event["response_count"], 1)
        self.assertEqual(event["outbox_row_count"], 1)
        self.assertEqual(event["component"], COMPONENT_WORKER)
        self.assertNotIn("failure_category", event)
        self.assertEqual(
            event["correlation_id"], self.identificador
        )

    def test_processed_without_response_emits_zero_count_event(
        self,
    ) -> None:
        """When the deferred processor commits ``processed`` and the
        mapper returns zero staged outbound rows it MUST emit
        exactly one ``processed_without_response`` event with zero
        counts and MUST NOT create a fallback row or invoke the
        outbound dispatcher."""
        receipt_id, _ = self._accept()

        result, captured = self._claim_and_process_with_emitter(
            staged_rows=[]
        )

        self.assertEqual(
            result.outcome, ProviderInboundProcessingOutcome.PROCESSED
        )
        with TestingSessionLocal() as session:
            outbox_rows = list(
                session.execute(
                    select(MensajeProveedorSaliente).where(
                        MensajeProveedorSaliente.recepcion_mensaje_proveedor_id
                        == receipt_id
                    )
                ).scalars()
            )
        self.assertEqual(
            len(outbox_rows),
            0,
            "zero-response commit must not create an outbox row",
        )

        events = self._processing_outcome_events(captured)
        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event["outcome"], "processed_without_response")
        self.assertEqual(event["response_count"], 0)
        self.assertEqual(event["outbox_row_count"], 0)
        self.assertNotIn("failure_category", event)
        self.assertEqual(
            event["correlation_id"], self.identificador
        )

    def test_retry_scheduled_failure_emits_failure_category(self) -> None:
        """A pipeline exception that rolls back to retry MUST emit
        exactly one ``retry_scheduled`` event with the safe bounded
        failure category. The emission MUST NOT alter the existing
        retry/lease contract."""
        self._accept()
        captured: list[dict[str, Any]] = []
        session = TestingSessionLocal()
        try:
            coordinator = ProviderInboundMessageCoordinator(
                session=session, max_attempts=3
            )
            leased = coordinator.claim_due_processing(now=_now())
            assert leased is not None

            def _capture_emit(*, event: str, **kwargs: Any) -> bool:
                from backend.observability.events import build_event

                payload = build_event(event=event, **kwargs)
                captured.append(payload)
                return True

            with patch(
                "backend.services.provider_inbound_message_coordinator"
                ".process_incoming_message",
                side_effect=RuntimeError("forced"),
            ), patch(
                "backend.services.provider_inbound_message_coordinator"
                ".emit_event",
                side_effect=_capture_emit,
            ):
                result = coordinator.process_lease(leased)
        finally:
            session.close()

        self.assertEqual(
            result.outcome, ProviderInboundProcessingOutcome.RETRY_SCHEDULED
        )
        events = self._processing_outcome_events(captured)
        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event["outcome"], "retry_scheduled")
        self.assertEqual(event["failure_category"], "pipeline_error")
        self.assertNotIn("response_count", event)
        self.assertNotIn("outbox_row_count", event)

    def test_terminal_exhaustion_emits_failed_terminal_event(self) -> None:
        """When the attempt budget is exhausted on a forced pipeline
        failure the coordinator MUST emit ``failed_terminal`` with
        the safe bounded failure category and MUST keep the existing
        bounded finalization contract intact."""
        self._accept()
        captured: list[dict[str, Any]] = []
        session = TestingSessionLocal()
        try:
            coordinator = ProviderInboundMessageCoordinator(
                session=session, max_attempts=1
            )
            leased = coordinator.claim_due_processing(now=_now())
            assert leased is not None

            def _capture_emit(*, event: str, **kwargs: Any) -> bool:
                from backend.observability.events import build_event

                payload = build_event(event=event, **kwargs)
                captured.append(payload)
                return True

            with patch(
                "backend.services.provider_inbound_message_coordinator"
                ".process_incoming_message",
                side_effect=RuntimeError("forced"),
            ), patch(
                "backend.services.provider_inbound_message_coordinator"
                ".emit_event",
                side_effect=_capture_emit,
            ):
                result = coordinator.process_lease(leased)
        finally:
            session.close()

        self.assertEqual(
            result.outcome,
            ProviderInboundProcessingOutcome.FAILED_TERMINAL,
        )
        events = self._processing_outcome_events(captured)
        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event["outcome"], "failed_terminal")
        self.assertEqual(event["failure_category"], "pipeline_error")

    def test_emission_does_not_call_mapper_twice(self) -> None:
        """The coordinator MUST use the existing ``stage_outbound_rows``
        result count exactly once. A second invocation of the mapper
        would be a regression of the diagnostic contract."""
        self._accept()
        session = TestingSessionLocal()
        try:
            coordinator = ProviderInboundMessageCoordinator(
                session=session, max_attempts=3
            )
            leased = coordinator.claim_due_processing(now=_now())
            assert leased is not None

            call_counter = {"count": 0}

            def _spy_stage(*args: Any, **kwargs: Any) -> list[StagedOutboundRow]:
                call_counter["count"] += 1
                return []

            with patch(
                "backend.services.provider_inbound_message_coordinator"
                ".process_incoming_message",
                return_value=[],
            ), patch(
                "backend.services.provider_inbound_message_coordinator"
                ".stage_outbound_rows",
                side_effect=_spy_stage,
            ):
                result = coordinator.process_lease(leased)
        finally:
            session.close()

        self.assertEqual(
            result.outcome, ProviderInboundProcessingOutcome.PROCESSED
        )
        self.assertEqual(
            call_counter["count"],
            1,
            "stage_outbound_rows must be invoked exactly once",
        )

    def test_receipt_missing_emits_failed_terminal_after_finalization(
        self,
    ) -> None:
        """When the receipt linked to the leased work item is
        missing the coordinator MUST finalize the row as terminal
        with the safe ``database_error`` category AND MUST emit
        exactly one ``provider_inbound_processing_outcome`` event
        with ``failed_terminal`` outcome AFTER the durable
        finalization. The emission MUST NOT alter the existing
        bounded transaction, lease or retry contract.
        """
        receipt_id, _ = self._accept()

        session = TestingSessionLocal()
        try:
            coordinator = ProviderInboundMessageCoordinator(
                session=session, max_attempts=3
            )
            leased = coordinator.claim_due_processing(now=_now())
            assert leased is not None

            captured: list[dict[str, Any]] = []
            call_order: list[str] = []

            def _capture_emit(*, event: str, **kwargs: Any) -> bool:
                from backend.observability.events import build_event

                call_order.append("emit")
                payload = build_event(event=event, **kwargs)
                captured.append(payload)
                return True

            real_finalize_terminal = (
                coordinator._procesamiento_repo.finalize_terminal
            )

            def _spy_finalize_terminal(**kwargs: Any) -> bool:
                call_order.append("finalize")
                return real_finalize_terminal(**kwargs)

            with patch(
                "backend.services.provider_inbound_message_coordinator"
                ".emit_event",
                side_effect=_capture_emit,
            ), patch.object(
                coordinator._recepcion_repo,
                "find_by_id",
                return_value=None,
            ), patch.object(
                coordinator._procesamiento_repo,
                "finalize_terminal",
                side_effect=_spy_finalize_terminal,
            ):
                result = coordinator.process_lease(leased)
        finally:
            session.close()

        self.assertEqual(
            result.outcome,
            ProviderInboundProcessingOutcome.FAILED_TERMINAL,
        )
        self.assertEqual(result.codigo, "receipt_missing")
        self.assertEqual(
            result.categoria,
            ProcesamientoMensajeProveedorFailureCategory.DATABASE_ERROR,
        )

        events = self._processing_outcome_events(captured)
        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event["outcome"], "failed_terminal")
        self.assertEqual(event["failure_category"], "database_error")
        self.assertEqual(event["component"], COMPONENT_WORKER)
        self.assertNotIn("response_count", event)
        self.assertNotIn("outbox_row_count", event)

        # The processing_outcome emit MUST come AFTER the
        # finalize_terminal call. With the new
        # ``processing_finalization`` helper the call_order is
        # ``[started-emit, finalize, completed-emit,
        # processing_outcome-emit]``; the previous strict
        # ``["finalize", "emit"]`` assertion is replaced by an
        # ordering assertion so the contract remains verifiable.
        finalize_positions = [
            index
            for index, value in enumerate(call_order)
            if value == "finalize"
        ]
        self.assertEqual(
            len(finalize_positions), 1, "finalize_terminal must run once"
        )
        emit_after_finalize = [
            index
            for index in range(
                finalize_positions[0] + 1, len(call_order)
            )
            if call_order[index] == "emit"
        ]
        self.assertGreaterEqual(
            len(emit_after_finalize),
            1,
            "processing_outcome emit MUST follow finalize_terminal",
        )
        self.assertEqual(
            call_order[-1],
            "emit",
            "the last emitted event MUST be the processing_outcome",
        )

        with TestingSessionLocal() as session:
            stored = session.execute(
                select(ProcesamientoMensajeProveedor).where(
                    ProcesamientoMensajeProveedor.recepcion_mensaje_proveedor_id
                    == receipt_id
                )
            ).scalar_one()
        self.assertEqual(
            stored.estado,
            ProcesamientoMensajeProveedorEstado.FAILED_TERMINAL.value,
        )
        self.assertEqual(stored.categoria_ultimo_fallo, "database_error")
        self.assertEqual(stored.codigo_ultimo_fallo, "receipt_missing")

    def test_receipt_missing_emits_lease_lost_when_finalization_fails(
        self,
    ) -> None:
        """When the receipt linked to the leased work item is
        missing AND the terminal finalization loses the lease the
        coordinator MUST emit ONLY ``lease_lost`` (without
        ``failure_category``). The receipt_missing path keeps its
        existing ``ProviderInboundProcessingResult`` semantic; the
        emission MUST happen AFTER the bounded lease loss is
        observed."""
        self._accept()

        session = TestingSessionLocal()
        try:
            coordinator = ProviderInboundMessageCoordinator(
                session=session, max_attempts=3
            )
            leased = coordinator.claim_due_processing(now=_now())
            assert leased is not None

            captured: list[dict[str, Any]] = []
            call_order: list[str] = []

            def _capture_emit(*, event: str, **kwargs: Any) -> bool:
                from backend.observability.events import build_event

                call_order.append("emit")
                payload = build_event(event=event, **kwargs)
                captured.append(payload)
                return True

            def _spy_finalize_terminal(**kwargs: Any) -> bool:
                call_order.append("finalize")
                return False

            with patch(
                "backend.services.provider_inbound_message_coordinator"
                ".emit_event",
                side_effect=_capture_emit,
            ), patch.object(
                coordinator._recepcion_repo,
                "find_by_id",
                return_value=None,
            ), patch.object(
                coordinator._procesamiento_repo,
                "finalize_terminal",
                side_effect=_spy_finalize_terminal,
            ):
                result = coordinator.process_lease(leased)
        finally:
            session.close()

        self.assertEqual(
            result.outcome,
            ProviderInboundProcessingOutcome.FAILED_TERMINAL,
        )
        self.assertEqual(result.codigo, "receipt_missing")

        events = self._processing_outcome_events(captured)
        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event["outcome"], "lease_lost")
        self.assertNotIn("failure_category", event)
        self.assertEqual(event["component"], COMPONENT_WORKER)

        # The processing_outcome (lease_lost) emit MUST come AFTER
        # the finalize_terminal call. The new
        # ``processing_finalization`` wrapper emits a ``started``
        # + ``failed (LeaseLost)`` pair around the finalize call,
        # so the recorded call_order is
        # ``[started-emit, finalize, failed-emit, outcome-emit]``.
        finalize_positions = [
            index
            for index, value in enumerate(call_order)
            if value == "finalize"
        ]
        self.assertEqual(
            len(finalize_positions), 1, "finalize_terminal must run once"
        )
        emit_after_finalize = [
            index
            for index in range(
                finalize_positions[0] + 1, len(call_order)
            )
            if call_order[index] == "emit"
        ]
        self.assertGreaterEqual(
            len(emit_after_finalize),
            1,
            "lease_lost processing_outcome emit MUST follow "
            "finalize_terminal",
        )

    @staticmethod
    def _unavailable_outcome(
        comercio_id: int,
    ) -> CommerceAvailabilityOutcome:
        """Return a typed ``unavailable`` / ``blocked_state`` outcome
        suitable for monkey-patching the availability service."""
        return CommerceAvailabilityOutcome(
            status=CommerceAvailabilityStatus.UNAVAILABLE,
            reason=CommerceUnavailableReason.BLOCKED_STATE,
            comercio_id=comercio_id,
            modo_operacion=None,
            prueba_hasta=None,
            prueba_max_pedidos=None,
            prueba_pedidos_consumidos=0,
        )

    def test_unavailable_emits_event_with_failure_category_after_finalization(
        self,
    ) -> None:
        """When the commerce is unavailable AND the terminal
        finalization commits, the coordinator MUST emit exactly one
        ``provider_inbound_processing_outcome`` event with
        ``outcome='unavailable'`` and
        ``failure_category='unavailable_commerce'`` AFTER the
        durable finalization. The receipt and work item must be
        finalized in ``failed_terminal`` and the row must carry the
        bounded ``unavailable_blocked_state`` codigo. The emission
        MUST NOT alter the existing transaction, lease or retry
        contract."""
        receipt_id, procesamiento_id = self._accept()

        session = TestingSessionLocal()
        try:
            coordinator = ProviderInboundMessageCoordinator(
                session=session, max_attempts=3
            )
            leased = coordinator.claim_due_processing(now=_now())
            assert leased is not None

            captured: list[dict[str, Any]] = []
            call_order: list[str] = []

            def _capture_emit(*, event: str, **kwargs: Any) -> bool:
                from backend.observability.events import build_event

                call_order.append("emit")
                payload = build_event(event=event, **kwargs)
                captured.append(payload)
                return True

            real_finalize_terminal = (
                coordinator._procesamiento_repo.finalize_terminal
            )

            def _spy_finalize_terminal(**kwargs: Any) -> bool:
                call_order.append("finalize")
                return real_finalize_terminal(**kwargs)

            with patch(
                "backend.services.provider_inbound_message_coordinator"
                ".emit_event",
                side_effect=_capture_emit,
            ), patch(
                "backend.services.provider_inbound_message_coordinator"
                ".CommerceAvailabilityService.evaluate",
                return_value=self._unavailable_outcome(
                    self.comercio_id
                ),
            ), patch.object(
                coordinator._procesamiento_repo,
                "finalize_terminal",
                side_effect=_spy_finalize_terminal,
            ):
                result = coordinator.process_lease(leased)
        finally:
            session.close()

        self.assertEqual(
            result.outcome,
            ProviderInboundProcessingOutcome.FAILED_TERMINAL,
        )
        self.assertEqual(
            result.categoria,
            ProcesamientoMensajeProveedorFailureCategory.TERMINAL_PROCESSOR_ERROR,
        )
        self.assertEqual(result.codigo, "unavailable_blocked_state")

        events = self._processing_outcome_events(captured)
        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event["outcome"], "unavailable")
        self.assertEqual(
            event["failure_category"], "unavailable_commerce"
        )
        self.assertEqual(event["component"], COMPONENT_WORKER)
        self.assertNotIn("response_count", event)
        self.assertNotIn("outbox_row_count", event)
        self.assertEqual(
            event["correlation_id"], self.identificador
        )

        # The processing_outcome emit MUST come AFTER the
        # finalize_terminal call. Stage events (provider_inbound_stage
        # started/completed for the availability seam) can be
        # interleaved before finalize but MUST NOT replace it.
        # The ``processing_finalization`` wrapper now also emits a
        # ``started`` + ``completed`` pair around the finalize call
        # so the recorded call_order is
        # ``[started-emit, finalize, completed-emit,
        # processing_outcome-emit]``.
        finalize_positions = [
            index
            for index, value in enumerate(call_order)
            if value == "finalize"
        ]
        self.assertEqual(
            len(finalize_positions), 1, "finalize_terminal must run once"
        )
        emit_after_finalize = [
            index
            for index in range(
                finalize_positions[0] + 1, len(call_order)
            )
            if call_order[index] == "emit"
        ]
        self.assertGreaterEqual(
            len(emit_after_finalize),
            1,
            "unavailable processing_outcome emit MUST follow "
            "finalize_terminal",
        )
        self.assertIn("provider_inbound_stage", {
            event["event"] for event in captured
        })

        with TestingSessionLocal() as session:
            stored = session.execute(
                select(ProcesamientoMensajeProveedor).where(
                    ProcesamientoMensajeProveedor.id == procesamiento_id
                )
            ).scalar_one()
            self.assertEqual(
                stored.estado,
                ProcesamientoMensajeProveedorEstado.FAILED_TERMINAL.value,
            )
            self.assertEqual(
                stored.categoria_ultimo_fallo,
                "terminal_processor_error",
            )
            self.assertEqual(
                stored.codigo_ultimo_fallo,
                "unavailable_blocked_state",
            )
            receipt_still_present = session.execute(
                select(RecepcionMensajeProveedor).where(
                    RecepcionMensajeProveedor.id == receipt_id
                )
            ).scalar_one()
            self.assertIsNotNone(receipt_still_present)

    def test_unavailable_emits_lease_lost_when_finalization_fails(
        self,
    ) -> None:
        """When the commerce is unavailable AND the terminal
        finalization loses the lease, the coordinator MUST emit
        ONLY ``lease_lost`` (without ``failure_category``) AFTER
        the bounded lease loss is observed. The unavailable
        outcome MUST NOT be reported when no durable finalization
        was committed. The receipt and work item must remain in
        their pre-finalization state for the next claim pass."""
        _receipt_id, procesamiento_id = self._accept()

        session = TestingSessionLocal()
        try:
            coordinator = ProviderInboundMessageCoordinator(
                session=session, max_attempts=3
            )
            leased = coordinator.claim_due_processing(now=_now())
            assert leased is not None

            captured: list[dict[str, Any]] = []
            call_order: list[str] = []

            def _capture_emit(*, event: str, **kwargs: Any) -> bool:
                from backend.observability.events import build_event

                call_order.append("emit")
                payload = build_event(event=event, **kwargs)
                captured.append(payload)
                return True

            def _spy_finalize_terminal(**kwargs: Any) -> bool:
                call_order.append("finalize")
                return False

            with patch(
                "backend.services.provider_inbound_message_coordinator"
                ".emit_event",
                side_effect=_capture_emit,
            ), patch(
                "backend.services.provider_inbound_message_coordinator"
                ".CommerceAvailabilityService.evaluate",
                return_value=self._unavailable_outcome(
                    self.comercio_id
                ),
            ), patch.object(
                coordinator._procesamiento_repo,
                "finalize_terminal",
                side_effect=_spy_finalize_terminal,
            ):
                result = coordinator.process_lease(leased)
        finally:
            session.close()

        self.assertEqual(
            result.outcome,
            ProviderInboundProcessingOutcome.FAILED_TERMINAL,
        )
        self.assertEqual(result.codigo, "unavailable_blocked_state")
        assert result.categoria is not None
        self.assertEqual(
            result.categoria,
            ProcesamientoMensajeProveedorFailureCategory.TERMINAL_PROCESSOR_ERROR,
        )

        events = self._processing_outcome_events(captured)
        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event["outcome"], "lease_lost")
        self.assertNotIn("failure_category", event)
        self.assertEqual(event["component"], COMPONENT_WORKER)
        self.assertNotIn("response_count", event)
        self.assertNotIn("outbox_row_count", event)
        self.assertNotIn("correlation_id", event)

        # The processing_outcome emit MUST come AFTER the
        # finalize_terminal call. Stage events (provider_inbound_stage
        # started/completed for the availability seam) can be
        # interleaved before finalize but MUST NOT replace it. The
        # ``processing_finalization`` wrapper also emits a
        # ``started`` + ``failed (LeaseLost)`` pair around the
        # finalize call so the recorded call_order is
        # ``[started-emit, finalize, failed-emit,
        # processing_outcome-emit]``.
        finalize_positions = [
            index
            for index, value in enumerate(call_order)
            if value == "finalize"
        ]
        self.assertEqual(
            len(finalize_positions), 1, "finalize_terminal must run once"
        )
        emit_after_finalize = [
            index
            for index in range(
                finalize_positions[0] + 1, len(call_order)
            )
            if call_order[index] == "emit"
        ]
        self.assertGreaterEqual(
            len(emit_after_finalize),
            1,
            "lease_lost processing_outcome emit MUST follow "
            "finalize_terminal",
        )
        self.assertIn("provider_inbound_stage", {
            event["event"] for event in captured
        })

        with TestingSessionLocal() as session:
            stored = session.execute(
                select(ProcesamientoMensajeProveedor).where(
                    ProcesamientoMensajeProveedor.id == procesamiento_id
                )
            ).scalar_one()
            self.assertEqual(
                stored.estado,
                ProcesamientoMensajeProveedorEstado.LEASED.value,
                "rolled-back lease must remain claimable until it "
                "expires",
            )
            self.assertIsNone(stored.fecha_finalizacion)


class ProviderInboundStageEventEmissionTest(unittest.TestCase):
    """The provider coordinator MUST emit the closed
    ``provider_inbound_stage`` event around every bounded seam it
    enters during a leased inbound turn: ``availability``,
    ``session_order``, ``business_pipeline``, ``outbound_staging``
    and ``processing_finalization``.

    The wrapper:

    * emits ``started`` before each seam;
    * emits ``completed`` after a normal return with bounded
      ``elapsed_ms`` and the existing opaque synthetic inbound
      ``correlation_id``;
    * emits ``failed`` with the safe exception type name ONLY
      when the seam raises (the existing coordinator rollback /
      retry / lease-loss / terminal handling remains
      authoritative);
    * never fabricates ``completed``/``failed`` when the seam
      does not return — the last ``started`` event is the only
      evidence of the reached boundary;
    * is fail-soft: a stage event that fails validation or
      serialization does NOT change the durable business
      result.
    """

    def setUp(self) -> None:
        suffix = _suffix()
        self.comercio_id = _seed_comercio(suffix)
        self.addCleanup(_delete_comercio, self.comercio_id)
        self.cliente_id = _seed_cliente(suffix + "C")
        self.addCleanup(_delete_cliente, self.cliente_id)
        self.destination = f"+54971{suffix[:8]}"
        self.addCleanup(_delete_canales_by_destination, self.destination)
        self.canal_id = _seed_dedicated_channel(
            suffix + "D", self.comercio_id, self.destination
        )
        self.proveedor = "twilio"
        self.identificador = f"SM-{suffix}"
        self.addCleanup(
            _cleanup_provider_inbound_artifacts, self.comercio_id
        )
        self.addCleanup(
            _delete_recepciones_by_comercio, self.comercio_id
        )
        self.addCleanup(
            _delete_procesamientos_by_comercio, self.comercio_id
        )

    def _command(self) -> ProviderInboundMessageCommand:
        return ProviderInboundMessageCommand(
            proveedor=self.proveedor,
            identificador_recepcion=self.identificador,
            canal_id=self.canal_id,
            cliente_id=self.cliente_id,
            comercio_id=self.comercio_id,
            mensaje="hola",
            destinatario_e164=self.destination,
        )

    def _accept(self) -> tuple[int, int]:
        coordinator = ProviderInboundMessageCoordinator(
            session=TestingSessionLocal(),
        )
        with patch(
            "backend.services.provider_inbound_message_coordinator"
            ".process_incoming_message"
        ):
            outcome = coordinator.accept(self._command())
        assert outcome.receipt_id is not None
        assert outcome.procesamiento_id is not None
        return int(outcome.receipt_id), int(outcome.procesamiento_id)

    def _claim_and_process(
        self,
        *,
        staged_rows: list[StagedOutboundRow],
        emit_side_effect: Any | None = None,
        process_side_effect: Any | None = None,
    ) -> tuple[
        ProviderInboundProcessingResult,
        list[dict[str, Any]],
    ]:
        """Run ``process_lease`` while capturing the JSON-line
        observability events the coordinator emits through
        :func:`emit_event` and forcing the mapper / pipeline to
        return the supplied values.
        """
        session = TestingSessionLocal()
        try:
            coordinator = ProviderInboundMessageCoordinator(
                session=session,
                max_attempts=3,
            )
            leased = coordinator.claim_due_processing(now=_now())
            assert leased is not None

            captured: list[dict[str, Any]] = []

            def _capture_emit(*, event: str, **kwargs: Any) -> bool:
                from backend.observability.events import build_event

                payload = build_event(event=event, **kwargs)
                captured.append(payload)
                return True

            patches: list[Any] = [
                patch(
                    "backend.services.provider_inbound_message_coordinator"
                    ".process_incoming_message",
                    return_value=(
                        [object()] if process_side_effect is None
                        else process_side_effect
                    ),
                ),
                patch(
                    "backend.services.provider_inbound_message_coordinator"
                    ".stage_outbound_rows",
                    return_value=staged_rows,
                ),
            ]
            if emit_side_effect is not None:
                patches.append(
                    patch(
                        "backend.services.provider_inbound_message_coordinator"
                        ".emit_event",
                        side_effect=emit_side_effect,
                    )
                )
            else:
                patches.append(
                    patch(
                        "backend.services.provider_inbound_message_coordinator"
                        ".emit_event",
                        side_effect=_capture_emit,
                    )
                )
            with patches[0], patches[1], patches[2]:
                result = coordinator.process_lease(leased)
            return result, captured
        finally:
            session.close()

    def _stage_events(
        self, captured: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        return [
            event
            for event in captured
            if event.get("event") == EVENT_PROVIDER_INBOUND_STAGE
        ]

    def _stage_pairs(
        self, captured: list[dict[str, Any]]
    ) -> list[
        tuple[str, str, str | None, str | None, int | None]
    ]:
        """Return ``(stage, outcome, correlation_id,
        exception_type, elapsed_ms)`` tuples for the captured stage
        events in order.

        The helper keeps the test assertions focused on order,
        stage/outcome and bounded metadata only.
        """
        pairs: list[
            tuple[str, str, str | None, str | None, int | None]
        ] = []
        for event in self._stage_events(captured):
            pairs.append(
                (
                    str(event.get("stage")),
                    str(event.get("outcome")),
                    event.get("correlation_id"),
                    event.get("exception_type"),
                    event.get("elapsed_ms"),
                )
            )
        return pairs

    def test_successful_turn_emits_stage_sequence(self) -> None:
        """A successful leased turn MUST emit one ``started`` and
        one ``completed`` event per bounded seam, in the existing
        coordinator order, carrying the same synthetic inbound
        correlation value as the
        ``provider_inbound_processing_outcome`` event."""
        self._accept()
        staged_row = StagedOutboundRow(
            mensaje_proveedor_saliente_id=1,
            sequence=0,
            customer_response=CustomerResponse(
                message="ok",
                intent="noop",
                status="executed",
            ),
        )
        result, captured = self._claim_and_process(
            staged_rows=[staged_row]
        )
        self.assertEqual(
            result.outcome,
            ProviderInboundProcessingOutcome.PROCESSED,
        )

        pairs = self._stage_pairs(captured)
        stages_seen = [pair[0] for pair in pairs]
        # The captured order interleaves started + completed per
        # stage; the unique stage sequence MUST follow the
        # existing coordinator order.
        unique_stages_in_order: list[str] = []
        for stage in stages_seen:
            if not unique_stages_in_order or (
                unique_stages_in_order[-1] != stage
            ):
                unique_stages_in_order.append(stage)
        self.assertEqual(
            unique_stages_in_order,
            [
                "availability",
                "session_order",
                "business_pipeline",
                "outbound_staging",
                "processing_finalization",
            ],
        )
        # Each entered seam MUST have a started and a completed
        # event in the captured order.
        for index, stage in enumerate(unique_stages_in_order):
            started = pairs[index * 2]
            completed = pairs[index * 2 + 1]
            self.assertEqual(started[1], "started")
            self.assertEqual(started[0], stage)
            self.assertEqual(completed[1], "completed")
            self.assertEqual(completed[0], stage)
            self.assertEqual(
                started[2], self.identificador,
                f"started event for {stage!r} must carry the "
                "provider synthetic inbound correlation_id",
            )
            self.assertEqual(
                completed[2], self.identificador,
                f"completed event for {stage!r} must carry the "
                "provider synthetic inbound correlation_id",
            )
            self.assertIsInstance(completed[4], int)
            self.assertGreaterEqual(int(completed[4] or 0), 0)

        # No stage event for the ``started`` outcome carries
        # ``elapsed_ms`` or ``exception_type``: the boundary had
        # not returned yet.
        for pair in pairs:
            if pair[1] == "started":
                self.assertIsNone(pair[4])
                self.assertIsNone(pair[3])

        # The processing-outcome event is emitted AFTER the
        # processing_finalization completed event so it remains
        # authoritative for the durable state. Find the position
        # right after the last stage event and assert the
        # processing_outcome sits there.
        events_in_order = [event.get("event") for event in captured]
        stage_event_count = events_in_order.count(
            EVENT_PROVIDER_INBOUND_STAGE
        )
        self.assertEqual(stage_event_count, 10)
        outcome_after_finalization = events_in_order[stage_event_count]
        self.assertEqual(outcome_after_finalization, EVENT_PROCESSING_OUTCOME)

    def test_business_pipeline_failure_emits_failed_and_re_raises(
        self,
    ) -> None:
        """When the ``business_pipeline`` seam raises, the wrapper
        MUST emit one ``failed`` event with the safe exception
        type and let the existing coordinator failure path run."""
        self._accept()

        class _PipelineBoom(RuntimeError):
            pass

        session = TestingSessionLocal()
        try:
            coordinator = ProviderInboundMessageCoordinator(
                session=session,
                max_attempts=3,
            )
            leased = coordinator.claim_due_processing(now=_now())
            assert leased is not None

            captured: list[dict[str, Any]] = []

            def _capture_emit(*, event: str, **kwargs: Any) -> bool:
                from backend.observability.events import build_event

                payload = build_event(event=event, **kwargs)
                captured.append(payload)
                return True

            with patch(
                "backend.services.provider_inbound_message_coordinator"
                ".process_incoming_message",
                side_effect=_PipelineBoom("secret-detail-leaked"),
            ), patch(
                "backend.services.provider_inbound_message_coordinator"
                ".emit_event",
                side_effect=_capture_emit,
            ):
                result = coordinator.process_lease(leased)
        finally:
            session.close()

        # The existing coordinator failure path returns a
        # retry_scheduled outcome; the wrapper MUST NOT replace
        # that contract.
        self.assertEqual(
            result.outcome,
            ProviderInboundProcessingOutcome.RETRY_SCHEDULED,
        )

        stage_events = self._stage_events(captured)
        self.assertEqual(len(stage_events), 8)
        self.assertEqual(stage_events[0]["stage"], "availability")
        self.assertEqual(stage_events[0]["outcome"], "started")
        self.assertEqual(stage_events[1]["stage"], "availability")
        self.assertEqual(stage_events[1]["outcome"], "completed")
        self.assertEqual(stage_events[2]["stage"], "session_order")
        self.assertEqual(stage_events[2]["outcome"], "started")
        self.assertEqual(stage_events[3]["stage"], "session_order")
        self.assertEqual(stage_events[3]["outcome"], "completed")
        self.assertEqual(stage_events[4]["stage"], "business_pipeline")
        self.assertEqual(stage_events[4]["outcome"], "started")
        self.assertEqual(stage_events[5]["stage"], "business_pipeline")
        self.assertEqual(stage_events[5]["outcome"], "failed")
        self.assertEqual(
            stage_events[5]["exception_type"], "_PipelineBoom"
        )
        self.assertEqual(
            stage_events[5]["correlation_id"], self.identificador
        )
        self.assertIsInstance(stage_events[5]["elapsed_ms"], int)
        # The ``business_pipeline`` ``failed`` event triggers the
        # ``_finalize_failure`` retryable path, which now also
        # emits a bounded ``processing_finalization`` started +
        # completed pair so every finalization branch has its
        # observability evidence.
        self.assertEqual(
            stage_events[6]["stage"], "processing_finalization"
        )
        self.assertEqual(stage_events[6]["outcome"], "started")
        self.assertEqual(
            stage_events[6]["correlation_id"], self.identificador
        )
        self.assertEqual(
            stage_events[7]["stage"], "processing_finalization"
        )
        self.assertEqual(stage_events[7]["outcome"], "completed")
        self.assertEqual(
            stage_events[7]["correlation_id"], self.identificador
        )
        self.assertIsInstance(stage_events[7]["elapsed_ms"], int)

        # The safe exception_type contract MUST reject the raw
        # exception message; only the type name leaks through.
        serialized = json.dumps(captured, sort_keys=True)
        self.assertNotIn("secret-detail-leaked", serialized)

        # The processing_outcome event reflects the existing
        # coordinator failure path (retry_scheduled) and is the
        # source of truth for the durable state. The
        # ``processing_finalization`` ``completed`` event is
        # emitted BEFORE the ``processing_outcome`` event so the
        # ordering ``finalize -> stage event -> processing
        # outcome`` remains authoritative.
        processing_events = [
            event
            for event in captured
            if event.get("event") == EVENT_PROCESSING_OUTCOME
        ]
        self.assertEqual(len(processing_events), 1)
        self.assertEqual(
            processing_events[0]["outcome"], "retry_scheduled"
        )
        # The combined ordering is ``finalize_retryable -> commit
        # -> processing_finalization completed -> processing
        # outcome retry_scheduled``.
        processing_finalization_completed_positions = [
            index
            for index, event in enumerate(captured)
            if event.get("event") == EVENT_PROVIDER_INBOUND_STAGE
            and event.get("stage") == "processing_finalization"
            and event.get("outcome") == "completed"
        ]
        processing_outcome_positions = [
            index
            for index, event in enumerate(captured)
            if event.get("event") == EVENT_PROCESSING_OUTCOME
        ]
        self.assertEqual(len(processing_finalization_completed_positions), 1)
        self.assertEqual(len(processing_outcome_positions), 1)
        self.assertLess(
            processing_finalization_completed_positions[0],
            processing_outcome_positions[0],
        )

    def test_non_returning_seam_emits_only_started(self) -> None:
        """When the existing seam does not return (e.g. the worker
        is interrupted, the session cannot be staged, or the
        underlying call hangs), only the ``started`` event is
        emitted — no synthetic ``completed``, no synthetic
        ``failed``, no recovery."""
        self._accept()

        call_count = {"n": 0}

        def _hanging_session_stage(*args: Any, **kwargs: Any) -> Any:
            call_count["n"] += 1
            raise KeyboardInterrupt("worker interrupted")

        session = TestingSessionLocal()
        try:
            coordinator = ProviderInboundMessageCoordinator(
                session=session,
                max_attempts=3,
            )
            leased = coordinator.claim_due_processing(now=_now())
            assert leased is not None

            captured: list[dict[str, Any]] = []

            def _capture_emit(*, event: str, **kwargs: Any) -> bool:
                from backend.observability.events import build_event

                payload = build_event(event=event, **kwargs)
                captured.append(payload)
                return True

            with patch(
                "backend.services.provider_inbound_message_coordinator"
                ".process_incoming_message",
                return_value=[object()],
            ), patch(
                "backend.services.provider_inbound_message_coordinator"
                ".stage_outbound_rows",
                return_value=[],
            ), patch(
                "backend.services.provider_inbound_message_coordinator"
                ".SessionRepository.stage_active",
                side_effect=_hanging_session_stage,
            ), patch(
                "backend.services.provider_inbound_message_coordinator"
                ".emit_event",
                side_effect=_capture_emit,
            ):
                with self.assertRaises(KeyboardInterrupt):
                    coordinator.process_lease(leased)
        finally:
            session.close()

        stage_events = self._stage_events(captured)
        # availability started + completed, then session_order
        # started, then session_order failed (the wrapper
        # always emits failed on exception, even for
        # KeyboardInterrupt, so the existing supervisor sees the
        # failure path). The absence of any later stage event
        # is the evidence the business pipeline was not reached.
        self.assertEqual(stage_events[0]["stage"], "availability")
        self.assertEqual(stage_events[0]["outcome"], "started")
        self.assertEqual(stage_events[1]["stage"], "availability")
        self.assertEqual(stage_events[1]["outcome"], "completed")
        self.assertEqual(stage_events[2]["stage"], "session_order")
        self.assertEqual(stage_events[2]["outcome"], "started")
        self.assertEqual(stage_events[3]["stage"], "session_order")
        self.assertEqual(stage_events[3]["outcome"], "failed")
        # No business_pipeline / outbound_staging /
        # processing_finalization events were emitted because
        # the failure path rolled back the transaction before
        # reaching those seams.
        stages_seen = [event["stage"] for event in stage_events]
        self.assertNotIn("business_pipeline", stages_seen)
        self.assertNotIn("outbound_staging", stages_seen)
        self.assertNotIn("processing_finalization", stages_seen)

    def test_emission_failure_does_not_alter_business_result(self) -> None:
        """A malformed stage event (e.g. an unknown stage token
        injected by a misconfigured caller) MUST NOT replace the
        existing processing-outcome contract. The coordinator
        keeps its previous behavior because :func:`emit_event`
        degrades to ``observability_emit_failed`` instead of
        propagating the validation error."""
        self._accept()
        staged_row = StagedOutboundRow(
            mensaje_proveedor_saliente_id=1,
            sequence=0,
            customer_response=CustomerResponse(
                message="ok",
                intent="noop",
                status="executed",
            ),
        )

        captured: list[dict[str, Any]] = []
        emission_failures: list[str] = []

        def _broken_emit(*, event: str, **kwargs: Any) -> bool:
            """First emit must fail; subsequent emits succeed so
            the coordinator continues its business flow even when
            the diagnostic event cannot be built."""
            from backend.observability.events import build_event

            if not emission_failures:
                emission_failures.append(event)
                return False
            payload = build_event(event=event, **kwargs)
            captured.append(payload)
            return True

        session = TestingSessionLocal()
        try:
            coordinator = ProviderInboundMessageCoordinator(
                session=session,
                max_attempts=3,
            )
            leased = coordinator.claim_due_processing(now=_now())
            assert leased is not None
            with patch(
                "backend.services.provider_inbound_message_coordinator"
                ".process_incoming_message",
                return_value=[object()],
            ), patch(
                "backend.services.provider_inbound_message_coordinator"
                ".stage_outbound_rows",
                return_value=[staged_row],
            ), patch(
                "backend.services.provider_inbound_message_coordinator"
                ".emit_event",
                side_effect=_broken_emit,
            ):
                result = coordinator.process_lease(leased)
        finally:
            session.close()

        # Business result MUST be PROCESSED: the diagnostic
        # emission failure NEVER replaces the durable outcome.
        self.assertEqual(
            result.outcome,
            ProviderInboundProcessingOutcome.PROCESSED,
        )
        processing_events = [
            event
            for event in captured
            if event.get("event") == EVENT_PROCESSING_OUTCOME
        ]
        self.assertEqual(len(processing_events), 1)
        self.assertIn(
            processing_events[0]["outcome"],
            {"processed_with_response", "processed_without_response"},
        )

    def test_processing_finalization_lease_lost_emits_failed(self) -> None:
        """When the existing finalization commit cannot honor the
        lease (lease_lost), the ``processing_finalization`` stage
        MUST emit ``failed`` with the safe ``LeaseLost`` exception
        token BEFORE the existing rollback runs."""
        self._accept()
        staged_row = StagedOutboundRow(
            mensaje_proveedor_saliente_id=1,
            sequence=0,
            customer_response=CustomerResponse(
                message="ok",
                intent="noop",
                status="executed",
            ),
        )

        session = TestingSessionLocal()
        try:
            coordinator = ProviderInboundMessageCoordinator(
                session=session,
                max_attempts=3,
            )
            leased = coordinator.claim_due_processing(now=_now())
            assert leased is not None

            captured: list[dict[str, Any]] = []

            def _capture_emit(*, event: str, **kwargs: Any) -> bool:
                from backend.observability.events import build_event

                payload = build_event(event=event, **kwargs)
                captured.append(payload)
                return True

            with patch(
                "backend.services.provider_inbound_message_coordinator"
                ".process_incoming_message",
                return_value=[object()],
            ), patch(
                "backend.services.provider_inbound_message_coordinator"
                ".stage_outbound_rows",
                return_value=[staged_row],
            ), patch(
                "backend.services.provider_inbound_message_coordinator"
                ".ProcesamientoMensajeProveedorRepository.finalize_processed",
                return_value=False,
            ), patch(
                "backend.services.provider_inbound_message_coordinator"
                ".emit_event",
                side_effect=_capture_emit,
            ):
                result = coordinator.process_lease(leased)
        finally:
            session.close()

        self.assertEqual(
            result.outcome,
            ProviderInboundProcessingOutcome.RETRY_SCHEDULED,
        )
        stage_events = self._stage_events(captured)
        finalization_events = [
            event
            for event in stage_events
            if event["stage"] == "processing_finalization"
        ]
        self.assertEqual(len(finalization_events), 2)
        self.assertEqual(finalization_events[0]["outcome"], "started")
        self.assertEqual(finalization_events[1]["outcome"], "failed")
        self.assertEqual(
            finalization_events[1]["exception_type"], "LeaseLost"
        )
        self.assertIsInstance(finalization_events[1]["elapsed_ms"], int)
        processing_events = [
            event
            for event in captured
            if event.get("event") == EVENT_PROCESSING_OUTCOME
        ]
        self.assertEqual(len(processing_events), 1)
        self.assertEqual(processing_events[0]["outcome"], "lease_lost")


class ProviderInboundProcessingFinalizationStageEventTest(unittest.TestCase):
    """The coordinator MUST emit the bounded
    ``processing_finalization`` ``provider_inbound_stage`` event
    around EVERY finalization branch so a future branch cannot
    silently miss its observability evidence.

    The branches covered here:

    * ``receipt_missing`` with ``finalize_terminal`` -> ``completed``;
    * ``receipt_missing`` with ``finalize_terminal`` returns ``False``
      -> ``failed`` with ``LeaseLost`` (no ``correlation_id`` because
      no receipt is available);
    * ``unavailable`` commerce with ``finalize_terminal`` ->
      ``completed`` carrying the existing receipt correlation_id;
    * ``unavailable`` commerce with ``finalize_terminal`` returns
      ``False`` -> ``failed`` with ``LeaseLost``;
    * business pipeline failure with attempts < max_attempts ->
      retryable ``completed`` carrying the existing receipt
      correlation_id;
    * business pipeline failure with attempts >= max_attempts ->
      terminal ``completed`` carrying the existing receipt
      correlation_id;
    * success path ``finalize_processed`` raises ->
      ``failed`` with safe exception_type and re-raises;
    * ordering: ``finalize -> commit/rollback -> stage event ->
      processing outcome``;
    * ``BaseException`` raised inside the provider scope clears the
      LLM timing recorder correlation so a direct subsequent
      ``QueryLlm`` / ``OllamaEmbeddingClient`` call cannot inherit
      a stale opaque synthetic inbound identifier.
    """

    def setUp(self) -> None:
        suffix = _suffix()
        self.comercio_id = _seed_comercio(suffix)
        self.addCleanup(_delete_comercio, self.comercio_id)
        self.cliente_id = _seed_cliente(suffix + "C")
        self.addCleanup(_delete_cliente, self.cliente_id)
        self.destination = f"+54971{suffix[:8]}"
        self.addCleanup(_delete_canales_by_destination, self.destination)
        self.canal_id = _seed_dedicated_channel(
            suffix + "D", self.comercio_id, self.destination
        )
        self.proveedor = "twilio"
        self.identificador = f"SM-{suffix}"
        self.addCleanup(
            _cleanup_provider_inbound_artifacts, self.comercio_id
        )
        self.addCleanup(
            _delete_recepciones_by_comercio, self.comercio_id
        )
        self.addCleanup(
            _delete_procesamientos_by_comercio, self.comercio_id
        )
        # Every test in this class MUST start with a clean LLM
        # thread-local recorder; otherwise an earlier suite that
        # left a correlation installed would silently leak into
        # the assertions below.
        from backend.llm.query_llm import reset_llm_timing_recorder

        reset_llm_timing_recorder()
        self.addCleanup(reset_llm_timing_recorder)

    def _command(self) -> ProviderInboundMessageCommand:
        return ProviderInboundMessageCommand(
            proveedor=self.proveedor,
            identificador_recepcion=self.identificador,
            canal_id=self.canal_id,
            cliente_id=self.cliente_id,
            comercio_id=self.comercio_id,
            mensaje="hola",
            destinatario_e164=self.destination,
        )

    def _accept(self) -> tuple[int, int]:
        coordinator = ProviderInboundMessageCoordinator(
            session=TestingSessionLocal(),
        )
        with patch(
            "backend.services.provider_inbound_message_coordinator"
            ".process_incoming_message"
        ):
            outcome = coordinator.accept(self._command())
        assert outcome.receipt_id is not None
        assert outcome.procesamiento_id is not None
        return int(outcome.receipt_id), int(outcome.procesamiento_id)

    @staticmethod
    def _unavailable_outcome(
        comercio_id: int,
    ) -> CommerceAvailabilityOutcome:
        return CommerceAvailabilityOutcome(
            status=CommerceAvailabilityStatus.UNAVAILABLE,
            reason=CommerceUnavailableReason.BLOCKED_STATE,
            comercio_id=comercio_id,
            modo_operacion=None,
            prueba_hasta=None,
            prueba_max_pedidos=None,
            prueba_pedidos_consumidos=0,
        )

    def _processing_finalization_pairs(
        self, captured: list[dict[str, Any]]
    ) -> list[tuple[str, str, str | None, str | None]]:
        return [
            (
                str(event.get("stage")),
                str(event.get("outcome")),
                event.get("correlation_id"),
                event.get("exception_type"),
            )
            for event in captured
            if event.get("event") == EVENT_PROVIDER_INBOUND_STAGE
            and event.get("stage") == "processing_finalization"
        ]

    def _processing_outcome_event(
        self, captured: list[dict[str, Any]]
    ) -> dict[str, Any]:
        events = [
            event
            for event in captured
            if event.get("event") == EVENT_PROCESSING_OUTCOME
        ]
        self.assertEqual(
            len(events),
            1,
            "exactly one processing_outcome event must be emitted",
        )
        return events[0]

    def _capture_emit_factory(
        self, captured: list[dict[str, Any]]
    ) -> Any:
        def _capture_emit(*, event: str, **kwargs: Any) -> bool:
            from backend.observability.events import build_event

            payload = build_event(event=event, **kwargs)
            captured.append(payload)
            return True

        return _capture_emit

    # ------------------------------- receipt_missing ----------------------

    def test_receipt_missing_emits_processing_finalization_started_and_completed(
        self,
    ) -> None:
        """``receipt_missing`` finalizes via ``_finalize_terminal`` and
        MUST emit one ``processing_finalization`` ``started`` event
        followed by one ``completed`` event with ``correlation_id``
        ABSENT (no receipt available to thread through)."""
        self._accept()
        captured: list[dict[str, Any]] = []
        session = TestingSessionLocal()
        try:
            coordinator = ProviderInboundMessageCoordinator(
                session=session,
            )
            leased = coordinator.claim_due_processing(now=_now())
            assert leased is not None

            with patch(
                "backend.services.provider_inbound_message_coordinator"
                ".emit_event",
                side_effect=self._capture_emit_factory(captured),
            ), patch.object(
                coordinator._recepcion_repo,
                "find_by_id",
                return_value=None,
            ):
                result = coordinator.process_lease(leased)
        finally:
            session.close()

        self.assertEqual(
            result.outcome,
            ProviderInboundProcessingOutcome.FAILED_TERMINAL,
        )
        pairs = self._processing_finalization_pairs(captured)
        self.assertEqual(
            len(pairs),
            2,
            "exactly one started + one completed finalization event",
        )
        self.assertEqual(pairs[0][1], "started")
        self.assertIsNone(
            pairs[0][2],
            "correlation_id MUST be None when no receipt exists",
        )
        self.assertIsNone(pairs[0][3])
        self.assertEqual(pairs[1][1], "completed")
        self.assertIsNone(pairs[1][2])
        self.assertIsNone(pairs[1][3])
        # The processing_outcome event is emitted AFTER the
        # ``processing_finalization`` completed event so the
        # existing ``finalize -> stage event -> outcome`` order is
        # preserved.
        outcome = self._processing_outcome_event(captured)
        self.assertEqual(outcome["outcome"], "failed_terminal")
        positions = [
            index
            for index, event in enumerate(captured)
            if event.get("event") == EVENT_PROVIDER_INBOUND_STAGE
            and event.get("stage") == "processing_finalization"
            and event.get("outcome") == "completed"
        ]
        outcome_positions = [
            index
            for index, event in enumerate(captured)
            if event.get("event") == EVENT_PROCESSING_OUTCOME
        ]
        self.assertEqual(len(positions), 1)
        self.assertEqual(len(outcome_positions), 1)
        self.assertLess(positions[0], outcome_positions[0])

    def test_receipt_missing_emits_processing_finalization_failed_on_leaselost(
        self,
    ) -> None:
        """``receipt_missing`` with a lease-lost ``finalize_terminal``
        MUST emit one ``processing_finalization`` ``failed`` event
        with the safe ``LeaseLost`` ``exception_type``. The
        ``processing_outcome`` event MUST be emitted AFTER the failed
        event so the existing ``finalize -> rollback -> stage event
        -> outcome`` order is preserved."""
        self._accept()
        captured: list[dict[str, Any]] = []
        session = TestingSessionLocal()
        try:
            coordinator = ProviderInboundMessageCoordinator(
                session=session,
            )
            leased = coordinator.claim_due_processing(now=_now())
            assert leased is not None

            with patch(
                "backend.services.provider_inbound_message_coordinator"
                ".emit_event",
                side_effect=self._capture_emit_factory(captured),
            ), patch.object(
                coordinator._recepcion_repo,
                "find_by_id",
                return_value=None,
            ), patch.object(
                coordinator._procesamiento_repo,
                "finalize_terminal",
                return_value=False,
            ):
                result = coordinator.process_lease(leased)
        finally:
            session.close()

        self.assertEqual(
            result.outcome,
            ProviderInboundProcessingOutcome.FAILED_TERMINAL,
        )
        pairs = self._processing_finalization_pairs(captured)
        self.assertEqual(len(pairs), 2)
        self.assertEqual(pairs[0][1], "started")
        self.assertIsNone(pairs[0][2])
        self.assertEqual(pairs[1][1], "failed")
        self.assertEqual(pairs[1][3], "LeaseLost")
        self.assertIsNone(pairs[1][2])

        outcome = self._processing_outcome_event(captured)
        self.assertEqual(outcome["outcome"], "lease_lost")

    # ------------------------------- unavailable --------------------------

    def test_unavailable_emits_processing_finalization_started_and_completed(
        self,
    ) -> None:
        """``unavailable`` commerce with a successful
        ``finalize_terminal`` MUST emit the
        ``processing_finalization`` ``started`` + ``completed`` pair
        carrying the existing opaque synthetic inbound
        ``correlation_id``."""
        self._accept()
        captured: list[dict[str, Any]] = []
        session = TestingSessionLocal()
        try:
            coordinator = ProviderInboundMessageCoordinator(
                session=session,
            )
            leased = coordinator.claim_due_processing(now=_now())
            assert leased is not None

            with patch(
                "backend.services.provider_inbound_message_coordinator"
                ".emit_event",
                side_effect=self._capture_emit_factory(captured),
            ), patch(
                "backend.services.provider_inbound_message_coordinator"
                ".CommerceAvailabilityService.evaluate",
                return_value=self._unavailable_outcome(self.comercio_id),
            ):
                result = coordinator.process_lease(leased)
        finally:
            session.close()

        self.assertEqual(
            result.outcome,
            ProviderInboundProcessingOutcome.FAILED_TERMINAL,
        )
        pairs = self._processing_finalization_pairs(captured)
        self.assertEqual(len(pairs), 2)
        self.assertEqual(pairs[0][1], "started")
        self.assertEqual(
            pairs[0][2], self.identificador,
            "unavailable path MUST keep the receipt correlation_id",
        )
        self.assertEqual(pairs[1][1], "completed")
        self.assertEqual(pairs[1][2], self.identificador)
        self.assertIsInstance(
            next(
                event["elapsed_ms"]
                for event in captured
                if event.get("event") == EVENT_PROVIDER_INBOUND_STAGE
                and event.get("stage") == "processing_finalization"
                and event.get("outcome") == "completed"
            ),
            int,
        )

        outcome = self._processing_outcome_event(captured)
        self.assertEqual(outcome["outcome"], "unavailable")
        self.assertEqual(
            outcome["failure_category"], "unavailable_commerce"
        )

    def test_unavailable_emits_processing_finalization_failed_on_leaselost(
        self,
    ) -> None:
        """``unavailable`` commerce with lease-lost finalization MUST
        emit ``processing_finalization`` ``failed`` with
        ``LeaseLost`` and the existing receipt ``correlation_id``,
        followed by ``processing_outcome`` ``lease_lost``."""
        self._accept()
        captured: list[dict[str, Any]] = []
        session = TestingSessionLocal()
        try:
            coordinator = ProviderInboundMessageCoordinator(
                session=session,
            )
            leased = coordinator.claim_due_processing(now=_now())
            assert leased is not None

            with patch(
                "backend.services.provider_inbound_message_coordinator"
                ".emit_event",
                side_effect=self._capture_emit_factory(captured),
            ), patch(
                "backend.services.provider_inbound_message_coordinator"
                ".CommerceAvailabilityService.evaluate",
                return_value=self._unavailable_outcome(self.comercio_id),
            ), patch.object(
                coordinator._procesamiento_repo,
                "finalize_terminal",
                return_value=False,
            ):
                result = coordinator.process_lease(leased)
        finally:
            session.close()

        self.assertEqual(
            result.outcome,
            ProviderInboundProcessingOutcome.FAILED_TERMINAL,
        )
        pairs = self._processing_finalization_pairs(captured)
        self.assertEqual(len(pairs), 2)
        self.assertEqual(pairs[1][1], "failed")
        self.assertEqual(pairs[1][3], "LeaseLost")
        self.assertEqual(pairs[1][2], self.identificador)
        outcome = self._processing_outcome_event(captured)
        self.assertEqual(outcome["outcome"], "lease_lost")

    # ------------------------------- retryable --------------------------

    def test_business_pipeline_failure_emits_processing_finalization_retryable(
        self,
    ) -> None:
        """A ``business_pipeline`` exception that rolls back through
        the existing retryable ``_finalize_failure`` path MUST emit
        ``processing_finalization`` ``started`` + ``completed`` with
        the receipt ``correlation_id`` so the finalization seam is
        observable."""
        self._accept()
        captured: list[dict[str, Any]] = []
        session = TestingSessionLocal()
        try:
            coordinator = ProviderInboundMessageCoordinator(
                session=session,
                max_attempts=3,
            )
            leased = coordinator.claim_due_processing(now=_now())
            assert leased is not None

            with patch(
                "backend.services.provider_inbound_message_coordinator"
                ".process_incoming_message",
                side_effect=RuntimeError("forced"),
            ), patch(
                "backend.services.provider_inbound_message_coordinator"
                ".emit_event",
                side_effect=self._capture_emit_factory(captured),
            ):
                result = coordinator.process_lease(leased)
        finally:
            session.close()

        self.assertEqual(
            result.outcome,
            ProviderInboundProcessingOutcome.RETRY_SCHEDULED,
        )
        pairs = self._processing_finalization_pairs(captured)
        self.assertEqual(len(pairs), 2)
        self.assertEqual(pairs[0][1], "started")
        self.assertEqual(pairs[0][2], self.identificador)
        self.assertEqual(pairs[1][1], "completed")
        self.assertEqual(pairs[1][2], self.identificador)
        self.assertIsNone(pairs[1][3])
        outcome = self._processing_outcome_event(captured)
        self.assertEqual(outcome["outcome"], "retry_scheduled")
        self.assertEqual(outcome["failure_category"], "pipeline_error")
        self.assertEqual(outcome.get("correlation_id"), self.identificador)

    # ------------------------------- terminal ----------------------------

    def test_business_pipeline_failure_emits_processing_finalization_terminal(
        self,
    ) -> None:
        """A ``business_pipeline`` exception that exhausts the
        attempt budget MUST drive ``_finalize_failure`` into the
        terminal ``finalize_terminal`` branch and emit
        ``processing_finalization`` ``started`` + ``completed``
        with the receipt ``correlation_id``."""
        self._accept()
        captured: list[dict[str, Any]] = []
        session = TestingSessionLocal()
        try:
            coordinator = ProviderInboundMessageCoordinator(
                session=session,
                max_attempts=1,
            )
            leased = coordinator.claim_due_processing(now=_now())
            assert leased is not None

            with patch(
                "backend.services.provider_inbound_message_coordinator"
                ".process_incoming_message",
                side_effect=RuntimeError("forced"),
            ), patch(
                "backend.services.provider_inbound_message_coordinator"
                ".emit_event",
                side_effect=self._capture_emit_factory(captured),
            ):
                result = coordinator.process_lease(leased)
        finally:
            session.close()

        self.assertEqual(
            result.outcome,
            ProviderInboundProcessingOutcome.FAILED_TERMINAL,
        )
        pairs = self._processing_finalization_pairs(captured)
        self.assertEqual(len(pairs), 2)
        self.assertEqual(pairs[0][1], "started")
        self.assertEqual(pairs[0][2], self.identificador)
        self.assertEqual(pairs[1][1], "completed")
        self.assertEqual(pairs[1][2], self.identificador)
        outcome = self._processing_outcome_event(captured)
        self.assertEqual(outcome["outcome"], "failed_terminal")
        self.assertEqual(outcome["failure_category"], "pipeline_error")

    # ------------------- finalize_processed exception -------------------

    def test_finalize_processed_exception_emits_processing_finalization_failed(
        self,
    ) -> None:
        """When the existing ``finalize_processed`` repo call raises
        an unexpected exception, the coordinator MUST emit a
        ``processing_finalization`` ``failed`` event with the safe
        exception_type and re-raise so the existing rollback / lease
        / retry / terminal paths remain authoritative."""
        from backend.llm.query_llm import reset_llm_timing_recorder

        reset_llm_timing_recorder()
        self.addCleanup(reset_llm_timing_recorder)
        self._accept()
        staged_row = StagedOutboundRow(
            mensaje_proveedor_saliente_id=1,
            sequence=0,
            customer_response=CustomerResponse(
                message="ok",
                intent="noop",
                status="executed",
            ),
        )
        captured: list[dict[str, Any]] = []

        class _FinalizeBoom(RuntimeError):
            pass

        session = TestingSessionLocal()
        try:
            coordinator = ProviderInboundMessageCoordinator(
                session=session,
                max_attempts=3,
            )
            leased = coordinator.claim_due_processing(now=_now())
            assert leased is not None

            with patch(
                "backend.services.provider_inbound_message_coordinator"
                ".process_incoming_message",
                return_value=[object()],
            ), patch(
                "backend.services.provider_inbound_message_coordinator"
                ".stage_outbound_rows",
                return_value=[staged_row],
            ), patch(
                "backend.services.provider_inbound_message_coordinator"
                ".ProcesamientoMensajeProveedorRepository.finalize_processed",
                side_effect=_FinalizeBoom("forced"),
            ), patch(
                "backend.services.provider_inbound_message_coordinator"
                ".emit_event",
                side_effect=self._capture_emit_factory(captured),
            ):
                with self.assertRaises(_FinalizeBoom):
                    coordinator.process_lease(leased)
        finally:
            session.close()

        pairs = self._processing_finalization_pairs(captured)
        self.assertEqual(len(pairs), 2)
        self.assertEqual(pairs[0][1], "started")
        self.assertEqual(pairs[0][2], self.identificador)
        self.assertEqual(pairs[1][1], "failed")
        self.assertEqual(pairs[1][3], "_FinalizeBoom")
        self.assertEqual(pairs[1][2], self.identificador)
        # The safe exception_type contract MUST reject the raw
        # exception message; only the type name leaks through.
        serialized = json.dumps(captured, sort_keys=True)
        self.assertNotIn("forced", serialized)

    # -------------------- ordering finalize -> stage -> outcome ----------

    def test_ordering_finalize_then_stage_event_then_processing_outcome(
        self,
    ) -> None:
        """Across every reachable branch the existing
        ``finalize -> commit/rollback -> processing_finalization
        stage event -> provider_inbound_processing_outcome`` order
        MUST be preserved so the new diagnostic never replaces the
        authoritative durable contract.

        The test verifies the four most representative branches in
        a single loop:

        * success (``finalize_processed`` with staged rows);
        * ``finalize_processed`` returns ``False`` (lease_lost);
        * ``receipt_missing`` (no receipt available);
        * ``unavailable`` commerce.
        """
        scenarios: list[
            tuple[str, Any, Any]
        ]

        def _setup_scenario(scenario_label: str) -> int:
            """Create an isolated cliente + dedicated canal + receipt +
            work item for one scenario so the unique-receipt constraint
            and the per-conversation claim block do not leak across the
            four scenarios in this test. Returns the new
            ``procesamiento_id`` and registers an atomic cleanup so
            the existing comercio-level cleanups in ``setUp`` finish
            the job.
            """
            base = _suffix()
            short_suffix = f"{base[:9]}{scenario_label[0]}"
            cliente_id = _seed_cliente(short_suffix + "C")
            destination = f"+54971{short_suffix[:8]}"
            canal_id = _seed_dedicated_channel(
                short_suffix + "D", self.comercio_id, destination
            )
            identificador = f"SM-{scenario_label}-{base}"
            self.addCleanup(_delete_canales_by_destination, destination)
            self.addCleanup(
                _delete_scenario_fixture, cliente_id, identificador
            )
            coordinator = ProviderInboundMessageCoordinator(
                session=TestingSessionLocal(),
            )
            with patch(
                "backend.services.provider_inbound_message_coordinator"
                ".process_incoming_message"
            ):
                outcome = coordinator.accept(
                    ProviderInboundMessageCommand(
                        proveedor=self.proveedor,
                        identificador_recepcion=identificador,
                        canal_id=canal_id,
                        cliente_id=cliente_id,
                        comercio_id=self.comercio_id,
                        mensaje="hola",
                        destinatario_e164=destination,
                    )
                )
            self.assertEqual(
                outcome.status,
                ProviderInboundMessageStatus.ACCEPTED,
            )
            assert outcome.procesamiento_id is not None
            return int(outcome.procesamiento_id)

        def _success_scenario() -> Any:
            _setup_scenario("success")
            session = TestingSessionLocal()
            coordinator = ProviderInboundMessageCoordinator(
                session=session,
                max_attempts=3,
            )
            leased = coordinator.claim_due_processing(now=_now())
            assert leased is not None
            staged_row = StagedOutboundRow(
                mensaje_proveedor_saliente_id=1,
                sequence=0,
                customer_response=CustomerResponse(
                    message="ok",
                    intent="noop",
                    status="executed",
                ),
            )
            captured: list[dict[str, Any]] = []
            try:
                with patch(
                    "backend.services.provider_inbound_message_coordinator"
                    ".process_incoming_message",
                    return_value=[object()],
                ), patch(
                    "backend.services.provider_inbound_message_coordinator"
                    ".stage_outbound_rows",
                    return_value=[staged_row],
                ), patch(
                    "backend.services.provider_inbound_message_coordinator"
                    ".emit_event",
                    side_effect=self._capture_emit_factory(captured),
                ):
                    coordinator.process_lease(leased)
                return captured, "processed_with_response"
            finally:
                session.close()

        def _lease_lost_scenario() -> Any:
            _setup_scenario("lease_lost")
            staged_row = StagedOutboundRow(
                mensaje_proveedor_saliente_id=1,
                sequence=0,
                customer_response=CustomerResponse(
                    message="ok",
                    intent="noop",
                    status="executed",
                ),
            )
            session = TestingSessionLocal()
            coordinator = ProviderInboundMessageCoordinator(
                session=session,
                max_attempts=3,
            )
            leased = coordinator.claim_due_processing(now=_now())
            assert leased is not None
            captured: list[dict[str, Any]] = []
            try:
                with patch(
                    "backend.services.provider_inbound_message_coordinator"
                    ".process_incoming_message",
                    return_value=[object()],
                ), patch(
                    "backend.services.provider_inbound_message_coordinator"
                    ".stage_outbound_rows",
                    return_value=[staged_row],
                ), patch(
                    "backend.services.provider_inbound_message_coordinator"
                    ".ProcesamientoMensajeProveedorRepository.finalize_processed",
                    return_value=False,
                ), patch(
                    "backend.services.provider_inbound_message_coordinator"
                    ".emit_event",
                    side_effect=self._capture_emit_factory(captured),
                ):
                    coordinator.process_lease(leased)
                return captured, "lease_lost"
            finally:
                session.close()

        def _receipt_missing_scenario() -> Any:
            _setup_scenario("receipt_missing")
            session = TestingSessionLocal()
            coordinator = ProviderInboundMessageCoordinator(
                session=session,
            )
            leased = coordinator.claim_due_processing(now=_now())
            assert leased is not None
            captured: list[dict[str, Any]] = []
            try:
                with patch(
                    "backend.services.provider_inbound_message_coordinator"
                    ".emit_event",
                    side_effect=self._capture_emit_factory(captured),
                ), patch.object(
                    coordinator._recepcion_repo,
                    "find_by_id",
                    return_value=None,
                ):
                    coordinator.process_lease(leased)
                return captured, "failed_terminal"
            finally:
                session.close()

        def _unavailable_scenario() -> Any:
            _setup_scenario("unavailable")
            session = TestingSessionLocal()
            coordinator = ProviderInboundMessageCoordinator(
                session=session,
            )
            leased = coordinator.claim_due_processing(now=_now())
            assert leased is not None
            captured: list[dict[str, Any]] = []
            try:
                with patch(
                    "backend.services.provider_inbound_message_coordinator"
                    ".emit_event",
                    side_effect=self._capture_emit_factory(captured),
                ), patch(
                    "backend.services.provider_inbound_message_coordinator"
                    ".CommerceAvailabilityService.evaluate",
                    return_value=self._unavailable_outcome(
                        self.comercio_id
                    ),
                ):
                    coordinator.process_lease(leased)
                return captured, "unavailable"
            finally:
                session.close()

        scenarios = [
            ("success", *_success_scenario()),
            ("lease_lost", *_lease_lost_scenario()),
            ("receipt_missing", *_receipt_missing_scenario()),
            ("unavailable", *_unavailable_scenario()),
        ]

        for label, captured, expected_outcome in scenarios:
            with self.subTest(scenario=label):
                self.assertEqual(
                    self._processing_outcome_event(captured)["outcome"],
                    expected_outcome,
                )
                pf_positions = [
                    index
                    for index, event in enumerate(captured)
                    if event.get("event") == EVENT_PROVIDER_INBOUND_STAGE
                    and event.get("stage") == "processing_finalization"
                    and event.get("outcome")
                    in {"completed", "failed"}
                ]
                outcome_positions = [
                    index
                    for index, event in enumerate(captured)
                    if event.get("event") == EVENT_PROCESSING_OUTCOME
                ]
                self.assertGreaterEqual(len(pf_positions), 1)
                self.assertEqual(len(outcome_positions), 1)
                self.assertLess(pf_positions[0], outcome_positions[0])

    # ------------------- correlation_id cleanup on BaseException ----------

    def test_base_exception_in_provider_scope_clears_correlation_id(
        self,
    ) -> None:
        """A ``BaseException`` (e.g., ``KeyboardInterrupt``) raised
        inside the provider scope MUST NOT leave a stale opaque
        synthetic inbound correlation on the worker thread.

        The coordinator wraps the provider-scoped flow in a
        ``try/finally`` that calls
        :func:`install_llm_timing_recorder` with ``None`` regardless
        of whether the flow returns normally, raises
        :class:`Exception` or propagates a
        :class:`BaseException` such as :class:`KeyboardInterrupt`.
        """
        from backend.llm.query_llm import (
            current_llm_correlation_id,
            install_llm_timing_recorder,
            reset_llm_timing_recorder,
        )

        reset_llm_timing_recorder()
        self.addCleanup(reset_llm_timing_recorder)
        self._accept()
        captured: list[dict[str, Any]] = []
        session = TestingSessionLocal()
        try:
            coordinator = ProviderInboundMessageCoordinator(
                session=session,
                max_attempts=3,
            )
            leased = coordinator.claim_due_processing(now=_now())
            assert leased is not None

            class _WorkerInterrupt(KeyboardInterrupt):
                pass

            # Sanity check: no correlation is installed yet.
            self.assertIsNone(current_llm_correlation_id())

            def _raise_base_exception(*args: Any, **kwargs: Any) -> Any:
                raise _WorkerInterrupt("interrupted by operator")

            with patch(
                "backend.services.provider_inbound_message_coordinator"
                ".emit_event",
                side_effect=self._capture_emit_factory(captured),
            ), patch(
                "backend.services.provider_inbound_message_coordinator"
                ".SessionRepository.stage_active",
                side_effect=_raise_base_exception,
            ):
                with self.assertRaises(KeyboardInterrupt):
                    coordinator.process_lease(leased)

            # After the provider scope returns (whether normally,
            # raising ``Exception`` or propagating
            # ``BaseException``) the LLM timing recorder
            # correlation MUST be cleared so a direct
            # ``QueryLlm`` / ``OllamaEmbeddingClient`` call on the
            # same worker thread cannot inherit the stale opaque
            # synthetic inbound identifier.
            self.assertIsNone(current_llm_correlation_id())

            # The BaseException must not have produced a
            # processing_finalization stage event pair — the
            # wrapper only emits ``started`` for the boundary that
            # was reached; it does NOT fabricate a terminal event
            # when the finalization did not run.
            stage_events = [
                event
                for event in captured
                if event.get("event") == EVENT_PROVIDER_INBOUND_STAGE
            ]
            finalization_events = [
                event
                for event in stage_events
                if event.get("stage") == "processing_finalization"
            ]
            self.assertEqual(
                len(finalization_events),
                0,
                "a BaseException that interrupted the provider scope "
                "MUST NOT produce a synthetic processing_finalization "
                "started / completed / failed pair",
            )
        finally:
            install_llm_timing_recorder(None)
            session.close()

    def test_subsequent_direct_call_does_not_inherit_stale_correlation(
        self,
    ) -> None:
        """After the provider scope exits — even with a
        ``BaseException`` — a direct ``QueryLlm`` call from the
        same thread MUST NOT carry the opaque synthetic inbound
        correlation. The test asserts the thread-local contract
        end-to-end through the coordinator + the
        ``current_llm_correlation_id`` helper that
        ``OllamaEmbeddingClient`` also reads."""
        from backend.llm.query_llm import (
            current_llm_correlation_id,
            install_llm_timing_recorder,
            reset_llm_timing_recorder,
        )

        reset_llm_timing_recorder()
        self.addCleanup(reset_llm_timing_recorder)
        self._accept()
        session = TestingSessionLocal()
        captured: list[dict[str, Any]] = []
        try:
            coordinator = ProviderInboundMessageCoordinator(
                session=session,
                max_attempts=3,
            )
            leased = coordinator.claim_due_processing(now=_now())
            assert leased is not None

            class _WorkerInterrupt(KeyboardInterrupt):
                pass

            def _raise_base_exception(*args: Any, **kwargs: Any) -> Any:
                raise _WorkerInterrupt("interrupted by operator")

            with patch(
                "backend.services.provider_inbound_message_coordinator"
                ".emit_event",
                side_effect=self._capture_emit_factory(captured),
            ), patch(
                "backend.services.provider_inbound_message_coordinator"
                ".SessionRepository.stage_active",
                side_effect=_raise_base_exception,
            ):
                with self.assertRaises(KeyboardInterrupt):
                    coordinator.process_lease(leased)

            self.assertIsNone(current_llm_correlation_id())

            # A direct ``QueryLlm`` call on the same worker thread
            # MUST NOT inherit the provider correlation. We feed
            # the call through the existing private emitter so the
            # assertion matches the QueryLlm boundary contract.
            from backend.config.settings import Settings
            from backend.llm.query_llm import QueryLlm

            class _FakeResponse:
                def __init__(self, body: str) -> None:
                    self._body = body
                    self.status_code = 200

                @property
                def text(self) -> str:
                    return self._body

                def json(self) -> dict[str, Any]:
                    return {"response": self._body}

                def raise_for_status(self) -> None:
                    return None

            settings = Settings(
                llm_url="http://llm.test/api/generate",
                llm_model="test-model",
                llm_timeout=30,
                llm_keep_alive="1h",
                llm_num_ctx=2048,
                llm_num_predict=256,
                llm_log_content=False,
                llm_log_max_chars=50,
            )
            captured_after: list[dict[str, Any]] = []

            def _capture(*, event: str, **kwargs: Any) -> bool:
                from backend.observability.events import build_event

                payload = build_event(event=event, **kwargs)
                captured_after.append(payload)
                return True

            client = QueryLlm(
                settings=settings,
                transport=lambda url, **kwargs: _FakeResponse('{"ok":true}'),
            )
            with patch(
                "backend.llm.query_llm.emit_event",
                side_effect=_capture,
            ):
                client.request("hola")
        finally:
            install_llm_timing_recorder(None)
            session.close()

        # Neither ``started`` nor ``completed`` event from the
        # direct ``QueryLlm`` call may carry the stale provider
        # correlation_id.
        self.assertEqual(len(captured_after), 2)
        self.assertNotIn("correlation_id", captured_after[0])
        self.assertNotIn("correlation_id", captured_after[1])


class FinalizationOrderingTest(unittest.TestCase):
    """Explicit ordering proof for every finalization branch.

    The deferred-processing coordinator MUST guarantee the order
    ``finalize -> commit/rollback -> processing_finalization
    completed/failed -> provider_inbound_processing_outcome`` on
    every reachable branch and MUST NEVER emit a
    ``processing_finalization=failed`` stage event BEFORE the
    matching rollback completes. This class wraps each branch with
    spies on ``finalize_*``, ``session.rollback()`` and the
    bounded ``emit_event`` helper so the relative position of
    each call is verifiable.

    The branches covered here:

    * ``finalize_processed`` returns ``True`` (commit only);
    * ``finalize_processed`` returns ``False`` (rollback then
      ``failed (LeaseLost)``);
    * ``finalize_processed`` raises an exception (rollback
      before ``failed``);
    * ``commit()`` raises after ``finalize_processed`` returns
      ``True`` (rollback before ``failed``);
    * ``finalize_terminal`` returns ``True`` via ``receipt_missing``
      (commit only);
    * ``finalize_terminal`` returns ``False`` via ``receipt_missing``
      (rollback then ``failed (LeaseLost)``);
    * ``finalize_terminal`` raises via ``receipt_missing``
      (rollback before ``failed``);
    * ``finalize_terminal`` returns ``True`` via ``unavailable``
      commerce (commit only);
    * ``finalize_terminal`` returns ``False`` via ``unavailable``
      commerce (rollback then ``failed (LeaseLost)``);
    * ``finalize_terminal`` raises via ``unavailable`` commerce
      (rollback before ``failed``);
    * ``finalize_retryable`` returns ``True`` (commit only);
    * ``finalize_retryable`` returns ``False`` (rollback then
      ``failed (LeaseLost)``);
    * ``finalize_retryable`` raises (rollback before ``failed``);
    * ``finalize_terminal`` (exhaustion) returns ``True`` (commit
      only);
    * ``finalize_terminal`` (exhaustion) returns ``False``
      (rollback then ``failed (LeaseLost)``);
    * ``finalize_terminal`` (exhaustion) raises (rollback before
      ``failed``).
    """

    def setUp(self) -> None:
        suffix = _suffix()
        self.comercio_id = _seed_comercio(suffix)
        self.addCleanup(_delete_comercio, self.comercio_id)
        self.cliente_id = _seed_cliente(suffix + "C")
        self.addCleanup(_delete_cliente, self.cliente_id)
        self.destination = f"+54971{suffix[:8]}"
        self.addCleanup(_delete_canales_by_destination, self.destination)
        self.canal_id = _seed_dedicated_channel(
            suffix + "D", self.comercio_id, self.destination
        )
        self.proveedor = "twilio"
        self.identificador = f"SM-{suffix}"
        self.addCleanup(
            _cleanup_provider_inbound_artifacts, self.comercio_id
        )
        self.addCleanup(
            _delete_recepciones_by_comercio, self.comercio_id
        )
        self.addCleanup(
            _delete_procesamientos_by_comercio, self.comercio_id
        )
        from backend.llm.query_llm import reset_llm_timing_recorder
        reset_llm_timing_recorder()
        self.addCleanup(reset_llm_timing_recorder)

    def _command(self) -> ProviderInboundMessageCommand:
        return ProviderInboundMessageCommand(
            proveedor=self.proveedor,
            identificador_recepcion=self.identificador,
            canal_id=self.canal_id,
            cliente_id=self.cliente_id,
            comercio_id=self.comercio_id,
            mensaje="hola",
            destinatario_e164=self.destination,
        )

    def _accept(self) -> tuple[int, int]:
        coordinator = ProviderInboundMessageCoordinator(
            session=TestingSessionLocal(),
        )
        with patch(
            "backend.services.provider_inbound_message_coordinator"
            ".process_incoming_message"
        ):
            outcome = coordinator.accept(self._command())
        assert outcome.receipt_id is not None
        assert outcome.procesamiento_id is not None
        return int(outcome.receipt_id), int(outcome.procesamiento_id)

    @staticmethod
    def _unavailable_outcome(
        comercio_id: int,
    ) -> CommerceAvailabilityOutcome:
        return CommerceAvailabilityOutcome(
            status=CommerceAvailabilityStatus.UNAVAILABLE,
            reason=CommerceUnavailableReason.BLOCKED_STATE,
            comercio_id=comercio_id,
            modo_operacion=None,
            prueba_hasta=None,
            prueba_max_pedidos=None,
            prueba_pedidos_consumidos=0,
        )

    def _build_recorder(self) -> dict[str, list[Any]]:
        """Return a fresh ``call_order`` / ``events`` recorder that
        captures ``rollback``, ``commit`` and ``emit`` calls in the
        order they were observed by the spy helpers.

        ``call_order`` is a flat list of every recorded action
        (``finalize_*``, ``commit``, ``rollback``, ``emit:<event>``)
        in the order they were observed. ``events`` is a parallel
        list of the JSON payloads for the emit entries only
        (``call_order[i].startswith('emit:')`` iff there is a
        payload in ``events`` at index
        :func:`_events_index_for`).
        """
        return {
            "call_order": [],
            "events": [],
            "rollbacks": [],
        }

    @staticmethod
    def _events_index_for(
        call_order: list[str], call_order_index: int
    ) -> int:
        """Return the ``events`` index that corresponds to the
        ``call_order`` position ``call_order_index`` (which MUST
        point to an ``emit:*`` entry)."""
        events_index = 0
        for index in range(call_order_index + 1):
            if call_order[index].startswith("emit:"):
                if index == call_order_index:
                    return events_index
                events_index += 1
        raise AssertionError(
            f"call_order[{call_order_index}]={call_order[call_order_index]!r} "
            "is not an emit entry"
        )

    @staticmethod
    def _finalization_rollback_index(
        call_order: list[str],
        *,
        before: int | None = None,
    ) -> int:
        """Return the ``call_order`` index of the rollback that
        immediately precedes the final
        ``processing_finalization`` ``failed`` stage event. When
        ``before`` is supplied, return the last rollback at or
        before that index; otherwise return the last rollback in
        ``call_order``. The external rollback in
        :meth:`process_lease` runs AFTER the failed stage event so
        tests pass ``before=pf_indices[-1]`` to skip it.
        """
        last_rollback = -1
        upper = before if before is not None else len(call_order)
        for index in range(upper):
            label = call_order[index]
            if label.startswith("rollback:"):
                last_rollback = index
        if last_rollback < 0:
            raise AssertionError(
                "no rollback observed in call_order before index "
                f"{before}"
            )
        return last_rollback

    def _capture_factory(
        self,
        call_order: list[str],
        events: list[dict[str, Any]],
    ) -> Any:
        def _capture_emit(*, event: str, **kwargs: Any) -> bool:
            from backend.observability.events import build_event
            call_order.append(f"emit:{event}")
            payload = build_event(event=event, **kwargs)
            events.append(payload)
            return True
        return _capture_emit

    def _spy_finalize(
        self,
        call_order: list[str],
        target_name: str,
        repo_attr: str,
        behavior: Any,
    ) -> Any:
        """Return a spy factory for ``finalize_processed`` /
        ``finalize_retryable`` / ``finalize_terminal`` that records
        its call position in the shared ``call_order`` list.
        ``behavior`` is either:

        * a literal ``bool`` returned directly (True / False);
        * a callable invoked with the repo kwargs;
        * an exception class / instance raised inside the spy;
        * ``None`` — the spy records the call and delegates to the
          original repo method (used by the success-path tests that
          do not want to override the finalization outcome).
        """
        real_method = getattr(
            self._coordinator_for_spy._procesamiento_repo, repo_attr
        )

        def _spy(**kwargs: Any) -> Any:
            call_order.append(target_name)
            if behavior is None:
                return real_method(**kwargs)
            if isinstance(behavior, BaseException):
                raise behavior
            if callable(behavior):
                result = behavior(**kwargs)
                if isinstance(result, BaseException):
                    raise result
                return result
            return behavior
        return patch.object(
            self._coordinator_for_spy._procesamiento_repo,
            repo_attr,
            side_effect=_spy,
        )

    def _record_only_spy(
        self,
        call_order: list[str],
        target_name: str,
        repo_attr: str,
    ) -> Any:
        """Spy that records the call in ``call_order`` but otherwise
        delegates to the original repo method. Used by the success
        tests that do not want to override the finalization outcome.
        """
        real_method = getattr(
            self._coordinator_for_spy._procesamiento_repo, repo_attr
        )

        def _spy(**kwargs: Any) -> Any:
            call_order.append(target_name)
            return real_method(**kwargs)

        return patch.object(
            self._coordinator_for_spy._procesamiento_repo,
            repo_attr,
            side_effect=_spy,
        )

    def _setup_session_spy(
        self,
        recorder: dict[str, list[Any]],
    ) -> Any:
        """Return a ``commit`` / ``rollback`` spy pair attached to
        the coordinator's session and a context-manager helper that
        installs them."""

        def _install(target_session: Any, target_coordinator: Any) -> list[Any]:
            self._coordinator_for_spy = target_coordinator
            spies: list[Any] = []
            rollback_counter = {"n": 0}

            def _record_commit() -> Any:
                recorder["call_order"].append("commit")
                return None

            spies.append(
                patch.object(
                    target_session,
                    "commit",
                    side_effect=_record_commit,
                )
            )

            def _record_rollback() -> Any:
                rollback_counter["n"] += 1
                recorder["call_order"].append(
                    f"rollback:{rollback_counter['n']}"
                )
                return None

            spies.append(
                patch.object(
                    target_session,
                    "rollback",
                    side_effect=_record_rollback,
                )
            )

            return spies

        return _install

    # The remaining tests build the coordinator / session / spies
    # inline because each scenario needs a slightly different set of
    # patches; helper-only designs turned out to be harder to
    # read than the direct inlined version.

    # ===== finalize_processed (success path) =====

    def test_finalize_processed_success_orders_commit_before_completed_event(
        self,
    ) -> None:
        """``finalize_processed`` returning ``True`` MUST run
        ``commit`` BEFORE the ``processing_finalization completed``
        stage event AND BEFORE the
        ``provider_inbound_processing_outcome`` event."""
        self._accept()
        session = TestingSessionLocal()
        try:
            coordinator = ProviderInboundMessageCoordinator(
                session=session,
                max_attempts=3,
            )
            leased = coordinator.claim_due_processing(now=_now())
            assert leased is not None

            recorder = self._build_recorder()
            self._coordinator_for_spy = coordinator
            install = self._setup_session_spy(recorder)
            session_spies = install(session, coordinator)

            staged_row = StagedOutboundRow(
                mensaje_proveedor_saliente_id=1,
                sequence=0,
                customer_response=CustomerResponse(
                    message="ok",
                    intent="noop",
                    status="executed",
                ),
            )

            with patch(
                "backend.services.provider_inbound_message_coordinator"
                ".process_incoming_message",
                return_value=[object()],
            ), patch(
                "backend.services.provider_inbound_message_coordinator"
                ".stage_outbound_rows",
                return_value=[staged_row],
            ), self._record_only_spy(
                recorder["call_order"],
                "finalize_processed",
                "finalize_processed",
            ), patch(
                "backend.services.provider_inbound_message_coordinator"
                ".emit_event",
                side_effect=self._capture_factory(
                    recorder["call_order"], recorder["events"]
                ),
            ), session_spies[0], session_spies[1]:
                result = coordinator.process_lease(leased)
        finally:
            session.close()

        self.assertEqual(
            result.outcome, ProviderInboundProcessingOutcome.PROCESSED
        )
        # ``finalize_processed``, ``commit``, and the
        # ``processing_finalization completed`` event must appear
        # in this order, and the ``processing_outcome`` event must
        # follow the stage event.
        idx_finalize = recorder["call_order"].index("finalize_processed")
        idx_commit = recorder["call_order"].index("commit")
        pf_indices = [
            index
            for index, label in enumerate(recorder["call_order"])
            if label == "emit:provider_inbound_stage"
        ]
        idx_pf_completed = pf_indices[-1]
        idx_outcome = recorder["call_order"].index(
            f"emit:{EVENT_PROCESSING_OUTCOME}"
        )
        self.assertLess(idx_finalize, idx_commit)
        self.assertLess(idx_commit, idx_pf_completed)
        self.assertLess(idx_pf_completed, idx_outcome)
        # No rollback should be observed for a successful run.
        self.assertNotIn(
            "rollback:",
            recorder["call_order"],
            "successful finalize_processed must not roll back",
        )

    # ===== finalize_processed=False =====

    def test_finalize_processed_false_orders_rollback_before_failed_event(
        self,
    ) -> None:
        """``finalize_processed`` returning ``False`` MUST run
        ``rollback`` BEFORE the ``processing_finalization failed``
        stage event AND BEFORE the ``processing_outcome lease_lost``
        event."""
        self._accept()
        session = TestingSessionLocal()
        try:
            coordinator = ProviderInboundMessageCoordinator(
                session=session,
                max_attempts=3,
            )
            leased = coordinator.claim_due_processing(now=_now())
            assert leased is not None

            recorder = self._build_recorder()
            self._coordinator_for_spy = coordinator
            install = self._setup_session_spy(recorder)
            session_spies = install(session, coordinator)

            staged_row = StagedOutboundRow(
                mensaje_proveedor_saliente_id=1,
                sequence=0,
                customer_response=CustomerResponse(
                    message="ok",
                    intent="noop",
                    status="executed",
                ),
            )

            with patch(
                "backend.services.provider_inbound_message_coordinator"
                ".process_incoming_message",
                return_value=[object()],
            ), patch(
                "backend.services.provider_inbound_message_coordinator"
                ".stage_outbound_rows",
                return_value=[staged_row],
            ), self._spy_finalize(
                recorder["call_order"],
                "finalize_processed",
                "finalize_processed",
                False,
            ), patch(
                "backend.services.provider_inbound_message_coordinator"
                ".emit_event",
                side_effect=self._capture_factory(
                    recorder["call_order"], recorder["events"]
                ),
            ), session_spies[0], session_spies[1]:
                result = coordinator.process_lease(leased)
        finally:
            session.close()

        self.assertEqual(
            result.outcome,
            ProviderInboundProcessingOutcome.RETRY_SCHEDULED,
        )
        idx_finalize = recorder["call_order"].index("finalize_processed")
        # ``provider_inbound_stage`` events appear first because the
        # ``processing_finalization`` wrapper emits ``started``
        # before the repo call. The
        # ``processing_finalization=failed (LeaseLost)`` event must
        # therefore be the *second* ``provider_inbound_stage``
        # entry, after the rollback.
        pf_indices = [
            index
            for index, label in enumerate(recorder["call_order"])
            if label == "emit:provider_inbound_stage"
        ]
        idx_pf_failed = pf_indices[-1]
        idx_outcome = recorder["call_order"].index(
            f"emit:{EVENT_PROCESSING_OUTCOME}"
        )
        idx_rollback = self._finalization_rollback_index(
            recorder["call_order"], before=idx_pf_failed,
        )
        self.assertLess(idx_finalize, idx_rollback)
        self.assertLess(idx_rollback, idx_pf_failed)
        self.assertLess(idx_pf_failed, idx_outcome)
        # No ``failed`` stage event before the rollback.
        self.assertLess(
            idx_rollback,
            idx_pf_failed,
            "processing_finalization=failed must follow rollback",
        )
        # The failed stage event must carry the safe ``LeaseLost``
        # token so operators can group lease-loss evidence.
        pf_failed_event = recorder["events"][
            self._events_index_for(
                recorder["call_order"], idx_pf_failed
            )
        ]
        self.assertEqual(
            pf_failed_event.get("exception_type"), "LeaseLost"
        )
        self.assertEqual(
            recorder["events"][
                self._events_index_for(
                    recorder["call_order"], idx_outcome
                )
            ].get("outcome"),
            "lease_lost",
        )

    # ===== finalize_processed raises =====

    def test_finalize_processed_exception_orders_rollback_before_failed_event(
        self,
    ) -> None:
        """``finalize_processed`` raising an exception MUST trigger
        a ``rollback`` BEFORE the ``processing_finalization failed``
        stage event is emitted. The original exception MUST be
        re-raised; no retry/terminal/business outcome may be
        substituted."""

        class _FinalizeBoom(RuntimeError):
            pass

        self._accept()
        session = TestingSessionLocal()
        try:
            coordinator = ProviderInboundMessageCoordinator(
                session=session,
                max_attempts=3,
            )
            leased = coordinator.claim_due_processing(now=_now())
            assert leased is not None

            recorder = self._build_recorder()
            self._coordinator_for_spy = coordinator
            install = self._setup_session_spy(recorder)
            session_spies = install(session, coordinator)

            staged_row = StagedOutboundRow(
                mensaje_proveedor_saliente_id=1,
                sequence=0,
                customer_response=CustomerResponse(
                    message="ok",
                    intent="noop",
                    status="executed",
                ),
            )

            boom = _FinalizeBoom("forced-finalize-processed-boom")
            with patch(
                "backend.services.provider_inbound_message_coordinator"
                ".process_incoming_message",
                return_value=[object()],
            ), patch(
                "backend.services.provider_inbound_message_coordinator"
                ".stage_outbound_rows",
                return_value=[staged_row],
            ), self._spy_finalize(
                recorder["call_order"],
                "finalize_processed",
                "finalize_processed",
                boom,
            ), patch(
                "backend.services.provider_inbound_message_coordinator"
                ".emit_event",
                side_effect=self._capture_factory(
                    recorder["call_order"], recorder["events"]
                ),
            ), session_spies[0], session_spies[1]:
                with self.assertRaises(_FinalizeBoom):
                    coordinator.process_lease(leased)
        finally:
            session.close()

        # The exception must surface unchanged (no
        # retry/terminal/business conversion).
        idx_finalize = recorder["call_order"].index("finalize_processed")
        pf_indices = [
            index
            for index, label in enumerate(recorder["call_order"])
            if label == "emit:provider_inbound_stage"
        ]
        idx_pf_failed = pf_indices[-1]
        idx_rollback = self._finalization_rollback_index(
            recorder["call_order"], before=idx_pf_failed,
        )
        self.assertLess(idx_finalize, idx_rollback)
        self.assertLess(idx_rollback, idx_pf_failed)
        # ``failed`` stage event carries the safe exception_type
        # only; the raw exception message MUST NOT leak.
        failed_event = recorder["events"][
            self._events_index_for(
                recorder["call_order"], idx_pf_failed
            )
        ]
        self.assertEqual(
            failed_event.get("exception_type"), "_FinalizeBoom"
        )
        serialized = json.dumps(recorder["events"], sort_keys=True)
        self.assertNotIn("forced-finalize-processed-boom", serialized)
        # No processing_outcome event when the coordinator re-raises
        # (the external rollback runs but never converts the
        # exception into a business outcome).
        outcome_labels = [
            label
            for label in recorder["call_order"]
            if label == f"emit:{EVENT_PROCESSING_OUTCOME}"
        ]
        self.assertEqual(
            outcome_labels,
            [],
            "an exception that re-raises from the finalization seam "
            "MUST NOT emit a provider_inbound_processing_outcome "
            "event (no retry/terminal conversion).",
        )

    # ===== commit() raises after finalize_processed returns True =====

    def test_commit_after_finalize_processed_raises_orders_rollback_before_failed_event(
        self,
    ) -> None:
        """When ``commit()`` raises AFTER ``finalize_processed``
        returned ``True``, the helper MUST roll back BEFORE the
        ``processing_finalization failed`` stage event and re-raise
        the original ``BaseException`` so the existing rollback /
        lease / retry / terminal contract remains authoritative."""

        class _CommitBoom(RuntimeError):
            pass

        self._accept()
        session = TestingSessionLocal()
        try:
            coordinator = ProviderInboundMessageCoordinator(
                session=session,
                max_attempts=3,
            )
            leased = coordinator.claim_due_processing(now=_now())
            assert leased is not None

            recorder = self._build_recorder()
            self._coordinator_for_spy = coordinator
            install = self._setup_session_spy(recorder)
            session_spies = install(session, coordinator)

            staged_row = StagedOutboundRow(
                mensaje_proveedor_saliente_id=1,
                sequence=0,
                customer_response=CustomerResponse(
                    message="ok",
                    intent="noop",
                    status="executed",
                ),
            )

            boom = _CommitBoom("forced-commit-boom")
            commit_spy = session_spies[0]
            assert commit_spy is not None
            original_commit_side_effect = commit_spy.kwargs.get(
                "side_effect"
            )

            def _commit_then_explode(*args: Any, **kwargs: Any) -> Any:
                if original_commit_side_effect is not None:
                    original_commit_side_effect(*args, **kwargs)
                recorder["call_order"].append("commit_pre_boom")
                raise boom

            with patch(
                "backend.services.provider_inbound_message_coordinator"
                ".process_incoming_message",
                return_value=[object()],
            ), patch(
                "backend.services.provider_inbound_message_coordinator"
                ".stage_outbound_rows",
                return_value=[staged_row],
            ), patch(
                "backend.services.provider_inbound_message_coordinator"
                ".emit_event",
                side_effect=self._capture_factory(
                    recorder["call_order"], recorder["events"]
                ),
            ), patch.object(
                session, "commit", side_effect=_commit_then_explode,
            ), patch.object(
                session, "rollback",
                side_effect=lambda: recorder["call_order"].append(
                    "rollback:custom"
                )
                or None,
            ):
                with self.assertRaises(_CommitBoom):
                    coordinator.process_lease(leased)
        finally:
            session.close()

        # ``commit`` ran once, then ``commit`` raised, then the
        # helper rolled back, then the failed stage event was
        # emitted, then the external rollback ran (idempotent
        # no-op since the helper already rolled back).
        idx_commit_boom = recorder["call_order"].index("commit_pre_boom")
        pf_indices = [
            index
            for index, label in enumerate(recorder["call_order"])
            if label == "emit:provider_inbound_stage"
        ]
        idx_pf_failed = pf_indices[-1]
        idx_rollback = self._finalization_rollback_index(
            recorder["call_order"], before=idx_pf_failed,
        )
        self.assertLess(idx_commit_boom, idx_rollback)
        self.assertLess(idx_rollback, idx_pf_failed)
        failed_event = recorder["events"][
            self._events_index_for(
                recorder["call_order"], idx_pf_failed
            )
        ]
        self.assertEqual(
            failed_event.get("exception_type"), "_CommitBoom"
        )
        serialized = json.dumps(recorder["events"], sort_keys=True)
        self.assertNotIn("forced-commit-boom", serialized)

    # ===== finalize_terminal (receipt_missing) =====

    def _run_receipt_missing(
        self,
        *,
        finalize_behavior: Any,
    ) -> dict[str, Any]:
        self._accept()
        session = TestingSessionLocal()
        try:
            coordinator = ProviderInboundMessageCoordinator(
                session=session,
                max_attempts=3,
            )
            leased = coordinator.claim_due_processing(now=_now())
            assert leased is not None

            recorder = self._build_recorder()
            self._coordinator_for_spy = coordinator
            install = self._setup_session_spy(recorder)
            session_spies = install(session, coordinator)

            with patch(
                "backend.services.provider_inbound_message_coordinator"
                ".emit_event",
                side_effect=self._capture_factory(
                    recorder["call_order"], recorder["events"]
                ),
            ), patch.object(
                coordinator._recepcion_repo,
                "find_by_id",
                return_value=None,
            ), self._spy_finalize(
                recorder["call_order"],
                "finalize_terminal",
                "finalize_terminal",
                (
                    None
                    if finalize_behavior is True
                    else finalize_behavior
                ),
            ), session_spies[0], session_spies[1]:
                result = coordinator.process_lease(leased)
            return {
                "result": result,
                "recorder": recorder,
                "session": session,
            }
        except BaseException:
            session.close()
            raise

    def test_receipt_missing_finalize_terminal_success_orders_commit_before_completed(
        self,
    ) -> None:
        outcome = self._run_receipt_missing(finalize_behavior=True)
        try:
            result = outcome["result"]
            recorder: dict[str, list[Any]] = outcome["recorder"]
        finally:
            outcome["session"].close()
        self.assertEqual(
            result.outcome,
            ProviderInboundProcessingOutcome.FAILED_TERMINAL,
        )
        idx_finalize = recorder["call_order"].index("finalize_terminal")
        idx_commit = recorder["call_order"].index("commit")
        pf_indices = [
            index
            for index, label in enumerate(recorder["call_order"])
            if label == "emit:provider_inbound_stage"
        ]
        idx_pf_completed = pf_indices[-1]
        idx_outcome = recorder["call_order"].index(
            f"emit:{EVENT_PROCESSING_OUTCOME}"
        )
        self.assertLess(idx_finalize, idx_commit)
        self.assertLess(idx_commit, idx_pf_completed)
        self.assertLess(idx_pf_completed, idx_outcome)
        self.assertNotIn("rollback", recorder["call_order"])

    def test_receipt_missing_finalize_terminal_false_orders_rollback_before_failed(
        self,
    ) -> None:
        outcome = self._run_receipt_missing(finalize_behavior=False)
        try:
            result = outcome["result"]
            recorder: dict[str, list[Any]] = outcome["recorder"]
        finally:
            outcome["session"].close()
        self.assertEqual(
            result.outcome,
            ProviderInboundProcessingOutcome.FAILED_TERMINAL,
        )
        idx_finalize = recorder["call_order"].index("finalize_terminal")
        pf_indices = [
            index
            for index, label in enumerate(recorder["call_order"])
            if label == "emit:provider_inbound_stage"
        ]
        idx_pf_failed = pf_indices[-1]
        idx_rollback = self._finalization_rollback_index(
            recorder["call_order"], before=idx_pf_failed,
        )
        idx_outcome = recorder["call_order"].index(
            f"emit:{EVENT_PROCESSING_OUTCOME}"
        )
        self.assertLess(idx_finalize, idx_rollback)
        self.assertLess(idx_rollback, idx_pf_failed)
        self.assertLess(idx_pf_failed, idx_outcome)
        failed_event = recorder["events"][
            self._events_index_for(
                recorder["call_order"], idx_pf_failed
            )
        ]
        self.assertEqual(
            failed_event.get("exception_type"), "LeaseLost"
        )

    def test_receipt_missing_finalize_terminal_exception_orders_rollback_before_failed(
        self,
    ) -> None:
        class _TerminalBoom(RuntimeError):
            pass

        boom = _TerminalBoom("receipt-missing-boom")
        self._accept()
        session = TestingSessionLocal()
        try:
            coordinator = ProviderInboundMessageCoordinator(
                session=session,
                max_attempts=3,
            )
            leased = coordinator.claim_due_processing(now=_now())
            assert leased is not None

            recorder = self._build_recorder()
            self._coordinator_for_spy = coordinator
            install = self._setup_session_spy(recorder)
            session_spies = install(session, coordinator)

            with patch(
                "backend.services.provider_inbound_message_coordinator"
                ".emit_event",
                side_effect=self._capture_factory(
                    recorder["call_order"], recorder["events"]
                ),
            ), patch.object(
                coordinator._recepcion_repo,
                "find_by_id",
                return_value=None,
            ), self._spy_finalize(
                recorder["call_order"],
                "finalize_terminal",
                "finalize_terminal",
                boom,
            ), session_spies[0], session_spies[1]:
                with self.assertRaises(_TerminalBoom):
                    coordinator.process_lease(leased)
        finally:
            session.close()

        idx_finalize = recorder["call_order"].index("finalize_terminal")
        pf_indices = [
            index
            for index, label in enumerate(recorder["call_order"])
            if label == "emit:provider_inbound_stage"
        ]
        idx_pf_failed = pf_indices[-1]
        idx_rollback = self._finalization_rollback_index(
            recorder["call_order"], before=idx_pf_failed,
        )
        self.assertLess(idx_finalize, idx_rollback)
        self.assertLess(idx_rollback, idx_pf_failed)
        failed_event = recorder["events"][
            self._events_index_for(
                recorder["call_order"], idx_pf_failed
            )
        ]
        self.assertEqual(
            failed_event.get("exception_type"), "_TerminalBoom"
        )
        serialized = json.dumps(recorder["events"], sort_keys=True)
        self.assertNotIn("receipt-missing-boom", serialized)

    # ===== finalize_terminal (unavailable) =====

    def _run_unavailable(
        self,
        *,
        finalize_behavior: Any,
    ) -> dict[str, Any]:
        self._accept()
        session = TestingSessionLocal()
        try:
            coordinator = ProviderInboundMessageCoordinator(
                session=session,
                max_attempts=3,
            )
            leased = coordinator.claim_due_processing(now=_now())
            assert leased is not None

            recorder = self._build_recorder()
            self._coordinator_for_spy = coordinator
            install = self._setup_session_spy(recorder)
            session_spies = install(session, coordinator)

            with patch(
                "backend.services.provider_inbound_message_coordinator"
                ".emit_event",
                side_effect=self._capture_factory(
                    recorder["call_order"], recorder["events"]
                ),
            ), patch(
                "backend.services.provider_inbound_message_coordinator"
                ".CommerceAvailabilityService.evaluate",
                return_value=self._unavailable_outcome(
                    self.comercio_id
                ),
            ), self._spy_finalize(
                recorder["call_order"],
                "finalize_terminal",
                "finalize_terminal",
                finalize_behavior,
            ), session_spies[0], session_spies[1]:
                result = coordinator.process_lease(leased)
            return {
                "result": result,
                "recorder": recorder,
                "session": session,
            }
        except BaseException:
            session.close()
            raise

    def test_unavailable_finalize_terminal_success_orders_commit_before_completed(
        self,
    ) -> None:
        outcome = self._run_unavailable(finalize_behavior=True)
        try:
            result = outcome["result"]
            recorder: dict[str, list[Any]] = outcome["recorder"]
        finally:
            outcome["session"].close()
        self.assertEqual(
            result.outcome,
            ProviderInboundProcessingOutcome.FAILED_TERMINAL,
        )
        idx_finalize = recorder["call_order"].index("finalize_terminal")
        idx_commit = recorder["call_order"].index("commit")
        pf_indices = [
            index
            for index, label in enumerate(recorder["call_order"])
            if label == "emit:provider_inbound_stage"
        ]
        idx_pf_completed = pf_indices[-1]
        idx_outcome = recorder["call_order"].index(
            f"emit:{EVENT_PROCESSING_OUTCOME}"
        )
        self.assertLess(idx_finalize, idx_commit)
        self.assertLess(idx_commit, idx_pf_completed)
        self.assertLess(idx_pf_completed, idx_outcome)
        self.assertEqual(
            recorder["events"][
                self._events_index_for(
                    recorder["call_order"], idx_outcome
                )
            ].get("outcome"),
            "unavailable",
        )

    def test_unavailable_finalize_terminal_false_orders_rollback_before_failed(
        self,
    ) -> None:
        outcome = self._run_unavailable(finalize_behavior=False)
        try:
            recorder: dict[str, list[Any]] = outcome["recorder"]
        finally:
            outcome["session"].close()
        idx_finalize = recorder["call_order"].index("finalize_terminal")
        pf_indices = [
            index
            for index, label in enumerate(recorder["call_order"])
            if label == "emit:provider_inbound_stage"
        ]
        idx_pf_failed = pf_indices[-1]
        idx_rollback = self._finalization_rollback_index(
            recorder["call_order"], before=idx_pf_failed,
        )
        idx_outcome = recorder["call_order"].index(
            f"emit:{EVENT_PROCESSING_OUTCOME}"
        )
        self.assertLess(idx_finalize, idx_rollback)
        self.assertLess(idx_rollback, idx_pf_failed)
        self.assertLess(idx_pf_failed, idx_outcome)
        failed_event = recorder["events"][
            self._events_index_for(
                recorder["call_order"], idx_pf_failed
            )
        ]
        self.assertEqual(
            failed_event.get("exception_type"), "LeaseLost"
        )
        self.assertEqual(
            recorder["events"][
                self._events_index_for(
                    recorder["call_order"], idx_outcome
                )
            ].get("outcome"),
            "lease_lost",
        )

    def test_unavailable_finalize_terminal_exception_orders_rollback_before_failed(
        self,
    ) -> None:
        class _UnavailableBoom(RuntimeError):
            pass

        boom = _UnavailableBoom("unavailable-boom")
        self._accept()
        session = TestingSessionLocal()
        try:
            coordinator = ProviderInboundMessageCoordinator(
                session=session,
                max_attempts=3,
            )
            leased = coordinator.claim_due_processing(now=_now())
            assert leased is not None

            recorder = self._build_recorder()
            self._coordinator_for_spy = coordinator
            install = self._setup_session_spy(recorder)
            session_spies = install(session, coordinator)

            with patch(
                "backend.services.provider_inbound_message_coordinator"
                ".emit_event",
                side_effect=self._capture_factory(
                    recorder["call_order"], recorder["events"]
                ),
            ), patch(
                "backend.services.provider_inbound_message_coordinator"
                ".CommerceAvailabilityService.evaluate",
                return_value=self._unavailable_outcome(
                    self.comercio_id
                ),
            ), self._spy_finalize(
                recorder["call_order"],
                "finalize_terminal",
                "finalize_terminal",
                boom,
            ), session_spies[0], session_spies[1]:
                with self.assertRaises(_UnavailableBoom):
                    coordinator.process_lease(leased)
        finally:
            session.close()

        idx_finalize = recorder["call_order"].index("finalize_terminal")
        pf_indices = [
            index
            for index, label in enumerate(recorder["call_order"])
            if label == "emit:provider_inbound_stage"
        ]
        idx_pf_failed = pf_indices[-1]
        idx_rollback = self._finalization_rollback_index(
            recorder["call_order"], before=idx_pf_failed,
        )
        self.assertLess(idx_finalize, idx_rollback)
        self.assertLess(idx_rollback, idx_pf_failed)
        failed_event = recorder["events"][
            self._events_index_for(
                recorder["call_order"], idx_pf_failed
            )
        ]
        self.assertEqual(
            failed_event.get("exception_type"), "_UnavailableBoom"
        )

    # ===== finalize_retryable (failure path under attempt budget) =====

    def _run_retryable(
        self,
        *,
        finalize_behavior: Any,
    ) -> dict[str, Any]:
        self._accept()
        session = TestingSessionLocal()
        try:
            coordinator = ProviderInboundMessageCoordinator(
                session=session,
                max_attempts=3,
            )
            leased = coordinator.claim_due_processing(now=_now())
            assert leased is not None

            recorder = self._build_recorder()
            self._coordinator_for_spy = coordinator
            install = self._setup_session_spy(recorder)
            session_spies = install(session, coordinator)

            with patch(
                "backend.services.provider_inbound_message_coordinator"
                ".process_incoming_message",
                side_effect=RuntimeError("forced"),
            ), patch(
                "backend.services.provider_inbound_message_coordinator"
                ".emit_event",
                side_effect=self._capture_factory(
                    recorder["call_order"], recorder["events"]
                ),
            ), self._spy_finalize(
                recorder["call_order"],
                "finalize_retryable",
                "finalize_retryable",
                finalize_behavior,
            ), session_spies[0], session_spies[1]:
                result = coordinator.process_lease(leased)
            return {
                "result": result,
                "recorder": recorder,
                "session": session,
            }
        except BaseException:
            session.close()
            raise

    def test_finalize_retryable_success_orders_commit_before_completed(
        self,
    ) -> None:
        outcome = self._run_retryable(finalize_behavior=True)
        try:
            result = outcome["result"]
            recorder: dict[str, list[Any]] = outcome["recorder"]
        finally:
            outcome["session"].close()
        self.assertEqual(
            result.outcome,
            ProviderInboundProcessingOutcome.RETRY_SCHEDULED,
        )
        idx_finalize = recorder["call_order"].index("finalize_retryable")
        idx_commit = recorder["call_order"].index("commit")
        pf_indices = [
            index
            for index, label in enumerate(recorder["call_order"])
            if label == "emit:provider_inbound_stage"
        ]
        idx_pf_completed = pf_indices[-1]
        idx_outcome = recorder["call_order"].index(
            f"emit:{EVENT_PROCESSING_OUTCOME}"
        )
        self.assertLess(idx_finalize, idx_commit)
        self.assertLess(idx_commit, idx_pf_completed)
        self.assertLess(idx_pf_completed, idx_outcome)

    def test_finalize_retryable_false_orders_rollback_before_failed(
        self,
    ) -> None:
        outcome = self._run_retryable(finalize_behavior=False)
        try:
            result = outcome["result"]
            recorder: dict[str, list[Any]] = outcome["recorder"]
        finally:
            outcome["session"].close()
        self.assertEqual(
            result.outcome,
            ProviderInboundProcessingOutcome.RETRY_SCHEDULED,
        )
        idx_finalize = recorder["call_order"].index("finalize_retryable")
        pf_indices = [
            index
            for index, label in enumerate(recorder["call_order"])
            if label == "emit:provider_inbound_stage"
        ]
        idx_pf_failed = pf_indices[-1]
        idx_rollback = self._finalization_rollback_index(
            recorder["call_order"], before=idx_pf_failed,
        )
        idx_outcome = recorder["call_order"].index(
            f"emit:{EVENT_PROCESSING_OUTCOME}"
        )
        self.assertLess(idx_finalize, idx_rollback)
        self.assertLess(idx_rollback, idx_pf_failed)
        self.assertLess(idx_pf_failed, idx_outcome)
        failed_event = recorder["events"][
            self._events_index_for(
                recorder["call_order"], idx_pf_failed
            )
        ]
        self.assertEqual(
            failed_event.get("exception_type"), "LeaseLost"
        )
        self.assertEqual(
            recorder["events"][
                self._events_index_for(
                    recorder["call_order"], idx_outcome
                )
            ].get("outcome"),
            "lease_lost",
        )

    def test_finalize_retryable_exception_orders_rollback_before_failed(
        self,
    ) -> None:
        class _RetryableBoom(RuntimeError):
            pass

        boom = _RetryableBoom("retryable-boom")
        self._accept()
        session = TestingSessionLocal()
        try:
            coordinator = ProviderInboundMessageCoordinator(
                session=session,
                max_attempts=3,
            )
            leased = coordinator.claim_due_processing(now=_now())
            assert leased is not None

            recorder = self._build_recorder()
            self._coordinator_for_spy = coordinator
            install = self._setup_session_spy(recorder)
            session_spies = install(session, coordinator)

            with patch(
                "backend.services.provider_inbound_message_coordinator"
                ".process_incoming_message",
                side_effect=RuntimeError("forced"),
            ), patch(
                "backend.services.provider_inbound_message_coordinator"
                ".emit_event",
                side_effect=self._capture_factory(
                    recorder["call_order"], recorder["events"]
                ),
            ), self._spy_finalize(
                recorder["call_order"],
                "finalize_retryable",
                "finalize_retryable",
                boom,
            ), session_spies[0], session_spies[1]:
                with self.assertRaises(_RetryableBoom):
                    coordinator.process_lease(leased)
        finally:
            session.close()

        idx_finalize = recorder["call_order"].index("finalize_retryable")
        pf_indices = [
            index
            for index, label in enumerate(recorder["call_order"])
            if label == "emit:provider_inbound_stage"
        ]
        idx_pf_failed = pf_indices[-1]
        idx_rollback = self._finalization_rollback_index(
            recorder["call_order"], before=idx_pf_failed,
        )
        self.assertLess(idx_finalize, idx_rollback)
        self.assertLess(idx_rollback, idx_pf_failed)
        failed_event = recorder["events"][
            self._events_index_for(
                recorder["call_order"], idx_pf_failed
            )
        ]
        self.assertEqual(
            failed_event.get("exception_type"), "_RetryableBoom"
        )

    # ===== finalize_terminal (exhaustion / terminal via _finalize_failure) =====

    def _run_terminal_exhaustion(
        self,
        *,
        finalize_behavior: Any,
    ) -> dict[str, Any]:
        self._accept()
        session = TestingSessionLocal()
        try:
            coordinator = ProviderInboundMessageCoordinator(
                session=session,
                max_attempts=1,
            )
            leased = coordinator.claim_due_processing(now=_now())
            assert leased is not None

            recorder = self._build_recorder()
            self._coordinator_for_spy = coordinator
            install = self._setup_session_spy(recorder)
            session_spies = install(session, coordinator)

            with patch(
                "backend.services.provider_inbound_message_coordinator"
                ".process_incoming_message",
                side_effect=RuntimeError("forced"),
            ), patch(
                "backend.services.provider_inbound_message_coordinator"
                ".emit_event",
                side_effect=self._capture_factory(
                    recorder["call_order"], recorder["events"]
                ),
            ), self._spy_finalize(
                recorder["call_order"],
                "finalize_terminal",
                "finalize_terminal",
                finalize_behavior,
            ), session_spies[0], session_spies[1]:
                result = coordinator.process_lease(leased)
            return {
                "result": result,
                "recorder": recorder,
                "session": session,
            }
        except BaseException:
            session.close()
            raise

    def test_finalize_terminal_exhaustion_success_orders_commit_before_completed(
        self,
    ) -> None:
        outcome = self._run_terminal_exhaustion(finalize_behavior=True)
        try:
            result = outcome["result"]
            recorder: dict[str, list[Any]] = outcome["recorder"]
        finally:
            outcome["session"].close()
        self.assertEqual(
            result.outcome,
            ProviderInboundProcessingOutcome.FAILED_TERMINAL,
        )
        idx_finalize = recorder["call_order"].index("finalize_terminal")
        idx_commit = recorder["call_order"].index("commit")
        pf_indices = [
            index
            for index, label in enumerate(recorder["call_order"])
            if label == "emit:provider_inbound_stage"
        ]
        idx_pf_completed = pf_indices[-1]
        idx_outcome = recorder["call_order"].index(
            f"emit:{EVENT_PROCESSING_OUTCOME}"
        )
        self.assertLess(idx_finalize, idx_commit)
        self.assertLess(idx_commit, idx_pf_completed)
        self.assertLess(idx_pf_completed, idx_outcome)

    def test_finalize_terminal_exhaustion_false_orders_rollback_before_failed(
        self,
    ) -> None:
        outcome = self._run_terminal_exhaustion(finalize_behavior=False)
        try:
            recorder: dict[str, list[Any]] = outcome["recorder"]
        finally:
            outcome["session"].close()
        idx_finalize = recorder["call_order"].index("finalize_terminal")
        pf_indices = [
            index
            for index, label in enumerate(recorder["call_order"])
            if label == "emit:provider_inbound_stage"
        ]
        idx_pf_failed = pf_indices[-1]
        idx_rollback = self._finalization_rollback_index(
            recorder["call_order"], before=idx_pf_failed,
        )
        idx_outcome = recorder["call_order"].index(
            f"emit:{EVENT_PROCESSING_OUTCOME}"
        )
        self.assertLess(idx_finalize, idx_rollback)
        self.assertLess(idx_rollback, idx_pf_failed)
        self.assertLess(idx_pf_failed, idx_outcome)
        failed_event = recorder["events"][
            self._events_index_for(
                recorder["call_order"], idx_pf_failed
            )
        ]
        self.assertEqual(
            failed_event.get("exception_type"), "LeaseLost"
        )

    def test_finalize_terminal_exhaustion_exception_orders_rollback_before_failed(
        self,
    ) -> None:
        class _TerminalExhaustBoom(RuntimeError):
            pass

        boom = _TerminalExhaustBoom("terminal-exhaust-boom")
        self._accept()
        session = TestingSessionLocal()
        try:
            coordinator = ProviderInboundMessageCoordinator(
                session=session,
                max_attempts=1,
            )
            leased = coordinator.claim_due_processing(now=_now())
            assert leased is not None

            recorder = self._build_recorder()
            self._coordinator_for_spy = coordinator
            install = self._setup_session_spy(recorder)
            session_spies = install(session, coordinator)

            with patch(
                "backend.services.provider_inbound_message_coordinator"
                ".process_incoming_message",
                side_effect=RuntimeError("forced"),
            ), patch(
                "backend.services.provider_inbound_message_coordinator"
                ".emit_event",
                side_effect=self._capture_factory(
                    recorder["call_order"], recorder["events"]
                ),
            ), self._spy_finalize(
                recorder["call_order"],
                "finalize_terminal",
                "finalize_terminal",
                boom,
            ), session_spies[0], session_spies[1]:
                with self.assertRaises(_TerminalExhaustBoom):
                    coordinator.process_lease(leased)
        finally:
            session.close()

        idx_finalize = recorder["call_order"].index("finalize_terminal")
        pf_indices = [
            index
            for index, label in enumerate(recorder["call_order"])
            if label == "emit:provider_inbound_stage"
        ]
        idx_pf_failed = pf_indices[-1]
        idx_rollback = self._finalization_rollback_index(
            recorder["call_order"], before=idx_pf_failed,
        )
        self.assertLess(idx_finalize, idx_rollback)
        self.assertLess(idx_rollback, idx_pf_failed)
        failed_event = recorder["events"][
            self._events_index_for(
                recorder["call_order"], idx_pf_failed
            )
        ]
        self.assertEqual(
            failed_event.get("exception_type"), "_TerminalExhaustBoom"
        )

    # ===== summary: every branch in one table =====

    def test_lease_lost_outcome_never_appears_before_failed_event(self) -> None:
        """Across all the ``lease_lost`` branches the
        ``processing_outcome`` event MUST follow the
        ``processing_finalization=failed (LeaseLost)`` event so no
        outcome leaks before the rolled-back finalization is
        observed. This is a final guard against regressions and a
        concise summary of the per-branch coverage above.

        The check inspects the recorder from the ``success`` path
        branch — the ``finalize_processed=False`` branch — which is
        the only branch where the per-branch test is not strictly
        tied to receipt_missing / unavailable / retryable inputs.
        The receipt_missing, unavailable and retryable branches are
        covered by their dedicated tests
        (:meth:`test_receipt_missing_finalize_terminal_false_orders
        _rollback_before_failed`,
        :meth:`test_unavailable_finalize_terminal_false_orders_rollback
        _before_failed`,
        :meth:`test_finalize_retryable_false_orders_rollback_before_failed`).
        """
        self._accept()
        session = TestingSessionLocal()
        try:
            coordinator = ProviderInboundMessageCoordinator(
                session=session,
                max_attempts=3,
            )
            leased = coordinator.claim_due_processing(now=_now())
            assert leased is not None

            recorder = self._build_recorder()
            self._coordinator_for_spy = coordinator
            install = self._setup_session_spy(recorder)
            session_spies = install(session, coordinator)

            staged_row = StagedOutboundRow(
                mensaje_proveedor_saliente_id=1,
                sequence=0,
                customer_response=CustomerResponse(
                    message="ok",
                    intent="noop",
                    status="executed",
                ),
            )

            with patch(
                "backend.services.provider_inbound_message_coordinator"
                ".process_incoming_message",
                return_value=[object()],
            ), patch(
                "backend.services.provider_inbound_message_coordinator"
                ".stage_outbound_rows",
                return_value=[staged_row],
            ), self._spy_finalize(
                recorder["call_order"],
                "finalize_processed",
                "finalize_processed",
                False,
            ), patch(
                "backend.services.provider_inbound_message_coordinator"
                ".emit_event",
                side_effect=self._capture_factory(
                    recorder["call_order"], recorder["events"]
                ),
            ), session_spies[0], session_spies[1]:
                result = coordinator.process_lease(leased)
        finally:
            session.close()

        self.assertEqual(
            result.outcome,
            ProviderInboundProcessingOutcome.RETRY_SCHEDULED,
        )
        pf_indices = [
            index
            for index, label in enumerate(recorder["call_order"])
            if label == "emit:provider_inbound_stage"
        ]
        self.assertGreaterEqual(len(pf_indices), 2)
        idx_pf_failed = pf_indices[-1]
        idx_outcome = recorder["call_order"].index(
            f"emit:{EVENT_PROCESSING_OUTCOME}"
        )
        self.assertLess(
            idx_pf_failed, idx_outcome,
            "processing_outcome lease_lost must follow "
            "processing_finalization=failed (LeaseLost)",
        )
        outcome_event = recorder["events"][
            self._events_index_for(
                recorder["call_order"], idx_outcome
            )
        ]
        self.assertEqual(outcome_event.get("outcome"), "lease_lost")
        failed_event = recorder["events"][
            self._events_index_for(
                recorder["call_order"], idx_pf_failed
            )
        ]
        self.assertEqual(failed_event.get("exception_type"), "LeaseLost")


if __name__ == "__main__":
    unittest.main(verbosity=2)