## Why

The sequential ambiguous-product queue can become stuck when a customer uniquely identifies the active candidate with a short fragment such as `picante`: the same clarification is returned indefinitely, the active addition never executes, and the next queued addition is never promoted. Subphase 3.32.5 must correct the first failing runtime boundary while preserving candidate scope, quantities, FIFO state, and the existing one-transaction-per-message contract.

## What Changes

- Diagnose the exact two-turn PostgreSQL-backed HTTP flow before changing runtime code and identify the first boundary where `picante` fails to resolve.
- Resolve discriminating fragments against only the active intent's persisted candidate IDs, preserving resolved data and quantity and transitioning a unique selection to `ready`.
- Prevent stale or unchanged active state from replacing a newly resolved intent or recreating the prior candidate set.
- Execute the resolved active `agregar_producto` intent exactly once, remove only that completed active item, and promote the next queued ambiguous product in FIFO order.
- Return the active execution confirmation followed by exactly one clarification for the promoted queued product in the same response.
- Add focused resolver, dispatcher, execution, orchestration, transactional, and exact two-/three-turn PostgreSQL HTTP regressions, including quantity, candidate-defense, queue-loss, duplicate, rejection, exception, and existing-intent coverage.
- Preserve the existing CLI, queue model, endpoints, classifier routing, repository boundaries, transaction ownership, and manual sync/archive workflow.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `product-selection-context-resolver`: Require deterministic unique resolution of short discriminating fragments within the persisted active candidate catalog.
- `pending-context-dispatcher`: Ensure the resolved active value is authoritative and ready resolution advances execution without repeated clarification or duplicate state.
- `pending-context-execution`: Preserve exactly-once active execution, FIFO promotion, promoted context restoration, and rollback-safe state advancement.
- `incoming-message-orchestrator`: Preserve the complete ordered active-execution and promoted-clarification result for clarification-only messages.
- `agregar-producto-end-to-end`: Cover the exact failing HTTP sequence, third-turn completion, persistence, quantities, candidate scope, failures, and regressions.

## Impact

Affected areas include product-selection resolution and candidate refinement, pending-intent persistence and dispatch, ready-context execution and FIFO promotion, incoming-message result propagation, response orchestration, and PostgreSQL-backed integration tests under `backend/intents/`, `backend/recognizers/`, and `backend/tests/`. No API, schema, migration, dependency, additional queue, or transaction-boundary change is intended.
