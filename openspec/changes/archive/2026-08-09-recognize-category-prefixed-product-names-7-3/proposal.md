## Why

The controlled WhatsApp pilot established that the deployed catalog stores the
product name `Napolitana` under the `Pizzas` category. The message
`3 Pizza napolitana` produced only a category-level ambiguity and an unmatched
fragment, while `3 Napolitana` is recognized. The resulting empty candidate
set is safely rendered as the generic retry message rather than selecting a
product.

The failure is in the fuzzy recognizer's significant-token guard: it requires
every meaningful input token to occur in `producto_nombre`. `pizza` belongs to
the candidate's category, not its stored product name, so the otherwise valid
Napolitana candidates are removed.

## Objective

Allow an explicit category prefix in a product request to act as compatible
context for a candidate of that category, while retaining the existing
product-token requirement, category-only safe fallback, commerce isolation and
candidate narrowing.

## Current execution path

`Provider inbound -> existing intent classifier -> agregar_producto ->
FuzzyProductRecognizer -> _extraer_candidatos -> _filtrar_por_tokens_clave ->
product intent resolver -> pending selection or execution`.

For `3 Pizza napolitana`, fuzzy extraction can surface a Napolitana candidate,
but `_filtrar_por_tokens_clave` rejects it because `pizza` is absent from the
stored `producto_nombre`. The existing category pass then returns a typed
category-only group for `Pizzas`; downstream correctly extracts no product IDs
and does not widen it.

## Scope

- Modify the fuzzy recognizer's key-token filtering only.
- For an individual candidate, ignore an input token only when it exactly
  identifies that candidate's catalog category (with the existing
  singular/plural normalization) **and** at least one remaining significant
  product token matches the candidate name or its existing aliases.
- Preserve the current score, presentation, quantity, availability, alias,
  category-only fallback and output-shape behavior.
- Add focused recognizer regression tests and a `product-recognizer` delta.

## Non-goals

- No changes to the provider/webhook, inbound coordinator, session/pedido,
  intents, response wording, outbox, dispatcher, catalog fixture data,
  aliases, embeddings, vector/hybrid policy, configuration, schema or
  migrations.
- No category-only request may become a product candidate; `pizza`, `3 pizza`,
  or `pizza grande` keep the existing category-level ambiguity behavior.
- No cross-category, cross-commerce, or unrestricted candidate selection.
- No direct Railway mutation or additional live-message experimentation.

## Shared boundary, outcomes and fallback

| Input / candidate relation | Authoritative outcome |
| --- | --- |
| `3 Pizza napolitana`; candidate product name `Napolitana`, category `Pizzas` | `pizza` is category context; `napolitana` remains required; only valid Napolitana presentation candidates are returned with quantity `3` |
| `pizza` / `3 pizza` / `pizza grande` with no product token | Existing category-only ambiguity; no product IDs are exposed |
| `empanada napolitana`; candidate category `Pizzas` | `empanada` is not compatible category context; candidate is rejected by existing token guard |
| Category-prefixed product has no valid candidate in that category | Existing `no_encontrados` / safe fallback behavior |
| Product candidate already includes category word in its own name | Existing matching result remains unchanged |

## Transaction ownership and observability

The recognizer remains pure: it owns no transaction and performs no persistence.
Existing recognizer result structure and diagnostics remain unchanged. No new
logging or raw-message retention is introduced.

## Expected files

- `backend/recognizers/product_recognizer.py`
- `backend/tests/test_product_recognizer.py` or one new focused recognizer test
  module only if the existing suite cannot express the boundary clearly
- `openspec/changes/recognize-category-prefixed-product-names-7-3/`

## Focused tests and validation

Tests shall prove:

- `3 Pizza napolitana` against products named `Napolitana` in `Pizzas` returns
  only its existing presentation candidates, preserves quantity `3`, and does
  not emit a category group or unmatched fragment;
- a generic category-only request remains category-only with no product IDs;
- a mismatched category prefix cannot promote a candidate;
- existing product names that already carry their category prefix preserve
  their result;
- existing alias, contract and category-ambiguity tests remain green.

The user runs locally:

```bash
PYTHONPATH=. venv/bin/python -m pytest backend/tests/test_product_recognizer.py backend/tests/test_product_recognizer_contract.py backend/tests/test_product_recognizer_persisted_alias.py backend/tests/test_product_recognition_calibration_4_11_5.py
PYTHONPATH=. venv/bin/python -m ruff check backend/recognizers/product_recognizer.py backend/tests/test_product_recognizer.py
PYTHONPATH=. venv/bin/python -m compileall -q backend/recognizers/product_recognizer.py backend/tests/test_product_recognizer.py
openspec validate recognize-category-prefixed-product-names-7-3 --strict
git diff --check
```

## Rollback and deferred limitations

The code change is reversible by deployment rollback. It creates no persistent
state. More general natural-language category/product composition, new aliases,
or catalog renaming are deliberately deferred.
