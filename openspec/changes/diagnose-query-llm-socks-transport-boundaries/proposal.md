# Proposal: diagnose QueryLlm SOCKS transport boundaries

## Objective

Obtain privacy-safe, decisive evidence for the intermittent QueryLlm failure
where NovaOrders emits `request_started`, never receives HTTP headers and
Ollama records no `POST /api/generate` before the 180-second client timeout.

The change instruments the existing synchronous Requests + SOCKS path at the
client boundaries it can truthfully observe and documents the complementary
proxy/host capture. It does not change the LLM request, its retry policy, its
timeout, client selection or the business pipeline.

## Verified incident evidence

On 2026-08-25 Argentina time, two consecutive requests reached Ollama and
returned HTTP 200 in about 2.5–2.9 seconds. A third request emitted
`llm_request` and `llm_request_transport_phase=request_started` at 17:06:50,
then timed out after about 180 seconds. It produced no response-header/body
phase and Ollama recorded no matching POST or task. Worker liveness and core
staging completed normally up to the QueryLlm boundary.

This proves neither that a packet left NovaOrders nor which lower network hop
stalled. The earlier Railway `strace -p` attempt was blocked by ptrace
permissions, so the diagnostic must not depend on attaching to a live process.

## Current execution path

`QueryLlm.request` emits `request_started` immediately before `_post`. The
default `_post_requests` invokes one `requests.post(..., stream=True)` using
the existing `OLLAMA_PROXY_URL` when configured. Requests delegates SOCKS
connection and negotiation to its existing urllib3/PySocks dependency path.
Only after `_post` returns does QueryLlm emit
`response_headers_received`; it then consumes the body and parses it. The
existing HTTPX selection is a separate, reversible experiment and is not the
subject of this change.

The SOCKS observation must respect the real stack order:
`http.client.HTTPConnection.request` enters the inherited writer seam first;
only then does the lazy `send` path trigger `connect()`, which routes through
`urllib3.contrib.socks.SOCKSConnection._new_conn`. Forcing `connect()` ahead
of the writer would invert that order and pre-allocate a socket the writer
is perfectly capable of opening lazily, so the observer never touches
`self.connect()` ahead of the writer.

## Scope

- Extend the existing closed `llm_request_transport_phase` event with
  client-side SOCKS boundary evidence for the default Requests path.
- Use a QueryLlm-scoped adapter/connection seam; no global monkeypatching of
  `socket`, Requests, urllib3 or PySocks is allowed.
- Build a fresh, single-request `_SocksPhaseObserverSession` for every
  SOCKS path invocation; no process-local session cache, no shared pool,
  no shared adapter, no shared proxy manager and no shared socket between
  two consecutive SOCKS requests. The session lives only as long as the
  single response it serves; the surrounding `QueryLlm.request` `finally`
  block closes the response through a private
  `_SocksResponseSessionCloser` wrapper that closes both the response
  and its private session exactly once.
- Emit only after a boundary has actually returned. Start evidence identifies
  an entered seam; no completion is fabricated when it blocks.
- Respect the real stack order: the inherited writer seam is entered
  before the lazy SOCKS connect, and the SOCKS connect runs only when
  the writer's `send` step reaches the `connect()` call. Forcing
  `connect()` ahead of the writer is forbidden.
- Keep the existing single request, payload, total timeout, `stream=True`,
  proxy scope, exception mapping and response handling unchanged.
- Document a read-only, time-bounded proxy/host capture procedure that pairs
  its results with the opaque correlation/timestamps from Railway.
- Add focused tests for phase order, partial traces, exception behavior,
  privacy, per-request session independence and wrapper close idempotency.

## Non-goals

- No HTTPX activation or change to its experiment, no fallback between HTTP
  clients and no second probe/request.
- No new proxy, Tailscale configuration, URL/proxy configuration changes,
  socket global patching, DNS override, connection pool redesign or dependency
  upgrade.
- No worker/core/coordinator/outbox/Twilio/Ollama behavior change, migration,
  endpoint, dashboard, alert, automatic recovery or persistent diagnostics.
- No claim that application events prove packets were delivered to Ollama.
- No logging of message text, prompt, response, URL, host, IP, port, proxy
  value, credentials, SOCKS handshake bytes, headers, payload lengths outside
  the existing bounded response count, exception text or traceback.

## Authoritative outcomes

New closed phases, only when `OLLAMA_PROXY_URL` selects the existing SOCKS
path, are:

- `socks_connect_started`: the scoped client has begun its existing SOCKS
  connection/negotiation seam;
- `socks_connect_completed`: that seam returned a usable target socket;
- `request_write_started`: the existing HTTP request writer was entered;
- `request_write_completed`: the writer returned after handing request bytes
  to the existing socket layer.

The existing `request_started` remains the application call boundary and
`response_headers_received` remains the first authoritative HTTP response
boundary. Every terminal phase carries bounded non-negative `elapsed_ms`; all
phases preserve the current opaque correlation ID.

The real stack order on a fresh SOCKS connection is:

```text
request_started
request_write_started                inherited HTTP writer entered
socks_connect_started                lazy SOCKS seam entered
socks_connect_completed               SOCKS seam returned a target socket
request_write_completed               writer
response_headers_received             existing HTTP response boundary
```

A connection that already has a cached socket skips the lazy `connect()`
step, so the SOCKS pair is omitted (and never fabricated) and only the
writer pair fires.

Interpretation is intentionally limited:

- `request_started` without `request_write_started`: stop before the inherited
  writer seam;
- `request_write_started` without `socks_connect_started`: the inherited
  writer was entered but the lazy `connect()` step did not run yet (e.g.
  the writer raised before any send); the trace is the last client-side
  observation;
- `socks_connect_started` without completion: stop during local-to-proxy TCP,
  SOCKS negotiation, or proxy-to-target connection; app telemetry cannot split
  those three operations;
- SOCKS completion without completed request write: stop in the client writer;
- completed write without response headers: the client handed bytes to its
  socket layer, but only proxy/host capture can establish onward delivery;
- headers received: the existing body/parser diagnostics remain authoritative.

The proxy/host capture is the authority for proxy-to-Ollama/Tailscale delivery:
matching ingress proves arrival; its absence after a completed client write
narrows the issue to that network leg. It never changes runtime state.

## Fallback and ownership

All observations are best effort. An emission or adapter-observer error must
be swallowed by the existing observability boundary and must not invoke the
request, writer or connection a second time. The `_SocksResponseSessionCloser`
wrapper MUST close its private session exactly once; multiple `close()`
calls are idempotent. The wrapper MUST NOT reopen the session, never
duplicate the response, and must swallow close errors so a misconfigured
observer cannot crash the surrounding business flow. Missing evidence must
not retry, fall back to HTTPX, alter timeout classification, or repair a
lease.

QueryLlm and its caller retain exception and transaction ownership. The
diagnostic performs no database/session operation, transaction control,
network probe or external call.

## Expected files

- `backend/llm/query_llm.py`
- `backend/observability/events.py`
- `backend/tests/test_query_llm.py`
- `backend/tests/test_production_observability.py`
- `backend/development/railway.md`
- This change's OpenSpec files

## Focused validation

The implementer must run and report complete output from the user's local
terminal:

```text
PYTHONPATH=. venv/bin/python -m pytest backend/tests/test_query_llm.py backend/tests/test_production_observability.py -q
PYTHONPATH=. venv/bin/ruff check backend/llm/query_llm.py backend/observability/events.py backend/tests/test_query_llm.py backend/tests/test_production_observability.py
PYTHONPATH=. venv/bin/python -m compileall -q backend/llm/query_llm.py backend/observability/events.py
openspec validate diagnose-query-llm-socks-transport-boundaries --strict
git diff --check
```

No commit, push, PR, sync, archive, Railway configuration action or deploy is
part of this change.

## Rollback / reversibility

Removing the adapter observer, the per-request session construction, the
response wrapper and the closed event tokens restores the current Requests
path exactly. No schema, configuration or durable business state is
introduced.

## Deferred limitations

This change cannot prove physical packet delivery, distinguish proxy TCP from
SOCKS negotiation inside the dependency, or observe proxy-to-Ollama/Tailscale
traffic from NovaOrders. Those facts require the documented external proxy or
host capture. A root-cause fix follows only after those traces agree.
