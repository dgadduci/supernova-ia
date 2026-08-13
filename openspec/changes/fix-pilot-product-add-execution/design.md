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
