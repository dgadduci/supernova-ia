"""Per-document embedding indexer CLI runner.

Subphase 4.6 introduces a CLI entry point that opens a
``_SessionLocal()`` session, instantiates the indexer with the
project's loaded ``Settings`` and an ``OllamaEmbeddingClient(settings)``,
calls ``seeder.run(session)``, and prints a summary.

The CLI owns ``session.commit()``, ``session.rollback()``, and
``session.close()``. The seeder / indexer / repository / service MUST
NOT call those.

The CLI accepts the following flags:

- ``--comercio-id <int>`` — restrict the run to presentations of the
  given comercio.
- ``--producto-id <int>`` — restrict the run to presentations of the
  given producto.
- ``--producto-presentacion-id <int>`` — restrict the run to the
  given producto_presentacion.
- ``--force`` — bypass the unchanged branch for applicable documents.
- ``--dry-run`` — project the catalog and print the planned summary
  without calling Ollama, persisting, or committing.
- ``--batch-size <int>`` — override the embedding client's batch size
  for this run (applied through ``dataclasses.replace`` on the
  frozen ``Settings``; the persisted ``Settings`` is unchanged).

The summary line is::

    model=<embedding_model> dim=<embedding_dimension> created=<n> updated=<n> unchanged=<n> stale=<n> inactive=<n> failed=<n> elapsed=<seconds>s

Plus a per-presentation report::

    id_producto_presentacion=<id> status=<status> reason=<reason>

Exit codes:

- ``0`` when ``--dry-run`` is supplied, when ``failed==0`` in a real
  run, or when the run is otherwise successful.
- ``1`` when ``failed>0`` in a real run or when an unhandled
  exception escapes.
"""
from __future__ import annotations

import argparse
import dataclasses
import sys
import time
from collections.abc import Sequence

from backend.config.settings import load_settings
from backend.dependencies import _SessionLocal
from backend.llm.embedding_client import OllamaEmbeddingClient
from backend.repositories.producto_presentacion_embedding_index_repository import (
    ProductoPresentacionEmbeddingIndexRepository,
)
from backend.services.producto_presentacion_embedding_indexer import (
    ProductoPresentacionEmbeddingIndexer,
)
from backend.services.producto_presentacion_embedding_seeder import (
    ProductoPresentacionEmbeddingSeeder,
    SeedingResult,
)
from backend.services.producto_presentacion_embedding_service import (
    ProductoPresentacionEmbeddingService,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Index the per-document product-presentation embedding catalog."
        )
    )
    parser.add_argument(
        "--comercio-id",
        type=int,
        default=None,
        help="Restrict the run to presentations of the given comercio.",
    )
    parser.add_argument(
        "--producto-id",
        type=int,
        default=None,
        help="Restrict the run to presentations of the given producto.",
    )
    parser.add_argument(
        "--producto-presentacion-id",
        type=int,
        default=None,
        help="Restrict the run to the given producto_presentacion.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Bypass the unchanged branch for applicable documents.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Project the catalog and print the planned summary without "
            "calling Ollama, persisting, or committing."
        ),
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=None,
        help=(
            "Override the embedding client's batch size for this run "
            "(must be a positive integer)."
        ),
    )
    return parser


def _validate_args(args: argparse.Namespace) -> None:
    if args.batch_size is not None and args.batch_size <= 0:
        print(
            f"--batch-size must be a positive integer (got {args.batch_size})",
            file=sys.stderr,
        )
        sys.exit(1)


def _print_per_presentation(result: SeedingResult) -> None:
    for outcome in result.outcomes:
        if outcome.reason is not None:
            print(
                f"id_producto_presentacion={outcome.id_producto_presentacion} "
                f"status={outcome.status} reason={outcome.reason}"
            )
        else:
            print(
                f"id_producto_presentacion={outcome.id_producto_presentacion} "
                f"status={outcome.status}"
            )


def _format_summary(
    *,
    model: str,
    dim: int,
    result: SeedingResult,
    elapsed: float,
) -> str:
    return (
        f"model={model} "
        f"dim={dim} "
        f"created={result.created} "
        f"updated={result.updated} "
        f"unchanged={result.unchanged} "
        f"stale={result.stale} "
        f"inactive={result.inactive} "
        f"failed={result.failed} "
        f"elapsed={elapsed:.2f}s"
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    _validate_args(args)
    base_settings = load_settings()
    if args.batch_size is not None:
        effective_settings = dataclasses.replace(
            base_settings, embedding_batch_size=args.batch_size
        )
    else:
        effective_settings = base_settings
    session = _SessionLocal()
    started = time.monotonic()
    try:
        try:
            embedding_client = OllamaEmbeddingClient(effective_settings)
            index_repository = ProductoPresentacionEmbeddingIndexRepository(session)
            embedding_service = ProductoPresentacionEmbeddingService(session)
            indexer = ProductoPresentacionEmbeddingIndexer(
                session=session,
                embedding_client=embedding_client,
                embedding_service=embedding_service,
                index_repository=index_repository,
                settings=effective_settings,
            )
            seeder = ProductoPresentacionEmbeddingSeeder(indexer)
            result = seeder.run(
                session,
                id_comercio=args.comercio_id,
                id_producto=args.producto_id,
                id_producto_presentacion=args.producto_presentacion_id,
                force=args.force,
                dry_run=args.dry_run,
            )
            if not args.dry_run:
                # Commit once on success. --dry-run is strictly read-only
                # and never commits.
                session.commit()
        except Exception:
            session.rollback()
            raise
        elapsed = time.monotonic() - started
        _print_per_presentation(result)
        print(
            _format_summary(
                model=effective_settings.embedding_model,
                dim=effective_settings.embedding_dimension,
                result=result,
                elapsed=elapsed,
            )
        )
    finally:
        session.close()
    exit_code = 1 if (result.failed > 0 and not args.dry_run) else 0
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
