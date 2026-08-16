# Design: safe outbound response styling

## Authoritative Flow

```text
inbound message
  -> existing classifier / deterministic business pipeline
  -> existing deterministic response builders
  -> shared outbound response styler (optional, one batch call)
  -> local JSON response OR staged provider outbox rows
```

The deterministic `CustomerResponse` is authoritative. Styling is a pure
presentation transform applied in `build_customer_responses`, after add-product
coalescing and all existing response builders. No execution outcome, response
order, intent, or status is accepted from the LLM.

## Flavor Resolution

The styler resolves the selected flavor for `session.id_comercio` through the
existing commerce/flavor model or repository. A flavor is usable only when it
is active, has a non-empty internal instruction, and its stable code is not
`neutro`. The neutral code is an explicit no-op and must not instantiate or
call `QueryLlm`.

Missing or stale flavor configuration is fail-closed for styling (not for the
business turn): the original response is returned.

## Eligibility and Privacy Boundary

Eligible normal messages include social conversation, full/category menu,
successful product mutation, order status, draft summary and guided closure,
confirmation, and new/empty-order outcomes. Error, rejection, and
pending/ambiguous outcomes are never eligible. Nor are responses associated
with customer-supplied free text (observations, address, payment/delivery
input), even if their builder normally produces a short acknowledgement.

The LLM receives neither the raw inbound message nor the deterministic
customer response. It receives only an ordered response-type token for each
eligible item. This deliberately excludes catalog contents, order summaries,
addresses, payment/delivery values, observations, IDs, and all other customer
or business data from the style prompt.

## One-Call Wrapper Contract

For all eligible responses in one turn, the styler sends exactly one JSON
prompt containing a static template, selected internal flavor instruction, and
the ordered response types:

```json
{"items":[{"index":0,"response_type":"product_add_success"}]}
```

It requests exactly:

```json
{"items":[{"index":0,"prefix":"¡Genial!","suffix":""}]}
```

The response schema is strict: `items` is required; indexes must match the
eligible input exactly once and in order; each item accepts only `index`,
`prefix`, and `suffix`. Prefix and suffix are short single-line strings.
For every eligible item, at least one of `prefix` or `suffix` MUST be
non-empty so an active non-neutral flavor produces visible presentation style.
Backend validation rejects wrappers with both fields empty, digits, line
breaks, question marks, or disallowed control characters. An empty wrapper is
an item-level `empty_wrapper` fallback; unsafe content remains
`wrapper_invalid`. The static prompt also prohibits new facts, products,
prices, quantities, promises, discounts, dates, instructions, questions, or
commands.

For each valid wrapper, backend code composes:

```text
normalized-prefix + exact original factual_message + normalized-suffix
```

The original factual message remains one intact contiguous substring. Therefore
the LLM cannot rewrite or remove the deterministic business facts. Invalid or
empty-wrapper items fall back individually; malformed batch structure falls
back for the entire batch. There is no retry.

## Failures and Transaction Semantics

`QueryLlm` errors (`timeout`, connection, HTTP, invalid response) and every
unexpected styler exception become a bounded fallback outcome. The styler does
not re-raise to business callers, does not call a second model, and owns no
database transaction controls. Existing outer callers keep their transaction
and outbox ownership unchanged.

Because mapper execution may occur in the provider coordinator before its
caller-owned transaction commits, the call is best effort and latency is
accepted for this phase. It must never alter whether the transaction is
committed or rolled back.

## Shared Rendering Contract

`stage_outbound_rows` must call the same `build_customer_responses` result as
the local path. It must not invoke a second stylistic pass. This maintains
equivalent message text and order between the pilot/local channel and provider
outbox for the same processed intents.

## Diagnostics

Use a new bounded event family or existing diagnostics conventions to report:
attempted/not-attempted, flavor code, eligible count, applied count, fallback
category, static template version/fingerprint, and elapsed milliseconds.
The static fingerprint derives only from static template text. Diagnostic
payloads and logger calls must not contain factual message text, prompt,
internal flavor instruction, LLM output, or customer/session/order data.

## Non-Goals and Extension Boundary

No migrations, UI/configuration changes, classifier changes, provider changes,
or response-builder rewrites are part of this change. Styling errors,
rejections, ambiguities, or customer-free-text response families remains
outside this privacy and factual-preservation contract.

## Reactivation from the full-message experiment

The full-message experiment is reverted at the styling boundary only. Restore
the wrapper contract represented by `17d7566` in these collaborators:

- `backend/diagnostics/outbound_response_style_prompt_template.py`
- `backend/services/outbound_response_styler.py`
- `backend/observability/events.py`
- `backend/tests/test_outbound_response_styler.py`

The wrapper LLM receives only response-type tokens and flavor instruction; it
does not receive factual customer text. The backend composes each validated
non-empty prefix/suffix around the exact deterministic message, leaving it an
intact contiguous substring. Current `outbound_response_mapper.py` remains
the existing shared boundary and is not restored from an older branch.

No model, migration, configuration API, global flavor data, prompt instruction
row, intent, response builder, router, outbox owner or transaction owner is
changed. This restoration deliberately uses the tested wrapper implementation
instead of attempting another full-message prompt calibration.

## Expressive wrapper boundary

The wrapper may be a short complete phrase rather than a two-word marker. Each
`prefix` and `suffix` accepts at most 96 characters; their combined length
accepts at most 140 characters. The validator continues to reject digits,
questions, line breaks and control characters. The static prompt explains
that fragments may contain flavor-appropriate emoji but must remain generic
and factual-free.

The selected `instruccion_llm` remains the only source for whether `joven` or
another flavor uses emojis and what tone it adopts. The application does not
hardcode a flavor phrase or emoji, and this amendment does not write the
already configured flavor row.

Because the LLM receives only `response_type` tokens and no factual message,
the backend's composition retains the entire deterministic response as an
intact contiguous substring. The combined bound preserves a concise customer
message even when both sides are non-empty.

## Local pilot diagnostic handoff

The existing structured event proves the styler knows whether it was applied,
not attempted, or fell back, but the event stream is not queryable from the
pilot UI. For the local-test route only, the shared styling call will optionally
produce a typed companion diagnostic alongside the normal response list.

The diagnostic has a closed shape:

```json
{
  "outcome": "applied | not_attempted | fallback",
  "eligible_count": 0,
  "applied_count": 0,
  "fallback_category": "optional-allowlisted-token",
  "flavor_code": "optional-allowlisted-code",
  "response_types": ["allowlisted-token"],
  "template_version": "static-version"
}
```

It deliberately excludes raw customer text, rendered factual messages,
prefix/suffix, prompt, flavor instruction, IDs, timestamps, latency, exception
types, model output and arbitrary event payload fields. The route serializes
only that typed object, and the existing panel renders name/value fields for
the latest local turn. The diagnostic is returned only in that HTTP response;
it is neither persisted nor reused by a later message.

The ordinary mapper API remains list-compatible. Its internal shared styling
operation is factored once so an opt-in caller can receive the same response
list plus its diagnostic without styling twice or creating a parallel business
pipeline. Provider/outbox callers retain the existing list-only behavior and
never receive this local UI projection.

`ver_menu` and executed status are eligible response types under an active
non-neutral selected flavor. An `outcome=fallback` means the selected flavor
was attempted but no valid wrapper was applied; it never means that the
application silently selected `neutro`.

## Menu wrapper calibration

`menu_full` is an eligible opaque response-type token, not an invitation for
the LLM to author a menu. The deterministic renderer remains the sole source
of headings, categories, products, presentations and prices. The static
wrapper prompt will make this boundary explicit: a `menu_full` wrapper may
only add a generic one-line framing phrase around the already-rendered menu.
It must not reproduce, summarize, enumerate, title, format or describe any
menu content.

The selected persisted flavor instruction remains the sole source of tone and
emoji choices. The static prompt may enforce the generic/factual-free boundary
but shall not prescribe a particular phrase or emoji for `joven` or any other
flavor. Updating this static rule increments the template version and changes
only the static fingerprint.

No validator is weakened. The existing strict JSON schema, 96 characters per
field, 140-character combined bound, no digits/questions/newlines/control
characters, one-request maximum and exact factual-substring composition remain
authoritative. An invalid menu wrapper continues to preserve the exact
deterministic menu as a `wrapper_invalid` fallback.
