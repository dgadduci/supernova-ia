## 1. Pending Intent Preservation

- [x] 1.1 Add focused pending-intent service tests proving definitive active removal promotes the FIFO queue head and non-definitive states preserve the complete queue.
- [x] 1.2 Update `agregar_producto` pending placement so a later pending addition is enqueued when an active addition already exists instead of overwriting it.
- [x] 1.3 Add initial orchestrator tests for first-active, subsequent-enqueued, queue-order, and no-handler/no-transaction side effects.

## 2. Initial Multi-Intent Dispatch

- [x] 2.1 Add initial-dispatcher tests for two pending additions, pending-then-ready, ready-then-pending, three-item ordering, and mixed non-`agregar_producto` classifications.
- [x] 2.2 Update `dispatch_initial_message` to preserve every classified `agregar_producto` in classifier order and retain later additions in the existing pending FIFO lifecycle without queueing other intent types.
- [x] 2.3 Verify existing single-intent, unsupported-intent, `quitar_producto`, and `modificar_producto` dispatcher tests remain unchanged and passing.

## 3. FIFO Execution and Context Lifecycle

- [x] 3.1 Add pending-context execution tests for multiple consecutive ready additions, executed/rejected promotion, pause at `pending_resolution`, stop on `failed`, final cleanup, and raised-exception preservation.
- [x] 3.2 Change `execute_ready_pending_context` to return `list[ProcessedIntent]`, remove only definitive active additions, promote through `remove_active`, and drain consecutive ready `agregar_producto` items in FIFO order.
- [x] 3.3 Keep `product_selection` context active while pending work remains, clear it only after queue exhaustion, and preserve existing scalar business behavior for `quitar_producto` and `modificar_producto` through one-item result lists.
- [x] 3.4 Assert execution and pending lifecycle code adds no commit, rollback, SQLAlchemy query, repository, response-generation, or HTTP side effects.

## 4. Result Propagation

- [x] 4.1 Add pending-context dispatcher tests proving ready resolution returns all drained outcomes while ambiguous and fallback paths return one-item lists and preserve queue order.
- [x] 4.2 Update `dispatch_pending_context` and all branches/callers to use `list[ProcessedIntent]` without dropping or double-wrapping outcomes.
- [x] 4.3 Add incoming-message orchestrator tests proving pending lists are propagated unchanged for one and multiple outcomes.
- [x] 4.4 Update `process_incoming_message` to return the pending dispatcher list unchanged and confirm the response orchestrator builds one ordered customer response per result.
- [x] 4.5 Verify transactional tests still prove exactly one commit per successful message and one rollback on a raised exception, including a message that executes multiple additions.

## 5. End-to-End Regression Coverage

- [x] 5.1 Add a real-component integration scenario for one ambiguous addition followed by a ready addition; resolve once and assert both execute exactly once in classifier/FIFO order.
- [x] 5.2 Add a real-component integration scenario for two ambiguous additions requiring two replies; assert first promotion, second completion, no loss, no duplication, and final cleanup.
- [x] 5.3 Add repeated-ambiguity coverage proving no order mutation and byte-equivalent queued ordering until a unique resolution.
- [x] 5.4 Re-run the existing single-product `agregar_producto` pending-resolution happy path and ambiguous-reply regression unchanged.

## 6. Verification

- [x] 6.1 Run the focused unit tests for initial orchestration, initial dispatch, pending-intent service, pending-context dispatch/execution, incoming-message orchestration, transactional processing, and response orchestration.
- [x] 6.2 Run the affected integration tests against `supernova_test` and report any environment prerequisite that prevents execution.
- [x] 6.3 Run the repository-provided lint and type-check commands and fix all failures introduced by this change.
- [x] 6.4 Update this checklist with completed tasks and stop without synchronizing specifications or archiving the change.
