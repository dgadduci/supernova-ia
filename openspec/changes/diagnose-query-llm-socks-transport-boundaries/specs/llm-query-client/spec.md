## ADDED Requirements

### Requirement: QueryLlm SHALL expose bounded SOCKS transport progress without changing the request

When QueryLlm uses its existing default Requests transport with the configured
SOCKS proxy, it SHALL emit privacy-safe, closed
`llm_request_transport_phase` evidence for SOCKS-connect start/completion and
HTTP-request-writer start/completion. It SHALL make exactly one existing
request with unchanged payload, total timeout, streaming and proxy semantics,
and SHALL NOT cache the observer session, the adapter, the proxy manager or
the socket between two consecutive SOCKS requests.

The observer MUST respect the real stack order: the inherited writer seam is
entered first and the lazy SOCKS connect runs only when the writer's `send`
path reaches `connect()`. Forcing `connect()` ahead of the writer is
forbidden.

#### Scenario: SOCKS request reaches response headers

- **WHEN** the existing SOCKS connection and HTTP request writer return and
  the upstream responds
- **THEN** the event order is `request_started`, writer start, SOCKS
  start/completion, writer completion, then existing
  `response_headers_received`
- **AND THEN** existing body, JSON and parsed-result events retain their
  current behavior
- **AND THEN** every completed new boundary contains only bounded elapsed time
  and the existing opaque correlation value
- **AND THEN** the per-call session is torn down with its response so two
  consecutive requests do not share a session, an adapter, a proxy manager,
  a connection pool or a socket

#### Scenario: SOCKS connection does not return

- **WHEN** the existing SOCKS connection seam is entered but does not return
- **THEN** QueryLlm records `request_started`, `request_write_started` and
  SOCKS-start evidence but no fabricated SOCKS completion, writer
  completion or response-header evidence
- **AND THEN** the existing timeout/error classification remains authoritative
- **AND THEN** it does not retry, fall back to HTTPX or change a lease

#### Scenario: HTTP writer raises before the lazy SOCKS connect runs

- **WHEN** the inherited HTTP writer raises before the lazy `connect()` step
- **THEN** QueryLlm records `request_started` and `request_write_started`
  only — no SOCKS evidence, no fabricated writer completion, no
  response-header evidence
- **AND THEN** the original exception follows the existing QueryLlm mapping
  and no second request is sent

### Requirement: SOCKS progress evidence SHALL remain privacy-safe and observational

The new phase events SHALL expose no URL, host, IP address, port, proxy value,
credential, SOCKS handshake byte, header, prompt, message, response text,
exception text or traceback. Observation failure or missing evidence SHALL not
change networking, business, transaction, lease, retry or recovery behavior.
The per-request session SHALL be closed exactly once when the surrounding
`QueryLlm.request` `finally` block closes the response, and a second `close`
on the response SHALL NOT close the session a second time.

#### Scenario: Non-SOCKS paths do not fabricate SOCKS evidence

- **WHEN** QueryLlm uses no configured proxy, an injected test transport or
  the HTTPX experiment
- **THEN** it emits none of the SOCKS-specific phases
- **AND THEN** its existing request/result/error contract remains unchanged
