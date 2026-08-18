# Tasks: add commerce lifecycle policy

## 1. Model, migration, and state contract

- [x] 1.1 Add typed operating mode, stable code, display description, and
  selectable flag to `EstadoComercio`; update exports and typed
  schemas/projections.
- [x] 1.2 Add trial deadline, maximum confirmed orders, and consumed counter
  to `Comercio` with model/database constraints appropriate to their types.
- [x] 1.3 Create and verify an Alembic migration that preserves existing IDs
  and references, backfills canonical/legacy modes, and adds safe trial data.
- [x] 1.4 Load state options from `seleccionable` configuration rather than
  hardcoding codes, and retire arbitrary runtime state creation without adding
  replacement CRUD.
- [x] 1.5 Apply a follow-up Alembic revision that seeds the five canonical
  lifecycle states idempotently (`ACTIVO`/`INACTIVO`/`PRUEBA` selectable;
  `SUSPENDIDO`/`BAJA` blocked/non-selectable) without altering pre-existing
  `id` values, and add a focused migration test that proves the five codes,
  exact attributes, pre-existing `ACTIVO` id preservation, the
  repository/panel selectable listing returning exactly `ACTIVO`,
  `INACTIVO` and `PRUEBA`, and idempotent re-application.

## 2. Central policy and transactional confirmation

- [x] 2.1 Implement the single typed availability policy and bounded reasons;
  it must not own transaction completion.
- [x] 2.2 Implement locked, same-transaction reservation of a trial confirmed
  order; prove that deadline/quota failures do not mutate state.
- [x] 2.3 Replace every production ACTIVO text comparison in channel,
  provider, and shared-routing paths with the policy.
- [x] 2.4 Apply the policy to both current BORRADOR-to-INGRESADO seams:
  `PedidoService` and draft-order closure, preserving each caller's transaction
  ownership.

## 3. Admin lifecycle configuration

- [x] 3.1 Extend the shared commerce create/update validation for lifecycle
  configuration, including entry-to-trial reset and in-trial edit preservation.
- [x] 3.2 Extend typed admin views/forms/routes/template with conditional
  deadline/quota fields, read-only consumption, and bounded errors.
- [x] 3.3 Preserve current Basic Auth, same-origin, exact-path CSRF,
  autoescaping, and POST/redirect/GET behavior on every mutation.

## 4. Focused verification

- [x] 4.1 Add model/migration/policy tests for all modes, legacy states,
  trial boundaries, and final-quota concurrency.
- [x] 4.2 Add panel tests for create/edit trial validation, counter reset only
  on entry, no reset during trial edits, and security rejection paths.
- [x] 4.3 Add focused routing/provider/order regressions proving blocked or
  expired/exhausted commerce cannot receive/confirm orders and ACTIVO still
  can.
- [x] 4.4 Run and report the exact validation commands in `proposal.md`, plus
  the migration upgrade/downgrade check against the project test database.

## 5. Unified inbound availability guard

- [x] 5.1 Apply `CommerceAvailabilityService` at direct/test ingress before
  session lookup or response orchestration. Preserve auth; unavailable returns
  a bounded error with no mutation or customer response.
- [x] 5.2 Re-evaluate the policy in provider `process_lease` after receipt
  resolution and before session/draft/intent/outbox staging. Terminalize an
  unavailable lease without retry or outbound work, preserving transactions.
- [x] 5.3 Keep provider acceptance guarded and ensure no current ingress
  interprets lifecycle codes or labels locally.
- [x] 5.4 Add regressions for blocked, expired, and quota-exhausted commerce at
  direct ingress, provider acceptance, and a lease accepted before deactivation.
  Prove pipeline/orchestrator/outbox are not called and available behavior stays.
- [x] 5.5 Run and report the revised validation commands, strict OpenSpec
  validation, and `git diff --check`.
