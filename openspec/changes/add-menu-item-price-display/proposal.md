# Proposal: display prices in customer menu responses

## Why

`ver_menu` loads the sellable catalog for the session's commerce, but its
menu-item projection drops the already-available presentation price. Both the
complete menu and a category menu therefore omit prices.

## What Changes

- Preserve one valid current price, formatted as a stable two-decimal string,
  in each `ver_menu` menu item built from the already-loaded sellable catalog.
- Render that price next to each applicable presentation in complete and
  category-specific deterministic menu responses.
- Preserve an item without a valid price unchanged; never invent or calculate
  a price.

## Objective

Make customer menu listings useful for purchase decisions without changing
category resolution, flavor styling, catalog eligibility, or business state.

## Current Execution Path

`_resolve_menu` in
`backend/intents/orchestration/informational_commerce_queries.py` calls
`ProductoQueryService.list_vendibles(session.id_comercio)`, projects each
`ProductoPresentacion` into `resolved_data.items`, and optionally filters that
same in-memory projection after category resolution. The pure renderer in
`backend/intents/responses/informational_commerce_queries.py` formats those
items for full and selected-category menus. `list_vendibles` already exposes
presentation `precios`; `_first_valid_precio` is an existing deterministic,
defensive formatter used by product detail.

## Scope

- Reuse the existing valid-price selection/formatting rule for `ver_menu`.
- Add the optional price field only to the transient menu item projection and
  display it as `— $<two-decimal-price>` in both menu forms.
- Add focused orchestration and response-builder coverage.

## Non-Goals

- No LLM, flavor, wrapper, classifier, category resolver, recognizer,
  handler, transaction, outbox, provider, schema, migration, catalog query,
  price calculation, currency conversion, discount, tax, or UI changes.
- No change to `consultar_producto`, which already has its own price contract.
- No change to sellability or category selection/fallback behavior.

## Shared Boundary

The deterministic `ver_menu` item projection is the only changed boundary.
The renderer consumes that projection; it must not query the database or infer
a price. The price comes only from the current session-commerce sellable
catalog already loaded by the orchestrator.

## Fallback Behavior

- Missing, malformed, negative, or otherwise invalid price: omit the price
  from that item and preserve the existing product/presentation text.
- Empty category result or an existing category-resolution fallback preserves
  current behavior, now displaying prices only where valid data is present.
- No fallback may invoke the LLM, widen commerce/catalog scope, retry, mutate
  a session/pedido/line, or alter a pending context.

## Transaction Ownership

The orchestration projection and renderer remain read-only and own no
`commit`, `rollback`, `flush`, `refresh`, `begin`, or session close. Existing
callers retain all transaction ownership.

## Observability

No new event is needed: this is deterministic presentation of existing
catalog data. No logs may contain raw customer text, identifiers, or price
source internals.

## Expected Files

- `backend/intents/orchestration/informational_commerce_queries.py`
- `backend/intents/responses/informational_commerce_queries.py`
- `backend/tests/test_informational_commerce_queries.py`
- This change's OpenSpec artifacts.

## Focused Tests

- Complete menu displays each valid presentation price in stable two-decimal
  form.
- Category menu displays only that category's valid presentation prices.
- Missing, malformed, and negative prices do not render a price or create a
  technical failure.
- Existing category filtering, full-menu fallback, commerce isolation, pure
  response rendering, and no-transaction behavior remain unchanged.

## Validation

```bash
PYTHONPATH=. venv/bin/python -m pytest backend/tests/test_informational_commerce_queries.py -q
PYTHONPATH=. venv/bin/python -m ruff check backend/intents/orchestration/informational_commerce_queries.py backend/intents/responses/informational_commerce_queries.py backend/tests/test_informational_commerce_queries.py
PYTHONPATH=. venv/bin/python -m compileall -q backend/intents/orchestration/informational_commerce_queries.py backend/intents/responses/informational_commerce_queries.py
openspec validate add-menu-item-price-display --strict
git diff --check
```

## Rollback / Reversibility

Removing the optional projection/rendering field restores the exact previous
price-free menu text. No persisted data, migration, or external state changes.

## Deferred Limitations

Currency symbols/localization, discounts, taxes, totals, and menu pagination
remain out of scope.
