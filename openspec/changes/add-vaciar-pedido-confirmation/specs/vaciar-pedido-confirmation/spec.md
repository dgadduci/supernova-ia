# Vaciar pedido with explicit confirmation

## ADDED Requirements

### Requirement: Clearing a draft requires explicit confirmation

When the authoritative initial classifier emits `vaciar_pedido` and the session has no pending context, the system SHALL inspect only the session-associated pedido. If it is owned by that session, is in `borrador`, and has one or more lines, it SHALL return a `pending_resolution` intent and persist an `order_clear_confirmation` context without deleting any row. The prompt SHALL ask for an explicit affirmative or negative response.

#### Scenario: Initial clear request does not mutate

- **WHEN** a session-owned borrador contains two lines and the classifier emits `vaciar_pedido`
- **THEN** both lines remain persisted
- **AND** the active pending intent is `vaciar_pedido` with a pending confirmation requirement
- **AND** `session.context_type` is `order_clear_confirmation`

### Requirement: Confirmation context has priority and is deterministic

While `order_clear_confirmation` is active, the next message SHALL be evaluated only by the deterministic confirmation resolver before any initial intent classification. A recognized affirmative SHALL authorize execution; a recognized negative SHALL cancel; any other text SHALL remain pending and re-prompt. No unresolved confirmation reply SHALL trigger a fallback initial intent, LLM call, or catalog/order recognizer.

#### Scenario: Unclear reply preserves the same confirmation

- **WHEN** the customer replies with text outside the approved affirmative/negative vocabulary
- **THEN** no order line changes
- **AND** the same `order_clear_confirmation` remains active
- **AND** the result is `pending_resolution`

#### Scenario: Confirmation text cannot add a product

- **WHEN** the customer replies `sí, agregá una pizza` while clear confirmation is active
- **THEN** the message is handled only as that confirmation reply
- **AND** no `agregar_producto` intent is dispatched in the same turn

### Requirement: Accepted confirmation clears only the validated active draft

After an affirmative confirmation, the handler SHALL revalidate that `session.id_pedido` points to a `Pedido` owned by that session, remains `borrador`, and still has lines. It SHALL delete every and only `PedidoProducto` row for that pedido in the outer transaction, then clear the pending context. It SHALL not delete any row belonging to another order, session, customer, or commerce.

#### Scenario: Affirmative clears all current lines

- **WHEN** the active session-owned borrador has three lines and the customer explicitly confirms
- **THEN** the result is `executed`
- **AND** that pedido has zero lines
- **AND** every other pedido retains its original lines
- **AND** the confirmation context is cleared

### Requirement: Cancellation and invalid draft states never mutate

A negative confirmation SHALL clear the confirmation context and return a rejected cancellation outcome without deleting rows. Missing, session-foreign, non-borrador, empty, or stale draft state at either initiation or execution SHALL return a rejected business outcome and delete no rows.

#### Scenario: Negative cancels

- **WHEN** the customer explicitly rejects a pending clear confirmation
- **THEN** every line remains unchanged
- **AND** pending context is cleared

#### Scenario: Draft becomes invalid before acceptance

- **WHEN** the pedido becomes non-borrador or empty after the prompt and before affirmative confirmation
- **THEN** the result is `rejected`
- **AND** no row outside any prior state change is deleted
- **AND** pending context is cleared

### Requirement: Existing transaction and shared response boundaries are preserved

The new orchestrator, resolver, handler, service, repository helper, and response builder SHALL not own transaction control. Database errors SHALL follow the existing outer transaction rollback policy. Customer responses for prompt, success, cancellation, business rejection, and failure SHALL be rendered by the existing shared mapper and therefore be identical and ordered equivalently for local and provider-outbox processing.

#### Scenario: Delete failure is atomic

- **WHEN** an error occurs while staging the clear operation
- **THEN** the existing transactional owner rolls back the turn
- **AND** no partially cleared pedido is committed
