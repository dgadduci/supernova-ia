import logging
from typing import Any, Protocol, cast

from backend.diagnostics import (
    ClassifierCallCompleted,
    ClassifierCallStarted,
    NoopDiagnosticSink,
)
from backend.diagnostics.prompt_template import (
    PROMPT_TEMPLATE_VERSION,
    build_intent_prompt,
    template_fingerprint,
)
from backend.diagnostics.sink import DiagnosticSink
from backend.intents.schemas.intent_classification import IntentClassificationResult
from backend.llm.query_llm import QueryLlm


class _QueryLlmLike(Protocol):
    def request(self, prompt: str) -> dict[str, Any]: ...


logger = logging.getLogger(__name__)


_UNKNOWN_MODEL = "<unknown>"


def _resolve_effective_model(
    query_llm: _QueryLlmLike,
    override: object | None,
) -> str:
    """Return the effective model identifier for a classification attempt.

    Prefers the live ``Settings.llm_model`` exposed by ``QueryLlm`` so the
    runtime diagnostic reflects the model actually used by the transport.
    Falls back to a caller-supplied override for tests that inject a stub
    ``query_llm`` without settings, and finally to ``"<unknown>"`` when no
    information is available.
    """
    settings = getattr(query_llm, "_settings", None)
    if settings is not None:
        configured = getattr(settings, "llm_model", None)
        if configured:
            return str(configured)
    if override:
        return str(override)
    return _UNKNOWN_MODEL


class IntentClassifier:
    def __init__(
        self,
        query_llm: _QueryLlmLike | None = None,
        *,
        sink: DiagnosticSink | None = None,
    ) -> None:
        self._query_llm: _QueryLlmLike = query_llm if query_llm is not None else QueryLlm()
        self._sink: DiagnosticSink = sink if sink is not None else NoopDiagnosticSink()

    def _build_prompt(self, message: str) -> str:
        return build_intent_prompt(message)

    def query(
        self,
        message: str,
        *,
        active_context_type: object | None = None,
        active_pending_intent: object | None = None,
        queued_intent_count: int = 0,
        prompt_name: object | None = None,
        model: object | None = None,
    ) -> IntentClassificationResult:
        if not isinstance(message, str):
            raise TypeError(
                f"El mensaje debe ser una cadena de texto, recibido: {type(message).__name__}"
            )

        cleaned = message.strip()
        if not cleaned:
            raise ValueError("El mensaje no puede estar vacío")

        logger.info("intent_classification start message_chars=%s", len(cleaned))
        rendered_prompt = self._build_prompt(cleaned)
        fingerprint = template_fingerprint()
        effective_model = _resolve_effective_model(self._query_llm, model)
        start_event = ClassifierCallStarted(
            active_context_type=active_context_type,
            has_active_pending_intent=active_pending_intent is not None,
            active_pending_intent=active_pending_intent,
            queued_intent_count=queued_intent_count,
            classifier_class=type(self).__name__,
            classifier_method="query",
            prompt_name=prompt_name,
            model=effective_model,
            prompt_template_version=PROMPT_TEMPLATE_VERSION,
            prompt_fingerprint=fingerprint,
        )
        self._sink.on_classifier_started(start_event)
        parse_errors: list[object] = []
        fallback_state: object = None
        result_payload: object = None
        classified_intents: list[object] = []
        validation_category: str = "transport_error"
        try:
            try:
                payload = self._query_llm.request(rendered_prompt)
            except Exception as exc:
                parse_errors.append(type(exc).__name__)
                logger.info(
                    "intent_classification failure error_type=%s", type(exc).__name__
                )
                raise

            try:
                result = IntentClassificationResult.model_validate(payload)
            except Exception as exc:
                parse_errors.append(type(exc).__name__)
                validation_category = "schema_error"
                logger.info(
                    "intent_classification failure error_type=%s", type(exc).__name__
                )
                raise

            result_payload = result
            classified_intents = [
                str(classified.intent.value) for classified in result.intents
            ]
            intent_count = len(result.intents)
            validation_category = "ok"
            logger.info(
                "intent_classification success intents_count=%s", intent_count
            )
            logger.debug(
                "intent_classification classified_intents=%s "
                "intent_count=%s validation_category=%s "
                "prompt_template_version=%s prompt_fingerprint=%s "
                "effective_model=%s",
                classified_intents,
                intent_count,
                validation_category,
                PROMPT_TEMPLATE_VERSION,
                fingerprint,
                effective_model,
            )
            return result
        finally:
            completed_event = ClassifierCallCompleted(
                intent_count=(
                    len(cast(Any, result_payload).intents)  # type: ignore[union-attr]
                    if result_payload is not None
                    else 0
                ),
                parse_errors=parse_errors,
                fallback_state=fallback_state,
                classified_intents=classified_intents,
                validation_category=validation_category,
                prompt_template_version=PROMPT_TEMPLATE_VERSION,
                prompt_fingerprint=fingerprint,
                effective_model=effective_model,
            )
            self._sink.on_classifier_completed(completed_event)


__all__ = ["IntentClassifier"]
