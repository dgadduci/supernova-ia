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
Backend validation rejects wrappers with digits, line breaks, question marks,
or disallowed control characters. The static prompt also prohibits new facts,
products, prices, quantities, promises, discounts, dates, instructions,
questions, or commands.

For each valid wrapper, backend code composes:

```text
normalized-prefix + exact original factual_message + normalized-suffix
```

The original factual message remains one intact contiguous substring. Therefore
the LLM cannot rewrite or remove the deterministic business facts. Invalid
items fall back individually; malformed batch structure falls back for the
entire batch. There is no retry.

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
