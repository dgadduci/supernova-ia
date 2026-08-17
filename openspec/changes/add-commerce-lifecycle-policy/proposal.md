# Proposal: add commerce lifecycle policy

## Objective

Replace the repeated `estado.estado == "ACTIVO"` checks with one typed,
transaction-safe commerce-availability policy. The supported operator-facing
lifecycle is `ACTIVO`, `INACTIVO`, and `PRUEBA`; a commerce in `PRUEBA` may
receive confirmed orders only until its exact deadline or its configured order
quota is reached, whichever occurs first.

## Current Execution Path

`Comercio.estado_id` references the `estado_comercio` lookup. The current
lookup stores only free text in `estado`; its seed includes ACTIVO, INACTIVO,
PRUEBA, SUSPENDIDO, and BAJA. Several independently implemented channel,
provider, and shared-routing services load that row and compare its text to
the literal `"ACTIVO"`. The admin commerce form can already change
`estado_id`, but it has no trial configuration. A confirmed customer order is
the transition of its `Pedido` from `BORRADOR` to `INGRESADO`; both the API
service and the draft-order closure own such a transition today.

## Scope

- Make `EstadoComercio` the data-owned lifecycle configuration: stable status
  code, operator description, typed operating mode, and a selectable flag.
  The policy reads only the mode, never a code or display label.
- Seed and expose the three selectable configured states: ACTIVO/HABILITADO,
  INACTIVO/BLOQUEADO, and PRUEBA/PRUEBA.
- Add per-commerce `prueba_hasta`, `prueba_max_pedidos`, and
  `prueba_pedidos_consumidos` fields.
- Centralize availability evaluation and quota reservation in one shared
  service/repository boundary, reused by all existing ingress/routing and
  `BORRADOR -> INGRESADO` paths.
- Extend the authenticated admin create/edit form to configure deadline and
  quota only for PRUEBA; show the consumed counter read-only.
- Make entering PRUEBA reset the counter atomically; editing an already trial
  commerce changes only deadline/quota and never resets it.
- Preserve current Basic Auth, same-origin validation, exact-path CSRF,
  autoescaping, and POST/redirect/GET behavior.

## Non-Goals

- No public/self-service commerce onboarding, trial-plan catalogue, billing,
  notifications, scheduled job, automatic state transition, or outbound reply
  wording.
- No deletion of commerce, orders, sessions, channels, catalog rows, or
  associations; no rewrite of historical orders.
- No new provider API or recognition/fuzzy/hybrid roadmap work.
- No status catalogue CRUD. Existing `SUSPENDIDO` and `BAJA` rows remain
  historical blocked/non-selectable configuration during this phase.

## Shared Boundary and Transaction Ownership

`CommerceAvailabilityService` is the sole availability and trial-reservation
boundary. It returns typed available/unavailable outcomes; it never commits,
rolls back, or opens a transaction. Its repository locks the exact `Comercio`
row only while reserving one trial order. Existing callers retain their commit
ownership: provider ingress remains receipt-owner, draft processing retains
its final transaction, and `PedidoService` retains its current commit/rollback
boundary.

The normal `ComercioService` remains the sole admin create/update boundary.
It validates the exact selected state and trial fields, updates one commerce,
and owns its one commit/rollback.

## Authoritative Outcomes and Fallback

| Condition | Required outcome |
| --- | --- |
| HABILITADO state | Commerce is available. |
| BLOQUEADO or missing/legacy state | Commerce is unavailable; no alternate state or routing fallback. |
| PRUEBA before deadline and below quota | Commerce is available; confirmation reserves exactly one quota unit. |
| PRUEBA at/after deadline or at quota | Commerce is unavailable; no order becomes INGRESADO and no counter changes. |
| Concurrent final confirmation for final quota unit | At most one reservation succeeds; the other gets typed unavailable. |
| Trial field invalid or absent for a selected PRUEBA | Admin mutation is rejected atomically. |
| Technical/database failure | Caller rolls back its full transaction; no counter or pedido partial write. |

An unavailable commerce must never silently route to another commerce, create
a replacement order, reset a trial counter, or downgrade the condition to a
successful draft/order outcome.

## Observability and Reversibility

Existing typed unavailable outcomes remain the external signal at routing and
provider ingress. Add a bounded reason (`blocked_state`, `trial_expired`, or
`trial_quota_exhausted`) for internal/operator-visible diagnostics without
logging customer message content or credentials. The admin detail shows the
configured deadline, quota, consumed count, and derived availability. The
current seeded rows define the initial lifecycle, but no concrete status code
is an operational condition in Python.

This change requires an Alembic migration. The upgrade adds nullable trial
configuration and backfills status metadata without changing existing
`Comercio.estado_id` values or orders. Legacy statuses are marked BLOCKED,
preserved, and excluded from selection. Downgrade removes the new columns only
after explicit operational confirmation; rolling it back after trial data is
used discards configuration and therefore is not an automatic recovery action.

## Expected Files

- `backend/models/estado_comercio.py`, `backend/models/comercio.py`, exports,
  and one Alembic revision
- status/commerce repositories, schemas, and services; a new small shared
  availability policy module
- existing channel, provider-ingress, shared-routing, order-service, and
  draft-order-confirmation seams only where they currently decide active
  commerce or finalize `INGRESADO`
- admin forms, views, view service, routes, and commerce template
- focused lifecycle, panel, routing/provider, and order regressions
- this change's OpenSpec artifacts

## Focused Tests and Validation

- Policy: enabled, blocked, missing/legacy, expired trial, exhausted trial,
  and exact deadline/quota boundaries.
- Transaction: concurrent/final quota reservation admits one confirmation;
  failed confirmation rolls back both counter and pedido change.
- Regression: dedicated/shared/provider paths reject unavailable commerce and
  do not select a fallback; ACTIVO behavior remains available.
- Admin: only canonical states are selectable; PRUEBA requires valid deadline
  and positive quota; edit does not reset consumption; entering PRUEBA does.
- Migration/seed: existing rows retain IDs/references and legacy rows block.

The implementer runs locally and reports complete output:

```text
venv/bin/python -m pytest backend/tests/test_administrative_catalog_panel.py backend/tests/test_commerce_channel_resolver.py backend/tests/test_shared_channel_manual_selection.py backend/tests/test_provider_inbound_message_coordinator.py backend/tests/test_pedido_service.py
venv/bin/ruff check backend/admin backend/models backend/repositories backend/services backend/intents/orchestration/draft_order_closure.py
venv/bin/python -m compileall backend/admin backend/models backend/repositories backend/services backend/intents/orchestration/draft_order_closure.py
venv/bin/openspec validate add-commerce-lifecycle-policy --strict
git diff --check
```

## Deferred Limitations

Self-service onboarding will later choose a plan and calculate the trial
deadline/quota at commerce creation. A separate decision is required before
retiring, merging, or deleting legacy SUSPENDIDO/BAJA statuses.
