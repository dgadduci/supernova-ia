## 1. Classifier Implementation

- [x] 1.1 Read the legacy `backend/old_project/intent_classifier.py` only as reference; do not import or modify it.
- [x] 1.2 Create `backend/llm/intent_classifier.py` with `__all__ = ["IntentClassifier"]`, a module logger via `logging.getLogger(__name__)`, and no global logging handler configuration.
- [x] 1.3 Implement `IntentClassifier` with `__init__(self, query_llm=None)` storing a single `self._query_llm: QueryLlm` attribute (default `QueryLlm()` when not provided); no `_message` or `_prompt` instance state.
- [x] 1.4 Implement a private `_build_prompt(message: str) -> str` returning a fresh string each call. Preserve the legacy intent catalog text and rules verbatim, and correct only the documented typos in the JSON example (`"mensaje: "` → `"mensaje": "` and the outer `}` placement) and the two intent names (`set_metodo_de_envio` → `set_metodo_de_entrega`, `set_forma_de_pago` → `set_metodo_de_pago`).
- [x] 1.5 Implement `query(message: str) -> IntentClassificationResult` that rejects non-string input with `TypeError`, rejects empty-after-trim input with `ValueError`, calls `self._query_llm.request(self._build_prompt(message))`, and returns `IntentClassificationResult.model_validate(payload)` without printing, swallowing, or returning `None`.
- [x] 1.6 Emit INFO logs for `intent_classification start message_chars=N`, `intent_classification success intents_count=N`, and `intent_classification failure error_type=<class name>`; emit a DEBUG log with the validated result only; do not log prompts or raw LLM responses.

## 2. Boundaries

- [x] 2.1 Keep the module free of `requests`, `fastapi`, `sqlalchemy`, `backend.sessions`, pedido modules, recognizers, resolvers, processor, orchestration, handlers, and context modules.
- [x] 2.2 Do not modify `backend/llm/query_llm.py`, `backend/intents/schemas/intent_classification.py`, or `backend/config/settings.py`.
- [x] 2.3 Do not import anything from `backend/old_project/`.

## 3. Verification

- [x] 3.1 Add `backend/tests/test_intent_classifier.py` using a stub `QueryLlm` (no real HTTP). Cover: single `agregar_producto`; multiple intents preserve order; replacement produces `quitar_producto` then `agregar_producto`; non-string input raises `TypeError`; empty/whitespace input raises `ValueError`; unsupported intent raises `pydantic.ValidationError`; malformed output (`{}`, empty `intents`, empty-after-trim `mensaje`) raises `pydantic.ValidationError`; `QueryLlmError` subclasses propagate unchanged.
- [x] 3.2 Add a source/behavior check confirming the module does not import disallowed side-effect modules and does not configure global logging handlers.
- [x] 3.3 Run `PYTHONPATH=. venv/bin/python -m unittest backend.tests.test_intent_classifier` (14/14 passed).
- [x] 3.4 Run `PYTHONPATH=. venv/bin/python -m compileall backend` (exit 0).