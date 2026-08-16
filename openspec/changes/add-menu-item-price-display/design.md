# Design: display prices in customer menu responses

## Authoritative Flow

```text
current commerce sellable catalog (already loaded)
  -> deterministic `ver_menu` item projection with optional valid price
  -> existing full-menu or selected-category filtering
  -> pure deterministic response renderer
  -> optional outbound wrapper around the exact factual menu text
```

The catalog and its price rows remain authoritative. Neither category LLM
resolution nor outbound flavor styling sees or decides prices.

## Price Projection

For every existing product/presentation menu item, `_resolve_menu` reuses the
existing `_first_valid_precio(producto_presentacion)` helper. When it yields a
stable two-decimal string, the item receives optional `precio`. When it yields
`None`, no `precio` key is required. The existing product, presentation,
category, ordering, and category-id filtering fields remain unchanged.

Full and selected-category results both derive from that one in-memory item
universe; they share the price projection and cannot query a second commerce
or separate price source.

## Rendering

`_format_menu_item` continues to require a valid product name and presentation
code. If its optional `precio` is a non-empty string, it returns:

```text
<producto> (<presentación>) — $<precio>
```

Otherwise it returns the pre-existing `<producto> (<presentación>)` text.
The renderer stays pure: it accepts no database/LLM/catalog service and does
not validate or calculate a price.

## Failure and Transaction Semantics

Invalid or absent price data degrades per item to the existing no-price form.
It is not a menu failure and must not affect other items. No transaction,
retry, logging of private data, pending mutation, or LLM fallback is added.

## Test Boundary

Focused tests establish valid price rendering for both full and category menu,
per-item absence/invalid fallback, exact current-commerce service call, and
unchanged pure/non-mutating rendering. They do not duplicate category-LLM or
outbound-wrapper tests.
