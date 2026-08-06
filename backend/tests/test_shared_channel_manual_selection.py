"""Focused tests for the Phase-5.3 manual commerce-selection and switch surface.

Covers:

* persistence layer (extra column ``comercio_id_cambio_pendiente``,
  restrictive FK, nullable column, new index);
* the manual selection / switch service decision table (every typed
  outcome);
* channel-scoped isolation of manual options and switch staging
  (memberships from another channel are never selectable);
* the byte-for-byte preservation of ``mensaje_original_pendiente``
  across every transition;
* the stale-target fail-closed behaviour at confirmation time;
* the targeted commerce replacement at confirmation and the targeted
  clearing at cancellation;
* the static no-transaction / no-pipeline boundaries on the repository
  and on each service entry point.

Uses the live ``supernova_test`` PostgreSQL database; tests create and
remove per-test canales, comercios, memberships, clientes and context
rows so unrelated rows are never modified.
"""
from __future__ import annotations

import unittest
import uuid
from unittest.mock import MagicMock, patch

from sqlalchemy import (
    Integer,
    create_engine,
    delete,
    select,
    text,
    update,
)
from sqlalchemy.orm import sessionmaker

from backend.models import (
    CanalWhatsapp,
    Cliente,
    Comercio,
    ComercioCanalCompartido,
    ContextoClienteCanalWhatsapp,
    EstadoComercio,
)
from backend.repositories.contexto_cliente_canal_whatsapp_repository import (
    ContextoClienteCanalWhatsappRepository,
)
from backend.services.canal_whatsapp_service import CanalWhatsappService
from backend.services.exceptions import (
    InvalidSharedChannelMembershipSelection,
)
from backend.services.shared_channel_routing_service import (
    ManualSelectionStatus,
    SharedChannelRoutingService,
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


def _estado_id_inactivo() -> int:
    return _estado_id("INACTIVO")


def _seed_comercio(suffix: str | None = None, activo: bool = True) -> dict:
    suffix = suffix or _suffix()
    estado_id = _estado_id_activo() if activo else _estado_id_inactivo()
    whatsapp_digits = suffix.lower().replace("a", "0").replace(
        "b", "1"
    ).replace("c", "2").replace("d", "3").replace("e", "4").replace(
        "f", "5"
    )
    cuit = f"30-{suffix[:8]}-{suffix[8:].upper()}"
    slug = f"manual-selection-{suffix.lower()}"[:150]
    with TestingSessionLocal() as session, session.begin():
        comercio = Comercio(
            nombre_fantasia=f"Manual Selection {suffix}",
            nombre_corto=f"MS {suffix[:6]}",
            razon_social=f"Manual Selection SRL {suffix}",
            cuit=cuit,
            whatsapp=f"+54941{whatsapp_digits}",
            calle="Av. Manual",
            numero="100",
            piso_departamento=None,
            localidad="CABA",
            provincia="Buenos Aires",
            codigo_postal="C1000",
            slug=slug,
            estado_id=estado_id,
        )
        session.add(comercio)
        session.flush()
        comercio_id = int(comercio.id)
    return {"comercio_id": comercio_id, "suffix": suffix}


def _seed_cliente(suffix: str | None = None) -> dict:
    suffix = suffix or _suffix()
    whatsapp_digits = suffix.lower().replace("a", "0").replace(
        "b", "1"
    ).replace("c", "2").replace("d", "3").replace("e", "4").replace(
        "f", "5"
    )
    with TestingSessionLocal() as session, session.begin():
        cliente = Cliente(
            whatsapp=f"+54951{whatsapp_digits}",
            nombre=f"Manual Cliente {suffix}",
            domicilio=None,
            activo=True,
        )
        session.add(cliente)
        session.flush()
        cliente_id = int(cliente.id)
    return {"cliente_id": cliente_id, "suffix": suffix}


def _delete_cliente(cliente_id: int) -> None:
    with TestingSessionLocal() as session, session.begin():
        session.execute(
            delete(ContextoClienteCanalWhatsapp).where(
                ContextoClienteCanalWhatsapp.cliente_id == cliente_id
            )
        )
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
            delete(ContextoClienteCanalWhatsapp).where(
                ContextoClienteCanalWhatsapp.comercio_id_cambio_pendiente
                == comercio_id
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
            delete(CanalWhatsapp).where(
                CanalWhatsapp.destination_e164 == destination
            )
        )


def _seed_context(
    canal_id: int,
    cliente_id: int,
    *,
    comercio_id_seleccionado: int | None,
    comercio_id_cambio_pendiente: int | None = None,
    mensaje_original_pendiente: str | None = None,
) -> None:
    with TestingSessionLocal() as session, session.begin():
        session.add(
            ContextoClienteCanalWhatsapp(
                canal_id=canal_id,
                cliente_id=cliente_id,
                comercio_id_seleccionado=comercio_id_seleccionado,
                comercio_id_cambio_pendiente=comercio_id_cambio_pendiente,
                mensaje_original_pendiente=mensaje_original_pendiente,
            )
        )


def _load_context(
    canal_id: int, cliente_id: int
) -> ContextoClienteCanalWhatsapp:
    with TestingSessionLocal() as session:
        row = session.execute(
            select(ContextoClienteCanalWhatsapp).where(
                ContextoClienteCanalWhatsapp.canal_id == canal_id,
                ContextoClienteCanalWhatsapp.cliente_id == cliente_id,
            )
        ).scalar_one()
        assert row is not None
    return row


def _register_channel(
    destination: str, id_comercio_exclusivo: int | None
) -> int:
    with TestingSessionLocal() as session, session.begin():
        service = CanalWhatsappService(session)
        if id_comercio_exclusivo is None:
            canal = service.register_shared_channel(
                provider="twilio", destination=destination
            )
        else:
            canal = service.register_dedicated_channel(
                provider="twilio",
                destination=destination,
                id_comercio_exclusivo=id_comercio_exclusivo,
            )
        session.flush()
        return int(canal.id)


class ManualSelectionSchemaTest(unittest.TestCase):
    def test_pending_target_column_shape(self):
        table = ContextoClienteCanalWhatsapp.__table__
        self.assertIs(table.c.comercio_id_cambio_pendiente.nullable, True)
        self.assertIsInstance(
            table.c.comercio_id_cambio_pendiente.type, Integer
        )
        fk = next(iter(table.c.comercio_id_cambio_pendiente.foreign_keys))
        self.assertEqual(str(fk.target_fullname), "comercios.id")
        self.assertEqual(fk.ondelete, "RESTRICT")
        index_names = [idx.name for idx in table.indexes]
        self.assertIn(
            "ix_contextos_clientes_canales_whatsapp_cambio_pendiente",
            index_names,
        )

    def test_pending_target_database_columns(self):
        with engine.connect() as c:
            column = c.execute(
                text(
                    "SELECT data_type, is_nullable FROM "
                    "information_schema.columns WHERE table_name="
                    "'contextos_clientes_canales_whatsapp' AND "
                    "column_name='comercio_id_cambio_pendiente'"
                )
            ).first()
            self.assertIsNotNone(column)
            assert column is not None
            self.assertEqual(column[0], "integer")
            self.assertEqual(column[1], "YES")
            fk_name = c.execute(
                text(
                    "SELECT conname FROM pg_constraint WHERE "
                    "conrelid="
                    "'public.contextos_clientes_canales_whatsapp'"
                    "::regclass AND contype='f' AND conname="
                    "'contextos_clientes_canales_whatsapp"
                    "_cambio_pendiente_fk'"
                )
            ).first()
            self.assertIsNotNone(fk_name)
            index_name = c.execute(
                text(
                    "SELECT indexname FROM pg_indexes WHERE tablename="
                    "'contextos_clientes_canales_whatsapp' AND "
                    "indexname="
                    "'ix_contextos_clientes_canales_whatsapp"
                    "_cambio_pendiente'"
                )
            ).first()
            self.assertIsNotNone(index_name)


class ManualSelectionServiceArgumentTest(unittest.TestCase):
    def test_list_manual_options_invalid_canal(self):
        with TestingSessionLocal() as session:
            service = SharedChannelRoutingService(session)
            for bad in (0, -1, None, "1", True):
                with self.subTest(value=bad):
                    with self.assertRaises(
                        InvalidSharedChannelMembershipSelection
                    ):
                        service.list_manual_options(
                            canal_id=bad,  # type: ignore[arg-type]
                            cliente_id=1,
                        )

    def test_select_manual_invalid_membership(self):
        with TestingSessionLocal() as session:
            service = SharedChannelRoutingService(session)
            for bad in (0, -1, None, "1", True):
                with self.subTest(value=bad):
                    with self.assertRaises(
                        InvalidSharedChannelMembershipSelection
                    ):
                        service.select_manual(
                            canal_id=1,
                            cliente_id=1,
                            membership_id=bad,  # type: ignore[arg-type]
                        )

    def test_invalid_cliente_id_raises(self):
        with TestingSessionLocal() as session:
            service = SharedChannelRoutingService(session)
            for bad in (0, -1, None, "1", True):
                with self.subTest(value=bad):
                    with self.assertRaises(
                        InvalidSharedChannelMembershipSelection
                    ):
                        service.list_manual_options(
                            canal_id=1,
                            cliente_id=bad,  # type: ignore[arg-type]
                        )


class ManualSelectionChannelBase(unittest.TestCase):
    def setUp(self):
        suffix = _suffix()
        self.comercio_a = _seed_comercio(suffix=suffix + "A")
        self.addCleanup(_delete_comercio, self.comercio_a["comercio_id"])
        self.comercio_b = _seed_comercio(suffix=suffix + "B")
        self.addCleanup(_delete_comercio, self.comercio_b["comercio_id"])
        self.inactive_comercio = _seed_comercio(
            suffix=suffix + "X", activo=False
        )
        self.addCleanup(
            _delete_comercio, self.inactive_comercio["comercio_id"]
        )
        self.cliente = _seed_cliente(suffix=suffix + "C")
        self.addCleanup(_delete_cliente, self.cliente["cliente_id"])
        self.dest_counter = 0
        self.destinations: list[str] = []

    def new_shared_channel(self, suffix_hex: str) -> dict:
        self.dest_counter += 1
        destination = (
            f"+54981{(int(suffix_hex, 16) * 1000 + self.dest_counter) % 10_000_000:07d}"
        )
        self.destinations.append(destination)
        self.addCleanup(_delete_canales_by_destination, destination)
        canal_id = _register_channel(destination, id_comercio_exclusivo=None)
        return {"canal_id": canal_id, "destination": destination}

    def new_dedicated_channel(self, suffix_hex: str) -> dict:
        self.dest_counter += 1
        destination = (
            f"+54971{(int(suffix_hex, 16) * 1000 + self.dest_counter) % 10_000_000:07d}"
        )
        self.destinations.append(destination)
        self.addCleanup(_delete_canales_by_destination, destination)
        canal_id = _register_channel(
            destination,
            id_comercio_exclusivo=self.comercio_a["comercio_id"],
        )
        return {"canal_id": canal_id, "destination": destination}


class ManualSelectionOptionsTest(ManualSelectionChannelBase):
    def test_options_lists_only_active_memberships_with_active_comercios(
        self,
    ):
        canal = self.new_shared_channel(self.comercio_a["suffix"])
        code_a = f"M1-{self.comercio_a['suffix'][:6]}"
        code_b = f"M2-{self.comercio_b['suffix'][:6]}"
        code_inactive = f"M3-{self.inactive_comercio['suffix'][:6]}"
        with TestingSessionLocal() as session, session.begin():
            service = CanalWhatsappService(session)
            service.register_shared_membership(
                canal_id=canal["canal_id"],
                comercio_id=self.comercio_a["comercio_id"],
                routing_code=code_a,
            )
            service.register_shared_membership(
                canal_id=canal["canal_id"],
                comercio_id=self.comercio_b["comercio_id"],
                routing_code=code_b,
            )
            session.flush()
            session.add(
                ComercioCanalCompartido(
                    canal_id=canal["canal_id"],
                    comercio_id=self.inactive_comercio["comercio_id"],
                    routing_code=code_inactive,
                    routing_code_normalizado=code_inactive,
                    activo=False,
                )
            )
        with TestingSessionLocal() as session:
            service = SharedChannelRoutingService(session)
            outcome = service.list_manual_options(
                canal_id=canal["canal_id"],
                cliente_id=self.cliente["cliente_id"],
            )
            self.assertEqual(
                outcome.status,
                ManualSelectionStatus.OPTIONS_AVAILABLE,
            )
            option_comercios = {
                int(opt.comercio_id) for opt in outcome.options
            }
            self.assertEqual(
                option_comercios,
                {
                    self.comercio_a["comercio_id"],
                    self.comercio_b["comercio_id"],
                },
            )

    def test_options_is_channel_scoped(self):
        canal_a = self.new_shared_channel(self.comercio_a["suffix"])
        canal_b = self.new_shared_channel(self.comercio_b["suffix"])
        code_a = f"M4-{self.comercio_a['suffix'][:6]}"
        code_b = f"M5-{self.comercio_b['suffix'][:6]}"
        with TestingSessionLocal() as session, session.begin():
            service = CanalWhatsappService(session)
            service.register_shared_membership(
                canal_id=canal_a["canal_id"],
                comercio_id=self.comercio_a["comercio_id"],
                routing_code=code_a,
            )
            service.register_shared_membership(
                canal_id=canal_b["canal_id"],
                comercio_id=self.comercio_b["comercio_id"],
                routing_code=code_b,
            )
        with TestingSessionLocal() as session:
            service = SharedChannelRoutingService(session)
            outcome_a = service.list_manual_options(
                canal_id=canal_a["canal_id"],
                cliente_id=self.cliente["cliente_id"],
            )
            outcome_b = service.list_manual_options(
                canal_id=canal_b["canal_id"],
                cliente_id=self.cliente["cliente_id"],
            )
            option_a = {int(o.comercio_id) for o in outcome_a.options}
            option_b = {int(o.comercio_id) for o in outcome_b.options}
            self.assertEqual(option_a, {self.comercio_a["comercio_id"]})
            self.assertEqual(option_b, {self.comercio_b["comercio_id"]})

    def test_select_manual_foreign_membership_returns_unknown(self):
        canal_a = self.new_shared_channel(self.comercio_a["suffix"])
        canal_b = self.new_shared_channel(self.comercio_b["suffix"])
        code_b = f"M6-{self.comercio_b['suffix'][:6]}"
        with TestingSessionLocal() as session, session.begin():
            service = CanalWhatsappService(session)
            service.register_shared_membership(
                canal_id=canal_b["canal_id"],
                comercio_id=self.comercio_b["comercio_id"],
                routing_code=code_b,
            )
            foreign_membership = service.register_shared_membership(
                canal_id=canal_b["canal_id"],
                comercio_id=self.comercio_b["comercio_id"],
                routing_code=f"M6B-{self.comercio_b['suffix'][:6]}",
            )
            session.flush()
            foreign_membership_id = int(foreign_membership.id)
        _seed_context(
            canal_a["canal_id"],
            self.cliente["cliente_id"],
            comercio_id_seleccionado=None,
            mensaje_original_pendiente="texto base",
        )
        with TestingSessionLocal() as session:
            service = SharedChannelRoutingService(session)
            outcome = service.select_manual(
                canal_id=canal_a["canal_id"],
                cliente_id=self.cliente["cliente_id"],
                membership_id=foreign_membership_id,
            )
            self.assertEqual(
                outcome.status,
                ManualSelectionStatus.UNKNOWN_OR_INACTIVE_MEMBERSHIP,
            )
            self.assertEqual(
                outcome.resolution_source, "membership_lookup"
            )
            self.assertIsNone(outcome.comercio_id_seleccionado)
        persisted = _load_context(
            canal_a["canal_id"], self.cliente["cliente_id"]
        )
        self.assertIsNone(persisted.comercio_id_seleccionado)
        self.assertEqual(
            persisted.mensaje_original_pendiente, "texto base"
        )

    def test_list_manual_options_dedicated_channel_returns_invalid_mode(
        self,
    ):
        canal = self.new_dedicated_channel(self.comercio_a["suffix"])
        _seed_context(
            canal["canal_id"],
            self.cliente["cliente_id"],
            comercio_id_seleccionado=self.comercio_a["comercio_id"],
            comercio_id_cambio_pendiente=self.comercio_b["comercio_id"],
            mensaje_original_pendiente="texto dedicado",
        )
        with TestingSessionLocal() as session:
            service = SharedChannelRoutingService(session)
            outcome = service.list_manual_options(
                canal_id=canal["canal_id"],
                cliente_id=self.cliente["cliente_id"],
            )
            self.assertEqual(
                outcome.status,
                ManualSelectionStatus.INVALID_CHANNEL_MODE,
            )
            self.assertEqual(outcome.resolution_source, "channel_mode")
            self.assertEqual(outcome.options, ())
            self.assertEqual(
                outcome.comercio_id_seleccionado,
                self.comercio_a["comercio_id"],
            )
            self.assertEqual(
                outcome.comercio_id_cambio_pendiente,
                self.comercio_b["comercio_id"],
            )
            self.assertEqual(
                outcome.mensaje_original_pendiente, "texto dedicado"
            )

        persisted = _load_context(
            canal["canal_id"], self.cliente["cliente_id"]
        )
        self.assertEqual(
            int(persisted.comercio_id_seleccionado),
            self.comercio_a["comercio_id"],
        )
        self.assertEqual(
            int(persisted.comercio_id_cambio_pendiente),
            self.comercio_b["comercio_id"],
        )
        self.assertEqual(
            persisted.mensaje_original_pendiente, "texto dedicado"
        )


class ManualSelectionTest(ManualSelectionChannelBase):
    def test_select_manual_first_selection_preserves_message_byte_for_byte(
        self,
    ):
        canal = self.new_shared_channel(self.comercio_a["suffix"])
        code_a = f"M7-{self.comercio_a['suffix'][:6]}"
        with TestingSessionLocal() as session, session.begin():
            service = CanalWhatsappService(session)
            membership = service.register_shared_membership(
                canal_id=canal["canal_id"],
                comercio_id=self.comercio_a["comercio_id"],
                routing_code=code_a,
            )
            session.flush()
            membership_id = int(membership.id)
        raw = (
            "PIZZA-001\n  con orégano 🥚 y emojis   🎉\t"
            "y multilinea sin tocar\n\n"
        )
        _seed_context(
            canal["canal_id"],
            self.cliente["cliente_id"],
            comercio_id_seleccionado=None,
            mensaje_original_pendiente=raw,
        )
        with TestingSessionLocal() as session, session.begin():
            service = SharedChannelRoutingService(session)
            outcome = service.select_manual(
                canal_id=canal["canal_id"],
                cliente_id=self.cliente["cliente_id"],
                membership_id=membership_id,
            )
            self.assertEqual(
                outcome.status, ManualSelectionStatus.SELECTED
            )
            self.assertEqual(
                outcome.comercio_id_seleccionado,
                self.comercio_a["comercio_id"],
            )
            self.assertEqual(
                outcome.mensaje_original_pendiente, raw
            )
            session.flush()
            persisted = service._contexto_repo.find_by_canal_and_cliente(
                canal["canal_id"], self.cliente["cliente_id"]
            )
            self.assertIsNotNone(persisted)
            assert persisted is not None
            self.assertEqual(
                persisted.mensaje_original_pendiente, raw
            )
            self.assertEqual(
                int(persisted.comercio_id_seleccionado),
                self.comercio_a["comercio_id"],
            )
            self.assertIsNone(persisted.comercio_id_cambio_pendiente)

    def test_select_manual_same_selection_is_idempotent(self):
        canal = self.new_shared_channel(self.comercio_a["suffix"])
        code_a = f"M8-{self.comercio_a['suffix'][:6]}"
        with TestingSessionLocal() as session, session.begin():
            service = CanalWhatsappService(session)
            membership = service.register_shared_membership(
                canal_id=canal["canal_id"],
                comercio_id=self.comercio_a["comercio_id"],
                routing_code=code_a,
            )
            session.flush()
            membership_id = int(membership.id)
        first_text = "primer texto  🥚"
        _seed_context(
            canal["canal_id"],
            self.cliente["cliente_id"],
            comercio_id_seleccionado=None,
            mensaje_original_pendiente=first_text,
        )
        with TestingSessionLocal() as session, session.begin():
            service = SharedChannelRoutingService(session)
            first = service.select_manual(
                canal_id=canal["canal_id"],
                cliente_id=self.cliente["cliente_id"],
                membership_id=membership_id,
            )
            self.assertEqual(
                first.status, ManualSelectionStatus.SELECTED
            )
            second = service.select_manual(
                canal_id=canal["canal_id"],
                cliente_id=self.cliente["cliente_id"],
                membership_id=membership_id,
            )
            self.assertEqual(
                second.status, ManualSelectionStatus.ALREADY_SELECTED
            )
            self.assertEqual(
                second.mensaje_original_pendiente, first_text
            )

    def test_select_manual_inactive_membership_returns_unknown(self):
        canal = self.new_shared_channel(self.comercio_a["suffix"])
        code_a = f"M9-{self.comercio_a['suffix'][:6]}"
        with TestingSessionLocal() as session, session.begin():
            service = CanalWhatsappService(session)
            membership = service.register_shared_membership(
                canal_id=canal["canal_id"],
                comercio_id=self.comercio_a["comercio_id"],
                routing_code=code_a,
            )
            session.flush()
            membership_id = int(membership.id)
            service.deactivate_shared_membership(
                canal_id=canal["canal_id"], routing_code=code_a
            )
        _seed_context(
            canal["canal_id"],
            self.cliente["cliente_id"],
            comercio_id_seleccionado=None,
            mensaje_original_pendiente="texto inicial",
        )
        with TestingSessionLocal() as session:
            service = SharedChannelRoutingService(session)
            outcome = service.select_manual(
                canal_id=canal["canal_id"],
                cliente_id=self.cliente["cliente_id"],
                membership_id=membership_id,
            )
            self.assertEqual(
                outcome.status,
                ManualSelectionStatus.UNKNOWN_OR_INACTIVE_MEMBERSHIP,
            )

    def test_select_manual_inactive_comercio_returns_unavailable(self):
        canal = self.new_shared_channel(self.comercio_a["suffix"])
        code_a = f"MA-{self.comercio_a['suffix'][:6]}"
        with TestingSessionLocal() as session, session.begin():
            session.add(
                ComercioCanalCompartido(
                    canal_id=canal["canal_id"],
                    comercio_id=self.inactive_comercio["comercio_id"],
                    routing_code=code_a,
                    routing_code_normalizado=code_a,
                    activo=True,
                )
            )
            session.flush()
            membership_id = int(
                session.execute(
                    select(ComercioCanalCompartido.id).where(
                        ComercioCanalCompartido.canal_id
                        == canal["canal_id"],
                        ComercioCanalCompartido.comercio_id
                        == self.inactive_comercio["comercio_id"],
                    )
                ).scalar_one()
            )
        _seed_context(
            canal["canal_id"],
            self.cliente["cliente_id"],
            comercio_id_seleccionado=None,
            mensaje_original_pendiente="texto inicial",
        )
        with TestingSessionLocal() as session:
            service = SharedChannelRoutingService(session)
            outcome = service.select_manual(
                canal_id=canal["canal_id"],
                cliente_id=self.cliente["cliente_id"],
                membership_id=membership_id,
            )
            self.assertEqual(
                outcome.status,
                ManualSelectionStatus.UNAVAILABLE_COMMERCE,
            )

    def test_select_manual_existing_different_selection_requires_switch(
        self,
    ):
        canal = self.new_shared_channel(self.comercio_a["suffix"])
        code_a = f"MB-{self.comercio_a['suffix'][:6]}"
        code_b = f"MC-{self.comercio_b['suffix'][:6]}"
        with TestingSessionLocal() as session, session.begin():
            service = CanalWhatsappService(session)
            membership_a = service.register_shared_membership(
                canal_id=canal["canal_id"],
                comercio_id=self.comercio_a["comercio_id"],
                routing_code=code_a,
            )
            membership_b = service.register_shared_membership(
                canal_id=canal["canal_id"],
                comercio_id=self.comercio_b["comercio_id"],
                routing_code=code_b,
            )
            session.flush()
            membership_a_id = int(membership_a.id)
            session.flush()
            membership_b_id = int(membership_b.id)
        _seed_context(
            canal["canal_id"],
            self.cliente["cliente_id"],
            comercio_id_seleccionado=self.comercio_a["comercio_id"],
            mensaje_original_pendiente="texto A",
        )
        with TestingSessionLocal() as session:
            service = SharedChannelRoutingService(session)
            outcome = service.select_manual(
                canal_id=canal["canal_id"],
                cliente_id=self.cliente["cliente_id"],
                membership_id=membership_b_id,
            )
            self.assertEqual(
                outcome.status,
                ManualSelectionStatus.UNKNOWN_OR_INACTIVE_MEMBERSHIP,
            )
            self.assertEqual(
                outcome.resolution_source, "requires_explicit_switch"
            )
        persisted = _load_context(
            canal["canal_id"], self.cliente["cliente_id"]
        )
        self.assertEqual(
            int(persisted.comercio_id_seleccionado),
            self.comercio_a["comercio_id"],
        )
        self.assertIsNone(persisted.comercio_id_cambio_pendiente)
        with TestingSessionLocal() as session:
            service = SharedChannelRoutingService(session)
            outcome_same = service.select_manual(
                canal_id=canal["canal_id"],
                cliente_id=self.cliente["cliente_id"],
                membership_id=membership_a_id,
            )
            self.assertEqual(
                outcome_same.status,
                ManualSelectionStatus.ALREADY_SELECTED,
            )

    def test_select_manual_same_selection_preserves_pending_target(
        self,
    ):
        canal = self.new_shared_channel(self.comercio_a["suffix"])
        code_a = f"MS-{self.comercio_a['suffix'][:6]}"
        code_b = f"MT-{self.comercio_b['suffix'][:6]}"
        with TestingSessionLocal() as session, session.begin():
            service = CanalWhatsappService(session)
            membership_a = service.register_shared_membership(
                canal_id=canal["canal_id"],
                comercio_id=self.comercio_a["comercio_id"],
                routing_code=code_a,
            )
            service.register_shared_membership(
                canal_id=canal["canal_id"],
                comercio_id=self.comercio_b["comercio_id"],
                routing_code=code_b,
            )
            session.flush()
            membership_a_id = int(membership_a.id)
        raw_message = (
            "PIZZA-001\n  con orégano 🥚 y emojis   🎉\t"
            "y multilinea sin tocar\n\n"
        )
        _seed_context(
            canal["canal_id"],
            self.cliente["cliente_id"],
            comercio_id_seleccionado=self.comercio_a["comercio_id"],
            comercio_id_cambio_pendiente=self.comercio_b["comercio_id"],
            mensaje_original_pendiente=raw_message,
        )

        with TestingSessionLocal() as session, session.begin():
            service = SharedChannelRoutingService(session)
            outcome = service.select_manual(
                canal_id=canal["canal_id"],
                cliente_id=self.cliente["cliente_id"],
                membership_id=membership_a_id,
            )
            self.assertEqual(
                outcome.status,
                ManualSelectionStatus.ALREADY_SELECTED,
            )
            self.assertEqual(
                outcome.resolution_source, "same_selection_idempotent"
            )
            self.assertEqual(
                outcome.comercio_id_seleccionado,
                self.comercio_a["comercio_id"],
            )
            self.assertEqual(
                outcome.comercio_id_cambio_pendiente,
                self.comercio_b["comercio_id"],
            )
            self.assertEqual(
                outcome.mensaje_original_pendiente, raw_message
            )

        persisted = _load_context(
            canal["canal_id"], self.cliente["cliente_id"]
        )
        self.assertEqual(
            int(persisted.comercio_id_seleccionado),
            self.comercio_a["comercio_id"],
        )
        self.assertEqual(
            int(persisted.comercio_id_cambio_pendiente),
            self.comercio_b["comercio_id"],
        )
        self.assertEqual(
            persisted.mensaje_original_pendiente, raw_message
        )


class ManualSelectionSwitchLifecycleTest(ManualSelectionChannelBase):
    def test_request_confirm_complete_lifecycle(self):
        canal = self.new_shared_channel(self.comercio_a["suffix"])
        code_b = f"S1-{self.comercio_b['suffix'][:6]}"
        with TestingSessionLocal() as session, session.begin():
            service = CanalWhatsappService(session)
            membership_b = service.register_shared_membership(
                canal_id=canal["canal_id"],
                comercio_id=self.comercio_b["comercio_id"],
                routing_code=code_b,
            )
            session.flush()
            membership_b_id = int(membership_b.id)
        msg_a = "primer mensaje A con espacios 🥚"
        _seed_context(
            canal["canal_id"],
            self.cliente["cliente_id"],
            comercio_id_seleccionado=self.comercio_a["comercio_id"],
            mensaje_original_pendiente=msg_a,
        )

        with TestingSessionLocal() as session, session.begin():
            service = SharedChannelRoutingService(session)
            request = service.request_switch(
                canal_id=canal["canal_id"],
                cliente_id=self.cliente["cliente_id"],
                membership_id=membership_b_id,
            )
            self.assertEqual(
                request.status,
                ManualSelectionStatus.SWITCH_REQUESTED,
            )
            self.assertEqual(
                request.comercio_id_seleccionado,
                self.comercio_a["comercio_id"],
            )
            self.assertEqual(
                request.comercio_id_cambio_pendiente,
                self.comercio_b["comercio_id"],
            )
            self.assertEqual(
                request.mensaje_original_pendiente, msg_a
            )

        persisted = _load_context(
            canal["canal_id"], self.cliente["cliente_id"]
        )
        self.assertEqual(
            int(persisted.comercio_id_seleccionado),
            self.comercio_a["comercio_id"],
        )
        self.assertEqual(
            int(persisted.comercio_id_cambio_pendiente),
            self.comercio_b["comercio_id"],
        )
        self.assertEqual(
            persisted.mensaje_original_pendiente, msg_a
        )

        with TestingSessionLocal() as session, session.begin():
            service = SharedChannelRoutingService(session)
            confirm = service.confirm_switch(
                canal_id=canal["canal_id"],
                cliente_id=self.cliente["cliente_id"],
            )
            self.assertEqual(
                confirm.status,
                ManualSelectionStatus.SWITCH_CONFIRMED,
            )
            self.assertEqual(
                confirm.comercio_id_seleccionado,
                self.comercio_b["comercio_id"],
            )
            self.assertIsNone(confirm.comercio_id_cambio_pendiente)

        persisted = _load_context(
            canal["canal_id"], self.cliente["cliente_id"]
        )
        self.assertEqual(
            int(persisted.comercio_id_seleccionado),
            self.comercio_b["comercio_id"],
        )
        self.assertIsNone(persisted.comercio_id_cambio_pendiente)
        self.assertEqual(persisted.mensaje_original_pendiente, msg_a)

    def test_request_switch_target_replacement(self):
        canal = self.new_shared_channel(self.comercio_a["suffix"])
        code_b = f"S2-{self.comercio_b['suffix'][:6]}"
        extra_suffix = self.comercio_a["suffix"] + "Z"
        with TestingSessionLocal() as session, session.begin():
            service = CanalWhatsappService(session)
            membership_b = service.register_shared_membership(
                canal_id=canal["canal_id"],
                comercio_id=self.comercio_b["comercio_id"],
                routing_code=code_b,
            )
            extra_comercio = _seed_comercio(suffix=extra_suffix)
            self.addCleanup(
                _delete_comercio, extra_comercio["comercio_id"]
            )
            membership_extra = service.register_shared_membership(
                canal_id=canal["canal_id"],
                comercio_id=extra_comercio["comercio_id"],
                routing_code=f"S2Z-{self.comercio_a['suffix'][:6]}",
            )
            session.flush()
            membership_b_id = int(membership_b.id)
            session.flush()
            membership_extra_id = int(membership_extra.id)
        _seed_context(
            canal["canal_id"],
            self.cliente["cliente_id"],
            comercio_id_seleccionado=self.comercio_a["comercio_id"],
            mensaje_original_pendiente="texto A",
        )

        with TestingSessionLocal() as session, session.begin():
            service = SharedChannelRoutingService(session)
            req_b = service.request_switch(
                canal_id=canal["canal_id"],
                cliente_id=self.cliente["cliente_id"],
                membership_id=membership_b_id,
            )
            self.assertEqual(
                req_b.comercio_id_cambio_pendiente,
                self.comercio_b["comercio_id"],
            )

        with TestingSessionLocal() as session, session.begin():
            service = SharedChannelRoutingService(session)
            req_extra = service.request_switch(
                canal_id=canal["canal_id"],
                cliente_id=self.cliente["cliente_id"],
                membership_id=membership_extra_id,
            )
            self.assertEqual(
                req_extra.status,
                ManualSelectionStatus.SWITCH_REQUESTED,
            )

        persisted = _load_context(
            canal["canal_id"], self.cliente["cliente_id"]
        )
        self.assertEqual(
            int(persisted.comercio_id_seleccionado),
            self.comercio_a["comercio_id"],
        )
        self.assertEqual(
            int(persisted.comercio_id_cambio_pendiente),
            extra_comercio["comercio_id"],
        )
        self.assertEqual(
            persisted.mensaje_original_pendiente, "texto A"
        )

    def test_request_switch_same_commerce_preserves_pending_target(self):
        canal = self.new_shared_channel(self.comercio_a["suffix"])
        code_a = f"S3-{self.comercio_a['suffix'][:6]}"
        code_b = f"S3B-{self.comercio_b['suffix'][:6]}"
        with TestingSessionLocal() as session, session.begin():
            service = CanalWhatsappService(session)
            membership_a = service.register_shared_membership(
                canal_id=canal["canal_id"],
                comercio_id=self.comercio_a["comercio_id"],
                routing_code=code_a,
            )
            service.register_shared_membership(
                canal_id=canal["canal_id"],
                comercio_id=self.comercio_b["comercio_id"],
                routing_code=code_b,
            )
            session.flush()
            membership_a_id = int(membership_a.id)
        raw_message = (
            "PIZZA-001\n  con orégano 🥚 y emojis   🎉\t"
            "y multilinea sin tocar\n\n"
        )
        _seed_context(
            canal["canal_id"],
            self.cliente["cliente_id"],
            comercio_id_seleccionado=self.comercio_a["comercio_id"],
            comercio_id_cambio_pendiente=self.comercio_b["comercio_id"],
            mensaje_original_pendiente=raw_message,
        )
        with TestingSessionLocal() as session, session.begin():
            service = SharedChannelRoutingService(session)
            outcome = service.request_switch(
                canal_id=canal["canal_id"],
                cliente_id=self.cliente["cliente_id"],
                membership_id=membership_a_id,
            )
            self.assertEqual(
                outcome.status,
                ManualSelectionStatus.SWITCH_REQUESTED,
            )
            self.assertEqual(outcome.resolution_source, "same_commerce_no_pending_switch")
            self.assertEqual(
                outcome.comercio_id_seleccionado,
                self.comercio_a["comercio_id"],
            )
            self.assertEqual(
                outcome.comercio_id_cambio_pendiente,
                self.comercio_b["comercio_id"],
            )
            self.assertEqual(
                outcome.mensaje_original_pendiente, raw_message
            )

        persisted = _load_context(
            canal["canal_id"], self.cliente["cliente_id"]
        )
        self.assertEqual(
            int(persisted.comercio_id_seleccionado),
            self.comercio_a["comercio_id"],
        )
        self.assertEqual(
            int(persisted.comercio_id_cambio_pendiente),
            self.comercio_b["comercio_id"],
        )
        self.assertEqual(
            persisted.mensaje_original_pendiente, raw_message
        )

    def test_request_switch_same_commerce_no_pending_keeps_no_pending(self):
        canal = self.new_shared_channel(self.comercio_a["suffix"])
        code_a = f"S3A-{self.comercio_a['suffix'][:6]}"
        with TestingSessionLocal() as session, session.begin():
            service = CanalWhatsappService(session)
            membership = service.register_shared_membership(
                canal_id=canal["canal_id"],
                comercio_id=self.comercio_a["comercio_id"],
                routing_code=code_a,
            )
            session.flush()
            membership_id = int(membership.id)
        _seed_context(
            canal["canal_id"],
            self.cliente["cliente_id"],
            comercio_id_seleccionado=self.comercio_a["comercio_id"],
            mensaje_original_pendiente="mensaje A",
        )
        with TestingSessionLocal() as session:
            service = SharedChannelRoutingService(session)
            outcome = service.request_switch(
                canal_id=canal["canal_id"],
                cliente_id=self.cliente["cliente_id"],
                membership_id=membership_id,
            )
            self.assertEqual(
                outcome.status,
                ManualSelectionStatus.SWITCH_REQUESTED,
            )
            self.assertIsNone(outcome.comercio_id_cambio_pendiente)
        persisted = _load_context(
            canal["canal_id"], self.cliente["cliente_id"]
        )
        self.assertIsNone(persisted.comercio_id_cambio_pendiente)

    def test_cancel_switch_clears_pending_only(self):
        canal = self.new_shared_channel(self.comercio_a["suffix"])
        code_b = f"S4-{self.comercio_b['suffix'][:6]}"
        with TestingSessionLocal() as session, session.begin():
            service = CanalWhatsappService(session)
            service.register_shared_membership(
                canal_id=canal["canal_id"],
                comercio_id=self.comercio_b["comercio_id"],
                routing_code=code_b,
            )
            session.flush()
        _seed_context(
            canal["canal_id"],
            self.cliente["cliente_id"],
            comercio_id_seleccionado=self.comercio_a["comercio_id"],
            comercio_id_cambio_pendiente=self.comercio_b["comercio_id"],
            mensaje_original_pendiente="texto A",
        )
        with TestingSessionLocal() as session, session.begin():
            service = SharedChannelRoutingService(session)
            outcome = service.cancel_switch(
                canal_id=canal["canal_id"],
                cliente_id=self.cliente["cliente_id"],
            )
            self.assertEqual(
                outcome.status,
                ManualSelectionStatus.SWITCH_CANCELLED,
            )
        persisted = _load_context(
            canal["canal_id"], self.cliente["cliente_id"]
        )
        self.assertEqual(
            int(persisted.comercio_id_seleccionado),
            self.comercio_a["comercio_id"],
        )
        self.assertIsNone(persisted.comercio_id_cambio_pendiente)
        self.assertEqual(
            persisted.mensaje_original_pendiente, "texto A"
        )

    def test_confirm_without_pending_returns_no_pending(self):
        canal = self.new_shared_channel(self.comercio_a["suffix"])
        _seed_context(
            canal["canal_id"],
            self.cliente["cliente_id"],
            comercio_id_seleccionado=self.comercio_a["comercio_id"],
            mensaje_original_pendiente="texto",
        )
        with TestingSessionLocal() as session:
            service = SharedChannelRoutingService(session)
            outcome = service.confirm_switch(
                canal_id=canal["canal_id"],
                cliente_id=self.cliente["cliente_id"],
            )
            self.assertEqual(
                outcome.status,
                ManualSelectionStatus.NO_PENDING_SWITCH,
            )

    def test_cancel_without_pending_returns_no_pending(self):
        canal = self.new_shared_channel(self.comercio_a["suffix"])
        _seed_context(
            canal["canal_id"],
            self.cliente["cliente_id"],
            comercio_id_seleccionado=self.comercio_a["comercio_id"],
            mensaje_original_pendiente="texto",
        )
        with TestingSessionLocal() as session:
            service = SharedChannelRoutingService(session)
            outcome = service.cancel_switch(
                canal_id=canal["canal_id"],
                cliente_id=self.cliente["cliente_id"],
            )
            self.assertEqual(
                outcome.status,
                ManualSelectionStatus.NO_PENDING_SWITCH,
            )

    def test_stale_pending_target_fails_closed_at_confirmation(self):
        canal = self.new_shared_channel(self.comercio_a["suffix"])
        code_b = f"S5-{self.comercio_b['suffix'][:6]}"
        with TestingSessionLocal() as session, session.begin():
            service = CanalWhatsappService(session)
            service.register_shared_membership(
                canal_id=canal["canal_id"],
                comercio_id=self.comercio_b["comercio_id"],
                routing_code=code_b,
            )
            session.flush()
            session.execute(
                update(ComercioCanalCompartido)
                .where(
                    ComercioCanalCompartido.canal_id == canal["canal_id"],
                    ComercioCanalCompartido.comercio_id
                    == self.comercio_b["comercio_id"],
                )
                .values(activo=False)
            )
        _seed_context(
            canal["canal_id"],
            self.cliente["cliente_id"],
            comercio_id_seleccionado=self.comercio_a["comercio_id"],
            comercio_id_cambio_pendiente=self.comercio_b["comercio_id"],
            mensaje_original_pendiente="mensaje A",
        )
        with TestingSessionLocal() as session:
            service = SharedChannelRoutingService(session)
            outcome = service.confirm_switch(
                canal_id=canal["canal_id"],
                cliente_id=self.cliente["cliente_id"],
            )
            self.assertEqual(
                outcome.status,
                ManualSelectionStatus.UNKNOWN_OR_INACTIVE_MEMBERSHIP,
            )
            self.assertEqual(
                outcome.resolution_source, "stale_pending_target"
            )
        persisted = _load_context(
            canal["canal_id"], self.cliente["cliente_id"]
        )
        self.assertEqual(
            int(persisted.comercio_id_seleccionado),
            self.comercio_a["comercio_id"],
        )
        self.assertEqual(
            int(persisted.comercio_id_cambio_pendiente),
            self.comercio_b["comercio_id"],
        )
        self.assertEqual(
            persisted.mensaje_original_pendiente, "mensaje A"
        )


class ManualSelectionInvalidClientTest(ManualSelectionChannelBase):
    def test_nonexistent_client_returns_invalid_context(self):
        canal = self.new_shared_channel(self.comercio_a["suffix"])
        with TestingSessionLocal() as session:
            service = SharedChannelRoutingService(session)
            outcome = service.list_manual_options(
                canal_id=canal["canal_id"],
                cliente_id=999_999_999,
            )
            self.assertEqual(
                outcome.status,
                ManualSelectionStatus.INVALID_CONTEXT,
            )
            self.assertEqual(
                outcome.resolution_source, "client_lookup"
            )

    def test_inactive_client_returns_invalid_context(self):
        cliente = _seed_cliente()
        self.addCleanup(_delete_cliente, cliente["cliente_id"])
        with TestingSessionLocal() as session, session.begin():
            session.query(Cliente).filter(
                Cliente.id == cliente["cliente_id"]
            ).update({"activo": False})
        canal = self.new_shared_channel(self.comercio_a["suffix"])
        with TestingSessionLocal() as session:
            service = SharedChannelRoutingService(session)
            with patch.object(
                service._canal_repo, "find_by_id"
            ) as canal_lookup:
                outcome = service.list_manual_options(
                    canal_id=canal["canal_id"],
                    cliente_id=cliente["cliente_id"],
                )
            self.assertEqual(
                outcome.status,
                ManualSelectionStatus.INVALID_CONTEXT,
            )
            canal_lookup.assert_not_called()

    def test_select_manual_dedicated_channel_returns_invalid_channel_mode(
        self,
    ):
        canal = self.new_dedicated_channel(self.comercio_a["suffix"])
        _seed_context(
            canal["canal_id"],
            self.cliente["cliente_id"],
            comercio_id_seleccionado=None,
            mensaje_original_pendiente="texto",
        )
        with TestingSessionLocal() as session:
            service = SharedChannelRoutingService(session)
            outcome = service.select_manual(
                canal_id=canal["canal_id"],
                cliente_id=self.cliente["cliente_id"],
                membership_id=1,
            )
            self.assertEqual(
                outcome.status,
                ManualSelectionStatus.INVALID_CHANNEL_MODE,
            )


class ManualSelectionStaticBoundariesTest(unittest.TestCase):
    def assert_no_transaction_control(self, session) -> None:
        session.flush.assert_not_called()
        session.begin.assert_not_called()
        session.commit.assert_not_called()
        session.rollback.assert_not_called()
        session.close.assert_not_called()

    def test_repository_does_not_commit_or_rollback(self) -> None:
        session = MagicMock()
        repo = ContextoClienteCanalWhatsappRepository(session)
        row = ContextoClienteCanalWhatsapp(
            canal_id=1,
            cliente_id=2,
            comercio_id_seleccionado=3,
            mensaje_original_pendiente="x",
        )
        repo.set_selected_comercio(row, 3)
        repo.stage_pending_target(row, 9)
        repo.clear_pending_target(row)
        repo.commit_pending_target_to_selection(row)
        self.assert_no_transaction_control(session)

    def _mock_service(self):
        session = MagicMock()
        service = SharedChannelRoutingService(session)
        service._canal_repo.find_by_id = MagicMock(return_value=None)
        return session, service

    def test_list_manual_options_does_not_control_transaction(self):
        session, service = self._mock_service()
        outcome = service.list_manual_options(
            canal_id=1, cliente_id=2
        )
        self.assert_no_transaction_control(session)
        self.assertEqual(
            outcome.status,
            ManualSelectionStatus.INACTIVE_CHANNEL,
        )

    def test_select_manual_invalid_channel_does_not_control_transaction(
        self,
    ):
        session, service = self._mock_service()
        outcome = service.select_manual(
            canal_id=1, cliente_id=2, membership_id=3
        )
        self.assert_no_transaction_control(session)
        self.assertEqual(
            outcome.status,
            ManualSelectionStatus.INACTIVE_CHANNEL,
        )

    def test_request_switch_invalid_channel_does_not_control_transaction(
        self,
    ):
        session, service = self._mock_service()
        outcome = service.request_switch(
            canal_id=1, cliente_id=2, membership_id=3
        )
        self.assert_no_transaction_control(session)
        self.assertEqual(
            outcome.status,
            ManualSelectionStatus.INACTIVE_CHANNEL,
        )

    def test_confirm_switch_invalid_channel_does_not_control_transaction(
        self,
    ):
        session, service = self._mock_service()
        outcome = service.confirm_switch(canal_id=1, cliente_id=2)
        self.assert_no_transaction_control(session)
        self.assertEqual(
            outcome.status,
            ManualSelectionStatus.INACTIVE_CHANNEL,
        )

    def test_cancel_switch_invalid_channel_does_not_control_transaction(
        self,
    ):
        session, service = self._mock_service()
        outcome = service.cancel_switch(canal_id=1, cliente_id=2)
        self.assert_no_transaction_control(session)
        self.assertEqual(
            outcome.status,
            ManualSelectionStatus.INACTIVE_CHANNEL,
        )


if __name__ == "__main__":
    unittest.main()
