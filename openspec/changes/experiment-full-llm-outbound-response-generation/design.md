# Design: experimental full LLM outbound response generation

## Architectural Invariant

```text
inbound message
  -> existing classification and deterministic business execution
  -> persisted order/session/product state
  -> deterministic CustomerResponse
  -> experimental full-message generator
  -> local pilot response or provider outbox message
```

The LLM operates only after deterministic business execution and receives no
authority to feed data back into the pipeline. Its text is a customer-facing
view of already-determined state, never a source of persisted state.

## Replaced Contract

On this branch, the existing `prefix`/`suffix` protocol is replaced rather than
coexisting as a second runtime pipeline. The shared styler makes one batch
request with ordered eligible items:

```json
{
  "items": [
    {
      "index": 0,
      "response_type": "product_add_success",
      "factual_message": "Listo, agregué 2 Empanadas de Pollo."
    }
  ]
}
```

It accepts only this output envelope:

```json
{
  "items": [
    {
      "index": 0,
      "message": "¡Genial! Ya sumé 2 empanadas de pollo a tu pedido 😊"
    }
  ]
}
```

The parser validates the closed envelope, exact item count and index order,
and a non-empty string message. It deliberately does not compare generated
words or values with `factual_message`. A structurally valid generated message
replaces only `CustomerResponse.message`; intent, status, response order and
all persisted state remain unchanged.

## Prompt Design

The prompt is a static, versioned contract with the flavor directive and a
runtime batch. It must repeat the immutable rules immediately before the
output schema, after the flavor directive, so tone cannot displace facts:

- Rewrite the supplied factual message in natural Spanish for the chosen tone.
- Preserve every product, presentation, quantity, price, date, hour, state,
  choice, menu entry, and other concrete fact supplied by the backend.
- Preserve every menu line when the factual message is a menu.
- Add no facts, promises, discounts, estimated times, instructions, questions,
  or customer-specific assumptions.
- Return only JSON with full `message` values.

The menu rule is deliberately stronger than ordinary paraphrase: categories,
individual lines, product names, presentation/unit labels, prices and order
are immutable visible content. A generated introduction or closing is allowed,
but the list itself must not be summarized, re-grouped or flattened. Likewise,
an order-status response may only repeat the state wording explicitly present
in `factual_message`; dispatch, delivery, timing and future-action language
are prohibited unless supplied factually.

The factual message is intentionally transmitted to the LLM for eligible
responses. Raw inbound text is not transmitted. Ineligible response text is
not transmitted.

## Eligibility and Privacy

Reuse the current explicit eligibility map, excluding `desconocida`, errors,
rejections, pending/ambiguous outcomes, and customer-free-text acknowledgements
for observations, address, payment/delivery, and date/time. Eligible factual
messages may contain normal commerce/order facts, including menu entries and
prices. This is an approved pilot trade-off; it is not PII logging.

Neither prompt nor response text, flavor instruction, generated LLM output,
or IDs may enter runtime logs or structured diagnostics.

## Failure Handling

`neutro` and unusable flavor are no-ops. For a technical failure or malformed
batch, all eligible messages use deterministic output. A structurally invalid
or empty generated message falls back per item where the batch can still be
mapped safely. There is no retry or wrapper fallback.

## Shared and Transaction Boundaries

The mapper remains the single place that invokes the generator. Local testing
and `stage_outbound_rows` render the same generated list; staging never calls
the LLM again. The generator does no transaction control and catches technical
failures as presentation fallbacks.

## Experimental Evaluation

Pilot gates must test each approved response family under at least `joven`,
`serio`, and `neutro`. For every generated response, compare client-visible
text manually against the deterministic panel/order state, specifically:
products/presentations, quantities, prices, menu completeness, order state,
dates and times. Full and category menus additionally require line-by-line
comparison, including presentation/unit labels and order. Status output must
not introduce preparation, dispatch, delivery or timing absent from the
deterministic factual message. Any deviation is a prompt-calibration defect.
The branch is discarded if calibration cannot reach reliable results.
