## ADDED Requirements

### Requirement: QueryLlm HTTP client selection SHALL be closed and reversible

The system SHALL expose `LLM_HTTP_CLIENT` as a closed QueryLlm transport
selection with allowed values `requests` and `httpx`. When unset, it SHALL
resolve to `requests`. Any unsupported value SHALL fail settings loading
before a network request. The selection SHALL apply only to real QueryLlm
calls and SHALL NOT alter embedding, Twilio, database, worker or process-wide
HTTP behavior.

#### Scenario: absent selection preserves the existing Requests transport

- **WHEN** `LLM_HTTP_CLIENT` is absent
- **THEN** Settings resolves the QueryLlm client to `requests`
- **AND THEN** existing real QueryLlm requests retain the Requests transport

#### Scenario: Test selects HTTPX explicitly

- **WHEN** `LLM_HTTP_CLIENT=httpx` is configured
- **THEN** Settings resolves the QueryLlm client to `httpx`
- **AND THEN** only the real QueryLlm boundary selects HTTPX

#### Scenario: selection is invalid

- **WHEN** `LLM_HTTP_CLIENT` is neither `requests` nor `httpx`
- **THEN** settings loading fails with a secret-free configuration error
- **AND THEN** no HTTP request is attempted
