# Capability: whatsapp-shared-routing-context

## MODIFIED Requirements

### Requirement: Selection never silently switches commerce

An existing selected commerce SHALL remain authoritative until the client
explicitly confirms a validated pending switch target. A request for a
different active membership SHALL persist only that target and return
`switch_requested`; it SHALL NOT change the selected commerce or pending
original text. Confirmation SHALL revalidate the target against the same
active shared channel and active commerce before replacing the selection.
Cancellation SHALL clear only the pending target. No invalid, unavailable,
missing or stale target may silently select a different commerce.

#### Scenario: Different membership requires explicit confirmation

- **WHEN** a selected client requests a switch to another active membership of
  the same shared channel
- **THEN** the selected commerce and pending original text remain unchanged
- **AND** only the requested commerce is stored as the pending switch target

#### Scenario: Confirmation completes exactly the requested switch

- **WHEN** a client confirms a still-active pending target whose commerce is
  active and belongs to the same shared channel
- **THEN** that target becomes the selected commerce
- **AND** the pending target is cleared
- **AND** the pending original text is unchanged

#### Scenario: Cancellation preserves current selection

- **WHEN** a client cancels a pending switch
- **THEN** the pending target is cleared
- **AND** the selected commerce and pending original text are unchanged

#### Scenario: Stale target fails closed

- **WHEN** the pending target is inactive, revoked, foreign to the channel, or
  its commerce is unavailable at confirmation time
- **THEN** confirmation returns a typed non-success outcome
- **AND** it does not change selected commerce, pending target or pending text

## ADDED Requirements

### Requirement: Manual options are channel-scoped active memberships

The system SHALL expose manual-selection options only for active memberships
of the supplied active shared channel whose commerces are active. Every option
SHALL be selected by its membership identifier; arbitrary commerce ids SHALL
NOT be accepted as a selection authority.

#### Scenario: Foreign membership is never selectable

- **WHEN** a caller supplies a membership belonging to another channel
- **THEN** selection returns `unknown_or_inactive_membership`
- **AND** no context state changes

#### Scenario: Inactive membership or commerce is omitted and rejected

- **WHEN** a membership or its commerce is inactive
- **THEN** it is absent from manual options
- **AND** an attempt to select it returns a typed non-success outcome without
  mutating context

### Requirement: Manual initial selection preserves the original message

For a valid active client with no selected commerce, manual selection of a
validated active membership SHALL set the selected commerce, clear any stale
pending switch target and preserve `mensaje_original_pendiente` byte-for-byte.
It SHALL NOT invoke the local message pipeline.

#### Scenario: Manual first selection is pre-pipeline

- **WHEN** a client with an unselected context chooses a valid membership
- **THEN** only the context state is staged
- **AND** no session, order, classifier, recognizer, handler or catalog call
  occurs

### Requirement: Phase-5.3 preserves caller transaction ownership

Manual selection and switch operations SHALL not invoke `commit`, `rollback`,
`begin`, `flush`, or `close`. They SHALL leave provider receipt deduplication,
transaction completion and inbound-message processing to Phase 5.4.

#### Scenario: Context updates remain caller-owned

- **WHEN** manual selection, switch request, confirmation or cancellation
  stages context state
- **THEN** no Phase-5.3 repository or service controls the transaction
