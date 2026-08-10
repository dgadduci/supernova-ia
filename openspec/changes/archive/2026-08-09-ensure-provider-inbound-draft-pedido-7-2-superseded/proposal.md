## Why

The controlled WhatsApp pilot reached the existing inbound, recognition,
outbox and outbound-delivery path. A valid product selection then produced the
generic rejection because the provider-created active conversation session had
`id_pedido = NULL`. `agregar_producto` correctly refuses to mutate without an
associated draft pedido.

The interactive CLI already creates and associates a draft pedido explicitly;
the provider inbound coordinator currently stages only the conversation
session. The provider path therefore cannot complete its supported product
addition lifecycle from a new or previously orderless active session.

## Objective

Within the existing provider inbound transaction, ensure that an active
provider conversation session with no associated pedido receives exactly one
new draft pedido associated to that session before the existing message
pipeline runs.

## Current execution path

`Twilio webhook -> ProviderInboundMessageCoordinator -> receipt claim ->
SessionRepository.stage_active -> existing incoming-message pipeline ->
outbox staging -> one coordinator commit`.

`stage_active` intentionally creates an active session with no pedido. The
later `agregar_producto` handler rejects any ready addition when
`conversation_session.id_pedido is None`.

## Scope

- Extend only the provider inbound coordinator's existing transaction to stage
  and associate one `borrador` pedido when the acquired active session has no
  `id_pedido`.
- Reuse `Pedido`, `PedidoRepository`, `Session`, and the existing coordinator
  transaction boundary; no service that owns its own transaction is used.
- Add focused unit and PostgreSQL integration coverage for first provider
  receipt, existing orderless active session, duplicate receipt, and rollback.
- Add the corresponding delta to `provider-message-receipt-core`.

## Non-goals

- No changes to Twilio parsing/routing, outbox, dispatcher, callbacks,
  recognition policy, pending-candidate resolution, customer response wording,
  CLI behavior, schemas, migrations, workers, schedulers, or configuration.
- No repair, replacement, reassociation, closure, or state transition for an
  existing non-null pedido. Existing invalid/non-draft associations retain
  their current downstream behavior.
- No direct Railway SQL or manual data repair in this change.

## Shared boundary, outcomes, and fallback

| Condition | Authoritative outcome | Fallback |
| --- | --- | --- |
| First valid receipt, active session has no pedido | Stage one new `borrador` pedido, associate it, then run the existing pipeline | Normal processing continues |
| First valid receipt, active session already has `id_pedido` | Do not stage or modify a pedido | Existing processing remains unchanged |
| Duplicate committed receipt | Do not create a session or pedido and do not run pipeline | `already_processed` |
| Any flush/pedido/pipeline/outbox technical failure | Roll back receipt, newly staged session/pedido/association and all pipeline effects | Propagate technical failure; later retry remains eligible |

## Transaction ownership and observability

`ProviderInboundMessageCoordinator` remains the sole owner of the transaction.
Its repositories may stage ORM rows but never commit or roll back. The
coordinator may flush solely to obtain generated identifiers and make the
session-to-pedido association valid; it commits once after receipt, session,
pedido, existing pipeline and outbox staging all succeed.

Existing safe coordinator outcome/log fields remain unchanged. No body,
address, credential, database URL, or raw exception is added to observability.

## Expected files

- `backend/services/provider_inbound_message_coordinator.py`
- `backend/repositories/pedido_repository.py`
- `backend/tests/test_provider_message_receipt_core.py`
- `backend/tests/test_provider_message_receipt_core_integration.py`
- `openspec/changes/ensure-provider-inbound-draft-pedido-7-2/`

## Focused tests and validation

Cover one new session and one existing orderless session receiving exactly one
associated `borrador` pedido; an already-associated session unchanged;
duplicate receipts creating none; and rollback after a downstream failure
leaving no receipt/session/pedido association durable. Preserve the current
coordinator's one commit/rollback ownership checks.

The user runs locally:

```bash
PYTHONPATH=. venv/bin/python -m pytest backend/tests/test_provider_message_receipt_core.py backend/tests/test_provider_message_receipt_core_integration.py backend/tests/test_twilio_webhook.py backend/tests/test_agregar_producto_sequential_queue_end_to_end.py
PYTHONPATH=. venv/bin/python -m ruff check backend/services/provider_inbound_message_coordinator.py backend/repositories/pedido_repository.py backend/tests/test_provider_message_receipt_core.py backend/tests/test_provider_message_receipt_core_integration.py
PYTHONPATH=. venv/bin/python -m compileall -q backend/services/provider_inbound_message_coordinator.py backend/repositories/pedido_repository.py backend/tests/test_provider_message_receipt_core.py backend/tests/test_provider_message_receipt_core_integration.py
openspec validate ensure-provider-inbound-draft-pedido-7-2 --strict
git diff --check
```

## Rollback and deferred limitations

The code change is reversible by deployment rollback. It does not delete draft
pedidos already created by valid traffic; any cleanup of pilot business data
requires a separately approved operational decision. Order confirmation,
payment, delivery, and automatic session closure remain deferred.
