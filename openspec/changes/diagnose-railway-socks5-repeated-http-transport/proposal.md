# Diagnose repeated HTTP connections through the Railway SOCKS5 boundary

## Objective

Provide an operator-run, non-mutating diagnostic that can be executed inside
the `supernova-ia` Railway `test` container to determine whether intermittent
request loss is associated with repeated HTTP connection establishment at the
local `requests` → `socks5h://127.0.0.1:1055` boundary.

The diagnostic compares the production-shaped behavior—one top-level
`requests.post` call per attempt—with a diagnostic-only reused
`requests.Session`, while separating connection timeout from response-read
timeout. It identifies the last observable client-side result without changing
runtime behavior.

## Current execution path

The affected application boundary is:

`QueryLlm.request()` → `QueryLlm._post()` → `requests.post()` →
`socks5h://127.0.0.1:1055`.

`QueryLlm._post()` currently uses the top-level Requests API and does not own a
persistent `Session` or adapter pool. In the observed third-message failures,
the existing `request_started` evidence is present but no
`response_received` evidence appears before the timeout. The exact internal
Requests phase is therefore not currently distinguishable.

The configured HTTP destination is used only as an opaque transport target by
the operator probe. This change does not inspect, modify, or draw conclusions
about the destination service or the infrastructure behind the SOCKS5 proxy.

## Scope

- Add one standalone module-run diagnostic under `backend/scripts/`.
- Run it inside the Railway `supernova-ia` service, not on the operator's Mac.
- Reuse the service's configured target and proxy settings without printing
  either value.
- Support a `fresh` mode using top-level `requests.post` for every attempt and
  a `session` mode using one diagnostic-only `requests.Session`.
- Use separate, bounded connect and read timeouts.
- Print only safe attempt timing, mode, status, byte count, outcome, and closed
  exception categories.
- Add focused tests and a short Railway runbook entry.

## Non-goals

- No changes to `QueryLlm`, `IntentClassifier`, coordinator, worker, leases,
  database, outbox, Twilio, or business-message behavior.
- No changes to Tailscale, `tailscaled`, SOCKS5 configuration, ACLs, routing,
  MTU, firewall, Railway variables, or Ollama configuration.
- No production HTTP connection pooling, retries, fallback, timeout changes,
  direct endpoint, or alternate proxy.
- No automatic replay, provider message, order mutation, database write, or
  new application endpoint.
- No claim of root cause based on one probe run.

## Shared boundary

The diagnostic exercises the existing configured HTTP target through the
existing proxy boundary. `fresh` must call the top-level `requests.post` once
per attempt, matching the current application call shape. `session` is only a
comparison mode and must use one `requests.Session` for the bounded run.

The diagnostic must consume and close each response so the comparison does not
confound connection reuse with an unread response body. It must not configure
implicit retries.

## Failure and fallback behavior

Each attempt is independent. A failed attempt is classified and the bounded
probe continues to the next attempt without retrying that attempt, changing
the proxy, or falling back to a direct request. The command exits non-zero if
any attempt fails.

The diagnostic distinguishes, where Requests exposes the distinction, between
connect timeout, read timeout, proxy error, connection error, request error,
empty response, and non-success HTTP status. It must not print exception text
or tracebacks.

## Transaction ownership

The diagnostic opens no database session and owns no transaction.

## Observability and privacy

Terminal output may contain only the mode, attempt number, UTC timestamps,
elapsed milliseconds, closed phase/outcome token, bounded HTTP status, bounded
response-byte count, and safe exception class/category. It must not print the
target URL, proxy URL, request body, response body, headers, credentials,
customer/order data, exception text, or traceback.

## Expected files

- `backend/scripts/probe_railway_socks5_repeated.py`
- `backend/tests/test_probe_railway_socks5_repeated.py`
- `backend/development/railway.md` for the Railway SSH command and result
  interpretation.

## Focused tests and validation

- Focused tests for fresh/session call shape, sequential attempts, timeout
  tuple, response closure, failure classification, safe output, and exit code.
- Ruff on the two Python files.
- `compileall` on the two Python files.
- Strict OpenSpec validation.
- `git diff --check`.
- No deployment or Railway variable change as part of implementation.

## Rollback and deferred limitations

Removing the diagnostic script, tests, and runbook section fully rolls back the
change; no runtime path or persisted data is altered. The result only narrows
the failure boundary. It does not prove whether a downstream network peer,
proxy implementation, or external service is the ultimate cause.
