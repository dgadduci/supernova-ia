"""CLI runner tests for the per-document embedding indexer.

Subphase 4.6 introduces a CLI runner at
``backend/scripts/seed_product_presentation_embeddings.py``. These
tests cover the runner end-to-end through the public entry point,
including dry-run behavior, flag validation, batch-size override,
and report fields.
"""

from __future__ import annotations

import unittest
from unittest import mock

from backend.config.settings import Settings
from backend.scripts import seed_product_presentation_embeddings as cli


class CLIArgparseTest(unittest.TestCase):
    def test_help_lists_all_six_flags(self):
        with mock.patch("sys.stdout") as stdout:
            with self.assertRaises(SystemExit) as ctx:
                cli.main(["--help"])
        self.assertEqual(ctx.exception.code, 0)
        text = "".join(
            str(call.args[0]) for call in stdout.write.call_args_list
        )
        for flag in (
            "--comercio-id",
            "--producto-id",
            "--producto-presentacion-id",
            "--force",
            "--dry-run",
            "--batch-size",
        ):
            self.assertIn(flag, text)

    def test_batch_size_zero_is_rejected_before_construction(self):
        with mock.patch(
            "backend.scripts.seed_product_presentation_embeddings._SessionLocal"
        ) as session_factory:
            with mock.patch(
                "backend.scripts.seed_product_presentation_embeddings.OllamaEmbeddingClient"
            ) as ollama:
                with self.assertRaises(SystemExit) as ctx:
                    cli.main(["--batch-size", "0"])
        self.assertEqual(ctx.exception.code, 1)
        session_factory.assert_not_called()
        ollama.assert_not_called()

    def test_negative_batch_size_is_rejected_before_construction(self):
        with mock.patch(
            "backend.scripts.seed_product_presentation_embeddings._SessionLocal"
        ) as session_factory:
            with mock.patch(
                "backend.scripts.seed_product_presentation_embeddings.OllamaEmbeddingClient"
            ) as ollama:
                with self.assertRaises(SystemExit) as ctx:
                    cli.main(["--batch-size", "-1"])
        self.assertEqual(ctx.exception.code, 1)
        session_factory.assert_not_called()
        ollama.assert_not_called()


class CLIBatchSizeOverrideTest(unittest.TestCase):
    def test_batch_size_override_passes_replaced_settings(self):
        captured: dict[str, object] = {}
        persisted = Settings(
            llm_url="http://llm.test",
            llm_model="test-llm",
            llm_timeout=30,
            llm_keep_alive="1h",
            llm_num_ctx=2048,
            llm_num_predict=256,
            llm_log_content=False,
            llm_log_max_chars=50,
            embedding_url="http://embed.test",
            embedding_model="test-embed",
            embedding_timeout_seconds=15,
            embedding_batch_size=32,
            embedding_dimension=384,
        )

        class _FakeSession:
            def __init__(self) -> None:
                self.committed = False
                self.closed = False

            def commit(self) -> None:
                self.committed = True

            def rollback(self) -> None:
                pass

            def close(self) -> None:
                self.closed = True

        session = _FakeSession()

        class _FakeIndexer:
            def __init__(self, **kwargs: object) -> None:
                captured["indexer_settings"] = kwargs["settings"]

            def index_presentations(self, **kwargs: object) -> object:
                from backend.services.producto_presentacion_embedding_seeder import (
                    SeedingResult,
                )

                return SeedingResult()

        class _FakeSeeder:
            def __init__(self, indexer: object) -> None:
                captured["seeder_indexer"] = indexer

            def run(self, session: object, **kwargs: object) -> object:
                from backend.services.producto_presentacion_embedding_seeder import (
                    SeedingResult,
                )

                captured["seeder_kwargs"] = kwargs
                return SeedingResult()

        class _FakeFactory:
            def __init__(self, *args: object, **kwargs: object) -> None:
                captured["client_args"] = args
                captured["client_kwargs"] = kwargs

        with mock.patch(
            "backend.scripts.seed_product_presentation_embeddings.load_settings",
            return_value=persisted,
        ):
            with mock.patch(
                "backend.scripts.seed_product_presentation_embeddings._SessionLocal",
                return_value=session,
            ):
                with mock.patch(
                    "backend.scripts.seed_product_presentation_embeddings.OllamaEmbeddingClient",
                    _FakeFactory,
                ):
                    with mock.patch(
                        "backend.scripts.seed_product_presentation_embeddings.ProductoPresentacionEmbeddingIndexRepository",
                        lambda s: captured.setdefault("index_repo", s),
                    ):
                        with mock.patch(
                            "backend.scripts.seed_product_presentation_embeddings.ProductoPresentacionEmbeddingService",
                            lambda s: captured.setdefault("service", s),
                        ):
                            with mock.patch(
                                "backend.scripts.seed_product_presentation_embeddings.ProductoPresentacionEmbeddingIndexer",
                                _FakeIndexer,
                            ):
                                with mock.patch(
                                    "backend.scripts.seed_product_presentation_embeddings.ProductoPresentacionEmbeddingSeeder",
                                    _FakeSeeder,
                                ):
                                    with mock.patch("sys.stdout"):
                                        exit_code = cli.main(
                                            ["--batch-size", "16", "--dry-run"]
                                        )
        self.assertEqual(exit_code, 0)
        self.assertEqual(persisted.embedding_batch_size, 32)
        client_args = captured["client_args"]
        effective_settings = client_args[0]
        self.assertEqual(effective_settings.embedding_batch_size, 16)
        self.assertFalse(session.committed)
        self.assertTrue(session.closed)


class CLIReportFieldsTest(unittest.TestCase):
    def test_report_fields_are_printed(self):
        from backend.services.producto_presentacion_embedding_seeder import (
            SeedingOutcome,
            SeedingResult,
        )

        result = SeedingResult(
            created=1,
            updated=2,
            unchanged=3,
            stale=0,
            inactive=0,
            failed=0,
            outcomes=(
                SeedingOutcome(
                    id_producto_presentacion=1,
                    status="indexed",
                ),
            ),
        )
        line = cli._format_summary(
            model="all-minilm:latest",
            dim=384,
            result=result,
            elapsed=1.234,
        )
        for token in (
            "model=all-minilm:latest",
            "dim=384",
            "created=1",
            "updated=2",
            "unchanged=3",
            "stale=0",
            "inactive=0",
            "failed=0",
            "elapsed=1.23s",
        ):
            self.assertIn(token, line)


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
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
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


class CLIExitCodeTest(unittest.TestCase):
    def test_exit_code_zero_for_dry_run_even_with_failures(self):
        from backend.services.producto_presentacion_embedding_seeder import (
            SeedingResult,
        )

        result = SeedingResult(
            created=0,
            updated=0,
            unchanged=0,
            stale=0,
            inactive=0,
            failed=5,
        )

        class _FakeSession:
            def __init__(self) -> None:
                self.committed = False
                self.closed = False

            def commit(self) -> None:
                self.committed = True

            def rollback(self) -> None:
                pass

            def close(self) -> None:
                self.closed = True

        session = _FakeSession()

        with mock.patch(
            "backend.scripts.seed_product_presentation_embeddings.load_settings",
            return_value=_settings(),
        ):
            with mock.patch(
                "backend.scripts.seed_product_presentation_embeddings._SessionLocal",
                return_value=session,
            ):
                with mock.patch(
                    "backend.scripts.seed_product_presentation_embeddings.OllamaEmbeddingClient",
                    lambda *a, **k: mock.Mock(),
                ):
                    with mock.patch(
                        "backend.scripts.seed_product_presentation_embeddings.ProductoPresentacionEmbeddingIndexRepository",
                        lambda s: mock.Mock(),
                    ):
                        with mock.patch(
                            "backend.scripts.seed_product_presentation_embeddings.ProductoPresentacionEmbeddingService",
                            lambda s: mock.Mock(),
                        ):
                            with mock.patch(
                                "backend.scripts.seed_product_presentation_embeddings.ProductoPresentacionEmbeddingIndexer",
                                lambda **kwargs: mock.Mock(
                                    index_presentations=mock.Mock(
                                        return_value=result
                                    )
                                ),
                            ):
                                with mock.patch(
                                    "backend.scripts.seed_product_presentation_embeddings.ProductoPresentacionEmbeddingSeeder",
                                    lambda indexer: mock.Mock(
                                        run=mock.Mock(return_value=result)
                                    ),
                                ):
                                    with mock.patch("sys.stdout"):
                                        exit_code = cli.main(["--dry-run"])
        self.assertEqual(exit_code, 0)
        self.assertFalse(session.committed)
        self.assertTrue(session.closed)

    def test_exit_code_one_when_failed_in_real_run(self):
        from backend.services.producto_presentacion_embedding_seeder import (
            SeedingResult,
        )

        result = SeedingResult(
            created=0,
            updated=0,
            unchanged=0,
            stale=0,
            inactive=0,
            failed=1,
        )

        class _FakeSession:
            def __init__(self) -> None:
                self.committed = False
                self.closed = False

            def commit(self) -> None:
                self.committed = True

            def rollback(self) -> None:
                pass

            def close(self) -> None:
                self.closed = True

        session = _FakeSession()

        with mock.patch(
            "backend.scripts.seed_product_presentation_embeddings.load_settings",
            return_value=_settings(),
        ):
            with mock.patch(
                "backend.scripts.seed_product_presentation_embeddings._SessionLocal",
                return_value=session,
            ):
                with mock.patch(
                    "backend.scripts.seed_product_presentation_embeddings.OllamaEmbeddingClient",
                    lambda *a, **k: mock.Mock(),
                ):
                    with mock.patch(
                        "backend.scripts.seed_product_presentation_embeddings.ProductoPresentacionEmbeddingIndexRepository",
                        lambda s: mock.Mock(),
                    ):
                        with mock.patch(
                            "backend.scripts.seed_product_presentation_embeddings.ProductoPresentacionEmbeddingService",
                            lambda s: mock.Mock(),
                        ):
                            with mock.patch(
                                "backend.scripts.seed_product_presentation_embeddings.ProductoPresentacionEmbeddingIndexer",
                                lambda **kwargs: mock.Mock(
                                    index_presentations=mock.Mock(
                                        return_value=result
                                    )
                                ),
                            ):
                                with mock.patch(
                                    "backend.scripts.seed_product_presentation_embeddings.ProductoPresentacionEmbeddingSeeder",
                                    lambda indexer: mock.Mock(
                                        run=mock.Mock(return_value=result)
                                    ),
                                ):
                                    with mock.patch("sys.stdout"):
                                        exit_code = cli.main([])
        self.assertEqual(exit_code, 1)
        self.assertTrue(session.committed)
        self.assertTrue(session.closed)


if __name__ == "__main__":
    unittest.main()
