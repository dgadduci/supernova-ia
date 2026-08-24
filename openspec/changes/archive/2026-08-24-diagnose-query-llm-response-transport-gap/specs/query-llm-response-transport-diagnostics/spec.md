# Capability: query-llm-response-transport-diagnostics

## Purpose

Expose privacy-safe, bounded phase evidence for the existing `QueryLlm`
request/response boundary without changing its transport or business behavior.

## ADDED Requirements

### Requirement: QueryLlm transport phases are observable

The system SHALL emit bounded, privacy-safe phase evidence for the existing
`QueryLlm.request()` path at request start, HTTP response return, JSON data
extraction and final result parsing. The phases SHALL use a closed vocabulary
and SHALL preserve the existing `llm_request` success and failure events.

#### Scenario: Successful request emits ordered phases

- **WHEN** the existing `QueryLlm.request()` call receives a valid HTTP
  response and parses a valid result
- **THEN** the phase evidence is emitted in the order
  `request_started`, `response_received`, `json_extracted`, `result_parsed`
- **AND THEN** the existing `llm_request` completed event remains emitted

#### Scenario: Timeout before response receipt is visible

- **WHEN** the existing `_post()` call raises `QueryLlmTimeoutError`
- **THEN** phase evidence includes `request_started`
- **AND THEN** it does not emit `response_received`, `json_extracted` or
  `result_parsed`
- **AND THEN** the existing timeout event and exception behavior remain
  unchanged

### Requirement: Phase metadata is bounded and private

Phase evidence SHALL contain only a closed phase token, bounded non-negative
elapsed milliseconds, an optional bounded HTTP status, an optional bounded
response byte count and the existing safe opaque correlation id. It SHALL
reject or omit prompts, response bodies, URLs, proxy values, headers,
credentials, provider/customer identifiers, raw exception text and
tracebacks.

#### Scenario: Response metadata is safe

- **WHEN** a phase event is emitted after a successful HTTP response
- **THEN** it may contain the status and bounded byte count
- **AND THEN** it contains no response body, prompt, URL or secret

#### Scenario: Invalid phase metadata is rejected

- **WHEN** a caller supplies an unknown phase, an unbounded number or an
  unsafe correlation value
- **THEN** the observability contract rejects the event or degrades through
  its existing safe emission path
- **AND THEN** the QueryLlm request itself is not changed into a business
  failure because of the diagnostic emission

### Requirement: Existing QueryLlm behavior is preserved

The diagnostic SHALL reuse the current HTTP call, proxy configuration,
timeout, response reading, JSON extraction, result parsing and exception
mapping. It SHALL not add a second request, retry, fallback, stream mode,
worker action or database operation.

#### Scenario: Successful result is unchanged

- **WHEN** the existing transport returns a valid result
- **THEN** `QueryLlm.request()` returns the same parsed result as before
- **AND THEN** only the bounded diagnostic evidence is additional

#### Scenario: Transport timeout remains a QueryLlm timeout

- **WHEN** the configured HTTP transport times out before returning a
  response
- **THEN** `QueryLlm.request()` raises the existing `QueryLlmTimeoutError`
- **AND THEN** no retry, fallback or business mutation is performed

### Requirement: Diagnostic phases support operational correlation

Each phase SHALL preserve the existing opaque correlation id when one is
available, and the repeated QueryLlm/IntentClassifier probes SHALL be able to
correlate their UTC timestamps with the Ollama access log without exposing
probe content in structured events.

#### Scenario: Ollama 200 without client response is distinguishable

- **WHEN** Ollama logs an HTTP 200 but the Railway client later times out
- **THEN** the service logs `request_started` without a subsequent
  `response_received` phase for that correlation
- **AND THEN** operators can distinguish response delivery failure from JSON
  parsing or classifier validation
