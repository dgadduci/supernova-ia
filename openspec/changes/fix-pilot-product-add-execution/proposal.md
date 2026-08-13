# Proposal: fix pilot product-add execution

## Objective

Make the real provider flow `Quiero una pizza de mozzarella` → `Grande` add
one line to the active session's own draft Pedido when the selected
presentation has exactly one current price. Keep the complete turn
caller-transaction-owned, and let an authenticated operator inspect catalog
price availability without raw API JSON or database access.

## Current execution path and evidence

Production displayed `Mozzarella Grande` / `Mozzarella Chica`; `Grande`
returned the generic `agregar_producto` rejection. The operations panel then
showed an active session, a `borrador` Pedido and no lines. This rules out a
closed session, closed Pedido and pre-existing line for that attempt.

For a ready selection, `execute_agregar_producto` calls legacy
`PedidoProductoService.add_or_increment`. Its `PrecioNotFound` and other
deterministic business exceptions map to the exact generic response observed.
It also commits, rolls back and refreshes within the provider's outer
transaction. The controlled fixture source declares a Mozzarella Grande price,
but its global empty-namespace verifier cannot prove availability for a
non-empty pilot catalog. Existing ambiguity E2E tests seed prices and call
incoming orchestration directly; they do not traverse the provider coordinator.

## Scope

- Add a dedicated caller-owned product add/increment seam used only by the
  modern intent handler. Validate active own session/draft Pedido, selected
  presentation, positive quantity and exactly one price before staging one
  price-snapshotted line.
- Preserve legacy `add_or_increment` behavior for existing callers.
- Emit a closed no-PII business outcome through the existing event catalogue.
- Extend the authenticated read-only pilot panel with a commerce-isolated
  catalog price-availability view.
- Add provider-level ambiguity → `Grande` coverage for price-present and
  price-unavailable outcomes.

## Non-goals

No catalog reseed or price writes, migration, webhook, classifier/prompt/
corpus, LLM, candidate-policy, endpoint JSON contract, provider/outbox schema,
customer-response redesign, reset, deploy or archive. Do not widen candidate
sets, choose another presentation, infer a price or repair data automatically.

## Authoritative outcomes and fallback

`executed` requires a restricted selected candidate, own `borrador` Pedido,
positive quantity and exactly one price; it stages only that line and price
snapshot. Malformed data, missing/inactive/foreign session or Pedido,
non-borrador state, missing presentation or zero/multiple prices are valid
no-mutation `rejected` outcomes with a closed internal reason. Unexpected
technical failures remain `failed` and propagate to the outer owner. Fuzzy and
the existing restricted pending resolver stay authoritative; no LLM or catalog
fallback may select a product or price after `Grande` resolves.

## Transaction ownership and observability

The new service/repository seam, handler, panel and event emission SHALL NOT
commit, rollback, begin, close, refresh or flush. The provider coordinator
commits once or rolls back technical failures.

`product_add_execution` has only these closed outcomes: `created`,
`incremented`, `rejected_invalid_input`, `rejected_session_or_pedido`,
`rejected_not_editable`, `rejected_missing_presentation`, and
`rejected_price_unavailable`. It has no identifier, text, label, quantity,
price, customer/session/Pedido, LLM, exception or correlation field. Emission
is best effort and cannot change the business result.

## Expected files

- `backend/services/pedido_producto_service.py` and
  `backend/repositories/pedido_producto_repository.py`
- `backend/intents/handlers/agregar_producto_handler.py`
- `backend/observability/events.py` and existing exports/query coverage
- `backend/services/pilot_order_operations_view_service.py`,
  `backend/routers/admin_pilot_orders.py`, and one bounded panel template/view
- Focused service/handler/observability/panel tests and a provider coordinator
  end-to-end test

## Focused validation

Run in the user's local terminal (the Codex sandbox cannot load this
project's Homebrew-backed `venv`):

```text
PYTHONPATH=. venv/bin/python -m pytest backend/tests/test_agregar_producto_handler.py backend/tests/test_pedido_producto_service.py backend/tests/test_pending_product_ambiguity_resolution_e2e.py backend/tests/test_provider_message_receipt_core_integration.py backend/tests/test_pilot_order_operations_view_service.py backend/tests/test_admin_pilot_orders_panel.py backend/tests/test_production_observability.py backend/tests/test_query_production_logs.py -q
PYTHONPATH=. venv/bin/python -m ruff check backend/services/pedido_producto_service.py backend/repositories/pedido_producto_repository.py backend/intents/handlers/agregar_producto_handler.py backend/observability/events.py backend/observability/__init__.py backend/services/pilot_order_operations_view_service.py backend/routers/admin_pilot_orders.py backend/tests/test_agregar_producto_handler.py backend/tests/test_pedido_producto_service.py backend/tests/test_pending_product_ambiguity_resolution_e2e.py backend/tests/test_provider_message_receipt_core_integration.py backend/tests/test_pilot_order_operations_view_service.py backend/tests/test_admin_pilot_orders_panel.py backend/tests/test_production_observability.py backend/tests/test_query_production_logs.py
PYTHONPATH=. venv/bin/python -m compileall -q backend/services/pedido_producto_service.py backend/repositories/pedido_producto_repository.py backend/intents/handlers/agregar_producto_handler.py backend/observability/events.py backend/services/pilot_order_operations_view_service.py backend/routers/admin_pilot_orders.py
openspec validate fix-pilot-product-add-execution --strict
```

## Rollback, production gate and deferred limitation

This is source-only and reversible; it has no migration or catalog mutation.
After approved deploy, use the panel to inspect Mozzarella Grande for the
selected commerce. If price is unavailable, stop for separately approved data
remediation. If available, run the WhatsApp ambiguity sequence and confirm one
line and success response. Only then may
`fix-pending-context-recovery-and-status-query` resume its three production
checks and, after that, `implement-product-line-observation-intent` its own.
No change may be archived without explicit user approval.
