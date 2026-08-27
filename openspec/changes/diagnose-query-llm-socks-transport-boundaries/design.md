# Design: diagnose QueryLlm SOCKS transport boundaries

## Decision

Extend the existing `llm_request_transport_phase` catalogue rather than create
raw logs, a second request pipeline or a background probe. The default
Requests path receives a narrowly scoped observing adapter/connection seam
that delegates to the same Requests/urllib3/PySocks behavior once and only
once, through a single-request session that is constructed and torn down on
every call. It must not replace networking, monkeypatch global socket state
or change the current HTTPX experiment.

The observer MUST respect the real stack order. ``HTTPConnection.request``
enters the inherited writer seam first; only then does the lazy ``send``
path trigger ``connect()``, which routes through
``SOCKSConnection._new_conn``. Forcing ``connect()`` ahead of the writer
would invert that order and pre-allocate a socket the writer is perfectly
capable of opening lazily, so the mixin must not call ``self.connect()``
before delegating to the inherited writer.

```text
request_started                         existing QueryLlm boundary
  request_write_started                 existing HTTP writer entered
  socks_connect_started                 existing SOCKS seam entered
  socks_connect_completed               SOCKS seam returned a target socket
  request_write_completed               writer returned
response_headers_received               existing HTTP response boundary
```

A connection that already has a cached socket skips the lazy ``connect()``
step, so the SOCKS pair is omitted (and never fabricated) and only the
writer pair fires.

No phase means a later action happened. Completion is emitted only after the
existing corresponding call returns; failed calls retain the canonical
`llm_request` error event and exception type. The new phase event is evidence,
not an error classifier.

## Adapter boundary

The implementation must select the observer only for QueryLlm's existing
Requests invocation with a configured SOCKS proxy. It may use supported,
pinned Requests/urllib3/PySocks extension points available in the installed
versions. Before implementation, verify those extension points in source and
write a focused test around them. If an extension point would require global
patching, manually reimplement SOCKS, alter proxy semantics, expose a secret
or add an unpinned dependency, stop and report the blocker instead of
approximating the observation.

The adapter delegates unchanged values for URL, JSON payload, total timeout,
streaming, proxy configuration, certificate behavior and exception flow. It
does not expose peer address, proxy address or handshake data.

The QueryLlm `_post_requests` SOCKS branch MUST build a fresh
`_SocksPhaseObserverSession` per call (no process-local cache, no shared
pool, no shared adapter, no shared proxy manager and no shared socket
between two consecutive SOCKS requests). The session MUST be torn down by
a private `_SocksResponseSessionCloser` wrapper the surrounding
`QueryLlm.request` `finally` block closes exactly once; the wrapper is
idempotent and fail-soft so a misconfigured observer cannot duplicate the
connection, the writer or the request.

## Event contract

Add exactly these values to the existing closed phase allowlist:

| Phase | Required fields | Meaning |
|---|---|---|
| `socks_connect_started` | `elapsed_ms=0`, existing correlation if present | scoped SOCKS seam entered |
| `socks_connect_completed` | bounded elapsed | existing SOCKS seam returned |
| `request_write_started` | bounded elapsed | existing HTTP writer entered |
| `request_write_completed` | bounded elapsed | existing writer returned |

`http_status`, `response_bytes` and `chunk_count` are absent for all four
phases. The current event privacy validator rejects arbitrary fields and
tokens. No new exception or failure category is introduced: a stall simply
lacks a later phase; errors keep their present `llm_request` contract.

## Trace interpretation

| Last phase | What it establishes | What it cannot establish |
|---|---|---|
| `request_started` | QueryLlm entered its request boundary | socket activity |
| `socks_connect_started` | the dependency began its SOCKS connect seam | proxy TCP or target connection success |
| `socks_connect_completed` | the existing SOCKS seam returned a target socket | HTTP bytes reached Ollama |
| `request_write_completed` | the existing writer returned after handing bytes to the socket layer | proxy forwarded bytes or Ollama received them |
| `response_headers_received` | NovaOrders received an HTTP response | complete body or parsed result |

External capture resolves the final network leg. The development guide shall
give a read-only, bounded `journalctl`/`tcpdump` example for the Ollama host
and explicitly require approved operator access on the proxy host. It shall
not prescribe permanent captures or include credentials/addresses.

## Failure and ownership

An observer must not swallow, transform or duplicate the underlying exception.
It may fail silently through the existing observability mechanism. QueryLlm
continues to perform one synchronous request and map it to the current
`QueryLlm*Error` types. No transaction/session control exists in this boundary.

## Tests

Focused tests must prove:

- valid new phases round-trip and reject forbidden/sensitive fields;
- proxy-enabled successful Requests trace has the documented strict order
  (request_started → request_write_started → socks_connect_started →
  socks_connect_completed → request_write_completed →
  response_headers_received → first_body_chunk → body_completed →
  response_received → json_extracted → result_parsed);
- a blocked/raised SOCKS seam emits only
  ``[request_started, request_write_started, socks_connect_started]`` with
  no fabricated SOCKS completion, writer completion or response-header
  evidence, and preserves the current QueryLlm error classification;
- a writer failure BEFORE the lazy SOCKS connect runs emits only
  ``[request_started, request_write_started]`` with no SOCKS evidence and
  no fabricated writer completion or response-header evidence;
- no-proxy and injected test transport paths retain their current event
  sequence and do not claim SOCKS evidence;
- the HTTPX branch never emits SOCKS evidence;
- two consecutive SOCKS requests build independent session / adapter /
  proxy manager resources (no shared pool, no shared socket) and both
  preserve the parsed result and the documented phase order;
- the `_SocksResponseSessionCloser` wrapper closes the underlying session
  exactly once (idempotent on repeated calls) and swallows close errors;
- the connect seam, the inherited writer seam and the SOCKS / writer phase
  pairs fire exactly once per request — no duplicate connection, writer,
  request or phase emission;
- the SOCKS / writer phases remain private to the QueryLlm SOCKS branch
  and carry only bounded ``elapsed_ms`` and the existing opaque
  correlation value;
- observer-emission failure does not change invocation count, payload,
  timeout, exception mapping or response parsing;
- external guidance is read-only and privacy-safe.
