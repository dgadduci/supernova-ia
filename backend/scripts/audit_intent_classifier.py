"""Read-only audit runner for the IntentClassifier prompt/response path.

The runner invokes the same ``IntentClassifier`` and ``QueryLlm`` code paths
production uses against the versioned controlled corpus and emits a structured
report that records, per fixture, the exact rendered prompt, the parsed model
response, the expected vs. actual ordered intent sequence, the preserved source
fragments, the prompt-template version, and the effective non-secret LLM
settings (model identifier, context length, output limit, temperature,
keep-alive). It deliberately does NOT read from the database, send provider
messages, mutate session/pedido state, or print endpoint URLs, proxy values,
tokens, credentials, or account identifiers.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import pydantic

from backend.config.settings import Settings, load_settings
from backend.diagnostics import (
    CONTROLLED_INTENT_CORPUS,
    CORPUS_VERSION,
    PROMPT_TEMPLATE_VERSION,
    IntentFixture,
    iter_fixtures,
    prompt_fingerprint,
    template_identity,
)
from backend.intents.schemas.intent_classification import (
    IntentClassificationResult,
    IntentName,
)
from backend.llm.intent_classifier import IntentClassifier
from backend.llm.query_llm import QueryLlm, QueryLlmError

__all__ = [
    "AuditReport",
    "FixtureReport",
    "build_report",
    "effective_non_secret_settings",
    "main",
    "render_report",
]


@dataclass(slots=True)
class FixtureReport:
    fixture_id: str
    description: str
    expected_intents: list[str]
    actual_intents: list[str]
    matched: bool
    failure_category: str
    expected_source_fragments: list[str]
    preserved_source_fragments: list[str]
    parsed_response: dict[str, Any] | None
    rendered_prompt: str
    prompt_fingerprint: str
    prompt_template_version: str
    error: str | None = None
    contamination_offenders: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "fixture_id": self.fixture_id,
            "description": self.description,
            "expected_intents": list(self.expected_intents),
            "actual_intents": list(self.actual_intents),
            "matched": self.matched,
            "failure_category": self.failure_category,
            "expected_source_fragments": list(self.expected_source_fragments),
            "preserved_source_fragments": list(self.preserved_source_fragments),
            "parsed_response": self.parsed_response,
            "rendered_prompt": self.rendered_prompt,
            "prompt_fingerprint": self.prompt_fingerprint,
            "prompt_template_version": self.prompt_template_version,
            "error": self.error,
            "contamination_offenders": list(self.contamination_offenders),
        }


@dataclass(slots=True)
class AuditReport:
    corpus_version: str
    prompt_template_version: str
    prompt_template_hash: str
    effective_settings: dict[str, Any]
    fixtures: list[FixtureReport] = field(default_factory=list)

    @property
    def passed(self) -> int:
        return sum(1 for fixture in self.fixtures if fixture.matched)

    @property
    def failed(self) -> int:
        return sum(1 for fixture in self.fixtures if not fixture.matched)

    def to_dict(self) -> dict[str, Any]:
        return {
            "corpus_version": self.corpus_version,
            "prompt_template_version": self.prompt_template_version,
            "prompt_template_hash": self.prompt_template_hash,
            "effective_settings": dict(self.effective_settings),
            "passed": self.passed,
            "failed": self.failed,
            "total": len(self.fixtures),
            "fixtures": [fixture.to_dict() for fixture in self.fixtures],
        }


def effective_non_secret_settings(settings: Settings) -> dict[str, Any]:
    """Return the non-secret LLM settings that production actually sends."""
    return {
        "model": settings.llm_model,
        "num_ctx": settings.llm_num_ctx,
        "num_predict": settings.llm_num_predict,
        "temperature": 0,
        "keep_alive": settings.llm_keep_alive,
    }


def _classify_fixture(
    classifier: IntentClassifier,
    fixture: IntentFixture,
) -> tuple[
    IntentClassificationResult | None,
    str,
    str | None,
    str,
    str,
]:
    """Run one fixture through the classifier and capture the audit evidence."""
    cleaned = fixture.message.strip()
    prompt = classifier._build_prompt(cleaned)
    fingerprint = prompt_fingerprint(prompt)
    result = classifier.query(fixture.message)
    return result, fingerprint, None, prompt, "ok"


def _contamination_offenders(
    fixture_message: str,
    result: IntentClassificationResult | None,
) -> list[str]:
    """Return ``mensaje`` values that are not substrings of the fixture message.

    A response is contaminated when at least one intent's ``mensaje`` field
    reproduces content not present in the current fixture message. This
    catches the failure mode where the upstream LLM copies from the prompt
    examples or the catalog instead of grounding every intent in the actual
    customer message.
    """
    if result is None:
        return []
    baseline = fixture_message.strip()
    offenders: list[str] = []
    for item in result.intents:
        returned = item.mensaje.strip()
        if returned and returned not in baseline:
            offenders.append(returned)
    return offenders


def _evaluate_fixture(
    expected_intents: tuple[IntentName, ...],
    expected_fragments: tuple[str, ...],
    result: IntentClassificationResult | None,
    prompt: str,
    fingerprint: str,
    error: str | None,
    contamination: list[str] | None = None,
) -> tuple[bool, str, list[str]]:
    if error is not None:
        return False, "transport_error", []
    if result is None:
        return False, "schema_error", []
    if contamination:
        return False, "contamination_detected", list(contamination)
    actual_intents = [str(item.intent.value) for item in result.intents]
    expected_list = [str(item.value) for item in expected_intents]
    if tuple(actual_intents) != tuple(expected_list):
        return False, "intent_mismatch", []
    if expected_fragments:
        joined_sources = " \n".join(item.mensaje for item in result.intents)
        preserved = [
            fragment
            for fragment in expected_fragments
            if fragment in joined_sources
        ]
        if tuple(preserved) != tuple(expected_fragments):
            return False, "fragment_missing", preserved
    return True, "ok", [
        fragment
        for fragment in expected_fragments
        if fragment in " \n".join(item.mensaje for item in result.intents)
    ]


def build_report(
    *,
    classifier_factory: Callable[[], IntentClassifier],
    settings: Settings,
    fixtures: list[IntentFixture] | None = None,
) -> AuditReport:
    """Run the corpus through a fresh classifier per fixture and build the report."""
    target_fixtures = (
        list(fixtures) if fixtures is not None else list(iter_fixtures())
    )
    identity = template_identity()
    report = AuditReport(
        corpus_version=CORPUS_VERSION,
        prompt_template_version=identity["prompt_template_version"],
        prompt_template_hash=identity["prompt_template_hash"],
        effective_settings=effective_non_secret_settings(settings),
    )
    for fixture in target_fixtures:
        classifier = classifier_factory()
        try:
            (
                result,
                fingerprint,
                _,
                prompt,
                _category,
            ) = _classify_fixture(classifier, fixture)
            contamination = _contamination_offenders(fixture.message, result)
            matched, failure_category, preserved = _evaluate_fixture(
                fixture.expected_intents,
                fixture.expected_source_fragments,
                result,
                prompt,
                fingerprint,
                None,
                contamination,
            )
            error_text: str | None = None
        except (QueryLlmError, pydantic.ValidationError, ValueError, TypeError) as exc:
            result = None
            cleaned = fixture.message.strip()
            prompt = classifier._build_prompt(cleaned)
            fingerprint = prompt_fingerprint(prompt)
            matched = False
            failure_category = type(exc).__name__
            preserved = []
            contamination = []
            error_text = type(exc).__name__
        report.fixtures.append(
            FixtureReport(
                fixture_id=fixture.fixture_id,
                description=fixture.description,
                expected_intents=[
                    str(item.value) for item in fixture.expected_intents
                ],
                actual_intents=(
                    [str(item.intent.value) for item in result.intents]
                    if result is not None
                    else []
                ),
                matched=matched,
                failure_category=failure_category,
                expected_source_fragments=list(fixture.expected_source_fragments),
                preserved_source_fragments=preserved,
                parsed_response=(
                    result.model_dump(mode="json") if result is not None else None
                ),
                rendered_prompt=prompt,
                prompt_fingerprint=fingerprint,
                prompt_template_version=PROMPT_TEMPLATE_VERSION,
                error=error_text,
                contamination_offenders=contamination,
            )
        )
    return report


def render_report(report: AuditReport) -> str:
    lines = [
        "IntentClassifier controlled audit",
        f"  corpus_version           : {report.corpus_version}",
        f"  prompt_template_version  : {report.prompt_template_version}",
        f"  prompt_template_hash     : {report.prompt_template_hash}",
        f"  effective_model          : {report.effective_settings.get('model')}",
        f"  num_ctx                  : {report.effective_settings.get('num_ctx')}",
        f"  num_predict              : {report.effective_settings.get('num_predict')}",
        f"  temperature              : {report.effective_settings.get('temperature')}",
        f"  keep_alive               : {report.effective_settings.get('keep_alive')}",
        f"  total                    : {len(report.fixtures)}",
        f"  passed                   : {report.passed}",
        f"  failed                   : {report.failed}",
        "",
    ]
    for fixture in report.fixtures:
        status = "PASS" if fixture.matched else "FAIL"
        lines.append(
            f"[{status}] {fixture.fixture_id} :: {fixture.description}"
        )
        lines.append(
            f"  failure_category          : {fixture.failure_category}"
        )
        lines.append(
            f"  expected_intents          : {fixture.expected_intents}"
        )
        lines.append(
            f"  actual_intents            : {fixture.actual_intents}"
        )
        if fixture.expected_source_fragments:
            lines.append(
                f"  expected_source_fragments : {fixture.expected_source_fragments}"
            )
            lines.append(
                f"  preserved_source_fragments: {fixture.preserved_source_fragments}"
            )
        if fixture.contamination_offenders:
            lines.append(
                f"  contamination_offenders   : {fixture.contamination_offenders}"
            )
        if fixture.error:
            lines.append(f"  error                     : {fixture.error}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _parse_fixture_ids(raw: str | None) -> set[str] | None:
    if raw is None or not raw.strip():
        return None
    return {item.strip() for item in raw.split(",") if item.strip()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="audit_intent_classifier",
        description=(
            "Read-only audit runner for the IntentClassifier prompt and "
            "response contract."
        ),
    )
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format (default: text).",
    )
    parser.add_argument(
        "--only",
        default=None,
        help=(
            "Comma-separated list of fixture ids to evaluate. Empty runs "
            "the full corpus."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Render prompts and validate fixture framing without performing "
            "the LLM call. Useful for template review in CI."
        ),
    )
    args = parser.parse_args(argv)

    settings = load_settings()
    only_ids = _parse_fixture_ids(args.only)
    fixtures = (
        [fixture for fixture in CONTROLLED_INTENT_CORPUS if fixture.fixture_id in only_ids]
        if only_ids is not None
        else list(CONTROLLED_INTENT_CORPUS)
    )

    if args.dry_run:
        report = AuditReport(
            corpus_version=CORPUS_VERSION,
            prompt_template_version=PROMPT_TEMPLATE_VERSION,
            prompt_template_hash=template_identity()["prompt_template_hash"],
            effective_settings=effective_non_secret_settings(settings),
        )
        for fixture in fixtures:
            preview = IntentClassifier()
            cleaned = fixture.message.strip()
            prompt = preview._build_prompt(cleaned)
            report.fixtures.append(
                FixtureReport(
                    fixture_id=fixture.fixture_id,
                    description=fixture.description,
                    expected_intents=[
                        str(item.value) for item in fixture.expected_intents
                    ],
                    actual_intents=[],
                    matched=False,
                    failure_category="dry_run",
                    expected_source_fragments=list(fixture.expected_source_fragments),
                    preserved_source_fragments=[],
                    parsed_response=None,
                    rendered_prompt=prompt,
                    prompt_fingerprint=prompt_fingerprint(prompt),
                    prompt_template_version=PROMPT_TEMPLATE_VERSION,
                )
            )
    else:
        def _classifier_factory() -> IntentClassifier:
            return IntentClassifier(query_llm=QueryLlm(settings=settings))

        report = build_report(
            classifier_factory=_classifier_factory,
            settings=settings,
            fixtures=fixtures,
        )

    if args.format == "json":
        json.dump(report.to_dict(), sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
    else:
        sys.stdout.write(render_report(report))
    return 0 if report.failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
