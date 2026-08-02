## ADDED Requirements

### Requirement: Ready agregar_producto queue draining
Pending-context execution SHALL return an ordered `list[ProcessedIntent]`. For `agregar_producto`, it SHALL execute the active ready intent, append its outcome, promote after each definitive `executed` or `rejected` result, and continue executing consecutive promoted ready additions.

#### Scenario: Two ready additions execute in FIFO order
- **WHEN** the active addition and the queue head are both ready
- **THEN** both handlers execute exactly once in FIFO order and both outcomes are returned in that order

#### Scenario: Definitive rejection does not discard later addition
- **WHEN** the active handler returns `rejected` and the promoted queue head is ready
- **THEN** the rejected outcome is returned first and the promoted addition executes and is returned second

### Requirement: Queue draining pauses at unresolved or failed work
Execution SHALL stop when the promoted active addition has `status == "pending_resolution"` or when a handler returns `failed`, preserving that active item and the remaining queue.

#### Scenario: Promotion reaches unresolved addition
- **WHEN** an executed active addition promotes a `pending_resolution` addition
- **THEN** execution returns the executed outcome, leaves the unresolved addition active, preserves the queue tail, and does not call its handler

#### Scenario: Handler failure stops draining
- **WHEN** a ready active handler returns `failed`
- **THEN** the failed outcome is returned, that intent remains active, and no queued handler executes

### Requirement: Context clears only after agregar_producto queue exhaustion
The execution flow SHALL keep `session.context_type == "product_selection"` while an active or queued addition remains and SHALL clear pending context only after the final definitive addition has been removed.

#### Scenario: Intermediate execution keeps context open
- **WHEN** one addition executes and another unresolved addition is promoted
- **THEN** product-selection context remains active

#### Scenario: Final execution clears context
- **WHEN** the final active addition executes and no queue remains
- **THEN** pending state is empty and `session.context_type is None`

### Requirement: Transaction and exception boundaries remain unchanged
Pending-context execution SHALL NOT commit or roll back, and raised handler exceptions SHALL propagate unchanged without removing active or queued intents.

#### Scenario: Raised exception preserves outer rollback ownership
- **WHEN** an agregar-producto handler raises
- **THEN** execution re-raises the same exception, does not clear pending state, and does not call commit or rollback
