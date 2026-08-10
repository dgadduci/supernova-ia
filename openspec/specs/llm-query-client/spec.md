# Capability: llm-query-client

## Purpose

Provide a synchronous HTTP client for the local LLM endpoint, owned by `backend/llm/query_llm.py`. Builds the request payload from configured settings, posts it via `requests`, parses clean JSON with a `{...}` extraction fallback, and surfaces timeout, connection, HTTP, and response errors as distinct exception types so future intent-classification code can handle them without coupling to upstream details.
## Requirements
### Requirement: Configurable LLM settings
The system SHALL expose configurable values for `LLM_URL`, `LLM_MODEL`, `LLM_TIMEOUT`, `LLM_KEEP_ALIVE`, `LLM_NUM_CTX`, `LLM_NUM_PREDICT`, `LLM_LOG_CONTENT`, and `LLM_LOG_MAX_CHARS`, allowing environment variables to override the local defaults and without depending on SQLAlchemy or Alembic.

#### Scenario: Settings use local defaults when no overrides are set
- **WHEN** the settings module is loaded without any `LLM_*` environment variables
- **THEN** each value matches its documented local default

#### Scenario: Settings honor environment overrides
- **WHEN** the user exports `LLM_MODEL=custom-model` and `LLM_URL=https://example/llm`
- **THEN** the loaded `LLM_MODEL` is `custom-model` and `LLM_URL` is `https://example/llm`

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

### Requirement: Lifecycle and content logging
The system SHALL log only request start, configured model, request duration, success/failure, and HTTP status when available at `INFO`. At `DEBUG`, when `LLM_LOG_CONTENT` is enabled, it SHALL also log the prompt content and raw model response. Logged content SHALL be truncated using `LLM_LOG_MAX_CHARS`; the module SHALL NOT log headers, credentials, or environment secrets, SHALL NOT log full content at `INFO`, SHALL NOT configure global logging handlers, and SHALL use `logging.getLogger(__name__)`.

#### Scenario: INFO logs carry metadata without content
- **WHEN** a successful request completes
- **THEN** the INFO log records request start, configured model, request duration, and success without prompt content

#### Scenario: DEBUG content logs respect LLM_LOG_CONTENT
- **WHEN** a request completes with `LLM_LOG_CONTENT` enabled at DEBUG level
- **THEN** the DEBUG log includes the prompt and response truncated to `LLM_LOG_MAX_CHARS`

#### Scenario: Module does not configure global logging
- **WHEN** the module is imported
- **THEN** it only obtains a logger via `logging.getLogger(__name__)` without configuring handlers

### Requirement: Constraints
The module SHALL NOT implement intent classification, Pydantic validation, database access, or FastAPI/Session integration, and SHALL NOT modify the legacy classifier prompt.

#### Scenario: Module has no classifier dependencies
- **WHEN** the module is imported
- **THEN** no intent-classification, validation, database, or framework code is loaded

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
