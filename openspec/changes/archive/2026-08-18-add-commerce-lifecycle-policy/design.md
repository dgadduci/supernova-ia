# Design: commerce lifecycle policy

## Context

The database relationship `Comercio.estado_id -> EstadoComercio` is sound, but
the business interpretation is not: free-text labels are compared to ACTIVO in
multiple execution paths. Trial limits are per-commerce, while the current
status row is global. The design keeps the existing FK and replaces the
distributed interpretation with one policy.

## Decisions

### D1 — Typed mode, stable code, display text

`EstadoComercio` gains immutable `codigo`, operator-facing `descripcion`, an
enum `modo_operacion` with `HABILITADO`, `BLOQUEADO`, and `PRUEBA`, and a
boolean `seleccionable`. The availability policy uses only
`modo_operacion`; `codigo` is a stable data identity and `descripcion` is
display-only. The panel asks the state repository for selectable rows; it does
not carry a hardcoded list. The current textual field is migrated to the
code/description representation; compatibility projections are updated in the
same change rather than retaining two sources of truth.

Existing SUSPENDIDO and BAJA rows are retained with `BLOQUEADO` mode and
`seleccionable = false`. They remain visible as historical current state where
referenced, but cannot be chosen in create/edit forms. This preserves
references and the present fail-closed behavior without a destructive data
rewrite.

### D2 — Trial configuration belongs to Comercio

`Comercio` gains nullable timezone-aware `prueba_hasta`, nullable positive
`prueba_max_pedidos`, and non-null non-negative
`prueba_pedidos_consumidos` (default 0). Trial configuration is required only
when the selected state has PRUEBA mode. The deadline is entered/persisted as
an exact instant, not a redundant number of days. The future self-service
onboarding will calculate that instant from its selected plan.

Entering PRUEBA from a non-trial state requires deadline and quota and resets
consumption to zero. Editing a commerce already in PRUEBA requires valid
deadline/quota but preserves consumption. Leaving PRUEBA preserves its last
configuration as read-only historical configuration; the policy ignores it.

### D3 — One non-committing availability policy

`CommerceAvailabilityService` evaluates an exact commerce's configured mode
and trial limits, returning a typed result with a bounded reason. All existing
helpers that currently test ACTIVO delegate to it; no routing/provider path
compares status code, description, or labels. A missing state and a
legacy/blocked state are unavailable. The enum represents only the three
technical behaviors, not the names of business states.

For a trial confirmation, `reserve_confirmed_order(comercio_id, now)` locks
the exact commerce row, re-evaluates deadline/quota, and increments the counter
only on success. It does not commit. The caller performs that reservation in
the same transaction as changing the exact pedido from BORRADOR to INGRESADO.
This makes the quota strict under concurrency and rolls back both changes on
technical failure.

### D4 — Inbound acceptance, leased processing, and order confirmation are distinct guards

Provider ingress/routing checks availability before accepting new customer
work, so unavailable commerce cannot begin a new pipeline. The authenticated
direct/test ingress uses the same `evaluate(comercio_id)` call before loading a
session or invoking the response orchestrator; unavailable returns a bounded
HTTP error without a customer response.

Provider work is asynchronous, so `process_lease` re-evaluates the policy after
resolving the receipt's authoritative commerce id and before session, draft,
intent, or outbox staging. An unavailable lease is terminalized with a bounded
reason, is not retried, and never invokes the pipeline. This leaves receipt
claiming, lease ownership, technical retries, and channel resolution unchanged.

A previously created draft might reach confirmation after a trial expires;
therefore every actual `BORRADOR -> INGRESADO` transition rechecks/reserves
availability. The API `PedidoService` and the draft-order closure are the only
current confirmation seams and both must use the same policy.

### D5 — Admin uses the existing commerce mutation path

The existing admin form gets conditional trial fields and a read-only consumed
count. Its route validates presentation data and calls the existing
`ComercioService`; the service performs authoritative lifecycle validation and
one transaction. The create path creates only a commerce; it does not create a
channel, session, order, provider resource, or trial order reservation.

### D6 — Migration and API compatibility

An Alembic revision backfills each existing state into
code/description/mode/selectable configuration and adds trial columns with
safe defaults. It must be idempotent for the canonical seed and preserve all
`estado_id` references. The legacy
`POST /estados-comercio` creation surface is retired because arbitrary labels
would create undefined operational behavior; list/retrieve remain available
with the new typed representation. No new endpoint is added.

## Interaction

```text
all inbound entry points, provider leased processing, routing, or order confirmation
  -> CommerceAvailabilityService
  -> exact Comercio + EstadoComercio
  -> typed available/unavailable
  -> (confirmation only) locked quota reservation
  -> caller-owned commit or rollback
```

```text
admin create/edit commerce
  -> Basic Auth + same-origin + path CSRF
  -> ComercioService lifecycle validation
  -> one commit or rollback
  -> exact commerce detail
```

## Risks and Mitigations

- A partial refactor could leave an ACTIVO comparison behind. Mitigate with a
  repository-wide targeted search and regressions for every existing caller.
- An adapter could bypass the policy and answer an unavailable commerce.
  Mitigate with direct endpoint and provider acceptance/lease regressions;
  future adapters must use this service before shared processing.
- A counter increment outside confirmation could consume trial quota for
  drafts. Reserve only at BORRADOR-to-INGRESADO in the same transaction.
- Concurrent confirmation could oversell the final quota. Lock the commerce
  row and re-evaluate inside the lock.
- Legacy status cleanup could destroy business context. Preserve blocked rows;
  defer their retirement to an explicit data-governance change.
- A user can extend an active trial through the admin panel in this phase;
  that is intentional operator authority. Plan-based limits and audit history
  are deferred.
