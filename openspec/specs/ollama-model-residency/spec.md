# ollama-model-residency Specification

## Purpose
TBD - created by archiving change pin-ollama-model-residency. Update Purpose after archive.
## Requirements
### Requirement: Configured NovaOrders models remain resident across idle periods

The production deployment SHALL configure Qwen generation with `LLM_KEEP_ALIVE=-1` and configure the shared Ubuntu Ollama daemon with `OLLAMA_KEEP_ALIVE=-1`. The provider worker SHALL be paused while the Ollama daemon is restarted and resumed only after controlled readiness succeeds. The configured Qwen and embedding models SHALL be verified resident through safe Ollama status evidence.

#### Scenario: Reversible configuration warm-up

- **WHEN** the worker is paused for the approved residency configuration
- **AND** Ollama is restarted with its keep-alive override
- **AND** Railway is redeployed with `LLM_KEEP_ALIVE=-1` and the worker re-enabled
- **THEN** controlled readiness warms generation and embeddings successfully
- **AND** the configured models remain resident after the warm-up
- **AND** normal receipt processing resumes without manual CLI execution

#### Scenario: Readiness failure restores the prior configuration

- **WHEN** Ollama restart or controlled readiness fails during the change
- **THEN** the worker remains paused
- **AND** the captured Railway and Ubuntu keep-alive values can be restored
- **AND** no inbound work is manually processed during recovery
