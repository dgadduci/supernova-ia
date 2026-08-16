# Proposal: safe outbound response styling

## Why

Phase 1 now persists one selected global communication flavor per commerce,
but every customer response remains deterministic and neutral. NovaOrders needs
an optional presentation layer that lets a selected flavor make short,
low-risk success messages sound consistent without allowing an LLM to decide
business behavior or rewrite business facts.

## What Changes

- Add one shared, bounded outbound-response styling step after deterministic
  response mapping and before both the local test response and provider outbox
  staging.
- For an active non-`neutro` commerce flavor, make at most one additional LLM
  request per inbound turn, batching only eligible response types.
- Require a structured wrapper result (`prefix` / `suffix`) per eligible
  response. The backend, not the LLM, composes the final text around the exact
  deterministic message, so quantities, products, prices, order state, and
  intent outcome cannot be replaced or reordered.
- Preserve the exact existing response and make no style request for `neutro`,
  no/missing/inactive flavor, an ineligible response, or any LLM/contract
  failure.
- Emit bounded, PII-safe observability for attempted, applied, and fallback
  styling; never log customer text, flavor instruction, prompt, IDs, or model
  output.

## Objective

Deliver an opt-in presentation-only layer for selected commerce flavors while
keeping the deterministic response mapper authoritative for every business
fact and preserving identical local/outbox response semantics.

## Current Execution Path

`incoming_message_response_orchestrator` processes an inbound turn and calls
`build_customer_responses`. `backend/services/outbound_response_mapper.py`
maps each `ProcessedIntent` through deterministic response builders.
`stage_outbound_rows` calls that same mapper before staging provider outbox
rows. The existing `QueryLlm` client already performs JSON-only LLM calls and
reports transport failures. Phase 1 provides `Comercio.flavor_comunicacion`
and a global `FlavorComunicacion` catalog, including the internal
`instruccion_llm` and canonical `neutro` flavor.

## Scope

- A reusable outbound response styler invoked only by the shared mapper.
- Exactly one batch request at most for a turn with eligible responses.
- Initial eligibility includes normal deterministic customer messages:
  social conversation, menus (full and by category), successful product
  mutations, order status, draft summary and guided closure, confirmation,
  and new/empty-order responses. Errors, rejections, pending/ambiguous
  selections, and responses associated with customer free text (observations,
  addresses, payment/delivery input) remain byte-for-byte deterministic.
- Strict parsing/validation of a wrapper-only JSON response and exact factual
  composition by backend code.

## Non-Goals

- No change to intent classification, recognition, handlers, transactions,
  response-builder business wording, delivery, outbox, provider routing,
  flavor administration, or schema/migrations.
- No style LLM call for inbound raw text, pending state, catalog/menu content,
  address, payment, observations, order summaries, or factual response text.
- No retries, streaming, asynchronous second pipeline, model-specific tuning,
  or free-form LLM rewriting in this phase.
- No requirement that every response be styled.

## Shared Boundary

The shared boundary is `build_customer_responses`: it is the only place where
an eligible deterministic `CustomerResponse` may be presentation-styled. Both
the local channel and `stage_outbound_rows` must consume the same returned
responses. The LLM receives only indexed, allowlisted response types (never a
factual response string) plus the selected internal flavor instruction; it
returns only bounded wrappers, never a replacement message.

## Fallback Behavior

- `neutro`, absent flavor relation, inactive flavor, zero eligible responses,
  and a missing usable instruction: no style call; return factual responses.
- Timeout, connection/HTTP/response failure, malformed JSON, wrong item count
  or indexes, unknown fields, invalid wrapper content, or any unexpected
  styling failure: preserve the original factual response for affected items;
  do not fail the customer turn or mutate business state.
- No fallback may invoke recognition, classification, another LLM call, or a
  transaction control method.

## Transaction Ownership

The mapper/styler owns no `commit`, `rollback`, `flush`, `refresh`, `begin`,
or session close. Existing callers retain transaction ownership. Styling is
best-effort after deterministic processing; a style failure is contained and
cannot cause a business mutation or outbox staging failure.

## Observability

Emit only event metadata such as flavor code, eligible count, applied count,
fallback category, and latency. Logs/events must exclude raw customer inbound
text, factual response text, prompt, `instruccion_llm`, customer/order/session
identifiers, addresses, observations, and model output.

## Expected Files

- `backend/services/outbound_response_styler.py` (new)
- `backend/services/outbound_response_mapper.py`
- `backend/diagnostics/outbound_response_style_prompt_template.py` (new, if
  needed for static template identity)
- `backend/tests/test_outbound_response_styler.py` (new)
- `backend/tests/test_outbound_response_mapper.py`
- `backend/tests/test_incoming_message_response_orchestrator.py` (only if the
  existing focused coverage needs a shared-path assertion)
- This change's OpenSpec files.

## Focused Tests

- A non-neutral active flavor makes one batch call and only adds validated
  wrappers around each exact factual message, without receiving that message.
- Multiple eligible responses still make one call, preserve response order,
  intent, status, and exact factual substrings.
- Neutral, absent, inactive, malformed, timeout, connection, HTTP, and schema
  failures preserve exact output and cause no business transaction control.
- Ineligible error, rejection, ambiguity, and free-text-sensitive response
  classes are neither sent to the LLM nor changed; mixed batches retain all
  original ordering.
- Local response and staged outbox obtain identical styled text from the
  shared mapper.
- Observability/template identity contains no raw customer text or internal
  flavor instruction.

## Validation

The implementer must run and report complete output from:

```bash
PYTHONPATH=. venv/bin/python -m pytest backend/tests/test_outbound_response_styler.py backend/tests/test_outbound_response_mapper.py backend/tests/test_order_status_query.py -q
PYTHONPATH=. venv/bin/python -m ruff check backend/services/outbound_response_styler.py backend/services/outbound_response_mapper.py backend/diagnostics/outbound_response_style_prompt_template.py backend/tests/test_outbound_response_styler.py backend/tests/test_outbound_response_mapper.py
PYTHONPATH=. venv/bin/python -m compileall -q backend/services/outbound_response_styler.py backend/services/outbound_response_mapper.py backend/diagnostics/outbound_response_style_prompt_template.py
openspec validate add-safe-outbound-response-styling --strict
git diff --check
```

## Rollback / Reversibility

Disabling a flavor by selecting `neutro` returns the current deterministic
behavior without migration or data rewrite. If the feature needs rollback,
remove the shared styler invocation; all existing deterministic builders and
outbox rows remain valid.

## Reactivation Amendment: discard the full-message experiment

The later `experiment-full-llm-outbound-response-generation` change replaced
this wrapper contract on its dedicated branch. Pilot calibration repeatedly
summarized menus, removed presentation/unit labels and added unsupported
status/logistics wording. Without a semantic output validator, which remains
out of scope, that experiment does not meet the factual-reliability threshold.

This amendment restores this already-approved wrapper contract on the current
branch. It is a targeted restoration, not a whole-branch rollback:

- Restore the wrapper-only template, parser/composition, bounded styling event
  contract and focused tests from the known safe wrapper state at `17d7566`.
- Keep the current shared mapper placement, global flavors, persisted
  `instruccion_llm`, protected administrative catalog endpoint, all later
  intent/order changes and caller-owned transaction behavior intact.
- Do not deploy the old branch wholesale and do not use `git revert` on
  unrelated commits.
- Keep `experiment-full-llm-outbound-response-generation` active and
unarchived as the documented failed experiment; its pilot gates remain
unmarked and it must not be archived as a successful change.

## Expressive Wrapper Amendment

The restored wrapper confirms factual safety, but its current 24-character
per-field limit and prompt wording (“a couple of words or an emoji”) leave too
little room for the configured flavor to make messages pleasant and distinctive.
This amendment increases expression while keeping the LLM outside factual
content.

- Allow a `prefix` and `suffix` of up to 96 characters each, with a combined
  maximum of 140 characters per eligible response. They remain single-line,
  printable, non-numeric and question-free.
- Permit a short complete framing phrase, not merely one or two words. It may
  include emojis when the selected persisted flavor instruction calls for them.
- The wrapper must stay generic to the opaque `response_type`; it cannot
  state, infer or promise product/order/customer facts because those facts are
  never supplied to the LLM.
- The current persisted `joven.instruccion_llm` is already the administrator's
  configured source for its style and emoji choices. This change MUST NOT edit
  flavor rows, migrations, seeds or API configuration.

The result remains `prefix + exact factual message + suffix`; only the
allowed surrounding framing becomes more expressive.

## Local Pilot Styling Diagnostic Amendment

An unwrapped eligible response is deliberately safe, but the pilot panel
currently cannot distinguish an ineligible response from an attempted styling
fallback. This amendment adds a bounded, request-scoped diagnostic handoff
for the existing authenticated local-test channel only.

- Preserve the selected active commerce flavor for every eligible normal
  response, including `ver_menu` full/category and order-status responses;
  this amendment MUST NOT substitute `neutro`, alter flavor selection, or
  make an unstyled fallback look like a flavor decision.
- The local-test success JSON and its existing execution-state panel gain a
  closed `outbound_style` projection for the turn: attempt outcome,
  eligible/applied counts, bounded fallback category when applicable, selected
  flavor code when usable, allowlisted response-type tokens, and static
  template version. It contains no messages, prompts, instruction, IDs,
  exception detail, model output, or timing.
- The diagnostic is ephemeral to the single local-test HTTP response and UI
  refresh. It is not persisted on Session/Pedido, placed in provider outbox,
  emitted as a second LLM call, or used as business input.
- Extract a single shared mapper/styler diagnostic path so the normal local
  processor remains the same business pipeline. Existing callers keep their
  list-of-responses contract unless they explicitly opt into the typed
  diagnostic companion.

### Expected files for this amendment

- `backend/services/outbound_response_styler.py`
- `backend/services/outbound_response_mapper.py`
- `backend/intents/orchestration/incoming_message_response_orchestrator.py`
- `backend/routers/admin_pilot_orders.py`
- `backend/templates/admin_pilot_orders/detail.html`
- focused styler/mapper/orchestrator/pilot-panel tests

### Focused tests for this amendment

- An eligible `ver_menu` and order-status response under a usable selected
  flavor records `applied` or a bounded `fallback` outcome; it never becomes
  a neutral flavor decision.
- `not_attempted` cleanly distinguishes no eligible response from an unusable
  flavor without disclosing configuration detail.
- The local route/UI receive only its closed safe projection and never raw
  messages, prompts, instructions, IDs, exception text, model output, or
  arbitrary diagnostic fields.
- Existing local business processing, mapper result ordering, provider outbox
  flow and caller-owned transaction behavior remain unchanged.

### Validation for this amendment

```bash
PYTHONPATH=. venv/bin/python -m pytest backend/tests/test_outbound_response_styler.py backend/tests/test_outbound_response_mapper.py backend/tests/test_incoming_message_response_orchestrator.py backend/tests/test_admin_pilot_orders_panel.py -q
PYTHONPATH=. venv/bin/python -m ruff check backend/services/outbound_response_styler.py backend/services/outbound_response_mapper.py backend/intents/orchestration/incoming_message_response_orchestrator.py backend/routers/admin_pilot_orders.py backend/tests/test_outbound_response_styler.py backend/tests/test_outbound_response_mapper.py backend/tests/test_incoming_message_response_orchestrator.py backend/tests/test_admin_pilot_orders_panel.py
PYTHONPATH=. venv/bin/python -m compileall -q backend/services/outbound_response_styler.py backend/services/outbound_response_mapper.py backend/intents/orchestration/incoming_message_response_orchestrator.py backend/routers/admin_pilot_orders.py
openspec validate add-safe-outbound-response-styling --strict
git diff --check
```

## Menu Wrapper Calibration Amendment

Pilot evidence under a usable selected `joven` flavor shows that `menu_full`
reaches the styler but receives the safe `wrapper_invalid` fallback, while
executed order status is styled correctly. This is not a `neutro` selection or
a mapper integration failure. It is a prompt-contract calibration issue: the
opaque `menu_full` token appears to invite menu reproduction, Markdown or
multi-line content that the existing wrapper validator correctly rejects.

- Revise only the static wrapper prompt and its version/fingerprint so
  `menu_full` is explicitly a generic, one-line presentation boundary: wrap
  the already-rendered menu; never reproduce, summarize, enumerate, format or
  describe it.
- Re-state that `menu_full` wrapper fields must be generic and factual-free:
  no product/presentation/category names, prices, quantities, headings,
  bullets, Markdown, line breaks, questions, or instruction to the customer.
- Preserve creative tone and emoji decisions as the selected persisted
  `instruccion_llm`; do not hardcode a customer-facing phrase, emoji, or any
  young-specific wording in code.
- Preserve the same strict JSON shape, existing 96/140 bounds, validation,
  exact factual substring composition, one LLM request maximum and all
  fallback behavior.

### Expected files for this amendment

- `backend/diagnostics/outbound_response_style_prompt_template.py`
- `backend/tests/test_outbound_response_styler.py`
- `backend/tests/test_prompt_template_grounding.py` only if it already owns
  static-template identity assertions
- This change's `tasks.md` and delta spec.

### Focused tests for this amendment

- Static prompt/version/fingerprint change when the menu-specific static
  guidance changes; no customer or flavor instruction text in that identity.
- `menu_full` valid generic one-line wrapper with an emoji is accepted and
  retains the exact menu message as a contiguous factual substring.
- Menu reproduction/list markers, product/category/price/quantity-like facts,
  line breaks, Markdown and questions remain rejected by the existing generic
  validator/fallback contract where representable at this boundary.
- Existing status and non-menu wrapper behavior, one-call limit, `neutro`
  no-op, privacy and no transaction controls remain unchanged.

### Validation for this amendment

```bash
PYTHONPATH=. venv/bin/python -m pytest backend/tests/test_outbound_response_styler.py backend/tests/test_outbound_response_mapper.py backend/tests/test_prompt_template_grounding.py -q
PYTHONPATH=. venv/bin/python -m ruff check backend/diagnostics/outbound_response_style_prompt_template.py backend/services/outbound_response_styler.py backend/tests/test_outbound_response_styler.py backend/tests/test_prompt_template_grounding.py
PYTHONPATH=. venv/bin/python -m compileall -q backend/diagnostics/outbound_response_style_prompt_template.py backend/services/outbound_response_styler.py
openspec validate add-safe-outbound-response-styling --strict
git diff --check
```

## Factual-Claim Guard Amendment

Pilot evidence under `joven` confirms that the backend preserves the exact
deterministic `product_add_success` sentence, but also shows a valid-shaped
wrapper claiming that the order is already in transit. That is an unsupported
commercial/logistics fact and violates the wrapper-only safety boundary even
though it is outside the deterministic substring.

### Objective

Fail closed when a wrapper asserts, promises, or infers an order, commerce, or
logistics fact. Retain generic, flavor-driven presentation framing without
allowing the LLM to author customer-facing business state.

### Scope and shared boundary

- Revise the static wrapper prompt and its version/fingerprint to explicitly
  prohibit claims about order state, preparation, confirmation, shipment,
  delivery, payment, availability, timing, or execution.
- Add a bounded normalized lexical guard in the existing wrapper validator for
  those high-risk commerce/logistics claim terms. A match is `wrapper_invalid`;
  the backend preserves the original deterministic response exactly.
- Keep `build_customer_responses` as the sole shared styling boundary for the
  local path and provider outbox. Do not add an LLM call, semantic validator,
  parallel pipeline, flavor-row change, migration, or response-builder change.

### Authoritative outcomes and fallback

- **Authoritative outcome:** the deterministic `CustomerResponse`; wrappers
  may frame it but cannot introduce a commercial fact.
- **Valid business outcome:** a generic, bounded, factual-free wrapper is
  composed around the exact deterministic substring.
- **Technical/contract failure:** a malformed wrapper or a wrapper matching a
  guarded claim term produces the existing bounded `wrapper_invalid` fallback.
- **Exact fallback:** preserve that item's deterministic response unchanged;
  retain the selected flavor diagnostic; make no retry, second LLM call,
  recognition/classification call, or transaction action.
- **Must not trigger fallback:** a generic emotional or social framing phrase
  with no guarded claim term and otherwise valid wrapper shape.

### Transaction ownership and observability

The validator remains pure and owns no transaction control. Existing bounded
diagnostics remain sufficient: they report `wrapper_invalid` but never the
rejected wrapper, factual message, prompt, instruction, or identifiers.

### Expected files and focused tests

- `backend/diagnostics/outbound_response_style_prompt_template.py`
- `backend/services/outbound_response_styler.py`
- `backend/tests/test_outbound_response_styler.py`
- This change's `proposal.md`, `design.md`, spec delta, and `tasks.md`.

Cover an otherwise valid wrapper that says an order is in transit and verify
exact deterministic fallback, bounded diagnostics, one-call behavior, and no
transaction control. Retain coverage that a generic expressive wrapper is
accepted, and that `neutro` remains an exact no-op.

### Validation, rollback, and deferred limitation

Run the existing focused styler/mapper/status pytest, Ruff, compileall, strict
OpenSpec validation, and `git diff --check` commands listed above. The user
runs `venv`-dependent commands locally and supplies complete output.

Rollback is limited to removing this validator/prompt amendment; no persisted
state changes. This amendment does not attempt general natural-language fact
classification: novel claims outside the bounded high-risk lexical guard remain
deferred and must fail closed through future, separately approved work.

## Deferred Limitations

- Styling error, rejection, ambiguity, or customer-free-text response families
  requires a separately approved clarity and safety review.
- Async delivery-time styling, retries, and provider-specific presentation are
  explicitly deferred.
