"""Focused tests for the WhatsApp channel routing persistence layer.

Covers the model schema (table shape, indexes, enum, check
constraints), the service lifecycle (dedicated / shared creation,
shared-membership reservation and permanent non-reassignment), and
the cross-entity invariants (dedicated channels reject memberships,
shared channels reject exclusive commerce). Uses the live
``supernova_test`` PostgreSQL database and creates / removes a
per-test comercio so unrelated rows are never modified.
"""
from __future__ import annotations

import unittest
import uuid
from unittest.mock import MagicMock

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    Integer,
    String,
    create_engine,
    delete,
    select,
    text,
)
from sqlalchemy.orm import sessionmaker

from backend.models import (
    CanalWhatsapp,
    CanalWhatsappMode,
    Comercio,
    ComercioCanalCompartido,
    EstadoComercio,
)
from backend.repositories.canal_whatsapp_repository import (
    CanalWhatsappRepository,
)
from backend.repositories.comercio_canal_compartido_repository import (
    ComercioCanalCompartidoRepository,
)
from backend.services.canal_whatsapp_service import (
    CanalWhatsappService,
    normalize_destination,
    normalize_routing_code,
)
from backend.services.exceptions import (
    CanalWhatsappNotFound,
    DedicatedChannelCannotHaveSharedMembership,
    DuplicateCanalWhatsappDestination,
    DuplicateRoutingCodeReservation,
    InvalidCanalWhatsappDestination,
    InvalidCanalWhatsappProvider,
    InvalidRoutingCode,
    SharedChannelCannotHaveExclusiveComercio,
)

TEST_URL = "postgresql+psycopg:///supernova_test"

engine = create_engine(TEST_URL)
TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _suffix() -> str:
    return uuid.uuid4().hex[:10]


def _estado_id(nombre: str) -> int:
    with engine.connect() as c:
        row = c.execute(
            select(EstadoComercio.id).where(EstadoComercio.estado == nombre)
        ).first()
        if row is None:
            raise RuntimeError(f"estado {nombre!r} not seeded in supernova_test")
        return row[0]


def _estado_id_activo() -> int:
    return _estado_id("ACTIVO")


def _seed_comercio(suffix: str | None = None) -> dict:
    suffix = suffix or _suffix()
    with TestingSessionLocal() as session, session.begin():
        comercio = Comercio(
            nombre_fantasia=f"Canal Test {suffix}",
            nombre_corto=f"CT {suffix}",
            razon_social=f"Canal Test SRL {suffix}",
            cuit=f"30-{suffix[:8]}-{suffix[8]}",
            whatsapp=f"+54911{suffix[:8]}",
            calle="Av. Canal",
            numero="100",
            piso_departamento=None,
            localidad="CABA",
            provincia="Buenos Aires",
            codigo_postal="C1000",
            slug=f"canal-test-{suffix}",
            estado_id=_estado_id_activo(),
        )
        session.add(comercio)
        session.flush()
        comercio_id = int(comercio.id)
    return {"comercio_id": comercio_id, "suffix": suffix}


def _seed_comercio_inactivo(suffix: str | None = None) -> dict:
    suffix = suffix or _suffix()
    inactive_estado_id = _estado_id("INACTIVO")
    with TestingSessionLocal() as session, session.begin():
        comercio = Comercio(
            nombre_fantasia=f"Canal Inactive {suffix}",
            nombre_corto=f"CI {suffix}",
            razon_social=f"Canal Inactive SRL {suffix}",
            cuit=f"30-{suffix[:8]}-{suffix[8]}",
            whatsapp=f"+54912{suffix[:8]}",
            calle="Av. Canal",
            numero="200",
            piso_departamento=None,
            localidad="CABA",
            provincia="Buenos Aires",
            codigo_postal="C1000",
            slug=f"canal-inactive-{suffix}",
            estado_id=inactive_estado_id,
        )
        session.add(comercio)
        session.flush()
        comercio_id = int(comercio.id)
    return {"comercio_id": comercio_id, "suffix": suffix}


def _delete_canales_for_comercio(comercio_id: int) -> None:
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
            delete(ComercioCanalCompartido).where(
                ComercioCanalCompartido.canal_id == canal_id
            )
        )
        session.execute(delete(CanalWhatsapp).where(CanalWhatsapp.id == canal_id))


class CanalWhatsappSchemaTest(unittest.TestCase):
    def test_table_name_and_columns(self):
        table = CanalWhatsapp.__table__
        self.assertEqual(table.name, "canales_whatsapp")
        self.assertEqual(
            set(table.columns.keys()),
            {
                "id",
                "provider",
                "destination_e164",
                "mode",
                "id_comercio_exclusivo",
                "activo",
                "fecha_alta",
                "fecha_ultima_modificacion",
                "fecha_baja",
            },
        )
        self.assertIsInstance(table.c.id.type, Integer)
        self.assertIsInstance(table.c.provider.type, String)
        self.assertIsInstance(table.c.destination_e164.type, String)
        self.assertIsInstance(table.c.mode.type, Enum)
        self.assertIsInstance(table.c.id_comercio_exclusivo.type, Integer)
        self.assertIsInstance(table.c.activo.type, Boolean)
        self.assertIsInstance(table.c.fecha_alta.type, DateTime)
        self.assertTrue(table.c.fecha_alta.type.timezone)
        self.assertTrue(table.c.fecha_alta.server_default is not None)
        self.assertTrue(table.c.fecha_ultima_modificacion.type.timezone)
        self.assertTrue(table.c.fecha_ultima_modificacion.onupdate is not None)
        self.assertIsInstance(table.c.fecha_baja.type, DateTime)

    def test_required_columns_are_not_nullable(self):
        table = CanalWhatsapp.__table__
        for column in (
            "provider",
            "destination_e164",
            "mode",
            "activo",
            "fecha_alta",
            "fecha_ultima_modificacion",
        ):
            self.assertIs(table.c[column].nullable, False, column)
        self.assertIs(table.c.id_comercio_exclusivo.nullable, True)
        self.assertIs(table.c.fecha_baja.nullable, True)

    def test_mode_enum_values(self):
        self.assertEqual(
            {member.value for member in CanalWhatsappMode},
            {"dedicated", "shared"},
        )

    def test_foreign_key_to_comercios_uses_restrict(self):
        column = CanalWhatsapp.__table__.c.id_comercio_exclusivo
        fk = next(iter(column.foreign_keys))
        self.assertEqual(str(fk.target_fullname), "comercios.id")
        self.assertEqual(fk.ondelete, "RESTRICT")

    def test_database_columns_match_model(self):
        with engine.connect() as c:
            rows = c.execute(
                text(
                    "SELECT column_name, data_type, is_nullable "
                    "FROM information_schema.columns "
                    "WHERE table_name = 'canales_whatsapp' "
                    "ORDER BY ordinal_position"
                )
            ).all()
        names = {row[0] for row in rows}
        self.assertEqual(
            names,
            {
                "id",
                "provider",
                "destination_e164",
                "mode",
                "id_comercio_exclusivo",
                "activo",
                "fecha_alta",
                "fecha_ultima_modificacion",
                "fecha_baja",
            },
        )

    def test_required_indexes_present(self):
        with engine.connect() as c:
            rows = c.execute(
                text(
                    "SELECT indexname FROM pg_indexes "
                    "WHERE tablename = 'canales_whatsapp'"
                )
            ).all()
        names = {row[0] for row in rows}
        self.assertIn("canales_whatsapp_pkey", names)
        self.assertIn("canales_whatsapp_provider_destino_unico", names)
        self.assertIn("ix_canales_whatsapp_id_comercio_exclusivo", names)
        self.assertIn("ix_canales_whatsapp_activo", names)

    def test_partial_unique_index_is_partial(self):
        with engine.connect() as c:
            row = c.execute(
                text(
                    "SELECT indexdef FROM pg_indexes "
                    "WHERE tablename = 'canales_whatsapp' "
                    "AND indexname = 'canales_whatsapp_provider_destino_unico'"
                )
            ).first()
        self.assertIsNotNone(row)
        self.assertIn("WHERE", row[0])
        self.assertIn("activo = true", row[0])

    def test_check_constraints_present(self):
        table = CanalWhatsapp.__table__
        names = {
            constraint.name
            for constraint in table.constraints
            if isinstance(constraint, CheckConstraint)
        }
        self.assertIn("canal_whatsapp_provider_no_vacio", names)
        self.assertIn("canal_whatsapp_destination_no_vacio", names)
        self.assertIn("canal_whatsapp_destination_no_prefijo", names)
        self.assertIn("canal_whatsapp_destination_e164", names)
        self.assertIn("canal_whatsapp_mode_comercio_exclusivo_chk", names)

    def test_model_indexes_match_database(self):
        table = CanalWhatsapp.__table__
        indexes = {index.name: index for index in table.indexes}
        self.assertIn("ix_canales_whatsapp_id_comercio_exclusivo", indexes)
        self.assertIn("ix_canales_whatsapp_activo", indexes)
        index = indexes["canales_whatsapp_provider_destino_unico"]
        self.assertTrue(index.unique)
        self.assertEqual(
            [expression.name for expression in index.expressions],
            ["provider", "destination_e164"],
        )
        predicate = index.dialect_options["postgresql"]["where"]
        self.assertEqual(str(predicate), "activo = true")


class ComercioCanalCompartidoSchemaTest(unittest.TestCase):
    def test_table_name_and_columns(self):
        table = ComercioCanalCompartido.__table__
        self.assertEqual(table.name, "comercios_canales_compartidos")
        self.assertEqual(
            set(table.columns.keys()),
            {
                "id",
                "canal_id",
                "comercio_id",
                "routing_code",
                "routing_code_normalizado",
                "activo",
                "fecha_alta",
                "fecha_ultima_modificacion",
            },
        )

    def test_required_columns_are_not_nullable(self):
        table = ComercioCanalCompartido.__table__
        for column in (
            "canal_id",
            "comercio_id",
            "routing_code",
            "routing_code_normalizado",
            "activo",
            "fecha_alta",
            "fecha_ultima_modificacion",
        ):
            self.assertIs(table.c[column].nullable, False, column)

    def test_foreign_keys_use_cascade_and_restrict(self):
        canal_fk = next(
            iter(ComercioCanalCompartido.__table__.c.canal_id.foreign_keys)
        )
        self.assertEqual(str(canal_fk.target_fullname), "canales_whatsapp.id")
        self.assertEqual(canal_fk.ondelete, "CASCADE")
        comercio_fk = next(
            iter(ComercioCanalCompartido.__table__.c.comercio_id.foreign_keys)
        )
        self.assertEqual(
            str(comercio_fk.target_fullname), "comercios.id"
        )
        self.assertEqual(comercio_fk.ondelete, "RESTRICT")

    def test_required_indexes_and_unique_constraint(self):
        with engine.connect() as c:
            rows = c.execute(
                text(
                    "SELECT indexname FROM pg_indexes "
                    "WHERE tablename = 'comercios_canales_compartidos'"
                )
            ).all()
        names = {row[0] for row in rows}
        self.assertIn("comercios_canales_compartidos_pkey", names)
        self.assertIn(
            "comercios_canales_compartidos_canal_code_unico", names
        )
        self.assertIn(
            "ix_comercios_canales_compartidos_canal_id", names
        )
        self.assertIn(
            "ix_comercios_canales_compartidos_comercio_id", names
        )
        self.assertIn(
            "ix_comercios_canales_compartidos_activo", names
        )

    def test_unique_constraint_is_unconditional(self):
        with engine.connect() as c:
            row = c.execute(
                text(
                    "SELECT indexdef FROM pg_indexes "
                    "WHERE tablename = 'comercios_canales_compartidos' "
                    "AND indexname = "
                    "'comercios_canales_compartidos_canal_code_unico'"
                )
            ).first()
        self.assertIsNotNone(row)
        self.assertNotIn("WHERE", row[0])

    def test_check_constraints_present(self):
        table = ComercioCanalCompartido.__table__
        names = {
            constraint.name
            for constraint in table.constraints
            if isinstance(constraint, CheckConstraint)
        }
        self.assertIn(
            "comercio_canal_compartido_routing_code_no_vacio", names
        )
        self.assertIn(
            "comercio_canal_compartido_routing_code_normalizado_no_vacio",
            names,
        )


class CanalWhatsappServiceNormalizeTest(unittest.TestCase):
    def test_destination_accepts_canonical_e164(self):
        self.assertEqual(
            normalize_destination("+5491155556666"),
            "+5491155556666",
        )

    def test_destination_strips_whatsapp_prefix(self):
        self.assertEqual(
            normalize_destination("whatsapp:+5491155556666"),
            "+5491155556666",
        )

    def test_destination_strips_whitespace_and_separators(self):
        self.assertEqual(
            normalize_destination("  whatsapp:+54911 5555-6666  "),
            "+5491155556666",
        )

    def test_destination_rejects_non_string(self):
        with self.assertRaises(InvalidCanalWhatsappDestination):
            normalize_destination(None)  # type: ignore[arg-type]

    def test_destination_rejects_empty(self):
        with self.assertRaises(InvalidCanalWhatsappDestination):
            normalize_destination("   ")

    def test_destination_rejects_non_e164(self):
        for bad in ("5491155556666", "+0123456789", "+abc", "+123"):
            with self.subTest(value=bad):
                with self.assertRaises(InvalidCanalWhatsappDestination):
                    normalize_destination(bad)

    def test_routing_code_accepts_opaque_identifier(self):
        self.assertEqual(normalize_routing_code("PIZZA-001"), "PIZZA-001")
        self.assertEqual(normalize_routing_code("  ABC_123  "), "ABC_123")

    def test_routing_code_rejects_invalid_characters(self):
        for bad in ("", "  ", "with space", "with/slash", "*"):
            with self.subTest(value=bad):
                with self.assertRaises(InvalidRoutingCode):
                    normalize_routing_code(bad)


class CallerOwnedTransactionBoundaryTest(unittest.TestCase):
    def assert_no_transaction_control(self, session):
        session.flush.assert_not_called()
        session.begin.assert_not_called()
        session.commit.assert_not_called()
        session.rollback.assert_not_called()

    def test_repository_creates_only_add_pending_state(self):
        session = MagicMock()
        CanalWhatsappRepository(session).create(
            "twilio",
            "+5491155556666",
            CanalWhatsappMode.DEDICATED,
            1,
            True,
        )
        ComercioCanalCompartidoRepository(session).create(
            1,
            1,
            "PIZZA-01",
            "PIZZA-01",
            True,
        )
        self.assertEqual(session.add.call_count, 2)
        self.assert_no_transaction_control(session)

    def test_lifecycle_deactivation_only_modifies_pending_state(self):
        session = MagicMock()
        service = CanalWhatsappService(session)
        canal = CanalWhatsapp(
            provider="twilio",
            destination_e164="+5491155556666",
            mode=CanalWhatsappMode.SHARED,
            id_comercio_exclusivo=None,
            activo=True,
        )
        membership = ComercioCanalCompartido(
            canal_id=1,
            comercio_id=1,
            routing_code="PIZZA-01",
            routing_code_normalizado="PIZZA-01",
            activo=True,
        )
        service._canal_repo = MagicMock()
        service._membresia_repo = MagicMock()
        service._canal_repo.find_by_id.return_value = canal
        service._membresia_repo.find_any_by_canal_and_code.return_value = membership

        self.assertIs(service.deactivate_channel(1), canal)
        self.assertIs(
            service.deactivate_shared_membership(1, "PIZZA-01"), membership
        )
        self.assertFalse(canal.activo)
        self.assertIsNotNone(canal.fecha_baja)
        self.assertFalse(membership.activo)
        self.assert_no_transaction_control(session)


class CanalWhatsappServiceLifecycleTest(unittest.TestCase):
    def setUp(self):
        self.fixtures = _seed_comercio()
        self.addCleanup(
            _delete_canales_for_comercio, self.fixtures["comercio_id"]
        )
        self._dest_counter = 0

    def _destination(self) -> str:
        self._dest_counter += 1
        suffix = self.fixtures["suffix"]
        digits = (int(suffix, 16) * 1000 + self._dest_counter) % 10_000_000
        return f"+54911{digits:07d}"

    def test_register_dedicated_channel_persists(self):
        destination = self._destination()
        self.addCleanup(_delete_canales_by_destination, destination)
        with TestingSessionLocal() as session, session.begin():
            service = CanalWhatsappService(session)
            canal = service.register_dedicated_channel(
                provider="twilio",
                destination=destination,
                id_comercio_exclusivo=self.fixtures["comercio_id"],
            )
            self.assertEqual(canal.provider, "twilio")
            self.assertEqual(canal.destination_e164, destination)
            self.assertEqual(canal.mode, CanalWhatsappMode.DEDICATED)
            self.assertEqual(
                canal.id_comercio_exclusivo, self.fixtures["comercio_id"]
            )
            self.assertTrue(canal.activo)

    def test_register_shared_channel_persists(self):
        destination = self._destination()
        self.addCleanup(_delete_canales_by_destination, destination)
        with TestingSessionLocal() as session, session.begin():
            service = CanalWhatsappService(session)
            canal = service.register_shared_channel(
                provider="twilio",
                destination=destination,
            )
            self.assertEqual(canal.mode, CanalWhatsappMode.SHARED)
            self.assertIsNone(canal.id_comercio_exclusivo)
            self.assertTrue(canal.activo)

    def test_destination_normalization_canonicalizes_equivalent_inputs(self):
        destination = self._destination()
        self.addCleanup(_delete_canales_by_destination, destination)
        with TestingSessionLocal() as session, session.begin():
            service = CanalWhatsappService(session)
            canal = service.register_dedicated_channel(
                provider="twilio",
                destination=f"  whatsapp:{destination}  ",
                id_comercio_exclusivo=self.fixtures["comercio_id"],
            )
            self.assertEqual(canal.destination_e164, destination)
            session.flush()
            with self.assertRaises(DuplicateCanalWhatsappDestination):
                service.register_dedicated_channel(
                    provider="twilio",
                    destination=destination,
                    id_comercio_exclusivo=self.fixtures["comercio_id"],
                )

    def test_provider_identity_prevents_conflation(self):
        destination = self._destination()
        self.addCleanup(_delete_canales_by_destination, destination)
        with TestingSessionLocal() as session, session.begin():
            service = CanalWhatsappService(session)
            canal_a = service.register_dedicated_channel(
                provider="twilio",
                destination=destination,
                id_comercio_exclusivo=self.fixtures["comercio_id"],
            )
            self.assertEqual(canal_a.provider, "twilio")
            with self.assertRaises(InvalidCanalWhatsappProvider):
                service.register_dedicated_channel(
                    provider="other-provider",
                    destination=destination,
                    id_comercio_exclusivo=self.fixtures["comercio_id"],
                )

    def test_unknown_provider_rejected(self):
        destination = self._destination()
        self.addCleanup(_delete_canales_by_destination, destination)
        with TestingSessionLocal() as session, session.begin():
            service = CanalWhatsappService(session)
            with self.assertRaises(InvalidCanalWhatsappProvider):
                service.register_dedicated_channel(
                    provider="meta-cloud",
                    destination=destination,
                    id_comercio_exclusivo=self.fixtures["comercio_id"],
                )

    def test_deactivate_channel_marks_inactive(self):
        destination = self._destination()
        self.addCleanup(_delete_canales_by_destination, destination)
        with TestingSessionLocal() as session, session.begin():
            service = CanalWhatsappService(session)
            canal = service.register_dedicated_channel(
                provider="twilio",
                destination=destination,
                id_comercio_exclusivo=self.fixtures["comercio_id"],
            )
            session.flush()
            canal_id = int(canal.id)
            service.deactivate_channel(canal_id)
            session.flush()
            session.expire_all()
            refreshed = service._canal_repo.find_by_id(canal_id)
            self.assertIsNotNone(refreshed)
            self.assertFalse(refreshed.activo)
            self.assertIsNotNone(refreshed.fecha_baja)

    def test_dedicated_channel_rejects_shared_membership(self):
        destination = self._destination()
        self.addCleanup(_delete_canales_by_destination, destination)
        with TestingSessionLocal() as session, session.begin():
            service = CanalWhatsappService(session)
            canal = service.register_dedicated_channel(
                provider="twilio",
                destination=destination,
                id_comercio_exclusivo=self.fixtures["comercio_id"],
            )
            session.flush()
            with self.assertRaises(
                DedicatedChannelCannotHaveSharedMembership
            ):
                service.register_shared_membership(
                    canal_id=int(canal.id),
                    comercio_id=self.fixtures["comercio_id"],
                    routing_code=f"PIZZA-{self.fixtures['suffix'][:6]}-01",
                )

    def test_dedicated_channel_with_inactive_comercio_rejected(self):
        inactive = _seed_comercio_inactivo()
        self.addCleanup(
            _delete_canales_for_comercio, inactive["comercio_id"]
        )
        destination = self._destination()
        self.addCleanup(_delete_canales_by_destination, destination)
        with TestingSessionLocal() as session, session.begin():
            service = CanalWhatsappService(session)
            with self.assertRaises(CanalWhatsappNotFound):
                service.register_dedicated_channel(
                    provider="twilio",
                    destination=destination,
                    id_comercio_exclusivo=inactive["comercio_id"],
                )

    def test_shared_channel_membership_round_trip(self):
        destination = self._destination()
        self.addCleanup(_delete_canales_by_destination, destination)
        routing_code = f"P-{self.fixtures['suffix'][:6]}-01"
        with TestingSessionLocal() as session, session.begin():
            service = CanalWhatsappService(session)
            canal = service.register_shared_channel(
                provider="twilio",
                destination=destination,
            )
            session.flush()
            membership = service.register_shared_membership(
                canal_id=int(canal.id),
                comercio_id=self.fixtures["comercio_id"],
                routing_code=routing_code,
            )
            self.assertEqual(membership.routing_code, routing_code)
            self.assertEqual(membership.routing_code_normalizado, routing_code)
            self.assertTrue(membership.activo)
            self.assertEqual(membership.canal_id, int(canal.id))
            self.assertEqual(
                membership.comercio_id, self.fixtures["comercio_id"]
            )

    def test_routing_code_normalization_is_canonical(self):
        destination = self._destination()
        self.addCleanup(_delete_canales_by_destination, destination)
        routing_code = f"p-{self.fixtures['suffix'][:6]}-02"
        with TestingSessionLocal() as session, session.begin():
            service = CanalWhatsappService(session)
            canal = service.register_shared_channel(
                provider="twilio",
                destination=destination,
            )
            session.flush()
            membership = service.register_shared_membership(
                canal_id=int(canal.id),
                comercio_id=self.fixtures["comercio_id"],
                routing_code=f"  {routing_code}  ",
            )
            self.assertEqual(
                membership.routing_code_normalizado, routing_code
            )

    def test_duplicate_active_routing_code_rejected(self):
        destination = self._destination()
        self.addCleanup(_delete_canales_by_destination, destination)
        routing_code = f"P-{self.fixtures['suffix'][:6]}-03"
        with TestingSessionLocal() as session, session.begin():
            service = CanalWhatsappService(session)
            canal = service.register_shared_channel(
                provider="twilio",
                destination=destination,
            )
            session.flush()
            service.register_shared_membership(
                canal_id=int(canal.id),
                comercio_id=self.fixtures["comercio_id"],
                routing_code=routing_code,
            )
            session.flush()
            with self.assertRaises(DuplicateRoutingCodeReservation):
                service.register_shared_membership(
                    canal_id=int(canal.id),
                    comercio_id=self.fixtures["comercio_id"],
                    routing_code=f"  {routing_code}  ",
                )

    def test_revoked_routing_code_remains_reserved(self):
        destination = self._destination()
        self.addCleanup(_delete_canales_by_destination, destination)
        routing_code = f"P-{self.fixtures['suffix'][:6]}-04"
        with TestingSessionLocal() as session, session.begin():
            service = CanalWhatsappService(session)
            canal = service.register_shared_channel(
                provider="twilio",
                destination=destination,
            )
            session.flush()
            service.register_shared_membership(
                canal_id=int(canal.id),
                comercio_id=self.fixtures["comercio_id"],
                routing_code=routing_code,
            )
            session.flush()
            service.deactivate_shared_membership(
                canal_id=int(canal.id), routing_code=routing_code
            )
            with self.assertRaises(DuplicateRoutingCodeReservation):
                service.register_shared_membership(
                    canal_id=int(canal.id),
                    comercio_id=self.fixtures["comercio_id"],
                    routing_code=routing_code,
                )

    def test_deactivate_unknown_routing_code_raises_not_found(self):
        destination = self._destination()
        self.addCleanup(_delete_canales_by_destination, destination)
        unknown_code = f"X-{self.fixtures['suffix'][:6]}-00"
        with TestingSessionLocal() as session, session.begin():
            service = CanalWhatsappService(session)
            canal = service.register_shared_channel(
                provider="twilio",
                destination=destination,
            )
            session.flush()
            with self.assertRaises(CanalWhatsappNotFound):
                service.deactivate_shared_membership(
                    canal_id=int(canal.id), routing_code=unknown_code
                )

    def test_service_does_not_commit_or_rollback(self):
        destination = self._destination()
        self.addCleanup(_delete_canales_by_destination, destination)
        with TestingSessionLocal() as session, session.begin():
            service = CanalWhatsappService(session)
            canal = service.register_dedicated_channel(
                provider="twilio",
                destination=destination,
                id_comercio_exclusivo=self.fixtures["comercio_id"],
            )
            session.flush()
            initial_id = int(canal.id)
            with self.assertRaises(DuplicateCanalWhatsappDestination):
                service.register_dedicated_channel(
                    provider="twilio",
                    destination=destination,
                    id_comercio_exclusivo=self.fixtures["comercio_id"],
                )
            rows = session.scalars(
                select(CanalWhatsapp).where(
                    CanalWhatsapp.destination_e164 == destination
                )
            ).all()
            self.assertEqual([int(row.id) for row in rows], [initial_id])

    def test_assert_can_be_dedicated_rejects_shared(self):
        destination = self._destination()
        self.addCleanup(_delete_canales_by_destination, destination)
        with TestingSessionLocal() as session, session.begin():
            service = CanalWhatsappService(session)
            canal = service.register_shared_channel(
                provider="twilio",
                destination=destination,
            )
            session.flush()
            with self.assertRaises(SharedChannelCannotHaveExclusiveComercio):
                service.assert_can_be_dedicated(int(canal.id))


if __name__ == "__main__":
    unittest.main()