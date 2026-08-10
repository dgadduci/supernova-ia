## ADDED Requirements

### Requirement: Audit reports effective non-secret request configuration

The controlled classifier audit SHALL report the effective model identifier,
context length, output limit, temperature, keep-alive, and prompt-template
version used for each audit run. It SHALL omit LLM endpoint URLs, proxy values,
headers, credentials, and environment dumps.

#### Scenario: Qwen compatibility evidence is attributable

- **WHEN** an operator runs the controlled classifier audit after a model
  change
- **THEN** the report identifies the effective model and prompt-template version
- **AND** the report can be compared with prior controlled audit results without
  exposing connection or secret configuration
