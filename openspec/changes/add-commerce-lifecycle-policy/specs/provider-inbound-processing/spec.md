## ADDED Requirements

### Requirement: Provider inbound acceptance uses the centralized commerce availability policy

Before accepting or routing provider inbound work for a commerce, the system
SHALL evaluate the centralized availability policy. It SHALL reject blocked,
missing, expired-trial, and quota-exhausted commerce without choosing a
different commerce or creating a replacement order.

#### Scenario: Expired trial is rejected before new work is accepted

- **WHEN** inbound provider work resolves to a commerce whose PRUEBA deadline
  has passed
- **THEN** the result is a typed unavailable-commerce outcome
- **AND** no receipt-derived order/session work for that commerce is created

### Requirement: Provider leased processing re-evaluates commerce availability

Before leased provider work stages a session, draft, intent, or outbound row,
the system SHALL evaluate the centralized policy using the commerce id in its
claimed receipt. Acceptance-time availability does not authorize later work.
Unavailable work SHALL be finalized non-retryable with a bounded policy reason;
it SHALL not invoke the pipeline or stage session, draft, order, or outbound
work. Technical evaluation failure retains existing rollback/retry behavior and
shall not process the message.

#### Scenario: Commerce becomes inactive after acceptance

- **GIVEN** provider work was accepted while available
- **AND** the commerce becomes blocked before lease processing
- **WHEN** the worker processes the lease
- **THEN** it is finalized unavailable and non-retryable
- **AND** no session, draft, intent, or outbound message is staged

### Requirement: Every current inbound entry point uses the centralized policy

The authenticated direct/test incoming-message endpoint SHALL evaluate the
same policy before loading a session or invoking the response orchestrator.
Unavailable commerce SHALL receive a bounded unavailable-commerce HTTP error
and SHALL not mutate business state or generate a customer response. Current
and future channel adapters SHALL delegate lifecycle interpretation to
`CommerceAvailabilityService`, never code, description, or label branches.

#### Scenario: Direct/test message to inactive commerce is rejected

- **WHEN** an authenticated direct/test request targets a blocked commerce
- **THEN** it returns the bounded unavailable-commerce error
- **AND** it does not load a session or invoke the response orchestrator
