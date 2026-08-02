## Context

Subphase 3.32.4 established one active ambiguous `agregar_producto` intent plus a persisted FIFO queue and a drain loop that executes ready additions until another customer interaction is required. In the real two-turn flow `quiero una empanada de carne y una pizza` followed by `picante`, the active Carne intent remains unresolved and its clarification repeats indefinitely, so no handler execution or Pizza promotion occurs. The correction crosses resolver, pending persistence, dispatch, execution, orchestration, response, and PostgreSQL integration boundaries while retaining the existing architecture.

Implementation must begin with an instrumented reproduction through the real HTTP pipeline. The first failing boundary and concrete state transitions must be reported before runtime code is modified; the recognizer must not be presumed at fault. SQLAlchemy remains confined to repositories/services that already own persistence, and the transactional message processor remains the sole commit/rollback owner.

## Goals / Non-Goals

**Goals:**

- Prove where `picante` first fails against the persisted Carne candidate catalog.
- Resolve unique discriminating fragments only within the active intent's candidate IDs while preserving quantity and all unrelated intent fields.
- Keep one authoritative pending state per transaction so stale serialized state cannot overwrite a resolved active intent.
- Execute a newly ready active addition exactly once and promote the persisted FIFO queue head without loss, duplication, reclassification, or catalog broadening.
- Return ordered outcomes: Carne execution first, then one promoted Pizza clarification; complete Pizza on the third turn.
- Cover exact HTTP, focused unit/integration, transactional failure, quantity, and existing-intent regressions.

**Non-Goals:**

- Redesigning the CLI, pending-intent schema, queue model, response API, or transaction boundary.
- Adding a queue, endpoint, confirmation turn, intent, Twilio integration, migration, or dependency.
- Reclassifying clarification-only messages or showing inactive queued clarifications.
- Synchronizing or archiving OpenSpec artifacts during implementation.

## Decisions

### Diagnose the first failing boundary before selecting the fix

Run the exact two HTTP turns against PostgreSQL and capture classified order, active/queue values, candidate IDs, context type, pending state before/after, restricted catalog, raw recognizer output, resolver output, status transitions, handler calls, promotion, responses, and order rows. Change runtime code only after the first incorrect transition is identified. This avoids a speculative recognizer patch when persistence or dispatch may be restoring stale state.

Alternative considered: directly extend fuzzy matching for `picante`. Rejected because aliases already exist and the defect may occur after recognition.

### Treat the persisted active intent and restricted catalog as the resolution boundary

Product-selection resolution will use only `active_intent.candidate_ids`. Discriminating fragments including `picante`, `la picante`, `carne picante`, `la común`, and `la de carne común` may refine candidates; one valid remaining ID applies the existing unique-selection path, clears candidate IDs, completes the product requirement, preserves quantity/resolved data, and returns `ready`. Zero matches preserve active and queue; multiple matches preserve only a legitimate refined active set.

Alternative considered: rerun unrestricted commerce recognition or initial classification. Rejected because it can select outside the persisted ambiguity and create duplicate intents.

### Maintain one authoritative pending state through dispatch and execution

The resolver result becomes authoritative for the active intent. Dispatch persists/stages that exact result once and invokes ready execution without later reapplying the pre-resolution active value. Any refresh is limited to an existing service pattern and added only if diagnosis proves ORM staleness. Queue advancement uses the persisted `PendingIntents` value rather than rebuilding from response text or an outdated session snapshot.

Alternative considered: add unconditional ORM refreshes. Rejected because they can mask ownership errors and introduce unnecessary persistence coupling.

### Reuse the existing deterministic drain-and-promote loop

After the ready active handler returns `executed` or definitive `rejected`, remove only that active item, preserve the queue, promote its head, derive context type from the promoted intent, execute consecutive ready additions, and stop at one unresolved active item or failure. Returned outcomes remain ordered and unique. Raised exceptions propagate to the transactional wrapper, which rolls back the complete message.

Alternative considered: promote in the dispatcher or response layer. Rejected because pending-context execution already owns FIFO advancement and exactly-once handler sequencing.

### Verify at behavior and persistence boundaries

Focused tests will assert resolver output and raw recognizer behavior; dispatcher/execution tests will assert state authority and promotion; HTTP tests will use the exact two- and three-turn messages and inspect active/queue state, response order, handler count, and `PedidoProducto` rows. Existing agregar/quitar/modificar and quantity-response regressions remain mandatory.

## Risks / Trade-offs

- [The root cause differs from the likely resolver path] → Preserve diagnosis as the first task and make the smallest correction at the proven boundary.
- [A broader candidate refinement changes unrelated ambiguity behavior] → Restrict every selected/refined ID to the original active candidate set and retain no-match/multi-match tests.
- [Stale session state reintroduces the old active value] → Assert pending state before and after dispatch/execution and prevent post-resolution writes from stale copies.
- [Promotion loses or duplicates queued work] → Assert full `ProcessedIntent` equality-relevant fields, FIFO order, handler call counts, and persisted rows after every turn.
- [An exception leaves partial in-memory advancement] → Keep commit/rollback out of orchestrators and test rollback through the transactional HTTP boundary.
- [PostgreSQL and manual CLI coverage are slower] → Keep focused unit tests for diagnosis and reserve full integration/manual checks for acceptance.

## Migration Plan

No schema or data migration is required. Implement the smallest proven runtime correction, run focused tests, then PostgreSQL-backed HTTP regressions and the broader intent suite. Rollback consists of reverting the runtime/test changes; persisted data formats and APIs remain compatible.

## Open Questions

- Which exact boundary first diverges in the real reproduction: restricted catalog construction, recognizer output interpretation, resolver refinement, `set_active`, or subsequent pending-state reload?
- Does the correction require any session refresh, or can state ownership be fixed entirely by eliminating a stale write/reconstruction?
