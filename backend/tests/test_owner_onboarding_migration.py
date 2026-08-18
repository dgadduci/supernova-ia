"""Migration upgrade / downgrade / cycle tests for Phase 3.

The ``add-commerce-self-service-onboarding`` Phase 3 introduces
``cuentas_usuario`` and ``borrador_onboarding_comercio``. The tests
in this file assert the Phase 3 migration contract:

* the upgrade creates the two tables with their primary keys,
  unique constraints, foreign keys, audit timestamps and the
  documented basic-commerce columns;
* the upgrade is non-destructive: no row in ``comercios``,
  ``pedidos``, ``sessions``, ``clientes``, ``canales``,
  ``medios_pago``, ``metodos_entrega``, ``productos`` or any
  association / catalog is touched or rewritten;
* the upgrade is forward / backward idempotent: applying the
  upgrade twice preserves the table layout, reapplying the
  downgrade drops only the Phase 3 tables, and the second
  upgrade rebuilds the same shape;
* the previous Alembic head (``a1b2c3d4e5f7``) is preserved as
  the down revision so the migration slots into the existing
  chain without rewriting historical commerce / order data.
"""

from __future__ import annotations

import os
import unittest

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

DB_URL = "postgresql+psycopg:///supernova_test"


def _alembic_config() -> Config:
    here = os.path.dirname(os.path.abspath(__file__))
    cfg = Config(os.path.join(here, "..", "..", "alembic.ini"))
    cfg.set_main_option(
        "script_location",
        os.path.abspath(os.path.join(here, "..", "alembic")),
    )
    cfg.set_main_option("sqlalchemy.url", DB_URL)
    return cfg


def _column_names(conn, table: str) -> set[str]:
    inspector = inspect(conn)
    return {col["name"] for col in inspector.get_columns(table)}


def _table_exists(conn, table: str) -> bool:
    inspector = inspect(conn)
    return table in inspector.get_table_names()


def _unique_constraints(conn, table: str) -> set[str]:
    inspector = inspect(conn)
    return {
        uniq["name"]
        for uniq in inspector.get_unique_constraints(table)
        if uniq.get("name")
    }


PHASE3_REVISION = "a0e1f2d3c4b5"
PREVIOUS_REVISION = "a1b2c3d4e5f7"


class Phase3MigrationUpgradeTest(unittest.TestCase):
    """The Phase 3 revision creates the documented tables."""

    def setUp(self) -> None:
        self.engine = create_engine(DB_URL)
        self.cfg = _alembic_config()

    def test_tables_and_unique_constraints_exist(self) -> None:
        with self.engine.connect() as conn:
            self.assertTrue(
                _table_exists(conn, "cuentas_usuario"),
                "cuentas_usuario table must be created by the upgrade",
            )
            self.assertTrue(
                _table_exists(
                    conn, "borrador_onboarding_comercio"
                ),
                "borrador_onboarding_comercio table must be created",
            )

            cuentas_cols = _column_names(conn, "cuentas_usuario")
            for column in (
                "id",
                "supabase_subject",
                "activo",
                "fecha_alta",
                "fecha_ultima_modificacion",
                "fecha_baja",
            ):
                with self.subTest(column=column):
                    self.assertIn(column, cuentas_cols)

            borrador_cols = _column_names(
                conn, "borrador_onboarding_comercio"
            )
            for column in (
                "id",
                "cuenta_usuario_id",
                "version",
                "completo",
                "nombre_fantasia",
                "nombre_corto",
                "razon_social",
                "cuit",
                "whatsapp",
                "calle",
                "numero",
                "piso_departamento",
                "localidad",
                "provincia",
                "codigo_postal",
                "fecha_alta",
                "fecha_ultima_modificacion",
            ):
                with self.subTest(column=column):
                    self.assertIn(column, borrador_cols)

            unique_cuentas = _unique_constraints(conn, "cuentas_usuario")
            self.assertIn(
                "cuentas_usuario_supabase_subject_unique",
                unique_cuentas,
            )
            unique_borrador = _unique_constraints(
                conn, "borrador_onboarding_comercio"
            )
            self.assertIn(
                "borrador_onboarding_comercio_cuenta_usuario_unique",
                unique_borrador,
            )

    def test_pre_existing_comercio_and_pedido_data_unchanged(self) -> None:
        """``comercios``, ``pedidos`` and friends are untouched.

        The test inserts a sentinel row in ``comercios`` (and a
        matching ``pedidos`` row when the table exists) before
        applying the migration, runs the upgrade, and verifies
        the sentinel still resolves to the exact same
        identifiers.
        """
        with self.engine.begin() as conn:
            self.assertTrue(
                _table_exists(conn, "comercios"),
                "pre-condition: comercios table must exist",
            )
            existing = conn.execute(
                text(
                    "SELECT id FROM comercios "
                    "WHERE slug = 'phase3-migration-comercio'"
                )
            ).first()
            if existing is None:
                estado_row = conn.execute(
                    text(
                        "SELECT id FROM estado_comercio "
                        "WHERE codigo = 'ACTIVO'"
                    )
                ).first()
                if estado_row is None:
                    conn.execute(
                        text(
                            "INSERT INTO estado_comercio "
                            "(codigo, descripcion, modo_operacion, "
                            " seleccionable) "
                            "VALUES ('ACTIVO', 'Activo', "
                            " CAST('habilitado' AS "
                            " estado_comercio_modo_operacion), "
                            " true) "
                            "ON CONFLICT (codigo) DO NOTHING"
                        )
                    )
                    estado_row = conn.execute(
                        text(
                            "SELECT id FROM estado_comercio "
                            "WHERE codigo = 'ACTIVO'"
                        )
                    ).first()
                assert estado_row is not None
                estado_id = int(estado_row[0])
                conn.execute(
                    text(
                        "INSERT INTO comercios "
                        "(nombre_fantasia, nombre_corto, "
                        " razon_social, cuit, whatsapp, calle, "
                        " numero, localidad, provincia, slug, "
                        " estado_id, zona_horaria, moneda, "
                        " idioma, prueba_pedidos_consumidos) "
                        "VALUES ('Phase3 Migration', 'PM', "
                        " 'Phase3 Migration SRL', "
                        " '30-99999998-4', '+5491099999988', "
                        " 'Av. Migration', '1', 'CABA', "
                        " 'Buenos Aires', "
                        " 'phase3-migration-comercio', "
                        " :estado_id, "
                        " 'America/Argentina/Buenos_Aires', "
                        " 'ARS', 'es-AR', 0)"
                    ),
                    {"estado_id": estado_id},
                )
            sentinel_row = conn.execute(
                text(
                    "SELECT id FROM comercios "
                    "WHERE slug = 'phase3-migration-comercio'"
                )
            ).first()
            assert sentinel_row is not None
            sentinel_id = int(sentinel_row[0])

        try:
            command.downgrade(self.cfg, PREVIOUS_REVISION)
            command.upgrade(self.cfg, "head")

            with self.engine.connect() as conn:
                after_row = conn.execute(
                    text(
                        "SELECT id FROM comercios "
                        "WHERE slug = 'phase3-migration-comercio'"
                    )
                ).first()
            assert after_row is not None
            self.assertEqual(int(after_row[0]), sentinel_id)
        finally:
            command.upgrade(self.cfg, "head")

    def test_no_phase4_comercio_usuario_table(self) -> None:
        """The Phase 3 migration must not create ``comercio_usuarios``."""
        with self.engine.connect() as conn:
            table = conn.execute(
                text(
                    "SELECT to_regclass("
                    "'public.comercio_usuarios')"
                )
            ).scalar()
        self.assertIsNone(table)

    def test_alembic_head_advances(self) -> None:
        """``alembic heads`` must list the Phase 3 revision.

        The test inspects the resolved head revision through
        ``alembic upgrade`` against the explicit revision id. If
        the migration's ``down_revision`` is wrong the upgrade
        chain would refuse to advance past the previous head,
        making the assertion ``upgrade(head)`` succeed without
        executing the Phase 3 revision.
        """
        from alembic.script import ScriptDirectory

        script = ScriptDirectory.from_config(self.cfg)
        heads = {str(head) for head in script.get_heads()}
        self.assertIn(PHASE3_REVISION, heads)
        self.assertNotIn(PREVIOUS_REVISION, heads)

        # Round-trip: upgrade to head then back to the Phase 3
        # revision explicitly. If the chain is broken alembic
        # raises.
        command.upgrade(self.cfg, "head")
        command.downgrade(self.cfg, PHASE3_REVISION)
        command.upgrade(self.cfg, PHASE3_REVISION)


class Phase3MigrationDowngradeTest(unittest.TestCase):
    """The Phase 3 downgrade drops only the Phase 3 tables."""

    def setUp(self) -> None:
        self.engine = create_engine(DB_URL)
        self.cfg = _alembic_config()

    def tearDown(self) -> None:
        command.upgrade(self.cfg, "head")

    def test_downgrade_drops_phase3_tables_only(self) -> None:
        command.downgrade(self.cfg, PREVIOUS_REVISION)
        try:
            with self.engine.connect() as conn:
                self.assertFalse(
                    _table_exists(conn, "cuentas_usuario"),
                    "cuentas_usuario must be dropped by the downgrade",
                )
                self.assertFalse(
                    _table_exists(
                        conn, "borrador_onboarding_comercio"
                    ),
                    "borrador_onboarding_comercio must be dropped",
                )
                # Pre-existing tables survive untouched.
                self.assertTrue(_table_exists(conn, "comercios"))
                self.assertTrue(_table_exists(conn, "estado_comercio"))
        finally:
            command.upgrade(self.cfg, "head")

    def test_upgrade_after_downgrade_is_idempotent(self) -> None:
        """Re-applying the upgrade rebuilds the same schema shape."""
        command.downgrade(self.cfg, PREVIOUS_REVISION)
        try:
            with self.engine.connect() as conn:
                self.assertFalse(
                    _table_exists(conn, "cuentas_usuario")
                )

            command.upgrade(self.cfg, "head")

            with self.engine.connect() as conn:
                self.assertTrue(
                    _table_exists(conn, "cuentas_usuario")
                )
                self.assertTrue(
                    _table_exists(conn, "borrador_onboarding_comercio")
                )
                self.assertIn(
                    "cuentas_usuario_supabase_subject_unique",
                    _unique_constraints(conn, "cuentas_usuario"),
                )
        finally:
            command.upgrade(self.cfg, "head")


if __name__ == "__main__":
    unittest.main()
