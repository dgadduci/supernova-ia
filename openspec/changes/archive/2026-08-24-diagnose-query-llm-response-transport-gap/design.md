# Design: QueryLlm response transport phase diagnostics

## Phase model

The existing `QueryLlm.request()` call remains the only execution path. It
emits bounded phases in this order on success:

```text
request_started
  -> response_received
  -> json_extracted
  -> result_parsed
  -> existing llm_request completed
```

If `requests.post()` raises a timeout or connection error, only
`request_started` is expected before the existing failure event. If the
response is returned but JSON/result handling fails, the corresponding last
completed phase identifies that boundary.

## Event shape

Prefer extending the existing `llm_request` contract only if it can represent
these phases without changing the meaning of its current `started` and
`completed` outcomes. Otherwise add one narrowly scoped event in the same
`query_llm` component. In either case:

- phase is a closed string allowlist;
- `http_status` is a bounded integer when present;
- `elapsed_ms` is a bounded non-negative integer;
- `response_bytes` is a bounded non-negative integer when available;
- `correlation_id` uses the existing safe short-string validator;
- no arbitrary labels or free-form exception data are accepted.

The phase event must not contain the prompt, response, URL, proxy, headers,
model output, credentials or customer/provider identifiers.

## Instrumentation locations

1. Immediately before the existing `_post(payload)` call.
2. Immediately after `_post` returns, before status handling or JSON access.
3. Immediately after the existing response-to-data extraction completes.
4. Immediately after `_parse(body)` returns and before the existing success
   event.

Do not use `stream=True`, change response reading, change the timeout, add a
second HTTP request or alter exception mapping. The diagnostic must preserve
the exact production transport behavior.

## Tests

Use injected transport seams and deterministic clocks already supported by
`QueryLlm`. Verify:

- successful phase ordering and metadata bounds;
- timeout in `_post` produces no false `response_received` phase;
- HTTP error and malformed/empty response preserve existing error semantics;
- correlation ids are preserved and no sensitive field is accepted;
- event emission failure does not change the request result or exception.

## Operational interpretation

- Ollama access log plus no `response_received`: response delivery/proxy path.
- `response_received` plus no `json_extracted`: client response extraction.
- `json_extracted` plus no `result_parsed`: JSON/result parsing.
- `result_parsed` plus no business response: caller/coordinator boundary,
  outside this diagnostic change.
