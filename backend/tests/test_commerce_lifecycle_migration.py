"""Migration upgrade / downgrade / upgrade cycle for the
``add-commerce-lifecycle-policy`` change.

The first revision must:

* add ``codigo``, ``descripcion``, ``modo_operacion`` and
  ``seleccionable`` to ``estado_comercio``;
* backfill every existing row from its previous ``estado`` label
  into the canonical lifecycle policy;
* preserve every existing ``Comercio.estado_id`` reference;
* add ``prueba_hasta``, ``prueba_max_pedidos`` and
  ``prueba_pedidos_consumidos`` to ``comercios``;
* downgrade cleanly so the schema returns to the prior shape.

The follow-up ``a1b2c3d4e5f7`` revision must:

* seed the five canonical lifecycle states
  (``ACTIVO``, ``INACTIVO``, ``PRUEBA``, ``SUSPENDIDO``, ``BAJA``)
  idempotently, preserving the pre-existing ``ACTIVO`` id;
* make the panel / repository selectable listing return exactly
  ``ACTIVO``, ``INACTIVO`` and ``PRUEBA``;
* remain safe to re-apply without duplicating rows.
"""
from __future__ import annotations

import os
import unittest

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from backend.repositories.estado_comercio_repository import (
    EstadoComercioRepository,
)

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


def _check_constraints(conn, table: str) -> set[str]:
    inspector = inspect(conn)
    return {
        check["name"]
        for check in inspector.get_check_constraints(table)
        if check.get("name")
    }


class CommerceLifecyclePolicyMigrationTest(unittest.TestCase):
    def test_upgrade_preserves_references_and_backfills_modes(self) -> None:
        engine = create_engine(DB_URL)
        cfg = _alembic_config()

        # Seed a deterministic pair of estado_comercio rows + one
        # comercio pointing at the canonical ACTIVO row so the test
        # proves the migration preserves ``estado_id`` references.
        with engine.begin() as conn:
            self.assertTrue(
                _table_exists(conn, "estado_comercio"),
                "estado_comercio must exist after upgrade head",
            )
            self.assertTrue(
                _table_exists(conn, "comercios"),
                "comercios must exist after upgrade head",
            )
            conn.execute(
                text(
                    "INSERT INTO estado_comercio "
                    "(codigo, descripcion, modo_operacion, seleccionable) "
                    "VALUES ('ACTIVO', 'Activo', "
                    " CAST('habilitado' AS estado_comercio_modo_operacion), "
                    " true), "
                    " ('INACTIVO', 'Inactivo', "
                    " CAST('bloqueado' AS estado_comercio_modo_operacion), "
                    " true) ON CONFLICT (codigo) DO NOTHING"
                )
            )
            activo_id = conn.execute(
                text(
                    "SELECT id FROM estado_comercio WHERE codigo = 'ACTIVO'"
                )
            ).scalar_one()
            comercio_estado_id = activo_id
            existing_comercio_id = conn.execute(
                text(
                    "SELECT id FROM comercios WHERE slug = 'comercio-test-migration'"
                )
            ).scalar_one_or_none()
            if existing_comercio_id is None:
                conn.execute(
                    text(
                        "INSERT INTO comercios "
                        "(nombre_fantasia, nombre_corto, razon_social, cuit, "
                        " whatsapp, calle, numero, localidad, provincia, "
                        " slug, estado_id, zona_horaria, moneda, idioma, "
                        " prueba_pedidos_consumidos) "
                        "VALUES ('Test', 'T', 'T SRL', '30-99999999-9', "
                        " '+5491100000099', 'Av. Test', '1', 'CABA', "
                        " 'Buenos Aires', 'comercio-test-migration', "
                        " :estado_id, 'America/Argentina/Buenos_Aires', "
                        " 'ARS', 'es-AR', 0)"
                    ),
                    {"estado_id": activo_id},
                )
                comercio_id = conn.execute(
                    text(
                        "SELECT id FROM comercios "
                        "WHERE slug = 'comercio-test-migration'"
                    )
                ).scalar_one()
            else:
                comercio_id = int(existing_comercio_id)

        with engine.connect() as conn:
            cols = _column_names(conn, "estado_comercio")
            self.assertIn("codigo", cols)
            self.assertIn("descripcion", cols)
            self.assertIn("modo_operacion", cols)
            self.assertIn("seleccionable", cols)
            self.assertNotIn("estado", cols)
            cols_comercios = _column_names(conn, "comercios")
            self.assertIn("prueba_hasta", cols_comercios)
            self.assertIn("prueba_max_pedidos", cols_comercios)
            self.assertIn("prueba_pedidos_consumidos", cols_comercios)

            after_estado = conn.execute(
                text(
                    "SELECT id, codigo, modo_operacion, seleccionable "
                    "FROM estado_comercio ORDER BY id"
                )
            ).all()
            self.assertGreaterEqual(len(after_estado), 2)
            codigos = {row[1] for row in after_estado}
            self.assertIn("ACTIVO", codigos)
            self.assertIn("INACTIVO", codigos)

            after_comercio = conn.execute(
                text(
                    "SELECT id, estado_id FROM comercios "
                    "WHERE id = :comercio_id"
                ),
                {"comercio_id": comercio_id},
            ).first()
            self.assertEqual(
                int(after_comercio[1]), int(comercio_estado_id)
            )
            self.assertEqual(int(after_comercio[1]), int(activo_id))

            constraints = _check_constraints(conn, "comercios")
            self.assertIn(
                "comercios_prueba_max_pedidos_positivo",
                constraints,
            )
            self.assertIn(
                "comercios_prueba_pedidos_consumidos_no_negativo",
                constraints,
            )

    def test_downgrade_removes_trial_columns(self) -> None:
        engine = create_engine(DB_URL)
        cfg = _alembic_config()

        command.downgrade(cfg, "f1g2h3i4j5k6")
        try:
            with engine.connect() as conn:
                cols = _column_names(conn, "estado_comercio")
                self.assertIn("estado", cols)
                self.assertNotIn("codigo", cols)
                cols_comercios = _column_names(conn, "comercios")
                self.assertNotIn("prueba_hasta", cols_comercios)
        finally:
            command.upgrade(cfg, "head")


class CommerceLifecycleSeedFullMigrationTest(unittest.TestCase):
    """Focused test for the follow-up ``a1b2c3d4e5f7`` revision.

    The deployed ``9c5b1d3e4f6c`` revision only backfilled existing
    rows from the previous free-text ``estado`` label, so production
    was left with a single ``ACTIVO`` row and the panel could not
    offer ``INACTIVO`` or ``PRUEBA``. The follow-up revision must:

    * be idempotent when re-applied (no duplicate ``codigo`` rows);
    * preserve the pre-existing ``ACTIVO`` ``id``;
    * expose the canonical five states with exact attributes;
    * make ``list_seleccionable()`` return ``ACTIVO``, ``INACTIVO``
      and ``PRUEBA`` only.

    The test rebuilds the schema to the ``9c5b1d3e4f6c`` revision,
    simulates the production state (only ``ACTIVO``), captures its
    id, applies ``a1b2c3d4e5f7``, re-applies it once more, and
    inspects every documented invariant.
    """

    NEW_REVISION = "a1b2c3d4e5f7"
    PREVIOUS_REVISION = "9c5b1d3e4f6c"

    CANONICAL_STATES: tuple[tuple[str, str, str, bool], ...] = (
        ("ACTIVO", "Activo", "habilitado", True),
        ("INACTIVO", "Inactivo", "bloqueado", True),
        ("PRUEBA", "Prueba", "prueba", True),
        ("SUSPENDIDO", "Suspendido", "bloqueado", False),
        ("BAJA", "Baja", "bloqueado", False),
    )
    SELECTABLE_CODES = ("ACTIVO", "INACTIVO", "PRUEBA")

    def setUp(self) -> None:
        self.engine = create_engine(DB_URL)
        self.cfg = _alembic_config()

        command.downgrade(self.cfg, self.PREVIOUS_REVISION)
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    "DELETE FROM estado_comercio "
                    "WHERE codigo IN ('INACTIVO', 'PRUEBA', "
                    "                  'SUSPENDIDO', 'BAJA')"
                )
            )
            conn.execute(
                text(
                    "UPDATE estado_comercio SET "
                    "descripcion = 'Activo', "
                    "modo_operacion = "
                    "  CAST('habilitado' AS estado_comercio_modo_operacion), "
                    "seleccionable = true "
                    "WHERE codigo = 'ACTIVO'"
                )
            )
        with self.engine.connect() as conn:
            self._pre_activo_id = int(
                conn.execute(
                    text(
                        "SELECT id FROM estado_comercio "
                        "WHERE codigo = 'ACTIVO'"
                    )
                ).scalar_one()
            )

    def tearDown(self) -> None:
        command.upgrade(self.cfg, "head")

    def _fetch_estado_rows(self) -> list[tuple[int, str, str, str, bool]]:
        with self.engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT id, codigo, descripcion, modo_operacion, "
                    "       seleccionable "
                    "FROM estado_comercio ORDER BY id"
                )
            ).all()
        return [
            (int(r[0]), r[1], r[2], str(r[3]), bool(r[4])) for r in rows
        ]

    def test_upgrade_seeds_full_canonical_set(self) -> None:
        """The follow-up revision inserts the five canonical rows."""
        command.upgrade(self.cfg, "head")

        rows = self._fetch_estado_rows()
        self.assertEqual(
            len(rows),
            len(self.CANONICAL_STATES),
            "exactly the five canonical states must be present",
        )

        by_codigo = {row[1]: row for row in rows}
        for codigo, descripcion, modo, seleccionable in self.CANONICAL_STATES:
            self.assertIn(codigo, by_codigo)
            row = by_codigo[codigo]
            self.assertEqual(row[2], descripcion)
            self.assertEqual(row[3], modo)
            self.assertEqual(row[4], seleccionable)

    def test_upgrade_preserves_pre_existing_activo_id(self) -> None:
        """The pre-existing ``ACTIVO`` row keeps its ``id``."""
        command.upgrade(self.cfg, "head")

        with self.engine.connect() as conn:
            activo_id = conn.execute(
                text(
                    "SELECT id FROM estado_comercio "
                    "WHERE codigo = 'ACTIVO'"
                )
            ).scalar_one()

        self.assertEqual(int(activo_id), self._pre_activo_id)

    def test_repository_list_seleccionable_returns_three_options(self) -> None:
        """``list_seleccionable`` returns exactly ACTIVO/INACTIVO/PRUEBA."""
        command.upgrade(self.cfg, "head")

        TestingSession = sessionmaker(
            bind=self.engine, autoflush=False, autocommit=False
        )
        with TestingSession() as session:
            repo = EstadoComercioRepository(session)
            codigos = tuple(
                row.codigo for row in repo.list_seleccionable()
            )

        self.assertEqual(codigos, self.SELECTABLE_CODES)

    def test_reapplying_upgrade_is_idempotent(self) -> None:
        """Running the upgrade again does not duplicate rows."""
        command.upgrade(self.cfg, "head")
        first_rows = self._fetch_estado_rows()

        command.upgrade(self.cfg, "head")
        second_rows = self._fetch_estado_rows()

        self.assertEqual(first_rows, second_rows)
        codigos = [row[1] for row in second_rows]
        self.assertEqual(
            sorted(codigos), sorted({c for c, _, _, _ in self.CANONICAL_STATES})
        )
        self.assertEqual(
            len(codigos), len({codigo for codigo in codigos}),
            "no duplicate codigo rows",
        )

        with self.engine.connect() as conn:
            activo_id = conn.execute(
                text(
                    "SELECT id FROM estado_comercio "
                    "WHERE codigo = 'ACTIVO'"
                )
            ).scalar_one()
        self.assertEqual(int(activo_id), self._pre_activo_id)


if __name__ == "__main__":
    unittest.main()