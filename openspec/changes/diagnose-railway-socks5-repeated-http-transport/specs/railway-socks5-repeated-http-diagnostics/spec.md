# railway-socks5-repeated-http-diagnostics Specification

## ADDED Requirements

### Requirement: Railway-local repeated HTTP transport probe

The system SHALL provide an operator-run module diagnostic that executes
inside the `supernova-ia` Railway service and sends a bounded sequence of
controlled HTTP requests through the configured local SOCKS5 proxy without
creating business state.

#### Scenario: Fresh mode matches the current application call shape

- **WHEN** the operator runs the diagnostic with `--mode fresh --count 10`
- **THEN** it invokes top-level `requests.post` once per attempt
- **AND** every attempt uses the configured proxy mapping
- **AND** no attempt is retried implicitly or sent directly

#### Scenario: Session mode provides a comparison

- **WHEN** the operator runs the diagnostic with `--mode session --count 10`
- **THEN** it uses one diagnostic-only `requests.Session` for the bounded run
- **AND** consumes and closes every response before the next attempt
- **AND** it does not alter the production `QueryLlm` transport

### Requirement: Connection and read timing are separated

The diagnostic SHALL accept independent positive connect and read timeout
values and SHALL classify each attempt using the most specific safe Requests
exception category available.

#### Scenario: Connect timeout occurs

- **WHEN** the request cannot establish the proxy-side connection within the
  configured connect timeout
- **THEN** the attempt reports a closed connect-timeout or proxy-error outcome
- **AND** the next bounded attempt is still executed

#### Scenario: Read timeout occurs

- **WHEN** the HTTP call is established but no response completes within the
  configured read timeout
- **THEN** the attempt reports a closed read-timeout outcome
- **AND** it does not retry or use a direct fallback

#### Scenario: Response completes

- **WHEN** a response is returned
- **THEN** the diagnostic reports bounded HTTP status and received-byte count
- **AND** it closes the response before continuing

### Requirement: Safe bounded terminal output

The diagnostic SHALL print only safe timing and transport metadata and SHALL
return a non-zero exit code if any requested attempt fails.

#### Scenario: Successful bounded run

- **WHEN** every requested attempt returns a successful HTTP response with
  at least one byte
- **THEN** the command exits `0`
- **AND** the terminal output contains no target URL, proxy URL, body, headers,
  credentials, exception text, or traceback

#### Scenario: Mixed bounded run

- **WHEN** one attempt fails and a later attempt succeeds
- **THEN** the later attempt is executed
- **AND** the command exits `1`
- **AND** the failure output contains only a closed category or exception class

#### Scenario: Invalid arguments

- **WHEN** count or either timeout is zero, negative, non-finite, or malformed
- **THEN** the command exits `2`
- **AND** no HTTP request or session is created

### Requirement: Diagnostic isolation

The diagnostic SHALL not modify production behavior or business state and SHALL
not inspect or configure Tailscale or Ollama.

#### Scenario: Operator runs the diagnostic in Railway

- **WHEN** the command runs inside `supernova-ia/test`
- **THEN** it reads existing settings only
- **AND** it performs no database, worker, provider, outbox, Twilio, lease,
  retry, migration, environment, or deployment operation
- **AND** it treats the configured HTTP destination as an opaque transport
  target
