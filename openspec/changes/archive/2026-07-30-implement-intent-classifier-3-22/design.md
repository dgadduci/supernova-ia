## Context

The legacy `backend/old_project/intent_classifier.py` is a `@dataclass` that stores the message and prompt as mutable fields, builds a hand-written prompt string around a hard-coded `_intents` catalog and an inconsistent JSON example, and then calls `QueryLlm(prompt=self._prompt).request_llm(message)`. The modern stack now has two reusable building blocks:

- `backend/llm/query_llm.py` — a generic LLM client with typed exceptions, payload building, JSON parsing, request/success/failure logging, and an injectable transport/clock.
- `backend/intents/schemas/intent_classification.py` — a typed Pydantic contract that locks the legacy intent names (`IntentName`), a single classified intent (`ClassifiedIntent`), and an aggregated result (`IntentClassificationResult`).

Subphase 3.22 must port the legacy classifier behavior into a thin consumer of those two blocks without re-implementing HTTP, payload, JSON extraction, or raw-response logging.

## Goals / Non-Goals

**Goals:**
- Provide `IntentClassifier.query(message) -> IntentClassificationResult` as the single modern entry point for intent classification.
- Preserve the legacy intent catalog and prompt instructions, fixing only invalid JSON examples, inconsistent intent names (e.g. `set_forma_de_pago` → `set_metodo_de_pago`, `set_metodo_de_envio` → `set_metodo_de_entrega`), and the obvious `"mensaje: "` typo in the example.
- Build the prompt as a local value; do not retain mutable `_message` / `_prompt` state between calls.
- Delegate the LLM call to `QueryLlm.request(prompt)`; let `QueryLlm` own payload, transport, JSON parsing, and HTTP logging.
- Validate the dict returned by `QueryLlm` with `IntentClassificationResult.model_validate`, preserving `intents` order and rejecting unknown intents and malformed payloads.
- Reject non-string and empty-after-trim messages locally before contacting the LLM.
- Propagate `QueryLlmError`, `ValueError`, and `pydantic.ValidationError` without swallowing them, printing, or returning `None`.
- Use a module logger at `INFO` (start, success, failure) and `DEBUG` (validated classification only); do not configure global handlers and do not log prompts/raw responses (already handled by `QueryLlm`).

**Non-Goals:**
- Modifying or importing anything under `backend/old_project/`.
- Adding new intent names or changing the catalog order.
- HTTP, FastAPI, database, `Session`, `Pedido`, recognizer, resolver, processor, dispatcher, handler, queue promotion, or response generation logic.
- Response beautification, retry/backoff, or async classification.
- Caching, conversation state, or multi-message context.
- Subphase 3.23 work (whatever it is — out of scope here).

## Decisions

- **Module location: `backend/llm/intent_classifier.py`.** Keeps the classifier next to its sole dependency (`QueryLlm`) and avoids creating a new top-level package; the schema lives in `backend/intents/schemas/` because it is a cross-cutting contract, while the classifier is a thin orchestration of the LLM client.
- **Class shape: stateless `IntentClassifier` with optional `query_llm` injection.** The classifier holds `self._query_llm: QueryLlm` only; no `_message` / `_prompt` fields. Optional `query_llm` injection enables tests to pass a `Mock`/`SimpleNamespace` with a `request(prompt) -> dict` method without monkey-patching `QueryLlm`.
- **Prompt construction: local helper `_build_prompt(message: str) -> str`.** Returns a fresh string each call; no `self.*` mutation. The prompt content mirrors the legacy `_intents` catalog verbatim, the legacy `_output_struct` JSON schema (with the corrected typos below), and the legacy instructions, with the catalog order, replacement-order rule, and per-product split rule preserved.
- **Prompt fixes (allowed by the project context):**
  - `"mensaje: "` → `"mensaje": "` in the JSON example (typos repeated twice).
  - `set_metodo_de_envio` → `set_metodo_de_entrega` (matches `IntentName.SET_METODO_DE_ENTREGA` and the catalog text "delivery, retiro en local o consumo en salón").
  - `set_forma_de_pago` → `set_metodo_de_pago` (matches `IntentName.SET_METODO_DE_PAGO`).
  - Closing brace placement in the example fixed so the JSON is parseable (`intents` array closing `]` followed by `}` on the outer object).
- **Input validation: explicit local checks, not Pydantic.** `isinstance(message, str)` and `message.strip()` happen before any LLM call; non-strings raise `TypeError`, empty/whitespace strings raise `ValueError`. This matches the legacy public contract and keeps the error message stable for callers.
- **Result validation: `IntentClassificationResult.model_validate`.** The dict returned by `QueryLlm` is passed straight into the Pydantic schema. Order preservation is guaranteed by the schema's `list[ClassifiedIntent]` and the `min_length=1` rule. Unknown intents fail via the existing `IntentName` enum; malformed payloads fail with `pydantic.ValidationError`.
- **Exceptions: propagate, do not catch.** `QueryLlmError` and its subclasses are not wrapped; `pydantic.ValidationError` is not wrapped. Tests assert the original types.
- **Logging: `logging.getLogger(__name__)` only.** `INFO` for `intent_classification start message_chars=N`, `intent_classification success intents_count=N`, and `intent_classification failure error_type=...`. `DEBUG` for the validated result as `intent_classification result: %s`. No global handler, no formatter, no `print`. Prompt and raw-response logging remain owned by `QueryLlm`.
- **No response beautification.** Return the validated `IntentClassificationResult` directly; downstream recognizers/resolvers are responsible for shaping user-facing replies.

## Risks / Trade-offs

- [Risk] Prompt fixes change the JSON example text the LLM has historically seen → Mitigation: only the example payload and the two intent names that already mismatched the catalog are corrected; catalog text and rules are preserved verbatim, so the LLM's contract is unchanged in spirit and aligned with the actual `IntentName` enum.
- [Risk] A future consumer might want to inject custom prompts or extra system messages → Mitigation: keep the helper private (`_build_prompt`) and the public surface minimal; an extension can be added in a dedicated subphase without breaking the contract here.
- [Risk] `QueryLlm` exception types might drift → Mitigation: the classifier does not wrap them; tests assert against the current `QueryLlmError` hierarchy and will fail loudly if those types change.
- [Risk] Logging duplication with `QueryLlm` could cause double lines for the same request → Mitigation: the classifier logs start/success/failure, `QueryLlm` logs request start/success/failure plus DEBUG prompt/response; both are at `INFO`/`DEBUG` from the same root logger hierarchy, so they appear as separate events under the `backend.llm` logger and remain individually useful.

## Migration Plan

1. Add `backend/llm/intent_classifier.py` exporting `IntentClassifier` with the documented surface.
2. Add `backend/tests/test_intent_classifier.py` using a mocked `QueryLlm` (a `SimpleNamespace(query_llm=..., request=lambda prompt: ...)`-style stub); no real network call.
3. Run only the new test module (`PYTHONPATH=. venv/bin/python -m unittest backend.tests.test_intent_classifier`) and `PYTHONPATH=. venv/bin/python -m compileall backend`.
4. Roll back by deleting the module and its test file; no other module is touched.

## Open Questions

None.