## ADDED Requirements

### Requirement: Pending agregar_producto preservation does not overwrite active work
When initial `agregar_producto` processing produces `pending_resolution` while the session already contains an active `agregar_producto`, the orchestration SHALL preserve the existing active intent and SHALL place the new intent in the pending FIFO queue through the existing pending-intent service.

#### Scenario: Second pending addition is queued
- **WHEN** one pending `agregar_producto` is active and a later classified addition also resolves to `pending_resolution`
- **THEN** the original intent remains active and the later intent is appended to the queue

#### Scenario: Queue order is preserved
- **WHEN** three pending additions are processed in classifier order
- **THEN** the first is active and the second and third appear in queue order

### Requirement: Initial agregar_producto orchestration retains side-effect boundaries
Queue-aware pending preservation SHALL NOT execute handlers, mutate order rows, commit, or roll back.

#### Scenario: Preserving a later addition performs no business action
- **WHEN** an addition is enqueued behind an active pending addition
- **THEN** no `PedidoProducto` mutation, handler call, commit, or rollback occurs in the initial orchestrator
