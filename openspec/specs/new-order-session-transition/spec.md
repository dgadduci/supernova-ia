# new-order-session-transition Specification

## Purpose
TBD - created by archiving change start-new-order-after-confirmation. Update Purpose after archive.
## Requirements
### Requirement: A non-draft associated order creates one clean successor

For authoritative `iniciar_pedido`, when the supplied active conversation session is associated with an order whose state is not `borrador`, the system SHALL close that session and create exactly one replacement active session for the same commerce/client pair. It SHALL create and associate exactly one empty `borrador` pedido to the replacement session.

#### Scenario: Confirmed order starts a separate draft

- **WHEN** the active session's associated pedido is `ingresado`
- **AND** the customer explicitly requests another order
- **THEN** the original session becomes `cerrada` while retaining its original pedido association
- **AND** one new active session for the same commerce/client has one associated `borrador` pedido
- **AND** the new pedido has no lines, payment selection, delivery selection, or copied session context

### Requirement: An active draft is never replaced

For authoritative `iniciar_pedido`, when the supplied active session's associated pedido is `borrador`, the system SHALL leave the session and pedido unchanged and return deterministic guidance to continue that draft.

#### Scenario: Another-order request during draft keeps the draft

- **WHEN** the active session has an associated `borrador` pedido
- **AND** the customer explicitly requests another order
- **THEN** no session or pedido is created, closed, replaced, or reassociated
- **AND** the existing draft remains the sole active order for that commerce/client pair

### Requirement: New-order transition preserves authority and transaction ownership

The transition SHALL use only the supplied session's commerce, client, and associated pedido. It SHALL not select or mutate another session/order and SHALL not commit, roll back, begin, close, refresh, or expire the database transaction. Technical exceptions SHALL propagate to the existing transaction owner.

#### Scenario: Provider failure does not leave a successor behind

- **WHEN** provider processing raises a technical failure after staging a successor session/order and before its final commit
- **THEN** the original active session and associated order remain durable as they were before the message
- **AND** no replacement session, replacement pedido, or outbound response becomes durable
