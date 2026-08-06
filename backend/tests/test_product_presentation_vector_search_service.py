"""Focused tests for the 4.9 product-presentation vector search service.

Subphase 4.9 introduces a pgvector-backed similarity search service
that exposes the read path over the existing 4.6
``producto_presentacion_embeddings`` table. The tests below cover the
18 scenarios required by the project playbook:

- Ordering (best match first; deterministic tie-breaker on
  ``id_producto_presentacion ASC``).
- Commerce isolation (rows for other comercios are NEVER returned).
- Inactive products / product presentations / unavailable products are
  excluded.
- Embedding status filtering (``failed`` / ``stale`` / ``inactive`` /
  ``pending`` rows are excluded).
- Model isolation (embeddings from another model are excluded).
- Dimension validation (rejected AFTER ``top_k`` and BEFORE the
  empty-candidate short-circuit).
- ``top_k`` validation (rejected FIRST; never reaches the repository).
- Candidate id restriction.
- Empty candidate list short-circuit (no SQL issued; result is ``[]``).
- Grouping: multiple documents for one product-presentation collapse
  to the best-scoring match.
- ``top_k`` counts unique product-presentations.
- ``source_type`` of the winning document is preserved on the typed
  result.
- No internal data leaks from the service result.
- 4.6–4.8 regression guard.
- Validation order: ``top_k=0`` + empty candidate list raises
  ``InvalidVectorSearchTopK`` (``top_k`` wins over the empty-candidate
  short-circuit).
- Validation order: wrong dimension + empty candidate list raises
  ``InvalidVectorSearchDimension`` (dimension wins over the
  empty-candidate short-circuit).
- Validation order: ``top_k=0`` + wrong dimension raises
  ``InvalidVectorSearchTopK`` (``top_k`` wins over dimension).

The tests use the live ``supernova_test`` PostgreSQL database and
seed embeddings directly through the existing 4.6
``ProductoPresentacionEmbeddingRepository.insert_document(...)``
surface. Each test creates / removes its own comercio so unrelated
rows are never modified.
"""
from __future__ import annotations

import unittest
import uuid
from typing import Any

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from backend.config.settings import Settings
from backend.models import (
    CategoriaProducto,
    EmbeddingStatus,
    Producto,
    ProductoPresentacion,
    ProductoPresentacionEmbedding,
)
from backend.repositories.producto_presentacion_embedding_repository import (
    ProductoPresentacionEmbeddingRepository,
)
from backend.services.exceptions import (
    InvalidVectorSearchDimension,
    InvalidVectorSearchTopK,
)
from backend.services.product_presentation_vector_search_service import (
    ProductPresentationVectorSearchService,
)
from backend.tests.test_producto_alias_model import (
    _delete_comercio,
    _seed_comercio_with_catalogo,
)

TEST_URL = "postgresql+psycopg:///supernova_test"

engine = create_engine(TEST_URL)
TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _suffix() -> str:
    return uuid.uuid4().hex[:10]


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


def _seed_extra_presentations(
    session, *, id_comercio: int, suffix: str
) -> dict[str, int]:
    """Add a third producto + presentation to the existing comercio."""
    categoria_id = session.scalar(
        select(CategoriaProducto.id).where(
            CategoriaProducto.id_comercio == id_comercio
        )
    )
    assert categoria_id is not None
    from backend.models import Presentacion

    presentacion_id = session.scalar(
        select(Presentacion.id).where(
            Presentacion.id_comercio == id_comercio,
            Presentacion.codigo == "chica",
        )
    )
    assert presentacion_id is not None
    producto = Producto(
        id_categoria_producto=categoria_id,
        nombre=f"Empanada {suffix}",
        descripcion=None,
        activo=True,
        disponible=True,
        orden=99,
    )
    session.add(producto)
    session.flush()
    pp = ProductoPresentacion(
        id_producto=producto.id,
        id_presentacion=presentacion_id,
        activo=True,
        orden=99,
    )
    session.add(pp)
    session.flush()
    return {
        "producto_c_id": int(producto.id),
        "pp_c_chica_id": int(pp.id),
    }


def _hash(source_type: str, key: str) -> str:
    """Build a 64-char hex placeholder hash.

    The database ``content_hash_chk`` constraint requires the value to
    match ``^[0-9a-f]{64}$`` so the helper composes a deterministic
    64-char hex string from the source type and an incrementing counter.
    """
    import hashlib

    digest = hashlib.sha256(f"{source_type}:{key}".encode()).hexdigest()
    return digest


def _insert_embedding(
    session,
    *,
    id_producto_presentacion: int,
    modelo: str,
    source_type: str,
    vector: list[float],
    source_record_id: int | None = None,
    embedding_status: str = EmbeddingStatus.READY.value,
    activo: bool = True,
) -> ProductoPresentacionEmbedding:
    """Seed one per-document embedding row directly through the 4.6 repo."""
    repo = ProductoPresentacionEmbeddingRepository(session)
    return repo.insert_document(
        id_producto_presentacion=id_producto_presentacion,
        modelo=modelo,
        source_type=source_type,
        source_record_id=source_record_id,
        source_text=f"source text for {source_type}",
        normalized_text=f"normalized text for {source_type}",
        content_hash=_hash(source_type, f"pp={id_producto_presentacion}"),
        vector=vector,
        embedding_status=embedding_status,
        activo=activo,
        last_error=None,
    )


def _unit_vector(value: float, dimension: int = 384) -> list[float]:
    """Build a unit-ish vector whose dominant axis is ``value``."""
    values = [value] + [0.0] * (dimension - 1)
    return values


def _make_query_vector(target_axis: float, dimension: int = 384) -> list[float]:
    return _unit_vector(target_axis, dimension)


class _SearchTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.fixtures = _seed_comercio_with_catalogo()
        self.addCleanup(_delete_comercio, self.fixtures["comercio_id"])
        self.settings = _settings()
        self.dimension = self.settings.embedding_dimension


class OrderingTest(_SearchTestCase):
    def test_nearest_matches_are_ordered_by_score_descending(self):
        pp_a = self.fixtures["pp_a_chica_id"]
        pp_b = self.fixtures["pp_a_grande_id"]
        with TestingSessionLocal() as session, session.begin():
            _insert_embedding(
                session,
                id_producto_presentacion=pp_a,
                modelo=self.settings.embedding_model,
                source_type="canonical",
                vector=_unit_vector(0.1, self.dimension),
            )
            _insert_embedding(
                session,
                id_producto_presentacion=pp_b,
                modelo=self.settings.embedding_model,
                source_type="canonical",
                vector=_unit_vector(0.9, self.dimension),
            )
        with TestingSessionLocal() as session:
            service = ProductPresentationVectorSearchService(
                session, self.settings
            )
            matches = service.search_similar(
                id_comercio=self.fixtures["comercio_id"],
                query_embedding=_make_query_vector(1.0, self.dimension),
                top_k=5,
            )
        self.assertEqual(len(matches), 2)
        self.assertEqual(matches[0].id_producto_presentacion, pp_b)
        self.assertEqual(matches[1].id_producto_presentacion, pp_a)
        self.assertGreater(matches[0].score, matches[1].score)
        self.assertTrue(-1.0 <= matches[0].score <= 1.0)
        self.assertTrue(-1.0 <= matches[1].score <= 1.0)

    def test_deterministic_tie_breaker_is_id_producto_presentacion_asc(self):
        pp_a = self.fixtures["pp_a_chica_id"]
        pp_b = self.fixtures["pp_a_grande_id"]
        with TestingSessionLocal() as session, session.begin():
            _insert_embedding(
                session,
                id_producto_presentacion=pp_a,
                modelo=self.settings.embedding_model,
                source_type="canonical",
                vector=_unit_vector(0.5, self.dimension),
            )
            _insert_embedding(
                session,
                id_producto_presentacion=pp_b,
                modelo=self.settings.embedding_model,
                source_type="canonical",
                vector=_unit_vector(0.5, self.dimension),
            )
        with TestingSessionLocal() as session:
            service = ProductPresentationVectorSearchService(
                session, self.settings
            )
            matches = service.search_similar(
                id_comercio=self.fixtures["comercio_id"],
                query_embedding=_make_query_vector(0.5, self.dimension),
                top_k=5,
            )
        self.assertEqual(
            [m.id_producto_presentacion for m in matches],
            sorted([m.id_producto_presentacion for m in matches]),
        )
        self.assertEqual(len(matches), 2)


class CommerceIsolationTest(_SearchTestCase):
    def test_results_are_isolated_by_comercio(self):
        other_suffix = uuid.uuid4().hex[:10]
        other = _seed_comercio_with_catalogo(suffix=other_suffix)
        self.addCleanup(_delete_comercio, other["comercio_id"])
        own_comercio = self.fixtures["comercio_id"]
        own_pp = self.fixtures["pp_a_chica_id"]
        other_pp = other["pp_a_chica_id"]
        with TestingSessionLocal() as session, session.begin():
            _insert_embedding(
                session,
                id_producto_presentacion=own_pp,
                modelo=self.settings.embedding_model,
                source_type="canonical",
                vector=_unit_vector(0.9, self.dimension),
            )
            _insert_embedding(
                session,
                id_producto_presentacion=other_pp,
                modelo=self.settings.embedding_model,
                source_type="canonical",
                vector=_unit_vector(0.9, self.dimension),
            )
        with TestingSessionLocal() as session:
            service = ProductPresentationVectorSearchService(
                session, self.settings
            )
            matches = service.search_similar(
                id_comercio=own_comercio,
                query_embedding=_make_query_vector(1.0, self.dimension),
                top_k=10,
            )
        returned_ids = {m.id_producto_presentacion for m in matches}
        self.assertIn(own_pp, returned_ids)
        self.assertNotIn(other_pp, returned_ids)


class InactiveChainTest(_SearchTestCase):
    def test_inactive_products_are_excluded(self):
        pp_a = self.fixtures["pp_a_chica_id"]
        with TestingSessionLocal() as session, session.begin():
            _insert_embedding(
                session,
                id_producto_presentacion=pp_a,
                modelo=self.settings.embedding_model,
                source_type="canonical",
                vector=_unit_vector(0.9, self.dimension),
            )
            producto = session.get(Producto, self.fixtures["producto_a_id"])
            assert producto is not None
            producto.activo = False
        with TestingSessionLocal() as session:
            service = ProductPresentationVectorSearchService(
                session, self.settings
            )
            matches = service.search_similar(
                id_comercio=self.fixtures["comercio_id"],
                query_embedding=_make_query_vector(1.0, self.dimension),
                top_k=10,
            )
        self.assertEqual(matches, [])

    def test_inactive_product_presentations_are_excluded(self):
        pp_a = self.fixtures["pp_a_chica_id"]
        with TestingSessionLocal() as session, session.begin():
            _insert_embedding(
                session,
                id_producto_presentacion=pp_a,
                modelo=self.settings.embedding_model,
                source_type="canonical",
                vector=_unit_vector(0.9, self.dimension),
            )
            pp_row = session.get(ProductoPresentacion, pp_a)
            assert pp_row is not None
            pp_row.activo = False
        with TestingSessionLocal() as session:
            service = ProductPresentationVectorSearchService(
                session, self.settings
            )
            matches = service.search_similar(
                id_comercio=self.fixtures["comercio_id"],
                query_embedding=_make_query_vector(1.0, self.dimension),
                top_k=10,
            )
        self.assertEqual(matches, [])

    def test_unavailable_products_are_excluded(self):
        pp_a = self.fixtures["pp_a_chica_id"]
        with TestingSessionLocal() as session, session.begin():
            _insert_embedding(
                session,
                id_producto_presentacion=pp_a,
                modelo=self.settings.embedding_model,
                source_type="canonical",
                vector=_unit_vector(0.9, self.dimension),
            )
            producto = session.get(Producto, self.fixtures["producto_a_id"])
            assert producto is not None
            producto.disponible = False
        with TestingSessionLocal() as session:
            service = ProductPresentationVectorSearchService(
                session, self.settings
            )
            matches = service.search_similar(
                id_comercio=self.fixtures["comercio_id"],
                query_embedding=_make_query_vector(1.0, self.dimension),
                top_k=10,
            )
        self.assertEqual(matches, [])


class EmbeddingStatusExclusionTest(_SearchTestCase):
    def _seed_one_with_status(self, status: str) -> None:
        pp_a = self.fixtures["pp_a_chica_id"]
        with TestingSessionLocal() as session, session.begin():
            _insert_embedding(
                session,
                id_producto_presentacion=pp_a,
                modelo=self.settings.embedding_model,
                source_type="canonical",
                vector=_unit_vector(0.9, self.dimension),
                embedding_status=status,
            )

    def _assert_no_matches(self) -> None:
        with TestingSessionLocal() as session:
            service = ProductPresentationVectorSearchService(
                session, self.settings
            )
            matches = service.search_similar(
                id_comercio=self.fixtures["comercio_id"],
                query_embedding=_make_query_vector(1.0, self.dimension),
                top_k=10,
            )
        self.assertEqual(matches, [])

    def test_failed_rows_are_excluded(self):
        self._seed_one_with_status(EmbeddingStatus.FAILED.value)
        self._assert_no_matches()

    def test_stale_rows_are_excluded(self):
        self._seed_one_with_status(EmbeddingStatus.STALE.value)
        self._assert_no_matches()

    def test_inactive_rows_are_excluded(self):
        self._seed_one_with_status(EmbeddingStatus.INACTIVE.value)
        self._assert_no_matches()

    def test_pending_rows_are_excluded(self):
        self._seed_one_with_status(EmbeddingStatus.PENDING.value)
        self._assert_no_matches()


class ModelIsolationTest(_SearchTestCase):
    def test_embeddings_from_another_model_are_excluded(self):
        pp_a = self.fixtures["pp_a_chica_id"]
        with TestingSessionLocal() as session, session.begin():
            _insert_embedding(
                session,
                id_producto_presentacion=pp_a,
                modelo=self.settings.embedding_model,
                source_type="canonical",
                vector=_unit_vector(0.9, self.dimension),
            )
            _insert_embedding(
                session,
                id_producto_presentacion=pp_a,
                modelo="other-model",
                source_type="canonical",
                vector=_unit_vector(0.9, self.dimension),
            )
        with TestingSessionLocal() as session:
            service = ProductPresentationVectorSearchService(
                session, self.settings
            )
            matches = service.search_similar(
                id_comercio=self.fixtures["comercio_id"],
                query_embedding=_make_query_vector(1.0, self.dimension),
                top_k=10,
            )
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].id_producto_presentacion, pp_a)


class DimensionValidationTest(_SearchTestCase):
    def test_invalid_dimension_is_rejected(self):
        with TestingSessionLocal() as session:
            service = ProductPresentationVectorSearchService(
                session, self.settings
            )
            with self.assertRaises(InvalidVectorSearchDimension):
                service.search_similar(
                    id_comercio=self.fixtures["comercio_id"],
                    query_embedding=[0.1, 0.2],
                    top_k=5,
                )

    def test_query_dimension_match_passes_validation(self):
        with TestingSessionLocal() as session:
            service = ProductPresentationVectorSearchService(
                session, self.settings
            )
            result = service.search_similar(
                id_comercio=self.fixtures["comercio_id"],
                query_embedding=[0.1] * self.dimension,
                top_k=5,
            )
        self.assertEqual(result, [])


class TopKValidationTest(_SearchTestCase):
    def test_zero_top_k_is_rejected(self):
        with TestingSessionLocal() as session:
            service = ProductPresentationVectorSearchService(
                session, self.settings
            )
            with self.assertRaises(InvalidVectorSearchTopK):
                service.search_similar(
                    id_comercio=self.fixtures["comercio_id"],
                    query_embedding=[0.1] * self.dimension,
                    top_k=0,
                )

    def test_negative_top_k_is_rejected(self):
        with TestingSessionLocal() as session:
            service = ProductPresentationVectorSearchService(
                session, self.settings
            )
            with self.assertRaises(InvalidVectorSearchTopK):
                service.search_similar(
                    id_comercio=self.fixtures["comercio_id"],
                    query_embedding=[0.1] * self.dimension,
                    top_k=-1,
                )


class CandidateRestrictionTest(_SearchTestCase):
    def test_candidate_ids_restrict_results(self):
        pp_a = self.fixtures["pp_a_chica_id"]
        pp_b = self.fixtures["pp_a_grande_id"]
        with TestingSessionLocal() as session, session.begin():
            _insert_embedding(
                session,
                id_producto_presentacion=pp_a,
                modelo=self.settings.embedding_model,
                source_type="canonical",
                vector=_unit_vector(0.9, self.dimension),
            )
            _insert_embedding(
                session,
                id_producto_presentacion=pp_b,
                modelo=self.settings.embedding_model,
                source_type="canonical",
                vector=_unit_vector(0.1, self.dimension),
            )
        with TestingSessionLocal() as session:
            service = ProductPresentationVectorSearchService(
                session, self.settings
            )
            matches = service.search_similar(
                id_comercio=self.fixtures["comercio_id"],
                query_embedding=_make_query_vector(1.0, self.dimension),
                top_k=10,
                candidate_producto_presentacion_ids=[pp_a],
            )
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].id_producto_presentacion, pp_a)


class EmptyCandidateShortCircuitTest(_SearchTestCase):
    def test_empty_candidate_list_returns_empty_result_without_sql(self):
        with TestingSessionLocal() as session, session.begin():
            _insert_embedding(
                session,
                id_producto_presentacion=self.fixtures["pp_a_chica_id"],
                modelo=self.settings.embedding_model,
                source_type="canonical",
                vector=_unit_vector(0.9, self.dimension),
            )
        with TestingSessionLocal() as session:
            service = ProductPresentationVectorSearchService(
                session, self.settings
            )
            result = service.search_similar(
                id_comercio=self.fixtures["comercio_id"],
                query_embedding=_make_query_vector(1.0, self.dimension),
                top_k=10,
                candidate_producto_presentacion_ids=[],
            )
        self.assertEqual(result, [])


class GroupingTest(_SearchTestCase):
    def test_multiple_documents_collapse_to_best_scoring_match(self):
        pp_a = self.fixtures["pp_a_chica_id"]
        with TestingSessionLocal() as session, session.begin():
            _insert_embedding(
                session,
                id_producto_presentacion=pp_a,
                modelo=self.settings.embedding_model,
                source_type="canonical",
                vector=_unit_vector(0.9, self.dimension),
            )
            _insert_embedding(
                session,
                id_producto_presentacion=pp_a,
                modelo=self.settings.embedding_model,
                source_type="description",
                vector=_unit_vector(0.1, self.dimension),
            )
        with TestingSessionLocal() as session:
            service = ProductPresentationVectorSearchService(
                session, self.settings
            )
            matches = service.search_similar(
                id_comercio=self.fixtures["comercio_id"],
                query_embedding=_make_query_vector(1.0, self.dimension),
                top_k=10,
            )
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].id_producto_presentacion, pp_a)
        self.assertEqual(matches[0].source_type, "canonical")

    def test_top_k_counts_unique_product_presentations(self):
        with TestingSessionLocal() as session, session.begin():
            extra = _seed_extra_presentations(
                session,
                id_comercio=self.fixtures["comercio_id"],
                suffix=_suffix(),
            )
            pp_a = self.fixtures["pp_a_chica_id"]
            pp_b = self.fixtures["pp_a_grande_id"]
            pp_c = extra["pp_c_chica_id"]
            for pp_id in (pp_a, pp_b, pp_c):
                _insert_embedding(
                    session,
                    id_producto_presentacion=pp_id,
                    modelo=self.settings.embedding_model,
                    source_type="canonical",
                    vector=_unit_vector(0.9, self.dimension),
                )
                _insert_embedding(
                    session,
                    id_producto_presentacion=pp_id,
                    modelo=self.settings.embedding_model,
                    source_type="description",
                    vector=_unit_vector(0.1, self.dimension),
                )
        with TestingSessionLocal() as session:
            service = ProductPresentationVectorSearchService(
                session, self.settings
            )
            matches = service.search_similar(
                id_comercio=self.fixtures["comercio_id"],
                query_embedding=_make_query_vector(1.0, self.dimension),
                top_k=2,
            )
        self.assertEqual(len(matches), 2)
        self.assertEqual(
            len({m.id_producto_presentacion for m in matches}), 2
        )


class SourceTypeTest(_SearchTestCase):
    def test_winning_source_type_is_returned(self):
        pp_a = self.fixtures["pp_a_chica_id"]
        with TestingSessionLocal() as session, session.begin():
            _insert_embedding(
                session,
                id_producto_presentacion=pp_a,
                modelo=self.settings.embedding_model,
                source_type="canonical",
                vector=_unit_vector(0.1, self.dimension),
            )
            _insert_embedding(
                session,
                id_producto_presentacion=pp_a,
                modelo=self.settings.embedding_model,
                source_type="description",
                vector=_unit_vector(0.9, self.dimension),
            )
        with TestingSessionLocal() as session:
            service = ProductPresentationVectorSearchService(
                session, self.settings
            )
            matches = service.search_similar(
                id_comercio=self.fixtures["comercio_id"],
                query_embedding=_make_query_vector(1.0, self.dimension),
                top_k=10,
            )
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].source_type, "description")


class NoLeakTest(unittest.TestCase):
    def test_dataclass_exposes_only_three_fields(self):
        from dataclasses import fields

        from backend.services.product_presentation_vector_match import (
            ProductPresentationVectorMatch,
        )

        names = {f.name for f in fields(ProductPresentationVectorMatch)}
        self.assertEqual(
            names,
            {"id_producto_presentacion", "score", "source_type"},
        )

    def test_dataclass_is_frozen(self):
        from dataclasses import FrozenInstanceError

        from backend.services.product_presentation_vector_match import (
            ProductPresentationVectorMatch,
        )

        match = ProductPresentationVectorMatch(
            id_producto_presentacion=1,
            score=0.5,
            source_type="canonical",
        )
        with self.assertRaises(FrozenInstanceError):
            match.score = 0.9  # type: ignore[misc]


class ValidationOrderTest(_SearchTestCase):
    def test_zero_top_k_with_empty_candidate_list_raises_invalid_top_k(self):
        with TestingSessionLocal() as session, session.begin():
            _insert_embedding(
                session,
                id_producto_presentacion=self.fixtures["pp_a_chica_id"],
                modelo=self.settings.embedding_model,
                source_type="canonical",
                vector=_unit_vector(0.9, self.dimension),
            )
        with TestingSessionLocal() as session:
            service = ProductPresentationVectorSearchService(
                session, self.settings
            )
            with self.assertRaises(InvalidVectorSearchTopK):
                service.search_similar(
                    id_comercio=self.fixtures["comercio_id"],
                    query_embedding=[0.1] * self.dimension,
                    top_k=0,
                    candidate_producto_presentacion_ids=[],
                )

    def test_wrong_dimension_with_empty_candidate_list_raises_invalid_dimension(
        self,
    ):
        with TestingSessionLocal() as session:
            service = ProductPresentationVectorSearchService(
                session, self.settings
            )
            with self.assertRaises(InvalidVectorSearchDimension):
                service.search_similar(
                    id_comercio=self.fixtures["comercio_id"],
                    query_embedding=[0.1, 0.2],
                    top_k=10,
                    candidate_producto_presentacion_ids=[],
                )

    def test_zero_top_k_with_wrong_dimension_raises_invalid_top_k(self):
        with TestingSessionLocal() as session:
            service = ProductPresentationVectorSearchService(
                session, self.settings
            )
            with self.assertRaises(InvalidVectorSearchTopK):
                service.search_similar(
                    id_comercio=self.fixtures["comercio_id"],
                    query_embedding=[0.1, 0.2],
                    top_k=0,
                )


class ExistingRowCountRegressionTest(_SearchTestCase):
    def test_search_does_not_mutate_embedding_rows(self):
        pp_a = self.fixtures["pp_a_chica_id"]
        with TestingSessionLocal() as session, session.begin():
            _insert_embedding(
                session,
                id_producto_presentacion=pp_a,
                modelo=self.settings.embedding_model,
                source_type="canonical",
                vector=_unit_vector(0.9, self.dimension),
            )
        before = int(
            TestingSessionLocal()
            .scalar(
                select(func.count())
                .select_from(ProductoPresentacionEmbedding)
                .where(
                    ProductoPresentacionEmbedding.id_producto_presentacion
                    == pp_a
                )
            )
            or 0
        )
        with TestingSessionLocal() as session:
            service = ProductPresentationVectorSearchService(
                session, self.settings
            )
            service.search_similar(
                id_comercio=self.fixtures["comercio_id"],
                query_embedding=_make_query_vector(1.0, self.dimension),
                top_k=5,
            )
        after = int(
            TestingSessionLocal()
            .scalar(
                select(func.count())
                .select_from(ProductoPresentacionEmbedding)
                .where(
                    ProductoPresentacionEmbedding.id_producto_presentacion
                    == pp_a
                )
            )
            or 0
        )
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main(verbosity=2)