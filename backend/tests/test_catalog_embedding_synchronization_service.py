"""Focused tests for the catalog-embedding synchronization service.

Subphase 4.8 wires the existing 4.6 indexer / seeder pipeline to every
catalog mutation boundary through ``CatalogEmbeddingSynchronizationService``.
The tests exercise the five scope entry points, the per-call
``SeedingResult`` aggregation, the embedding-relevance gating at the
caller boundary, the recoverable vs unhandled failure handling, the
post-delete scope capture for ``ProductoAliasService.delete``, and the
read-only scope-resolution repository methods.

The tests reuse the project's live ``supernova_test`` PostgreSQL
database so the parent chain joins and the SQLAlchemy session state
match production. A fake ``EmbeddingClientProtocol`` is injected so
no real Ollama call is made. The tests do NOT depend on the manual
reindex endpoint or the admin endpoint.
"""
from __future__ import annotations

import unittest
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import create_engine, delete, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from backend.config.settings import Settings
from backend.llm.embedding_client import (
    EmbeddingClientProtocol,
    EmbeddingConnectionError,
)
from backend.models import (
    CategoriaProducto,
    Comercio,
    EstadoComercio,
    Precio,
    Presentacion,
    Producto,
    ProductoAlias,
    ProductoPresentacion,
    ProductoPresentacionEmbedding,
)
from backend.repositories.producto_presentacion_embedding_index_repository import (
    ProductoPresentacionEmbeddingIndexRepository,
)
from backend.services.catalog_embedding_synchronization_service import (
    CatalogEmbeddingSynchronizationService,
)
from backend.services.embedding_synchronization_result import (
    EmbeddingSynchronizationResult,
    empty_result,
    synchronization_failed_result,
)
from backend.services.producto_presentacion_embedding_indexer import (
    ProductoPresentacionEmbeddingIndexer,
)
from backend.services.producto_presentacion_embedding_seeder import (
    ProductoPresentacionEmbeddingSeeder,
)
from backend.services.producto_presentacion_embedding_service import (
    ProductoPresentacionEmbeddingService,
)
from backend.services.producto_alias_service import ProductoAliasService

TEST_URL = "postgresql+psycopg:///supernova_test"

engine = create_engine(TEST_URL)
TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


# -- Fixtures -------------------------------------------------------------


def _suffix() -> str:
    return uuid.uuid4().hex[:10]


def _estado_id_activo() -> int:
    with engine.connect() as c:
        row = c.execute(
            select(EstadoComercio.id).where(EstadoComercio.estado == "ACTIVO")
        ).first()
        if row is None:
            raise RuntimeError("estado ACTIVO not seeded in supernova_test")
        return row[0]


def _seed_two_productos_two_categorias() -> dict:
    """Seed one comercio with two categorias and two productos each owning
    two presentations. Returns a stable mapping of ids."""
    suffix = _suffix()
    with TestingSessionLocal() as session, session.begin():
        comercio = Comercio(
            nombre_fantasia=f"Sync Test {suffix}",
            nombre_corto=f"ST {suffix}",
            razon_social=f"Sync Test SRL {suffix}",
            cuit=f"30-{suffix[:8]}-{suffix[8]}",
            whatsapp=f"+54911{suffix[:8]}",
            calle="Av. Sync",
            numero="321",
            piso_departamento=None,
            localidad="CABA",
            provincia="Buenos Aires",
            codigo_postal="C1000",
            slug=f"sync-test-{suffix}",
            estado_id=_estado_id_activo(),
        )
        session.add(comercio)
        session.flush()
        comercio_id = int(comercio.id)

        cat_a = CategoriaProducto(
            id_comercio=comercio_id,
            descripcion=f"Pizzas {suffix}",
            activo=True,
            orden=0,
        )
        cat_b = CategoriaProducto(
            id_comercio=comercio_id,
            descripcion=f"Empanadas {suffix}",
            activo=True,
            orden=1,
        )
        session.add_all([cat_a, cat_b])
        session.flush()
        cat_a_id = int(cat_a.id)
        cat_b_id = int(cat_b.id)

        presentacion_chica = Presentacion(
            id_comercio=comercio_id,
            codigo=f"chica-{suffix}",
            descripcion=f"Chica {suffix}",
            activo=True,
            orden=0,
        )
        presentacion_grande = Presentacion(
            id_comercio=comercio_id,
            codigo=f"grande-{suffix}",
            descripcion=f"Grande {suffix}",
            orden=1,
            activo=True,
        )
        session.add_all([presentacion_chica, presentacion_grande])
        session.flush()
        presentacion_chica_id = int(presentacion_chica.id)
        presentacion_grande_id = int(presentacion_grande.id)

        producto_a = Producto(
            id_categoria_producto=cat_a_id,
            nombre=f"Pizza Muzza {suffix}",
            descripcion=None,
            activo=True,
            disponible=True,
            orden=0,
        )
        producto_b = Producto(
            id_categoria_producto=cat_a_id,
            nombre=f"Pizza Fugazzeta {suffix}",
            descripcion=None,
            activo=True,
            disponible=True,
            orden=1,
        )
        producto_c = Producto(
            id_categoria_producto=cat_b_id,
            nombre=f"Empanada Carne {suffix}",
            descripcion=None,
            activo=True,
            disponible=True,
            orden=0,
        )
        session.add_all([producto_a, producto_b, producto_c])
        session.flush()
        producto_a_id = int(producto_a.id)
        producto_b_id = int(producto_b.id)
        producto_c_id = int(producto_c.id)

        # Two presentations for producto_a, two for producto_b, one for producto_c.
        pps: list[ProductoPresentacion] = []
        for pid in (producto_a_id, producto_b_id):
            for pp_id in (presentacion_chica_id, presentacion_grande_id):
                pp = ProductoPresentacion(
                    id_producto=pid,
                    id_presentacion=pp_id,
                    activo=True,
                    orden=0,
                )
                pps.append(pp)
        pp_c_chica = ProductoPresentacion(
            id_producto=producto_c_id,
            id_presentacion=presentacion_chica_id,
            activo=True,
            orden=0,
        )
        pps.append(pp_c_chica)
        session.add_all(pps)
        session.flush()

        pp_a_chica_id = int(pps[0].id)
        pp_a_grande_id = int(pps[1].id)
        pp_b_chica_id = int(pps[2].id)
        pp_b_grande_id = int(pps[3].id)
        pp_c_chica_id = int(pps[4].id)

    return {
        "comercio_id": comercio_id,
        "cat_a_id": cat_a_id,
        "cat_b_id": cat_b_id,
        "producto_a_id": producto_a_id,
        "producto_b_id": producto_b_id,
        "producto_c_id": producto_c_id,
        "presentacion_chica_id": presentacion_chica_id,
        "presentacion_grande_id": presentacion_grande_id,
        "pp_a_chica_id": pp_a_chica_id,
        "pp_a_grande_id": pp_a_grande_id,
        "pp_b_chica_id": pp_b_chica_id,
        "pp_b_grande_id": pp_b_grande_id,
        "pp_c_chica_id": pp_c_chica_id,
        "suffix": suffix,
    }


def _delete_comercio(comercio_id: int) -> None:
    with TestingSessionLocal() as session, session.begin():
        producto_ids = session.execute(
            select(Producto.id).where(
                Producto.id_categoria_producto.in_(
                    select(CategoriaProducto.id).where(
                        CategoriaProducto.id_comercio == comercio_id
                    )
                )
            )
        ).scalars()
        producto_ids = list(producto_ids)
        pp_ids = session.execute(
            select(ProductoPresentacion.id).where(
                ProductoPresentacion.id_producto.in_(producto_ids)
            )
        ).scalars()
        pp_ids = list(pp_ids)
        session.execute(
            delete(ProductoPresentacionEmbedding).where(
                ProductoPresentacionEmbedding.id_producto_presentacion.in_(pp_ids)
            )
        )
        session.execute(
            delete(ProductoAlias).where(
                ProductoAlias.id_producto.in_(producto_ids)
            )
        )
        session.execute(delete(Precio).where(Precio.id_producto_presentacion.in_(pp_ids)))
        session.execute(
            delete(ProductoPresentacion).where(
                ProductoPresentacion.id_producto.in_(producto_ids)
            )
        )
        session.execute(delete(Producto).where(Producto.id.in_(producto_ids)))
        session.execute(
            delete(CategoriaProducto).where(
                CategoriaProducto.id_comercio == comercio_id
            )
        )
        session.execute(delete(Presentacion).where(Presentacion.id_comercio == comercio_id))
        session.execute(delete(Comercio).where(Comercio.id == comercio_id))


# -- Fake embedding client -------------------------------------------------


@dataclass
class _FakeEmbeddingClient:
    """Programmable fake implementing ``EmbeddingClientProtocol``."""

    vectors: dict[str, list[float]] | None = None
    raise_for: set[str] | None = None
    call_count: int = 0

    def __post_init__(self) -> None:
        if self.vectors is None:
            self.vectors = {}
        if self.raise_for is None:
            self.raise_for = set()

    def embed_query(self, text: str) -> list[float]:
        return self._vector_for(text)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.call_count += 1
        for text in texts:
            for needle in self.raise_for or set():
                if needle in text:
                    raise EmbeddingConnectionError(
                        f"fake connection error for {needle!r}"
                    )
        return [self._vector_for(text) for text in texts]

    def _vector_for(self, text: str) -> list[float]:
        if text in self.vectors:
            return self.vectors[text]
        return [0.0] * 384


def _settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "llm_url": "http://llm.test/api/generate",
        "llm_model": "test-llm",
        "llm_timeout": 30,
        "llm_keep_alive": "1h",
        "llm_num_ctx": 2048,
        "llm_num_predict": 256,
        "llm_log_content": False,
        "llm_log_max_chars": 50,
        "embedding_url": "http://embed.test/api/embed",
        "embedding_model": "all-minilm:latest",
        "embedding_timeout_seconds": 15,
        "embedding_batch_size": 32,
        "embedding_dimension": 384,
    }
    base.update(overrides)
    return Settings(**base)


def _build_sync_service(
    session: Session,
    *,
    client: EmbeddingClientProtocol,
    settings: Settings,
) -> CatalogEmbeddingSynchronizationService:
    return CatalogEmbeddingSynchronizationService(
        session=session,
        embedding_client=client,
        settings=settings,
    )


def _add_alias(
    session: Session,
    *,
    id_producto: int,
    id_producto_presentacion: int | None,
    alias: str,
) -> ProductoAlias:
    row = ProductoAlias(
        id_producto=id_producto,
        id_producto_presentacion=id_producto_presentacion,
        alias=alias,
        alias_normalizado=alias,
        activo=True,
    )
    session.add(row)
    session.flush()
    return row


# -- Tests -----------------------------------------------------------------


class ScopeResolutionRepositoryTest(unittest.TestCase):
    """The scope-resolution repository methods must return ``list[int]``
    only and never call commit/rollback/close/begin."""

    def setUp(self) -> None:
        self.fixtures = _seed_two_productos_two_categorias()
        self.addCleanup(_delete_comercio, self.fixtures["comercio_id"])

    def test_list_ids_by_producto_returns_only_matching(self) -> None:
        with TestingSessionLocal() as session, session.begin():
            repo = ProductoPresentacionEmbeddingIndexRepository(session)
            ids = repo.list_producto_presentacion_ids_by_producto(
                self.fixtures["producto_a_id"]
            )
            self.assertEqual(
                sorted(ids),
                sorted(
                    [
                        self.fixtures["pp_a_chica_id"],
                        self.fixtures["pp_a_grande_id"],
                    ]
                ),
            )

    def test_list_ids_by_categoria_returns_only_matching(self) -> None:
        with TestingSessionLocal() as session, session.begin():
            repo = ProductoPresentacionEmbeddingIndexRepository(session)
            ids_a = repo.list_producto_presentacion_ids_by_categoria(
                self.fixtures["cat_a_id"]
            )
            ids_b = repo.list_producto_presentacion_ids_by_categoria(
                self.fixtures["cat_b_id"]
            )
            self.assertEqual(
                sorted(ids_a),
                sorted(
                    [
                        self.fixtures["pp_a_chica_id"],
                        self.fixtures["pp_a_grande_id"],
                        self.fixtures["pp_b_chica_id"],
                        self.fixtures["pp_b_grande_id"],
                    ]
                ),
            )
            self.assertEqual(ids_b, [self.fixtures["pp_c_chica_id"]])

    def test_list_ids_by_presentacion_returns_only_matching(self) -> None:
        with TestingSessionLocal() as session, session.begin():
            repo = ProductoPresentacionEmbeddingIndexRepository(session)
            chica_ids = repo.list_producto_presentacion_ids_by_presentacion(
                self.fixtures["presentacion_chica_id"]
            )
            grande_ids = repo.list_producto_presentacion_ids_by_presentacion(
                self.fixtures["presentacion_grande_id"]
            )
            self.assertEqual(
                sorted(chica_ids),
                sorted(
                    [
                        self.fixtures["pp_a_chica_id"],
                        self.fixtures["pp_b_chica_id"],
                        self.fixtures["pp_c_chica_id"],
                    ]
                ),
            )
            self.assertEqual(
                sorted(grande_ids),
                sorted(
                    [
                        self.fixtures["pp_a_grande_id"],
                        self.fixtures["pp_b_grande_id"],
                    ]
                ),
            )

    def test_list_ids_by_alias_product_wide(self) -> None:
        with TestingSessionLocal() as session, session.begin():
            alias = _add_alias(
                session,
                id_producto=self.fixtures["producto_a_id"],
                id_producto_presentacion=None,
                alias="muzza",
            )
            repo = ProductoPresentacionEmbeddingIndexRepository(session)
            ids = repo.list_producto_presentacion_ids_by_alias(int(alias.id))
            self.assertEqual(
                sorted(ids),
                sorted(
                    [
                        self.fixtures["pp_a_chica_id"],
                        self.fixtures["pp_a_grande_id"],
                    ]
                ),
            )

    def test_list_ids_by_alias_presentation_specific(self) -> None:
        with TestingSessionLocal() as session, session.begin():
            alias = _add_alias(
                session,
                id_producto=self.fixtures["producto_a_id"],
                id_producto_presentacion=self.fixtures["pp_a_chica_id"],
                alias="muzza-chica",
            )
            repo = ProductoPresentacionEmbeddingIndexRepository(session)
            ids = repo.list_producto_presentacion_ids_by_alias(int(alias.id))
            self.assertEqual(ids, [self.fixtures["pp_a_chica_id"]])

    def test_scope_resolution_methods_are_read_only(self) -> None:
        with TestingSessionLocal() as session, session.begin():
            repo = ProductoPresentacionEmbeddingIndexRepository(session)
            before = _count_embeddings(session)
            repo.list_producto_presentacion_ids_by_producto(
                self.fixtures["producto_a_id"]
            )
            repo.list_producto_presentacion_ids_by_categoria(
                self.fixtures["cat_a_id"]
            )
            repo.list_producto_presentacion_ids_by_presentacion(
                self.fixtures["presentacion_chica_id"]
            )
            alias = _add_alias(
                session,
                id_producto=self.fixtures["producto_a_id"],
                id_producto_presentacion=None,
                alias="muzza",
            )
            repo.list_producto_presentacion_ids_by_alias(int(alias.id))
            after = _count_embeddings(session)
            self.assertEqual(before, after)


def _count_embeddings(session: Session) -> int:
    return int(
        session.execute(select(ProductoPresentacionEmbedding.id)).scalars().all().__len__()
    )


class EmptyScopeTest(unittest.TestCase):
    def test_empty_scope_short_circuits_without_ollama(self) -> None:
        fixtures = _seed_two_productos_two_categorias()
        self.addCleanup(_delete_comercio, fixtures["comercio_id"])
        client = _FakeEmbeddingClient()
        with TestingSessionLocal() as session, session.begin():
            service = _build_sync_service(
                session, client=client, settings=_settings()
            )
            # A producto without any presentations.
            with TestingSessionLocal() as session:
                new_service = _build_sync_service(
                    session, client=client, settings=_settings()
                )
                # Use a fresh producto without presentations.
                # producto_c has one presentation, so use the second presentacion
                # which is unused.
                with session.begin():
                    presentacion = Presentacion(
                        id_comercio=fixtures["comercio_id"],
                        codigo=f"empty-{fixtures['suffix']}",
                        descripcion="Empty",
                        activo=True,
                        orden=99,
                    )
                    session.add(presentacion)
                    session.flush()
                    empty_producto = Producto(
                        id_categoria_producto=fixtures["cat_b_id"],
                        nombre=f"Empty {fixtures['suffix']}",
                        descripcion=None,
                        activo=True,
                        disponible=True,
                        orden=99,
                    )
                    session.add(empty_producto)
                    session.flush()
                    empty_id = int(empty_producto.id)

                result = new_service.synchronize_producto(empty_id)
            self.assertEqual(result, empty_result())
            self.assertEqual(client.call_count, 0)


class ProductoSynchronizationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.fixtures = _seed_two_productos_two_categorias()
        self.addCleanup(_delete_comercio, self.fixtures["comercio_id"])
        self.client = _FakeEmbeddingClient()
        self.settings = _settings()

    def test_producto_reindexes_all_its_presentations_and_aggregates(self) -> None:
        with TestingSessionLocal() as session, session.begin():
            service = _build_sync_service(
                session, client=self.client, settings=self.settings
            )
            result = service.synchronize_producto(self.fixtures["producto_a_id"])
        self.assertTrue(result.attempted)
        self.assertFalse(result.synchronization_failed)
        # producto_a owns two presentations; each presentation yields two
        # documents (canonical + description) per the 4.6 builder, so the
        # aggregate counters must reflect four created rows on first run.
        self.assertEqual(result.created, 4)
        self.assertEqual(result.updated, 0)
        self.assertEqual(result.failed, 0)
        self.assertGreater(self.client.call_count, 0)

    def test_producto_second_run_reports_unchanged(self) -> None:
        # First run creates the rows.
        with TestingSessionLocal() as session, session.begin():
            service = _build_sync_service(
                session, client=self.client, settings=self.settings
            )
            first = service.synchronize_producto(self.fixtures["producto_a_id"])
        self.assertEqual(first.created, 4)
        # Second run should not call Ollama and should report all unchanged.
        client_calls = self.client.call_count
        with TestingSessionLocal() as session, session.begin():
            service = _build_sync_service(
                session, client=self.client, settings=self.settings
            )
            second = service.synchronize_producto(self.fixtures["producto_a_id"])
        self.assertTrue(second.attempted)
        self.assertEqual(second.unchanged, 4)
        self.assertEqual(second.created, 0)
        self.assertEqual(second.updated, 0)
        # No new Ollama call between the two runs (cache-hit behavior).
        self.assertEqual(self.client.call_count, client_calls)


class EmptyScopeShortCircuitsTest(unittest.TestCase):
    """A scope with zero presentations must short-circuit without Ollama."""

    def setUp(self) -> None:
        self.fixtures = _seed_two_productos_two_categorias()
        self.addCleanup(_delete_comercio, self.fixtures["comercio_id"])
        self.client = _FakeEmbeddingClient()

    def test_producto_without_presentations_returns_empty_result(self) -> None:
        with TestingSessionLocal() as session, session.begin():
            empty_producto = Producto(
                id_categoria_producto=self.fixtures["cat_b_id"],
                nombre=f"Empty {self.fixtures['suffix']}",
                descripcion=None,
                activo=True,
                disponible=True,
                orden=99,
            )
            session.add(empty_producto)
            session.flush()
            empty_id = int(empty_producto.id)
        with TestingSessionLocal() as session, session.begin():
            service = _build_sync_service(
                session, client=self.client, settings=_settings()
            )
            result = service.synchronize_producto(empty_id)
        self.assertEqual(result, empty_result())
        self.assertEqual(self.client.call_count, 0)

    def test_categoria_without_products_returns_empty_result(self) -> None:
        with TestingSessionLocal() as session, session.begin():
            empty_cat = CategoriaProducto(
                id_comercio=self.fixtures["comercio_id"],
                descripcion=f"Empty {self.fixtures['suffix']}",
                activo=True,
                orden=99,
            )
            session.add(empty_cat)
            session.flush()
            empty_cat_id = int(empty_cat.id)
        with TestingSessionLocal() as session, session.begin():
            service = _build_sync_service(
                session, client=self.client, settings=_settings()
            )
            result = service.synchronize_categoria(empty_cat_id)
        self.assertEqual(result, empty_result())
        self.assertEqual(self.client.call_count, 0)

    def test_presentacion_without_pp_returns_empty_result(self) -> None:
        with TestingSessionLocal() as session, session.begin():
            orphan = Presentacion(
                id_comercio=self.fixtures["comercio_id"],
                codigo=f"orphan-{self.fixtures['suffix']}",
                descripcion="Orphan",
                activo=True,
                orden=99,
            )
            session.add(orphan)
            session.flush()
            orphan_id = int(orphan.id)
        with TestingSessionLocal() as session, session.begin():
            service = _build_sync_service(
                session, client=self.client, settings=_settings()
            )
            result = service.synchronize_presentacion(orphan_id)
        self.assertEqual(result, empty_result())
        self.assertEqual(self.client.call_count, 0)


class InactiveCatalogTest(unittest.TestCase):
    """When the parent catalog chain is inactive, the indexer marks every
    existing embedding row as ``inactive`` without calling Ollama."""

    def setUp(self) -> None:
        self.fixtures = _seed_two_productos_two_categorias()
        self.addCleanup(_delete_comercio, self.fixtures["comercio_id"])
        self.client = _FakeEmbeddingClient()
        self.settings = _settings()

    def test_inactive_producto_marks_rows_inactive_without_ollama(self) -> None:
        # First run creates ready rows.
        with TestingSessionLocal() as session, session.begin():
            service = _build_sync_service(
                session, client=self.client, settings=self.settings
            )
            first = service.synchronize_producto(self.fixtures["producto_a_id"])
        self.assertEqual(first.created, 4)
        calls_after_first = self.client.call_count

        # Mark producto inactive and re-sync.
        with TestingSessionLocal() as session, session.begin():
            producto = session.get(Producto, self.fixtures["producto_a_id"])
            producto.activo = False
        with TestingSessionLocal() as session, session.begin():
            service = _build_sync_service(
                session, client=self.client, settings=self.settings
            )
            second = service.synchronize_producto(self.fixtures["producto_a_id"])
        self.assertTrue(second.attempted)
        self.assertEqual(second.inactive, 4)
        self.assertEqual(second.created, 0)
        self.assertEqual(second.updated, 0)
        self.assertEqual(second.failed, 0)
        # No Ollama call on the inactive path.
        self.assertEqual(self.client.call_count, calls_after_first)


class ResultLeakageTest(unittest.TestCase):
    """The ``EmbeddingSynchronizationResult`` MUST NOT expose vectors or
    source text."""

    def test_result_does_not_leak_internal_fields(self) -> None:
        fields = set(EmbeddingSynchronizationResult.__dataclass_fields__.keys())
        self.assertEqual(
            fields,
            {
                "attempted",
                "created",
                "updated",
                "unchanged",
                "stale",
                "inactive",
                "failed",
                "synchronization_failed",
            },
        )


class CategoriaSynchronizationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.fixtures = _seed_two_productos_two_categorias()
        self.addCleanup(_delete_comercio, self.fixtures["comercio_id"])
        self.client = _FakeEmbeddingClient()
        self.settings = _settings()

    def test_categoria_reindexes_only_its_products_presentations(self) -> None:
        with TestingSessionLocal() as session, session.begin():
            service = _build_sync_service(
                session, client=self.client, settings=self.settings
            )
            result = service.synchronize_categoria(self.fixtures["cat_b_id"])
        # cat_b owns producto_c which has one presentation; only that
        # presentation is reindexed.
        self.assertTrue(result.attempted)
        self.assertEqual(result.created, 2)
        self.assertEqual(result.updated, 0)
        self.assertEqual(result.failed, 0)


class PresentacionSynchronizationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.fixtures = _seed_two_productos_two_categorias()
        self.addCleanup(_delete_comercio, self.fixtures["comercio_id"])
        self.client = _FakeEmbeddingClient()
        self.settings = _settings()

    def test_presentacion_reindexes_only_linked_product_presentations(self) -> None:
        with TestingSessionLocal() as session, session.begin():
            service = _build_sync_service(
                session, client=self.client, settings=self.settings
            )
            result = service.synchronize_presentacion(
                self.fixtures["presentacion_grande_id"]
            )
        self.assertTrue(result.attempted)
        # Only producto_a and producto_b reference presentacion_grande,
        # so two presentations are reindexed (producto_c is excluded).
        self.assertEqual(result.created, 4)


class ProductoPresentacionSynchronizationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.fixtures = _seed_two_productos_two_categorias()
        self.addCleanup(_delete_comercio, self.fixtures["comercio_id"])
        self.client = _FakeEmbeddingClient()
        self.settings = _settings()

    def test_producto_presentacion_reindexes_only_itself(self) -> None:
        with TestingSessionLocal() as session, session.begin():
            service = _build_sync_service(
                session, client=self.client, settings=self.settings
            )
            result = service.synchronize_producto_presentacion(
                self.fixtures["pp_a_chica_id"]
            )
        self.assertTrue(result.attempted)
        self.assertEqual(result.created, 2)


class AliasSynchronizationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.fixtures = _seed_two_productos_two_categorias()
        self.addCleanup(_delete_comercio, self.fixtures["comercio_id"])
        self.client = _FakeEmbeddingClient()
        self.settings = _settings()

    def test_product_wide_alias_reindexes_every_presentation_of_product(self) -> None:
        with TestingSessionLocal() as session, session.begin():
            alias = _add_alias(
                session,
                id_producto=self.fixtures["producto_a_id"],
                id_producto_presentacion=None,
                alias="muzza",
            )
            alias_id = int(alias.id)
        with TestingSessionLocal() as session, session.begin():
            service = _build_sync_service(
                session, client=self.client, settings=self.settings
            )
            result = service.synchronize_alias(alias_id)
        self.assertTrue(result.attempted)
        # producto_a owns two presentations; each yields canonical +
        # description + the product-wide alias = 3 documents.
        self.assertEqual(result.created, 6)

    def test_presentation_specific_alias_reindexes_only_its_presentation(self) -> None:
        with TestingSessionLocal() as session, session.begin():
            alias = _add_alias(
                session,
                id_producto=self.fixtures["producto_a_id"],
                id_producto_presentacion=self.fixtures["pp_a_chica_id"],
                alias="muzza-chica",
            )
            alias_id = int(alias.id)
        with TestingSessionLocal() as session, session.begin():
            service = _build_sync_service(
                session, client=self.client, settings=self.settings
            )
            result = service.synchronize_alias(alias_id)
        self.assertTrue(result.attempted)
        # The single presentation yields canonical + description + alias = 3
        # documents on first run.
        self.assertEqual(result.created, 3)


class RecoverableFailureTest(unittest.TestCase):
    """``EmbeddingClientError`` must NOT roll back the catalog change."""

    def setUp(self) -> None:
        self.fixtures = _seed_two_productos_two_categorias()
        self.addCleanup(_delete_comercio, self.fixtures["comercio_id"])

    def test_ollama_error_is_recoverable(self) -> None:
        client = _FakeEmbeddingClient(raise_for={"Pizza"})
        with TestingSessionLocal() as session, session.begin():
            service = _build_sync_service(
                session, client=client, settings=_settings()
            )
            result = service.synchronize_producto(self.fixtures["producto_a_id"])
        self.assertTrue(result.attempted)
        self.assertFalse(result.synchronization_failed)
        self.assertGreater(result.failed, 0)


class UnhandledSQLAlchemyErrorTest(unittest.TestCase):
    """An unhandled ``SQLAlchemyError`` produces a recovery-safe result."""

    def test_unhandled_error_produces_synchronization_failed(self) -> None:
        fixtures = _seed_two_productos_two_categorias()
        self.addCleanup(_delete_comercio, fixtures["comercio_id"])

        class _RaisingIndexer:
            def index_presentations(self, **_kwargs: Any) -> None:
                raise SQLAlchemyError("simulated")

        client = _FakeEmbeddingClient()
        # Build a seeder with a custom indexer that raises.
        with TestingSessionLocal() as session, session.begin():
            # Build the service with a raising indexer via constructor injection.
            session.flush()
        with TestingSessionLocal() as session:
            service = CatalogEmbeddingSynchronizationService(
                session=session,
                embedding_client=client,
                settings=_settings(),
                indexer=_RaisingIndexer(),  # type: ignore[arg-type]
            )
            result = service.synchronize_producto(fixtures["producto_a_id"])
        self.assertFalse(result.attempted)
        self.assertTrue(result.synchronization_failed)
        self.assertEqual(
            result,
            synchronization_failed_result(),
        )


class CommerceIsolationTest(unittest.TestCase):
    """Sync for one comercio MUST NOT touch embeddings of another comercio."""

    def test_other_commerce_presentations_untouched(self) -> None:
        fixtures_a = _seed_two_productos_two_categorias()
        fixtures_b = _seed_two_productos_two_categorias()
        self.addCleanup(_delete_comercio, fixtures_a["comercio_id"])
        self.addCleanup(_delete_comercio, fixtures_b["comercio_id"])

        client = _FakeEmbeddingClient()
        # Run sync for comercio A only.
        with TestingSessionLocal() as session, session.begin():
            service = _build_sync_service(
                session, client=client, settings=_settings()
            )
            service.synchronize_producto(fixtures_a["producto_a_id"])

        # Comercio B's presentaciones must have NO embeddings.
        with TestingSessionLocal() as session:
            count = (
                session.execute(
                    select(ProductoPresentacionEmbedding).where(
                        ProductoPresentacionEmbedding.id_producto_presentacion.in_(
                            [
                                fixtures_b["pp_a_chica_id"],
                                fixtures_b["pp_a_grande_id"],
                                fixtures_b["pp_b_chica_id"],
                                fixtures_b["pp_b_grande_id"],
                                fixtures_b["pp_c_chica_id"],
                            ]
                        )
                    )
                )
                .scalars()
                .all()
            )
            self.assertEqual(count, [])


class AliasDeleteScopeCaptureTest(unittest.TestCase):
    """``ProductoAliasService.delete`` MUST capture the scope BEFORE deletion
    and expose it on the return value. The sync service MUST be able to
    reindex the captured scope without re-reading the alias row."""

    def setUp(self) -> None:
        self.fixtures = _seed_two_productos_two_categorias()
        self.addCleanup(_delete_comercio, self.fixtures["comercio_id"])

    def test_product_wide_alias_delete_captures_scope(self) -> None:
        with TestingSessionLocal() as session, session.begin():
            alias = _add_alias(
                session,
                id_producto=self.fixtures["producto_a_id"],
                id_producto_presentacion=None,
                alias="muzza",
            )
            alias_id = int(alias.id)
        with TestingSessionLocal() as session:
            result = ProductoAliasService(session).delete(alias_id)
            session.commit()
        self.assertEqual(result.id_alias, alias_id)
        self.assertEqual(result.id_producto, self.fixtures["producto_a_id"])
        self.assertIsNone(result.id_producto_presentacion)

    def test_presentation_specific_alias_delete_captures_scope(self) -> None:
        with TestingSessionLocal() as session, session.begin():
            alias = _add_alias(
                session,
                id_producto=self.fixtures["producto_a_id"],
                id_producto_presentacion=self.fixtures["pp_a_chica_id"],
                alias="muzza-chica",
            )
            alias_id = int(alias.id)
        with TestingSessionLocal() as session:
            result = ProductoAliasService(session).delete(alias_id)
            session.commit()
        self.assertEqual(result.id_alias, alias_id)
        self.assertEqual(result.id_producto, self.fixtures["producto_a_id"])
        self.assertEqual(
            result.id_producto_presentacion, self.fixtures["pp_a_chica_id"]
        )

    def test_post_delete_sync_uses_captured_scope(self) -> None:
        """After the alias commit, the orchestrator uses the captured scope
        to drive sync. The sync service MUST accept the captured scope and
        NOT attempt to resolve a deleted alias through ``id_alias``."""
        client = _FakeEmbeddingClient()
        with TestingSessionLocal() as session, session.begin():
            alias = _add_alias(
                session,
                id_producto=self.fixtures["producto_a_id"],
                id_producto_presentacion=self.fixtures["pp_a_chica_id"],
                alias="muzza-chica",
            )
            alias_id = int(alias.id)
        with TestingSessionLocal() as session:
            captured = ProductoAliasService(session).delete(alias_id)
            session.commit()
        # Now drive sync through the captured scope (NOT id_alias).
        with TestingSessionLocal() as session, session.begin():
            service = _build_sync_service(
                session, client=client, settings=_settings()
            )
            if captured.id_producto_presentacion is not None:
                result = service.synchronize_producto_presentacion(
                    int(captured.id_producto_presentacion)
                )
            else:
                result = service.synchronize_producto(int(captured.id_producto))
        self.assertTrue(result.attempted)
        self.assertFalse(result.synchronization_failed)


class CallerOrchestrationTest(unittest.TestCase):
    """When the sync raises an unhandled ``SQLAlchemyError``, the caller
    rolls back only the synchronization transaction, the catalog row
    stays committed, and the returned result has
    ``synchronization_failed=True``."""

    def test_caller_rolls_back_only_sync_and_returns_safe_result(self) -> None:
        fixtures = _seed_two_productos_two_categorias()
        self.addCleanup(_delete_comercio, fixtures["comercio_id"])

        class _RaisingIndexer:
            def index_presentations(self, **_kwargs: Any) -> None:
                raise SQLAlchemyError("simulated")

        client = _FakeEmbeddingClient()
        # Stage a catalog mutation that the caller already committed and
        # capture the resulting id BEFORE the context manager exits.
        with TestingSessionLocal() as session, session.begin():
            new_producto = Producto(
                id_categoria_producto=fixtures["cat_a_id"],
                nombre=f"Caller Orchestration {fixtures['suffix']}",
                descripcion=None,
                activo=True,
                disponible=True,
                orden=50,
            )
            session.add(new_producto)
            session.flush()
            producto_id = int(new_producto.id)
        # The catalog row is committed by the context manager exit.

        # Now simulate the caller orchestration: try sync, catch unhandled
        # SQLAlchemyError, rollback only the sync transaction. We use an
        # existing producto that already has presentations so the
        # indexer is actually invoked (and raises).
        with TestingSessionLocal() as session:
            service = CatalogEmbeddingSynchronizationService(
                session=session,
                embedding_client=client,
                settings=_settings(),
                indexer=_RaisingIndexer(),  # type: ignore[arg-type]
            )
            try:
                result = service.synchronize_producto(
                    fixtures["producto_a_id"]
                )
                session.commit()
            except SQLAlchemyError:
                session.rollback()
                result = synchronization_failed_result()

        self.assertTrue(result.synchronization_failed)
        self.assertFalse(result.attempted)

        # The catalog row remains committed (the previously staged new
        # producto from the first commit is still in the database).
        with TestingSessionLocal() as session:
            still_there = session.get(Producto, producto_id)
            self.assertIsNotNone(still_there)


if __name__ == "__main__":
    unittest.main(verbosity=2)
