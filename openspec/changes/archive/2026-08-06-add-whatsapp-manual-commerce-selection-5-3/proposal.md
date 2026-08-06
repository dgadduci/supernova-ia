## Why

Phase 5.2 persists a commerce chosen by an exact shared-channel routing code,
but deliberately refuses a different valid code once a selection exists. The
customer therefore has no safe, explicit way to choose a shared-channel
commerce manually or to confirm/cancel a requested change.

## Objective

Add a narrow, pre-pipeline service boundary for manual commerce selection and
explicit switching on an active shared WhatsApp channel. It must preserve the
original pending message exactly and make a commerce change only after the
caller explicitly confirms the selected active membership.

## Current execution path

`SharedChannelRoutingService.activate` validates an active client, active
shared channel and exact active membership. It creates a
`ContextoClienteCanalWhatsapp` on first activation, returns `already_selected`
for the same commerce, and returns `requires_explicit_switch` without mutation
for another valid commerce. The local incoming-message endpoint still requires
an already known commerce and is not a valid pre-commerce entry point.

## Scope

- Expose the active memberships of one supplied active shared channel as
  channel-scoped manual-selection options.
- Allow a known active client to select one of those memberships when no
  commerce is selected yet.
- Allow a selected client to request a change, then separately confirm or
  cancel that exact target.
- Persist the pending switch target in the existing channel-scoped context;
  preserve `mensaje_original_pendiente` byte-for-byte during every outcome.
- Return typed outcomes and focused tests; add one reversible migration only
  for the pending-switch state.

## Non-goals

- No Twilio SDK, webhook, TwiML, HTTP route, outbound delivery, callbacks,
  receipt/idempotency or retry behaviour.
- No client creation, `Session`, order, classifier, recognizer, handler,
  catalog, local incoming-message pipeline or automatic pending-message
  processing.
- No silent switch, free-form lookup by commerce id, code reassignment, or
  selection from another channel.
- No commit, rollback, begin or flush in repository/service code.

## Shared boundary and business outcomes

The shared boundary is a single `SharedChannelRoutingService` (or its direct
successor in the same module) over the caller-owned SQLAlchemy session. Manual
selection and switch confirmation accept a `canal_id`, `cliente_id` and an
active membership identifier; the target is validated against that channel,
not accepted as a raw commerce identifier.

Authoritative outcomes are `options_available`, `selected`,
`already_selected`, `switch_requested`, `switch_confirmed`, `switch_cancelled`,
and `no_pending_switch`. Valid non-selection outcomes are `invalid_context`,
`inactive_channel`, `invalid_channel_mode`, `unknown_or_inactive_membership`,
and `unavailable_commerce`. Technical database failures propagate to the
caller; they are not translated to a business result.

Fallback is intentionally absent: unknown/inactive memberships, unavailable
commerce, missing/inactive client and an absent/mismatched pending switch must
not fall back to an existing selection or another membership. Confirmation is
the sole transition that may replace `comercio_id_seleccionado`.

## Transaction ownership and observability

The service may query and stage context changes but never controls the
transaction. Each immutable outcome includes the channel/client ids, current
and target commerce ids when safe, status and a stable `resolution_source` so
the future webhook boundary can log the decision without exposing exceptions.

## Expected files

- `backend/models/contexto_cliente_canal_whatsapp.py`
- `backend/alembic/versions/<revision>_add_whatsapp_pending_switch.py`
- `backend/repositories/contexto_cliente_canal_whatsapp_repository.py`
- `backend/repositories/comercio_canal_compartido_repository.py`
- `backend/services/shared_channel_routing_service.py`
- `backend/tests/test_shared_channel_manual_selection.py`
- `openspec/changes/add-whatsapp-manual-commerce-selection-5-3/specs/whatsapp-shared-routing-context/spec.md`

## Validation and rollback

Focused pytest, Ruff on touched files, `compileall` on touched Python files,
strict OpenSpec validation and `git diff --check` are required. The migration
adds one nullable restrictive pending-target foreign key and its index; a
downgrade removes only that column/index and does not rewrite existing
selection or message data. Phase 5.4 remains responsible for receipt
idempotency and a single processing transaction.
