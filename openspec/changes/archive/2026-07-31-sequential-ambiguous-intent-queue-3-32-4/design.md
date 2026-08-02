## Context

Subphase 3.32.3 established `PendingIntents.active` plus a persisted FIFO `queue` and list-shaped pending results. Static inspection now shows two remaining boundary defects. First, `dispatch_initial_message` returns every `ProcessedIntent` produced by classification even after `process_initial_agregar_producto` has made the first unresolved item active and enqueued later items; the response layer therefore renders clarification text for inactive queued intents. Second, `execute_ready_pending_context` promotes the queue head and stops when it is `pending_resolution`, but returns only the preceding executed/rejected outcomes; the newly active item's clarification is absent from that HTTP response. Promotion also inherits the prior `session.context_type` rather than resolving it from the promoted intent.

The correction must use the existing persisted `ProcessedIntent` queue, preserve PostgreSQL transaction ownership in `process_incoming_message_transactional`, and keep response shaping outside queue orchestration. Before runtime edits, implementation must reproduce the exact three-turn HTTP flow and capture state at every boundary to confirm these are the first real-pipeline failures.

## Goals / Non-Goals

**Goals:**

- Allow exactly one interactive `agregar_producto` clarification to be active and customer-visible at a time.
- Preserve all later ready and ambiguous additions in classifier/source order across HTTP requests.
- Execute ready work before the first unresolved item, then pause; after resolution, drain promoted ready work and stop after emitting the next unresolved clarification.
- Preserve complete queued `ProcessedIntent` values, including quantities, candidate IDs, requirements, and refinement state.
- Return customer responses in actual processing order with no loss, premature clarification, or duplicate handler execution.
- Preserve one commit per successful incoming message and one rollback for a raised exception.

**Non-Goals:**

- Creating another queue, changing `PendingIntents` or `ProcessedIntent`, or adding a migration.
- Re-running classification/recognition for promoted work or reconstructing intents from response text.
- Changing matching, quantity, pricing, consolidation, handler, or response wording rules.
- Generalizing sequential batching to `quitar_producto` or `modificar_producto`.
- Redesigning the CLI, endpoint, fragment-level NLP, transaction wrapper, or transport layer.

## Decisions

### Treat dispatcher output as processed-now outcomes, not all recognized work

`dispatch_initial_message` will continue processing classified `agregar_producto` fragments in source order so their typed intents can be executed or persisted. Ready additions before the first unresolved item remain immediate outcomes. Once a `pending_resolution` item becomes active, that item is the last customer-visible result for the turn; later additions are still processed into full `ProcessedIntent` values and enqueued by the existing orchestration path, but are omitted from the returned list until promoted.

Alternative: return all classified results and make the response layer filter inactive items. Rejected because response shaping would need queue-state knowledge and could still expose stale or duplicate clarifications.

### Keep active-plus-FIFO as the only lifecycle model

The existing `set_pending_intent`, `enqueue`, `load`, and `remove_active` operations remain authoritative. Queue entries are persisted `ProcessedIntent` values and promotion uses those exact values; no classifier, recognizer, or full-catalog resolver is rerun solely because an item was queued.

Alternative: introduce batch IDs or a second queue. Rejected because the current schema already preserves ordered typed work across requests.

### Make promotion produce the next interaction boundary

After the active handler returns `executed` or definitive `rejected`, pending execution appends that outcome, removes only the active item, and inspects the promoted queue head. A promoted `ready` addition executes immediately and the loop continues. A promoted `pending_resolution` addition is appended once to the result list as the next clarification target, receives a context type from the existing resolver, and stops the loop. Queue exhaustion clears context. A returned `failed` result remains active and stops; a raised exception propagates.

Alternative: let the next customer message discover the promoted pending item. Rejected because the customer would receive no prompt describing what must be clarified.

### Recompute context type at promotion

When a persisted unresolved intent becomes active, orchestration calls the existing context-type resolver and stores that value on the session rather than blindly retaining the completed item's type. The current `agregar_producto` case resolves to `product_selection`, while the rule remains compatible with future queued context types.

Alternative: leave `context_type` unchanged because all current queued items are additions. Rejected because queue lifecycle should be driven by the promoted intent, not stale state.

### Keep response and transaction ownership unchanged

The pending dispatcher and incoming orchestrator propagate the ordered result list unchanged. Existing response builders convert each item in order, producing an executed/rejected response before the one promoted clarification. The transactional processor remains the sole commit/rollback owner, so handler exceptions roll back both domain mutations and queue advancement from that request.

Alternative: commit each promoted item independently. Rejected because it would expose partial batches and violate the existing message transaction boundary.

## Risks / Trade-offs

- [Later classified additions could be omitted from both output and queue] → Assert persisted active/queue contents after initial dispatch for pending-ready-pending permutations.
- [A promoted unresolved item could be returned twice] → Append it only at the transition where it becomes active and stop immediately.
- [Queue advancement could mutate quantity or candidates] → Compare promoted intents with their persisted values and prohibit recognition against the full catalog.
- [A later handler exception could leave partial data] → Propagate unchanged and verify the outer transaction rolls back order rows and pending state.
- [Changes could affect other intent contexts] → Scope FIFO draining and initial suppression to `agregar_producto`; rerun `quitar_producto` and `modificar_producto` regressions.
- [Static diagnosis may differ from the real HTTP path] → Make the exact PostgreSQL-backed reproduction the first implementation task and do not modify runtime code until the first failing boundary is reported.

## Migration Plan

No data migration is required. Deploy orchestration and tests together; existing persisted active/queue payloads remain schema-compatible and will use the corrected promotion behavior. Rollback consists of reverting the orchestration changes; no stored data conversion is needed.

## Open Questions

None. The exact three-turn flow and queue rules in `openspec/specs/project.md` are authoritative.
