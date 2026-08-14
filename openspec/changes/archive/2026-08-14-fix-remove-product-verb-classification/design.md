# Design: semantic removal classifier guidance

## Decision

Revise the existing static intent-classifier prompt in
`backend/diagnostics/prompt_template.py`. State that a request to remove a
product from the current order means `quitar_producto`. Include
representative formulations — `quita`, `quitar`, `saca`, `sacar`, `retirá`,
`retirar`, `eliminá`, and `eliminar` — while making the action's meaning, not
membership in a closed verb list, the decision criterion. Add concise
examples and bump the prompt-template version.

```text
customer text
  -> existing LLM classifier with revised static prompt
  -> existing IntentName.QUITAR_PRODUCTO
  -> existing dispatcher
  -> existing own-order-line removal recognizer and handler
```

No post-classification rewrite is introduced. This avoids treating arbitrary
add requests as removals or turning prompt wording into a second classifier.
Existing Pedido-scoped recognition, quantity validation, and caller-owned
transaction keep mutation authority.

## Safety

- No new candidate source or product matcher.
- No change to `agregar_producto`, `quitar_producto`, or `modificar_producto`
  execution paths after classification.
- Prompt examples preserve the literal customer message contract.
- The diagnostic version/fingerprint remain static-template-only; raw messages
  are never added to observability.
- Unit tests verify static contract and routing; only the pilot gate verifies
  live LLM semantics.

## Test strategy

- Prompt tests assert the semantic removal rule, representative wording and
  version change.
- Controlled classifier payload tests verify `quitar_producto` schema and
  literal message preservation for the reported and representative forms.
- Dispatcher test proves a `QUITAR_PRODUCTO` result invokes only the existing
  remove orchestrator, not the add one.
- Pilot tests prove the two reported turns and one representative synonym
  decrement rather than increment. They do not claim exhaustive natural-
  language coverage.
