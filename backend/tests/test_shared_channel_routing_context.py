"""Focused tests for the Phase-5.2 shared-channel routing context.

Covers:

* the persistence layer (table shape, columns, FK rules, unconditional
  ``(canal_id, cliente_id)`` unique key);
* migration reversibility (downgrade drops the new table only);
* the service activation decision table for every typed outcome;
* channel-scoped isolation (one client on two destinations);
* raw original-text byte-for-byte preservation;
* the caller-owned transaction boundary (no commit / rollback /
  begin / flush by the 5.2 service or repository).

Uses the live ``supernova_test`` PostgreSQL database and creates /
removes per-test canales, comercios, memberships, clientes and
contexts so unrelated rows are never modified.
"""
from __future__ import annotations

import unittest
import uuid
from unittest.mock import MagicMock, patch

from sqlalchemy import (
    DateTime,
    Integer,
    Text,
    create_engine,
    delete,
    select,
    text,
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
from backend.services.exceptions import InvalidSharedRoutingContext
from backend.services.shared_channel_routing_service import (
    ContextActivationStatus,
    SharedChannelRoutingService,
)

TEST_URL = "postgresql+psycopg:///supernova_test"

engine = create_engine(TEST_URL)
TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _suffix() -> str:
    return uuid.uuid4().hex[:10]


def _estado_id(nombre: str) -> int:
    with engine.connect() as c:
        row = c.execute(
            select(EstadoComercio.id).where(EstadoComercio.codigo == nombre)
        ).first()
        if row is None:
            raise RuntimeError(f"estado {nombre!r} not seeded in supernova_test")
        return row[0]


def _estado_id_activo() -> int:
    return _estado_id("ACTIVO")


def _estado_id_inactivo() -> int:
    return _estado_id("INACTIVO")


def _seed_comercio(suffix: str | None = None, activo: bool = True) -> dict:
    suffix = suffix or _suffix()
    estado_id = _estado_id_activo() if activo else _estado_id_inactivo()
    with TestingSessionLocal() as session, session.begin():
        comercio = Comercio(
            nombre_fantasia=f"Routing Test {suffix}",
            nombre_corto=f"RT {suffix}",
            razon_social=f"Routing Test SRL {suffix}",
            cuit=f"30-{suffix[:8]}-{suffix[8]}",
            whatsapp=f"+54941{suffix[:8]}",
            calle="Av. Routing",
            numero="100",
            piso_departamento=None,
            localidad="CABA",
            provincia="Buenos Aires",
            codigo_postal="C1000",
            slug=f"routing-test-{suffix}",
            estado_id=estado_id,
        )
        session.add(comercio)
        session.flush()
        comercio_id = int(comercio.id)
    return {"comercio_id": comercio_id, "suffix": suffix}


def _seed_cliente(suffix: str | None = None) -> dict:
    suffix = suffix or _suffix()
    with TestingSessionLocal() as session, session.begin():
        cliente = Cliente(
            whatsapp=f"+54951{suffix[:8]}",
            nombre=f"Routing Cliente {suffix}",
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
                ContextoClienteCanalWhatsapp.canal_id.in_(canal_ids_subquery)
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


def _delete_canales_by_canal_id(canal_id: int) -> None:
    with TestingSessionLocal() as session, session.begin():
        session.execute(
            delete(ContextoClienteCanalWhatsapp).where(
                ContextoClienteCanalWhatsapp.canal_id == canal_id
            )
        )
        session.execute(
            delete(ComercioCanalCompartido).where(
                ComercioCanalCompartido.canal_id == canal_id
            )
        )
        session.execute(delete(CanalWhatsapp).where(CanalWhatsapp.id == canal_id))


class ContextoClienteCanalWhatsappSchemaTest(unittest.TestCase):
    def test_table_name_and_columns(self):
        table = ContextoClienteCanalWhatsapp.__table__
        self.assertEqual(
            table.name, "contextos_clientes_canales_whatsapp"
        )
        self.assertEqual(
            set(table.columns.keys()),
            {
                "id",
                "canal_id",
                "cliente_id",
                "comercio_id_seleccionado",
                "comercio_id_cambio_pendiente",
                "mensaje_original_pendiente",
                "fecha_alta",
                "fecha_ultima_modificacion",
            },
        )

    def test_required_columns_are_not_nullable(self):
        table = ContextoClienteCanalWhatsapp.__table__
        for column in (
            "canal_id",
            "cliente_id",
            "fecha_alta",
            "fecha_ultima_modificacion",
        ):
            self.assertIs(table.c[column].nullable, False, column)
        self.assertIs(table.c.comercio_id_seleccionado.nullable, True)
        self.assertIs(table.c.comercio_id_cambio_pendiente.nullable, True)
        self.assertIs(table.c.mensaje_original_pendiente.nullable, True)

    def test_column_types(self):
        table = ContextoClienteCanalWhatsapp.__table__
        self.assertIsInstance(table.c.id.type, Integer)
        self.assertIsInstance(table.c.canal_id.type, Integer)
        self.assertIsInstance(table.c.cliente_id.type, Integer)
        self.assertIsInstance(
            table.c.comercio_id_seleccionado.type, Integer
        )
        self.assertIsInstance(
            table.c.comercio_id_cambio_pendiente.type, Integer
        )
        self.assertIsInstance(
            table.c.mensaje_original_pendiente.type, Text
        )
        self.assertIsInstance(table.c.fecha_alta.type, DateTime)
        self.assertTrue(table.c.fecha_alta.type.timezone)
        self.assertTrue(table.c.fecha_ultima_modificacion.type.timezone)
        self.assertTrue(
            table.c.fecha_ultima_modificacion.onupdate is not None
        )

    def test_foreign_keys_use_restrict(self):
        canal_fk = next(
            iter(
                ContextoClienteCanalWhatsapp.__table__.c.canal_id.foreign_keys
            )
        )
        self.assertEqual(
            str(canal_fk.target_fullname), "canales_whatsapp.id"
        )
        self.assertEqual(canal_fk.ondelete, "RESTRICT")
        cliente_fk = next(
            iter(
                ContextoClienteCanalWhatsapp.__table__.c.cliente_id.foreign_keys
            )
        )
        self.assertEqual(str(cliente_fk.target_fullname), "clientes.id")
        self.assertEqual(cliente_fk.ondelete, "RESTRICT")
        comercio_fk = next(
            iter(
                ContextoClienteCanalWhatsapp.__table__.c.comercio_id_seleccionado.foreign_keys
            )
        )
        self.assertEqual(str(comercio_fk.target_fullname), "comercios.id")
        self.assertEqual(comercio_fk.ondelete, "RESTRICT")
        cambio_pendiente_fk = next(
            iter(
                ContextoClienteCanalWhatsapp.__table__.c.comercio_id_cambio_pendiente.foreign_keys
            )
        )
        self.assertEqual(
            str(cambio_pendiente_fk.target_fullname), "comercios.id"
        )
        self.assertEqual(cambio_pendiente_fk.ondelete, "RESTRICT")

    def test_unique_constraint_on_canal_and_cliente(self):
        table = ContextoClienteCanalWhatsapp.__table__
        unique_constraints = [
            constraint
            for constraint in table.constraints
            if constraint.__class__.__name__ == "UniqueConstraint"
        ]
        names = [c.name for c in unique_constraints]
        self.assertIn(
            "contextos_clientes_canales_whatsapp_canal_cliente_unico", names
        )

    def test_database_columns_match_model(self):
        with engine.connect() as c:
            rows = c.execute(
                text(
                    "SELECT column_name, data_type, is_nullable "
                    "FROM information_schema.columns "
                    "WHERE table_name = 'contextos_clientes_canales_whatsapp' "
                    "ORDER BY ordinal_position"
                )
            ).all()
        names = {row[0] for row in rows}
        self.assertEqual(
            names,
            {
                "id",
                "canal_id",
                "cliente_id",
                "comercio_id_seleccionado",
                "comercio_id_cambio_pendiente",
                "mensaje_original_pendiente",
                "fecha_alta",
                "fecha_ultima_modificacion",
            },
        )

    def test_required_unique_constraint_present_in_database(self):
        with engine.connect() as c:
            rows = c.execute(
                text(
                    "SELECT indexname FROM pg_indexes "
                    "WHERE tablename = 'contextos_clientes_canales_whatsapp'"
                )
            ).all()
        names = {row[0] for row in rows}
        self.assertIn(
            "contextos_clientes_canales_whatsapp_canal_cliente_unico", names
        )


class ContextoClienteCanalWhatsappMigrationTest(unittest.TestCase):
    def test_downgrade_drops_only_new_table(self):
        with engine.connect() as c:
            exists_before = c.execute(
                text(
                    "SELECT to_regclass("
                    "'public.contextos_clientes_canales_whatsapp')"
                )
            ).scalar_one()
            self.assertTrue(bool(exists_before))
        from alembic import command
        from alembic.config import Config

        cfg = Config("alembic.ini")
        cfg.set_main_option("sqlalchemy.url", TEST_URL)
        command.downgrade(cfg, "6d9e0f1a2b3c")
        with engine.connect() as c:
            exists_after = c.execute(
                text(
                    "SELECT to_regclass("
                    "'public.contextos_clientes_canales_whatsapp')"
                )
            ).scalar_one()
            self.assertFalse(
                bool(
                    c.execute(
                        text(
                            "SELECT EXISTS (SELECT 1 FROM "
                            "information_schema.columns "
                            "WHERE table_name = "
                            "'contextos_clientes_canales_whatsapp' "
                            "AND column_name = "
                            "'comercio_id_cambio_pendiente')"
                        )
                    ).scalar_one()
                ),
                "5.3 column must be dropped at 5.2 head",
            )
            self.assertTrue(bool(exists_after))
            canales_exists = c.execute(
                text("SELECT to_regclass('public.canales_whatsapp')")
            ).scalar_one()
            self.assertTrue(bool(canales_exists))
            membresias_exists = c.execute(
                text(
                    "SELECT to_regclass("
                    "'public.comercios_canales_compartidos')"
                )
            ).scalar_one()
            self.assertTrue(bool(membresias_exists))
            clientes_exists = c.execute(
                text("SELECT to_regclass('public.clientes')")
            ).scalar_one()
            self.assertTrue(bool(clientes_exists))
        command.downgrade(cfg, "5c8d1a2b3e4f")
        with engine.connect() as c:
            exists_dropped = c.execute(
                text(
                    "SELECT to_regclass("
                    "'public.contextos_clientes_canales_whatsapp')"
                )
            ).scalar_one()
            self.assertFalse(bool(exists_dropped))
        command.upgrade(cfg, "head")
        with engine.connect() as c:
            exists_final = c.execute(
                text(
                    "SELECT to_regclass("
                    "'public.contextos_clientes_canales_whatsapp')"
                )
            ).scalar_one()
            self.assertTrue(bool(exists_final))


class SharedChannelRoutingServiceArgumentTest(unittest.TestCase):
    def test_invalid_canal_id_raises(self):
        with TestingSessionLocal() as session:
            service = SharedChannelRoutingService(session)
            for bad in (0, -1, None, "1", True):
                with self.subTest(value=bad):
                    with self.assertRaises(InvalidSharedRoutingContext):
                        service.activate(
                            canal_id=bad,  # type: ignore[arg-type]
                            cliente_id=1,
                            routing_code="PIZZA-01",
                            mensaje_original_pendiente="hola",
                        )

    def test_invalid_cliente_id_raises(self):
        with TestingSessionLocal() as session:
            service = SharedChannelRoutingService(session)
            for bad in (0, -1, None, "1", True):
                with self.subTest(value=bad):
                    with self.assertRaises(InvalidSharedRoutingContext):
                        service.activate(
                            canal_id=1,
                            cliente_id=bad,  # type: ignore[arg-type]
                            routing_code="PIZZA-01",
                            mensaje_original_pendiente="hola",
                        )

    def test_invalid_mensaje_original_raises(self):
        with TestingSessionLocal() as session:
            service = SharedChannelRoutingService(session)
            for bad in (None, "", 123, b"hola"):
                with self.subTest(value=bad):
                    with self.assertRaises(InvalidSharedRoutingContext):
                        service.activate(
                            canal_id=1,
                            cliente_id=1,
                            routing_code="PIZZA-01",
                            mensaje_original_pendiente=bad,  # type: ignore[arg-type]
                        )


class SharedChannelRoutingServiceActivationTest(unittest.TestCase):
    def setUp(self):
        self.comercio = _seed_comercio()
        self.addCleanup(_delete_comercio, self.comercio["comercio_id"])
        self.other_comercio = _seed_comercio()
        self.addCleanup(
            _delete_comercio, self.other_comercio["comercio_id"]
        )
        self.inactive_comercio = _seed_comercio(activo=False)
        self.addCleanup(
            _delete_comercio, self.inactive_comercio["comercio_id"]
        )
        self.cliente = _seed_cliente()
        self.addCleanup(_delete_cliente, self.cliente["cliente_id"])
        self._dest_counter = 0
        self._registered_destinations: list[str] = []

    def _new_shared_channel(self) -> dict:
        suffix = self.comercio["suffix"]
        self._dest_counter += 1
        destination = (
            f"+54961{(int(suffix, 16) * 1000 + self._dest_counter) % 10_000_000:07d}"
        )
        self._registered_destinations.append(destination)
        self.addCleanup(_delete_canales_by_destination, destination)
        with TestingSessionLocal() as session, session.begin():
            service = CanalWhatsappService(session)
            canal = service.register_shared_channel(
                provider="twilio", destination=destination
            )
            session.flush()
            return {
                "canal_id": int(canal.id),
                "destination": destination,
            }

    def _new_dedicated_channel(self) -> dict:
        suffix = self.comercio["suffix"]
        self._dest_counter += 1
        destination = (
            f"+54971{(int(suffix, 16) * 1000 + self._dest_counter) % 10_000_000:07d}"
        )
        self._registered_destinations.append(destination)
        self.addCleanup(_delete_canales_by_destination, destination)
        with TestingSessionLocal() as session, session.begin():
            service = CanalWhatsappService(session)
            canal = service.register_dedicated_channel(
                provider="twilio",
                destination=destination,
                id_comercio_exclusivo=self.comercio["comercio_id"],
            )
            session.flush()
            return {
                "canal_id": int(canal.id),
                "destination": destination,
            }

    def _register_membership(
        self, canal_id: int, comercio_id: int, routing_code: str
    ) -> None:
        with TestingSessionLocal() as session, session.begin():
            service = CanalWhatsappService(session)
            service.register_shared_membership(
                canal_id=canal_id,
                comercio_id=comercio_id,
                routing_code=routing_code,
            )

    def test_first_activation_persists_comercio_and_original_text(self):
        canal = self._new_shared_channel()
        code = f"R-{self.comercio['suffix'][:6]}-01"
        self._register_membership(
            canal["canal_id"], self.comercio["comercio_id"], code
        )
        raw = "  PIZZA-001 Hola quiero 2 muzzarelas 🥚  "
        with TestingSessionLocal() as session:
            service = SharedChannelRoutingService(session)
            outcome = service.activate(
                canal_id=canal["canal_id"],
                cliente_id=self.cliente["cliente_id"],
                routing_code=f"  {code}  ",
                mensaje_original_pendiente=raw,
            )
            self.assertEqual(
                outcome.status, ContextActivationStatus.ACTIVATED
            )
            self.assertEqual(outcome.canal_id, canal["canal_id"])
            self.assertEqual(outcome.cliente_id, self.cliente["cliente_id"])
            self.assertEqual(
                outcome.comercio_id, self.comercio["comercio_id"]
            )
            self.assertEqual(outcome.routing_code_normalizado, code)
            self.assertEqual(outcome.mensaje_original_pendiente, raw)
            self.assertEqual(outcome.resolution_source, "first_activation")
            session.rollback()

    def test_repeating_same_code_returns_already_selected(self):
        canal = self._new_shared_channel()
        code = f"R-{self.comercio['suffix'][:6]}-02"
        self._register_membership(
            canal["canal_id"], self.comercio["comercio_id"], code
        )
        first_text = "primer mensaje con espacios  y emojis 🎉"
        second_text = "segundo mensaje NO debe sobreescribir"
        with TestingSessionLocal() as session, session.begin():
            service = SharedChannelRoutingService(session)
            first = service.activate(
                canal_id=canal["canal_id"],
                cliente_id=self.cliente["cliente_id"],
                routing_code=code,
                mensaje_original_pendiente=first_text,
            )
            self.assertEqual(
                first.status, ContextActivationStatus.ACTIVATED
            )
            session.flush()
            persisted = service._contexto_repo.find_by_canal_and_cliente(
                canal["canal_id"], self.cliente["cliente_id"]
            )
            assert persisted is not None
            assert persisted.comercio_id_seleccionado is not None
            persisted_id = int(persisted.id)
            persisted_comercio_id = int(persisted.comercio_id_seleccionado)
        with TestingSessionLocal() as session, session.begin():
            service = SharedChannelRoutingService(session)
            second = service.activate(
                canal_id=canal["canal_id"],
                cliente_id=self.cliente["cliente_id"],
                routing_code=code,
                mensaje_original_pendiente=second_text,
            )
            self.assertEqual(
                second.status, ContextActivationStatus.ALREADY_SELECTED
            )
            self.assertEqual(
                second.comercio_id, self.comercio["comercio_id"]
            )
            self.assertEqual(
                second.mensaje_original_pendiente, first_text
            )
            session.flush()
            persisted_after = (
                service._contexto_repo.find_by_canal_and_cliente(
                    canal["canal_id"], self.cliente["cliente_id"]
                )
            )
            assert persisted_after is not None
            self.assertEqual(int(persisted_after.id), persisted_id)
            self.assertEqual(
                persisted_after.mensaje_original_pendiente, first_text
            )
            assert persisted_after.comercio_id_seleccionado is not None
            self.assertEqual(
                int(persisted_after.comercio_id_seleccionado),
                persisted_comercio_id,
            )

    def test_conflicting_commerce_code_returns_requires_explicit_switch(self):
        canal = self._new_shared_channel()
        first_code = f"R-{self.comercio['suffix'][:6]}-03"
        second_code = f"R-{self.comercio['suffix'][:6]}-04"
        self._register_membership(
            canal["canal_id"], self.comercio["comercio_id"], first_code
        )
        self._register_membership(
            canal["canal_id"],
            self.other_comercio["comercio_id"],
            second_code,
        )
        first_text = "primer texto del primer comercio"
        with TestingSessionLocal() as session, session.begin():
            service = SharedChannelRoutingService(session)
            service.activate(
                canal_id=canal["canal_id"],
                cliente_id=self.cliente["cliente_id"],
                routing_code=first_code,
                mensaje_original_pendiente=first_text,
            )
            session.flush()
            persisted_for_id = (
                service._contexto_repo.find_by_canal_and_cliente(
                    canal["canal_id"], self.cliente["cliente_id"]
                )
            )
            assert persisted_for_id is not None
            persisted_id = int(persisted_for_id.id)
        with TestingSessionLocal() as session, session.begin():
            service = SharedChannelRoutingService(session)
            conflict = service.activate(
                canal_id=canal["canal_id"],
                cliente_id=self.cliente["cliente_id"],
                routing_code=second_code,
                mensaje_original_pendiente="segundo texto otro comercio",
            )
            self.assertEqual(
                conflict.status,
                ContextActivationStatus.REQUIRES_EXPLICIT_SWITCH,
            )
            self.assertEqual(
                conflict.comercio_id, self.other_comercio["comercio_id"]
            )
            self.assertEqual(
                conflict.mensaje_original_pendiente, first_text
            )
            session.flush()
            persisted_after = (
                service._contexto_repo.find_by_canal_and_cliente(
                    canal["canal_id"], self.cliente["cliente_id"]
                )
            )
            assert persisted_after is not None
            self.assertEqual(int(persisted_after.id), persisted_id)
            assert persisted_after.comercio_id_seleccionado is not None
            self.assertEqual(
                persisted_after.comercio_id_seleccionado,
                self.comercio["comercio_id"],
            )
            self.assertEqual(
                persisted_after.mensaje_original_pendiente, first_text
            )

    def test_nonexistent_client_returns_invalid_context_without_routing_lookup(self):
        canal = self._new_shared_channel()
        service = SharedChannelRoutingService(TestingSessionLocal())
        try:
            with patch.object(service._canal_repo, "find_by_id") as channel_lookup:
                outcome = service.activate(
                    canal_id=canal["canal_id"],
                    cliente_id=999_999_999,
                    routing_code="PIZZA-01",
                    mensaje_original_pendiente="hola",
                )
            self.assertEqual(outcome.status, ContextActivationStatus.INVALID_CONTEXT)
            self.assertEqual(outcome.resolution_source, "client_lookup")
            channel_lookup.assert_not_called()
            with TestingSessionLocal() as verify_session:
                self.assertIsNone(
                    verify_session.execute(
                        select(ContextoClienteCanalWhatsapp).where(
                            ContextoClienteCanalWhatsapp.canal_id
                            == canal["canal_id"],
                            ContextoClienteCanalWhatsapp.cliente_id
                            == 999_999_999,
                        )
                    ).scalar_one_or_none()
                )
        finally:
            service._session.close()

    def test_inactive_client_returns_invalid_context_without_routing_lookup(self):
        inactive_cliente = _seed_cliente()
        self.addCleanup(_delete_cliente, inactive_cliente["cliente_id"])
        with TestingSessionLocal() as session, session.begin():
            session.query(Cliente).filter(Cliente.id == inactive_cliente["cliente_id"]).update({"activo": False})
        canal = self._new_shared_channel()
        with TestingSessionLocal() as session:
            service = SharedChannelRoutingService(session)
            with patch.object(service._canal_repo, "find_by_id") as channel_lookup:
                outcome = service.activate(
                    canal_id=canal["canal_id"],
                    cliente_id=inactive_cliente["cliente_id"],
                    routing_code="PIZZA-01",
                    mensaje_original_pendiente="hola",
                )
            self.assertEqual(outcome.status, ContextActivationStatus.INVALID_CONTEXT)
            self.assertEqual(outcome.resolution_source, "client_lookup")
            channel_lookup.assert_not_called()
            self.assertIsNone(
                session.execute(
                    select(ContextoClienteCanalWhatsapp).where(
                        ContextoClienteCanalWhatsapp.canal_id == canal["canal_id"],
                        ContextoClienteCanalWhatsapp.cliente_id == inactive_cliente["cliente_id"],
                    )
                ).scalar_one_or_none()
            )

        with TestingSessionLocal() as session:
            service = SharedChannelRoutingService(session)
            outcome = service.activate(
                canal_id=999_999_999,
                cliente_id=self.cliente["cliente_id"],
                routing_code="PIZZA-01",
                mensaje_original_pendiente="hola",
            )
            self.assertEqual(
                outcome.status, ContextActivationStatus.INACTIVE_CHANNEL
            )
            self.assertIsNone(outcome.comercio_id)
            self.assertIsNone(outcome.routing_code_normalizado)
            self.assertIsNone(outcome.mensaje_original_pendiente)
            self.assertEqual(outcome.resolution_source, "channel_lookup")

    def test_dedicated_channel_returns_invalid_context(self):
        canal = self._new_dedicated_channel()
        with TestingSessionLocal() as session:
            service = SharedChannelRoutingService(session)
            outcome = service.activate(
                canal_id=canal["canal_id"],
                cliente_id=self.cliente["cliente_id"],
                routing_code="PIZZA-01",
                mensaje_original_pendiente="hola",
            )
            self.assertEqual(
                outcome.status, ContextActivationStatus.INVALID_CONTEXT
            )
            self.assertEqual(outcome.resolution_source, "channel_mode")

    def test_invalid_routing_code_returns_invalid_routing_code(self):
        canal = self._new_shared_channel()
        with TestingSessionLocal() as session:
            service = SharedChannelRoutingService(session)
            outcome = service.activate(
                canal_id=canal["canal_id"],
                cliente_id=self.cliente["cliente_id"],
                routing_code="with space and slash/",
                mensaje_original_pendiente="hola",
            )
            self.assertEqual(
                outcome.status, ContextActivationStatus.INVALID_ROUTING_CODE
            )
            self.assertIsNone(outcome.routing_code_normalizado)
            self.assertIsNone(outcome.mensaje_original_pendiente)
            self.assertEqual(
                outcome.resolution_source, "routing_code_normalization"
            )

    def test_unknown_or_revoked_code_returns_unknown_outcome(self):
        canal = self._new_shared_channel()
        reserved = f"R-{self.comercio['suffix'][:6]}-05"
        self._register_membership(
            canal["canal_id"], self.comercio["comercio_id"], reserved
        )
        with TestingSessionLocal() as session:
            service = SharedChannelRoutingService(session)
            outcome = service.activate(
                canal_id=canal["canal_id"],
                cliente_id=self.cliente["cliente_id"],
                routing_code="NUNCA-RESERVADO-99",
                mensaje_original_pendiente="hola",
            )
            self.assertEqual(
                outcome.status,
                ContextActivationStatus.UNKNOWN_OR_REVOKED_CODE,
            )
            self.assertEqual(outcome.resolution_source, "membership_lookup")
            self.assertIsNone(outcome.comercio_id)
            self.assertIsNone(outcome.mensaje_original_pendiente)

    def test_revoked_membership_code_returns_unknown_outcome(self):
        canal = self._new_shared_channel()
        reserved = f"R-{self.comercio['suffix'][:6]}-06"
        self._register_membership(
            canal["canal_id"], self.comercio["comercio_id"], reserved
        )
        with TestingSessionLocal() as session, session.begin():
            service = CanalWhatsappService(session)
            service.deactivate_shared_membership(
                canal_id=canal["canal_id"], routing_code=reserved
            )
        with TestingSessionLocal() as session:
            service = SharedChannelRoutingService(session)
            outcome = service.activate(
                canal_id=canal["canal_id"],
                cliente_id=self.cliente["cliente_id"],
                routing_code=reserved,
                mensaje_original_pendiente="hola",
            )
            self.assertEqual(
                outcome.status,
                ContextActivationStatus.UNKNOWN_OR_REVOKED_CODE,
            )

    def test_inactive_membership_commerce_returns_unavailable_commerce(self):
        canal = self._new_shared_channel()
        code = f"R-{self.comercio['suffix'][:6]}-07"
        with TestingSessionLocal() as session, session.begin():
            session.add(
                ComercioCanalCompartido(
                    canal_id=canal["canal_id"],
                    comercio_id=self.inactive_comercio["comercio_id"],
                    routing_code=code,
                    routing_code_normalizado=code,
                    activo=True,
                )
            )
        with TestingSessionLocal() as session:
            service = SharedChannelRoutingService(session)
            outcome = service.activate(
                canal_id=canal["canal_id"],
                cliente_id=self.cliente["cliente_id"],
                routing_code=code,
                mensaje_original_pendiente="hola",
            )
            self.assertEqual(
                outcome.status,
                ContextActivationStatus.UNAVAILABLE_COMMERCE,
            )
            self.assertEqual(
                outcome.comercio_id, self.inactive_comercio["comercio_id"]
            )
            self.assertEqual(
                outcome.resolution_source, "membership_commerce"
            )
            self.assertIsNone(outcome.mensaje_original_pendiente)

    def test_foreign_channel_code_returns_unknown_or_revoked(self):
        canal_a = self._new_shared_channel()
        canal_b = self._new_shared_channel()
        code_b = f"R-{self.comercio['suffix'][:6]}-08"
        self._register_membership(
            canal_b["canal_id"], self.comercio["comercio_id"], code_b
        )
        with TestingSessionLocal() as session:
            service = SharedChannelRoutingService(session)
            outcome = service.activate(
                canal_id=canal_a["canal_id"],
                cliente_id=self.cliente["cliente_id"],
                routing_code=code_b,
                mensaje_original_pendiente="hola",
            )
            self.assertEqual(
                outcome.status,
                ContextActivationStatus.UNKNOWN_OR_REVOKED_CODE,
            )
            self.assertEqual(outcome.canal_id, canal_a["canal_id"])


class SharedChannelRoutingServiceIsolationTest(unittest.TestCase):
    def setUp(self):
        self.comercio_a = _seed_comercio()
        self.addCleanup(_delete_comercio, self.comercio_a["comercio_id"])
        self.comercio_b = _seed_comercio()
        self.addCleanup(_delete_comercio, self.comercio_b["comercio_id"])
        self.cliente = _seed_cliente()
        self.addCleanup(_delete_cliente, self.cliente["cliente_id"])
        self._dest_counter = 0
        self._registered: list[str] = []

    def _new_shared_channel(self, suffix_hex: str) -> dict:
        self._dest_counter += 1
        destination = (
            f"+54981{(int(suffix_hex, 16) * 1000 + self._dest_counter) % 10_000_000:07d}"
        )
        self._registered.append(destination)
        self.addCleanup(_delete_canales_by_destination, destination)
        with TestingSessionLocal() as session, session.begin():
            service = CanalWhatsappService(session)
            canal = service.register_shared_channel(
                provider="twilio", destination=destination
            )
            session.flush()
            return {"canal_id": int(canal.id), "destination": destination}

    def _register_membership(
        self, canal_id: int, comercio_id: int, routing_code: str
    ) -> None:
        with TestingSessionLocal() as session, session.begin():
            service = CanalWhatsappService(session)
            service.register_shared_membership(
                canal_id=canal_id,
                comercio_id=comercio_id,
                routing_code=routing_code,
            )

    def test_one_client_two_destinations_independent(self):
        canal_a = self._new_shared_channel(self.comercio_a["suffix"])
        canal_b = self._new_shared_channel(self.comercio_b["suffix"])
        code_a = f"X-{self.comercio_a['suffix'][:6]}-A"
        code_b = f"Y-{self.comercio_b['suffix'][:6]}-B"
        self._register_membership(
            canal_a["canal_id"], self.comercio_a["comercio_id"], code_a
        )
        self._register_membership(
            canal_b["canal_id"], self.comercio_b["comercio_id"], code_b
        )
        text_a = "texto para canal A con espacios"
        text_b = "texto para canal B"
        with TestingSessionLocal() as session, session.begin():
            service = SharedChannelRoutingService(session)
            outcome_a = service.activate(
                canal_id=canal_a["canal_id"],
                cliente_id=self.cliente["cliente_id"],
                routing_code=code_a,
                mensaje_original_pendiente=text_a,
            )
            outcome_b = service.activate(
                canal_id=canal_b["canal_id"],
                cliente_id=self.cliente["cliente_id"],
                routing_code=code_b,
                mensaje_original_pendiente=text_b,
            )
            self.assertEqual(
                outcome_a.status, ContextActivationStatus.ACTIVATED
            )
            self.assertEqual(
                outcome_b.status, ContextActivationStatus.ACTIVATED
            )
            self.assertEqual(
                outcome_a.comercio_id, self.comercio_a["comercio_id"]
            )
            self.assertEqual(
                outcome_b.comercio_id, self.comercio_b["comercio_id"]
            )
            session.flush()
            row_a = service._contexto_repo.find_by_canal_and_cliente(
                canal_a["canal_id"], self.cliente["cliente_id"]
            )
            row_b = service._contexto_repo.find_by_canal_and_cliente(
                canal_b["canal_id"], self.cliente["cliente_id"]
            )
            assert row_a is not None
            assert row_b is not None
            self.assertNotEqual(int(row_a.id), int(row_b.id))
            self.assertEqual(row_a.mensaje_original_pendiente, text_a)
            self.assertEqual(row_b.mensaje_original_pendiente, text_b)
            assert row_a.comercio_id_seleccionado is not None
            assert row_b.comercio_id_seleccionado is not None
            self.assertEqual(
                row_a.comercio_id_seleccionado,
                self.comercio_a["comercio_id"],
            )
            self.assertEqual(
                row_b.comercio_id_seleccionado,
                self.comercio_b["comercio_id"],
            )

    def test_unique_constraint_rejects_duplicate_canal_cliente(self):
        canal = self._new_shared_channel(self.comercio_a["suffix"])
        code = f"X-{self.comercio_a['suffix'][:6]}-DUP"
        self._register_membership(
            canal["canal_id"], self.comercio_a["comercio_id"], code
        )
        with TestingSessionLocal() as session, session.begin():
            session.add(
                ContextoClienteCanalWhatsapp(
                    canal_id=canal["canal_id"],
                    cliente_id=self.cliente["cliente_id"],
                    comercio_id_seleccionado=self.comercio_a["comercio_id"],
                    mensaje_original_pendiente="primero",
                )
            )
        from sqlalchemy.exc import IntegrityError

        with TestingSessionLocal() as session, session.begin():
            session.add(
                ContextoClienteCanalWhatsapp(
                    canal_id=canal["canal_id"],
                    cliente_id=self.cliente["cliente_id"],
                    comercio_id_seleccionado=self.comercio_a["comercio_id"],
                    mensaje_original_pendiente="segundo",
                )
            )
            with self.assertRaises(IntegrityError):
                session.flush()
            session.rollback()


class SharedChannelRoutingServicePreservationTest(unittest.TestCase):
    def setUp(self):
        self.comercio = _seed_comercio()
        self.addCleanup(_delete_comercio, self.comercio["comercio_id"])
        self.cliente = _seed_cliente()
        self.addCleanup(_delete_cliente, self.cliente["cliente_id"])

    def test_raw_text_preserved_byte_for_byte(self):
        suffix = self.comercio["suffix"]
        digits = int(suffix, 16) % 100_000_000
        destination = f"+54991{digits:08d}"
        self.addCleanup(_delete_canales_by_destination, destination)
        with TestingSessionLocal() as session, session.begin():
            service = CanalWhatsappService(session)
            canal = service.register_shared_channel(
                provider="twilio", destination=destination
            )
            session.flush()
            canal_id = int(canal.id)
            code = f"P-{suffix[:6]}-01"
            service.register_shared_membership(
                canal_id=canal_id,
                comercio_id=self.comercio["comercio_id"],
                routing_code=code,
            )
            session.flush()
        raw = (
            "PIZZA-001\n  quiero 2 muzzarelas 🥚  "
            "con orégano y aceitunas!!\t🎉🎉\n\n\n"
        )
        with TestingSessionLocal() as session, session.begin():
            service = SharedChannelRoutingService(session)
            outcome = service.activate(
                canal_id=canal_id,
                cliente_id=self.cliente["cliente_id"],
                routing_code=code,
                mensaje_original_pendiente=raw,
            )
            self.assertEqual(
                outcome.status, ContextActivationStatus.ACTIVATED
            )
            session.flush()
            persisted = service._contexto_repo.find_by_canal_and_cliente(
                canal_id, self.cliente["cliente_id"]
            )
            assert persisted is not None
            self.assertEqual(persisted.mensaje_original_pendiente, raw)


class SharedChannelRoutingServiceCallerOwnedTransactionTest(
    unittest.TestCase
):
    def assert_no_transaction_control(self, session) -> None:
        session.flush.assert_not_called()
        session.begin.assert_not_called()
        session.commit.assert_not_called()
        session.rollback.assert_not_called()

    def test_repository_does_not_commit_or_rollback(self) -> None:
        session = MagicMock()
        repo = ContextoClienteCanalWhatsappRepository(session)
        repo.create(
            canal_id=1,
            cliente_id=2,
            comercio_id_seleccionado=3,
            mensaje_original_pendiente="hola",
        )
        self.assertEqual(session.add.call_count, 1)
        self.assert_no_transaction_control(session)

    def test_service_does_not_commit_or_rollback(self) -> None:
        session = MagicMock()
        service = SharedChannelRoutingService(session)
        outcome = service.activate(
            canal_id=1,
            cliente_id=2,
            routing_code="PIZZA-01",
            mensaje_original_pendiente="hola",
        )
        self.assert_no_transaction_control(session)
        self.assertIn(
            outcome.status,
            {
                ContextActivationStatus.INACTIVE_CHANNEL,
                ContextActivationStatus.INVALID_CONTEXT,
                ContextActivationStatus.UNKNOWN_OR_REVOKED_CODE,
            },
        )

    def test_service_invokes_no_business_pipeline(self) -> None:
        session = MagicMock()
        service = SharedChannelRoutingService(session)
        from unittest.mock import patch

        with (
            patch.object(
                service,
                "_canal_repo",
            ) as canal_repo_mock,
            patch.object(
                service,
                "_membresia_repo",
            ) as membresia_repo_mock,
            patch.object(
                service,
                "_contexto_repo",
            ) as contexto_repo_mock,
        ):
            canal_repo_mock.find_by_id.return_value = None
            service.activate(
                canal_id=1,
                cliente_id=2,
                routing_code="PIZZA-01",
                mensaje_original_pendiente="hola",
            )
            canal_repo_mock.find_by_id.assert_called_once_with(1)
            membresia_repo_mock.find_active_by_canal_and_code.assert_not_called()
            contexto_repo_mock.create.assert_not_called()
            contexto_repo_mock.find_by_canal_and_cliente.assert_not_called()


if __name__ == "__main__":
    unittest.main()
