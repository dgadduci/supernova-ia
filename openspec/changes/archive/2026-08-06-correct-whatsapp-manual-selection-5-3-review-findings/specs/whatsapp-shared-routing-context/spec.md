# Capability: whatsapp-shared-routing-context

## MODIFIED Requirements

### Requirement: Manual options are channel-scoped active memberships

The system SHALL expose manual-selection options only for active memberships
of the supplied active **shared** channel whose commerces are active. An
active non-shared channel SHALL return `invalid_channel_mode`, expose no
options and make no context mutation. Every option SHALL be selected by its
membership identifier; arbitrary commerce ids SHALL NOT be accepted as a
selection authority.

#### Scenario: Dedicated channel is not a manual-selection surface

- **WHEN** a caller lists manual options for an active dedicated channel
- **THEN** the operation returns `invalid_channel_mode` with no options
- **AND** it does not create or modify channel-scoped customer context

#### Scenario: Foreign membership is never selectable

- **WHEN** a caller supplies a membership belonging to another channel
- **THEN** selection returns `unknown_or_inactive_membership`
- **AND** no context state changes

#### Scenario: Inactive membership or commerce is omitted and rejected

- **WHEN** a membership or its commerce is inactive
- **THEN** it is absent from manual options
- **AND** an attempt to select it returns a typed non-success outcome without
  mutating context

### Requirement: Selection never silently switches commerce

An existing selected commerce SHALL remain authoritative until the client
explicitly confirms a validated pending switch target. A request for a
different active membership SHALL persist only that target and return
`switch_requested`; it SHALL NOT change the selected commerce or pending
original text. A request resolving to the already selected commerce SHALL be
a non-mutating no-op and SHALL preserve any pending target; it SHALL NOT act
as a cancellation. Confirmation SHALL revalidate the target against the same
active shared channel and active commerce before replacing the selection.
Cancellation SHALL clear only the pending target. No invalid, unavailable,
missing or stale target may silently select a different commerce.

#### Scenario: Current-commerce request preserves an existing pending target

- **WHEN** a selected client with a pending target requests the membership of
  the currently selected commerce
- **THEN** the selected commerce, pending target and pending original text are
  unchanged
- **AND** the pending target can be removed only by explicit cancellation or
  consumed by explicit confirmation

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