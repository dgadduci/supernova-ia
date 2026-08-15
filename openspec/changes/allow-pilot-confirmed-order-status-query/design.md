# Design: safe local status queries after confirmation

## Decision

Use the existing intent classifier for language interpretation only, then
enforce an endpoint-local allowlist before any business orchestration runs.
The only allowlisted confirmed-order result is one
`consultar_estado_pedido` intent. This avoids duplicating the classifier or
introducing a second message pipeline while making it impossible for classifier
output to trigger a post-confirmation mutation.

## Execution design

1. Keep the current strict loader for an exact active draft and preserve its
   call to `process_incoming_message_with_responses` unchanged.
2. Add a separate exact-target loader or explicit result that can distinguish a
   valid confirmed-or-later order from an invalid target, while enforcing the
   same `pedido.id`, `session.id_pedido`, active-session, client, and commerce
   consistency checks. It never searches for another session or successor.
3. A valid non-draft target is eligible only when `session.context_type` is
   absent and its pending state is semantically empty/absent. A malformed,
   active, queued, or otherwise non-empty pending state fails closed.
4. Invoke the existing `IntentClassifier` once for the operator text. Require
   a parsed result containing exactly one item whose enum is
   `IntentName.CONSULTAR_ESTADO_PEDIDO`.
5. On that sole accepted outcome, call
   `process_initial_order_status_query(db, exact_session, classified.mensaje)`
   and render its singleton result with `build_customer_responses`. Return the
   existing typed local response and re-load the same exact identity for the
   safe execution-state and order-lines snapshots.
6. For every other outcome, return `_reject_local_test(...)` without invoking
   `process_incoming_message_with_responses`, the initial dispatcher, or any
   mutating handler. Do not map a rejected classifier result into a business
   response because the route's existing generic rejection is the closed
   operator-facing contract.

## Authoritative outcomes and fallback

| Input state | Classifier output | Action |
| --- | --- | --- |
| Valid draft | Any current valid message | Current processor path, unchanged |
| Valid confirmed exact order, clean context | Exactly one status intent | Read status only |
| Valid confirmed exact order, clean context | Any non-status intent | Fail closed |
| Valid confirmed exact order, clean context | More than one intent | Fail closed |
| Valid confirmed exact order, clean context | Transport/schema/validation exception | Fail closed |
| Any non-draft target with active/queued/invalid pending state | N/A | Fail closed before classifier |
| Missing, foreign, inactive, inconsistent, or re-pointed target | N/A | Existing generic rejection |

No classifier result may fall back into the draft message processor. No
classifier failure may fall back to deterministic phrase matching. The existing
global dispatcher remains untouched, so provider/WhatsApp behavior remains
unchanged.

## Transaction and response ownership

The confirmed path has no independent transaction boundary and must not call
`commit`, `rollback`, `flush`, `refresh`, `begin`, `begin_nested`, `close`, or
`expire`. `process_initial_order_status_query` remains the authoritative
read-only business function; `build_customer_responses` remains the shared
renderer. The draft processor retains ownership of its existing transactional
turn exactly as before.

## Privacy and observability

The endpoint continues to return only the existing typed response fields,
closed execution snapshot, and typed order-line snapshot. It does not expose
classified payloads, prompt text, raw customer text beyond the volatile
browser transcript, IDs, pending JSON, exception details, configuration, or
provider data. Existing classifier diagnostic hygiene applies; this change
adds no new raw-text diagnostic field or public response field.

## Tests

Focused route tests shall prove:

- a confirmed exact order accepts a classifier-derived natural-language status
  request and returns the existing status response;
- draft route behavior remains on the existing processor seam;
- non-status (`iniciar_pedido`, add/remove/modify/cancel) and multi-intent
  classifier output are rejected and call neither message processor nor status
  orchestration;
- classifier transport/schema failure is generically rejected without internal
  leakage;
- pending, malformed pending, and identity/ownership failure reject before
  classification;
- the accepted confirmed path neither creates/replaces a session/order nor
  calls transaction controls, provider, outbox, worker, or Twilio paths;
- response and safe snapshots continue to use the same exact session/order
  identity.
