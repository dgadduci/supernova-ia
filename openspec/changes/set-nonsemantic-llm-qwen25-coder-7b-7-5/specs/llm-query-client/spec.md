## MODIFIED Requirements

### Requirement: Synchronous QueryLlm HTTP client

The system SHALL provide a synchronous `QueryLlm.request(prompt: str) -> dict`
method that builds the payload with `stream=False`, `think=False`,
`format="json"`, `temperature=0`, uses the configured URL/model/options,
parses clean JSON responses, falls back to extracting the substring between the
first `{` and last `}` only when the raw body is non-empty, rejects empty or
invalid JSON, distinguishes timeout, connection, and HTTP errors with clear
exceptions, does not call `print`, never returns `None`, and keeps no mutable
request state between calls. With no environment override it SHALL emit
`model=qwen2.5-coder:7b-ctx8192` and `options.num_ctx=8192`.

#### Scenario: Default controlled model is sent

- **WHEN** `QueryLlm.request("hola")` is invoked with mocked transport and no
  model/context overrides
- **THEN** the outbound payload contains `model=qwen2.5-coder:7b-ctx8192` and
  `options.num_ctx=8192` while preserving the existing JSON and temperature
  fields
