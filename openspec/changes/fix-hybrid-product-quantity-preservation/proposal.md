# Proposal: fix hybrid product quantity preservation

## Why

The deployed pilot accepted `quiero dos napolitanas grandes` on a draft that
already contained three Napolitana Grande units. It returned a final total of
four and the panel displayed four. This proves the panel snapshot and product
add seam were consistent, but the real upstream recognizer supplied an added
quantity of one instead of two.

The configured `hybrid_authoritative` recognizer was the cause for the unique
path: its translator wrote `cantidad=1` unconditionally, although the inner
fuzzy recognizer already parses quantities deterministically. That repair is
deployed and its unique-result pilot gate passed.

The same translator has now revealed the equivalent defect in the ambiguous
path. For `quiero 2 empanadas de carne`, it returns the valid, bounded Carne
Picante / Carne Suave candidate group but omits `cantidad` on every candidate.
The existing resolver consequently persists its established default of one in
the pending context; the later reply `picante` or `suave` correctly selects a
candidate, but adds one rather than the requested two. Candidate selection and
the durable add seam are not the cause.

## What Changes

- Preserve the deterministic quantity parsed from the original input when a
  hybrid authoritative decision translates to one unique product.
- Preserve that same deterministic quantity on every candidate of one
  ambiguous hybrid result group, so the existing resolver persists it before
  the customer selects a bounded candidate.
- Keep the hybrid ranking and top product authoritative for product selection;
  quantity parsing does not select or widen candidates and grants no LLM
  authority to mutate a Pedido.
- Prove the live local-test route, with the real hybrid recognizer and real
  text parsing, adds 1, then 2, then 3 as `1 -> 3 -> 6` on one line.
- Preserve the current default of quantity one when the input omits a valid
  quantity, and preserve byte-for-byte fuzzy fallback for hybrid technical
  failures.

## Current execution path

```text
incoming agregar_producto text
  -> factory-selected hybrid_authoritative recognizer
  -> inner fuzzy recognition parses "dos" as 2
  -> hybrid ranks the already catalog-bounded candidates
  -> hybrid translator emits either one unique candidate or one bounded
     ambiguous group
  -> unique path or every ambiguous candidate carries the parsed quantity
  -> existing resolver persists it; a later bounded selection preserves it
  -> existing handler adds the requested quantity
```

## Scope and non-goals

Scope is the hybrid unique- and ambiguous-result translation and its focused
recognition, pending-selection and local-test-route coverage.

Non-goals: no product normalizer/plural mapping change, classifier/prompt,
policy weights or thresholds, embedding/vector ranking, hybrid mode setting,
fuzzy behavior, catalog data, candidate narrowing rules, handler, service,
repository, transaction boundary, response wording, panel JavaScript,
Twilio/provider/outbox, telemetry schema, authentication, migration or
deployment automation change. Do not change the legacy add path, persist a
quantity from the customer selection reply, or introduce a second recognition
pipeline.

## Authoritative outcomes and fallback

| Condition | Required outcome |
| --- | --- |
| Hybrid decision is `unique` | Use its existing top ranked in-catalog presentation and deterministic parsed positive quantity. |
| Hybrid decision is `ambiguous` | Keep exactly the existing ranked, in-catalog candidate group and attach the same deterministic parsed positive quantity to each candidate. |
| Quantity is omitted | Preserve the existing default `1`. |
| Hybrid decision is `unknown` | Preserve existing unknown behavior. |
| Embedding/vector technical failure | Return the inner fuzzy result byte-for-byte, including its quantity. |
| Invalid/foreign/non-editable order state | Existing downstream typed no-mutation rejection remains unchanged. |

The quantity parser is a pure deterministic text helper. It must not re-rank,
query, choose a candidate, invoke an LLM, inspect a later selection reply, or
cause fallback. The passed catalog remains the complete allowed candidate
universe.

## Transaction ownership, privacy and observability

The hybrid recognizer remains free of database I/O and never commits,
rolls back, flushes, refreshes, expires, begins or closes a transaction. The
existing transactional processor remains the sole owner. No new event or raw
message/quantity field is emitted; existing no-PII observation contracts stay
unchanged.

## Expected files

- `backend/services/hybrid_authoritative_recognizer.py`
- `backend/tests/test_controlled_hybrid_product_recognition.py`
- `backend/tests/test_product_intent_resolver.py` and/or the existing
  add-product pending-selection tests, only as needed to prove that the
  quantity reaches and survives the existing pending context
- the focused local-test route regression under `backend/tests/` as needed to
  replace its mocked product-recognizer assertion with a real hybrid boundary
- `openspec/changes/fix-hybrid-product-quantity-preservation/`

## Focused validation

Run in the user's local terminal:

```text
PYTHONPATH=. venv/bin/python -m pytest backend/tests/test_controlled_hybrid_product_recognition.py backend/tests/test_product_recognition_factory.py backend/tests/test_pedido_producto_local_test_route_sequential_regression.py backend/tests/test_agregar_producto_handler.py backend/tests/test_pedido_producto_service.py -q
PYTHONPATH=. venv/bin/python -m ruff check backend/services/hybrid_authoritative_recognizer.py backend/tests/test_controlled_hybrid_product_recognition.py backend/tests/test_product_recognition_factory.py backend/tests/test_pedido_producto_local_test_route_sequential_regression.py backend/tests/test_agregar_producto_handler.py backend/tests/test_pedido_producto_service.py
PYTHONPATH=. venv/bin/python -m compileall -q backend/services/hybrid_authoritative_recognizer.py
openspec validate fix-hybrid-product-quantity-preservation --strict
git diff --check
```

## Rollback and production gate

This source-only correction is reversible by restoring the quantity decoration
of the affected translator output. After approval, implementation, review and
deploy, retain the unique pilot check and use the pilot's local channel with
the two valid Carne presentations: send `quiero 2 empanadas de carne`, choose
`picante`, then send `agrega dos empanadas de carne` and choose `suave`.
Each resulting line and response must show two; pending/context must clear
after each selection. Do not archive this or dependent active changes without
explicit user approval.
