# Proposal: diagnose the QueryLlm response transport gap

## Objective

Add privacy-safe phase observability around the existing `QueryLlm` transport
boundary so the team can distinguish a request that never reaches Ollama, a
response that Ollama produces but the client does not receive, a JSON decoding
failure, and a result-parsing failure.

This is a diagnostic change only. It must not alter timeout values, retry
behavior, worker scheduling, business processing or fallback behavior.

## Current execution path

The provider worker invokes the inbound coordinator, which invokes
`IntentClassifier.query()`. The classifier builds the production prompt and
delegates to `QueryLlm.request()`. `QueryLlm` emits `llm_request started`,
calls `requests.post()` through the configured SOCKS5/Tailscale path, decodes
the response and parses the JSON result. The current evidence shows Ollama
logging HTTP 200 while the Railway process remains inside the 180-second
request timeout, so the missing boundary is not yet observable from the
existing events.

## Scope

- Extend the existing privacy-safe LLM observability contract with bounded
  transport-phase events or fields, reusing the existing `query_llm` component.
- Emit markers at the request start, after the HTTP response is returned, after
  JSON extraction and after the final `QueryLlm` result is parsed.
- Include only safe metadata: closed phase, HTTP status when available,
  bounded elapsed milliseconds, bounded received-body length when available,
  and the existing opaque correlation id.
- Add focused tests that verify phase ordering and the timeout boundary.
- Preserve the existing repeated probes so operators can correlate Railway
  phases with Ollama's access log timestamps.

## Non-goals

- No change to `QueryLlm` timeout, HTTP client, proxy URL, Tailscale process,
  Ollama, worker, coordinator, IntentClassifier semantics or retries.
- No fallback, replay, parallel request, connection-pool redesign or response
  buffering strategy.
- No prompt, response body, URL, proxy value, credential, header, customer
  data, provider data, exception text or traceback in events or logs.
- No database, order, receipt, lease, outbox, T-C, Twilio or deployment
  configuration change.

## Shared boundary

The authoritative boundary is the existing `QueryLlm.request()` method and its
`_post()` call. The instrumentation must observe the existing calls without
reimplementing or wrapping the transport in a second pipeline.

## Runtime decision and fallback behavior

The instrumentation is observational only. If an event cannot be emitted, the
existing safe observability degradation behavior remains in force and the
LLM request continues with its current behavior. No new timeout, retry or
fallback is introduced.

## Transaction ownership

This change owns no transaction and must not open or mutate a database
session.

## Observability contract

Use a closed vocabulary for phases, for example `request_started`,
`response_received`, `json_extracted` and `result_parsed`. The contract must
bound numeric fields and reject arbitrary strings. A timeout occurring inside
`requests.post()` must leave a clear record that `request_started` was emitted
without a subsequent `response_received` marker before the existing timeout
event.

## Expected files

- `backend/observability/events.py` if the existing event contract needs the
  closed phase vocabulary and bounded fields.
- `backend/llm/query_llm.py` for the four observation points.
- Focused observability and QueryLlm tests only.

## Focused validation

- Focused QueryLlm and observability pytest tests.
- Ruff on every touched Python file.
- `compileall` on every touched Python file.
- Strict OpenSpec validation.
- `git diff --check`.
- One Railway test run using the existing repeated IntentClassifier probe,
  correlated with the local Ollama access log.

## Rollback and reversibility

Revert the instrumentation commit. Existing request behavior, timeout,
worker processing and provider contracts remain unchanged.

## Deferred limitations

This change identifies the last completed client-side phase; it does not fix a
SOCKS5/Tailscale response-delivery defect. If the evidence confirms a proxy
failure, a separate approved change will be required for that infrastructure
boundary.
