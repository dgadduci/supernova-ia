# provider-flow-live-audit Specification

## ADDED Requirements

### Requirement: read-only live provider-flow audit

The system SHALL provide an operator-run bounded CLI that polls durable
provider receipt, processing, LLM timing and outbound rows without mutating
application state.

#### Scenario: audit starts before a Twilio message

- **WHEN** the operator starts the CLI in the integrated Railway service shell
- **THEN** it opens only read sessions at each polling interval
- **AND** it reports no pre-existing rows outside the configured start window
- **AND** it performs no claim, commit, update, delete, retry, replay or send

#### Scenario: a new provider turn is received

- **WHEN** a receipt and its processing row become visible after the audit
  starts
- **THEN** the CLI emits a safe snapshot containing numeric ids, closed states,
  bounded attempt/count fields, opaque fingerprint and timestamps
- **AND** it does not print message text, phone numbers or raw provider ids

### Requirement: lifecycle boundary evidence

The audit SHALL expose enough durable evidence to locate the last persisted
boundary between receipt, worker processing, LLM timing, finalization and
outbound staging.

#### Scenario: processing has not reached the LLM boundary

- **WHEN** processing remains pending and both LLM timing fields are null
- **THEN** the snapshot reports the pending state and null LLM timing
- **AND** labels the result as an observation without claiming a root cause

#### Scenario: the LLM attempt is durable but finalization is unresolved

- **WHEN** `llm_solicitado_en` is present and `llm_finalizado_en` is absent
  or processing remains non-terminal
- **THEN** the snapshot exposes those safe timing/state fields
- **AND** does not retry, repair or change the work item

#### Scenario: processed work has no outbound row

- **WHEN** processing is `processed` and the joined outbound row count is zero
- **THEN** the CLI reports the zero count as a terminal observation
- **AND** does not create a fallback outbound row

#### Scenario: outbound staging is visible

- **WHEN** one or more outbound rows are joined to the receipt
- **THEN** the CLI reports the bounded count and safe outbound state/id fields
- **AND** leaves dispatch ownership to the existing dispatcher

### Requirement: bounded operation and privacy

The audit SHALL support an explicit polling interval and duration, stop cleanly
on Ctrl-C, and exclude bodies, destinations, provider SIDs, credentials,
signatures, URLs, prompts, responses, exception text and tracebacks from output.

#### Scenario: audit duration ends or operator interrupts

- **WHEN** the configured duration expires or the operator sends Ctrl-C
- **THEN** the CLI emits a safe termination marker and exits without mutating
  durable state

#### Scenario: a database read fails

- **WHEN** a polling read fails
- **THEN** the CLI reports only a closed safe error category/class
- **AND** it does not print connection details or exception text
