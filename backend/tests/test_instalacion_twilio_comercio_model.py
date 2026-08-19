"""Focused tests for the ``InstalacionTwilioComercio`` model.

The tests cover the documented schema invariants of the new
technical installation registry:

* the table name and column set;
* the column types and nullability;
* the unique index on ``instalacion_id``;
* the secondary index on ``id_comercio``;
* the foreign key to ``comercios.id`` with ``RESTRICT``;
* the regex pattern that constrains the opaque ``instalacion_id``
  to a 24-character lowercase alphanumeric string;
* the active lifecycle flag and the optional ``fecha_baja``.
"""
from __future__ import annotations

import re
import unittest
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    delete,
    select,
    text,
)
from sqlalchemy.orm import sessionmaker

from backend.models import (
    Comercio,
    EstadoComercio,
    InstalacionTwilioComercio,
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
        return int(row[0])


def _estado_id_activo() -> int:
    return _estado_id("ACTIVO")


def _seed_comercio(suffix: str | None = None) -> dict:
    suffix = suffix or _suffix()
    with TestingSessionLocal() as session, session.begin():
        comercio = Comercio(
            nombre_fantasia=f"Install Test {suffix}",
            nombre_corto=f"IT {suffix}",
            razon_social=f"Install Test SRL {suffix}",
            cuit=f"30-{suffix[:8]}-{suffix[8]}",
            whatsapp=f"+54913{suffix[:8]}",
            calle="Av. Install",
            numero="100",
            piso_departamento=None,
            localidad="CABA",
            provincia="Buenos Aires",
            codigo_postal="C1000",
            slug=f"install-test-{suffix}",
            estado_id=_estado_id_activo(),
        )
        session.add(comercio)
        session.flush()
        comercio_id = int(comercio.id)
    return {"comercio_id": comercio_id, "suffix": suffix}


def _delete_installation(instalacion_id: str) -> None:
    with TestingSessionLocal() as session, session.begin():
        session.execute(
            delete(InstalacionTwilioComercio).where(
                InstalacionTwilioComercio.instalacion_id == instalacion_id
            )
        )


def _delete_comercio(comercio_id: int) -> None:
    with TestingSessionLocal() as session, session.begin():
        session.execute(
            delete(InstalacionTwilioComercio).where(
                InstalacionTwilioComercio.id_comercio == comercio_id
            )
        )
        session.execute(delete(Comercio).where(Comercio.id == comercio_id))


def _make_instalacion_id() -> str:
    return "".join(secrets_choice(ascii_lowercase + digits) for _ in range(24))


def secrets_choice(seq: str) -> str:
    import secrets as _s

    return _s.choice(seq)


ascii_lowercase = "abcdefghijklmnopqrstuvwxyz"
digits = "0123456789"


class InstalacionTwilioComercioSchemaTest(unittest.TestCase):
    def test_table_name(self) -> None:
        self.assertEqual(
            InstalacionTwilioComercio.__tablename__,
            "instalaciones_twilio_comercio",
        )

    def test_required_columns(self) -> None:
        table = InstalacionTwilioComercio.__table__
        self.assertEqual(
            set(table.columns.keys()),
            {
                "id",
                "id_comercio",
                "tc_service_url",
                "instalacion_id",
                "activo",
                "secreto_envelope",
                "secreto_envelope_kid",
                "fecha_alta",
                "fecha_ultima_modificacion",
                "fecha_baja",
            },
        )

    def test_primary_key_is_autoincrement(self) -> None:
        table = InstalacionTwilioComercio.__table__
        self.assertIsInstance(table.c.id.type, Integer)
        self.assertTrue(table.c.id.primary_key)

    def test_instalacion_id_column_type(self) -> None:
        table = InstalacionTwilioComercio.__table__
        self.assertIsInstance(table.c.instalacion_id.type, String)
        self.assertEqual(table.c.instalacion_id.type.length, 24)
        self.assertFalse(table.c.instalacion_id.nullable)

    def test_tc_service_url_column_type(self) -> None:
        table = InstalacionTwilioComercio.__table__
        self.assertIsInstance(table.c.tc_service_url.type, String)
        self.assertEqual(table.c.tc_service_url.type.length, 512)
        self.assertFalse(table.c.tc_service_url.nullable)

    def test_activo_column_is_boolean(self) -> None:
        table = InstalacionTwilioComercio.__table__
        self.assertIsInstance(table.c.activo.type, Boolean)
        self.assertFalse(table.c.activo.nullable)

    def test_secreto_envelope_column_is_text(self) -> None:
        table = InstalacionTwilioComercio.__table__
        self.assertIsInstance(table.c.secreto_envelope.type, Text)
        self.assertFalse(table.c.secreto_envelope.nullable)

    def test_secreto_envelope_kid_column_type(self) -> None:
        table = InstalacionTwilioComercio.__table__
        self.assertIsInstance(table.c.secreto_envelope_kid.type, String)
        self.assertEqual(table.c.secreto_envelope_kid.type.length, 64)
        self.assertFalse(table.c.secreto_envelope_kid.nullable)

    def test_fecha_alta_and_modificacion_are_timestamps(self) -> None:
        table = InstalacionTwilioComercio.__table__
        self.assertIsInstance(table.c.fecha_alta.type, DateTime)
        self.assertTrue(table.c.fecha_alta.type.timezone)
        self.assertIsInstance(table.c.fecha_ultima_modificacion.type, DateTime)
        self.assertTrue(table.c.fecha_ultima_modificacion.type.timezone)

    def test_fecha_baja_is_nullable_timestamp(self) -> None:
        table = InstalacionTwilioComercio.__table__
        self.assertIsInstance(table.c.fecha_baja.type, DateTime)
        self.assertTrue(table.c.fecha_baja.nullable)

    def test_unique_index_on_instalacion_id(self) -> None:
        table = InstalacionTwilioComercio.__table__
        constraints = [
            c
            for c in table.constraints
            if isinstance(c, UniqueConstraint)
        ]
        names = {c.name for c in constraints}
        self.assertIn("uq_instalacion_twilio_instalacion_id", names)
        unique = next(
            c
            for c in constraints
            if c.name == "uq_instalacion_twilio_instalacion_id"
        )
        self.assertEqual(list(unique.columns.keys()), ["instalacion_id"])

    def test_index_on_id_comercio(self) -> None:
        table = InstalacionTwilioComercio.__table__
        indexes = [i for i in table.indexes if isinstance(i, Index)]
        names = {i.name for i in indexes}
        self.assertIn("ix_instalaciones_twilio_comercio_id_comercio", names)
        idx = next(
            i
            for i in indexes
            if i.name == "ix_instalaciones_twilio_comercio_id_comercio"
        )
        self.assertEqual(list(idx.columns.keys()), ["id_comercio"])

    def test_foreign_key_to_comercios_uses_restrict(self) -> None:
        table = InstalacionTwilioComercio.__table__
        fk = next(iter(table.c.id_comercio.foreign_keys))
        self.assertEqual(str(fk.target_fullname), "comercios.id")
        self.assertEqual(fk.ondelete, "RESTRICT")

    def test_database_table_present(self) -> None:
        with engine.connect() as c:
            row = c.execute(
                text(
                    "SELECT to_regclass('public.instalaciones_twilio_comercio')"
                )
            ).first()
        self.assertIsNotNone(row)
        if row is None:
            self.fail("database returned no row")
        self.assertIsNotNone(row[0])

    def test_database_unique_index_present(self) -> None:
        with engine.connect() as c:
            rows = c.execute(
                text(
                    "SELECT indexname FROM pg_indexes "
                    "WHERE tablename = 'instalaciones_twilio_comercio'"
                )
            ).all()
        names = {r[0] for r in rows}
        self.assertIn("uq_instalacion_twilio_instalacion_id", names)
        self.assertIn(
            "ix_instalaciones_twilio_comercio_id_comercio", names
        )
        self.assertIn(
            "uq_instalacion_twilio_one_active_per_comercio", names
        )

    def test_database_idempotency_table_present(self) -> None:
        with engine.connect() as c:
            row = c.execute(
                text(
                    "SELECT to_regclass("
                    "'public.instalaciones_twilio_comercio_idempotencia')"
                )
            ).first()
        self.assertIsNotNone(row)
        if row is None:
            self.fail("database returned no row")
        self.assertIsNotNone(row[0])

    def test_database_idempotency_unique_constraint_present(self) -> None:
        with engine.connect() as c:
            rows = c.execute(
                text(
                    "SELECT indexname FROM pg_indexes "
                    "WHERE tablename = "
                    "'instalaciones_twilio_comercio_idempotencia'"
                )
            ).all()
        names = {r[0] for r in rows}
        self.assertIn(
            "uq_instalacion_twilio_idempotencia_installation_key", names
        )

    def test_database_foreign_key_present(self) -> None:
        with engine.connect() as c:
            row = c.execute(
                text(
                    "SELECT confdeltype FROM pg_constraint "
                    "WHERE conname = 'instalaciones_twilio_comercio_comercio_fk'"
                )
            ).first()
        self.assertIsNotNone(row)
        if row is None:
            self.fail("database returned no row")
        self.assertEqual(row[0], "r")

    def test_instalacion_id_pattern_matches_only_lowercase_alphanumeric(self) -> None:
        from backend.models.instalacion_twilio_comercio import (
            INSTALLACION_ID_PATTERN,
        )

        self.assertTrue(INSTALLACION_ID_PATTERN.match("a" * 24))
        self.assertTrue(INSTALLACION_ID_PATTERN.match("0" * 24))
        self.assertTrue(
            INSTALLACION_ID_PATTERN.match("abcdef0123456789abcdef01")
        )
        self.assertFalse(INSTALLACION_ID_PATTERN.match("A" * 24))
        self.assertFalse(INSTALLACION_ID_PATTERN.match("a" * 23))
        self.assertFalse(INSTALLACION_ID_PATTERN.match("a" * 25))
        self.assertFalse(
            INSTALLACION_ID_PATTERN.match("a" * 23 + "!")
        )
        self.assertFalse(INSTALLACION_ID_PATTERN.match(""))


class InstalacionTwilioComercioPersistenceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.seeded = _seed_comercio()
        self.comercio_id = int(self.seeded["comercio_id"])

    def tearDown(self) -> None:
        _delete_comercio(self.comercio_id)

    def _insert_row(self, instalacion_id: str) -> int:
        with TestingSessionLocal() as session, session.begin():
            row = InstalacionTwilioComercio(
                id_comercio=self.comercio_id,
                tc_service_url="https://tc.example.test",
                instalacion_id=instalacion_id,
                activo=True,
                secreto_envelope="gAAAAA-test-envelope",
                secreto_envelope_kid="current",
            )
            session.add(row)
            session.flush()
            return int(row.id)

    def test_insert_and_fetch_round_trip(self) -> None:
        instalacion_id = _make_instalacion_id()
        try:
            row_id = self._insert_row(instalacion_id)
            with TestingSessionLocal() as session:
                row = session.get(InstalacionTwilioComercio, row_id)
                self.assertIsNotNone(row)
                if row is None:
                    self.fail("row not found")
                self.assertEqual(row.instalacion_id, instalacion_id)
                self.assertEqual(row.id_comercio, self.comercio_id)
                self.assertTrue(row.activo)
                self.assertIsNone(row.fecha_baja)
        finally:
            _delete_installation(instalacion_id)

    def test_unique_instalacion_id_is_enforced(self) -> None:
        from sqlalchemy.exc import IntegrityError

        instalacion_id = _make_instalacion_id()
        try:
            self._insert_row(instalacion_id)
            with TestingSessionLocal() as session, session.begin():
                duplicate = InstalacionTwilioComercio(
                    id_comercio=self.comercio_id,
                    tc_service_url="https://tc.example.test",
                    instalacion_id=instalacion_id,
                    activo=True,
                    secreto_envelope="gAAAAA-test-envelope",
                    secreto_envelope_kid="current",
                )
                session.add(duplicate)
                with self.assertRaises(IntegrityError):
                    session.flush()
        finally:
            _delete_installation(instalacion_id)

    def test_delete_cascades_not_allowed(self) -> None:
        import logging

        logger = logging.getLogger(__name__)

        instalacion_id = _make_instalacion_id()
        try:
            self._insert_row(instalacion_id)
            with TestingSessionLocal() as session, session.begin():
                session.execute(
                    delete(Comercio).where(Comercio.id == self.comercio_id)
                )
        except Exception as exc:
            logger.debug("expected failure: %s", exc)
        with TestingSessionLocal() as session:
            count = session.execute(
                select(InstalacionTwilioComercio).where(
                    InstalacionTwilioComercio.id_comercio == self.comercio_id
                )
            ).all()
            self.assertGreaterEqual(len(count), 1)
        _delete_installation(instalacion_id)

    def test_fecha_alta_is_populated_by_default(self) -> None:
        instalacion_id = _make_instalacion_id()
        try:
            self._insert_row(instalacion_id)
            with TestingSessionLocal() as session:
                row = session.execute(
                    select(InstalacionTwilioComercio).where(
                        InstalacionTwilioComercio.instalacion_id
                        == instalacion_id
                    )
                ).scalar_one()
                self.assertIsNotNone(row.fecha_alta)
                self.assertIsInstance(row.fecha_alta, datetime)
        finally:
            _delete_installation(instalacion_id)

    def test_secreto_envelope_kid_is_persisted(self) -> None:
        instalacion_id = _make_instalacion_id()
        try:
            with TestingSessionLocal() as session, session.begin():
                row = InstalacionTwilioComercio(
                    id_comercio=self.comercio_id,
                    tc_service_url="https://tc.example.test",
                    instalacion_id=instalacion_id,
                    activo=True,
                    secreto_envelope="gAAAAA-payload",
                    secreto_envelope_kid="previous",
                )
                session.add(row)
                session.flush()
            with TestingSessionLocal() as session:
                fetched = session.execute(
                    select(InstalacionTwilioComercio).where(
                        InstalacionTwilioComercio.instalacion_id
                        == instalacion_id
                    )
                ).scalar_one()
                self.assertEqual(fetched.secreto_envelope_kid, "previous")
        finally:
            _delete_installation(instalacion_id)


class InstalacionPatternTest(unittest.TestCase):
    def test_pattern_compiles(self) -> None:
        from backend.models.instalacion_twilio_comercio import (
            INSTALLACION_ID_PATTERN,
        )

        self.assertIsInstance(INSTALLACION_ID_PATTERN, re.Pattern)
        self.assertEqual(INSTALLACION_ID_PATTERN.pattern, r"^[a-z0-9]{24}$")


if __name__ == "__main__":
    unittest.main(verbosity=2)
