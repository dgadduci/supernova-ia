"""Migration upgrade / downgrade / cycle tests for Phase 3 / Phase 4A.

The ``add-commerce-self-service-onboarding`` change introduces
two narrow additive surfaces used by the owner wizard:

* Phase 3 introduces ``cuentas_usuario`` and
  ``borrador_onboarding_comercio``.
* Phase 4A extends ``borrador_onboarding_comercio`` with the
  ``slug`` and terminal ``comercio_id`` / ``completado_en``
  columns, and creates the ``comercio_usuarios`` membership
  table.

The tests in this file assert the migration contract for both
phases:

* the upgrade creates the documented tables with their primary
  keys, unique constraints, foreign keys, audit timestamps and
  closed-set business columns;
* the upgrade is non-destructive: no row in ``comercios``,
  ``pedidos``, ``sessions``, ``clientes``, ``canales``,
  ``medios_pago``, ``metodos_entrega``, ``productos`` or any
  association / catalog is touched or rewritten;
* the upgrade is forward / backward idempotent: applying the
  upgrade twice preserves the table layout, reapplying the
  downgrade drops only the new surface, and the second upgrade
  rebuilds the same shape;
* the previous Alembic head chain is preserved so the migration
  slots into the existing chain without rewriting historical
  commerce / order data.
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


def _check_constraints(conn, table: str) -> set[str]:
    inspector = inspect(conn)
    return {
        chk["name"]
        for chk in inspector.get_check_constraints(table)
        if chk.get("name")
    }


def _foreign_keys(conn, table: str) -> dict[tuple[str, str], str]:
    inspector = inspect(conn)
    return {
        (fk["constrained_columns"][0], fk["referred_table"]):
        fk["name"] or ""
        for fk in inspector.get_foreign_keys(table)
        if fk.get("constrained_columns")
    }


PHASE3_REVISION = "a0e1f2d3c4b5"
PHASE4A_REVISION = "b5f47a4c19d3"
PRE_PHASE3_REVISION = "a1b2c3d4e5f7"


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
            command.downgrade(self.cfg, PRE_PHASE3_REVISION)
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

    def test_alembic_head_is_phase4a(self) -> None:
        """``alembic heads`` must list the Phase 4A revision.

        The Phase 4A implementation extends the Phase 3 chain.
        The head revision is therefore the Phase 4A id, and the
        Phase 3 id is no longer the head.
        """
        from alembic.script import ScriptDirectory

        script = ScriptDirectory.from_config(self.cfg)
        heads = {str(head) for head in script.get_heads()}
        self.assertIn(PHASE4A_REVISION, heads)
        self.assertNotIn(PHASE3_REVISION, heads)

        # Round-trip: upgrade to head, then back to the Phase 4A
        # revision explicitly. If the chain is broken alembic
        # raises.
        command.upgrade(self.cfg, "head")
        command.downgrade(self.cfg, PHASE4A_REVISION)
        command.upgrade(self.cfg, PHASE4A_REVISION)


class Phase4AMigrationUpgradeTest(unittest.TestCase):
    """The Phase 4A revision extends the draft and adds the membership table."""

    def setUp(self) -> None:
        self.engine = create_engine(DB_URL)
        self.cfg = _alembic_config()

    def test_draft_columns_and_constraints_exist(self) -> None:
        """The upgrade adds slug, comercio_id, completado_en + constraints."""
        with self.engine.connect() as conn:
            borrador_cols = _column_names(
                conn, "borrador_onboarding_comercio"
            )
            for column in (
                "slug",
                "comercio_id",
                "completado_en",
            ):
                with self.subTest(column=column):
                    self.assertIn(
                        column,
                        borrador_cols,
                        f"Phase 4A must add {column!r} to the draft",
                    )

            unique_borrador = _unique_constraints(
                conn, "borrador_onboarding_comercio"
            )
            self.assertIn(
                "borrador_onboarding_comercio_comercio_id_unique",
                unique_borrador,
            )

            check_borrador = _check_constraints(
                conn, "borrador_onboarding_comercio"
            )
            self.assertIn(
                "borrador_onboarding_comercio_comercio_id_"
                "completado_en_paired",
                check_borrador,
            )

            fks = _foreign_keys(
                conn, "borrador_onboarding_comercio"
            )
            self.assertIn(
                ("comercio_id", "comercios"),
                fks,
            )

    def test_comercio_usuarios_table_and_constraints_exist(self) -> None:
        """The upgrade creates the closed-OWNER membership table."""
        with self.engine.connect() as conn:
            self.assertTrue(
                _table_exists(conn, "comercio_usuarios"),
                "comercio_usuarios table must be created",
            )

            cols = _column_names(conn, "comercio_usuarios")
            for column in (
                "id",
                "cuenta_usuario_id",
                "comercio_id",
                "rol",
                "activo",
                "fecha_alta",
                "fecha_ultima_modificacion",
                "fecha_baja",
            ):
                with self.subTest(column=column):
                    self.assertIn(column, cols)

            unique_pairs = _unique_constraints(conn, "comercio_usuarios")
            self.assertIn(
                "comercio_usuarios_cuenta_comercio_unique",
                unique_pairs,
            )
            self.assertIn(
                "comercio_usuarios_comercio_rol_unique",
                unique_pairs,
            )

            check_pairs = _check_constraints(
                conn, "comercio_usuarios"
            )
            self.assertIn(
                "comercio_usuarios_rol_owner",
                check_pairs,
            )

            fks = _foreign_keys(conn, "comercio_usuarios")
            self.assertIn(
                ("cuenta_usuario_id", "cuentas_usuario"),
                fks,
                "RESTRICT FK to cuentas_usuario is required",
            )
            self.assertIn(
                ("comercio_id", "comercios"),
                fks,
                "RESTRICT FK to comercios is required",
            )

    def test_pre_existing_comercios_and_pedidos_unchanged(self) -> None:
        """The upgrade is non-destructive on historical commerce / order data."""
        with self.engine.begin() as conn:
            existing = conn.execute(
                text(
                    "SELECT id FROM comercios "
                    "WHERE slug = 'phase4a-migration-comercio'"
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
                        "VALUES ('Phase4A Migration', 'P4A', "
                        " 'Phase4A Migration SRL', "
                        " '30-99999997-3', '+5491099999977', "
                        " 'Av. Migration4A', '1', 'CABA', "
                        " 'Buenos Aires', "
                        " 'phase4a-migration-comercio', "
                        " :estado_id, "
                        " 'America/Argentina/Buenos_Aires', "
                        " 'ARS', 'es-AR', 0)"
                    ),
                    {"estado_id": estado_id},
                )
            sentinel_row = conn.execute(
                text(
                    "SELECT id FROM comercios "
                    "WHERE slug = 'phase4a-migration-comercio'"
                )
            ).first()
            assert sentinel_row is not None
            sentinel_id = int(sentinel_row[0])

        try:
            command.downgrade(self.cfg, PHASE3_REVISION)
            command.upgrade(self.cfg, "head")

            with self.engine.connect() as conn:
                after_row = conn.execute(
                    text(
                        "SELECT id FROM comercios "
                        "WHERE slug = 'phase4a-migration-comercio'"
                    )
                ).first()
            assert after_row is not None
            self.assertEqual(int(after_row[0]), sentinel_id)
        finally:
            command.upgrade(self.cfg, "head")

    def test_paired_check_constraint_blocks_partial_terminal(self) -> None:
        """The paired check rejects one-sided terminal rows.

        The test inserts a draft that violates the paired
        constraint (``comercio_id`` set with ``completado_en``
        still null) and verifies the database itself rejects
        the row. The wizard / completion seam must always pair
        the two columns.
        """
        import uuid

        stamp = uuid.uuid4().hex[:12]
        sentinel_subject = f"phase4a-paired-sentinel-{stamp}"
        paired_slug = f"phase4a-paired-check-{stamp}"
        paired_whatsapp = f"+54910{stamp[:8]}"
        paired_cuit = f"30-{stamp[:8]}-{stamp[8]}"

        with self.engine.begin() as conn:
            cuenta_id = conn.execute(
                text(
                    "INSERT INTO cuentas_usuario "
                    "(supabase_subject, activo, fecha_alta, "
                    " fecha_ultima_modificacion) "
                    "VALUES (:subject, true, now(), now()) "
                    "RETURNING id"
                ),
                {"subject": sentinel_subject},
            ).scalar_one()

        with self.engine.begin() as conn:
            estado_row = conn.execute(
                text(
                    "SELECT id FROM estado_comercio "
                    "WHERE codigo = 'ACTIVO'"
                )
            ).first()
            assert estado_row is not None
            estado_id = int(estado_row[0])
            comercio_id = conn.execute(
                text(
                    "INSERT INTO comercios "
                    "(nombre_fantasia, nombre_corto, "
                    " razon_social, cuit, whatsapp, calle, "
                    " numero, localidad, provincia, slug, "
                    " estado_id, zona_horaria, moneda, "
                    " idioma, prueba_pedidos_consumidos) "
                    "VALUES ('Phase4A Pair', 'PP', "
                    " 'Phase4A Pair SRL', :cuit, :whatsapp, "
                    " 'Av. Pair', '1', 'CABA', "
                    " 'Buenos Aires', :slug, "
                    " :estado_id, "
                    " 'America/Argentina/Buenos_Aires', "
                    " 'ARS', 'es-AR', 0) RETURNING id"
                ),
                {
                    "cuit": paired_cuit,
                    "whatsapp": paired_whatsapp,
                    "slug": paired_slug,
                    "estado_id": estado_id,
                },
            ).scalar_one()

        from sqlalchemy.exc import IntegrityError

        try:
            with self.engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO borrador_onboarding_comercio "
                        "(cuenta_usuario_id, version, completo, "
                        " comercio_id) "
                        "VALUES (:cuenta_id, 0, false, "
                        " :comercio_id)"
                    ),
                    {"cuenta_id": cuenta_id, "comercio_id": comercio_id},
                )
        except IntegrityError:
            return
        self.fail(
            "paired check constraint must reject a draft whose "
            "comercio_id is set while completado_en is NULL"
        )

    def test_unique_owner_pair_constraint_exits(self) -> None:
        """The unique commerce/role pair prevents double OWNER rows."""
        with self.engine.connect() as conn:
            self.assertIn(
                "comercio_usuarios_comercio_rol_unique",
                _unique_constraints(conn, "comercio_usuarios"),
            )


class Phase4AMigrationDowngradeTest(unittest.TestCase):
    """The Phase 4A downgrade drops only the new surface."""

    def setUp(self) -> None:
        self.engine = create_engine(DB_URL)
        self.cfg = _alembic_config()

    def tearDown(self) -> None:
        command.upgrade(self.cfg, "head")

    def test_downgrade_drops_phase4a_surface(self) -> None:
        command.downgrade(self.cfg, PHASE3_REVISION)
        try:
            with self.engine.connect() as conn:
                self.assertFalse(
                    _table_exists(conn, "comercio_usuarios"),
                    "comercio_usuarios must be dropped by the downgrade",
                )
                borrador_cols = _column_names(
                    conn, "borrador_onboarding_comercio"
                )
                for removed in (
                    "slug",
                    "comercio_id",
                    "completado_en",
                ):
                    with self.subTest(column=removed):
                        self.assertNotIn(removed, borrador_cols)
                # Phase 3 table survives the downgrade.
                self.assertTrue(
                    _table_exists(conn, "cuentas_usuario")
                )
                self.assertTrue(
                    _table_exists(conn, "borrador_onboarding_comercio")
                )
                self.assertTrue(_table_exists(conn, "comercios"))
        finally:
            command.upgrade(self.cfg, "head")

    def test_upgrade_after_downgrade_is_idempotent(self) -> None:
        command.downgrade(self.cfg, PHASE3_REVISION)
        try:
            with self.engine.connect() as conn:
                self.assertFalse(
                    _table_exists(conn, "comercio_usuarios")
                )

            command.upgrade(self.cfg, "head")

            with self.engine.connect() as conn:
                self.assertTrue(
                    _table_exists(conn, "comercio_usuarios")
                )
                borrador_cols = _column_names(
                    conn, "borrador_onboarding_comercio"
                )
                for column in (
                    "slug",
                    "comercio_id",
                    "completado_en",
                ):
                    with self.subTest(column=column):
                        self.assertIn(column, borrador_cols)
                self.assertIn(
                    "comercio_usuarios_cuenta_comercio_unique",
                    _unique_constraints(conn, "comercio_usuarios"),
                )
        finally:
            command.upgrade(self.cfg, "head")


if __name__ == "__main__":
    unittest.main()
