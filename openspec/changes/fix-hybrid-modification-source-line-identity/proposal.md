# Proposal: fix hybrid modification source-line identity

## Why

The pilot rejects both `cambiá 2 napolitanas grandes por 2 napolitanas
chicas` and `cambiar 2 napolitanas grandes por 2 napolitanas chicas` with
`Ese producto no está en tu pedido.` while the active draft has the source
line and remains unchanged. The verb is not the cause: the existing
normalizer turns `cambiá` into `cambia`, and both `cambia` and `cambiar` are
already stripped before source recognition.

Under the configured `hybrid_authoritative` mode, the generic hybrid
translator emits recognized product-presentation IDs but deliberately does not
carry the order-line-specific `pedido_producto_id`. The modification source
catalog already contains the exact mapping between those two IDs. However,
`modificar_producto_recognizer` currently flattens only already-carried
`pedido_producto_id` values, so a hybrid unique source becomes
`source_candidate_ids=[]`. The existing safe source-absent rejection follows.

## What Changes

- Restore the exact `pedido_producto_id` on modification *source* recognition
  entries by mapping their recognized `producto_presentacion_id` exclusively
  against the current draft's already-loaded source catalog.
- Apply the same restoration to non-category possible source entries, so the
  existing source-pending flow retains its narrowed own-order-line IDs.
- Preserve destination recognition, hybrid ranking/decision/policy, fuzzy
  fallback, classifier behavior, handler/service semantics and caller-owned
  transactions unchanged.
- Prove a real hybrid modification path resolves an explicit partial transfer
  from Napolitana Grande to Napolitana Chica without widening candidates.

## Current execution path

```text
cambiar 2 napolitanas grandes por 2 napolitanas chicas
  -> modificar_producto recognizer builds source catalog from own Pedido lines
  -> hybrid unique source result carries producto_presentacion_id only
  -> current source flattener expects pedido_producto_id
  -> source_candidate_ids = []
  -> existing source-absent rejection; no mutation
```

## Scope and non-goals

Scope is the identity projection immediately after modification source
recognition and its focused tests.

Non-goals: no change to intent classification or prompt, natural-language
verbs, quantity parsing, hybrid translator output, factory mode, policy,
embedding/vector ranking, fuzzy behavior, catalog reads, pending resolver,
handler, service, repository, response text, panel, provider/Twilio/outbox,
observability schema, authentication, migrations or deployment automation.
Do not reuse a source line from another Pedido or create a second recognition
pipeline.

## Shared boundary and outcomes

The source catalog loaded from `PedidoProductoService.list_by_pedido` is the
sole authority for mapping presentation IDs to order-line IDs. A mapping is
valid only when the recognized `producto_presentacion_id` exactly matches one
entry in that current catalog.

| Condition | Required outcome |
| --- | --- |
| Hybrid/fuzzy source result has an exact own presentation match | Attach that current `pedido_producto_id`; existing flattening/orchestration continues. |
| Source result has several exact own presentation matches | Attach only those corresponding IDs; existing pending source-selection flow owns refinement. |
| Result has no exact own match, is foreign, malformed, or category-only | Attach nothing; preserve current no-candidate/rejection behavior. |
| Hybrid embedding/vector technical failure | Keep its existing fuzzy fallback, then apply the same own-catalog identity projection only to returned source entries. |
| Destination is unknown/unavailable or quantity is invalid/excessive | Existing downstream typed outcome and no-mutation behavior remain unchanged. |

This projection has no LLM, ranking, vector, catalog expansion, or mutation
authority. It cannot turn an unknown result into a candidate or choose among
multiple lines.

## Transaction ownership, privacy and observability

The recognizer remains read-only and caller-transaction-owned: it must not
commit, rollback, flush, refresh, expire, begin or close the SQLAlchemy
session. The existing transactional incoming-message processor remains the
only commit/rollback owner. No new log, trace, metric, raw message field or
customer response is introduced; existing no-PII observability stays intact.

## Expected files

- `backend/intents/recognizers/modificar_producto_recognizer.py`
- `backend/tests/test_modificar_producto_recognizer.py`
- `backend/tests/test_modificar_producto_end_to_end.py` (or the smallest
  existing modification integration test that can run the real hybrid boundary)
- `openspec/changes/fix-hybrid-modification-source-line-identity/`

## Focused validation

Run in the user's local terminal:

```text
PYTHONPATH=. venv/bin/python -m pytest backend/tests/test_modificar_producto_recognizer.py backend/tests/test_modificar_producto_initial.py backend/tests/test_modificar_producto_end_to_end.py backend/tests/test_modificar_producto_handler.py backend/tests/test_modificar_producto_response.py backend/tests/test_product_recognition_calibration_4_11_5.py -q
PYTHONPATH=. venv/bin/python -m ruff check backend/intents/recognizers/modificar_producto_recognizer.py backend/tests/test_modificar_producto_recognizer.py backend/tests/test_modificar_producto_initial.py backend/tests/test_modificar_producto_end_to_end.py backend/tests/test_modificar_producto_handler.py backend/tests/test_modificar_producto_response.py backend/tests/test_product_recognition_calibration_4_11_5.py
PYTHONPATH=. venv/bin/python -m compileall -q backend/intents/recognizers/modificar_producto_recognizer.py
openspec validate fix-hybrid-modification-source-line-identity --strict
git diff --check
```

## Rollback, production gate and deferred limitation

This source-only correction is reversible by removing the identity projection.
After approval, implementation, review and deploy, use the pilot local channel
with a known Napolitana Grande line and available Napolitana Chica:
`cambiar 2 napolitanas grandes por 2 napolitanas chicas`. Verify the source
decreases by two, destination increases by two, no unrelated line changes and
the pending/context state clears. Do not archive this change or the active
quantity-preservation change without explicit user approval.

Testing the classifier's non-deterministic wording coverage beyond the two
reported imperative forms is intentionally deferred; this repair must not
broaden the classifier or recognizer vocabulary.
