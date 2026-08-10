# Stabilize intent classification for the current Qwen deployment

## Objective

Establish why the production intent classifier produces incorrect intent sets for
otherwise unambiguous customer messages, make the prompt and model response
auditable in a controlled diagnostic path, and apply the smallest prompt or
contract adjustment that makes the existing intent catalog reliable with the
currently deployed Qwen model.

## Verified production evidence

The deferred production path was exercised with a controlled WhatsApp client:
webhook receipt -> inbound work item -> `run_inbound_processing` -> outbox ->
`run_outbound_dispatch`. The workers processed and dispatched correctly.

The classification result was not reliable:

- `resumen de pedido` was sometimes handled as payment selection in the real
  deferred turn, although a rollback-only direct pipeline invocation resolved
  it as `consultar_resumen_pedido`.
- `Pago en Efectivo (prueba cierre)` was received exactly as sent and the
  deferred turn returned a summary; a rollback-only direct pipeline invocation
  resolved the same text as `agregar_producto` with pending resolution.
- A controlled 27-case audit against the production LLM returned 23 exact
  expected results. It failed `set_observacion_producto`,
  `set_observacion_pedido`, and `set_metodo_de_pago`; the payment case expanded
  into unrelated product and address intents.

The user reports a model change from Qwen 27B in earlier changes to Qwen 7B in
the current deployment. The effective Railway model and request settings must
be verified without exposing credentials.

## Current execution path

`ProviderInboundMessageCoordinator.process_lease()` loads the transient
work-item body and invokes `process_incoming_message`. With no pending context,
`dispatch_initial_message` constructs `IntentClassifier`, which builds its
prompt and calls `QueryLlm.request`. The validated result is routed to the
existing dispatcher, then the response mapper stages one outbox row. Successful
work-item finalization clears the inbound body, so after-the-fact production
inspection cannot reconstruct the effective prompt or model response.

## Scope and non-goals

- Define a controlled, read-only classifier audit that records the exact prompt
  template, effective non-secret LLM settings, parsed response, and outcome for
  each curated fixture message.
- Add safe per-turn diagnostic evidence sufficient to correlate a deferred
  classification with the prompt template/version, effective model, response
  shape, and resulting intents, without logging raw customer text or secrets.
- Evaluate prompt instructions and examples for Qwen 7B compatibility and
  apply only the minimal correction required by the approved acceptance corpus.
- Add deterministic tests for the prompt contract and the discovered failure
  cases, plus a controlled Railway verification procedure.

Non-goals: no new intents, no LLM provider/model switch, no changes to product
recognition policy, no queue/worker automation, no migration, no persistence of
raw prompts or customer messages, and no changes to pending-candidate rules.

## Shared boundary, fallback, and transaction ownership

The classifier remains responsible only for one typed classification request.
It does not own session, pedido, work-item, outbox, or transaction control.
`process_incoming_message_transactional` and
`ProviderInboundMessageCoordinator.process_lease()` retain commit/rollback
ownership.

Malformed/technical LLM outcomes retain the existing technical-failure path;
this change must not silently reinterpret them as product actions. A valid but
unsupported or multi-intent classification remains governed by the existing
dispatcher contracts. No fallback may widen pending candidate sets, create a
pedido, or mutate a payment/delivery selection.

## Observability, expected files, and validation

Expected implementation surface is limited to `backend/llm/intent_classifier.py`,
`backend/llm/query_llm.py`, the existing diagnostics boundary, focused classifier
tests, and a small controlled audit CLI or fixture module. Prompt/response text
is permitted only in explicitly invoked fixture diagnostics; runtime logs and
durable records may contain only redacted or derived evidence.

Focused validation, to be run by the user locally:

`venv/bin/python -m pytest backend/tests/test_intent_classifier.py backend/tests/test_diagnostics.py -q`

`venv/bin/python -m ruff check backend/llm/intent_classifier.py backend/llm/query_llm.py backend/diagnostics backend/tests/test_intent_classifier.py backend/tests/test_diagnostics.py`

`venv/bin/python -m compileall -q backend/llm backend/diagnostics`

`openspec validate stabilize-intent-classifier-qwen7b --strict`

## Reversibility and deferred limitations

The change is reversible by restoring the prior prompt/diagnostic behavior; it
requires no schema or migration rollback. Model replacement and automatic worker
deployment remain deferred until the controlled corpus and a fresh WhatsApp
end-to-end closure test both pass.
