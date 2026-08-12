# Tasks

## 1. Specification and approval

- [x] 1.1 Inspect the modern `IntentClassifier` path, the prompt
  template body, the controlled corpus, and the focused test files.
- [x] 1.2 Define the static boundary rule, the four contrastive
  examples, the four regression fixtures, and the focused test scope.
- [x] 1.3 Obtain approval of the proposal before implementation.

## 2. Implementation (after approval, by Minimax 3)

Allowed files only:

- `backend/diagnostics/prompt_template.py`
- `backend/diagnostics/intent_corpus.py`
- `backend/tests/test_intent_corpus.py`
- `backend/tests/test_prompt_template_grounding.py`
- `backend/tests/test_intent_classifier.py` only if an existing
  version-literal pin (`test_template_version_bumped_for_second_correction`
  or equivalent) must be updated to the new template version.

- [ ] 2.1 Bump `PROMPT_TEMPLATE_VERSION` to
  `intent-classifier/v1.3.0` and append the numbered rule 8 (boundary
  between `set_metodo_de_entrega` and `set_observacion_pedido`) to
  `_RULES` in `backend/diagnostics/prompt_template.py`.
- [ ] 2.2 Append the four contrastive `Mensaje:` / `Salida:` /
  fenced-JSON examples (portón lateral, cuidado con el perro, envío
  a domicilio, retiro por el local) to `_EXAMPLES` in
  `backend/diagnostics/prompt_template.py`, after the existing
  `modificar_producto` example and before `_OUTPUT_STRUCT`.
- [ ] 2.3 Bump `CORPUS_VERSION` to `intent-corpus/v1.2.0` and append
  the four regression fixtures (`F-REG-OBSERVACION_PEDIDO-PORTON_LATERAL`,
  `F-REG-OBSERVACION_PEDIDO-MASCOTAS`,
  `F-REG-METODO_DE_ENTREGA-ENVIO_DOMICILIO`,
  `F-REG-METODO_DE_ENTREGA-RETIRO_LOCAL`) to
  `CONTROLLED_INTENT_CORPUS` in `backend/diagnostics/intent_corpus.py`.
- [ ] 2.4 Add focused regression tests in
  `backend/tests/test_intent_corpus.py` (one assertion per fixture id
  pinning exactly one intent) and in
  `backend/tests/test_prompt_template_grounding.py`
  (rendered-prompt contains each boundary message + matching intent
  name, plus the new rule 8, plus `PROMPT_TEMPLATE_VERSION ==
  "intent-classifier/v1.3.0"`).
- [ ] 2.5 Update any pre-existing version-literal pin in the four
  allowed test files that hardcodes `intent-classifier/v1.2.0` so the
  suite reflects the new template version. Do not modify any other
  assertion and do not introduce new private surfaces.

## 3. Validation and Codex review

- [ ] 3.1 User runs locally and shares complete output of:

  ```bash
  venv/bin/python -m pytest backend/tests/test_intent_corpus.py backend/tests/test_prompt_template_grounding.py backend/tests/test_intent_classifier.py -q
  venv/bin/python -m ruff check backend/diagnostics/prompt_template.py backend/diagnostics/intent_corpus.py backend/tests/test_intent_corpus.py backend/tests/test_prompt_template_grounding.py backend/tests/test_intent_classifier.py
  venv/bin/python -m compileall -q backend/diagnostics/prompt_template.py backend/diagnostics/intent_corpus.py backend/tests/test_intent_corpus.py backend/tests/test_prompt_template_grounding.py backend/tests/test_intent_classifier.py
  openspec validate calibrate-order-observation-delivery-intent --strict
  ```

- [ ] 3.2 Codex reviews the diff against scope, privacy,
  substring-literal contract, version-pin changes, and the absence of
  any keyword heuristic, second classifier, second LLM call, model /
  settings / transport change, or any change outside the allowed files.
- [ ] 3.3 No commit, no sync, no archive. The user decides the next
  phase closure separately.
