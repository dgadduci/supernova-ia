from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from backend.config.settings import load_settings
from backend.dependencies import _SessionLocal
from backend.llm.embedding_client import OllamaEmbeddingClient
from backend.recognizers.fuzzy_product_recognizer import FuzzyProductRecognizer
from backend.services.product_presentation_vector_search_service import (
    ProductPresentationVectorSearchService,
)
from backend.services.product_recognition_calibration_policy import validate_dataset
from backend.services.product_recognition_calibration_report import (
    write_diagnostic_atomic,
    write_report_atomic,
)
from backend.services.product_recognition_calibration_runner import (
    ProductRecognitionCalibrationRunner,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--commerce-id", type=int)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--diagnose", action="store_true", help="Emit a per-case diagnostic evidence file in addition to the JSON report.")
    parser.add_argument("--diagnose-output", help="Path for the diagnostic evidence file. Defaults to <output>.diagnose.json when omitted.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.limit is not None and args.limit <= 0:
        print("invalid limit", file=sys.stderr)
        return 2
    try:
        with Path(args.dataset).open(encoding="utf-8") as file:
            dataset = json.load(file)
        validate_dataset(dataset)
    except (OSError, ValueError, TypeError) as error:
        print(f"invalid dataset: {type(error).__name__}", file=sys.stderr)
        return 2
    session = None
    try:
        session = _SessionLocal()
        settings = load_settings()
        embedding_client = OllamaEmbeddingClient(settings=settings)
        runner = ProductRecognitionCalibrationRunner(
            recognizer=FuzzyProductRecognizer(),
            embedding_client=embedding_client,
            vector_search_factory=lambda: ProductPresentationVectorSearchService(session, settings),
            session=session,
        )
        report = runner.run(dataset, commerce_id=args.commerce_id, limit=args.limit)
        diagnostic_records = report.pop("_diagnostic_records", [])
        write_report_atomic(report, args.output)
        if args.diagnose:
            diagnose_output = args.diagnose_output or f"{args.output}.diagnose.json"
            write_diagnostic_atomic(diagnostic_records, diagnose_output)
        print(f"cases={report['case_count']} policies={report['policy_count']} eligibility={report['eligibility']['status']}")
        return 0
    except (RuntimeError, OSError, ValueError, TypeError):
        return 1
    finally:
        if session is not None:
            session.close()


if __name__ == "__main__":
    raise SystemExit(main())
