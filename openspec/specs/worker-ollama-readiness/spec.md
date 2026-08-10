# worker-ollama-readiness Specification

## Purpose
TBD - created by archiving change harden-worker-ollama-readiness. Update Purpose after archive.
## Requirements
### Requirement: Automatic inbound waits for usable Ollama

When the provider worker is enabled, it SHALL not invoke inbound processing until a controlled fixed-input probe proves both configured Ollama generate and embedding surfaces usable. The probe SHALL not touch database, provider or conversation state.

#### Scenario: Generate or embed is unavailable after restart

- **WHEN** either controlled probe fails
- **THEN** the worker does not invoke inbound processing or claim inbound work
- **AND** it records only a safe not-ready category and retries after its poll interval

### Requirement: Outbound continues while inbound is gated

While Ollama is not ready, the worker SHALL invoke the existing bounded outbound pass and SHALL not create, reorder or replay outbound rows.

#### Scenario: Due outbound exists during readiness failure

- **WHEN** the initial readiness probe fails while an outbound row is due
- **THEN** the existing outbound dispatcher runs
- **AND** inbound work remains unclaimed until readiness succeeds

### Requirement: First readiness success restores normal cycles

After both probes pass, readiness SHALL be cached for the worker process and normal bounded inbound-then-outbound cycles resume. It SHALL not probe every message or change later pipeline retry policy.

#### Scenario: Later probe recovers

- **WHEN** a later probe succeeds after not-ready cycles
- **THEN** the next cycle invokes inbound before outbound with configured bounds
- **AND** existing leases, transactions, ordering and retries remain unchanged

### Requirement: Readiness evidence is privacy-safe

Readiness records SHALL contain only state, safe category, bounds, cycle and duration; never probe text, prompt, response/vector, URL/proxy, customer/provider data, credentials, signature, account identifier or environment dump.

#### Scenario: Readiness records omit probe text and secrets

- **WHEN** the worker emits a readiness record or a not-ready cycle summary
- **THEN** it contains only ``ollama_ready``, safe category, configured bounds, cycle index and probe duration
- **AND** it MUST NOT contain the probe prompt, response, vector, configured URL/proxy, customer/provider content, credentials, signature, account identifier or environment dump
