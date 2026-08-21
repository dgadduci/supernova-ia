# Proposal: allow Twilio Emulator messages on active draft orders

## Objective

Allow the authenticated Admin/Pilot detail action `Enviar por Twilio
Emulator` to submit a provider-shaped inbound for an exact active Session
whose associated Pedido is still `borrador`. This completes the intended test
conversation after the bootstrap inbound creates the initial draft order.

## Current execution path

The bootstrap action on the Admin/Pilot order list sends the first inbound
through the standalone emulator. The T-C webhook, NovaOrders provider
coordinator and worker then create an active Session with an associated empty
`borrador` Pedido. The detail-page emulator action subsequently calls the same
emulator inbound control surface, but `load_active_emulator_target` currently
rejects `BORRADOR` before any downstream call. The browser therefore shows the
generic emulator rejection even though the Session and commerce are valid.

## Scope

- Extend the existing detail-page emulator target eligibility to include an
  exact `borrador` Pedido with an active associated Session.
- Preserve all existing identity and operational guards: Pedido/Session
  association, client and commerce ownership, active dedicated channel,
  available commerce, active T-C installation and explicit emulator mode.
- Keep the existing emulator inbound route, T-C webhook, provider coordinator,
  worker, outbox and outbound emulator path as the only processing pipeline.
- Make the existing asynchronous status projection work for the selected
  active draft without adding another source of truth.
- Update the detail-page copy so the operator understands that the action can
  be used on an active draft order.
- Add focused tests for draft acceptance, identity rejection, consecutive
  messages, status polling and unchanged non-draft behavior.

## Non-goals

- No direct creation, replacement, closure or mutation of Session/Pedido from
  the Admin/Pilot route.
- No automatic transition from `borrador` to `ingresado`.
- No bypass of normal message processing, pending context, worker leases,
  retries, outbox finalization or T-C authentication.
- No support for closed/inactive Sessions, detached pedidos, cross-commerce
  identity, arbitrary addresses or arbitrary provider targets.
- No change to the initial bootstrap action's active-context guard.
- No changes to real Twilio behavior, Railway variables, secrets, production or
  calibration.
- No migration or new persistence model.

## Shared boundary

```text
Admin/Pilot detail action for exact active draft
  -> twilio_emulator /internal/emulator/inbound
  -> T-C signed inbound webhook
  -> NovaOrders provider coordinator
  -> existing provider worker
  -> existing draft Session/Pedido processing + outbound outbox
  -> T-C outbound command
  -> twilio_emulator Messages API
```

The browser remains unable to choose the webhook URL, E.164 addresses,
credentials or provider payload. The emulator remains the only provider-shaped
entry point for this Admin/Pilot action.

## Authoritative outcomes and fallback

### Valid business outcome

- `submitted`: the emulator accepted the inbound control command. The existing
  worker and dispatcher remain authoritative for processing and outbound
  delivery.

### Valid target states

- An exact active Session with an associated `borrador` Pedido.
- The existing currently eligible non-`borrador` detail targets, unchanged.

### Rejections

- Missing/mismatched/detached Pedido and Session.
- Inactive Session or unavailable commerce.
- Missing/inactive dedicated channel or T-C installation.
- Disabled/incomplete emulator configuration.
- Invalid same-origin request or malformed message.

All rejection and transport failures keep the existing generic browser response
and never fall back to local processing or real Twilio.

## Transaction ownership

The detail route and target loader remain read-only before the emulator call.
They must not commit, rollback, flush, refresh, begin or close the SQLAlchemy
session. The provider coordinator owns inbound acceptance and the existing
worker transaction owns business processing, outbound staging and finalization.

## Observability

Reuse the existing bounded Admin/Pilot emulator outcome events. Add no raw
message body, phone number, credential, URL, provider payload or exception
text. If a reason category distinguishes draft acceptance/rejection, it must
remain a closed category and must not expose order or commerce identifiers.

## Expected files

- `backend/services/admin_pilot_emulator_service.py` — extend the exact target
  eligibility without weakening identity checks.
- `backend/routers/admin_pilot_orders.py` — preserve route/status contracts and
  update only the draft eligibility documentation or bounded projection when
  required.
- `backend/templates/admin_pilot_orders/detail.html` — clarify draft-order
  emulator availability.
- `backend/tests/test_admin_pilot_orders_panel.py` — update existing contract
  assertions where the documented draft eligibility changes.
- `backend/tests/test_admin_pilot_emulator_draft_inbound.py` — focused draft,
  consecutive-message and status tests.
- `openspec/changes/allow-admin-pilot-emulator-draft-inbound/` — this change
  proposal, design, spec delta and tasks.

## Focused tests

- The exact active draft Pedido/Session is accepted by the target loader.
- Detached, inactive, closed, cross-client and cross-commerce targets remain
  rejected before the emulator call.
- A valid draft submission calls the emulator exactly once with server-resolved
  addresses and no direct database write.
- Two sequential valid inbound submissions preserve the same exact draft
  Session/Pedido identity and use the existing receipt/outbox pipeline.
- Status polling accepts the exact draft target and remains bounded.
- Existing non-draft detail behavior and local-test behavior remain unchanged.
- Emulator disabled, unavailable commerce and invalid configuration remain
  fail-closed.

## Validation commands

The implementer must run and report complete output for:

```text
PYTHONPATH=. venv/bin/python -m pytest backend/tests/test_admin_pilot_orders_panel.py backend/tests/test_admin_pilot_emulator_draft_inbound.py -q
PYTHONPATH=. venv/bin/ruff check backend/services/admin_pilot_emulator_service.py backend/routers/admin_pilot_orders.py backend/tests/test_admin_pilot_orders_panel.py backend/tests/test_admin_pilot_emulator_draft_inbound.py
PYTHONPATH=. venv/bin/python -m compileall -q backend/services/admin_pilot_emulator_service.py backend/routers/admin_pilot_orders.py
openspec validate allow-admin-pilot-emulator-draft-inbound --strict
git diff --check
```

## Rollback and reversibility

The change is code-only and requires no migration. Disabling emulator mode
continues to make the action unavailable. Reverting the change restores the
previous draft rejection while leaving the bootstrap action and real provider
defaults unchanged.

## Deferred limitations

This change does not add a new browser action for arbitrary inbound targets,
does not allow multiple active sessions for one client/commerce pair and does
not alter the business rule that a draft must be explicitly confirmed before
its normal lifecycle transition.
