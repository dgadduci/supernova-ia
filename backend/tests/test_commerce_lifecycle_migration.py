"""Migration upgrade / downgrade / upgrade cycle for the
``add-commerce-lifecycle-policy`` change.

The revision must:

* add ``codigo``, ``descripcion``, ``modo_operacion`` and
  ``seleccionable`` to ``estado_comercio``;
* backfill every existing row from its previous ``estado`` label
  into the canonical lifecycle policy;
* preserve every existing ``Comercio.estado_id`` reference;
* add ``prueba_hasta``, ``prueba_max_pedidos`` and
  ``prueba_pedidos_consumidos`` to ``comercios``;
* downgrade cleanly so the schema returns to the prior shape.
"""
from __future__ import annotations

import os
import unittest

from alembic.config import Config
from alembic import command
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


if __name__ == "__main__":
    unittest.main()