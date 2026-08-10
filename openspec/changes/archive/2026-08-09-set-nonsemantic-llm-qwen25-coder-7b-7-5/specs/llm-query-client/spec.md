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

#### Scenario: Correct payload and configured values are sent

- **WHEN** `QueryLlm.request("hola")` is invoked with mocked transport
- **THEN** the outbound payload contains `model=LLM_MODEL`, `prompt="hola"`,
  `stream=False`, `think=False`, `format="json"`, `temperature=0`, and the
  configured numeric options

#### Scenario: Clean JSON response is parsed

- **WHEN** the mocked transport returns a valid JSON object body
- **THEN** `QueryLlm.request` returns the parsed dictionary

#### Scenario: JSON is extracted from surrounding text

- **WHEN** the mocked transport returns `texto { "intents": [] } más`
- **THEN** `QueryLlm.request` extracts and parses the substring between the
  first `{` and last `}`

#### Scenario: Empty response is rejected

- **WHEN** the mocked transport returns an empty body
- **THEN** `QueryLlm.request` raises a clear exception and does not return
  `None`

#### Scenario: Invalid JSON response is rejected

- **WHEN** the mocked transport returns `not-json`
- **THEN** `QueryLlm.request` raises a clear exception

#### Scenario: Timeout raises a clear exception

- **WHEN** the mocked transport raises a timeout
- **THEN** `QueryLlm.request` raises a timeout-specific exception

#### Scenario: HTTP error raises a clear exception

- **WHEN** the mocked transport raises an HTTP error
- **THEN** `QueryLlm.request` raises an HTTP-error-specific exception

#### Scenario: Empty prompt is rejected

- **WHEN** `QueryLlm.request("")` is invoked
- **THEN** a validation error is raised without contacting the transport
