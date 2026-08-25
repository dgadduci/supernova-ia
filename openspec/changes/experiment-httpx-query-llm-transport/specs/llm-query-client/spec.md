## ADDED Requirements

### Requirement: HTTPX experiment SHALL preserve the QueryLlm boundary contract

When the closed configuration selects HTTPX, QueryLlm SHALL make exactly one
synchronous HTTPX request using the existing URL, non-streaming Ollama payload,
total timeout and optional SOCKS5/SOCKS5H proxy. It SHALL consume and close one
response, preserve the established parsing/result/error contract and emit only
the existing privacy-safe transport phases. It SHALL NOT attempt Requests as a
fallback or make a second LLM request.

#### Scenario: HTTPX receives a complete response

- **WHEN** `LLM_HTTP_CLIENT=httpx` and the configured Ollama endpoint returns
  a valid response
- **THEN** QueryLlm returns the same parsed result shape as the Requests path
- **AND THEN** the existing ordered transport-phase observations are emitted
- **AND THEN** the response is closed

#### Scenario: HTTPX fails before a response header

- **WHEN** the HTTPX request times out or cannot connect before headers arrive
- **THEN** QueryLlm raises the corresponding existing closed technical error
- **AND THEN** it emits no fabricated header or body phase
- **AND THEN** it does not invoke Requests or issue another LLM request

#### Scenario: runtime rollback selects Requests

- **WHEN** the operator removes `LLM_HTTP_CLIENT=httpx` from Test configuration
- **THEN** the next process start selects Requests by default
- **AND THEN** no code, schema or data rollback is required
