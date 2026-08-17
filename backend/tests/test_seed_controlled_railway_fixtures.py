"""Focused tests for the controlled Railway fixture CLI.

Coverage:

1. ``--verify-only`` default mode returns ``not_ready`` for an
   truly empty production-shaped database (no ``estado_comercio``
   either) and never mutates any row.
2. ``--apply`` on the truly empty database creates the ``ACTIVO``
   state as part of the fixture and provisions the full catalog
   atomically, returning ``provisioned`` with the persisted numeric
   commerce IDs.
3. ``--apply`` on the exact complete fixture set returns ``ready``
   without mutating any row.
4. ``--verify-only`` on the exact complete fixture set returns
   ``ready`` without mutating any row.
5. ``--apply`` on a pre-existing partial or non-fixture row in any
   fixture-owned table — including the ``estado_comercio`` table —
   returns ``conflict`` and does not mutate, repair, delete or
   merge the existing data.
6. A pre-existing ``ACTIVO`` ``estado_comercio`` row alone (with
   every other fixture-owned table empty) returns ``conflict`` in
   both verify and apply modes without mutation.
7. A pre-existing non-``ACTIVO`` ``estado_comercio`` row alone
   returns ``conflict`` in both verify and apply modes without
   mutation.
8. The CLI is the sole owner of one setup transaction: the
   service, helpers and the used repositories never call
   ``commit``, ``rollback``, ``begin`` or ``flush``. The CLI may
   flush at most once and only for the final read-back verification
   before the single commit.
9. The CLI prints only safe aggregate information: it never echoes
   a database URL, a phone number, a credential, a Twilio signature,
   a message body, raw caught exception text or any E.164
   destination. The fixture dataset itself contains no E.164
   destinations or any other forbidden identifier.
10. The apply path creates the locked catalog shape: 3 commerces,
    4 categories, 7 presentations, 30 products, 59 product-presentation
    associations and 59 prices per commerce, and the per-category
    presentation policy (pizzas → grande/chica, empanadas → unidad,
    beverages → lata/litro/2-litros, desserts → unidad/kilo).
11. The fixture apply path NEVER creates ``CanalWhatsapp``,
    ``ComercioCanalCompartido`` or ``Cliente`` rows.
12. The CLI is the sole owner of one setup transaction: a mid-apply
    failure rolls back the entire fixture set and leaves no partial
    rows behind.
13. The CLI flushes exactly once, then performs the exact
    post-flush verification on the same session, and only then
    commits. The order ``flush → verify → commit`` is observable.
14. If the exact post-flush verification returns ``False`` (or
    raises), the CLI rolls back its transaction and reports
    ``conflict`` without persisting any staged row.
15. Per-comercio corruption of categories/products, one incorrect
    association and one incorrect price all yield ``conflict`` in
    both verify and apply modes.
16. The exact re-run on the full fixture set returns ``ready``
    without mutating any row.

The tests use the live ``supernova_test`` PostgreSQL database. A
per-class ``setUpClass`` truncates every project data table
(CASCADE) and a per-class ``tearDownClass`` re-seeds the standard
``estado_comercio`` rows so other tests can run unaffected.
"""
from __future__ import annotations

import contextlib
import io
import unittest
from collections.abc import Iterator
from decimal import Decimal
from typing import Any, cast
from unittest import mock

from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session, sessionmaker

from backend.cli.seed_controlled_railway_fixtures import (
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
from backend.services.seed_controlled_railway_fixtures_data import (
    CATEGORY_FIXTURES,
    COMMERCE_ESTADO_CODIGO,
    COMMERCE_ESTADO_MODO,
    COMMERCE_FIXTURES,
    PRESENTATION_FIXTURES,
    PRESENTATIONS_BY_CATEGORY,
    expected_fixture_counts,
)
from backend.services.seed_controlled_railway_fixtures_service import (
    ControlledRailwayFixtureService,
    FixtureApplyMode,
    FixtureApplyStatus,
    build_service,
)

TEST_URL = "postgresql+psycopg:///supernova_test"

engine = create_engine(TEST_URL)
TestingSessionLocal = sessionmaker(
    bind=engine, autoflush=False, autocommit=False
)


_TRUNCATE_TABLES: tuple[str, ...] = (
    "estado_comercio",
    "comercios",
    "categorias_productos",
    "presentaciones",
    "productos",
    "producto_presentaciones",
    "producto_precios",
    "clientes",
    "canales_whatsapp",
    "comercios_canales_compartidos",
    "comercio_medios_pago",
    "comercio_metodos_entrega",
    "contextos_clientes_canales_whatsapp",
    "producto_aliases",
    "producto_presentacion_embeddings",
    "pedidos",
    "pedidos_productos",
    "mensajes_proveedor_salientes",
    "recepciones_mensajes_proveedor",
    "sessions",
    "medios_pago",
    "metodos_entrega",
)


def _truncate_all_data_tables() -> None:
    """Truncate every project data table with CASCADE.

    A single ``TRUNCATE ... CASCADE`` is the simplest way to wipe
    the schema in dependency order without enumerating every
    dependent table. The ``estado_comercio`` table is also
    truncated so the fixture CLI can verify the strict empty-target
    contract.
    """
    tables_sql = ", ".join(_TRUNCATE_TABLES)
    with engine.begin() as conn:
        conn.execute(
            text(f"TRUNCATE TABLE {tables_sql} RESTART IDENTITY CASCADE")
        )


def _reseed_estado_comercio_standard() -> None:
    """Re-seed the standard ``estado_comercio`` rows used by other tests.

    The seed mirrors the canonical lifecycle policy:

    * ACTIVO -> ``habilitado``, ``seleccionable=True``;
    * INACTIVO -> ``bloqueado``, ``seleccionable=True``;
    * PRUEBA -> ``prueba``, ``seleccionable=True``;
    * SUSPENDIDO / BAJA -> ``bloqueado``, ``seleccionable=False``.
    """
    rows: tuple[tuple[str, str, bool], ...] = (
        ("ACTIVO", "habilitado", True),
        ("INACTIVO", "bloqueado", True),
        ("PRUEBA", "prueba", True),
        ("SUSPENDIDO", "bloqueado", False),
        ("BAJA", "bloqueado", False),
    )
    with engine.begin() as conn:
        for codigo, modo, seleccionable in rows:
            conn.execute(
                text(
                    "INSERT INTO estado_comercio "
                    "(codigo, descripcion, modo_operacion, seleccionable) "
                    "VALUES (:codigo, :codigo, CAST(:modo AS "
                    "estado_comercio_modo_operacion), :seleccionable)"
                ),
                {
                    "codigo": codigo,
                    "modo": modo,
                    "seleccionable": bool(seleccionable),
                },
            )


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


def _count(session: Session, model: type[Any]) -> int:
    return int(session.execute(select(func.count()).select_from(model)).scalar_one())


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


@contextlib.contextmanager
def _open_inspection_session() -> Iterator[Session]:
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


def _catalog_row_counts_in_context() -> dict[str, int]:
    with _open_inspection_session() as session:
        return _catalog_row_counts(session)


@contextlib.contextmanager
def _capture_streams() -> Any:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(
        stderr
    ):
        yield stdout, stderr


class _SessionFactorySpy:
    def __init__(self) -> None:
        self.open_calls = 0

    def __call__(self) -> Session:
        self.open_calls += 1
        return TestingSessionLocal()


class _OrderSpyFactory:
    """Test session factory that records the exact order of
    ``flush``, ``verify`` and ``commit`` events for the CLI.

    The factory wraps the returned session's ``commit`` method with
    a thin spy that appends ``"commit"`` to a shared event list and
    then delegates to the original ``commit``. This lets the focused
    order test assert the exact sequence
    ``flush → verify → commit`` that the locked contract requires.
    """

    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.open_calls = 0
        self.commit_calls = 0

    def __call__(self) -> Session:
        self.open_calls += 1
        session = TestingSessionLocal()
        original_commit = session.commit

        def _tracked_commit() -> Any:
            self.events.append("commit")
            self.commit_calls += 1
            return original_commit()

        session.commit = _tracked_commit  # type: ignore[method-assign]
        return session


class ControlledRailwayFixtureCliTest(unittest.TestCase):
    """End-to-end coverage of the controlled Railway fixture CLI."""

    @classmethod
    def setUpClass(cls) -> None:
        _truncate_all_data_tables()
        _reseed_estado_comercio_standard()

    @classmethod
    def tearDownClass(cls) -> None:
        _truncate_all_data_tables()
        _reseed_estado_comercio_standard()

    def setUp(self) -> None:
        _truncate_all_data_tables()

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

    def test_railway_without_estado_comercio_verify_not_ready(self) -> None:
        before = _catalog_row_counts_in_context()
        for value in before.values():
            self.assertEqual(value, 0)

        with _capture_streams() as (stdout, _stderr):
            exit_code = main(
                argv=[],
                session_factory=_SessionFactorySpy(),
            )

        self.assertEqual(exit_code, EXIT_NOT_READY)
        rendered = stdout.getvalue()
        self.assertIn(
            f"status={FixtureApplyStatus.NOT_READY.value}", rendered
        )
        self.assertIn("mode=verify", rendered)
        self.assertIn("detalle=empty_target", rendered)
        after = _catalog_row_counts_in_context()
        self.assertEqual(before, after)
        self.assertNotIn(TEST_URL, rendered)
        self.assertNotIn("postgresql", rendered)

    def test_railway_without_estado_comercio_apply_creates_activo(self) -> None:
        before = _catalog_row_counts_in_context()
        for value in before.values():
            self.assertEqual(value, 0)

        with _capture_streams() as (stdout, stderr):
            exit_code = main(
                argv=["--apply"],
                session_factory=_SessionFactorySpy(),
            )
        self.assertEqual(exit_code, EXIT_OK)
        rendered = stdout.getvalue()
        self.assertIn(
            f"status={FixtureApplyStatus.PROVISIONED.value}", rendered
        )
        self.assertIn("mode=apply", rendered)
        self.assertIn("counts=comercios=3", rendered)
        self.assertIn("categorias=4", rendered)
        self.assertIn("presentaciones=7", rendered)
        self.assertIn("productos=30", rendered)
        self.assertIn("producto_presentaciones=59", rendered)
        self.assertIn("precios=59", rendered)
        self.assertIn("comercio_ids=", rendered)
        self.assertEqual(stderr.getvalue(), "")

        with _open_inspection_session() as session:
            actual = _catalog_row_counts(session)
        expected = self._expected_catalog_counts()
        for table, count in expected.items():
            self.assertEqual(
                actual[table],
                count,
                f"table {table}: expected {count} got {actual[table]}",
            )
        self.assertEqual(actual["estado_comercio"], 1)

        with _open_inspection_session() as session:
            estado = session.execute(
                select(EstadoComercio).where(
                    EstadoComercio.codigo == COMMERCE_ESTADO_CODIGO
                )
            ).scalar_one()
            self.assertIsNotNone(estado)
            estado_id_value = cast(int, estado.id)
            self.assertEqual(estado_id_value, 1)

    def test_apply_on_pre_existing_data_returns_conflict(self) -> None:
        with TestingSessionLocal() as session, session.begin():
            estado = session.execute(
                select(EstadoComercio).where(
                    EstadoComercio.codigo == COMMERCE_ESTADO_CODIGO
                )
            ).scalar_one_or_none()
            if estado is None:
                estado = _make_estado(COMMERCE_ESTADO_CODIGO, modo=COMMERCE_ESTADO_MODO, seleccionable=True)
                session.add(estado)
                session.flush()
            estado_id_value = cast(int, estado.id)
            session.add(
                Comercio(
                    nombre_fantasia="Comercio Externo",
                    nombre_corto="Comercio Externo",
                    razon_social="Comercio Externo SRL",
                    cuit="30-99999999-9",
                    whatsapp="FIXTURE:EXTERNO",
                    calle="Av. Externa",
                    numero="1",
                    piso_departamento=None,
                    localidad="CABA",
                    provincia="Buenos Aires",
                    codigo_postal="C1000",
                    slug="comercio-externo",
                    estado_id=estado_id_value,
                )
            )

        before = _catalog_row_counts_in_context()
        with _capture_streams() as (stdout, _stderr):
            exit_code = main(
                argv=["--apply"], session_factory=_SessionFactorySpy()
            )
        self.assertEqual(exit_code, EXIT_NOT_READY)
        rendered = stdout.getvalue()
        self.assertIn(
            f"status={FixtureApplyStatus.CONFLICT.value}", rendered
        )
        self.assertIn("detalle=pre_existing_data", rendered)
        after = _catalog_row_counts_in_context()
        self.assertEqual(before, after)

    def test_verify_on_pre_existing_data_returns_conflict(self) -> None:
        with TestingSessionLocal() as session, session.begin():
            estado = session.execute(
                select(EstadoComercio).where(
                    EstadoComercio.codigo == COMMERCE_ESTADO_CODIGO
                )
            ).scalar_one_or_none()
            if estado is None:
                estado = _make_estado(COMMERCE_ESTADO_CODIGO, modo=COMMERCE_ESTADO_MODO, seleccionable=True)
                session.add(estado)
                session.flush()
            estado_id_value = cast(int, estado.id)
            session.add(
                Comercio(
                    nombre_fantasia="Otro Comercio",
                    nombre_corto="Otro",
                    razon_social="Otro SRL",
                    cuit="30-88888888-8",
                    whatsapp="FIXTURE:OTRO",
                    calle="Av. Otra",
                    numero="2",
                    piso_departamento=None,
                    localidad="CABA",
                    provincia="Buenos Aires",
                    codigo_postal="C1000",
                    slug="otro-comercio",
                    estado_id=estado_id_value,
                )
            )
        with _capture_streams() as (stdout, _stderr):
            exit_code = main(
                argv=[], session_factory=_SessionFactorySpy()
            )
        self.assertEqual(exit_code, EXIT_NOT_READY)
        rendered = stdout.getvalue()
        self.assertIn(
            f"status={FixtureApplyStatus.CONFLICT.value}", rendered
        )

    def test_apply_does_not_create_transport_routing(self) -> None:
        with _capture_streams() as (_stdout, _stderr):
            main(argv=["--apply"], session_factory=_SessionFactorySpy())
        with _open_inspection_session() as session:
            self.assertEqual(_count(session, CanalWhatsapp), 0)
            self.assertEqual(_count(session, ComercioCanalCompartido), 0)
            self.assertEqual(_count(session, Cliente), 0)

    def test_pre_existing_activo_estado_returns_conflict_without_mutation(
        self,
    ) -> None:
        with TestingSessionLocal() as session, session.begin():
            session.add(_make_estado(COMMERCE_ESTADO_CODIGO, modo=COMMERCE_ESTADO_MODO, seleccionable=True))

        before = _catalog_row_counts_in_context()
        self.assertEqual(before["estado_comercio"], 1)
        self.assertEqual(before["comercios"], 0)

        with _capture_streams() as (stdout, stderr):
            verify_exit = main(
                argv=[], session_factory=_SessionFactorySpy()
            )
        self.assertEqual(verify_exit, EXIT_NOT_READY)
        verify_rendered = stdout.getvalue()
        self.assertIn(
            f"status={FixtureApplyStatus.CONFLICT.value}", verify_rendered
        )
        self.assertEqual(stderr.getvalue(), "")
        after_verify = _catalog_row_counts_in_context()
        self.assertEqual(before, after_verify)

        with _capture_streams() as (stdout, stderr):
            apply_exit = main(
                argv=["--apply"], session_factory=_SessionFactorySpy()
            )
        self.assertEqual(apply_exit, EXIT_NOT_READY)
        apply_rendered = stdout.getvalue()
        self.assertIn(
            f"status={FixtureApplyStatus.CONFLICT.value}", apply_rendered
        )
        self.assertEqual(stderr.getvalue(), "")
        after_apply = _catalog_row_counts_in_context()
        self.assertEqual(before, after_apply)

    def test_pre_existing_non_activo_estado_returns_conflict_without_mutation(
        self,
    ) -> None:
        with TestingSessionLocal() as session, session.begin():
            session.add(
                _make_estado(
                    "INACTIVO",
                    modo="bloqueado",
                    seleccionable=True,
                )
            )

        before = _catalog_row_counts_in_context()
        self.assertEqual(before["estado_comercio"], 1)
        self.assertEqual(before["comercios"], 0)

        with _open_inspection_session() as session:
            estados = session.execute(
                select(EstadoComercio.codigo)
            ).all()
        self.assertEqual(
            [row[0] for row in estados], ["INACTIVO"]
        )
        self.assertNotIn(COMMERCE_ESTADO_CODIGO, [row[0] for row in estados])

        with _capture_streams() as (stdout, stderr):
            verify_exit = main(
                argv=[], session_factory=_SessionFactorySpy()
            )
        self.assertEqual(verify_exit, EXIT_NOT_READY)
        verify_rendered = stdout.getvalue()
        self.assertIn(
            f"status={FixtureApplyStatus.CONFLICT.value}", verify_rendered
        )
        self.assertEqual(stderr.getvalue(), "")
        after_verify = _catalog_row_counts_in_context()
        self.assertEqual(before, after_verify)

        with _capture_streams() as (stdout, stderr):
            apply_exit = main(
                argv=["--apply"], session_factory=_SessionFactorySpy()
            )
        self.assertEqual(apply_exit, EXIT_NOT_READY)
        apply_rendered = stdout.getvalue()
        self.assertIn(
            f"status={FixtureApplyStatus.CONFLICT.value}", apply_rendered
        )
        self.assertEqual(stderr.getvalue(), "")
        after_apply = _catalog_row_counts_in_context()
        self.assertEqual(before, after_apply)

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

        before = _catalog_row_counts_in_context()
        for value in before.values():
            self.assertEqual(value, 0)

        spy = _OrderSpyFactory(events)

        with _capture_streams() as (stdout, stderr):
            exit_code = main(
                argv=["--apply"],
                session_factory=spy,
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

        expected = self._expected_catalog_counts()
        with _open_inspection_session() as session:
            actual = _catalog_row_counts(session)
        self.assertEqual(actual["estado_comercio"], 1)
        for table, count in expected.items():
            self.assertEqual(
                actual[table],
                count,
                f"table {table}: expected {count} got {actual[table]}",
            )

    def test_cli_post_flush_verification_failure_triggers_rollback(self) -> None:
        before = _catalog_row_counts_in_context()
        for value in before.values():
            self.assertEqual(value, 0)

        flush_calls: list[str] = []
        verify_calls: list[bool] = []

        def _record_flush(reason: str) -> None:
            flush_calls.append(reason)

        def _record_verify(ok: bool) -> None:
            verify_calls.append(ok)

        with mock.patch.object(
            ControlledRailwayFixtureService,
            "verify_staged_dataset_is_exact",
            autospec=True,
        ) as mock_verify:
            mock_verify.return_value = False
            with _capture_streams() as (stdout, stderr):
                exit_code = main(
                    argv=["--apply"],
                    session_factory=_OrderSpyFactory([]),
                    flush_recorder=_record_flush,
                    verification_recorder=_record_verify,
                )

        self.assertEqual(exit_code, EXIT_NOT_READY)
        self.assertEqual(flush_calls, ["apply"])
        self.assertEqual(verify_calls, [False])
        rendered = stdout.getvalue()
        self.assertIn(
            f"status={FixtureApplyStatus.CONFLICT.value}", rendered
        )
        self.assertIn("detalle=post_flush_verification_failed", rendered)
        self.assertEqual(stderr.getvalue(), "")

        after = _catalog_row_counts_in_context()
        self.assertEqual(before, after)

    def test_fixture_shape_matches_design(self) -> None:
        with _capture_streams() as (_stdout, _stderr):
            main(argv=["--apply"], session_factory=_SessionFactorySpy())
        with _open_inspection_session() as session:
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
                select(CategoriaProducto.id_comercio, CategoriaProducto.descripcion)
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

    def test_apply_rolls_back_on_mid_apply_failure(self) -> None:
        before = _catalog_row_counts_in_context()
        with mock.patch.object(
            ControlledRailwayFixtureService,
            "_stage_fixture_dataset",
            autospec=True,
            side_effect=RuntimeError("simulated staging failure"),
        ):
            with _capture_streams() as (stdout, _stderr):
                exit_code = main(
                    argv=["--apply"],
                    session_factory=_SessionFactorySpy(),
                )
        self.assertEqual(exit_code, EXIT_TECHNICAL_FAILURE)
        rendered = stdout.getvalue()
        self.assertIn(
            FixtureApplyStatus.TECHNICAL_FAILURE.value, rendered
        )
        self.assertIn("RuntimeError", rendered)
        after = _catalog_row_counts_in_context()
        self.assertEqual(before, after)

    def test_output_never_echoes_secrets_or_e164(self) -> None:
        with _capture_streams() as (_stdout, _stderr):
            main(argv=["--apply"], session_factory=_SessionFactorySpy())
        with _capture_streams() as (stdout, stderr):
            exit_code = main(
                argv=[], session_factory=_SessionFactorySpy()
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
        )
        for token in forbidden:
            self.assertNotIn(token, rendered)

    def test_unexpected_session_failure_returns_exit_code_one(self) -> None:
        class _BrokenSessionFactory:
            def __call__(self) -> Session:
                raise RuntimeError(
                    "secret-cliente-e164 db=postgresql"
                )

        with _capture_streams() as (stdout, stderr):
            exit_code = main(
                argv=[],
                session_factory=_BrokenSessionFactory(),
            )
        self.assertEqual(exit_code, EXIT_TECHNICAL_FAILURE)
        rendered = stdout.getvalue() + stderr.getvalue()
        self.assertIn(
            FixtureApplyStatus.TECHNICAL_FAILURE.value, rendered
        )
        for forbidden in (
            "secret-cliente-e164",
            "postgresql",
            "+5491100000001",
        ):
            self.assertNotIn(forbidden, rendered)

    def test_fixture_data_contains_no_e164_or_secrets(self) -> None:
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

    def test_cli_single_flush_and_zero_in_service_and_helpers(self) -> None:
        flush_calls: list[str] = []

        def _record(reason: str) -> None:
            flush_calls.append(reason)

        spy = _SessionFactorySpy()
        with _capture_streams() as (stdout, stderr):
            main(
                argv=["--apply"],
                session_factory=spy,
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

    def test_service_does_not_flush_or_commit_during_apply(self) -> None:
        with _truncate_then_apply_recording_session() as (
            session,
            flush_calls,
            commit_calls,
            rollback_calls,
        ):
            service = build_service(session)
            result = service.apply()
        self.assertEqual(result.status, FixtureApplyStatus.PROVISIONED)
        self.assertEqual(flush_calls, [])
        self.assertEqual(commit_calls, [])
        self.assertEqual(rollback_calls, [])

    def test_service_does_not_flush_or_commit_during_verify(self) -> None:
        with _truncate_then_apply_recording_session() as (
            session,
            flush_calls,
            commit_calls,
            rollback_calls,
        ):
            service = build_service(session)
            result = service.verify()
        self.assertEqual(result.status, FixtureApplyStatus.NOT_READY)
        self.assertEqual(flush_calls, [])
        self.assertEqual(commit_calls, [])
        self.assertEqual(rollback_calls, [])

    def test_exact_rerun_returns_ready_without_mutation(self) -> None:
        with _capture_streams() as (_stdout, _stderr):
            first_exit = main(
                argv=["--apply"], session_factory=_SessionFactorySpy()
            )
        self.assertEqual(first_exit, EXIT_OK)

        before = _catalog_row_counts_in_context()
        flush_calls: list[str] = []

        def _record(reason: str) -> None:
            flush_calls.append(reason)

        with _capture_streams() as (stdout, stderr):
            second_exit = main(
                argv=["--apply"],
                session_factory=_SessionFactorySpy(),
                flush_recorder=_record,
            )
        self.assertEqual(second_exit, EXIT_OK)
        rendered = stdout.getvalue()
        self.assertIn(
            f"status={FixtureApplyStatus.READY.value}", rendered
        )
        self.assertIn("detalle=exact_match", rendered)
        self.assertEqual(flush_calls, [])
        self.assertEqual(stderr.getvalue(), "")
        after = _catalog_row_counts_in_context()
        self.assertEqual(before, after)

    def test_per_comercio_category_corruption_returns_conflict(self) -> None:
        self._seed_full_fixture()
        with _open_inspection_session() as session, session.begin():
            target = session.execute(
                select(CategoriaProducto)
                .join(Comercio, Comercio.id == CategoriaProducto.id_comercio)
                .where(Comercio.slug == "piloto-whatsapp-dedicado")
                .order_by(CategoriaProducto.id)
                .limit(1)
            ).scalar_one()
            target.descripcion = "Categoria Corrupta"
        with _capture_streams() as (stdout, _stderr):
            verify_exit = main(
                argv=[], session_factory=_SessionFactorySpy()
            )
        self.assertEqual(verify_exit, EXIT_NOT_READY)
        self.assertIn(
            f"status={FixtureApplyStatus.CONFLICT.value}", stdout.getvalue()
        )
        with _capture_streams() as (stdout, _stderr):
            apply_exit = main(
                argv=["--apply"], session_factory=_SessionFactorySpy()
            )
        self.assertEqual(apply_exit, EXIT_NOT_READY)
        self.assertIn(
            f"status={FixtureApplyStatus.CONFLICT.value}", stdout.getvalue()
        )

    def test_per_comercio_product_corruption_returns_conflict(self) -> None:
        self._seed_full_fixture()
        with _open_inspection_session() as session, session.begin():
            target = session.execute(
                select(Producto)
                .join(CategoriaProducto)
                .join(Comercio)
                .where(Comercio.slug == "piloto-whatsapp-compartido-uno")
                .order_by(Producto.id)
                .limit(1)
            ).scalar_one()
            target.nombre = "Producto Corrupto"
        with _capture_streams() as (stdout, _stderr):
            verify_exit = main(
                argv=[], session_factory=_SessionFactorySpy()
            )
        self.assertEqual(verify_exit, EXIT_NOT_READY)
        self.assertIn(
            f"status={FixtureApplyStatus.CONFLICT.value}", stdout.getvalue()
        )
        with _capture_streams() as (stdout, _stderr):
            apply_exit = main(
                argv=["--apply"], session_factory=_SessionFactorySpy()
            )
        self.assertEqual(apply_exit, EXIT_NOT_READY)
        self.assertIn(
            f"status={FixtureApplyStatus.CONFLICT.value}", stdout.getvalue()
        )

    def test_one_wrong_association_returns_conflict(self) -> None:
        self._seed_full_fixture()
        with _open_inspection_session() as session, session.begin():
            target = session.execute(
                select(Producto)
                .join(CategoriaProducto)
                .join(Comercio)
                .where(
                    Comercio.slug == "piloto-whatsapp-compartido-dos",
                    CategoriaProducto.descripcion == "Pizzas",
                    Producto.nombre == "Mozzarella",
                )
                .limit(1)
            ).scalar_one()
            empanadas = session.execute(
                select(CategoriaProducto)
                .join(Comercio)
                .where(
                    Comercio.slug == "piloto-whatsapp-compartido-dos",
                    CategoriaProducto.descripcion == "Empanadas",
                )
                .limit(1)
            ).scalar_one()
            empanadas_id = cast(int, empanadas.id)
            target.id_categoria_producto = empanadas_id
        with _capture_streams() as (stdout, _stderr):
            verify_exit = main(
                argv=[], session_factory=_SessionFactorySpy()
            )
        self.assertEqual(verify_exit, EXIT_NOT_READY)
        self.assertIn(
            f"status={FixtureApplyStatus.CONFLICT.value}", stdout.getvalue()
        )
        with _capture_streams() as (stdout, _stderr):
            apply_exit = main(
                argv=["--apply"], session_factory=_SessionFactorySpy()
            )
        self.assertEqual(apply_exit, EXIT_NOT_READY)
        self.assertIn(
            f"status={FixtureApplyStatus.CONFLICT.value}", stdout.getvalue()
        )

    def test_one_wrong_price_returns_conflict(self) -> None:
        self._seed_full_fixture()
        with _open_inspection_session() as session, session.begin():
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
                .where(Comercio.slug == "piloto-whatsapp-dedicado")
                .order_by(Precio.id)
                .limit(1)
            ).scalar_one()
            target.precio = Decimal("99999.99")
        with _capture_streams() as (stdout, _stderr):
            verify_exit = main(
                argv=[], session_factory=_SessionFactorySpy()
            )
        self.assertEqual(verify_exit, EXIT_NOT_READY)
        self.assertIn(
            f"status={FixtureApplyStatus.CONFLICT.value}", stdout.getvalue()
        )
        with _capture_streams() as (stdout, _stderr):
            apply_exit = main(
                argv=["--apply"], session_factory=_SessionFactorySpy()
            )
        self.assertEqual(apply_exit, EXIT_NOT_READY)
        self.assertIn(
            f"status={FixtureApplyStatus.CONFLICT.value}", stdout.getvalue()
        )

    def test_content_moved_between_comercios_returns_conflict(self) -> None:
        self._seed_full_fixture()
        with _open_inspection_session() as session, session.begin():
            target = session.execute(
                select(CategoriaProducto)
                .join(Comercio, Comercio.id == CategoriaProducto.id_comercio)
                .where(
                    Comercio.slug == "piloto-whatsapp-compartido-uno",
                    CategoriaProducto.descripcion == "Postres",
                )
                .limit(1)
            ).scalar_one()
            target.descripcion = "Postres Movidos"
        with _capture_streams() as (stdout, _stderr):
            verify_exit = main(
                argv=[], session_factory=_SessionFactorySpy()
            )
        self.assertEqual(verify_exit, EXIT_NOT_READY)
        self.assertIn(
            f"status={FixtureApplyStatus.CONFLICT.value}", stdout.getvalue()
        )
        with _capture_streams() as (stdout, _stderr):
            apply_exit = main(
                argv=["--apply"], session_factory=_SessionFactorySpy()
            )
        self.assertEqual(apply_exit, EXIT_NOT_READY)
        self.assertIn(
            f"status={FixtureApplyStatus.CONFLICT.value}", stdout.getvalue()
        )

    def _seed_full_fixture(self) -> None:
        with _capture_streams() as (_stdout, _stderr):
            exit_code = main(
                argv=["--apply"], session_factory=_SessionFactorySpy()
            )
        self.assertEqual(exit_code, EXIT_OK)


@contextlib.contextmanager
def _truncate_then_apply_recording_session() -> Iterator[tuple[Session, list[str], list[str], list[str]]]:
    _truncate_all_data_tables()
    flush_calls: list[str] = []
    commit_calls: list[str] = []
    rollback_calls: list[str] = []
    session = TestingSessionLocal()
    try:
        with mock.patch.object(
            session, "flush", autospec=True
        ) as flush, mock.patch.object(
            session, "commit", autospec=True
        ) as commit, mock.patch.object(
            session, "rollback", autospec=True
        ) as rollback, mock.patch.object(
            session, "begin", autospec=True
        ) as begin:
            flush.side_effect = lambda *a, **kw: flush_calls.append("flush")
            commit.side_effect = lambda *a, **kw: commit_calls.append("commit")
            rollback.side_effect = lambda *a, **kw: rollback_calls.append("rollback")
            begin.side_effect = lambda *a, **kw: None
            yield session, flush_calls, commit_calls, rollback_calls
    finally:
        session.close()


class StagingServiceNoTransactionControlTest(unittest.TestCase):
    """The staging service must not call commit/rollback/begin/flush."""

    @classmethod
    def setUpClass(cls) -> None:
        _truncate_all_data_tables()
        _reseed_estado_comercio_standard()

    @classmethod
    def tearDownClass(cls) -> None:
        _truncate_all_data_tables()
        _reseed_estado_comercio_standard()

    def setUp(self) -> None:
        _truncate_all_data_tables()

    def test_verify_does_not_call_commit_rollback_begin_or_flush(self) -> None:
        with _open_inspection_session() as session:
            with mock.patch.object(
                session, "commit"
            ) as commit, mock.patch.object(
                session, "rollback"
            ) as rollback, mock.patch.object(
                session, "begin"
            ) as begin, mock.patch.object(
                session, "flush"
            ) as flush:
                service = build_service(session)
                result = service.verify()
        self.assertEqual(result.mode, FixtureApplyMode.VERIFY)
        commit.assert_not_called()
        rollback.assert_not_called()
        begin.assert_not_called()
        flush.assert_not_called()

    def test_apply_does_not_call_commit_rollback_begin_or_flush(self) -> None:
        with _open_inspection_session() as session:
            with mock.patch.object(
                session, "commit"
            ) as commit, mock.patch.object(
                session, "rollback"
            ) as rollback, mock.patch.object(
                session, "begin"
            ) as begin, mock.patch.object(
                session, "flush"
            ) as flush:
                service = build_service(session)
                result = service.apply()
        self.assertEqual(result.mode, FixtureApplyMode.APPLY)
        commit.assert_not_called()
        rollback.assert_not_called()
        begin.assert_not_called()
        flush.assert_not_called()

    def test_apply_releases_staged_state_on_session_close(self) -> None:
        before = _catalog_row_counts_in_context()
        with TestingSessionLocal() as session:
            service = build_service(session)
            service.apply()
            session.close()
        after = _catalog_row_counts_in_context()
        self.assertEqual(before, after)


class CliParserTest(unittest.TestCase):
    def test_help_lists_required_flags(self) -> None:
        parser = build_parser()
        help_text = parser.format_help()
        self.assertIn("--apply", help_text)
        self.assertIn("--verify-only", help_text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
