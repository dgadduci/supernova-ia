# Proposal: repeated diagnostic probe through QueryLlm

## Objective

Add a disposable command-line diagnostic that invokes the existing `QueryLlm`
boundary repeatedly using the service's real settings and transport. The probe
shall default to ten sequential requests, accept a manually configured delay
between requests, and print the exact probe message plus the parsed response
for each attempt so an operator can compare application results with Ollama
server logs.

## Current execution path

Production calls `QueryLlm.request()` from the provider inbound coordinator
inside the worker. The existing
`backend/scripts/check_railway_ollama_contracts.py` performs one controlled
readiness request and deliberately hides its response. This change adds only a
separate operator diagnostic for repeated observation; it does not alter the
worker, coordinator, readiness check, transport, timeout or business state.

## Scope

- Add one standalone script under `backend/scripts/`.
- Reuse `QueryLlm`, `load_settings()` and the existing configured proxy/URL.
- Default to ten sequential calls with zero delay.
- Accept `--count`, `--delay-seconds` and `--prompt` arguments.
- Print the message sent, parsed response, UTC timestamps, elapsed time and a
  bounded success/error classification for every attempt.
- Keep output in the operator terminal only; do not persist probe content.

## Non-goals

- No changes to `QueryLlm`, worker, coordinator, T-C, Twilio, Ollama or
  production configuration.
- No database access, provider message, order mutation, outbox row, retry,
  lease or background task.
- No new HTTP endpoint, queue, migration or observability event catalogue
  entry.
- No automatic retry beyond the explicitly requested sequential attempts.

## Shared boundary

The diagnostic boundary is the existing `QueryLlm.request()` call. The script
must not reimplement its HTTP request, payload construction, proxy handling,
timeout, parsing or error mapping.

## Fallback behavior

Each failed attempt is reported with its exception type and the probe proceeds
to the next attempt after the configured delay. The process exits non-zero if
any attempt fails, and zero only when every requested attempt succeeds. It
must not retry an individual attempt implicitly.

## Transaction ownership

The script opens no database session and owns no transaction.

## Observability

The terminal output may show the explicitly supplied probe message and the
parsed LLM response because this is an operator-invoked diagnostic. The script
must not log credentials, URLs, proxy values, headers, raw exception text or
tracebacks. Each request should use a safe opaque correlation id so existing
`llm_request` events can be aligned with Ollama timestamps.

## Expected files

- `backend/scripts/probe_query_llm_repeated.py`
- Focused tests for argument validation, sequential invocation, delay,
  message/response output, error classification and exit status.

## Focused validation

- Focused pytest for the new script.
- Ruff on the new script and its test file.
- `compileall` on the new Python files.
- Strict OpenSpec validation.
- One operator run inside the Railway `supernova-ia` service, without
  modifying Railway variables or business data.

## Rollback and reversibility

Delete the standalone script and its tests. No runtime path or persisted data
is changed.

## Deferred limitations

The probe isolates the `QueryLlm` boundary but does not reproduce worker
claiming, session leases, coordinator transactions or outbound dispatch. A
successful probe therefore narrows the investigation; it does not prove that
the complete provider pipeline is healthy.
