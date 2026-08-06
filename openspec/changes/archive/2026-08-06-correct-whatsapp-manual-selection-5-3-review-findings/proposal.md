## Why

The Phase-5.3 implementation review found two required state-boundary
regressions. `list_manual_options` accepts an active dedicated channel and
reports `options_available`, although manual commerce routing is defined only
for active shared channels. Separately, `request_switch` clears an existing
pending target when the client submits the already selected commerce. That
acts as a cancellation without the explicit cancellation operation.

## Objective

Restore the Phase-5.3 shared-channel and explicit-switch invariants with the
smallest change: reject manual option listing on non-shared channels, and make
a request for the current commerce a non-mutating no-op that preserves any
existing pending target.

## Current execution path

`SharedChannelRoutingService.list_manual_options()` performs client and active
channel checks, then lists active memberships, but does not check
`CanalWhatsappMode.SHARED`. `request_switch()` validates a channel-scoped
active membership and, when its commerce equals
`comercio_id_seleccionado`, currently calls `clear_pending_target()` before
returning `switch_requested`.

## Scope

- In the existing shared routing service, return
  `invalid_channel_mode` from manual option listing for an active non-shared
  channel, without reading options or mutating context.
- Preserve the pending target, selected commerce and original pending message
  when `request_switch` receives the currently selected commerce.
- Add focused regression tests for both cases, including a current-commerce
  request while another target is already pending.
- Update only this change's OpenSpec artifacts and spec delta.

## Non-goals

- No routes, webhooks, Twilio integration, receipt deduplication, automatic
  message processing, client creation, pipeline invocation, migrations, or
  database schema changes.
- No change to the existing typed public outcomes or to valid requests for a
  different membership, which continue to replace the pending target.
- No transaction control and no unrelated Phase-5.x cleanup.

## Shared boundary and outcomes

The sole boundary remains `SharedChannelRoutingService` over a caller-owned
SQLAlchemy session. For an active dedicated channel, `list_manual_options`
returns `invalid_channel_mode`. A request whose membership resolves to the
currently selected commerce returns the existing typed non-selection result
(`switch_requested`) but stages no change: it preserves any pending target.
Database exceptions propagate; they are not converted to business outcomes.

## Transaction ownership and observability

The service and repositories stage no mutation for either corrective path and
do not call `commit`, `rollback`, `begin`, `flush`, or `close`. Outcomes retain
the channel/client identifiers, safe state projections and stable
`resolution_source` values for the later provider boundary.

## Expected files

- `backend/services/shared_channel_routing_service.py`
- `backend/tests/test_shared_channel_manual_selection.py`
- `openspec/changes/correct-whatsapp-manual-selection-5-3-review-findings/*`

## Validation and rollback

Run the focused Phase-5.2/5.3 tests, Ruff and `compileall` on touched Python
files, strict OpenSpec validation and `git diff --check`. The correction has
no migration or external-state change; reverting it restores the reviewed
behavior.
