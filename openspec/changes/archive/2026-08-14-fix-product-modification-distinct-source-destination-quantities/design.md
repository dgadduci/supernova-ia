# Design: distinct source and destination quantities for product modification

## Decision

Keep existing `cantidad` as the source amount and add optional
`cantidad_destino`. The paired path activates only when explicit positive
quantities occur on both normalized sides of the existing `por` boundary.

```text
source side -> existing deterministic extractor -> cantidad
destination side -> existing deterministic extractor -> cantidad_destino

both explicit: carry 2 / 1
otherwise:     cantidad_destino absent; destination mirrors effective source
```

This makes `dos ... por una ...` a `2 -> 1` operation. A one-quantity or
omitted-quantity request remains exactly compatible, including old persisted
pending JSON that has only `cantidad`.

## Data flow and ownership

1. Reuse `_split_on_por`, project normalization, and existing digit/word
   quantity vocabulary. No LLM, hybrid, or candidate result determines either
   amount.
2. Initial orchestration and the pending resolver preserve optional
   `cantidad_destino` in `resolved_data` without changing candidate IDs.
3. The handler validates each value. It re-reads source quantity when legacy
   `cantidad` is absent; absent destination quantity mirrors the effective
   source amount.
4. The existing service validates the source ceiling and every destination
   condition before source mutation, then decrements source by its amount and
   increments/creates destination by its amount in the same caller-owned
   transaction.
5. The result contains both operation amounts. Only a distinct-amount response
   branch changes customer wording; equal legacy wording is preserved.

## Outcomes and fallbacks

| Input/outcome | Behavior |
| --- | --- |
| Both explicit positive amounts | Atomic distinct mutation. |
| One/zero explicit amount or old pending payload | Existing equal/full-source mutation. |
| Invalid amount or source ceiling | Existing rejection before mutation. |
| Candidate ambiguity | Both amounts remain pending; candidate universe stays restricted. |
| Destination validation failure | Existing rejection before source mutation. |
| Technical exception | Propagates to the transaction owner; never falls back to another quantity. |

No fallback may convert a `2 -> 1` request into `2 -> 2` or infer a ratio.
The unique destination-line invariant and price snapshots are unchanged; no
migration, panel data, event/log payload, or PII exposure is added.

## Test strategy

- Recognizer: paired words/digits, one/zero-quantity compatibility and invalid
  values.
- Orchestration/resolver: paired values survive ready and both pending stages,
  including bare destination `chica`.
- Handler/service: `2 -> 1`, consolidation, source ceiling, destination
  validation, no mutation on rejection, and caller-owned transactions.
- Response: distinct values and durable destination total, while equal legacy
  response text remains unchanged.
- End-to-end: destination ambiguity then `chica` persists source -2 /
  destination +1 and clears context only after execution.
