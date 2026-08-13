## ADDED Requirements

### Requirement: Pending-context transitions have a closed privacy-safe event

The system SHALL expose `pending_context_transition` through the existing
versioned operational-event catalogue with component `pending_context`. Every
event SHALL contain only the standard envelope plus closed `outcome`,
`context_kind`, `status_before`, `status_after`,
`candidate_count_before`, `candidate_count_after`, and `context_cleared`
fields. Unknown fields and values outside their fixed allowlists/bounds SHALL
be rejected before emission or parsing.

#### Scenario: Rejected clarification is observable without identifiers

- **WHEN** a pending resolver returns `rejected` and the dispatcher clears its
  context
- **THEN** one event records `outcome == "rejected_cleared"` and
  `context_cleared == true`
- **AND** it contains no text, identifier, label, prompt, model payload,
  exception material, E.164 address, or correlation field

### Requirement: Observability cannot change pending-context behavior

Event construction and emission for a pending-context transition SHALL be best
effort. It SHALL not invoke a database operation or transaction-control method
and an emission/validation failure SHALL leave the processing outcome and
pending-context state unchanged.

#### Scenario: Event failure does not turn selection into rejection

- **WHEN** the event emitter fails while a `Grande` clarification is otherwise
  ready for normal execution
- **THEN** the existing ready execution path receives the same intent it would
  have received without observability

### Requirement: Bounded production queries accept only the closed event

The existing production-log CLI SHALL parse and return valid
`pending_context_transition` events through the shared catalogue and reject a
claimed event carrying an unknown or unsafe field without printing the raw
line.

#### Scenario: Bounded query filters the new event safely

- **WHEN** an authorized operator requests the exact event name with existing
  finite query bounds
- **THEN** the CLI returns only catalogue-valid event payloads
