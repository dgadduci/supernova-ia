# Delta for worker-ollama-readiness

## ADDED Requirements

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
