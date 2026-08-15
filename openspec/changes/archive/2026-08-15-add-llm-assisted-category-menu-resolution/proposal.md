# Proposal: resolve requested menu categories with a bounded second LLM call

## Why

`ver_menu` currently returns every sellable product of the session's commerce.
Customers naturally ask for a category instead: “qué pizzas hay”, “qué gustos
de empanadas tenés” or “qué bebidas están disponibles”. A deterministic exact
phrase list would not cover ordinary wording, singular/plural forms, spelling
variation or conversational phrasing.

The existing `IntentClassifier` already determines that these are menu
requests, but it receives no commerce catalog and its result schema cannot
select a category. We need a bounded language-interpreter step which can
relate the customer's menu wording to the small category list of the current
commerce, while keeping catalog selection and rendering authoritative in the
backend.

## What Changes

Keep `ver_menu` as the only intent. After the existing classifier emits one
`ver_menu`, the informational menu orchestration SHALL:

1. Load the existing sellable catalog once through
   `ProductoQueryService.list_vendibles(session.id_comercio)`.
2. Build an ordered, bounded category candidate list from that same result.
   Each internal candidate maps an opaque token and exact display name to its
   database category identity; only `token` and `nombre` are sent to the LLM.
3. Invoke one dedicated category resolver LLM with the original classified
   menu query and those candidate token/name pairs. It returns one exact pair
   or explicit no-selection.
4. Validate both returned token and returned name against the same in-memory
   candidate pair. Only then filter the already-loaded vendible catalog by the
   backend-held category identity and render that one category.
5. On no-selection, invalid/mismatched result, bounded-context overflow, or
   technical resolver failure, render the existing full-menu outcome unchanged.

The primary classifier receives calibrated static guidance that browsing all
products of one category is `ver_menu`, including ordinary wording such as
“qué gustos de empanadas tenés” and “qué bebidas tenés”, while a request about
one concrete product, price, presentation, ingredient or availability remains
`consultar_producto`.

For a query that explicitly names two or more current visible category names,
the backend SHALL conservatively preserve the full-menu result without calling
the secondary resolver. This bounded, read-only guard prevents an ambiguous
multi-category request from being reduced to the first category by a
non-deterministic model.

## Current execution path

The first classifier receives a static prompt and customer message only. When
it returns `ver_menu`, `process_initial_informational_commerce_query` calls
`_resolve_menu`, which loads every sellable product for `session.id_comercio`
and returns `items`; the response builder groups and renders all categories.
No product/category list is passed to the first classifier.

## Scope

- Existing `ver_menu` only; no new `IntentName` and no modification intent.
- A second LLM request occurs only after one `ver_menu` reaches the existing
  informational branch with no pending context.
- Category candidates are derived only from the current session commerce's
  sellable catalog and include no product names, prices, addresses, customer
  data, order data, database IDs, aliases or provider data.
- Exact backend validation of the returned `(token, nombre)` pair before any
  deterministic in-memory filter.
- Existing full-menu rendering as the safe fallback.

## Non-goals

- No LLM product recognition, product selection, availability authority,
  price calculation, order mutation, pending-context interruption or category
  CRUD.
- No change to `ProductoQueryService.list_vendibles` signature or an extra
  catalog query: the existing loaded sellable result is reused.
- No new IntentName, category IDs in prompts/LLM output, alias lookup,
  fuzzy/vector search, migrations, provider/Twilio behavior, panel changes or
  response embellishment.

## Authoritative outcomes and fallback

| Condition | Outcome |
| --- | --- |
| One `ver_menu`, one valid exact token/name pair | Render only the matching current-commerce sellable category |
| Resolver returns explicit no-selection | Existing full menu |
| Token/name unknown, mismatched, duplicate, malformed or extra output | Existing full menu |
| Resolver timeout, connection, HTTP or schema failure | Existing full menu; no technical detail exposed |
| No sellable items | Existing `no_items` outcome; no category resolver call |
| Candidate list exceeds its documented bounds | Existing full menu; no category resolver call |
| Query explicitly identifies two or more current visible categories | Existing full menu; no category resolver call |
| Pending context active | Existing pending dispatcher remains authoritative; no category resolver call |

The resolver is an interpreter only. It cannot supply a database ID or a
product; the backend owns category identity, category/product filtering,
availability and all response facts.

## Transaction ownership, privacy, and observability

This path is read-only. The resolver, informational orchestration and response
builder SHALL not call transaction control or mutate session, pedido, lines,
pending state, catalog, provider rows or outbox rows. The existing outer
transaction owner remains unchanged. Resolver technical failures become the
defined full-menu fallback, not a failed order turn.

The dynamic prompt contains only the raw menu query and bounded token/name
category pairs. It SHALL not include database IDs, product/price lists, order
data, PII, settings or credentials. Runtime diagnostics may record only
bounded metadata (resolver attempted/result category such as selected/null,
candidate count, fallback reason class, latency/model/template identity); they
must not record raw message text, category labels/tokens, IDs, prompt content
or resolver exception text.

## Expected files

- `backend/intents/orchestration/informational_commerce_queries.py`
- `backend/intents/responses/informational_commerce_queries.py`
- a narrowly scoped dedicated category-resolver module and static prompt
  template module under existing `backend/llm/` / `backend/diagnostics/`
- `backend/diagnostics/prompt_template.py`
- `backend/diagnostics/intent_corpus.py`
- focused tests for the resolver, informational queries, response mapper and
  primary classifier prompt/corpus grounding
- `openspec/changes/add-llm-assisted-category-menu-resolution/**`

## Focused validation

```bash
PYTHONPATH=. venv/bin/python -m pytest backend/tests/test_intent_classifier.py backend/tests/test_prompt_template_grounding.py backend/tests/test_intent_corpus.py backend/tests/test_informational_commerce_queries.py backend/tests/test_outbound_response_mapper.py -q
PYTHONPATH=. venv/bin/python -m ruff check backend/intents/orchestration/informational_commerce_queries.py backend/intents/responses/informational_commerce_queries.py backend/diagnostics/prompt_template.py backend/diagnostics/intent_corpus.py backend/tests/test_intent_classifier.py backend/tests/test_prompt_template_grounding.py backend/tests/test_intent_corpus.py backend/tests/test_informational_commerce_queries.py backend/tests/test_outbound_response_mapper.py
PYTHONPATH=. venv/bin/python -m compileall -q backend/intents/orchestration/informational_commerce_queries.py backend/intents/responses/informational_commerce_queries.py
openspec validate add-llm-assisted-category-menu-resolution --strict
git diff --check
```

## Rollback and deferred limitations

Deleting or disabling the dedicated resolver path restores the current full
menu behavior; no durable data needs rollback. The resolver does not promise
semantic perfection: it is instructed to return no-selection when uncertain,
and the full menu remains the conservative fallback. Product-level semantic
search and arbitrary category aliases remain deferred.
