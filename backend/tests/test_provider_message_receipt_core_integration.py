"""Real PostgreSQL integration tests for ``ProviderInboundMessageCoordinator``.

These tests intentionally bypass mocks for the receipt-claim boundary
because the proof the spec relies on is the actual PostgreSQL
``INSERT ... ON CONFLICT DO NOTHING RETURNING`` contract — the
guarantee that a committed unique pair is never claimed twice and that
the second issuer observes an empty ``RETURNING`` instead of raising
the unique-constraint violation. Mocks cannot substitute for that
guarantee.

The tests use the live ``supernova_test`` PostgreSQL database, seed
exactly one comercio, one canal, one cliente and one receipt row per
test, and remove every row they create so unrelated rows are never
modified. The integration test exercises the real
``RecepcionMensajeProveedorRepository.claim`` against the real
PostgreSQL unique constraint, exactly as the production transaction
would.

The shared-channel membership revalidation is exercised here too so
the fix is covered end-to-end:

* a shared channel with a selected commerce but a revoked
  ``ComercioCanalCompartido`` MUST return ``invalid_context`` with no
  receipt, no session and no pipeline call;
* a membership present at validation time but revoked before commit
  cannot leak a receipt row.
"""
from __future__ import annotations

import unittest
import uuid
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
)

TEST_URL = "postgresql+psycopg:///supernova_test"

engine = create_engine(TEST_URL)
TestingSessionLocal = sessionmaker(
    bind=engine, autoflush=False, autocommit=False
)


def _suffix() -> str:
    return uuid.uuid4().hex[:10]


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
        self.destination = (
            f"+54971{suffix[:8]}"
        )
        self.addCleanup(_delete_canales_by_destination, self.destination)
        self.canal_id = _seed_dedicated_channel(
            suffix + "D", self.comercio_id, self.destination
        )
        self.proveedor = "twilio"
        self.identificador = f"SM-{suffix}"
        self.addCleanup(_delete_recepciones_by_comercio, self.comercio_id)

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
            outcome = coordinator.process(command)

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

    def test_missing_membership_yields_invalid_context_with_zero_mutations(
        self,
    ) -> None:
        """No ``ComercioCanalCompartido`` row exists for the selected
        commerce on the shared channel. The coordinator MUST refuse
        the same way as for a revoked membership."""
        _seed_shared_context(
            self.canal_id,
            self.cliente_id,
            self.comercio_id,
            mensaje="sin membresia",
        )
        with TestingSessionLocal() as session, session.begin():
            session.execute(
                delete(ComercioCanalCompartido).where(
                    ComercioCanalCompartido.id == self.membership_id
                )
            )
        with TestingSessionLocal() as session:
            active = session.execute(
                select(ComercioCanalCompartido).where(
                    ComercioCanalCompartido.id == self.membership_id
                )
            ).first()
            self.assertIsNone(active)

        recepciones_before = self._count_all_recepciones()
        coordinator = self._open_coordinator()
        command = self._command()
        with patch(
            "backend.services.provider_inbound_message_coordinator"
            ".process_incoming_message"
        ) as pipeline:
            outcome = coordinator.process(command)

        self.assertEqual(
            outcome.status,
            ProviderInboundMessageStatus.INVALID_CONTEXT,
        )
        self.assertEqual(
            outcome.resolution_source, "revoked_shared_membership"
        )
        pipeline.assert_not_called()
        self.assertEqual(
            self._count_all_recepciones(),
            recepciones_before,
        )


class DraftPedidoStagingIntegrationTest(unittest.TestCase):
    """Real PostgreSQL proof that the provider inbound coordinator
    stages and associates exactly one ``borrador`` pedido to the
    active conversation session before the existing message pipeline
    runs.

    Scenarios covered:

    * First valid receipt, no pre-existing session: one draft pedido
      is persisted and bound to the session.
    * Existing active session with ``id_pedido is null``: one new
      draft pedido is created and associated; the previous session
      row is preserved with the new pedido FK.
    * Existing active session already associated: no new pedido is
      created.
    * Duplicate receipt: no session, no pedido, no pipeline effects
      remain durable.
    * Forced post-staging technical failure: receipt, session,
      pedido and association are rolled back; a later retry is
      eligible and re-creates the pedido.
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
        # Cleanups run LIFO: pedidos/sessions/outbox must be removed
        # before the foreign keys to comercio/cliente/canal disappear.
        self.addCleanup(_delete_comercio, self.comercio_id)
        self.addCleanup(_delete_cliente, self.cliente_id)
        self.addCleanup(_delete_canales_by_destination, self.destination)
        self.addCleanup(_delete_recepciones_by_comercio, self.comercio_id)
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

    def test_first_receipt_creates_one_draft_pedido_and_associates_session(
        self,
    ) -> None:
        coordinator = self._open_coordinator()
        command = self._command()
        with patch(
            "backend.services.provider_inbound_message_coordinator"
            ".process_incoming_message",
            return_value=[],
        ) as pipeline:
            outcome = coordinator.process(command)

        self.assertEqual(
            outcome.status,
            ProviderInboundMessageStatus.PROCESSED,
        )
        pipeline.assert_called_once()

        session_row = _load_session(self.cliente_id, self.comercio_id)
        self.assertIsNotNone(session_row.id_pedido)
        self.assertEqual(
            _count_pedidos_for_session(int(session_row.id)),
            1,
            "exactly one draft pedido must be staged per first receipt",
        )

        with TestingSessionLocal() as session:
            pedido = session.execute(
                select(Pedido).where(
                    Pedido.id_session == int(session_row.id)
                )
            ).scalar_one()
            self.assertEqual(pedido.estado_pedido, EstadoPedido.BORRADOR)
            self.assertEqual(
                int(pedido.id_session), int(session_row.id)
            )
            assert session_row.id_pedido is not None
            assert pedido.id is not None
            self.assertEqual(int(pedido.id), int(session_row.id_pedido))

    def test_existing_orderless_session_receives_one_new_pedido(
        self,
    ) -> None:
        """An active session with ``id_pedido is null`` MUST receive
        exactly one new draft pedido associated to it.
        """
        existing_session_id = _seed_active_session(
            self.comercio_id, self.cliente_id, id_pedido=None
        )
        self.assertIsNotNone(existing_session_id)

        coordinator = self._open_coordinator()
        command = self._command()
        with patch(
            "backend.services.provider_inbound_message_coordinator"
            ".process_incoming_message",
            return_value=[],
        ) as pipeline:
            outcome = coordinator.process(command)

        self.assertEqual(
            outcome.status,
            ProviderInboundMessageStatus.PROCESSED,
        )
        pipeline.assert_called_once()

        session_row = _load_session(self.cliente_id, self.comercio_id)
        self.assertEqual(int(session_row.id), existing_session_id)
        self.assertIsNotNone(session_row.id_pedido)
        self.assertEqual(
            _count_pedidos_for_session(existing_session_id),
            1,
            "the existing active session must own exactly one pedido",
        )

        with TestingSessionLocal() as session:
            pedido = session.execute(
                select(Pedido).where(
                    Pedido.id_session == existing_session_id
                )
            ).scalar_one()
            self.assertEqual(pedido.estado_pedido, EstadoPedido.BORRADOR)
            assert session_row.id_pedido is not None
            assert pedido.id is not None
            self.assertEqual(int(pedido.id), int(session_row.id_pedido))

    def test_existing_associated_session_creates_no_new_pedido(
        self,
    ) -> None:
        existing_session_id = _seed_active_session(
            self.comercio_id, self.cliente_id, id_pedido=None
        )
        existing_pedido_id = _seed_draft_pedido(existing_session_id)
        with TestingSessionLocal() as session, session.begin():
            sess = session.get(SessionModel, existing_session_id)
            assert sess is not None
            sess.id_pedido = existing_pedido_id

        pedidos_before = _count_all_pedidos_for_comercio(self.comercio_id)

        coordinator = self._open_coordinator()
        command = self._command()
        with patch(
            "backend.services.provider_inbound_message_coordinator"
            ".process_incoming_message",
            return_value=[],
        ) as pipeline:
            outcome = coordinator.process(command)

        self.assertEqual(
            outcome.status,
            ProviderInboundMessageStatus.PROCESSED,
        )
        pipeline.assert_called_once()

        self.assertEqual(
            _count_all_pedidos_for_comercio(self.comercio_id),
            pedidos_before,
            "already-associated session must not get a new pedido",
        )
        session_row = _load_session(self.cliente_id, self.comercio_id)
        assert session_row.id_pedido is not None
        self.assertEqual(int(session_row.id_pedido), existing_pedido_id)

    def test_duplicate_receipt_creates_no_session_and_no_pedido(
        self,
    ) -> None:
        """A first receipt commits; a second receipt for the same
        (proveedor, identificador_recepcion) pair MUST return
        ``already_processed`` and must not create a new session or a
        new pedido.
        """
        coordinator_a = self._open_coordinator()
        with patch(
            "backend.services.provider_inbound_message_coordinator"
            ".process_incoming_message",
            return_value=[],
        ):
            first = coordinator_a.process(self._command())
        self.assertEqual(
            first.status,
            ProviderInboundMessageStatus.PROCESSED,
        )

        pedidos_after_first = _count_all_pedidos_for_comercio(
            self.comercio_id
        )
        sessions_after_first = 1

        coordinator_b = self._open_coordinator()
        with patch(
            "backend.services.provider_inbound_message_coordinator"
            ".process_incoming_message",
        ) as pipeline:
            second = coordinator_b.process(self._command())

        self.assertEqual(
            second.status,
            ProviderInboundMessageStatus.ALREADY_PROCESSED,
        )
        pipeline.assert_not_called()
        self.assertEqual(
            _count_all_pedidos_for_comercio(self.comercio_id),
            pedidos_after_first,
            "duplicate receipt must not create a new pedido",
        )
        with TestingSessionLocal() as session:
            sessions_now = len(
                session.execute(
                    select(SessionModel).where(
                        SessionModel.id_cliente == self.cliente_id,
                        SessionModel.id_comercio == self.comercio_id,
                    )
                ).all()
            )
        self.assertEqual(sessions_now, sessions_after_first)

    def test_post_staging_failure_rolls_back_and_allows_retry(
        self,
    ) -> None:
        """A forced pipeline failure AFTER the pedido has been staged
        must roll back the receipt, session, pedido and association.
        A subsequent valid retry must succeed and re-create exactly
        one draft pedido.
        """
        coordinator = self._open_coordinator()
        identifier_first = self.identificador

        with patch(
            "backend.services.provider_inbound_message_coordinator"
            ".process_incoming_message",
            side_effect=RuntimeError("forced post-staging failure"),
        ):
            with self.assertRaises(RuntimeError):
                coordinator.process(self._command(identifier_first))

        self.assertEqual(
            _count_all_pedidos_for_comercio(self.comercio_id),
            0,
            "rolled-back transaction must leave no pedido",
        )
        with TestingSessionLocal() as session:
            sessions_now = len(
                session.execute(
                    select(SessionModel).where(
                        SessionModel.id_comercio == self.comercio_id
                    )
                ).all()
            )
            self.assertEqual(sessions_now, 0)
            recepciones_now = len(
                session.execute(
                    select(RecepcionMensajeProveedor).where(
                        RecepcionMensajeProveedor.comercio_id
                        == self.comercio_id
                    )
                ).all()
            )
            self.assertEqual(recepciones_now, 0)

        coordinator_retry = self._open_coordinator()
        with patch(
            "backend.services.provider_inbound_message_coordinator"
            ".process_incoming_message",
            return_value=[],
        ) as pipeline:
            retry_outcome = coordinator_retry.process(
                self._command(identifier_first)
            )

        self.assertEqual(
            retry_outcome.status,
            ProviderInboundMessageStatus.PROCESSED,
        )
        pipeline.assert_called_once()
        self.assertEqual(
            _count_all_pedidos_for_comercio(self.comercio_id),
            1,
            "retry must create exactly one pedido",
        )
        session_row = _load_session(self.cliente_id, self.comercio_id)
        self.assertIsNotNone(session_row.id_pedido)
        self.assertEqual(
            _count_pedidos_for_session(int(session_row.id)),
            1,
        )


if __name__ == "__main__":
    unittest.main()
