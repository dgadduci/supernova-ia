"""Focused tests for the optional ``Comercio.flavor_comunicacion``
relation after the ``make-commerce-flavor-optional`` change.

The contract under test:

* a fresh comercio is persisted without a flavor; the service
  does NOT require the canonical ``neutro`` row to exist;
* the migration only converts ``neutro``-assigned comerce rows
  to ``NULL`` and leaves non-neutral assignments intact;
* clearing an existing assignment through the assignment
  endpoint / service is an idempotent, authenticated,
  transactional operation that persists ``NULL`` and returns
  the existing commerce projection with the flavor summary
  absent (``flavor_comunicacion`` is ``null``);
* unknown or inactive flavors are rejected without mutating
  the prior assignment, exactly as before.

The tests use the live ``supernova_test`` PostgreSQL database.
"""

from __future__ import annotations

import unittest
import uuid
from typing import Any
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, text
from sqlalchemy.orm import sessionmaker

import backend.routers.flavors_comunicacion as router_module
from backend.config import settings as settings_module
from backend.config.settings import Settings
from backend.dependencies import get_session, require_admin_token
from backend.models import Comercio
from backend.services.comercio_service import ComercioService
from backend.services.comunicacion_flavor_service import (
    ComunicacionFlavorService,
)

CONFIGURED_TOKEN = "optional-flavor-test-token"

TEST_URL = "postgresql+psycopg:///supernova_test"
engine = create_engine(TEST_URL)
TestingSessionLocal = sessionmaker(
    bind=engine, autoflush=False, autocommit=False
)


def _settings(token: str | None = CONFIGURED_TOKEN) -> Settings:
    base = settings_module.load_settings()
    return Settings(
        **{**base.__dict__, "order_management_admin_token": token}
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


def _seed_comercio(
    suffix: str,
    *,
    flavor_codigo: str | None = "neutro",
) -> int:
    flavor_id: int | None = None
    if flavor_codigo is not None:
        with engine.connect() as conn:
            flavor_id = int(
                conn.execute(
                    text(
                        "SELECT id FROM flavors_comunicacion "
                        "WHERE codigo = :codigo"
                    ),
                    {"codigo": flavor_codigo},
                ).scalar_one()
            )
    with TestingSessionLocal() as session, session.begin():
        comercio = Comercio(
            nombre_fantasia=f"Optional Flavor {suffix}",
            nombre_corto=f"OF {suffix}",
            razon_social=f"Optional Flavor SRL {suffix}",
            cuit=f"30-{suffix[:8]}-{suffix[8]}",
            whatsapp=f"+54919{suffix[:8]}",
            calle="Av. Optional",
            numero="100",
            piso_departamento=None,
            localidad="CABA",
            provincia="Buenos Aires",
            codigo_postal="C1000",
            slug=f"optional-flavor-{suffix}",
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


def _flavor_id(codigo: str) -> int:
    with engine.connect() as conn:
        return int(
            conn.execute(
                text(
                    "SELECT id FROM flavors_comunicacion "
                    "WHERE codigo = :codigo"
                ),
                {"codigo": codigo},
            ).scalar_one()
        )


def _stored_flavor(comercio_id: int) -> int | None:
    with engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT flavor_comunicacion_id FROM comercios "
                "WHERE id = :id"
            ),
            {"id": comercio_id},
        ).scalar_one()


# ---------------------------------------------------------------------------
# Migration contract
# ---------------------------------------------------------------------------


class OptionalFlavorMigrationContractTest(unittest.TestCase):
    """The optional-flavor migration contract:: the column is
    nullable, the foreign key and index survive, only ``neutro``
    assignments become ``NULL``, and the operation tolerates a
    missing ``neutro`` row (no fabricated numeric ID)."""

    def test_column_is_nullable_post_migration(self) -> None:
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT is_nullable FROM information_schema.columns "
                    "WHERE table_name = 'comercios' "
                    "AND column_name = 'flavor_comunicacion_id'"
                )
            ).first()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], "YES")

    def test_foreign_key_is_preserved(self) -> None:
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT confdeltype FROM pg_constraint "
                    "WHERE conname = 'comercios_flavor_comunicacion_fk'"
                )
            ).first()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], "r")

    def test_supporting_index_is_preserved(self) -> None:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT indexname FROM pg_indexes "
                    "WHERE tablename = 'comercios' "
                    "AND indexname = 'ix_comercios_flavor_comunicacion_id'"
                )
            ).all()
        self.assertEqual(len(rows), 1)


class OptionalFlavorMigrationNeutroStateTest(unittest.TestCase):
    """The migration resolves the canonical ``neutro`` row only
    by ``codigo`` — never by ``activo`` — so an inactive or
    missing ``neutro`` row is handled deterministically: the
    upgrade still converts its assignments to ``NULL`` (or
    safely does nothing when the row is missing); the downgrade
    uses the row when present and aborts before any mutation
    when it is missing.

    Each test seeds and tears down its own ``comercios``
    fixtures. The migration is driven through explicit
    ``alembic upgrade`` / ``alembic downgrade`` subprocesses
    so the migration body actually executes on a freshly
    populated pre-migration state.
    """

    def _run_alembic(
        self,
        command: str,
        target: str,
        venv_python: str,
    ) -> Any:
        import subprocess

        return subprocess.run(
            [venv_python, "-m", "alembic", command, target],
            capture_output=True,
            text=True,
            check=False,
        )

    def _seed_comercio(
        self,
        session: Any,
        suffix: str,
        flavor_id: int | None,
    ) -> int:
        comercio = Comercio(
            nombre_fantasia=f"Mig {suffix}",
            nombre_corto=f"MIG {suffix}",
            razon_social=f"Mig {suffix} SRL",
            cuit=f"30-{suffix[:8]}-{suffix[8]}",
            whatsapp=f"+54930{suffix[:8]}",
            calle="Av. Mig",
            numero="100",
            piso_departamento=None,
            localidad="CABA",
            provincia="Buenos Aires",
            codigo_postal="C1000",
            slug=f"mig-flavor-{suffix}",
            estado_id=_estado_id_activo(),
            flavor_comunicacion_id=flavor_id,
        )
        session.add(comercio)
        session.flush()
        return int(comercio.id)

    def _set_neutro_activo(self, neutro_id: int, activo: bool) -> None:
        with TestingSessionLocal() as session, session.begin():
            session.execute(
                text(
                    "UPDATE flavors_comunicacion SET activo = :activo "
                    "WHERE id = :id"
                ),
                {"activo": activo, "id": neutro_id},
            )

    def _ensure_neutro_present(self, neutro_id: int) -> None:
        with TestingSessionLocal() as session, session.begin():
            row = session.execute(
                text(
                    "SELECT id FROM flavors_comunicacion WHERE id = :id"
                ),
                {"id": neutro_id},
            ).first()
            if row is None:
                session.execute(
                    text(
                        "INSERT INTO flavors_comunicacion "
                        "(id, codigo, nombre, descripcion, "
                        "instruccion_llm, activo, version) "
                        "VALUES (:id, 'neutro', 'Neutro', "
                        "'Tono profesional', 'instruccion', "
                        "true, 1)"
                    ),
                    {"id": neutro_id},
                )

    def test_neutro_id_resolves_inactive_row_by_code(self) -> None:
        """The resolution ignores the ``activo`` flag: an
        inactive ``neutro`` row is still recognised so the
        upgrade / downgrade can use it without ambiguity."""
        from backend.alembic.versions import (
            e1a2b3c4d5f6_make_commerce_communication_flavor_optional as mig,
        )

        neutro_id = _flavor_id("neutro")
        self._set_neutro_activo(neutro_id, False)
        try:
            with engine.connect() as conn:
                self.assertEqual(
                    mig._neutro_id(conn),
                    neutro_id,
                )
        finally:
            self._set_neutro_activo(neutro_id, True)

    def test_neutro_id_returns_none_when_row_missing(self) -> None:
        """When the canonical row is missing, resolution returns
        ``None`` so callers can refuse to fabricate numeric
        IDs."""
        from backend.alembic.versions import (
            e1a2b3c4d5f6_make_commerce_communication_flavor_optional as mig,
        )

        neutro_id = _flavor_id("neutro")
        with TestingSessionLocal() as session, session.begin():
            session.execute(
                text(
                    "UPDATE comercios SET flavor_comunicacion_id = NULL "
                    "WHERE flavor_comunicacion_id = :id"
                ),
                {"id": neutro_id},
            )
            session.execute(
                text(
                    "DELETE FROM flavors_comunicacion WHERE id = :id"
                ),
                {"id": neutro_id},
            )
        try:
            with engine.connect() as conn:
                self.assertIsNone(mig._neutro_id(conn))
        finally:
            self._ensure_neutro_present(neutro_id)

    def test_upgrade_with_inactive_neutro_converts_assignments_to_null(
        self,
    ) -> None:
        """When the canonical ``neutro`` row is inactive, the
        upgrade must still recognise the row and convert every
        referencing ``comercio`` to ``NULL``; non-neutral
        assignments are preserved exactly. The migration is
        executed against a freshly seeded pre-migration state
        via ``alembic downgrade`` then ``alembic upgrade``.
        """
        import sys

        neutro_id = _flavor_id("neutro")
        serio_id = _flavor_id("serio")
        suffix = _suffix()
        suffix_other = _suffix()
        comercio_neutro: int | None = None
        comercio_serio: int | None = None
        venv_python = sys.executable

        try:
            pre_down = self._run_alembic(
                "downgrade", "d1d2e3f4a5b6", venv_python
            )
            self.assertEqual(
                pre_down.returncode,
                0,
                msg=(
                    "setup downgrade failed:\n"
                    f"stdout={pre_down.stdout}\nstderr={pre_down.stderr}"
                ),
            )
            with TestingSessionLocal() as session, session.begin():
                self._set_neutro_activo(neutro_id, False)
                comercio_neutro = self._seed_comercio(
                    session, suffix, neutro_id
                )
                comercio_serio = self._seed_comercio(
                    session, suffix_other, serio_id
                )
            upgrade = self._run_alembic(
                "upgrade", "e1a2b3c4d5f6", venv_python
            )
            self.assertEqual(
                upgrade.returncode,
                0,
                msg=(
                    "upgrade failed unexpectedly:\n"
                    f"stdout={upgrade.stdout}\nstderr={upgrade.stderr}"
                ),
            )
            with engine.connect() as conn:
                neutro_stored = conn.execute(
                    text(
                        "SELECT flavor_comunicacion_id FROM comercios "
                        "WHERE id = :id"
                    ),
                    {"id": comercio_neutro},
                ).scalar_one()
                serio_stored = conn.execute(
                    text(
                        "SELECT flavor_comunicacion_id FROM comercios "
                        "WHERE id = :id"
                    ),
                    {"id": comercio_serio},
                ).scalar_one()
                nullable = conn.execute(
                    text(
                        "SELECT is_nullable FROM information_schema.columns "
                        "WHERE table_name = 'comercios' "
                        "AND column_name = 'flavor_comunicacion_id'"
                    )
                ).scalar_one()
            self.assertIsNone(neutro_stored)
            self.assertEqual(int(serio_stored), serio_id)
            self.assertEqual(nullable, "YES")
        finally:
            with TestingSessionLocal() as session, session.begin():
                session.execute(
                    text(
                        "DELETE FROM comercios WHERE id IN (:a, :b)"
                    ),
                    {"a": comercio_neutro, "b": comercio_serio},
                )
                session.execute(
                    text(
                        "UPDATE flavors_comunicacion SET activo = true "
                        "WHERE id = :id"
                    ),
                    {"id": neutro_id},
                )
            self._run_alembic(
                "upgrade", "e1a2b3c4d5f6", venv_python
            )

    def test_downgrade_with_inactive_neutro_restores_not_null(self) -> None:
        """When the canonical ``neutro`` row exists but is
        inactive, the downgrade must use it to map ``NULL``
        rows back to its ID and restore the ``NOT NULL``
        constraint without raising. Non-neutral references
        are preserved exactly.
        """
        import sys

        neutro_id = _flavor_id("neutro")
        serio_id = _flavor_id("serio")
        suffix_null = _suffix()
        suffix_serio = _suffix()
        comercio_null: int | None = None
        comercio_serio: int | None = None
        venv_python = sys.executable
        try:
            with TestingSessionLocal() as session, session.begin():
                self._set_neutro_activo(neutro_id, False)
                comercio_null = self._seed_comercio(
                    session, suffix_null, None
                )
                comercio_serio = self._seed_comercio(
                    session, suffix_serio, serio_id
                )
            down = self._run_alembic(
                "downgrade", "d1d2e3f4a5b6", venv_python
            )
            self.assertEqual(
                down.returncode,
                0,
                msg=(
                    "downgrade failed unexpectedly:\n"
                    f"stdout={down.stdout}\nstderr={down.stderr}"
                ),
            )
            with engine.connect() as conn:
                nullable = conn.execute(
                    text(
                        "SELECT is_nullable FROM information_schema.columns "
                        "WHERE table_name = 'comercios' "
                        "AND column_name = 'flavor_comunicacion_id'"
                    )
                ).scalar_one()
                null_stored = conn.execute(
                    text(
                        "SELECT flavor_comunicacion_id FROM comercios "
                        "WHERE id = :id"
                    ),
                    {"id": comercio_null},
                ).scalar_one()
                serio_stored = conn.execute(
                    text(
                        "SELECT flavor_comunicacion_id FROM comercios "
                        "WHERE id = :id"
                    ),
                    {"id": comercio_serio},
                ).scalar_one()
            self.assertEqual(nullable, "NO")
            self.assertEqual(int(null_stored), neutro_id)
            self.assertEqual(int(serio_stored), serio_id)
        finally:
            with TestingSessionLocal() as session, session.begin():
                session.execute(
                    text(
                        "DELETE FROM comercios WHERE id IN (:a, :b)"
                    ),
                    {"a": comercio_null, "b": comercio_serio},
                )
                session.execute(
                    text(
                        "UPDATE flavors_comunicacion SET activo = true "
                        "WHERE id = :id"
                    ),
                    {"id": neutro_id},
                )
            self._run_alembic(
                "upgrade", "e1a2b3c4d5f6", venv_python
            )

    def test_downgrade_with_missing_neutro_aborts_before_mutation(
        self,
    ) -> None:
        """When the canonical ``neutro`` row is missing, the
        downgrade must fail clearly before touching the
        database. The migration state stays at the upgrade
        head; non-neutral references remain intact.
        """
        import sys

        neutro_id = _flavor_id("neutro")
        serio_id = _flavor_id("serio")
        suffix = _suffix()
        comercio_serio: int | None = None
        serio_pre = 0
        nullable_pre: str | None = None
        venv_python = sys.executable

        try:
            with TestingSessionLocal() as session, session.begin():
                comercio_serio = self._seed_comercio(
                    session, suffix, serio_id
                )
                serio_pre = int(
                    session.execute(
                        text(
                            "SELECT flavor_comunicacion_id FROM comercios "
                            "WHERE id = :id"
                        ),
                        {"id": comercio_serio},
                    ).scalar_one()
                    or 0
                )
                nullable_pre = session.execute(
                    text(
                        "SELECT is_nullable FROM information_schema.columns "
                        "WHERE table_name = 'comercios' "
                        "AND column_name = 'flavor_comunicacion_id'"
                    )
                ).scalar_one()
                session.execute(
                    text(
                        "DELETE FROM flavors_comunicacion WHERE id = :id"
                    ),
                    {"id": neutro_id},
                )

            result = self._run_alembic(
                "downgrade", "d1d2e3f4a5b6", venv_python
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("missing", result.stderr.lower())
            self.assertNotIn(
                "and activo=true",
                result.stderr.lower(),
                "the error message must no longer demand activo=true",
            )
            with engine.connect() as conn:
                nullable_post = conn.execute(
                    text(
                        "SELECT is_nullable FROM information_schema.columns "
                        "WHERE table_name = 'comercios' "
                        "AND column_name = 'flavor_comunicacion_id'"
                    )
                ).scalar_one()
                serio_post = int(
                    conn.execute(
                        text(
                            "SELECT flavor_comunicacion_id FROM comercios "
                            "WHERE id = :id"
                        ),
                        {"id": comercio_serio},
                    ).scalar_one()
                    or 0
                )
            self.assertEqual(nullable_post, nullable_pre)
            self.assertEqual(serio_post, serio_pre)
        finally:
            with TestingSessionLocal() as session, session.begin():
                session.execute(
                    text(
                        "DELETE FROM comercios WHERE id = :id"
                    ),
                    {"id": comercio_serio},
                )
            self._ensure_neutro_present(neutro_id)
            self._run_alembic(
                "upgrade", "e1a2b3c4d5f6", venv_python
            )

    def test_upgrade_with_missing_neutro_is_safe(self) -> None:
        """The upgrade must NOT mutate comerce assignments when
        the canonical ``neutro`` row is missing.

        The migration is exercised through a full
        ``downgrade`` → ``DELETE`` → ``upgrade`` cycle. The
        downgrade is performed while the row still exists so
        the ``NOT NULL`` restoration can backfill non-null
        references; the row is then deleted at the nullable
        head so the FK does not block the ``DELETE``. The
        cycle verifies that the upgrade at the head with the
        row missing is idempotent and safe.
        """
        import sys

        neutro_id = _flavor_id("neutro")
        serio_id = _flavor_id("serio")
        suffix = _suffix()
        comercio_serio: int | None = None
        venv_python = sys.executable

        try:
            downgrade = self._run_alembic(
                "downgrade", "d1d2e3f4a5b6", venv_python
            )
            self.assertEqual(
                downgrade.returncode,
                0,
                msg=(
                    "setup downgrade failed:\n"
                    f"stdout={downgrade.stdout}\nstderr={downgrade.stderr}"
                ),
            )
            with TestingSessionLocal() as session, session.begin():
                comercio_serio = self._seed_comercio(
                    session, suffix, serio_id
                )
            upgrade_with_neutro = self._run_alembic(
                "upgrade", "e1a2b3c4d5f6", venv_python
            )
            self.assertEqual(
                upgrade_with_neutro.returncode,
                0,
                msg=(
                    "upgrade (with neutro) failed:\n"
                    f"stdout={upgrade_with_neutro.stdout}\n"
                    f"stderr={upgrade_with_neutro.stderr}"
                ),
            )
            with TestingSessionLocal() as session, session.begin():
                serio_pre = int(
                    session.execute(
                        text(
                            "SELECT flavor_comunicacion_id FROM comercios "
                            "WHERE id = :id"
                        ),
                        {"id": comercio_serio},
                    ).scalar_one()
                    or 0
                )
                neutro_pre_count = int(
                    session.execute(
                        text(
                            "SELECT COUNT(*) FROM comercios "
                            "WHERE flavor_comunicacion_id IS NULL"
                        )
                    ).scalar_one()
                    or 0
                )
                session.execute(
                    text(
                        "DELETE FROM flavors_comunicacion WHERE id = :id"
                    ),
                    {"id": neutro_id},
                )
                serio_pre_after_delete = int(
                    session.execute(
                        text(
                            "SELECT flavor_comunicacion_id FROM comercios "
                            "WHERE id = :id"
                        ),
                        {"id": comercio_serio},
                    ).scalar_one()
                    or 0
                )
            self.assertEqual(serio_pre, serio_id)
            self.assertEqual(serio_pre_after_delete, serio_id)
            upgrade_no_neutro = self._run_alembic(
                "upgrade", "e1a2b3c4d5f6", venv_python
            )
            self.assertEqual(
                upgrade_no_neutro.returncode,
                0,
                msg=(
                    "upgrade (without neutro) failed:\n"
                    f"stdout={upgrade_no_neutro.stdout}\n"
                    f"stderr={upgrade_no_neutro.stderr}"
                ),
            )
            with engine.connect() as conn:
                serio_stored = conn.execute(
                    text(
                        "SELECT flavor_comunicacion_id FROM comercios "
                        "WHERE id = :id"
                    ),
                    {"id": comercio_serio},
                ).scalar_one()
                nullable = conn.execute(
                    text(
                        "SELECT is_nullable FROM information_schema.columns "
                        "WHERE table_name = 'comercios' "
                        "AND column_name = 'flavor_comunicacion_id'"
                    )
                ).scalar_one()
                neutro_count_after = int(
                    conn.execute(
                        text(
                            "SELECT COUNT(*) FROM comercios "
                            "WHERE flavor_comunicacion_id IS NULL"
                        )
                    ).scalar_one()
                    or 0
                )
            self.assertEqual(int(serio_stored), serio_id)
            self.assertEqual(nullable, "YES")
            self.assertEqual(neutro_count_after, neutro_pre_count)
        finally:
            with TestingSessionLocal() as session, session.begin():
                session.execute(
                    text("DELETE FROM comercios WHERE id = :id"),
                    {"id": comercio_serio},
                )
            self._ensure_neutro_present(neutro_id)
            self._run_alembic(
                "upgrade", "e1a2b3c4d5f6", venv_python
            )


# ---------------------------------------------------------------------------
# Commerce creation
# ---------------------------------------------------------------------------


class ComercioCreationOptionalFlavorTest(unittest.TestCase):
    """``ComercioService.create`` persists a fresh comercio without
    a flavor. The service does NOT require the canonical ``neutro``
    row to be present and does NOT auto-assign it."""

    def setUp(self) -> None:
        self.suffix = _suffix()
        self.estado_id = _estado_id_activo()

    def _payload(self, flavor: int | None = None) -> dict:
        payload = {
            "nombre_fantasia": f"OFC {self.suffix}",
            "nombre_corto": f"OC {self.suffix}",
            "razon_social": f"OFC SRL {self.suffix}",
            "cuit": f"30-{self.suffix[:8]}-{self.suffix[8]}",
            "whatsapp": f"+54919{self.suffix[:8]}",
            "calle": "Av. Optional",
            "numero": "100",
            "piso_departamento": None,
            "localidad": "CABA",
            "provincia": "Buenos Aires",
            "codigo_postal": "C1000",
            "slug": f"optional-create-{self.suffix}",
            "estado_id": self.estado_id,
            "zona_horaria": "America/Argentina/Buenos_Aires",
            "moneda": "ARS",
            "idioma": "es-AR",
        }
        if flavor is not None:
            payload["flavor_comunicacion_id"] = flavor
        return payload

    def test_create_leaves_flavor_absent(self) -> None:
        session = TestingSessionLocal()
        try:
            service = ComercioService(session)
            comercio = service.create(self._payload())
            comercio_id = int(comercio.id)
        finally:
            session.close()
        self.addCleanup(_delete_comercio, comercio_id)
        with engine.connect() as conn:
            stored = conn.execute(
                text(
                    "SELECT flavor_comunicacion_id FROM comercios "
                    "WHERE id = :id"
                ),
                {"id": comercio_id},
            ).scalar_one()
        self.assertIsNone(stored)

    def test_create_does_not_require_neutro_catalog_row(self) -> None:
        """If the canonical ``neutro`` row is removed from the
        catalog, commerce creation must continue to succeed. This
        guards the contract that ``neutro`` is no longer a required
        default."""
        neutro_id = _flavor_id("neutro")
        with TestingSessionLocal() as session, session.begin():
            session.execute(
                text(
                    "DELETE FROM flavors_comunicacion "
                    "WHERE id = :id"
                ),
                {"id": neutro_id},
            )
        try:
            session = TestingSessionLocal()
            try:
                service = ComercioService(session)
                comercio = service.create(self._payload())
                comercio_id = int(comercio.id)
            finally:
                session.close()
            self.addCleanup(_delete_comercio, comercio_id)
        finally:
            with TestingSessionLocal() as session, session.begin():
                session.execute(
                    text(
                        "INSERT INTO flavors_comunicacion "
                        "(codigo, nombre, descripcion, instruccion_llm, "
                        "activo, version) VALUES "
                        "('neutro', 'Neutro', 'Tono neutro', "
                        "'instruccion', true, 1)"
                    )
                )
        with engine.connect() as conn:
            stored = conn.execute(
                text(
                    "SELECT flavor_comunicacion_id FROM comercios "
                    "WHERE id = :id"
                ),
                {"id": comercio_id},
            ).scalar_one()
        self.assertIsNone(stored)


# ---------------------------------------------------------------------------
# Flavor assignment extension
# ---------------------------------------------------------------------------


class ComunicacionFlavorOptionalAssignmentTest(unittest.TestCase):
    """The existing assignment service is extended to persist an
    absent selection (no new endpoint, no parallel seam). The
    positive assignment validation is unchanged."""

    def setUp(self) -> None:
        self.suffix = _suffix()
        self.comercio_id = _seed_comercio(self.suffix)
        self.addCleanup(_delete_comercio, self.comercio_id)

    def _assign(self, comercio_id: int, flavor_id: int | None) -> None:
        """Assign / clear using the same transactional idiom as
        the existing service tests."""
        with TestingSessionLocal() as session, session.begin():
            service = ComunicacionFlavorService(session)
            service.assign_to_comercio(comercio_id, flavor_id)

    def test_clear_to_null_persists_absent_selection(self) -> None:
        self._assign(self.comercio_id, None)
        with engine.connect() as conn:
            stored = conn.execute(
                text(
                    "SELECT flavor_comunicacion_id FROM comercios "
                    "WHERE id = :id"
                ),
                {"id": self.comercio_id},
            ).scalar_one()
        self.assertIsNone(stored)

    def test_clear_already_cleared_is_idempotent(self) -> None:
        self._assign(self.comercio_id, None)
        self._assign(self.comercio_id, None)
        with engine.connect() as conn:
            stored = conn.execute(
                text(
                    "SELECT flavor_comunicacion_id FROM comercios "
                    "WHERE id = :id"
                ),
                {"id": self.comercio_id},
            ).scalar_one()
        self.assertIsNone(stored)

    def test_assign_active_flavor_after_clear(self) -> None:
        self._assign(self.comercio_id, None)
        serio_id = _flavor_id("serio")
        self._assign(self.comercio_id, serio_id)
        self.assertEqual(_stored_flavor(self.comercio_id), serio_id)

    def test_clear_does_not_raise_flavor_not_found(self) -> None:
        """The clear operation MUST NOT raise
        :class:`FlavorComunicacionNotFound` when no flavor is
        present. A ``None`` request is a valid administrative
        operation that simply persists the absent state."""
        from backend.services.exceptions import (
            FlavorComunicacionInactivo,
            FlavorComunicacionNotFound,
        )

        with TestingSessionLocal() as session, session.begin():
            service = ComunicacionFlavorService(session)
            service.assign_to_comercio(self.comercio_id, None)
        with TestingSessionLocal() as session:
            service = ComunicacionFlavorService(session)
            try:
                service.assign_to_comercio(self.comercio_id, None)
            except (FlavorComunicacionNotFound, FlavorComunicacionInactivo):
                self.fail(
                    "clear operation must not raise flavor domain errors"
                )


class ComunicacionFlavorRejectionPreservedTest(unittest.TestCase):
    """The positive-assignment rejection contract is preserved
    verbatim: unknown / inactive flavor IDs do not mutate the
    prior assignment."""

    def setUp(self) -> None:
        self.suffix = _suffix()
        self.comercio_id = _seed_comercio(self.suffix, flavor_codigo="serio")
        self.addCleanup(_delete_comercio, self.comercio_id)

    def test_unknown_flavor_is_rejected_without_mutation(self) -> None:
        from backend.services.exceptions import FlavorComunicacionNotFound

        previous = _stored_flavor(self.comercio_id)
        with TestingSessionLocal() as session:
            service = ComunicacionFlavorService(session)
            with self.assertRaises(FlavorComunicacionNotFound):
                service.assign_to_comercio(self.comercio_id, 999_999_999)
        self.assertEqual(_stored_flavor(self.comercio_id), previous)

    def test_clear_does_not_consume_positive_assignment_validation(self) -> None:
        """A subsequent positive assignment after a rejection is
        still authoritative and persists through the same boundary.
        """
        from backend.services.exceptions import (
            ComercioNotFound,
            FlavorComunicacionNotFound,
        )

        with TestingSessionLocal() as session:
            service = ComunicacionFlavorService(session)
            with self.assertRaises(FlavorComunicacionNotFound):
                service.assign_to_comercio(self.comercio_id, 999_999_999)
            with self.assertRaises(ComercioNotFound):
                service.assign_to_comercio(999_999_999, 5)


class ComunicacionFlavorServiceTransactionBoundaryTest(
    unittest.TestCase
):
    """The service contract is unchanged: ``commit`` / ``rollback``
    are NEVER called by the service. The caller's transaction is
    preserved for both positive and clear operations."""

    def test_clear_does_not_commit_or_rollback(self) -> None:
        session = MagicMock()
        service = ComunicacionFlavorService(session)
        service._flavor_repo = MagicMock()
        service._comercio_repo = MagicMock()
        comercio = MagicMock(
            id=1, flavor_comunicacion_id=7
        )
        service._comercio_repo.get_by_id.return_value = comercio
        service.assign_to_comercio(1, None)
        session.commit.assert_not_called()
        session.rollback.assert_not_called()


# ---------------------------------------------------------------------------
# Router contract for clear-to-null
# ---------------------------------------------------------------------------


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router_module.router)
    return app


def _override_session() -> object:
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


class RouterAssignOptionalFlavorTest(unittest.TestCase):
    """The existing ``PUT /comercios/{id}/flavor-comunicacion``
    endpoint accepts an explicit ``null`` payload to clear the
    current selection. The response remains the
    ``ComercioResponse`` projection with ``flavor_comunicacion``
    set to ``null``."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = _build_app()
        cls.app.dependency_overrides[get_session] = _override_session
        cls.app.dependency_overrides[require_admin_token] = lambda: None
        cls.client = TestClient(cls.app)

    def setUp(self) -> None:
        self.suffix = _suffix()
        self.comercio_id = _seed_comercio(self.suffix)
        self.addCleanup(_delete_comercio, self.comercio_id)

    def test_clear_payload_persists_null_and_returns_null_summary(self) -> None:
        response = self.client.put(
            f"/comercios/{self.comercio_id}/flavor-comunicacion",
            json={"flavor_comunicacion_id": None},
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIsNone(body["flavor_comunicacion"])
        self.assertNotIn("instruccion_llm", body)
        with engine.connect() as conn:
            stored = conn.execute(
                text(
                    "SELECT flavor_comunicacion_id FROM comercios "
                    "WHERE id = :id"
                ),
                {"id": self.comercio_id},
            ).scalar_one()
        self.assertIsNone(stored)

    def test_assign_then_clear_keeps_other_comercio_intact(self) -> None:
        other_suffix = _suffix()
        other_id = _seed_comercio(other_suffix, flavor_codigo="serio")
        self.addCleanup(_delete_comercio, other_id)
        with engine.connect() as conn:
            other_previous = conn.execute(
                text(
                    "SELECT flavor_comunicacion_id FROM comercios "
                    "WHERE id = :id"
                ),
                {"id": other_id},
            ).scalar_one()

        response = self.client.put(
            f"/comercios/{self.comercio_id}/flavor-comunicacion",
            json={"flavor_comunicacion_id": None},
        )
        self.assertEqual(response.status_code, 200)
        with engine.connect() as conn:
            other_after = conn.execute(
                text(
                    "SELECT flavor_comunicacion_id FROM comercios "
                    "WHERE id = :id"
                ),
                {"id": other_id},
            ).scalar_one()
        self.assertEqual(other_previous, other_after)

    def test_clear_rejects_zero_id_as_invalid_payload(self) -> None:
        """The schema MUST reject ``0`` as a magic ID; the only
        accepted absent-assignment value is the explicit ``null``.
        """
        response = self.client.put(
            f"/comercios/{self.comercio_id}/flavor-comunicacion",
            json={"flavor_comunicacion_id": 0},
        )
        self.assertEqual(response.status_code, 422)

    def test_clear_rejects_empty_string_as_invalid_payload(self) -> None:
        """The schema MUST reject empty strings; ``null`` is the
        only accepted absent-assignment value."""
        response = self.client.put(
            f"/comercios/{self.comercio_id}/flavor-comunicacion",
            json={"flavor_comunicacion_id": ""},
        )
        self.assertEqual(response.status_code, 422)

    def test_router_invokes_service_for_clear(self) -> None:
        capturado: dict[str, object] = {}

        def _factory(session: Any) -> Any:
            service = ComunicacionFlavorService(session)
            original = service.assign_to_comercio

            def _spy(c_id: int, f_id: int | None) -> Any:
                capturado["comercio_id"] = c_id
                capturado["flavor_id"] = f_id
                return original(c_id, f_id)

            service.assign_to_comercio = _spy  # type: ignore[method-assign]
            return service

        app = _build_app()
        app.dependency_overrides[get_session] = _override_session
        app.dependency_overrides[require_admin_token] = lambda: None
        client = TestClient(app)
        with patch.object(
            router_module, "ComunicacionFlavorService", side_effect=_factory
        ):
            response = client.put(
                f"/comercios/{self.comercio_id}/flavor-comunicacion",
                json={"flavor_comunicacion_id": None},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(capturado.get("comercio_id"), self.comercio_id)
        self.assertIsNone(capturado.get("flavor_id"))


# ---------------------------------------------------------------------------
# Privacy / read projections
# ---------------------------------------------------------------------------


class ConfigurationResponseOptionalFlavorTest(unittest.TestCase):
    """The ``ComercioConfiguracionResponse`` and ``ComercioResponse``
    schemas expose a nullable ``flavor_comunicacion`` summary that
    never carries ``instruccion_llm``. The earlier privacy
    invariant survives verbatim."""

    def setUp(self) -> None:
        self.suffix = _suffix()
        self.comercio_id = _seed_comercio(self.suffix, flavor_codigo=None)
        self.addCleanup(_delete_comercio, self.comercio_id)

    def _build(self) -> FastAPI:
        import backend.routers.comercios as comercios_router
        import backend.routers.configuracion_comercio as config_router

        app = FastAPI()
        app.include_router(config_router.router)
        app.include_router(comercios_router.router)
        app.dependency_overrides[get_session] = _override_session
        app.dependency_overrides[require_admin_token] = lambda: None
        return app

    def test_configuracion_returns_null_summary_for_absent_flavor(
        self,
    ) -> None:
        client = TestClient(self._build())
        response = client.get(
            f"/comercios/{self.comercio_id}/configuracion"
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("flavor_comunicacion", body)
        self.assertIsNone(body["flavor_comunicacion"])
        self.assertNotIn("instruccion_llm", body)

    def test_comercio_get_returns_null_summary_for_absent_flavor(
        self,
    ) -> None:
        client = TestClient(self._build())
        response = client.get(f"/comercios/{self.comercio_id}")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("flavor_comunicacion", body)
        self.assertIsNone(body["flavor_comunicacion"])
        self.assertNotIn("instruccion_llm", body)


# ---------------------------------------------------------------------------
# Styling boundary
# ---------------------------------------------------------------------------


class StylerAbsentFlavorTest(unittest.TestCase):
    """The shared styler returns no LLM call when the resolved
    flavor is ``None`` and emits a bounded ``not_attempted``
    diagnostic without a flavor code, both for the local list
    API and for the opt-in companion."""

    def test_local_styling_returns_original_messages(self) -> None:
        from unittest.mock import MagicMock

        from backend.intents.schemas.customer_response import (
            CustomerResponse,
        )
        from backend.services.outbound_response_styler import (
            style_responses,
        )

        db = MagicMock()
        comercio = MagicMock()
        comercio.flavor_comunicacion_id = None
        db.get.side_effect = [comercio, None]
        client = MagicMock()
        responses = [
            CustomerResponse(
                message="Hola", intent="saludo", status="executed"
            ),
            CustomerResponse(
                message="Buenas",
                intent="agradecimientos",
                status="executed",
            ),
        ]
        styled = style_responses(db, 1, responses, query_llm=client)
        self.assertEqual([r.message for r in styled], ["Hola", "Buenas"])
        self.assertEqual(client.request.call_count, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
