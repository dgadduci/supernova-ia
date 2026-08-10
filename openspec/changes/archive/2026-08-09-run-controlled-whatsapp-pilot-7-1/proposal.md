## Why

The completed implementation now has a deployed provider boundary, private
Ollama reachability, an inbound WhatsApp route, a durable outbound outbox and
an explicit bounded dispatcher. Before adding order-confirmation behavior, the
project needs evidence that those existing surfaces operate together under a
small, reversible real-world pilot.

## Objective

Run a controlled WhatsApp pilot for one explicitly selected commerce using
the existing deployment, inbound, outbox and dispatcher surfaces. Before its
first live case, add one narrow, reversible provisioning/verification command
for the already-supported client and dedicated-channel routing data. Produce a
safe operator evidence record that determines whether the current baseline is
fit to begin the next order-domain phase.

## Current execution path

`Twilio WhatsApp webhook -> durable deferred inbound work item -> explicit
backend.cli.run_inbound_processing pass -> existing incoming-message
orchestration -> durable outbound provider-message outbox -> explicit
backend.cli.run_outbound_dispatch pass -> Twilio delivery callback`.
For local/manual diagnosis, `backend.scripts.cli_chat_client` uses the public
HTTP endpoints and supports `--debug-flow` without importing application
internals.

At ingress, the signed webhook normalizes `From` and `To`, resolves an existing
active `Cliente` by `From`, then calls `CommerceChannelResolver` with provider
`twilio` and the destination `To`. Only an active `DEDICATED`
`CanalWhatsapp` whose active exclusive commerce resolves proceeds to first
processing. Any missing/inactive client or non-resolved channel returns the
generic control TwiML before the coordinator and outbox.

## Scope

- Define the readiness gate, pilot script and evidence template for one
  commerce and designated test customer numbers.
- Add a one-shot internal CLI provisioning boundary which, on explicit apply,
  ensures the selected test `Cliente` is active and the configured Twilio
  sender has exactly one active `DEDICATED` channel for the selected active
  commerce. Its default is read-only verification.
- Reuse the existing `Cliente`, `CanalWhatsappService`,
  `CanalWhatsappRepository` and `CommerceChannelResolver` contracts. The
  command reports only stable IDs, enum/status values and pass/fail counters;
  it never prints E.164 values or message bodies.
- Exercise the existing CLI locally against a controlled environment and the
  existing WhatsApp/Twilio path in production-shaped infrastructure.
- Require explicit, bounded inbound-processing and outbound-dispatch passes,
  and inspect safe delivery outcomes.
- Classify observations as business outcomes, technical failures, or
  recognition-quality follow-ups without changing current behavior.

## Non-goals

- No change to order intents, confirmation, payment, delivery, catalog,
  recognition policy, schemas, migrations, Twilio routes, workers, schedulers,
  queues, monitoring platforms or CI/CD.
- No automatic enabling of a real public WhatsApp number, bulk messaging,
  real customer traffic, or automatic outbound dispatch.
- No routing administration HTTP endpoint, direct PostgreSQL edits, data
  import, automatic client creation from inbound traffic, channel
  reassignment, or reuse of an inactive channel.
- No retention of message bodies, prompts, generated text, vectors,
  credentials, signatures, database URLs, or customer personal data in pilot
  evidence.

## Shared boundary, outcomes and fallback

| Condition | Authoritative outcome | Fallback |
| --- | --- | --- |
| Infrastructure gates and controlled cases pass | Pilot is eligible to continue within the agreed small cohort | Continue only with explicit operator dispatches |
| Product ambiguity is returned and clarified within the existing flow | Valid business outcome | Record the safe identifier/category only; do not broaden candidate sets |
| Recognition, response, delivery, callback or infrastructure failure | Technical or quality failure | Stop affected pilot traffic, retain safe evidence, diagnose in a separate approved change |
| A case needs payment, delivery selection or final confirmation | Expected unsupported business outcome | Do not improvise persistence or operator mutation; defer to the next order-domain proposal |
| Routing verification finds a missing active client or channel | Not ready; verification makes no mutation | Use the approved one-shot apply command only after target identity is confirmed |
| Routing verification finds a conflicting/inactive channel or wrong commerce ownership | Technical/configuration failure | Make no mutation; stop and diagnose in a separate approved action |
| Any readiness gate fails | Pilot is not eligible | Keep real traffic disabled and use CLI/local verification only |

## Transaction ownership and observability

The provisioning command is the sole owner of its short setup transaction: it
may flush its staged client/channel state for the final resolver check, commits
once only when that check succeeds, and rolls back on a technical or invariant
failure. It does not enter the inbound coordinator, recognition pipeline,
outbox or dispatcher.
The webhook owns receipt/work-item acceptance; the bounded inbound processor
owns its lease and business-processing transactions; the outbound dispatcher
and callback retain their existing boundaries. Evidence may contain timestamps,
deployment/revision identifiers, anonymized case IDs, numeric internal IDs,
route status, outbox safe IDs/SIDs, dispatch counters, callback states and
pass/fail classification. It must not contain E.164 values, sensitive or raw
business content.

## Expected files

- `backend/cli/provision_whatsapp_pilot_routing.py` and a focused service or
  small repository staging helper only if needed to preserve a single setup
  transaction.
- Focused tests for the provisioning/verification contract.
- This OpenSpec change only: proposal, design, pilot capability delta and
  tasks.

## Focused tests and validation

The user performs the existing local focused validation and all live manual
checks. The pilot requires the new focused provisioning tests; Railway
release/revision/health evidence with Alembic at head before live traffic; the
existing safe Ollama contract probe; a
CLI happy path and ambiguity path with `--debug-flow`; routing verification;
one controlled WhatsApp inbound case; one explicitly invoked bounded inbound
processing pass; one explicitly invoked bounded outbound dispatch; and a
signed delivery callback outcome. Exact commands are in
`design.md`. No result is considered passed until the complete user-reported
output/evidence is reviewed.

## Rollback and deferred limitations

Rollback is to stop the pilot and deactivate only the newly-created dedicated
channel through an approved follow-up operational action; a newly-created test
client may be deactivated only when it has no unrelated history. Existing
clients/channels are never reassigned or deleted by this change. Disable the
Twilio production route if needed, and use Railway rollback only for a
demonstrated deployment regression; no database downgrade is automatic.
Automatic dispatch, monitoring/alerting, full customer rollout, and order
confirmation/payment/delivery capture remain deferred.
