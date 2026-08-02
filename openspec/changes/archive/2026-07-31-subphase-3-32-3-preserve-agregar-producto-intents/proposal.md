## Why

When one classified message contains multiple `agregar_producto` intents and any item requires product clarification, each pending result currently replaces the session's active intent while ready items are returned without execution. Earlier additions can therefore be lost, and resolving the surviving pending item does not reliably execute the remaining additions.

## What Changes

- Preserve every classified `agregar_producto` intent in classifier order when product selection becomes pending, using the existing active-plus-queue pending state instead of overwriting prior work.
- Execute ready `agregar_producto` intents while advancing through the preserved queue after each product-resolution reply.
- Promote the next queued addition after a definitive result, keep product-selection context open while more additions remain, and clear context only after the full batch is complete.
- Return every `ProcessedIntent` produced during queue advancement in deterministic order so response generation can acknowledge all executed additions.
- Add unit and end-to-end regression coverage for mixed ready/pending additions, multiple pending additions, repeated clarification, ordering, persistence, and transaction behavior.

## Capabilities

### New Capabilities

- None.

### Modified Capabilities

- `agregar-producto-intent-orchestration`: Initial processing must preserve additional pending additions rather than replacing the active pending intent.
- `initial-intent-dispatcher`: Multiple classified `agregar_producto` items must remain ordered and enter the pending execution lifecycle without loss.
- `pending-intent-service`: Active removal and queue promotion must support processing all preserved additions without clearing the remaining queue.
- `pending-context-execution`: Definitive execution must advance and execute queued ready additions, pausing at the next unresolved addition and clearing context only when exhausted.
- `pending-context-dispatcher`: Product-selection replies must return all outcomes produced while advancing the pending addition queue.
- `incoming-message-orchestrator`: Pending-context processing must propagate multiple ordered outcomes from one resolution message.
- `agregar-producto-end-to-end`: Integration coverage must prove all additions survive and execute across one or more product-selection replies.

## Impact

Affected areas are the `agregar_producto` initial orchestrator, initial and pending dispatchers, pending-intent lifecycle service, pending-context execution, incoming-message orchestration, response propagation, and their unit/integration tests. The existing `PendingIntents.active` and `queue` schema is reused; no database migration, API shape change, new dependency, handler business-rule change, or transaction-owner change is required.
