"""Executable seeder for the persisted product alias set.

Run with::

    PYTHONPATH=. venv/bin/python -m backend.scripts.seed_product_aliases

The script opens one outer transaction, runs the seeder, commits on
success, and rolls back on any failed required mapping. Unrelated alias
rows are never modified.
"""
from __future__ import annotations

import argparse
import sys

from backend.dependencies import _SessionLocal
from backend.services.exceptions import UnsafeAliasSeederMapping
from backend.services.producto_alias_seeder import (
    PRODUCTO_WIDE_SEEDS,
    SeederResult,
    run_seeder,
)


def _format_result(result: SeederResult) -> str:
    return (
        f"inserted={result.inserted} "
        f"unchanged={result.unchanged} "
        f"skipped={result.skipped} "
        f"failed={result.failed}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Seed the persisted product alias set."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Resolve seeds without persisting; prints counts only.",
    )
    args = parser.parse_args(argv)
    session = _SessionLocal()
    try:
        try:
            if args.dry_run:
                from backend.services.producto_alias_seeder import _resolve_target

                matched = 0
                skipped = 0
                for seed in PRODUCTO_WIDE_SEEDS:
                    resolution = _resolve_target(session, seed)
                    if resolution is None:
                        skipped += 1
                    else:
                        matched += 1
                print(
                    f"dry-run: matched={matched} skipped={skipped} total={len(PRODUCTO_WIDE_SEEDS)}"
                )
                return 0
            result = run_seeder(session)
            session.commit()
        except UnsafeAliasSeederMapping as exc:
            session.rollback()
            print(f"FAILED required mapping; transaction rolled back: {exc}", file=sys.stderr)
            return 1
        except Exception as exc:  # pragma: no cover - defensive
            session.rollback()
            print(f"seeder aborted; transaction rolled back: {exc}", file=sys.stderr)
            raise
        print(_format_result(result))
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
