# Proposal: diagnose incremental QueryLlm body receipt

## Objective

Determine whether the integrated worker receives HTTP headers and each portion
of the non-streaming Ollama response before its current timeout. The client
will use Requests response streaming only as an observation seam; the Ollama
payload remains `stream: false` and the parsed business contract is unchanged.

## Current path

`QueryLlm.request()` emits `request_started`, then `_post()` calls
`requests.post(..., stream=False)` implicitly. Requests therefore consumes the
full response body before `_post()` returns, so current evidence cannot
distinguish no headers, a partial body, or a complete body followed by parsing.
The worker's durable audit has shown `llm_resultado=timeout` and no outbox.

## Scope

- Use `requests.post(..., stream=True)` at the existing `_post` seam.
- Preserve the Ollama JSON payload `stream: false`, target, proxy, timeout,
  request count, retry behaviour and result shape.
- Read the returned body through the existing call once, emitting closed,
  privacy-safe phases: `response_headers_received`, `first_body_chunk`,
  `body_completed`, then the existing JSON/result phases.
- Record only status, elapsed milliseconds, bounded cumulative byte count,
  bounded chunk count and opaque correlation id.
- Consume and close the response deterministically on every path.

## Non-goals

- No Ollama streaming protocol, async client, Session/pooling, timeout change,
  proxy/Tailscale change, retry, fallback, worker/lease/outbox change, schema,
  migration, raw log capture or production activation.
- No prompt, body/chunk content, URL, proxy, header values, credential,
  provider/customer data, exception message or traceback in events.

## Outcomes

| Last event | Evidence |
| --- | --- |
| `request_started` only | headers were not returned before timeout/error |
| `response_headers_received` only | headers reached client; no body chunk completed |
| `first_body_chunk` without `body_completed` | partial body / stalled completion |
| `body_completed` without JSON phase | response extraction boundary |
| existing JSON/result phases | transport body completed; investigate later boundary |

Missing evidence is observational only and must not cause recovery, retry or
transaction action.

## Transaction, privacy and fallback

The instrumentation remains inside `QueryLlm` and owns no database session or
transaction. Event failure is fail-soft. Existing technical exceptions and
business fallback remain authoritative. The response is always closed; no
second request is made.

## Expected files

- `backend/llm/query_llm.py`
- `backend/observability/events.py`
- `backend/tests/test_query_llm.py`
- `backend/tests/test_production_observability.py`
- `backend/development/railway.md`
- this OpenSpec

## Focused validation

- `PYTHONPATH=. venv/bin/python -m pytest backend/tests/test_query_llm.py backend/tests/test_production_observability.py -q`
- `PYTHONPATH=. venv/bin/ruff check backend/llm/query_llm.py backend/observability/events.py backend/tests/test_query_llm.py backend/tests/test_production_observability.py`
- `PYTHONPATH=. venv/bin/python -m compileall -q backend/llm/query_llm.py backend/observability/events.py`
- `openspec validate diagnose-query-llm-incremental-body-receipt --strict`
- `git diff --check`

The user runs `venv/bin/python` commands locally and provides complete output.
No commit, sync, archive, production deploy or configuration change is in scope.

## Rollback and limit

Reverting the small client/event change restores Requests' prior eager body
read. This diagnosis can locate the last client-visible HTTP boundary; it does
not itself repair a network or server defect.

