# railway-ollama-generate-transport-diagnostics Specification

## Purpose
TBD - created by archiving change diagnose-railway-ollama-generate-transport-gap. Update Purpose after archive.

## Requirements
### Requirement: sanitized generate transport diagnostic

The system SHALL provide an operator-run diagnostic that sends one fixed,
non-business `/api/generate` request through the existing configured Ollama
proxy and reports only a closed result category, HTTP status when available,
elapsed time, and received-byte count.

#### Scenario: proxied generate response returns bytes

- **WHEN** the configured proxy delivers a non-empty HTTP response from
  `/api/generate`
- **THEN** the diagnostic reports `response_bytes_received`
- **AND** includes the HTTP status, elapsed time, and bounded byte count
- **AND** returns success

#### Scenario: Ollama request never returns a response

- **WHEN** the proxied request times out or cannot connect
- **THEN** the diagnostic reports the corresponding closed failure category
- **AND** does not retry or use a direct/public fallback
- **AND** returns failure

#### Scenario: Ollama logs success but Railway receives no bytes

- **WHEN** Ollama records a successful `/api/generate` request
- **AND** the Railway diagnostic receives no response bytes before the bound
- **THEN** the diagnostic reports `empty_response` or `timeout`
- **AND** the operator can retain that result for return-path investigation

### Requirement: diagnostic isolation and privacy

The diagnostic SHALL reuse the existing settings and proxy boundary without
altering runtime QueryLlm, worker, classifier, timeout, retry, fallback,
Twilio, or business-message behavior.

#### Scenario: diagnostic is executed

- **WHEN** an operator runs the generate transport diagnostic
- **THEN** it performs no database write, lease claim, outbox operation, or
  provider-message call
- **AND** it does not change environment variables or deployment settings

#### Scenario: diagnostic output is captured

- **WHEN** the diagnostic prints its result
- **THEN** it excludes the prompt, generated response, URL, proxy value,
  credentials, headers, customer/order data, exception text, tracebacks, and
  raw Tailscale status

### Requirement: existing embedding diagnostic remains compatible

The existing embedding transport diagnostic SHALL retain its command behavior,
result semantics, and privacy contract while the generate target is added.

#### Scenario: existing embed diagnostic is run

- **WHEN** the operator invokes the existing embedding transport diagnostic
- **THEN** it continues to classify returned bytes, empty responses, HTTP
  failures, timeouts, and connection failures as before
- **AND** it does not invoke the generate target