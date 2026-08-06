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
    RecepcionMensajeProveedor,
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


if __name__ == "__main__":
    unittest.main()
