# Proposal: fix product-modification pending destination selection

## Why

In the pilot local channel, `cambiar 2 napolitanas grandes por una pizza de
mozzarella` correctly produces a pending destination clarification between
`Mozzarella (grande)` and `Mozzarella (chica)`. A reply of `chica` repeats the
same clarification without mutating the order. A fuller reply, `mozzarella
grande`, resolves and performs the expected transfer. This proves the pending
candidate set and modification path are valid; the failure is limited to the
presentation-only refinement.

`product_modification_resolver` currently sends a bare `chica` through the
generic product recognizer. That recognizer needs a product token and returns
no destination ID, so the resolver safely returns the unchanged pending
intent. The panel also projects this valid pending state misleadingly: it does
not admit `modificar_producto` as a closed active intent and counts only the
generic empty `candidate_ids`, although the authoritative destination IDs are
stored in `resolved_data.destination_candidate_ids`.

## What Changes

- Add a deterministic, exact bare-presentation pre-check only for
  `modificar_producto` at `stage="destination_selection"`.
- Compare `chica`, `grande`, or one leading article plus that code only
  against the already-loaded and persisted `destination_candidate_ids`.
- On one match, reuse the existing ready intent and handler path; on zero or
  multiple matches, fall through unchanged to existing product recognition.
- Correct the read-only panel projection for active modification pending
  state: admit its active intent and count its stage-relevant restricted
  candidate set, without exposing IDs or raw pending data.

## Current execution path

```text
cambiar 2 napolitanas grandes por mozzarella
  -> initial modification resolves one own source + two destination IDs
  -> pending product_modification / destination_selection
  -> "chica" reaches generic recognizer with only two destination rows
  -> no product-name match -> no destination ID
  -> unchanged pending intent -> clarification repeats
```

## Scope and non-goals

Scope is the proven `destination_selection` bare-presentation refinement and
the panel's safe projection of the same modification pending shape.

Non-goals: no source-selection behavior, intent classifier/prompt/verb
vocabulary, hybrid/fuzzy mode, policy, ranking, embedding/vector behavior,
candidate loader, product identity mapping, quantity extraction, handler,
service, repository, response wording, transaction boundary, provider/Twilio,
outbox, authentication, schema, migration or panel layout change. Do not
change the existing `quitar_producto` size-only resolver; its active change is
separate and intentionally scoped to order-line selection.

## Shared boundary and outcomes

The persisted `resolved_data.destination_candidate_ids` is the sole
authoritative destination universe. The resolver may read only those
presentations through its existing `list_presentaciones_by_ids` call; it shall
not query a broader catalog or infer a destination from text outside the exact
presentation-code rule.

| Condition | Required outcome |
| --- | --- |
| Exactly one pending destination code exactly matches `chica`, `grande`, or article + code | Existing ready intent receives that same destination ID; existing execution owns the transfer. |
| Zero or multiple exact code matches | Existing recognizer/intersection behavior remains the fallback; no guess or candidate expansion. |
| Full product reply (`mozzarella chica`) | Existing recognizer path remains valid and unchanged. |
| Missing source, invalid pending shape, unavailable destination or technical read failure | Existing typed rejection/failure behavior remains unchanged. |
| Valid active modification pending shown in the panel | Show active `modificar_producto`, the count of the stage-relevant restricted source/destination list, and derived `consistent`; expose no IDs, text or resolved values. |

The deterministic match has no LLM, hybrid, ranking or mutation authority. It
does not itself call the handler, persist state, or control transactions.

## Transaction ownership, privacy and observability

The resolver and panel remain read-only/caller-owned collaborators: no commit,
rollback, flush, refresh, expire, begin or close. The existing pending
dispatcher and transactional processor persist and execute any ready intent.
The panel continues returning only closed intent/status/count values; it must
not reveal pending IDs, product labels, source text, resolved quantities,
raw JSON, diagnostics, credentials or provider data. No event/log/metric
schema is added.

## Expected files

- `backend/intents/context/product_modification_resolver.py`
- `backend/services/pilot_order_operations_view_service.py`
- `backend/tests/test_product_modification_resolver.py`
- `backend/tests/test_modificar_producto_end_to_end.py` or the smallest
  existing pending-dispatch integration test
- `backend/tests/test_pilot_order_operations_view_service.py`
- `openspec/changes/fix-product-modification-pending-destination-selection/`

## Focused validation

Run in the user's local terminal:

```text
PYTHONPATH=. venv/bin/python -m pytest backend/tests/test_product_modification_resolver.py backend/tests/test_modificar_producto_end_to_end.py backend/tests/test_pending_context_dispatcher.py backend/tests/test_modificar_producto_response.py backend/tests/test_pilot_order_operations_view_service.py backend/tests/test_admin_pilot_orders_panel.py -q
PYTHONPATH=. venv/bin/python -m ruff check backend/intents/context/product_modification_resolver.py backend/services/pilot_order_operations_view_service.py backend/tests/test_product_modification_resolver.py backend/tests/test_modificar_producto_end_to_end.py backend/tests/test_pending_context_dispatcher.py backend/tests/test_modificar_producto_response.py backend/tests/test_pilot_order_operations_view_service.py backend/tests/test_admin_pilot_orders_panel.py
PYTHONPATH=. venv/bin/python -m compileall -q backend/intents/context/product_modification_resolver.py backend/services/pilot_order_operations_view_service.py
openspec validate fix-product-modification-pending-destination-selection --strict
git diff --check
```

## Rollback and production gate

This source-only correction is reversible by removing the destination-only
pre-check and the panel projection branch. After approval, implementation,
review and deploy, in a clean local pilot draft create a destination
clarification, reply `chica`, and verify the exact requested transfer, empty
pending/context and the panel's active intent/candidate count/consistency
before and after the reply. Do not archive this or dependent active changes
without explicit user approval.

The analogous `source_selection` bare-presentation path is intentionally
deferred: it has not failed in the observed pilot flow and uses a different
Pedido-line identity domain.
