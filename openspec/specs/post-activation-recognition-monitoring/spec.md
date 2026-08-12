# post-activation-recognition-monitoring Specification

## Purpose
Define a repeatable, privacy-safe and read-only monitoring procedure for
existing product-recognition observations after hybrid-authoritative activation.
The procedure preserves bounded queries and closed aggregates while preventing
empty windows or business outcomes from causing operational mutation.
## Requirements
### Requirement: Monitoring uses only bounded validated recognition events

The operator SHALL query post-activation recognition observations only through
the existing bounded production-log CLI with an explicit Railway target, time
boundary, `shadow_product_recognition` event filter and finite limit. Each
production query SHALL require separate explicit authorization.

#### Scenario: A valid bounded window has no recognition observations

- **WHEN** the CLI returns a valid response with zero events
- **THEN** the operator SHALL record the result as inconclusive
- **AND** SHALL NOT infer recognition quality, business traffic or failure
- **AND** SHALL NOT send synthetic traffic or change recognition mode.

### Requirement: Monitoring retains only closed aggregates

For a valid non-empty window, the operator SHALL retain only the query bounds,
validated event count and aggregates over the closed recognition categories and
bounded latency fields. The procedure SHALL NOT retain or expose individual
event payloads, raw Railway lines or customer/commerce/decision-input data.

#### Scenario: A returned event carries a technical fallback

- **WHEN** a validated observation has `fallback=true`
- **THEN** the operator MAY record only its allowlisted fallback category and
  aggregate count
- **AND** SHALL stop the window and request separate authorization before any
  investigation, rollback or configuration change.

### Requirement: Business outcomes do not cause operational mutation

`unique`, `ambiguous` and `unknown` observations SHALL be treated as valid
business outcomes. They SHALL NOT by themselves trigger a mode change,
rollback, retry or synthetic recognition request.

#### Scenario: A window contains ambiguous or unknown decisions

- **WHEN** validated events contain `ambiguous` or `unknown`
- **THEN** the operator SHALL record only their aggregate counts
- **AND** SHALL maintain the current recognition mode unless a separately
  authorized decision establishes another action.
