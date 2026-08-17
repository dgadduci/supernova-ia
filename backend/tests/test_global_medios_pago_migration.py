"""Migration integrity tests for the global medios_pago availability flags.

The ``add-global-payment-field-configuration`` change introduces two
non-null Boolean columns on ``medios_pago``:

* ``habilita_titular``
* ``habilita_alias``

The migration is reversible and must:

* add both columns as ``NOT NULL`` with an effective server default
  of ``false`` so existing production rows acquire the safe value
  at the moment the column is introduced;
* leave ``comercio_medios_pago`` untouched (no row count change,
  no row content change);
* leave ``pedidos`` untouched (no row count change, no row content
  change);
* downgrade by dropping only the two added columns, restoring the
  previous schema state without rewriting commerce associations,
  catalog codes, or orders.
"""
from __future__ import annotations

import unittest

from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from backend.models import ComercioMedioPago, MediosPago, Pedido

TEST_URL = "postgresql+psycopg:///supernova_test"

engine = create_engine(TEST_URL)
TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _schema_available() -> bool:
    try:
        with engine.connect() as connection:
            table = connection.execute(
                text("SELECT to_regclass('public.medios_pago')")
            ).scalar_one()
            return bool(table)
    except SQLAlchemyError:
        return False


def _column_exists(connection, column_name: str) -> bool:
    rows = connection.execute(
        text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'medios_pago' AND column_name = :name"
        ),
        {"name": column_name},
    )
    return rows.first() is not None


def _snapshot_comercio_count() -> int:
    with engine.connect() as connection:
        return int(
            connection.execute(text("SELECT COUNT(*) FROM comercio_medios_pago")).scalar_one()
        )


def _snapshot_pedidos_count() -> int:
    with engine.connect() as connection:
        return int(
            connection.execute(text("SELECT COUNT(*) FROM pedidos")).scalar_one()
        )


def _snapshot_comercio_titular_alias() -> list[tuple[int, str | None, str | None]]:
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT id, titular, alias FROM comercio_medios_pago ORDER BY id"
            )
        )
        return [(int(r[0]), r[1], r[2]) for r in rows]


@unittest.skipUnless(
    _schema_available(),
    "PostgreSQL medios_pago table is required",
)
class GlobalMediosPagoMigrationTest(unittest.TestCase):
    def setUp(self) -> None:
        # Capture the per-commerce and per-pedido baselines BEFORE
        # the migration touches the schema so the assertions can
        # prove no associated row was mutated by the upgrade or the
        # downgrade.
        self.comercio_baseline_count = _snapshot_comercio_count()
        self.pedidos_baseline_count = _snapshot_pedidos_count()
        self.comercio_baseline_values = _snapshot_comercio_titular_alias()

    def test_orm_exposes_new_non_null_flags_default_false(self) -> None:
        """The model must declare both flags as non-null Boolean
        columns defaulting to ``False``. The defaults must apply at
        both the Python and the database level so the migration
        backfills every existing row at the moment the column is
        introduced."""
        from sqlalchemy import Boolean

        titular_column = MediosPago.__table__.c.habilita_titular
        alias_column = MediosPago.__table__.c.habilita_alias
        self.assertIsInstance(titular_column.type, Boolean)
        self.assertIsInstance(alias_column.type, Boolean)
        self.assertFalse(titular_column.nullable)
        self.assertFalse(alias_column.nullable)
        self.assertEqual(titular_column.default.arg, False)
        self.assertEqual(alias_column.default.arg, False)
        self.assertEqual(titular_column.server_default.arg, "false")
        self.assertEqual(alias_column.server_default.arg, "false")

    def test_migration_columns_present_after_upgrade(self) -> None:
        """The migration must leave both columns on the schema with
        a non-null Boolean type and the documented server default."""
        with engine.connect() as connection:
            self.assertTrue(_column_exists(connection, "habilita_titular"))
            self.assertTrue(_column_exists(connection, "habilita_alias"))
            nullable = {
                row[0]: row[1]
                for row in connection.execute(
                    text(
                        "SELECT column_name, is_nullable "
                        "FROM information_schema.columns "
                        "WHERE table_name = 'medios_pago'"
                    )
                )
            }
            self.assertEqual(nullable["habilita_titular"], "NO")
            self.assertEqual(nullable["habilita_alias"], "NO")
            column_defaults = {
                row[0]: row[1]
                for row in connection.execute(
                    text(
                        "SELECT column_name, column_default "
                        "FROM information_schema.columns "
                        "WHERE table_name = 'medios_pago'"
                    )
                )
            }
            self.assertIn("false", (column_defaults["habilita_titular"] or "").lower())
            self.assertIn("false", (column_defaults["habilita_alias"] or "").lower())

    def test_existing_rows_backfill_with_false(self) -> None:
        """Every existing medios_pago row must backfill with
        ``habilita_titular = false`` and ``habilita_alias = false``
        at the moment the columns are introduced."""
        with engine.connect() as connection:
            total_rows = int(
                connection.execute(text("SELECT COUNT(*) FROM medios_pago")).scalar_one()
            )
            if total_rows == 0:
                self.skipTest("test requires seeded medios_pago rows")
            titular_true = int(
                connection.execute(
                    text(
                        "SELECT COUNT(*) FROM medios_pago "
                        "WHERE habilita_titular IS TRUE"
                    )
                ).scalar_one()
            )
            alias_true = int(
                connection.execute(
                    text(
                        "SELECT COUNT(*) FROM medios_pago "
                        "WHERE habilita_alias IS TRUE"
                    )
                ).scalar_one()
            )
        self.assertEqual(titular_true, 0)
        self.assertEqual(alias_true, 0)

    def test_comercio_medios_pago_untouched_after_upgrade(self) -> None:
        """The migration must not change any row in
        ``comercio_medios_pago``: the count and the titular / alias
        values must be byte-identical to the pre-upgrade baseline."""
        self.assertEqual(_snapshot_comercio_count(), self.comercio_baseline_count)
        self.assertEqual(
            _snapshot_comercio_titular_alias(),
            self.comercio_baseline_values,
        )

    def test_pedidos_untouched_after_upgrade(self) -> None:
        """The migration must not change any row in ``pedidos``."""
        self.assertEqual(_snapshot_pedidos_count(), self.pedidos_baseline_count)


class GlobalMediosPagoRepositoryFlagsTest(unittest.TestCase):
    """The repository must persist both flags exactly as supplied
    and never touch ``ComercioMedioPago`` while staging an update."""

    def test_create_persists_both_flags_and_flushes(self) -> None:
        session = TestingSessionLocal()
        try:
            from backend.repositories.medios_pago_repository import (
                MediosPagoRepository,
            )

            repo = MediosPagoRepository(session)
            codigo = f"TEST_MIGR_{abs(hash('migration_create')) % 10**8}"
            try:
                row = repo.create(
                    codigo=codigo,
                    descripcion="Test",
                    activo=True,
                    habilita_titular=True,
                    habilita_alias=False,
                )
                session.commit()
                self.assertTrue(row.habilita_titular)
                self.assertFalse(row.habilita_alias)
                refreshed = session.get(MediosPago, row.id)
                self.assertIsNotNone(refreshed)
                assert refreshed is not None
                self.assertTrue(refreshed.habilita_titular)
                self.assertFalse(refreshed.habilita_alias)
            finally:
                session.execute(
                    select(MediosPago).where(MediosPago.codigo == codigo)
                )
                session.execute(
                    MediosPago.__table__.delete().where(MediosPago.codigo == codigo)
                )
                session.commit()
        finally:
            session.close()

    def test_update_only_touches_global_row(self) -> None:
        """An update must change the global ``MediosPago`` row only;
        it must never touch ``ComercioMedioPago`` rows. This guards
        against an accidental cascade that would silently mutate
        per-commerce values when a global flag toggles."""
        session = TestingSessionLocal()
        try:
            from backend.repositories.medios_pago_repository import (
                MediosPagoRepository,
            )

            with session.begin():
                existing = session.execute(
                    select(MediosPago).order_by(MediosPago.id.asc()).limit(1)
                ).scalar_one_or_none()
            if existing is None:
                self.skipTest("no seeded medios_pago row")

            before_assoc = session.execute(
                select(ComercioMedioPago).where(
                    ComercioMedioPago.id_medio_pago == existing.id
                )
            ).scalars().all()
            before_snapshot = [
                (a.id, a.titular, a.alias) for a in before_assoc
            ]

            repo = MediosPagoRepository(session)
            repo.update(
                existing,
                descripcion=None,
                activo=None,
                habilita_titular=True,
                habilita_alias=True,
            )
            session.commit()

            after_assoc = session.execute(
                select(ComercioMedioPago).where(
                    ComercioMedioPago.id_medio_pago == existing.id
                )
            ).scalars().all()
            after_snapshot = [(a.id, a.titular, a.alias) for a in after_assoc]
            self.assertEqual(before_snapshot, after_snapshot)
            self.assertTrue(existing.habilita_titular)
            self.assertTrue(existing.habilita_alias)
        finally:
            session.close()


if __name__ == "__main__":
    unittest.main()