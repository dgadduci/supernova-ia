# Design: closed HTTP client selection at QueryLlm

## Decision

Add `llm_http_client: Literal["requests", "httpx"]` to `Settings`, sourced
from `LLM_HTTP_CLIENT` and defaulting to `requests`. `QueryLlm._post()` keeps
the injected `transport` seam first. For real calls it dispatches exactly once
to the selected client. No selected-client failure may invoke the other.

HTTPX is already pinned. Add `socksio` because HTTPX requires it to support the
existing `socks5://` / `socks5h://` proxy contract. The proxy remains scoped to
only the real QueryLlm call.

```text
LLM_HTTP_CLIENT unset / requests ──> Requests stream path (current default)
LLM_HTTP_CLIENT=httpx             ──> HTTPX synchronous stream path
                                     └─ same payload, proxy, timeout, events
```

## Equivalent boundary contract

For either real transport:

1. Send one POST with the existing non-streaming Ollama payload (`stream: false`).
2. Return only after headers, then iterate response bytes once.
3. Preserve phase order: `request_started`, `response_headers_received`,
   `first_body_chunk`, `body_completed`, `response_received`,
   `json_extracted`, `result_parsed`.
4. Close the response in `finally`.
5. Map HTTPX timeout, connection/proxy and stream exceptions to the existing
   closed `QueryLlmTimeoutError` / `QueryLlmConnectionError` categories.
6. Retain the existing HTTP-status and response parsing outcomes.

HTTPX permits distinct connect/write/read/pool limits, but this experiment
deliberately uses the existing total `LLM_TIMEOUT` equivalently. It does not
introduce separate timeout settings or transport-specific event fields.

## Settings and safety

Only lowercase trimmed `requests` and `httpx` are accepted; absent resolves to
`requests`. Any other value raises a clear secret-free `ValueError` during
settings load. The value is not an endpoint, proxy, credential, or customer
input.

The test deployment is opt-in. Its initial deployment remains on Requests;
the operator changes only `LLM_HTTP_CLIENT=httpx` for the experiment. Removing
that variable restores the deployed default without migration or code change.

## Tests

- Settings defaults/accepts/rejects the closed client vocabulary.
- Requests remains selected by default with existing call arguments.
- HTTPX receives the existing URL/payload/total timeout and configured SOCKS
  proxy, reads and closes one response, and produces the same result/events.
- HTTPX timeout, connection and iteration failures map to the established
  closed errors and do not call Requests.
- Neither path logs sensitive transport or business content.

## Operations

After approved implementation and local validation, deploy only to Test.
Capture Railway application events and network metadata for controlled turns.
Compare the last transport phase and Ollama journal timestamp. Revert the
runtime experiment by unsetting `LLM_HTTP_CLIENT`; do not alter timeout,
proxy, worker, or production while collecting this evidence.
