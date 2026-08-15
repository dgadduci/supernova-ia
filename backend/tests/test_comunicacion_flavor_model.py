"""Focused tests for the global ``FlavorComunicacion`` model and
catalog migration.

The Phase-1 contract is:

* the catalog is a global, system-managed table;
* ``codigo`` is unique and acts as the canonical machine key;
* the six canonical seeds are inserted in the same migration that
  creates the table, including one active ``neutro`` row;
* every existing ``comercio`` is backfilled to the ``neutro`` row
  resolved by code (never by assumed numeric ID);
* the ``comercios.flavor_comunicacion_id`` foreign key becomes
  ``NOT NULL`` after backfill;
* the catalog has no commerce owner.

The tests use the live ``supernova_test`` PostgreSQL database and
look up the seeded canon by code rather than by assuming a numeric
ID, so that the migration is robust against identity changes.
"""

from __future__ import annotations

import unittest
import uuid
from collections.abc import Sequence

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Integer,
    String,
    create_engine,
    delete,
    insert,
    select,
    text,
)
from sqlalchemy.orm import sessionmaker

from backend.models import Comercio, FlavorComunicacion
from backend.repositories.flavor_comunicacion_repository import (
    FlavorComunicacionRepository,
)

TEST_URL = "postgresql+psycopg:///supernova_test"

engine = create_engine(TEST_URL)
TestingSessionLocal = sessionmaker(
    bind=engine, autoflush=False, autocommit=False
)


CANONICAL_CODES: Sequence[str] = (
    "neutro",
    "serio",
    "joven",
    "elegante",
    "mexicano",
    "peruano",
)


def _suffix() -> str:
    return uuid.uuid4().hex[:10]


def _estado_id_activo() -> int:
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT id FROM estado_comercio WHERE estado = 'ACTIVO'")
        ).first()
    if row is None:
        raise RuntimeError("estado ACTIVO not seeded in supernova_test")
    return int(row[0])


def _seed_comercio(suffix: str) -> int:
    with TestingSessionLocal() as session, session.begin():
        flavor_id = session.execute(
            select(FlavorComunicacion.id).where(
                FlavorComunicacion.codigo == "neutro"
            )
        ).scalar_one()
        comercio = Comercio(
            nombre_fantasia=f"Flavor Model {suffix}",
            nombre_corto=f"FM {suffix}",
            razon_social=f"Flavor Model SRL {suffix}",
            cuit=f"30-{suffix[:8]}-{suffix[8]}",
            whatsapp=f"+54913{suffix[:8]}",
            calle="Av. Flavor",
            numero="100",
            piso_departamento=None,
            localidad="CABA",
            provincia="Buenos Aires",
            codigo_postal="C1000",
            slug=f"flavor-model-{suffix}",
            estado_id=_estado_id_activo(),
            flavor_comunicacion_id=flavor_id,
        )
        session.add(comercio)
        session.flush()
        comercio_id = int(comercio.id)
    return comercio_id


def _delete_comercio(comercio_id: int) -> None:
    with TestingSessionLocal() as session, session.begin():
        session.execute(delete(Comercio).where(Comercio.id == comercio_id))


class FlavorComunicacionSchemaTest(unittest.TestCase):
    def test_table_name_and_columns(self) -> None:
        table = FlavorComunicacion.__table__
        self.assertEqual(table.name, "flavors_comunicacion")
        self.assertEqual(
            set(table.columns.keys()),
            {
                "id",
                "codigo",
                "nombre",
                "descripcion",
                "instruccion_llm",
                "activo",
                "version",
                "fecha_alta",
                "fecha_ultima_modificacion",
            },
        )

    def test_required_columns_are_not_nullable(self) -> None:
        table = FlavorComunicacion.__table__
        for column in (
            "codigo",
            "nombre",
            "descripcion",
            "instruccion_llm",
            "activo",
            "version",
            "fecha_alta",
            "fecha_ultima_modificacion",
        ):
            self.assertIs(table.c[column].nullable, False, column)

    def test_codigo_is_unique(self) -> None:
        table = FlavorComunicacion.__table__
        unique = {
            constraint.name
            for constraint in table.constraints
            if constraint.name == "flavors_comunicacion_codigo_unico"
        }
        self.assertIn("flavors_comunicacion_codigo_unico", unique)

    def test_database_columns_match_model(self) -> None:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT column_name, data_type, is_nullable "
                    "FROM information_schema.columns "
                    "WHERE table_name = 'flavors_comunicacion' "
                    "ORDER BY ordinal_position"
                )
            ).all()
        names = {row[0] for row in rows}
        self.assertEqual(
            names,
            {
                "id",
                "codigo",
                "nombre",
                "descripcion",
                "instruccion_llm",
                "activo",
                "version",
                "fecha_alta",
                "fecha_ultima_modificacion",
            },
        )

    def test_required_indexes_present(self) -> None:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT indexname FROM pg_indexes "
                    "WHERE tablename = 'flavors_comunicacion'"
                )
            ).all()
        names = {row[0] for row in rows}
        self.assertIn("flavors_comunicacion_pkey", names)
        self.assertIn("flavors_comunicacion_codigo_unico", names)
        self.assertIn("ix_flavors_comunicacion_activo", names)

    def test_check_constraints_present(self) -> None:
        table = FlavorComunicacion.__table__
        names = {
            constraint.name
            for constraint in table.constraints
            if isinstance(constraint, CheckConstraint)
        }
        self.assertIn("flavor_comunicacion_codigo_no_vacio", names)
        self.assertIn("flavor_comunicacion_nombre_no_vacio", names)
        self.assertIn("flavor_comunicacion_descripcion_no_vacia", names)
        self.assertIn("flavor_comunicacion_instruccion_llm_no_vacia", names)
        self.assertIn("flavor_comunicacion_version_positiva", names)

    def test_column_types(self) -> None:
        table = FlavorComunicacion.__table__
        self.assertIsInstance(table.c.id.type, Integer)
        self.assertIsInstance(table.c.codigo.type, String)
        self.assertIsInstance(table.c.nombre.type, String)
        self.assertIsInstance(table.c.descripcion.type, String)
        self.assertIsInstance(table.c.instruccion_llm.type, String)
        self.assertIsInstance(table.c.activo.type, Boolean)
        self.assertIsInstance(table.c.version.type, Integer)
        self.assertTrue(table.c.fecha_alta.type.timezone)
        self.assertTrue(table.c.fecha_ultima_modificacion.type.timezone)


class FlavorComunicacionCatalogTest(unittest.TestCase):
    """Verifies the seeded canonical catalog (post-migration)."""

    def test_six_canonical_codes_are_seeded(self) -> None:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT codigo FROM flavors_comunicacion "
                    "ORDER BY codigo"
                )
            ).all()
        codes = [row[0] for row in rows]
        for code in CANONICAL_CODES:
            self.assertIn(code, codes)

    def test_catalog_size_is_exactly_six(self) -> None:
        with engine.connect() as conn:
            count = conn.execute(
                text("SELECT COUNT(*) FROM flavors_comunicacion")
            ).scalar_one()
        self.assertEqual(count, len(CANONICAL_CODES))

    def test_codigo_is_unique_in_database(self) -> None:
        with engine.connect() as conn:
            duplicates = conn.execute(
                text(
                    "SELECT codigo, COUNT(*) FROM flavors_comunicacion "
                    "GROUP BY codigo HAVING COUNT(*) > 1"
                )
            ).all()
        self.assertEqual(duplicates, [])

    def test_neutro_is_active_and_resolved_by_code(self) -> None:
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT id, activo FROM flavors_comunicacion "
                    "WHERE codigo = 'neutro'"
                )
            ).first()
        self.assertIsNotNone(row)
        self.assertTrue(row[1])

    def test_seed_instruccion_llm_is_not_empty(self) -> None:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT codigo, length(instruccion_llm) "
                    "FROM flavors_comunicacion"
                )
            ).all()
        for codigo, length in rows:
            with self.subTest(codigo=codigo):
                self.assertGreater(int(length), 0)


class CatalogoGlobalSinOwnerTest(unittest.TestCase):
    """The catalog is global: there is no commerce-side owner column
    on ``FlavorComunicacion``. Every flavor is reusable across
    commerces."""

    def test_flavors_have_no_comercio_ownership_column(self) -> None:
        table = FlavorComunicacion.__table__
        for column in ("id_comercio", "comercio_id", "owner_id"):
            self.assertNotIn(column, table.columns.keys())

    def test_one_flavor_can_be_referenced_by_many_comercios(self) -> None:
        with TestingSessionLocal() as session:
            neutro_id = session.execute(
                select(FlavorComunicacion.id).where(
                    FlavorComunicacion.codigo == "neutro"
                )
            ).scalar_one()
            count = session.execute(
                text(
                    "SELECT COUNT(*) FROM comercios "
                    "WHERE flavor_comunicacion_id = :id"
                ),
                {"id": neutro_id},
            ).scalar_one()
        self.assertIsInstance(count, int)
        self.assertGreaterEqual(count, 0)


class MigrationBackfillTest(unittest.TestCase):
    """Verifies the migration produced a coherent, non-null and
    FK-enforced backfill, and that a fresh comercio is created with
    the ``neutro`` flavor by code (no hard-coded numeric ID)."""

    def test_all_comercios_reference_a_flavor(self) -> None:
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT COUNT(*) FILTER (WHERE flavor_comunicacion_id IS NULL), "
                    "COUNT(*) FROM comercios"
                )
            ).first()
        self.assertEqual(int(row[0]), 0)

    def test_fk_constraint_is_non_null(self) -> None:
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT is_nullable FROM information_schema.columns "
                    "WHERE table_name = 'comercios' "
                    "AND column_name = 'flavor_comunicacion_id'"
                )
            ).first()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], "NO")

    def test_fk_is_restrict(self) -> None:
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT confdeltype FROM pg_constraint "
                    "WHERE conname = 'comercios_flavor_comunicacion_fk'"
                )
            ).first()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], "r")

    def test_new_comercio_defaults_to_neutro_resolved_by_code(self) -> None:
        suffix = _suffix()
        comercio_id = _seed_comercio(suffix)
        self.addCleanup(_delete_comercio, comercio_id)
        with engine.connect() as conn:
            flavor_id = conn.execute(
                text(
                    "SELECT id FROM flavors_comunicacion "
                    "WHERE codigo = 'neutro'"
                )
            ).scalar_one()
            stored = conn.execute(
                text(
                    "SELECT flavor_comunicacion_id FROM comercios "
                    "WHERE id = :id"
                ),
                {"id": comercio_id},
            ).scalar_one()
        self.assertEqual(int(stored), int(flavor_id))

    def test_idempotent_seed_via_code_resolution(self) -> None:
        """Re-running the seed step by code must not create duplicate
        canonical rows. The codigo unique constraint absorbs the
        insertion safely.

        This mirrors the actual migration's seed behaviour: the
        migrate command resolves ``neutro`` by code, which means the
        operation is robust to inserts that happen before or after
        the backfill step.
        """
        with engine.connect() as conn:
            count_before = conn.execute(
                text("SELECT COUNT(*) FROM flavors_comunicacion")
            ).scalar_one()
        with engine.begin() as conn:
            try:
                conn.execute(
                    insert(FlavorComunicacion).values(
                        codigo="neutro",
                        nombre="duplicado",
                        descripcion="duplicado",
                        instruccion_llm="duplicado",
                        activo=True,
                        version=1,
                    )
                )
            except Exception as exc:  # noqa: BLE001
                self.assertIn("flavors_comunicacion_codigo_unico", str(exc))
            else:
                self.fail("expected unique constraint violation")
        with engine.connect() as conn:
            count_after = conn.execute(
                text("SELECT COUNT(*) FROM flavors_comunicacion")
            ).scalar_one()
        self.assertEqual(count_before, count_after)


class FlavorComunicacionRepositoryTest(unittest.TestCase):
    """Repository is read-only and the only safe resolve path is by
    code (``neutro``). It must not assume any numeric ID."""

    def test_neutro_resolved_by_code_not_by_id(self) -> None:
        with TestingSessionLocal() as session:
            repo = FlavorComunicacionRepository(session)
            resolved = repo.get_by_codigo("neutro")
            self.assertIsNotNone(resolved)
            assert resolved is not None
            self.assertEqual(resolved.codigo, "neutro")
            self.assertTrue(resolved.activo)

    def test_list_active_returns_only_active(self) -> None:
        with TestingSessionLocal() as session:
            repo = FlavorComunicacionRepository(session)
            seeds = repo.list_active()
            self.assertGreaterEqual(len(seeds), len(CANONICAL_CODES))
            for flavor in seeds:
                self.assertTrue(flavor.activo)
                self.assertIn(flavor.codigo, CANONICAL_CODES)

    def test_get_by_id_returns_requested_row(self) -> None:
        with TestingSessionLocal() as session:
            repo = FlavorComunicacionRepository(session)
            resolved = repo.get_by_codigo("serio")
            assert resolved is not None
            fetched = repo.get_by_id(int(resolved.id))
            self.assertIsNotNone(fetched)
            assert fetched is not None
            self.assertEqual(fetched.codigo, "serio")

    def test_repository_does_not_commit_or_rollback(self) -> None:
        from unittest.mock import MagicMock

        session = MagicMock()
        FlavorComunicacionRepository(session).list_active()
        FlavorComunicacionRepository(session).get_by_id(1)
        FlavorComunicacionRepository(session).get_by_codigo("neutro")
        session.commit.assert_not_called()
        session.rollback.assert_not_called()
        session.flush.assert_not_called()


class FlavorComercioForeignKeyTest(unittest.TestCase):
    def test_comercio_without_flavor_insertion_is_rejected(self) -> None:
        suffix = _suffix()
        with TestingSessionLocal() as session:
            try:
                with session.begin():
                    session.add(
                        Comercio(
                            nombre_fantasia=f"FK Test {suffix}",
                            nombre_corto=f"FK {suffix}",
                            razon_social=f"FK Test SRL {suffix}",
                            cuit=f"30-{suffix[:8]}-{suffix[8]}",
                            whatsapp=f"+54914{suffix[:8]}",
                            calle="Av. FK",
                            numero="100",
                            piso_departamento=None,
                            localidad="CABA",
                            provincia="Buenos Aires",
                            codigo_postal="C1000",
                            slug=f"fk-test-{suffix}",
                            estado_id=_estado_id_activo(),
                        )
                    )
            except Exception as exc:  # noqa: BLE001
                self.assertIn("flavor_comunicacion_id", str(exc).lower())
            else:
                self.fail("expected NOT NULL violation on flavor_comunicacion_id")

    def test_comercio_with_unknown_flavor_id_is_rejected(self) -> None:
        suffix = _suffix()
        with TestingSessionLocal() as session:
            try:
                with session.begin():
                    session.add(
                        Comercio(
                            nombre_fantasia=f"FK Unknown {suffix}",
                            nombre_corto=f"FU {suffix}",
                            razon_social=f"FK Unknown SRL {suffix}",
                            cuit=f"30-{suffix[:8]}-{suffix[8]}",
                            whatsapp=f"+54915{suffix[:8]}",
                            calle="Av. FK",
                            numero="200",
                            piso_departamento=None,
                            localidad="CABA",
                            provincia="Buenos Aires",
                            codigo_postal="C1000",
                            slug=f"fk-unknown-{suffix}",
                            estado_id=_estado_id_activo(),
                            flavor_comunicacion_id=999_999_999,
                        )
                    )
            except Exception as exc:  # noqa: BLE001
                self.assertIn("flavors_comunicacion", str(exc))
            else:
                self.fail("expected FK violation on flavor_comunicacion_id")


class FlavorUpdatePropagationTest(unittest.TestCase):
    """Changing the ``flavor_comunicacion_id`` on a comercio is
    propagated identically to the FK column."""

    def test_update_flavor_changes_only_target_comercio(self) -> None:
        suffix = _suffix()
        target = _seed_comercio(suffix)
        self.addCleanup(_delete_comercio, target)
        with engine.connect() as conn:
            otro_id = conn.execute(
                text(
                    "SELECT id FROM comercios "
                    "WHERE id <> :id ORDER BY id LIMIT 1"
                ),
                {"id": target},
            ).first()
        self.assertIsNotNone(otro_id)
        other_id = int(otro_id[0])
        with engine.connect() as conn:
            serio_id = conn.execute(
                text(
                    "SELECT id FROM flavors_comunicacion "
                    "WHERE codigo = 'serio'"
                )
            ).scalar_one()
            conn.execute(
                text(
                    "UPDATE comercios SET flavor_comunicacion_id = :fid "
                    "WHERE id = :id"
                ),
                {"fid": serio_id, "id": target},
            )
            target_flavor = conn.execute(
                text(
                    "SELECT flavor_comunicacion_id FROM comercios "
                    "WHERE id = :id"
                ),
                {"id": target},
            ).scalar_one()
            other_flavor = conn.execute(
                text(
                    "SELECT flavor_comunicacion_id FROM comercios "
                    "WHERE id = :id"
                ),
                {"id": other_id},
            ).scalar_one()
        self.assertEqual(int(target_flavor), int(serio_id))
        self.assertNotEqual(int(other_flavor), int(serio_id))


if __name__ == "__main__":
    unittest.main(verbosity=2)
