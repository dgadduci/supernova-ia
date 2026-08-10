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

### Requirement: Production readiness recovery is demonstrable without manual processing

An operator SHALL be able to demonstrate that a freshly started worker with its controlled Ollama readiness result not ready leaves a receipt durable and unprocessed until the worker's generate and embedding readiness checks both succeed. A generate failure establishes not-ready and short-circuits embedding by contract. Recovery SHALL produce exactly one normal inbound processing and at most one corresponding outbound delivery, without manual inbound/outbound CLI invocation. A previously ready worker caches readiness; stopping Ollama after that cache is established is not evidence for this requirement.

#### Scenario: Receipt waits while readiness is false

- **WHEN** the user has temporarily stopped the Ollama dependency configured by Railway
- **AND** a safe control probe confirms generation is unavailable (with embedding skipped by contract)
- **AND** the Railway application is restarted so the worker begins without cached readiness
- **AND** a single approved test receipt arrives
- **THEN** its work item remains pending or otherwise unclaimed by inbound processing
- **AND** it does not reach `failed_terminal` because of the readiness window
- **AND** it creates no new outbound response before readiness recovers

#### Scenario: Recovery processes the same receipt once

- **WHEN** Ollama is restored and both controlled readiness probes succeed
- **THEN** the same receipt reaches one `processed` inbound outcome
- **AND** exactly one corresponding outbound response reaches `delivered`
- **AND** no operator manually runs inbound or outbound processing
