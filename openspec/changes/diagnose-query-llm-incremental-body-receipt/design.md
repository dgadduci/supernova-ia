# Design: incremental body observation at QueryLlm

## Decision

Requests response streaming is used without enabling Ollama generation
streaming. `_post()` returns a response after headers are available. The
existing request method reads `iter_content()` once, aggregates the exact same
final text for `_parse()`, and closes the response in `finally`.

```text
request_started
  -> response_headers_received
  -> first_body_chunk (once)
  -> body_completed
  -> json_extracted
  -> result_parsed
```

No completion phase is fabricated when header/body iteration blocks or raises.

## Event contract

Extend the existing closed transport-phase vocabulary with the three phases in
the proposal. Only `http_status`, `elapsed_ms`, `response_bytes`,
`chunk_count`, and the existing opaque correlation are allowed. `chunk_count`
is bounded non-negative; unknown fields and arbitrary labels are rejected.

## Failure semantics

Timeout during the initial request leaves only `request_started`. Timeout while
iterating leaves headers and any chunks already observed, then preserves the
existing `QueryLlmTimeoutError` mapping. HTTP, empty-body and parse failures
retain their current exception behaviour. `response.close()` executes whether
success or failure occurs.

## Tests

Focused tests prove the exact request argument `stream=True`, unchanged
payload `stream=False`, phase order, header-only timeout, partial-body timeout,
complete body parsing, close-on-success/error and exclusion of body/header
content from every event. Existing non-streaming transport stubs remain
supported through the smallest compatible adapter seam.

