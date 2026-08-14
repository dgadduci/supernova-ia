# Design: pilot product-add execution

## Decision

Use a new caller-owned `stage_add_or_increment_for_session` seam only from the
modern `agregar_producto` handler. It verifies the session, own draft Pedido,
selected presentation, positive quantity and exactly one price before staging
an existing-line increment or a new price-snapshotted line. The legacy
transaction-owning `add_or_increment` remains untouched for legacy callers.

```text
restricted candidates -> `Grande` ready id -> handler
  -> new own-session seam -> one price: stage line -> provider commits once
                            no/multiple price: rejected, no mutation
```

The seam must not query another candidate/Pedido or infer a price. An
ambiguous price is a safe business rejection, not an uncaught
`scalar_one_or_none` technical error. Unexpected errors remain `failed` and
the outer transaction rolls back.

## Operational boundary

Add one authenticated GET-only catalog subview/page for a numeric commerce id
already visible to the pilot operator. It loads only that commerce's active
product/presentation rows and displays escaped labels plus `price_available`:
true only for exactly one price, false for zero/multiple. It is not an editor
and renders no IDs, price values, customer/session/Pedido/provider data or
message text.

Register `product_add_execution` in the existing event catalogue with the
closed outcomes in `proposal.md`, a dedicated component and no optional/free
form fields. Emit once for a typed business or success result. The existing
bounded production-log CLI parses it through the catalogue. Event failure is
observational only.

## Tests

- Service/handler tests cover no transaction methods, one staged success and
  every validation rejection without mutation.
- A real provider-coordinator E2E test covers Mozzarella ambiguity → `Grande`
  with a price (one line, success response, cleared context), and absent price
  (generic rejection, no line, closed event).
- Unexpected DB failure remains failed and rolls back under the coordinator.
- Panel tests cover auth, commerce isolation, escaping, price cardinality and
  zero mutation; event tests enforce privacy and parse allowlists.

No production traffic, data repair, archive or deploy is authorized here.

## Amendment: durable sequential quantity totals

### Decision

Treat `ProductAddResult.cantidad_final` as the one authoritative post-turn
quantity. For three distinct successful turns against the exact same active
Session, draft Pedido and presentation, the existing seam must preserve this
state transition:

```text
line absent + 1 -> create line: 1
line 1       + 2 -> increment line: 3
line 3       + 3 -> increment line: 6
```

The response builder and local-test order-lines snapshot consume that durable
state; neither is permitted to compute or overwrite it from the requested
quantity. The implementation starts by exercising the actual transactional
path with a non-mocked existing line. It then changes only the component shown
to violate the sequence (if any): exact-line lookup/staging, outer turn
boundary, or the post-commit snapshot projection.

### Invariants and failure behavior

- A repeated exact add never creates a second line and never resets the
  existing line to the request quantity.
- `cantidad_agregada` is the delta; `cantidad_final` is the persisted total.
  They must not be interchanged in any consumer.
- The exact `pedido_id`/`session_id` ownership, `BORRADOR` and price
  cardinality guards remain before mutation.
- Business rejections remain no-mutation results. Technical errors propagate
  to the existing outer rollback; no catch-and-retry can create a duplicate or
  replace a quantity.
- The panel uses only the typed server order-lines snapshot after the turn;
  no JavaScript accumulation, hidden client state or raw pending payload is
  introduced.

### Tests

One integration-style fixture must persist a real first line, run the two
following messages through the normal transaction owner, and reload the line
from storage. It asserts one line and totals `1`, `3`, `6`, plus emitted
response wording derived from `cantidad_final`. A local-test route assertion
uses the same exact Pedido and verifies its JSON-safe snapshot exposes `6`.
Focused unit tests continue to assert no transaction control in the modern
seam. Existing environment-authentication failures in provider E2E tests are
reported separately and do not justify weakening the sequential invariant.
