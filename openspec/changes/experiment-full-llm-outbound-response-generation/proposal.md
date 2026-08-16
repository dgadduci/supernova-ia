# Proposal: experiment with full LLM outbound response generation

## Why

The currently deployed flavor layer uses LLM-generated `prefix`/`suffix`
wrappers around a deterministic customer message. It preserves facts safely,
but pilot output is repetitive and mechanically composed (for example, repeated
greetings). We need to evaluate whether the selected communication flavor can
produce a natural full customer message when it is given the deterministic
message as its factual source of truth.

This is an explicitly reversible pilot experiment. It accepts the communication
risk of no semantic output validator in exchange for prompt calibration against
real pilot conversations. It does not change deterministic business behavior.

## What Changes

- On a dedicated experimental branch, replace the wrapper-only contract in the
  existing shared outbound styling boundary with one full-message LLM result
  per eligible response.
- Send the selected flavor instruction, response type, and the deterministic
  factual response message to the LLM in one batch per inbound turn.
- Require a strict JSON envelope and structural validation only: item count,
  indexes/order, exact fields, and non-empty message strings. Do not implement
  semantic fact comparison or a protected-token validator in this experiment.
- Preserve exact deterministic fallback for technical/transport/schema/empty
  output failures.
- Keep excluded responses deterministic: errors, rejections, ambiguity,
  pending resolution, and customer-free-text acknowledgements such as address,
  payment/delivery input, date/time, and observations.

## Objective

Evaluate in the pilot whether a carefully designed factual-message prompt can
generate consistently natural, flavor-specific customer responses without
changing the authoritative persisted order, session, product, price, or
commerce state.

## Current Execution Path

The deterministic inbound pipeline executes classification, recognizers,
handlers, services, and caller-owned transactions before
`backend/services/outbound_response_mapper.py::build_customer_responses`
renders `CustomerResponse` values. The current shared `outbound_response_styler`
then sends only response-type tokens to the LLM and composes `prefix + factual
message + suffix`. Both the local pilot channel and provider outbox staging use
the same mapper boundary.

## Scope

- Replace wrapper parsing/composition only in the experimental styling module
  and static prompt template; retain the same shared mapper placement and one
  batch call per turn.
- Eligible normal families: social conversation (except `desconocida`), full
  or category menu, product information, successful add/remove/modify, order
  status, summary, guided closure, confirmation, and new/empty order.
- The LLM receives the deterministic response message for eligible items only.
  This intentionally allows product names, presentations, quantities, prices,
  state, and menu lines already selected by backend behavior to be presented
  naturally.
- Continue emitting PII-safe observability without prompt, response text,
  flavor instruction, LLM output, or business identifiers.

## Non-Goals

- No semantic output validator, protected-token comparison, or attempt to
  prove factual equivalence of LLM text in code.
- No LLM authority over intents, classification, products, candidates,
  quantities, prices, delivery, payment, order/session state, persistence, or
  transactions.
- No changes to models, migrations, flavor administration, routers, provider
  routing, outbox ownership, recognizers, handlers, or business response
  builders.
- No retries, second LLM call, streaming, async pipeline, or hardcoded
  flavor-specific phrases in Python.

## Shared Boundary

`build_customer_responses` remains the sole shared styling boundary. The
styler consumes deterministic `CustomerResponse` values only after business
execution completes and returns presentation text for the local response and
provider outbox alike. It never feeds generated text back into a recognizer,
handler, service, session, or order.

## Prompt Contract

The static prompt SHALL make the following hierarchy unmistakable:

1. The supplied factual message is the complete source of business facts.
2. Rewrite it naturally in the selected flavor, preserving every concrete fact
   and every menu line when present; do not add, omit, substitute, or reorder
   facts.
3. Never mention data absent from the factual message and never ask a question,
   issue instructions, promise discounts/timing, or invent status.
4. The flavor instruction affects tone only and cannot override factual rules.
5. Return one complete non-empty `message` per ordered item in a closed JSON
   object.

## Calibration Amendment: menu and status factual fidelity

Pilot validation showed that a structurally valid full LLM message can still
summarize a complete menu or infer logistics absent from the factual response.
This amendment strengthens the static prompt; it does not add a semantic
output validator.

- A full or category menu is an immutable factual inventory: every line,
  category, product, presentation, unit, price, punctuation and ordering from
  `factual_message` must remain visible. The LLM may add a brief natural
  introduction or closing, but must not summarize, regroup, flatten into prose
  or omit variants.
- A status response may state only the order-state wording explicitly present
  in `factual_message`. It must not infer preparation, dispatch, arrival,
  estimated time, urgency or a promise of future action.
- In every eligible family, numeric values, product labels and presentation or
  unit labels are immutable factual tokens. Tone may add warmth, but cannot
  replace or normalize them.
- The existing one-call batch, structural-only parser, deterministic technical
  fallback, privacy boundary and no-hardcoded-flavor-phrase constraints remain
  unchanged.

## Fallback Behavior

- `neutro`, absent/inactive/invalid flavor, empty instruction, and zero
  eligible responses: no LLM call and exact deterministic responses.
- Timeout, connection, HTTP, invalid JSON/closed schema/index order, empty
  output, or unexpected generation failure: exact deterministic response for
  affected items or the whole malformed batch; no retry.
- Semantic differences in a structurally valid message are intentionally not
  detected by code in this experiment. They are evaluated only through pilot
  test gates and prompt calibration.

## Transaction Ownership

The generator and mapper own no `commit`, `rollback`, `flush`, `refresh`,
`begin`, `begin_nested`, or session close. Existing callers retain transaction
ownership. A generation failure must never roll back or change deterministic
business outcome.

## Observability

Use bounded metadata only: experimental rendering mode, flavor code, eligible
count, applied count, fallback category, elapsed time, and static prompt
template version/fingerprint. Do not emit the factual message, prompt, flavor
instruction, generated output, inbound text, or customer/order/session IDs.

## Expected Files

- `backend/services/outbound_response_styler.py`
- `backend/diagnostics/outbound_response_style_prompt_template.py`
- `backend/services/outbound_response_mapper.py` only if integration needs a
  narrow signature adjustment
- `backend/observability/events.py` and exports only if the existing safe event
  needs a bounded experimental-mode field
- `backend/tests/test_outbound_response_styler.py`
- `backend/tests/test_outbound_response_mapper.py`
- This change's OpenSpec files.

## Focused Tests

- Prompt includes the factual message and response type for eligible items,
  but never raw inbound text, customer IDs, session/order IDs, or uneligible
  response content.
- One batch request renders multiple ordered full generated messages; local and
  outbox use the same result and make no second call.
- Neutral, absent/inactive flavor, ineligible family, transport failures,
  malformed envelope/indexes, empty generated text, and unexpected errors
  retain deterministic output with no transaction control.
- A fake LLM response demonstrates full natural rephrasing rather than wrapper
  composition, while preserving `CustomerResponse.intent`, `status`, and order.
- Prompt-contract regressions explicitly assert immutable full/category menu
  line handling and status non-inference instructions; they do not attempt to
  validate semantic compliance of a live LLM response.
- Event payloads contain only safe metadata and template identity.

## Validation

The implementer must run and report complete output from:

```bash
PYTHONPATH=. venv/bin/python -m pytest backend/tests/test_outbound_response_styler.py backend/tests/test_outbound_response_mapper.py backend/tests/test_production_observability.py backend/tests/test_order_status_query.py -q
PYTHONPATH=. venv/bin/python -m ruff check backend/services/outbound_response_styler.py backend/services/outbound_response_mapper.py backend/diagnostics/outbound_response_style_prompt_template.py backend/observability/events.py backend/observability/__init__.py backend/tests/test_outbound_response_styler.py backend/tests/test_outbound_response_mapper.py backend/tests/test_production_observability.py
PYTHONPATH=. venv/bin/python -m compileall -q backend/services/outbound_response_styler.py backend/services/outbound_response_mapper.py backend/diagnostics/outbound_response_style_prompt_template.py backend/observability/events.py
openspec validate experiment-full-llm-outbound-response-generation --strict
git diff --check
```

## Rollback / Reversibility

The current wrapper implementation remains intact on
`codex/add-global-communication-flavors`; discarding this experimental branch
returns to it without data migration or persisted-state change. The neutral
flavor remains a runtime no-op in either implementation.

## Deferred Limitations

- Pilot observations, not code, determine whether prompt calibration is
  sufficiently reliable to promote this approach.
- Semantic validation, provider-specific rendering, retries, and styling of
  free-text-sensitive/error/ambiguity responses remain explicitly deferred.
