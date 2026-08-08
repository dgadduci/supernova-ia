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

import unittest
import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import patch

from sqlalchemy import create_engine, delete, select, text
from sqlalchemy.orm import Session as SqlSession
from sqlalchemy.orm import sessionmaker

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
    RecepcionMensajeProveedor,
)
from backend.models import (
    Session as SessionModel,
)
from backend.repositories.recepcion_mensaje_proveedor_repository import (
    RecepcionMensajeProveedorRepository,
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
            select(EstadoComercio.id).where(EstadoComercio.estado == nombre)
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


if __name__ == "__main__":
    unittest.main(verbosity=2)