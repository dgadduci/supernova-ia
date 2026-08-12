# Calibrate the order-observation vs delivery-method boundary

## Objective

Sharpen the static classifier prompt so that `set_observacion_pedido` and
`set_metodo_de_entrega` no longer overlap on messages that mention "entrega"
but describe logistics, access, route, building, security, pets, or care
indications, while continuing to route genuine modality selection
(delivery / pickup / dine-in) to `set_metodo_de_entrega`. The boundary must
be expressed inside the existing prompt template and controlled corpus so
the change is auditable, reversible, and grounded in the same single
classifier pass.

## Verified current execution path

The modern classification path is:

1. `backend/llm/intent_classifier.py::IntentClassifier.query(message)`
   validates the message, builds the prompt via
   `backend/diagnostics/prompt_template.py::build_intent_prompt`, calls the
   injected `QueryLlm.request`, validates the response with
   `IntentClassificationResult`, and propagates errors unchanged.
2. The prompt body (`backend/diagnostics/prompt_template.py`) embeds an
   intent catalog, static rules, the existing few-shot examples
   (`ver_metodos_de_entrega`, `set_observacion_producto`,
   `set_observacion_pedido`, `set_direccion_entrega`,
   `set_metodo_de_pago`, `modificar_producto`), the JSON output structure
   contract, and the current customer message as the last section.
3. `backend/diagnostics/intent_corpus.py::CONTROLLED_INTENT_CORPUS`
   pins the expected intent sequence per fixture and a substring fragment
   for the production regressions called out by the proposal
   (`F-REG-PAGO-EFECTIVO`, `F-REG-OBSERVACION_PRODUCTO`,
   `F-REG-OBSERVACION_PEDIDO`).
4. `backend/tests/test_intent_corpus.py`,
   `backend/tests/test_prompt_template_grounding.py`, and
   `backend/tests/test_intent_classifier.py` pin the corpus shape, the
   substring-literal contract, and the prompt structure with version pins
   (`intent-classifier/v1.2.0`, `intent-corpus/v1.1.0`).
5. The runtime `ClassifierCallStarted` / `ClassifierCallCompleted`
   diagnostic events expose the static `template_fingerprint` (SHA-256 of
   the prompt body), not the rendered prompt or the customer message.

Today there is no rule or example that distinguishes
"la entrega es por el portón lateral" (an order observation) from
"quiero envío a domicilio" (a delivery method selection). When the LLM
collapses both into `set_metodo_de_entrega`, the dispatcher routes an
access instruction into the delivery-method branch and the observation
is lost. The production template fingerprint is stable
(`intent-classifier/v1.2.0`) but the prompt body itself provides no static
signal for this boundary.

## Scope

In scope, and only in scope, for this change:

- Extend `_RULES` in `backend/diagnostics/prompt_template.py` with a
  static boundary rule that documents the
  `set_metodo_de_entrega` vs `set_observacion_pedido` contract.
- Extend `_EXAMPLES` in `backend/diagnostics/prompt_template.py` with
  the four contrastive boundary cases called out in the contract:
  - `La entrega es por el portón lateral` → `set_observacion_pedido`
  - `Cuidado con el perro` → `set_observacion_pedido`
  - `Quiero envío a domicilio` → `set_metodo_de_entrega`
  - `Lo retiro por el local` → `set_metodo_de_entrega`
- Bump `PROMPT_TEMPLATE_VERSION` and `CORPUS_VERSION` to reflect the new
  body.
- Add the four boundary cases as controlled fixtures in
  `backend/diagnostics/intent_corpus.py`, each pinning exactly one intent
  and the literal substring expected from the current message.
- Add focused regression tests in
  `backend/tests/test_intent_corpus.py` and
  `backend/tests/test_prompt_template_grounding.py` that pin the four
  boundary fixtures and the new static rule / example contract.
- Update `test_template_version_bumped_for_second_correction` (and any
  other version-literal pin that survives the bump) to the new template
  version, keeping one narrow assertion in this change only.

## Non-goals

- No keyword / regex heuristics, no second classifier, no second LLM
  call, no change to model, transport, or `Settings`.
- No change to `IntentName` enum, `IntentClassificationResult` /
  `ClassifiedIntent` schemas, the dispatcher, pending context,
  persistence of `Pedido`, observations persistence, the order mapper,
  the outbox, transactions, product recognition, migrations, endpoints,
  workers, Railway configuration, or deploy.
- No sync, archive, commit, or deploy during this phase.

## Shared boundary, fallback, and transaction ownership

The classifier in `backend/llm/intent_classifier.py` and the prompt
template in `backend/diagnostics/prompt_template.py` remain the only
authority. `backend/diagnostics/intent_corpus.py` remains the audit-grade
fixture set; the controlled audit runner is not changed.

There is no runtime fallback. A mismatch between the rendered prompt and
a corpus fixture is observed by the audit; it never falls back to a
keyword router, a second classifier pass, or a default intent. The
classifier still propagates `QueryLlm` / Pydantic errors unchanged and
still does not own commit, rollback, or any business transaction.

The runtime fingerprint (`template_fingerprint()`) automatically
reflects the new prompt body; no diagnostic event format changes.

## Observability

The existing `ClassifierCallStarted` and `ClassifierCallCompleted`
events already carry the static `prompt_fingerprint`, so the SHA-256 of
the new body is observable without any new event shape. The new test
suite asserts that each boundary fixture pins exactly one intent and the
substring-literal contract that already exists
(`test_every_fixture_message_is_present_in_its_rendered_prompt`,
`test_substring_literal_contract_is_documented`).

No new logging is added.

## Expected files

- `backend/diagnostics/prompt_template.py`
- `backend/diagnostics/intent_corpus.py`
- `backend/tests/test_intent_corpus.py`
- `backend/tests/test_prompt_template_grounding.py`
- `backend/tests/test_intent_classifier.py` only if a version-literal
  pin in the existing file must be updated to match the new template
  version
- `openspec/changes/calibrate-order-observation-delivery-intent/`
  (this change's planning artifacts)

## Focused tests and validation

The user will run locally:

```bash
venv/bin/python -m pytest backend/tests/test_intent_corpus.py backend/tests/test_prompt_template_grounding.py backend/tests/test_intent_classifier.py -q
venv/bin/python -m ruff check backend/diagnostics/prompt_template.py backend/diagnostics/intent_corpus.py backend/tests/test_intent_corpus.py backend/tests/test_prompt_template_grounding.py backend/tests/test_intent_classifier.py
venv/bin/python -m compileall -q backend/diagnostics/prompt_template.py backend/diagnostics/intent_corpus.py backend/tests/test_intent_corpus.py backend/tests/test_prompt_template_grounding.py backend/tests/test_intent_classifier.py
openspec validate calibrate-order-observation-delivery-intent --strict
```

## Rollback and deferred limitations

Reverting the prompt template, the corpus, and the focused tests
restores the previous classification contract byte-for-byte
(`PROMPT_TEMPLATE_VERSION` and `CORPUS_VERSION` revert). No DB /
deploy state needs rollback.

Deferred: a separate, follow-up calibration phase may add more
boundary cases (e.g. transfer to a third party, reception by a
neighbour) once this phase has been audited and approved. That phase
will be tracked under its own OpenSpec change.
