## Why

The deployed Twilio WhatsApp webhook reaches Railway but the current synchronous
inbound path does not return an HTTP response before Twilio's configured
15-second limit. Railway recorded a `499` after 14,977 ms with zero response
bytes, and Twilio recorded error `11200`. The request therefore times out
before any receipt, recognizer result, session effect or outbound response is
durable.

The synchronous path calls the intent classifier and product recognizer during
the webhook request. Those dependencies may exceed the provider deadline.
Returning an immediate TwiML response without durable deferred work would lose
the message; a FastAPI background task would not survive a process restart and
is not an acceptable queue.

## Objective

Make the provider webhook acknowledge a valid inbound message quickly by
durably accepting one idempotent receipt plus one deferred inbound work item.
Provide an explicit, bounded operator CLI that processes due items through the
existing message pipeline and existing outbound outbox after the HTTP request
has completed.

## Current execution path

`Twilio webhook -> signature/route validation -> ProviderInboundMessageCoordinator
-> receipt claim -> session/draft pedido -> classifier + recognizer + pipeline
-> outbound rows -> commit -> TwiML response`.

The classifier/recognizer makes this path exceed 15 seconds. The existing
outbound dispatcher is already a bounded, lease-protected CLI, but no durable
inbound work surface exists. `RecepcionMensajeProveedor` intentionally stores
no message body, so it cannot replay deferred processing.

## Scope

- Add a durable, receipt-keyed provider inbound work item with a nullable
  transient message body, safe state/lease/attempt fields and a migration.
- Change the signed Twilio webhook path to validate the existing routing
  authority, atomically claim the receipt and stage exactly one inbound work
  item, then return empty TwiML without classifier, recognizer, session,
  pedido or outbound work.
- Add one explicit bounded CLI that claims at most the requested number of due
  inbound work items and processes each through the existing session/draft
  pedido, intent pipeline, response mapper and outbound outbox.
- Reuse existing canonical routing, session, pedido, pipeline and outbound
  contracts. Preserve explicit manual outbound dispatch as a separate pass.
- Add focused unit, PostgreSQL integration, webhook and CLI tests; update the
  relevant provider-receipt/outbound capability deltas and tasks.

## Non-goals

- No worker, scheduler, cron, FastAPI background task, polling loop,
  automatic inbound processing or automatic outbound dispatch.
- No changes to recognition policy, candidate widening, aliases, hybrid/vector
  settings, Twilio sender rendering, client/channel routing rules, customer
  wording, payment/delivery/order closure, or public administration endpoints.
- No direct Railway SQL/manual repair, no message-body logging or pilot-evidence
  retention, and no migration downgrade as an operational cleanup mechanism.

## Shared boundary, authoritative outcomes and fallback

| Condition | Webhook outcome | Deferred processor outcome |
| --- | --- | --- |
| Valid first receipt and queue staging succeeds | Empty TwiML `200` after one acceptance commit | `pending` work awaits explicit CLI pass |
| Duplicate committed receipt | Empty TwiML `200`; no second work item | No reprocessing/replay |
| Invalid client/channel/authority | Existing generic control TwiML; no receipt/work | None |
| Acceptance DB/technical failure | Error response; no receipt/work commit | Twilio may retry the same receipt |
| Due work executes successfully | N/A | Session/pedido/pipeline/outbox effects and work completion commit atomically |
| Processing technical failure | N/A | Roll back business effects; retain transient body and schedule bounded retry |
| Retry budget exhausted / terminal processor contract failure | N/A | Terminal safe state, scrub transient body; no automatic retry |

## Data handling and transaction ownership

The new work item stores the inbound body only while it is required to process
or retry the receipt. On successful processing or terminal exhaustion, the
processor clears the body and retains only receipt relation, state, attempt
count, safe failure category/code and timestamps. It never exposes body text in
CLI output, logs, diagnostics or pilot evidence.

Acceptance owns one short transaction: receipt claim plus work staging commit
together. Processing owns a distinct transaction per leased work item: it
claims the lease, runs the existing pipeline, stages outbound responses tied to
the pre-existing receipt and finalizes the work row in the same commit. No
repository owns commit/rollback; no transaction is shared across HTTP and CLI
processes.

## Conversational ordering

The processor operates in receipt creation order for due rows. A later work
item for the same `(canal_id, cliente_id)` pair MUST NOT be claimed while an
earlier item for the same conversation remains in any non-terminal state
(`pending`, `leased` or `retryable`). The conversational block is
unconditional based on state and is independent of `lease_expira_en` and
`proximo_intento_en`: a `retryable` row whose `proximo_intento_en` is in the
future still blocks a later item in the same conversation because the row
is not yet terminal, and a `leased` row whose lease has already expired
still blocks a later item in the same conversation even though the row
remains eligible for its own lease-recovery claim. Only `processed` and
`failed_terminal` rows never block a later item in the same conversation.
"Earlier" is defined by the receipt creation order
(`recepciones_mensajes_proveedor.fecha_recepcion` with
`recepciones_mensajes_proveedor.id` as the stable tiebreaker), NOT by the
autoincrement id of the work item itself. Conversations that do not share
the `(canal_id, cliente_id)` pair remain fully independent and never block
each other. The exclusion is enforced inside the single `claim_due` query
as a correlated `NOT EXISTS` subquery; the CLI and the coordinator do not
perform any second-pass filtering.

The candidate's own eligibility remains time-bounded so the bounded CLI
never violates the documented retry budget: a `retryable` candidate is
only claimable when its `proximo_intento_en` is due (or unset), and a
`leased` candidate is only claimable through the lease-recovery path when
its `lease_expira_en` is in the past. The conversational block targets
strictly later rows, so a candidate that is its own earliest unresolved
row remains eligible.

## Expected files

- `backend/models/procesamiento_mensaje_proveedor.py`
- One new migration under `backend/alembic/versions/` for
  `procesamientos_mensajes_proveedor`
- `backend/repositories/procesamiento_mensaje_proveedor_repository.py`
- `backend/services/provider_inbound_message_coordinator.py` (split its
  acceptance and business-processing responsibilities without adding a parallel
  pipeline)
- `backend/routers/twilio_webhook.py`
- `backend/cli/run_inbound_processing.py`
- `backend/tests/test_procesamiento_mensaje_proveedor_model.py`
- `backend/tests/test_provider_message_receipt_core.py`
- `backend/tests/test_provider_message_receipt_core_integration.py`
- `backend/tests/test_twilio_webhook.py`
- `backend/tests/test_run_inbound_processing_cli.py`
- This OpenSpec change and deltas for `provider-message-receipt-core` and a new
  inbound-processing capability

## Focused tests and validation

Tests must prove the webhook acceptance path does not call classifier,
recognizer, session/pedido creation or outbound mapping; first/duplicate/invalid
receipt behavior; one receipt-to-one work-item uniqueness; body scrubbing after
completion/exhaustion; lease/attempt/retry behavior; rollback atomicity;
processing creates exactly the existing session/draft pedido/outbox effects;
and the CLI processes a bounded number of due rows with sanitized output.

The user runs locally:

```bash
PYTHONPATH=. venv/bin/python -m pytest backend/tests/test_procesamiento_mensaje_proveedor_model.py backend/tests/test_provider_message_receipt_core.py backend/tests/test_provider_message_receipt_core_integration.py backend/tests/test_twilio_webhook.py backend/tests/test_run_inbound_processing_cli.py backend/tests/test_run_outbound_dispatch_cli.py
PYTHONPATH=. venv/bin/python -m ruff check backend/models/procesamiento_mensaje_proveedor.py backend/repositories/procesamiento_mensaje_proveedor_repository.py backend/services/provider_inbound_message_coordinator.py backend/routers/twilio_webhook.py backend/cli/run_inbound_processing.py backend/tests/test_procesamiento_mensaje_proveedor_model.py backend/tests/test_provider_message_receipt_core.py backend/tests/test_provider_message_receipt_core_integration.py backend/tests/test_twilio_webhook.py backend/tests/test_run_inbound_processing_cli.py
PYTHONPATH=. venv/bin/python -m compileall -q backend/models/procesamiento_mensaje_proveedor.py backend/repositories/procesamiento_mensaje_proveedor_repository.py backend/services/provider_inbound_message_coordinator.py backend/routers/twilio_webhook.py backend/cli/run_inbound_processing.py backend/tests/test_procesamiento_mensaje_proveedor_model.py backend/tests/test_provider_message_receipt_core.py backend/tests/test_provider_message_receipt_core_integration.py backend/tests/test_twilio_webhook.py backend/tests/test_run_inbound_processing_cli.py
PYTHONPATH=. venv/bin/python -m alembic upgrade head
openspec validate defer-provider-inbound-processing-7-4 --strict
git diff --check
```

## Rollback and deferred limitations

Rollback is deployment rollback. Rows already accepted retain their safe receipt
audit and may retain transient pending bodies until the approved processor
handles or expires them; the system introduces no destructive cleanup command.
An always-on worker, throughput scaling, user-visible queue acknowledgements,
and broader message-retention policy are deferred.
