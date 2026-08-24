# Capability: query-llm-repeated-diagnostic-probe

## Purpose

Provide an operator-invoked, non-mutating diagnostic for repeatedly observing
the existing `QueryLlm` boundary with the same service configuration used by
the provider worker.

## Requirements

### Requirement: Standalone repeated QueryLlm probe

The system SHALL provide `backend/scripts/probe_query_llm_repeated.py` as a
module-runnable command that loads the existing settings and invokes the
existing `QueryLlm.request()` boundary sequentially. It SHALL default to ten
attempts and zero seconds between attempts, and SHALL accept a positive
`--count`, a non-negative finite `--delay-seconds`, and a non-empty `--prompt`.

#### Scenario: Default probe performs ten calls

- **WHEN** the operator runs the module without arguments
- **THEN** the script invokes `QueryLlm.request()` exactly ten times
- **AND THEN** all calls use the same loaded service settings and occur in
  sequence

#### Scenario: Manual delay is applied between calls

- **WHEN** the operator runs the probe with `--delay-seconds 2`
- **THEN** the script waits two seconds only between consecutive attempts
- **AND THEN** it does not add a delay before the first or after the last call

#### Scenario: Custom count and prompt are honored

- **WHEN** the operator supplies `--count 3 --prompt "diagnostic message"`
- **THEN** the script invokes the existing boundary three times with that
  exact message

### Requirement: Message and response are visible to the operator

For every attempt, the script SHALL print the exact message sent and, on
success, the parsed response returned by `QueryLlm.request()`, together with
the attempt number, UTC timestamps, elapsed time and bounded outcome. The
output SHALL remain terminal-only and SHALL NOT be written to a file or
application log by the script.

#### Scenario: Successful response is displayed

- **WHEN** `QueryLlm.request()` returns a parsed response
- **THEN** terminal output contains `Mensaje enviado`, the exact prompt,
  `Respuesta recibida`, the parsed response, and the elapsed time

#### Scenario: Failure displays bounded diagnostics

- **WHEN** one call raises a known `QueryLlmError`
- **THEN** terminal output contains the message, `outcome=error` and the safe
  exception class name
- **AND THEN** it does not print exception text, traceback, credentials, URL,
  proxy configuration or headers

### Requirement: Failures do not stop the bounded probe

The script SHALL classify each attempt independently, continue with later
attempts after an individual `QueryLlmError` or unexpected `Exception`, and
return exit code `1` if any attempt failed. It SHALL return exit code `0` only
when all attempts succeed and SHALL NOT add an implicit retry for a failed
attempt.

#### Scenario: Mixed outcomes continue and fail the command

- **WHEN** the second of three sequential calls raises a timeout
- **THEN** the third call is still attempted
- **AND THEN** the process returns exit code `1`

#### Scenario: All attempts succeed

- **WHEN** every requested call returns successfully
- **THEN** the process returns exit code `0`

### Requirement: Probe has no business side effects

The diagnostic SHALL not import or invoke the worker, coordinator, database,
repositories, T-C, Twilio, outbox or any business mutation. It SHALL reuse the
existing `QueryLlm` transport, timeout, proxy, payload construction and
response parsing rather than duplicating them.

#### Scenario: Probe does not create business state

- **WHEN** the operator runs any number of probe attempts
- **THEN** no database session, provider receipt, order change, lease, outbox
  row, provider call or retry is created by the script

#### Scenario: Existing QueryLlm configuration is preserved

- **WHEN** the script runs in the Railway `supernova-ia` service
- **THEN** the calls use the service's configured LLM URL, model, timeout and
  proxy without changing any environment variable or runtime setting

### Requirement: Probe correlation is safe

Each attempt SHALL use a bounded opaque correlation id compatible with the
existing `QueryLlm` observability contract. The id SHALL contain no prompt,
response, customer, phone, credential, URL or secret.

#### Scenario: Attempts can be aligned with transport logs

- **WHEN** the operator compares the probe output timing with application and
  Ollama logs
- **THEN** each attempt has a distinct safe correlation id and UTC timestamp
- **AND THEN** no sensitive probe content is added to structured observability
  events