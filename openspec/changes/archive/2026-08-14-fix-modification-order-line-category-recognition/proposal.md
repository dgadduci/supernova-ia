# Proposal: category-aware own-order-line recognition for product modification

## Why

The active pilot draft contains `Mozzarella Grande`, `Mozzarella Chica` and
`Verdura`, but both `cambia una empanada de verdura por una empanada de carne
picante` and `cambia una pizza de mozzarella grande por 1 empanada de pollo`
are rejected with `Ese producto no está en tu pedido.` No pending context is
created and no line is mutated.

`modificar_producto` already loads only the active Pedido's lines. Its
order-line catalog nevertheless writes `categoria_nombre=None`, while the
shared recognizer expects the category name to distinguish a category token
such as `pizza` or `empanada` from a required product token. The repository
already eager-loads that category for the same read. This is a missing owned
catalog projection, not a quantity, handler, transaction, Twilio, or
classifier defect.

## What Changes

- Project the already eager-loaded product category description as
  `categoria_nombre` in the source order-line catalog used by
  `modificar_producto`.
- Retain the active draft lines as the sole source candidate universe and the
  existing source identity projection from presentation ID to order-line ID.
- Prove category-qualified source recognition for Pizza/Mozzarella and
  Empanadas/Verdura, including safe rejection for a product absent from the
  draft.

## Objective and current execution path

```text
active session.id_pedido
  -> PedidoProductoService.list_by_pedido (already eager-loads category)
  -> modificar_producto _build_order_line_catalog
  -> categoria_nombre=None                         # current defect
  -> shared recognizer treats pizza/empanada as unmatched product token
  -> source_candidate_ids=[]
  -> source_absent -> Ese producto no está en tu pedido.

corrected
  -> category description from the same owned row
  -> shared recognizer treats pizza/empanada as category context
  -> only matching own order-line IDs proceed to existing ready/pending flow
```

## Scope and non-goals

Scope is limited to the source order-line catalog projection of
`modificar_producto` and its focused tests. The existing repository eager
load is reused; it must not be duplicated or replaced with a query per line.

Non-goals: quantities (including `cantidad_destino`), classifier/prompt,
hybrid/fuzzy mode or policy, embeddings/vector ranking, aliases, global
commerce-catalog fallback, destination recognition, candidate resolver,
handler/service/repository mutation semantics, response text, panel,
provider/Twilio, observability schema, authentication, migrations, sync,
archive, and deployment.

## Shared boundary, authoritative outcomes, and fallback

The source catalog from `PedidoProductoService.list_by_pedido(session.id_pedido)`
is authoritative. The category is descriptive context attached to those same
rows only; it cannot add candidates from another Pedido or from the commerce
catalog.

| Condition | Required outcome |
| --- | --- |
| `pizza de mozzarella grande` matches one owned line | Existing ready/handler path receives that exact own line ID. |
| `pizza de mozzarella` matches two own presentations | Existing `source_selection` pending flow receives exactly those two own line IDs. |
| `empanada de verdura` matches an owned line | Existing modification flow proceeds; no category-only candidate is invented. |
| Product is outside the active draft | Existing zero-candidate/source-absent rejection remains. |
| Category relation is absent or malformed | Preserve safe no-match/technical behavior; do not infer a category. |
| Hybrid returns unique, ambiguous, or unknown | Preserve the configured boundary and its existing fuzzy fallback behavior; no new fallback is introduced. |

The shared recognizer remains authoritative for recognition only. No LLM,
hybrid, fuzzy, or category field gains mutation authority. Candidate sets must
never widen beyond current owned lines.

## Transaction ownership, privacy, and observability

The repository, service, recognizer, and initial orchestrator remain read-only
with respect to transaction control: no commit, rollback, flush, refresh,
begin, close, or per-line query. The outer incoming-message transaction keeps
ownership. No raw message, order/customer/session ID, category label, trace,
metric, or customer-facing field is added.

## Expected files

- `backend/intents/recognizers/modificar_producto_recognizer.py`
- `backend/tests/test_modificar_producto_recognizer.py`
- `backend/tests/test_modificar_producto_initial.py` and/or
  `backend/tests/test_modificar_producto_end_to_end.py` only for the smallest
  real-flow proof
- `openspec/changes/fix-modification-order-line-category-recognition/`

## Focused validation

Run in the user's local terminal:

```text
PYTHONPATH=. venv/bin/python -m pytest backend/tests/test_modificar_producto_recognizer.py backend/tests/test_modificar_producto_initial.py backend/tests/test_modificar_producto_end_to_end.py backend/tests/test_modificar_producto_handler.py backend/tests/test_modificar_producto_response.py backend/tests/test_product_recognition_calibration_4_11_5.py -q
PYTHONPATH=. venv/bin/python -m ruff check backend/intents/recognizers/modificar_producto_recognizer.py backend/tests/test_modificar_producto_recognizer.py backend/tests/test_modificar_producto_initial.py backend/tests/test_modificar_producto_end_to_end.py backend/tests/test_modificar_producto_handler.py backend/tests/test_modificar_producto_response.py backend/tests/test_product_recognition_calibration_4_11_5.py
PYTHONPATH=. venv/bin/python -m compileall -q backend/intents/recognizers/modificar_producto_recognizer.py
openspec validate fix-modification-order-line-category-recognition --strict
git diff --check
```

## Rollback and deferred limitations

The change is reversible by restoring the `None` projection. No persisted
state changes. After an approved deploy, verify both reported category-
qualified messages against a known draft, then prove that an outside-draft
source stays rejected without mutation. Do not archive this change or the
active destination-only quantity change without explicit user approval.
