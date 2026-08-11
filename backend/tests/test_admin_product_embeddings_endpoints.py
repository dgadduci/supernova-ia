"""Endpoint tests for the local-admin product-embedding routes.

Subphase 4.7 introduces two routes under
``/admin/comercios/{comercio_id}/product-embeddings/{reindex,status}``
gated behind ``Settings.enable_local_admin_endpoints``. These tests
cover the nine focused cases from ``openspec/specs/project.md`` §4.7
plus the FastAPI session lifecycle (commit / rollback / close) using a
``MagicMock`` session so the assertions exercise only the route
handler's actions.

The test app is built the same way as
``test_incoming_messages_endpoint.py``: a thin ``FastAPI()`` that
includes the router, with ``app.dependency_overrides[get_session]``
replaced by a plain function (not a generator) that returns the mock
so ``mock.commit`` / ``mock.rollback`` / ``mock.close`` call counts
reflect the route handler's actions only. The admin service is
replaced through a ``patch.object`` on the router module so the route
handlers receive a programmable fake that records the call and yields
a controllable ``SeedingResult``.
"""
from __future__ import annotations

import unittest
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

import backend.routers.admin_product_embeddings as router_module
from backend.dependencies import get_session, require_admin_token
from backend.services.exceptions import (
    ComercioNotFound,
    InvalidBatchSize,
    InvalidProductEmbeddingAdminScope,
)
from backend.services.producto_presentacion_embedding_seeder import (
    SeedingOutcome,
    SeedingResult,
)

db = MagicMock(name="DatabaseSession")
app = FastAPI()
app.include_router(router_module.router)


def override_get_session():
    return db


def override_require_admin_token():
    return None


app.dependency_overrides[get_session] = override_get_session
app.dependency_overrides[require_admin_token] = override_require_admin_token


class _FakeAdminService:
    """Programmable fake of ``ProductoPresentacionEmbeddingAdminService``."""

    def __init__(
        self,
        *,
        reindex_result: SeedingResult | None = None,
        reindex_error: BaseException | None = None,
        status_result: tuple | None = None,
        status_error: BaseException | None = None,
    ) -> None:
        self.calls: list[dict] = []
        self._reindex_result = reindex_result or SeedingResult()
        self._reindex_error = reindex_error
        self._status_result = status_result or (
            MagicMock(name="StatusCounts"),
            MagicMock(name="SourceTypeCounts"),
            [],
        )
        self._status_error = status_error

    def run_reindex(self, **kwargs):
        self.calls.append({"method": "run_reindex", **kwargs})
        if self._reindex_error is not None:
            raise self._reindex_error
        return self._reindex_result

    def get_status(self, **kwargs):
        self.calls.append({"method": "get_status", **kwargs})
        if self._status_error is not None:
            raise self._status_error
        return self._status_result


@contextmanager
def _patch_service(service: _FakeAdminService):
    class _Factory:
        def __init__(self, _session):
            self._impl = service

        def run_reindex(self, **kwargs):
            return self._impl.run_reindex(**kwargs)

        def get_status(self, **kwargs):
            return self._impl.get_status(**kwargs)

    with patch.object(
        router_module,
        "ProductoPresentacionEmbeddingAdminService",
        _Factory,
    ):
        yield service


def _clear_overrides() -> None:
    app.dependency_overrides.clear()
    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[require_admin_token] = override_require_admin_token


REINDEX_URL = "/admin/comercios/1/product-embeddings/reindex"
STATUS_URL = "/admin/comercios/1/product-embeddings/status"


class EndpointGateTest(unittest.TestCase):
    def setUp(self):
        db.reset_mock()
        _clear_overrides()
        self.client = TestClient(app)
        self._patcher = patch.object(
            router_module,
            "load_settings",
            return_value=_settings(enable_local_admin_endpoints=False),
        )
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()
        _clear_overrides()

    def test_post_returns_404_when_gate_disabled(self):
        response = self.client.post(REINDEX_URL, json={"dry_run": True})
        self.assertEqual(response.status_code, 404)
        db.commit.assert_not_called()
        db.rollback.assert_not_called()
        db.close.assert_not_called()

    def test_get_returns_404_when_gate_disabled(self):
        response = self.client.get(STATUS_URL)
        self.assertEqual(response.status_code, 404)
        db.commit.assert_not_called()
        db.rollback.assert_not_called()
        db.close.assert_not_called()


class EndpointSessionLifecycleTest(unittest.TestCase):
    def setUp(self):
        db.reset_mock()
        _clear_overrides()
        self.client = TestClient(app, raise_server_exceptions=False)
        self._patcher = patch.object(
            router_module,
            "load_settings",
            return_value=_settings(enable_local_admin_endpoints=True),
        )
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()
        _clear_overrides()

    def test_reindex_dry_run_performs_no_commit(self):
        service = _FakeAdminService(
            reindex_result=SeedingResult(
                created=1,
                updated=2,
                unchanged=3,
                stale=0,
                inactive=0,
                failed=0,
            )
        )
        with _patch_service(service):
            response = self.client.post(REINDEX_URL, json={"dry_run": True})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["counters"]["created"], 1)
        self.assertEqual(response.json()["counters"]["updated"], 2)
        self.assertEqual(response.json()["counters"]["unchanged"], 3)
        self.assertEqual(response.json()["dry_run"], True)
        self.assertEqual(
            service.calls,
            [
                {
                    "method": "run_reindex",
                    "id_comercio": 1,
                    "id_producto": None,
                    "id_producto_presentacion": None,
                    "force": False,
                    "dry_run": True,
                    "batch_size": None,
                }
            ],
        )
        db.commit.assert_not_called()
        db.rollback.assert_not_called()
        db.close.assert_not_called()

    def test_reindex_real_run_commits_once(self):
        service = _FakeAdminService(
            reindex_result=SeedingResult(
                created=0,
                updated=0,
                unchanged=0,
                stale=0,
                inactive=0,
                failed=0,
            )
        )
        with _patch_service(service):
            response = self.client.post(REINDEX_URL, json={"dry_run": False})

        self.assertEqual(response.status_code, 200)
        db.commit.assert_called_once()
        db.rollback.assert_not_called()
        db.close.assert_not_called()

    def test_reindex_unhandled_failure_rolls_back(self):
        service = _FakeAdminService(reindex_error=RuntimeError("boom"))
        with _patch_service(service):
            response = self.client.post(
                REINDEX_URL,
                json={"dry_run": False},
            )
        self.assertEqual(response.status_code, 500)
        db.commit.assert_not_called()
        db.rollback.assert_called_once()
        db.close.assert_not_called()

    def test_reindex_recoverable_failures_return_200_with_counters(self):
        service = _FakeAdminService(
            reindex_result=SeedingResult(
                created=0,
                updated=0,
                unchanged=0,
                stale=0,
                inactive=0,
                failed=5,
                outcomes=(
                    SeedingOutcome(
                        id_producto_presentacion=1,
                        status="failed",
                        failed=5,
                    ),
                ),
            )
        )
        with _patch_service(service):
            response = self.client.post(REINDEX_URL, json={"dry_run": False})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["counters"]["failed"], 5)
        self.assertNotIn("trace", response.text)
        self.assertNotIn("RuntimeError", response.text)
        db.commit.assert_called_once()
        db.rollback.assert_not_called()

    def test_reindex_missing_comercio_returns_404(self):
        service = _FakeAdminService(reindex_error=ComercioNotFound(99))
        with _patch_service(service):
            response = self.client.post(
                REINDEX_URL,
                json={"dry_run": False},
            )
        self.assertEqual(response.status_code, 404)
        db.commit.assert_not_called()
        db.rollback.assert_called_once()

    def test_reindex_invalid_scope_returns_400(self):
        service = _FakeAdminService(
            reindex_error=InvalidProductEmbeddingAdminScope("scope mismatch")
        )
        with _patch_service(service):
            response = self.client.post(
                REINDEX_URL,
                json={"dry_run": False, "producto_id": 99},
            )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "scope mismatch")
        db.commit.assert_not_called()
        db.rollback.assert_called_once()

    def test_reindex_non_positive_batch_size_returns_400(self):
        service = _FakeAdminService(reindex_error=InvalidBatchSize("batch_size"))
        with _patch_service(service):
            response = self.client.post(
                REINDEX_URL,
                json={"dry_run": False, "batch_size": 0},
            )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "batch_size")
        db.commit.assert_not_called()
        db.rollback.assert_called_once()

    def test_get_status_happy_path_does_not_commit_or_rollback(self):
        counts = MagicMock(name="StatusCounts")
        counts.total = 0
        counts.pending = 0
        counts.ready = 0
        counts.failed = 0
        counts.stale = 0
        counts.inactive = 0
        counts.active = 0
        counts.with_last_error = 0
        source_type_counts = MagicMock(name="SourceTypeCounts")
        source_type_counts.canonical = 0
        source_type_counts.description = 0
        source_type_counts.alias = 0
        source_type_counts.combined = 0
        service = _FakeAdminService(
            status_result=(counts, source_type_counts, [])
        )
        with _patch_service(service):
            response = self.client.get(STATUS_URL)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["comercio_id"], 1)
        self.assertEqual(response.json()["total"], 0)
        db.commit.assert_not_called()
        db.rollback.assert_not_called()
        db.close.assert_not_called()

    def test_get_status_non_negative_counters_without_vectors(self):
        counts = MagicMock(name="StatusCounts")
        counts.total = 4
        counts.pending = 1
        counts.ready = 2
        counts.failed = 1
        counts.stale = 0
        counts.inactive = 0
        counts.active = 3
        counts.with_last_error = 1
        source_type_counts = MagicMock(name="SourceTypeCounts")
        source_type_counts.canonical = 1
        source_type_counts.description = 1
        source_type_counts.alias = 1
        source_type_counts.combined = 1
        service = _FakeAdminService(
            status_result=(counts, source_type_counts, ["row-a", "row-b"])
        )
        with _patch_service(service):
            response = self.client.get(STATUS_URL)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["total"], 4)
        self.assertEqual(payload["counts"]["ready"], 2)
        self.assertEqual(payload["counts"]["failed"], 1)
        self.assertEqual(payload["active"], 3)
        self.assertEqual(payload["with_last_error"], 1)
        self.assertEqual(payload["source_type_counts"]["canonical"], 1)
        self.assertEqual(payload["source_type_counts"]["alias"], 1)
        self.assertNotIn("vector", payload)
        self.assertNotIn("source_text", payload)
        self.assertNotIn("normalized_text", payload)
        self.assertNotIn("content_hash", payload)
        self.assertNotIn("last_error", payload)

    def test_get_status_missing_comercio_returns_404(self):
        service = _FakeAdminService(status_error=ComercioNotFound(99))
        with _patch_service(service):
            response = self.client.get(STATUS_URL)
        self.assertEqual(response.status_code, 404)
        db.commit.assert_not_called()
        db.rollback.assert_not_called()


class GetSessionGeneratorClosesSessionTest(unittest.TestCase):
    """Smoke test that the original ``get_session`` generator closes the
    session in its ``finally`` so the route handler can rely on the
    generator as the sole ``close`` owner.
    """

    def test_get_session_generator_closes_session(self):
        from backend.dependencies import get_session as real_get_session

        session = MagicMock(name="DatabaseSession")
        session.close = MagicMock(name="close")

        with patch.object(
            router_module,
            "load_settings",
            return_value=_settings(enable_local_admin_endpoints=True),
        ):
            with patch(
                "backend.dependencies._SessionLocal",
                return_value=session,
            ):
                generator = real_get_session()
                try:
                    next(generator)
                finally:
                    try:
                        next(generator)
                    except StopIteration:
                        pass
        session.close.assert_called_once()


def _settings(**overrides):
    from backend.config.settings import Settings

    base = {
        "llm_url": "http://llm.test",
        "llm_model": "test-llm",
        "llm_timeout": 30,
        "llm_keep_alive": "1h",
        "llm_num_ctx": 2048,
        "llm_num_predict": 256,
        "llm_log_content": False,
        "llm_log_max_chars": 50,
        "embedding_url": "http://embed.test",
        "embedding_model": "test-embed",
        "embedding_timeout_seconds": 15,
        "embedding_batch_size": 32,
        "embedding_dimension": 384,
        "enable_local_admin_endpoints": False,
    }
    base.update(overrides)
    return Settings(**base)


if __name__ == "__main__":
    unittest.main(verbosity=2)
