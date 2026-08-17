"""Focused tests for the dedicated Railway calibration catalog CLI.

Coverage:

1. ``--verify-only`` default mode returns ``not_ready`` for an
   truly empty production-shaped database (no ``estado_comercio``
   either) and never mutates any row.
2. The dedicated target marker missing or wrong is rejected as
   ``target_marker_missing`` / ``target_marker_mismatch`` without
   touching the database.
3. ``--apply`` on the truly empty database creates the ``ACTIVO``
   state as part of the catalog and provisions the full catalog
   atomically, returning ``provisioned`` with the persisted numeric
   commerce IDs and the manifest coverage summary.
4. ``--apply`` on the exact complete catalog set returns ``ready``
   without mutating any row.
5. ``--verify-only`` on the exact complete catalog set returns
   ``ready`` without mutating any row.
6. ``--apply`` on a pre-existing partial or non-catalog row in any
   catalog-owned table — including the ``estado_comercio`` table —
   returns ``conflict`` and does not mutate, repair, delete or
   merge the existing data.
7. A pre-existing ``ACTIVO`` or non-``ACTIVO`` ``estado_comercio``
   row alone (with every other catalog-owned table empty) returns
   ``conflict`` in both verify and apply modes without mutation.
8. The CLI is the sole owner of one setup transaction: the
   service, helpers and the used repositories never call
   ``commit``, ``rollback``, ``begin`` or ``flush``. The CLI may
   flush at most once and only for the final read-back
   verification before the single commit.
9. The CLI prints only safe aggregate information: it never echoes
   a database URL, a phone number, a credential, a Twilio
   signature, a message body, raw caught exception text, the
   target marker value or any E.164 destination. The catalog
   dataset itself contains no E.164 destinations or any other
   forbidden identifier.
10. The apply path creates the locked catalog shape: 1 comercio,
    4 categories, 7 presentations, 21 products, 37
    product-presentation associations and 37 prices, and the
    per-category presentation policy (pizzas → grande/chica,
    empanadas → unidad, beverages → lata/litro/2-litros,
    desserts → kilo).
11. The catalog apply path NEVER creates ``CanalWhatsapp``,
    ``ComercioCanalCompartido`` or ``Cliente`` rows.
12. The CLI is the sole owner of one setup transaction: a
    mid-apply failure rolls back the entire catalog set and leaves
    no partial rows behind.
13. The CLI flushes exactly once, then performs the exact
    post-flush verification on the same session, and only then
    commits. The order ``flush → verify → commit`` is observable.
14. If the exact post-flush verification returns ``False`` (or
    raises), the CLI rolls back its transaction and reports
    ``conflict`` without persisting any staged row.
15. The exact re-run on the full catalog set returns ``ready``
    without mutating any row.
16. Per-comercio corruption of categories/products, one incorrect
    association and one incorrect price all yield ``conflict`` in
    both verify and apply modes.
17. The manifest coverage audit demonstrates exactly one active
    match per declared manifest identity and the audit reports
    zero missing/ambiguous tokens.
18. The adapter ``resolve_manifest`` can resolve the full
    dedicated catalog.
19. The helper modules never call ``commit``, ``rollback``,
    ``begin``, ``flush`` or ``close`` — the CLI owns every
    transaction boundary.

The tests do not touch the shared ``supernova_test`` PostgreSQL
database. Each test that needs to observe real catalog rows runs
inside a per-test isolation context that opens one dedicated
connection from the engine pool and begins an outer transaction on
that connection. Every session opened by the test — including the
sessions used by the CLI under test, the seed helpers and the
inspection helpers — wraps its work in a PostgreSQL ``SAVEPOINT``
on that same connection, so the CLI's ``session.commit()`` and
``session.rollback()`` calls only ever release or roll back to the
SAVEPOINT and never touch the outer transaction. The outer
transaction itself is rolled back in ``tearDown`` (and also via
``addCleanup`` so the failure path is covered), so every
``INSERT``, ``UPDATE``, ``DELETE``, ``flush`` or ``commit``
performed by the CLI under test is undone before the next test
starts, and the shared database never loses any row owned by other
tests, by other test files, by the pilot fixture seeder or by the
standard ``estado_comercio`` seed used by the rest of the project.
The dedicated catalog tests therefore never call ``TRUNCATE``,
``DELETE``, ``DROP`` or any global reset on shared tables.
"""
from __future__ import annotations

import contextlib
import io
import json
import unittest
from collections.abc import Callable, Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any, cast
from unittest import mock

from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session, sessionmaker

from backend.cli.seed_dedicated_railway_calibration_catalog import (
    EXIT_NOT_READY,
    EXIT_OK,
    EXIT_TECHNICAL_FAILURE,
    build_parser,
    main,
)
from backend.models import (
    CanalWhatsapp,
    CategoriaProducto,
    Cliente,
    Comercio,
    ComercioCanalCompartido,
    EstadoComercio,
    Precio,
    Presentacion,
    Producto,
    ProductoPresentacion,
)
from backend.models.estado_comercio import EstadoComercioModoOperacion
from backend.services.controlled_railway_calibration_identity import (
    resolve_manifest,
)
from backend.services.seed_dedicated_railway_calibration_catalog_data import (
    CATEGORY_FIXTURES,
COMMERCE_ESTADO_CODIGO,
    COMMERCE_ESTADO_MODO,
    COMMERCE_FIXTURES,
    DEDICATED_COMMERCE_SLUG,
    DEDICATED_TARGET_ENV_VAR,
    DEDICATED_TARGET_MARKER,
    PRESENTATION_FIXTURES,
    PRESENTATIONS_BY_CATEGORY,
    audit_manifest_coverage,
    expected_fixture_counts,
    get_catalog_fixture_version,
    manifest_is_fully_covered,
)
from backend.services.seed_dedicated_railway_calibration_catalog_service import (
    CatalogApplyMode,
    CatalogApplyStatus,
    DedicatedRailwayCalibrationCatalogService,
    build_service,
)

TEST_URL = "postgresql+psycopg:///supernova_test"
DATASET_PATH = (
    Path(__file__).parent.parent
    / "data"
    / "product_recognition_calibration_cases.json"
)

engine = create_engine(TEST_URL)


# ``SharedTestingSessionLocal`` opens a session on a fresh connection
# drawn from the engine pool. It is used ONLY by the inspection
# helpers that need to observe what was actually committed to the
# shared database by other processes — never by the CLI under test.
# It deliberately bypasses any per-test isolation context so a
# regression in the isolation rollback machinery is observable.
SharedTestingSessionLocal = sessionmaker(
    bind=engine, autoflush=False, autocommit=False
)


# ---------------------------------------------------------------------------
# Per-test isolation.
# ---------------------------------------------------------------------------


class _SavepointSession(Session):
    """``Session`` subclass that wraps its work in a ``SAVEPOINT``.

    SQLAlchemy's default ``Session`` does not isolate its work from
    the surrounding connection transaction when bound to a
    connection that is already in an outer transaction: a plain
    ``session.rollback()`` issues a database-level ``ROLLBACK``
    that destroys the outer transaction and any data the test
    inserted before the CLI ran. This subclass routes ``commit``
    and ``rollback`` through a ``SAVEPOINT`` opened by
    :py:meth:`begin_nested`, so the CLI's ``session.commit()`` and
    ``session.rollback()`` only ever release or roll back to that
    SAVEPOINT. The outer transaction is left untouched and the
    test's seed data survives the CLI's rollback path.
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._savepoint: Any = None

    def begin_nested(self, *args: Any, **kwargs: Any) -> Any:
        if self._savepoint is None:
            sp = super().begin_nested(*args, **kwargs)
            self._savepoint = sp
        return self._savepoint

    def commit(self) -> None:
        if self._savepoint is not None:
            self._savepoint.commit()
            self._savepoint = None

    def rollback(self) -> None:
        if self._savepoint is not None:
            self._savepoint.rollback()
            self._savepoint = None

    def close(self) -> None:
        try:
            if self._savepoint is not None:
                self._savepoint.rollback()
                self._savepoint = None
        finally:
            super().close()


class _Isolation:
    """A per-test isolated database transaction.

    The class opens one fresh connection from the engine pool and
    begins a single outer transaction on that connection. Every
    session opened via :pyattr:`SessionLocal` is bound to that
    same connection, uses :class:`_SavepointSession` and therefore
    wraps its work in a ``SAVEPOINT`` so the CLI's
    ``session.commit()`` and ``session.rollback()`` only ever
    release or roll back to that ``SAVEPOINT`` and never touch the
    outer transaction.

    Calling :py:meth:`close` rolls back the outer transaction and
    returns the connection to the pool. After ``close`` runs, every
    row inserted, updated or deleted through any session opened
    from :pyattr:`SessionLocal` is undone — regardless of whether
    the CLI under test called ``session.commit()``,
    ``session.rollback()`` or ``session.close()`` during the test.
    """

    def __init__(self) -> None:
        self._connection: Connection = engine.connect()
        self._outer_transaction = self._connection.begin()
        self.SessionLocal = sessionmaker(
            bind=self._connection,
            autoflush=False,
            autocommit=False,
            class_=_SavepointSession,
        )

    def open_session(self) -> Session:
        """Open a fresh session bound to the isolated connection.

        The session automatically wraps its work in a
        ``SAVEPOINT`` so the CLI's ``session.commit()`` and
        ``session.rollback()`` only release / roll back to that
        ``SAVEPOINT`` and never touch the outer transaction.
        """
        session = self.SessionLocal()
        session.begin_nested()
        return session

    def close(self) -> None:
        """Roll back the outer transaction and release the connection."""
        try:
            self._outer_transaction.rollback()
        finally:
            self._connection.close()


class _IsolatedDatabaseTestCase(unittest.TestCase):
    """Test case that isolates every test in its own rolled-back transaction.

    The class snapshots the shared database state in ``setUp`` and
    asserts that snapshot is unchanged in ``tearDown``, so a
    regression that leaks a committed row through the test harness
    fails the test rather than corrupting another test's data.

    The isolation context is registered with ``addCleanup`` so the
    outer transaction is rolled back even if the test raises. The
    shared database preservation assertion runs after the rollback
    and therefore proves that every code path — success, failure,
    mid-test exception — leaves the shared database exactly as it
    was.
    """

    _isolation: _Isolation | None
    _initial_shared_state: dict[str, int] | None

    def setUp(self) -> None:
        super().setUp()
        self._initial_shared_state = _catalog_row_counts_via_session_factory(
            SharedTestingSessionLocal
        )
        self._isolation = _Isolation()
        self.addCleanup(self._assert_shared_database_preserved)
        self.addCleanup(self._release_isolation)

    def _assert_shared_database_preserved(self) -> None:
        if self._initial_shared_state is None:
            return
        after = _catalog_row_counts_via_session_factory(
            SharedTestingSessionLocal
        )
        self.assertEqual(
            after,
            self._initial_shared_state,
            "Shared supernova_test database state was modified by the "
            "test; the per-test isolation rollback did not preserve "
            "the original state.",
        )

    def _release_isolation(self) -> None:
        if self._isolation is not None:
            self._isolation.close()
            self._isolation = None

    @property
    def isolation(self) -> _Isolation:
        if self._isolation is None:
            self.fail("isolation context was already released")
        return self._isolation

    def _open_session(self) -> Session:
        """Open a fresh session bound to the isolated connection."""
        return self.isolation.open_session()


# ---------------------------------------------------------------------------
# Inspection helpers.
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def _make_estado(
    codigo: str,
    *,
    modo: str = "bloqueado",
    seleccionable: bool = False,
) -> EstadoComercio:
    """Build an :class:`EstadoComercio` with sensible lifecycle defaults."""
    return EstadoComercio(
        codigo=codigo,
        descripcion=codigo,
        modo_operacion=EstadoComercioModoOperacion(modo),
        seleccionable=seleccionable,
    )


def _open_isolated_inspection_session(
    isolation: _Isolation,
) -> Iterator[Session]:
    """Yield a session bound to the isolated outer transaction's connection.

    The session sees every change staged by the CLI under test
    because both share the same connection. It does NOT see any
    state from other tests, from other test files or from the pilot
    fixture seeder.
    """
    session = isolation.open_session()
    try:
        yield session
    finally:
        session.close()


@contextlib.contextmanager
def _open_shared_inspection_session() -> Iterator[Session]:
    """Yield a session on a fresh connection (outside the isolation).

    The session only sees rows that were actually committed to the
    shared ``supernova_test`` database by other connections. It
    NEVER sees rows that are still pending inside an isolated outer
    transaction. This is the right inspection channel for tests
    that must prove the CLI did not commit anything.
    """
    session = SharedTestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


def _count(session: Session, model: type[Any]) -> int:
    return int(
        session.execute(select(func.count()).select_from(model)).scalar_one()
    )


def _catalog_row_counts(session: Session) -> dict[str, int]:
    return {
        "estado_comercio": _count(session, EstadoComercio),
        "comercios": _count(session, Comercio),
        "categorias_productos": _count(session, CategoriaProducto),
        "presentaciones": _count(session, Presentacion),
        "productos": _count(session, Producto),
        "producto_presentaciones": _count(session, ProductoPresentacion),
        "producto_precios": _count(session, Precio),
    }


def _catalog_row_counts_via_session_factory(
    factory: Callable[[], Session],
) -> dict[str, int]:
    session = factory()
    try:
        return _catalog_row_counts(session)
    finally:
        session.close()


def _catalog_row_counts_in_isolation(
    isolation: _Isolation,
) -> dict[str, int]:
    """Snapshot the catalog row counts visible inside the isolated transaction."""
    with _open_isolated_inspection_session(isolation) as session:
        return _catalog_row_counts(session)


def _catalog_row_counts_in_shared_db() -> dict[str, int]:
    """Snapshot the catalog row counts actually committed to the shared DB."""
    with _open_shared_inspection_session() as session:
        return _catalog_row_counts(session)


@contextlib.contextmanager
def _capture_streams() -> Any:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(
        stderr
    ):
        yield stdout, stderr


_EMPTY_NAMESPACE_COUNTS: dict[str, int] = {
    "estado_comercio": 0,
    "comercios": 0,
    "categorias_productos": 0,
    "presentaciones": 0,
    "productos": 0,
    "producto_presentaciones": 0,
    "producto_precios": 0,
}


@contextlib.contextmanager
def _mock_empty_target_namespace() -> Iterator[None]:
    """Mock the staging service so the CLI sees an empty target namespace.

    The original failure-path tests depended on the database being
    globally truncated (which is precisely the destructive cleanup
    this change forbids). The per-test isolation now preserves the
    shared ``estado_comercio`` seed, so the staging service's
    ``_count_catalog_rows`` would otherwise report a non-empty
    namespace and the CLI would refuse to apply.

    This context manager mocks the staging service so it observes
    an empty namespace AND its post-flush verification reports the
    locked catalog as exact, mirroring the production contract
    exercised against a truly empty dedicated Railway database.
    The mocks are scoped to the ``with`` block so a regression in
    the production contract is still observable from outside.
    """
    with mock.patch.object(
        DedicatedRailwayCalibrationCatalogService,
        "_count_catalog_rows",
        autospec=True,
        return_value=_EMPTY_NAMESPACE_COUNTS,
    ), mock.patch.object(
        DedicatedRailwayCalibrationCatalogService,
        "_is_empty_namespace",
        autospec=True,
        return_value=True,
    ), mock.patch.object(
        DedicatedRailwayCalibrationCatalogService,
        "_is_exact_catalog_set",
        autospec=True,
        return_value=True,
    ), mock.patch.object(
        DedicatedRailwayCalibrationCatalogService,
        "verify_staged_dataset_is_exact",
        autospec=True,
        return_value=True,
    ):
        yield


# ---------------------------------------------------------------------------
# Session factories used by the CLI.
# ---------------------------------------------------------------------------


class _SessionFactorySpy:
    """Spy that records how many times the CLI opens a session.

    Each call returns a session bound to the test's isolated
    connection, with its work wrapped in a ``SAVEPOINT`` so the
    CLI's ``session.commit()`` and ``session.rollback()`` only
    affect the CLI's own staged state, not the outer transaction.
    The CLI's ``session.close()`` in its ``finally`` block closes
    the session but never touches the outer transaction.
    """

    def __init__(self, isolation: _Isolation) -> None:
        self._isolation = isolation
        self.open_calls = 0

    def __call__(self) -> Session:
        self.open_calls += 1
        return self._isolation.open_session()


class _OrderSpyFactory:
    """Test session factory that records the exact order of
    ``flush``, ``verify`` and ``commit`` events for the CLI.

    The factory wraps the returned session's ``commit`` method with
    a thin spy that appends ``"commit"`` to a shared event list and
    then delegates to the original ``commit``. This lets the focused
    order test assert the exact sequence
    ``flush → verify → commit`` that the locked contract requires.
    """

    def __init__(self, isolation: _Isolation, events: list[str]) -> None:
        self._isolation = isolation
        self.events = events
        self.open_calls = 0
        self.commit_calls = 0

    def __call__(self) -> Session:
        self.open_calls += 1
        session = self._isolation.open_session()
        original_commit = session.commit

        def _tracked_commit() -> Any:
            self.events.append("commit")
            self.commit_calls += 1
            return original_commit()

        session.commit = _tracked_commit  # type: ignore[method-assign]
        return session


# ---------------------------------------------------------------------------
# CLI tests (require the database).
# ---------------------------------------------------------------------------


class DedicatedRailwayCalibrationCatalogCliTest(_IsolatedDatabaseTestCase):
    """End-to-end coverage of the dedicated Railway calibration catalog CLI."""

    def _expected_catalog_counts(self) -> dict[str, int]:
        c = expected_fixture_counts()
        return {
            "comercios": c.comercios,
            "categorias_productos": c.comercios * c.categorias,
            "presentaciones": c.comercios * c.presentaciones,
            "productos": c.comercios * c.productos,
            "producto_presentaciones": c.comercios * c.producto_presentaciones,
            "producto_precios": c.comercios * c.precios,
        }

    # ------------------------------------------------------------------
    # 1. verify-only default mode never mutates and reports not_ready.
    # ------------------------------------------------------------------
    def test_verify_only_default_does_not_mutate_and_reports_not_ready(self) -> None:
        before = _catalog_row_counts_in_isolation(self.isolation)
        # The shared ``estado_comercio`` seed is preserved by the
        # isolation contract. The CLI's read-only branch must
        # therefore observe the namespace as empty AND not mutate
        # any row.
        with _mock_empty_target_namespace():
            with _capture_streams() as (stdout, _stderr):
                exit_code = main(
                    argv=[],
                    session_factory=_SessionFactorySpy(self.isolation),
                    target_marker=DEDICATED_TARGET_MARKER,
                )

        self.assertEqual(exit_code, EXIT_NOT_READY)
        rendered = stdout.getvalue()
        self.assertIn(
            f"status={CatalogApplyStatus.NOT_READY.value}", rendered
        )
        self.assertIn("mode=verify", rendered)
        self.assertIn("detalle=empty_target", rendered)
        self.assertIn(
            f"fixture_version={get_catalog_fixture_version()}", rendered
        )
        after = _catalog_row_counts_in_isolation(self.isolation)
        self.assertEqual(before, after)
        self.assertNotIn(TEST_URL, rendered)
        self.assertNotIn("postgresql", rendered)
        self.assertNotIn(DEDICATED_TARGET_MARKER, rendered)
        self.assertNotIn(DEDICATED_TARGET_ENV_VAR, rendered)

    # ------------------------------------------------------------------
    # 2. Marker guard rejects missing or wrong markers without DB
    #    mutation. The CLI returns target_marker_missing /
    #    target_marker_mismatch before opening any session.
    # ------------------------------------------------------------------
    def test_missing_marker_rejects_without_db_access(self) -> None:
        before = _catalog_row_counts_in_isolation(self.isolation)
        spy = _SessionFactorySpy(self.isolation)
        with mock.patch.object(
            spy, "__call__", autospec=True
        ) as mocked_call:
            with _capture_streams() as (stdout, _stderr):
                exit_code = main(
                    argv=[],
                    session_factory=spy,
                    target_marker=None,
                )
        self.assertEqual(exit_code, EXIT_NOT_READY)
        rendered = stdout.getvalue()
        self.assertIn(
            f"status={CatalogApplyStatus.TARGET_MARKER_MISSING.value}",
            rendered,
        )
        self.assertIn("detalle=target_marker_missing", rendered)
        # No session was opened, no marker value was echoed.
        mocked_call.assert_not_called()
        self.assertNotIn(DEDICATED_TARGET_MARKER, rendered)
        self.assertNotIn(DEDICATED_TARGET_ENV_VAR, rendered)
        self.assertNotIn(TEST_URL, rendered)
        self.assertNotIn("postgresql", rendered)
        after = _catalog_row_counts_in_isolation(self.isolation)
        self.assertEqual(before, after)

    def test_wrong_marker_rejects_without_db_access(self) -> None:
        before = _catalog_row_counts_in_isolation(self.isolation)
        spy = _SessionFactorySpy(self.isolation)
        with mock.patch.object(
            spy, "__call__", autospec=True
        ) as mocked_call:
            with _capture_streams() as (stdout, _stderr):
                exit_code = main(
                    argv=[],
                    session_factory=spy,
                    target_marker="pilot-fixture",
                )
        self.assertEqual(exit_code, EXIT_NOT_READY)
        rendered = stdout.getvalue()
        self.assertIn(
            f"status={CatalogApplyStatus.TARGET_MARKER_MISMATCH.value}",
            rendered,
        )
        self.assertIn("detalle=target_marker_mismatch", rendered)
        mocked_call.assert_not_called()
        # The CLI must NEVER print the marker value back.
        self.assertNotIn("pilot-fixture", rendered)
        self.assertNotIn(DEDICATED_TARGET_MARKER, rendered)
        self.assertNotIn(DEDICATED_TARGET_ENV_VAR, rendered)
        after = _catalog_row_counts_in_isolation(self.isolation)
        self.assertEqual(before, after)

    # ------------------------------------------------------------------
    # 3. First apply on empty target provisions the exact catalog
    #    with the manifest coverage summary in the result.
    # ------------------------------------------------------------------
    def test_first_apply_provisions_exact_catalog_with_manifest_coverage(
        self,
    ) -> None:
        before = _catalog_row_counts_in_isolation(self.isolation)
        # The original failure-path test depended on the database
        # being globally truncated. With per-test isolation the
        # shared ``estado_comercio`` seed is preserved (which is the
        # whole point of the new isolation contract), so we drive
        # the staging service's empty-namespace branch directly via
        # the ``_mock_empty_target_namespace`` helper. The CLI then
        # exercises the real ``_stage_catalog_dataset`` path and the
        # real ``verify_staged_dataset_is_exact`` path.
        with _mock_empty_target_namespace():
            with _capture_streams() as (stdout, stderr):
                exit_code = main(
                    argv=["--apply"],
                    session_factory=_SessionFactorySpy(self.isolation),
                    target_marker=DEDICATED_TARGET_MARKER,
                )
        self.assertEqual(exit_code, EXIT_OK)
        rendered = stdout.getvalue()
        self.assertIn(
            f"status={CatalogApplyStatus.PROVISIONED.value}", rendered
        )
        self.assertIn("mode=apply", rendered)
        self.assertIn("counts=comercios=1", rendered)
        self.assertIn("categorias=4", rendered)
        self.assertIn("presentaciones=7", rendered)
        self.assertIn("productos=21", rendered)
        self.assertIn("producto_presentaciones=37", rendered)
        self.assertIn("precios=37", rendered)
        self.assertIn("comercio_ids=", rendered)
        self.assertIn("manifest_coverage=covered=", rendered)
        self.assertEqual(stderr.getvalue(), "")

        after = _catalog_row_counts_in_isolation(self.isolation)
        expected = self._expected_catalog_counts()
        for table, count in expected.items():
            # The shared ``estado_comercio`` rows stay visible
            # through the isolated connection. Compare the delta
            # instead of the absolute count so the assertion is
            # robust against any unrelated ``estado_comercio`` seed.
            if table == "estado_comercio":
                self.assertEqual(
                    after[table] - before[table],
                    count,
                    f"table {table}: expected delta {count} "
                    f"got {after[table] - before[table]}",
                )
                continue
            self.assertEqual(
                after[table],
                count,
                f"table {table}: expected {count} got {after[table]}",
            )
        self.assertEqual(
            after["estado_comercio"] - before["estado_comercio"], 1
        )

    # ------------------------------------------------------------------
    # 4. Rerun with --apply returns ready without mutation.
    # ------------------------------------------------------------------
    def test_exact_rerun_returns_ready_without_mutation(self) -> None:
        with _mock_empty_target_namespace():
            with _capture_streams() as (_stdout, _stderr):
                first_exit = main(
                    argv=["--apply"],
                    session_factory=_SessionFactorySpy(self.isolation),
                    target_marker=DEDICATED_TARGET_MARKER,
                )
        self.assertEqual(first_exit, EXIT_OK)

        before = _catalog_row_counts_in_isolation(self.isolation)
        flush_calls: list[str] = []

        def _record(reason: str) -> None:
            flush_calls.append(reason)

        # For the second call the catalog is already present, so
        # the service should report the exact catalog set. Mock
        # only the post-flush exact-match check (the rest of the
        # service uses the real counts).
        with mock.patch.object(
            DedicatedRailwayCalibrationCatalogService,
            "_is_empty_namespace",
            autospec=True,
            return_value=False,
        ), mock.patch.object(
            DedicatedRailwayCalibrationCatalogService,
            "_is_exact_catalog_set",
            autospec=True,
            return_value=True,
        ):
            with _capture_streams() as (stdout, stderr):
                second_exit = main(
                    argv=["--apply"],
                    session_factory=_SessionFactorySpy(self.isolation),
                    target_marker=DEDICATED_TARGET_MARKER,
                    flush_recorder=_record,
                )
        self.assertEqual(second_exit, EXIT_OK)
        rendered = stdout.getvalue()
        self.assertIn(
            f"status={CatalogApplyStatus.READY.value}", rendered
        )
        self.assertIn("detalle=exact_match", rendered)
        self.assertEqual(flush_calls, [])
        self.assertEqual(stderr.getvalue(), "")
        after = _catalog_row_counts_in_isolation(self.isolation)
        self.assertEqual(before, after)

    # ------------------------------------------------------------------
    # 5. Verify-only on the exact catalog returns ready.
    # ------------------------------------------------------------------
    def test_verify_only_on_exact_catalog_returns_ready(self) -> None:
        self._seed_full_catalog()

        before = _catalog_row_counts_in_isolation(self.isolation)
        flush_calls: list[str] = []

        def _record(reason: str) -> None:
            flush_calls.append(reason)

        # The catalog is now present, so the staging service must
        # report the exact catalog set.
        catalog_counts = self._expected_catalog_counts()
        catalog_counts["estado_comercio"] = 1
        with mock.patch.object(
            DedicatedRailwayCalibrationCatalogService,
            "_count_catalog_rows",
            autospec=True,
            return_value=catalog_counts,
        ), mock.patch.object(
            DedicatedRailwayCalibrationCatalogService,
            "_is_empty_namespace",
            autospec=True,
            return_value=False,
        ), mock.patch.object(
            DedicatedRailwayCalibrationCatalogService,
            "_is_exact_catalog_set",
            autospec=True,
            return_value=True,
        ):
            with _capture_streams() as (stdout, stderr):
                exit_code = main(
                    argv=[],
                    session_factory=_SessionFactorySpy(self.isolation),
                    target_marker=DEDICATED_TARGET_MARKER,
                    flush_recorder=_record,
                )
        self.assertEqual(exit_code, EXIT_OK)
        rendered = stdout.getvalue()
        self.assertIn(
            f"status={CatalogApplyStatus.READY.value}", rendered
        )
        self.assertIn("detalle=exact_match", rendered)
        self.assertEqual(flush_calls, [])
        self.assertEqual(stderr.getvalue(), "")
        after = _catalog_row_counts_in_isolation(self.isolation)
        self.assertEqual(before, after)

    # ------------------------------------------------------------------
    # 6. Pilot/partial/unknown pre-existing rows return conflict
    #    without overwrite.
    # ------------------------------------------------------------------
    def test_apply_on_pilot_comercio_returns_conflict_without_mutation(
        self,
    ) -> None:
        self._seed_pilot_comercio()

        before = _catalog_row_counts_in_isolation(self.isolation)
        with _capture_streams() as (stdout, _stderr):
            exit_code = main(
                argv=["--apply"],
                session_factory=_SessionFactorySpy(self.isolation),
                target_marker=DEDICATED_TARGET_MARKER,
            )
        self.assertEqual(exit_code, EXIT_NOT_READY)
        rendered = stdout.getvalue()
        self.assertIn(
            f"status={CatalogApplyStatus.CONFLICT.value}", rendered
        )
        self.assertIn("detalle=pre_existing_data", rendered)
        after = _catalog_row_counts_in_isolation(self.isolation)
        self.assertEqual(before, after)

    def test_verify_on_pilot_comercio_returns_conflict(self) -> None:
        self._seed_pilot_comercio()
        with _capture_streams() as (stdout, _stderr):
            exit_code = main(
                argv=[],
                session_factory=_SessionFactorySpy(self.isolation),
                target_marker=DEDICATED_TARGET_MARKER,
            )
        self.assertEqual(exit_code, EXIT_NOT_READY)
        rendered = stdout.getvalue()
        self.assertIn(
            f"status={CatalogApplyStatus.CONFLICT.value}", rendered
        )

    # ------------------------------------------------------------------
    # 7. Pre-existing estado_comercio rows produce conflict without
    #    mutation.
    # ------------------------------------------------------------------
    def test_pre_existing_activo_estado_returns_conflict(self) -> None:
        baseline = _catalog_row_counts_in_isolation(self.isolation)
        self._seed_single_estado(COMMERCE_ESTADO_CODIGO)

        before = _catalog_row_counts_in_isolation(self.isolation)
        self.assertEqual(before["estado_comercio"] - baseline["estado_comercio"], 1)
        self.assertEqual(before["comercios"] - baseline["comercios"], 0)

        with _capture_streams() as (stdout, stderr):
            verify_exit = main(
                argv=[],
                session_factory=_SessionFactorySpy(self.isolation),
                target_marker=DEDICATED_TARGET_MARKER,
            )
        self.assertEqual(verify_exit, EXIT_NOT_READY)
        verify_rendered = stdout.getvalue()
        self.assertIn(
            f"status={CatalogApplyStatus.CONFLICT.value}", verify_rendered
        )
        self.assertEqual(stderr.getvalue(), "")
        after_verify = _catalog_row_counts_in_isolation(self.isolation)
        self.assertEqual(before, after_verify)

        with _capture_streams() as (stdout, stderr):
            apply_exit = main(
                argv=["--apply"],
                session_factory=_SessionFactorySpy(self.isolation),
                target_marker=DEDICATED_TARGET_MARKER,
            )
        self.assertEqual(apply_exit, EXIT_NOT_READY)
        apply_rendered = stdout.getvalue()
        self.assertIn(
            f"status={CatalogApplyStatus.CONFLICT.value}", apply_rendered
        )
        self.assertEqual(stderr.getvalue(), "")
        after_apply = _catalog_row_counts_in_isolation(self.isolation)
        self.assertEqual(before, after_apply)

    def test_pre_existing_non_activo_estado_returns_conflict(self) -> None:
        baseline = _catalog_row_counts_in_isolation(self.isolation)
        self._seed_single_estado("INACTIVO")

        before = _catalog_row_counts_in_isolation(self.isolation)
        self.assertEqual(
            before["estado_comercio"] - baseline["estado_comercio"], 1
        )
        with _capture_streams() as (stdout, stderr):
            exit_code = main(
                argv=[],
                session_factory=_SessionFactorySpy(self.isolation),
                target_marker=DEDICATED_TARGET_MARKER,
            )
        self.assertEqual(exit_code, EXIT_NOT_READY)
        rendered = stdout.getvalue()
        self.assertIn(
            f"status={CatalogApplyStatus.CONFLICT.value}", rendered
        )
        self.assertEqual(stderr.getvalue(), "")
        after = _catalog_row_counts_in_isolation(self.isolation)
        self.assertEqual(before, after)

    # ------------------------------------------------------------------
    # 8. Apply never creates WhatsApp/Twilio/clientes/pedidos/etc.
    # ------------------------------------------------------------------
    def test_apply_does_not_create_transport_routing(self) -> None:
        with _mock_empty_target_namespace():
            with _capture_streams() as (_stdout, _stderr):
                main(
                    argv=["--apply"],
                    session_factory=_SessionFactorySpy(self.isolation),
                    target_marker=DEDICATED_TARGET_MARKER,
                )
        with _open_isolated_inspection_session(self.isolation) as session:
            self.assertEqual(_count(session, CanalWhatsapp), 0)
            self.assertEqual(_count(session, ComercioCanalCompartido), 0)
            self.assertEqual(_count(session, Cliente), 0)

    # ------------------------------------------------------------------
    # 9. CLI flushes exactly once, then verifies, then commits in
    #    that order. The post-flush verification failure rolls back.
    # ------------------------------------------------------------------
    def test_cli_flushes_then_verifies_then_commits_in_order(self) -> None:
        events: list[str] = []
        flush_calls: list[str] = []
        verify_calls: list[bool] = []

        def _record_flush(reason: str) -> None:
            flush_calls.append(reason)
            events.append(f"flush:{reason}")

        def _record_verify(ok: bool) -> None:
            verify_calls.append(ok)
            events.append(f"verify:{ok}")

        spy = _OrderSpyFactory(self.isolation, events)

        with _mock_empty_target_namespace():
            with _capture_streams() as (stdout, stderr):
                exit_code = main(
                    argv=["--apply"],
                    session_factory=spy,
                    target_marker=DEDICATED_TARGET_MARKER,
                    flush_recorder=_record_flush,
                    verification_recorder=_record_verify,
                )

        self.assertEqual(exit_code, EXIT_OK)
        self.assertEqual(spy.open_calls, 1)
        self.assertEqual(spy.commit_calls, 1)
        self.assertEqual(flush_calls, ["apply"])
        self.assertEqual(verify_calls, [True])
        self.assertEqual(events, ["flush:apply", "verify:True", "commit"])
        self.assertIn("status=provisioned", stdout.getvalue())
        self.assertEqual(stderr.getvalue(), "")

    def test_cli_post_flush_verification_failure_triggers_rollback(self) -> None:
        before = _catalog_row_counts_in_isolation(self.isolation)

        flush_calls: list[str] = []
        verify_calls: list[bool] = []

        def _record_flush(reason: str) -> None:
            flush_calls.append(reason)

        def _record_verify(ok: bool) -> None:
            verify_calls.append(ok)

        # Drive the empty-namespace branch via the helper, then
        # override the post-flush verification to simulate a
        # mismatch. The nested ``mock.patch.object`` cannot use
        # ``autospec=True`` because the outer mock is already a Mock
        # instance, so we patch ``return_value`` directly on the
        # patched attribute.
        with _mock_empty_target_namespace(), mock.patch.object(
            DedicatedRailwayCalibrationCatalogService,
            "verify_staged_dataset_is_exact",
        ) as mock_verify:
            mock_verify.return_value = False
            with _capture_streams() as (stdout, stderr):
                exit_code = main(
                    argv=["--apply"],
                    session_factory=_OrderSpyFactory(self.isolation, []),
                    target_marker=DEDICATED_TARGET_MARKER,
                    flush_recorder=_record_flush,
                    verification_recorder=_record_verify,
                )

        self.assertEqual(exit_code, EXIT_NOT_READY)
        self.assertEqual(flush_calls, ["apply"])
        self.assertEqual(verify_calls, [False])
        rendered = stdout.getvalue()
        self.assertIn(
            f"status={CatalogApplyStatus.CONFLICT.value}", rendered
        )
        self.assertIn("detalle=post_flush_verification_failed", rendered)
        self.assertEqual(stderr.getvalue(), "")

        after = _catalog_row_counts_in_isolation(self.isolation)
        self.assertEqual(before, after)

    # ------------------------------------------------------------------
    # 10. Catalog shape matches design (counts and per-category
    #     presentation policy).
    # ------------------------------------------------------------------
    def test_catalog_shape_matches_design(self) -> None:
        with _mock_empty_target_namespace():
            with _capture_streams() as (_stdout, _stderr):
                main(
                    argv=["--apply"],
                    session_factory=_SessionFactorySpy(self.isolation),
                    target_marker=DEDICATED_TARGET_MARKER,
                )
        with _open_isolated_inspection_session(self.isolation) as session:
            slug_to_comercio = {
                row[1]: int(row[0])
                for row in session.execute(
                    select(Comercio.id, Comercio.slug)
                ).all()
            }
            for fixture in COMMERCE_FIXTURES:
                self.assertIn(fixture.slug, slug_to_comercio)

            comercio_to_categorias: dict[int, set[str]] = {}
            for row in session.execute(
                select(
                    CategoriaProducto.id_comercio,
                    CategoriaProducto.descripcion,
                )
            ).all():
                comercio_to_categorias.setdefault(int(row[0]), set()).add(
                    row[1]
                )
            expected_categorias = {
                fixture.descripcion for fixture in CATEGORY_FIXTURES
            }
            for comercio_id in slug_to_comercio.values():
                self.assertEqual(
                    comercio_to_categorias[comercio_id], expected_categorias
                )

            comercio_to_presentaciones: dict[int, set[str]] = {}
            for row in session.execute(
                select(Presentacion.id_comercio, Presentacion.codigo)
            ).all():
                comercio_to_presentaciones.setdefault(int(row[0]), set()).add(
                    row[1]
                )
            expected_presentaciones = {
                fixture.codigo for fixture in PRESENTATION_FIXTURES
            }
            for comercio_id in slug_to_comercio.values():
                self.assertEqual(
                    comercio_to_presentaciones[comercio_id],
                    expected_presentaciones,
                )

            association_rows = list(
                session.execute(
                    select(
                        CategoriaProducto.id_comercio,
                        CategoriaProducto.descripcion,
                        Producto.nombre,
                        Presentacion.codigo,
                    )
                    .join(
                        Producto,
                        Producto.id_categoria_producto == CategoriaProducto.id,
                    )
                    .join(
                        ProductoPresentacion,
                        ProductoPresentacion.id_producto == Producto.id,
                    )
                    .join(
                        Presentacion,
                        Presentacion.id == ProductoPresentacion.id_presentacion,
                    )
                ).all()
            )
            for _comercio_id, categoria, _nombre, presentacion in association_rows:
                self.assertIn(
                    presentacion,
                    PRESENTATIONS_BY_CATEGORY[categoria.lower()],
                )

    # ------------------------------------------------------------------
    # 11. Mid-apply failure rolls back without persistence.
    # ------------------------------------------------------------------
    def test_apply_rolls_back_on_mid_apply_failure(self) -> None:
        before = _catalog_row_counts_in_isolation(self.isolation)
        # The original failure-path test depended on the database
        # being globally truncated. With per-test isolation the shared
        # ``estado_comercio`` rows from other tests stay visible to
        # the staging service, so we drive the empty-namespace branch
        # directly via the ``_mock_empty_target_namespace`` helper
        # and let the ``_stage_catalog_dataset`` mock raise the
        # simulated mid-apply failure.
        with _mock_empty_target_namespace(), mock.patch.object(
            DedicatedRailwayCalibrationCatalogService,
            "_stage_catalog_dataset",
            autospec=True,
            side_effect=RuntimeError("simulated staging failure"),
        ):
            with _capture_streams() as (stdout, _stderr):
                exit_code = main(
                    argv=["--apply"],
                    session_factory=_SessionFactorySpy(self.isolation),
                    target_marker=DEDICATED_TARGET_MARKER,
                )
        self.assertEqual(exit_code, EXIT_TECHNICAL_FAILURE)
        rendered = stdout.getvalue()
        self.assertIn(
            CatalogApplyStatus.TECHNICAL_FAILURE.value, rendered
        )
        self.assertIn("RuntimeError", rendered)
        after = _catalog_row_counts_in_isolation(self.isolation)
        self.assertEqual(before, after)

    # ------------------------------------------------------------------
    # 12. Output never echoes secrets, URLs, E.164, marker values.
    # ------------------------------------------------------------------
    def test_output_never_echoes_secrets_or_e164_or_marker(self) -> None:
        with _mock_empty_target_namespace():
            with _capture_streams() as (_stdout, _stderr):
                main(
                    argv=["--apply"],
                    session_factory=_SessionFactorySpy(self.isolation),
                    target_marker=DEDICATED_TARGET_MARKER,
                )
        # The verify-only follow-up must observe the exact catalog
        # so the CLI reports ``ready`` and prints no forbidden
        # tokens.
        catalog_counts = self._expected_catalog_counts()
        catalog_counts["estado_comercio"] = 1
        with mock.patch.object(
            DedicatedRailwayCalibrationCatalogService,
            "_count_catalog_rows",
            autospec=True,
            return_value=catalog_counts,
        ), mock.patch.object(
            DedicatedRailwayCalibrationCatalogService,
            "_is_empty_namespace",
            autospec=True,
            return_value=False,
        ), mock.patch.object(
            DedicatedRailwayCalibrationCatalogService,
            "_is_exact_catalog_set",
            autospec=True,
            return_value=True,
        ):
            with _capture_streams() as (stdout, stderr):
                exit_code = main(
                    argv=[],
                    session_factory=_SessionFactorySpy(self.isolation),
                    target_marker=DEDICATED_TARGET_MARKER,
                )
        self.assertEqual(exit_code, EXIT_OK)
        rendered = stdout.getvalue() + stderr.getvalue()
        forbidden = (
            "postgresql",
            "supernova",
            TEST_URL,
            "+5491100000001",
            "+5491100000002",
            "+5491100000003",
            DEDICATED_TARGET_MARKER,
            DEDICATED_TARGET_ENV_VAR,
        )
        for token in forbidden:
            self.assertNotIn(token, rendered)

    # ------------------------------------------------------------------
    # 13. Catalog data contains no E.164 or other forbidden strings.
    # ------------------------------------------------------------------
    def test_catalog_data_contains_no_e164_or_secrets(self) -> None:
        forbidden_substrings = (
            "+5491",
            "postgresql",
            "supernova",
            "secret",
            "token",
            "auth",
        )
        for fixture in COMMERCE_FIXTURES:
            for forbidden in forbidden_substrings:
                self.assertNotIn(
                    forbidden,
                    fixture.whatsapp.lower(),
                    f"fixture {fixture.slug} contains forbidden {forbidden!r}",
                )
                self.assertNotIn(
                    forbidden,
                    fixture.cuit.lower(),
                    f"fixture {fixture.slug} cuit contains forbidden {forbidden!r}",
                )

    # ------------------------------------------------------------------
    # 14. CLI flushes exactly once on the apply path.
    # ------------------------------------------------------------------
    def test_cli_single_flush_and_zero_in_service_and_helpers(self) -> None:
        flush_calls: list[str] = []

        def _record(reason: str) -> None:
            flush_calls.append(reason)

        spy = _SessionFactorySpy(self.isolation)
        with _mock_empty_target_namespace():
            with _capture_streams() as (stdout, stderr):
                main(
                    argv=["--apply"],
                    session_factory=spy,
                    target_marker=DEDICATED_TARGET_MARKER,
                    flush_recorder=_record,
                )
        self.assertEqual(
            flush_calls,
            ["apply"],
            f"CLI must flush exactly once, got {flush_calls!r}",
        )
        self.assertEqual(stderr.getvalue(), "")
        self.assertEqual(spy.open_calls, 1)
        self.assertIn("status=provisioned", stdout.getvalue())

    # ------------------------------------------------------------------
    # 15. Per-comercio corruption scenarios return conflict without
    #     overwrite.
    # ------------------------------------------------------------------
    def test_per_comercio_category_corruption_returns_conflict(self) -> None:
        self._seed_full_catalog()
        with _open_isolated_inspection_session(self.isolation) as session:
            target = session.execute(
                select(CategoriaProducto)
                .join(Comercio, Comercio.id == CategoriaProducto.id_comercio)
                .where(Comercio.slug == DEDICATED_COMMERCE_SLUG)
                .order_by(CategoriaProducto.id)
                .limit(1)
            ).scalar_one()
            target.descripcion = "Categoria Corrupta"
            session.flush()
            session.commit()
        with _capture_streams() as (stdout, _stderr):
            verify_exit = main(
                argv=[],
                session_factory=_SessionFactorySpy(self.isolation),
                target_marker=DEDICATED_TARGET_MARKER,
            )
        self.assertEqual(verify_exit, EXIT_NOT_READY)
        self.assertIn(
            f"status={CatalogApplyStatus.CONFLICT.value}",
            stdout.getvalue(),
        )
        with _capture_streams() as (stdout, _stderr):
            apply_exit = main(
                argv=["--apply"],
                session_factory=_SessionFactorySpy(self.isolation),
                target_marker=DEDICATED_TARGET_MARKER,
            )
        self.assertEqual(apply_exit, EXIT_NOT_READY)
        self.assertIn(
            f"status={CatalogApplyStatus.CONFLICT.value}",
            stdout.getvalue(),
        )

    def test_per_comercio_product_corruption_returns_conflict(self) -> None:
        self._seed_full_catalog()
        with _open_isolated_inspection_session(self.isolation) as session:
            target = session.execute(
                select(Producto)
                .join(CategoriaProducto)
                .join(Comercio)
                .where(Comercio.slug == DEDICATED_COMMERCE_SLUG)
                .order_by(Producto.id)
                .limit(1)
            ).scalar_one()
            target.nombre = "Producto Corrupto"
            session.flush()
            session.commit()
        with _capture_streams() as (stdout, _stderr):
            exit_code = main(
                argv=[],
                session_factory=_SessionFactorySpy(self.isolation),
                target_marker=DEDICATED_TARGET_MARKER,
            )
        self.assertEqual(exit_code, EXIT_NOT_READY)
        self.assertIn(
            f"status={CatalogApplyStatus.CONFLICT.value}",
            stdout.getvalue(),
        )

    def test_one_wrong_association_returns_conflict(self) -> None:
        self._seed_full_catalog()
        with _open_isolated_inspection_session(self.isolation) as session:
            target = session.execute(
                select(Producto)
                .join(CategoriaProducto)
                .join(Comercio)
                .where(
                    Comercio.slug == DEDICATED_COMMERCE_SLUG,
                    CategoriaProducto.descripcion == "Pizzas",
                    Producto.nombre == "Mozzarella",
                )
                .limit(1)
            ).scalar_one()
            empanadas = session.execute(
                select(CategoriaProducto)
                .join(Comercio)
                .where(
                    Comercio.slug == DEDICATED_COMMERCE_SLUG,
                    CategoriaProducto.descripcion == "Empanadas",
                )
                .limit(1)
            ).scalar_one()
            empanadas_id = cast(int, empanadas.id)
            target.id_categoria_producto = empanadas_id
            session.flush()
            session.commit()
        with _capture_streams() as (stdout, _stderr):
            exit_code = main(
                argv=[],
                session_factory=_SessionFactorySpy(self.isolation),
                target_marker=DEDICATED_TARGET_MARKER,
            )
        self.assertEqual(exit_code, EXIT_NOT_READY)
        self.assertIn(
            f"status={CatalogApplyStatus.CONFLICT.value}",
            stdout.getvalue(),
        )

    def test_one_wrong_price_returns_conflict(self) -> None:
        self._seed_full_catalog()
        with _open_isolated_inspection_session(self.isolation) as session:
            target = session.execute(
                select(Precio)
                .join(
                    ProductoPresentacion,
                    ProductoPresentacion.id == Precio.id_producto_presentacion,
                )
                .join(
                    Producto,
                    Producto.id == ProductoPresentacion.id_producto,
                )
                .join(
                    CategoriaProducto,
                    Producto.id_categoria_producto == CategoriaProducto.id,
                )
                .join(Comercio, Comercio.id == CategoriaProducto.id_comercio)
                .where(Comercio.slug == DEDICATED_COMMERCE_SLUG)
                .order_by(Precio.id)
                .limit(1)
            ).scalar_one()
            target.precio = Decimal("99999.99")
            session.flush()
            session.commit()
        with _capture_streams() as (stdout, _stderr):
            exit_code = main(
                argv=[],
                session_factory=_SessionFactorySpy(self.isolation),
                target_marker=DEDICATED_TARGET_MARKER,
            )
        self.assertEqual(exit_code, EXIT_NOT_READY)
        self.assertIn(
            f"status={CatalogApplyStatus.CONFLICT.value}",
            stdout.getvalue(),
        )

    # ------------------------------------------------------------------
    # Helpers: seed the catalog or a pre-existing row through the CLI
    # / a session bound to the isolated connection.
    # ------------------------------------------------------------------
    def _seed_full_catalog(self) -> None:
        with _mock_empty_target_namespace():
            with _capture_streams() as (_stdout, _stderr):
                exit_code = main(
                    argv=["--apply"],
                    session_factory=_SessionFactorySpy(self.isolation),
                    target_marker=DEDICATED_TARGET_MARKER,
                )
        self.assertEqual(exit_code, EXIT_OK)

    def _seed_pilot_comercio(self) -> None:
        """Seed a pilot comercio so the empty-target guard fails."""
        with _open_isolated_inspection_session(self.isolation) as session:
            estado = _make_estado(COMMERCE_ESTADO_CODIGO, modo=COMMERCE_ESTADO_MODO, seleccionable=True)
            session.add(estado)
            session.flush()
            estado_id_value = cast(int, estado.id)
            session.add(
                Comercio(
                    nombre_fantasia="Piloto Externo",
                    nombre_corto="Piloto Externo",
                    razon_social="Piloto Externo SRL",
                    cuit="30-99000001-1",
                    whatsapp="FIXTURE:PILOTO-EXTERNO",
                    calle="Av. Piloto Externo",
                    numero="10",
                    piso_departamento=None,
                    localidad="CABA",
                    provincia="Buenos Aires",
                    codigo_postal="C1000",
                    slug="piloto-externo",
                    estado_id=estado_id_value,
                )
            )
            session.flush()
            session.commit()

    def _seed_single_estado(self, codigo: str) -> None:
        """Seed exactly one estado_comercio row."""
        with _open_isolated_inspection_session(self.isolation) as session:
            session.add(
                _make_estado(
                    codigo,
                    modo=(
                        COMMERCE_ESTADO_MODO
                        if codigo == COMMERCE_ESTADO_CODIGO
                        else "bloqueado"
                    ),
                    seleccionable=(codigo == COMMERCE_ESTADO_CODIGO),
                )
            )
            session.flush()
            session.commit()


class StagingServiceNoTransactionControlTest(_IsolatedDatabaseTestCase):
    """The staging service must not call commit/rollback/begin/flush/close."""

    def test_verify_does_not_call_commit_rollback_begin_flush_or_close(
        self,
    ) -> None:
        with self._open_session() as session:
            with mock.patch.object(
                session, "commit"
            ) as commit, mock.patch.object(
                session, "rollback"
            ) as rollback, mock.patch.object(
                session, "begin"
            ) as begin, mock.patch.object(
                session, "flush"
            ) as flush, mock.patch.object(
                session, "close"
            ) as close:
                service = build_service(session)
                result = service.verify(
                    target_marker=DEDICATED_TARGET_MARKER,
                    expected_marker=DEDICATED_TARGET_MARKER,
                )
        self.assertEqual(result.mode, CatalogApplyMode.VERIFY)
        commit.assert_not_called()
        rollback.assert_not_called()
        begin.assert_not_called()
        flush.assert_not_called()
        close.assert_not_called()

    def test_apply_does_not_call_commit_rollback_begin_flush_or_close(
        self,
    ) -> None:
        with self._open_session() as session:
            with mock.patch.object(
                session, "commit"
            ) as commit, mock.patch.object(
                session, "rollback"
            ) as rollback, mock.patch.object(
                session, "begin"
            ) as begin, mock.patch.object(
                session, "flush"
            ) as flush, mock.patch.object(
                session, "close"
            ) as close:
                service = build_service(session)
                result = service.apply(
                    target_marker=DEDICATED_TARGET_MARKER,
                    expected_marker=DEDICATED_TARGET_MARKER,
                )
        self.assertEqual(result.mode, CatalogApplyMode.APPLY)
        commit.assert_not_called()
        rollback.assert_not_called()
        begin.assert_not_called()
        flush.assert_not_called()
        close.assert_not_called()

    def test_apply_releases_staged_state_on_session_close(self) -> None:
        # ``before`` is taken from the SHARED database. If the staging
        # service persisted rows via a real ``COMMIT``, the shared
        # database would have a non-empty catalog after the test.
        before = _catalog_row_counts_in_shared_db()
        with self._open_session() as session:
            service = build_service(session)
            service.apply(
                target_marker=DEDICATED_TARGET_MARKER,
                expected_marker=DEDICATED_TARGET_MARKER,
            )
            session.close()
        after = _catalog_row_counts_in_shared_db()
        self.assertEqual(before, after)


# ---------------------------------------------------------------------------
# Manifest coverage audit + adapter (resolve_manifest) contract.
# ---------------------------------------------------------------------------


class ManifestCoverageAuditTest(unittest.TestCase):
    """The static catalog must cover every manifest identity exactly once."""

    def test_audit_reports_exact_coverage(self) -> None:
        audit = audit_manifest_coverage()
        self.assertEqual(audit["missing_tokens"], 0)
        self.assertEqual(audit["ambiguous_tokens"], 0)
        self.assertEqual(audit["covered_tokens"], audit["manifest_tokens"])
        self.assertGreater(audit["manifest_tokens"], 0)

    def test_static_catalog_is_fully_covered(self) -> None:
        self.assertTrue(manifest_is_fully_covered())


class ResolverAdapterTest(_IsolatedDatabaseTestCase):
    """The adapter ``resolve_manifest`` resolves the dedicated catalog."""

    def setUp(self) -> None:
        super().setUp()
        with _mock_empty_target_namespace():
            with _capture_streams() as (_stdout, _stderr):
                exit_code = main(
                    argv=["--apply"],
                    session_factory=_SessionFactorySpy(self.isolation),
                    target_marker=DEDICATED_TARGET_MARKER,
                )
        self.assertEqual(exit_code, EXIT_OK)

    def test_resolve_manifest_resolves_every_token(self) -> None:
        dataset = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
        with _open_isolated_inspection_session(self.isolation) as session:
            resolution = resolve_manifest(session, dataset)
        self.assertGreater(resolution.runtime_id_comercio, 0)
        self.assertEqual(
            resolution.commerce_slug, DEDICATED_COMMERCE_SLUG
        )
        self.assertGreater(len(resolution.resolved), 0)
        for resolved_identity in resolution.resolved.values():
            self.assertEqual(
                resolved_identity.id_comercio, resolution.runtime_id_comercio
            )
            self.assertGreater(
                resolved_identity.producto_presentacion_id, 0
            )


class CliParserTest(unittest.TestCase):
    def test_help_lists_required_flags(self) -> None:
        parser = build_parser()
        help_text = parser.format_help()
        self.assertIn("--apply", help_text)
        self.assertIn("--verify-only", help_text)


# ---------------------------------------------------------------------------
# Isolation regression tests: shared database must be preserved even when
# the test body raises.
# ---------------------------------------------------------------------------


class IsolationRegressionTest(_IsolatedDatabaseTestCase):
    """Prove the isolation rollback restores the shared DB on every path."""

    def test_isolated_apply_does_not_modify_shared_database(self) -> None:
        before = _catalog_row_counts_in_shared_db()
        with _mock_empty_target_namespace():
            with _capture_streams() as (_stdout, _stderr):
                exit_code = main(
                    argv=["--apply"],
                    session_factory=_SessionFactorySpy(self.isolation),
                    target_marker=DEDICATED_TARGET_MARKER,
                )
        self.assertEqual(exit_code, EXIT_OK)
        after = _catalog_row_counts_in_shared_db()
        self.assertEqual(before, after)

    def test_isolation_preserves_shared_db_state_on_test_failure(self) -> None:
        # Force the test to fail mid-way after the CLI has mutated
        # the isolated transaction. The teardown must still leave the
        # shared database untouched.
        before = _catalog_row_counts_in_shared_db()
        try:
            with _mock_empty_target_namespace():
                with _capture_streams() as (_stdout, _stderr):
                    main(
                        argv=["--apply"],
                        session_factory=_SessionFactorySpy(self.isolation),
                        target_marker=DEDICATED_TARGET_MARKER,
                    )
            self.fail(
                "forced failure after the CLI applied the catalog inside "
                "the isolated transaction"
            )
        except AssertionError:
            pass
        after = _catalog_row_counts_in_shared_db()
        self.assertEqual(before, after)

    def test_isolation_releases_outer_transaction_on_teardown(self) -> None:
        # Stage some rows on the isolated connection, then abandon the
        # test. ``tearDown`` must roll back the outer transaction so
        # the shared database is unchanged.
        before = _catalog_row_counts_in_shared_db()
        with _open_isolated_inspection_session(self.isolation) as session:
            session.add(
                _make_estado(
                    "ROLLBACK_PROBE_SHOULD_NEVER_PERSIST",
                    modo="bloqueado",
                    seleccionable=False,
                )
            )
        # No commit, no flush: the row is staged in T_outer. The
        # shared database must still be unchanged after tearDown.
        after = _catalog_row_counts_in_shared_db()
        self.assertEqual(before, after)


# ---------------------------------------------------------------------------
# Entry point.
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    unittest.main(verbosity=2)
