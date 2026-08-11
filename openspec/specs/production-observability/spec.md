# production-observability Specification

## Purpose
TBD - created by archiving change add-production-observability-cli. Update Purpose after archive.
## Requirements
### Requirement: Privacy-safe operational events are queryable

The system SHALL emit versioned structured operational events for covered
provider worker, outbound dispatch, Twilio callback, LLM/Ollama and database
technical boundaries. Each event SHALL contain only the documented allowlist
of safe metadata and SHALL NOT contain customer message text, E.164 values,
credentials, tokens, signed URLs, provider payloads, prompts, model output,
raw exception text or tracebacks.

#### Scenario: Outbound acceptance can be correlated safely

- **WHEN** the dispatcher receives a provider acceptance for an outbox row
- **THEN** it emits a safe outbound event with the event version, outcome,
  outbox id and applicable safe attempt/provider metadata
- **AND THEN** no outbound body or provider message SID is emitted.

#### Scenario: Callback transition is visible

- **WHEN** a valid Twilio callback produces a monotonic state transition
- **THEN** the system emits a safe callback event with its safe outcome,
  outbox id and state transition
- **AND THEN** it does not log the callback signature, form payload or
  provider message SID.

### Requirement: Operators can query bounded production events from a terminal

The system SHALL provide a terminal CLI that queries the existing Railway log
source through the locally authenticated Railway CLI using explicit target and
bounded filter arguments. The CLI SHALL return only parsed safe structured
events or a safe aggregate and SHALL distinguish no results from technical
errors.

#### Scenario: Filtered query succeeds

- **WHEN** an operator supplies a valid Railway target, event filter, time
  bound and result limit
- **THEN** the CLI queries Railway logs and outputs only matching parsed safe
  events up to the requested bound
- **AND THEN** it does not access PostgreSQL, Twilio, LLM/Ollama or customer
  content.

#### Scenario: Railway returns unparseable output

- **WHEN** the Railway CLI returns output that is not a recognized safe event
- **THEN** the CLI exits with a safe parsing failure
- **AND THEN** it does not print the raw provider line as a fallback.

### Requirement: Log retention and durable-message retention are separate

The system SHALL document Railway/platform log retention as an external,
finite policy and SHALL NOT delete individual Railway log entries. It SHALL
provide a read-only age/state inventory for durable provider-message records
without revealing content or mutating records.

#### Scenario: Operator inventories old durable records

- **WHEN** an operator supplies a valid age threshold to the inventory CLI
- **THEN** it reports counts grouped by safe state and age eligibility
- **AND THEN** it does not reveal message text/addresses or delete records.

#### Scenario: Requested log window predates retained platform logs

- **WHEN** an operator requests a window outside the documented Railway
  retention period
- **THEN** the CLI reports that the platform may no longer retain the data
- **AND THEN** it does not attempt application-side log deletion or recovery.

