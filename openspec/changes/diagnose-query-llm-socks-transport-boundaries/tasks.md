# Tasks: diagnose QueryLlm SOCKS transport boundaries

## 1. Feasibility and event contract

- [x] 1.1 Verify a supported pinned Requests/urllib3/PySocks scoped extension
  point; stop rather than globally patch or reimplement SOCKS if unavailable.
- [x] 1.2 Register the four closed transport phases and preserve existing
  privacy/bounds validation.
- [x] 1.3 Add focused event parser and privacy tests.

## 2. Scoped observation

- [x] 2.1 Add one QueryLlm-scoped Requests observer for SOCKS connect and
  request-writer boundaries without changing the request contract.
- [x] 2.2 Preserve one-call behavior, timeout/error mapping, HTTPX selection,
  response streaming and parsing.
- [x] 2.3 Add partial-trace, no-proxy, injected-transport, writer failure and
  fail-soft observer tests.

## 3. Per-request session lifecycle and real stack order

- [x] 3.1 Remove the persistent `_SOCKS_OBSERVER_SESSION`, its lock,
  getter/reset and any process-local cache of `requests.Session`,
  adapter, manager or socket.
- [x] 3.2 Construct a fresh `_SocksPhaseObserverSession` per SOCKS call so
  two consecutive requests never share a session, an adapter, a proxy
  manager, a connection pool or a socket.
- [x] 3.3 Wrap the SOCKS response with `_SocksResponseSessionCloser` so
  the surrounding `QueryLlm.request` `finally` block closes both the
  response and its private session exactly once; the wrapper is
  idempotent and fail-soft.
- [x] 3.4 Remove the explicit `self.connect()` call from the writer seam
  so the lazy stack ordering is preserved
  (`request_started → request_write_started → socks_connect_started →
  socks_connect_completed → request_write_completed`).
- [x] 3.5 Update the trace interpretation rules in `proposal.md`,
  `design.md`, the spec delta and `backend/development/railway.md` to
  document the real order and the per-request session lifecycle.

## 4. Tests for the new lifecycle and order

- [x] 4.1 Test that two consecutive SOCKS requests build independent
  session / adapter resources, no shared pool / socket, and both
  preserve the parsed result and the documented phase order.
- [x] 4.2 Test that the `_SocksResponseSessionCloser` wrapper closes the
  underlying session exactly once (idempotent on repeated calls) and
  swallows close errors.
- [x] 4.3 Test that the SOCKS-blocked trace stops at
  `[request_started, request_write_started, socks_connect_started]` with
  no fabricated completion / header evidence.
- [x] 4.4 Test that a writer failure before the lazy SOCKS connect runs
  emits only `[request_started, request_write_started]` with no SOCKS
  evidence.
- [x] 4.5 Test that the no-proxy, injected-transport and HTTPX branches
  never emit SOCKS evidence.
- [x] 4.6 Test that the connect seam, the inherited writer seam and the
  SOCKS / writer phase pairs fire exactly once per request — no
  duplicate connection, writer, request or phase emission.

## 5. Operator evidence and validation

- [x] 5.1 Document bounded, read-only proxy/Ollama-host capture correlation
  and its explicit limits.
- [x] 5.2 Run and report the focused validation commands from `proposal.md`.
- [x] 5.3 Report exact files, supported extension point, trace interpretation,
  unresolved limits and confirmation of no commit, push, PR, sync, archive,
  Railway action or deploy.
