## Why

The existing multi-intent preservation work retains multiple ambiguous `agregar_producto` intents, but the customer still receives clarification prompts for inactive queued items and promotion does not return the next active clarification after the current item executes. This leaves the real HTTP/CLI flow unable to process several ambiguous additions sequentially across requests.

## What Changes

- Diagnose the exact first failing boundary through the real three-turn PostgreSQL-backed HTTP flow before modifying runtime code.
- Make the first ambiguous `agregar_producto` intent the only active interactive context and retain every later ready or ambiguous addition in source order in the existing `PendingIntents.queue`.
- Return only outcomes processed up to the first unresolved item on initial dispatch, so queued ambiguous additions do not emit premature clarification prompts.
- After an active intent executes or is definitively rejected, promote persisted queued intents in FIFO order, execute promoted ready items immediately, and emit exactly one clarification when a promoted item remains unresolved.
- Preserve each queued `ProcessedIntent` in full, including source text, quantity, candidate IDs, requirements, resolved/refinement data, status, handler, and intent name; do not reclassify or reconstruct it.
- Restore the promoted intent's context type through the existing resolver, preserve one outer transaction per incoming message, and propagate technical exceptions for rollback.
- Add focused queue tests plus exact HTTP and CLI regressions for response order, queue persistence, quantities, candidates, rejection, rollback, and no duplicate execution.

## Capabilities

### New Capabilities

- None.

### Modified Capabilities

- `initial-intent-dispatcher`: Initial multi-intent processing must execute only ready additions before the first unresolved item, queue all later additions in source order, and expose only the active clarification.
- `pending-context-execution`: Definitive outcomes must promote persisted intents, drain ready items, restore context for the next unresolved item, and return that item's clarification outcome in processing order.
- `pending-context-dispatcher`: A clarification reply must return the executed/rejected active outcome followed by at most one newly promoted unresolved outcome.
- `incoming-message-orchestrator`: Initial and pending routes must propagate only the outcomes actually processed on that turn, without premature or duplicate queued results.
- `agregar-producto-end-to-end`: Real HTTP and CLI coverage must prove the exact sequential lifecycle, persisted queue, response order, quantity/candidate preservation, rollback, and final order contents.

## Impact

Affected code is expected in the initial intent dispatcher, pending-context execution/dispatch, incoming-message orchestration, pending context-type restoration, and focused HTTP/CLI integration tests. The existing `PendingIntents.active` plus FIFO `queue`, `ProcessedIntent` schema, endpoint, handlers, response builders, repositories, and transaction owner are reused; no migration, new endpoint, dependency, CLI redesign, second queue, classifier rerun, or API schema change is planned.
