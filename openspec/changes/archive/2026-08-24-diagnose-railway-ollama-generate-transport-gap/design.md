# Design

## Shared boundary

Reuse the existing readiness diagnostic's `requests.post` boundary and the
configured `Settings.llm_url`, `Settings.ollama_proxy_url`, and
`Settings.llm_timeout`. The generate probe must use a fixed controlled JSON
payload sufficient for Ollama `/api/generate`, `stream=false`, and
`response.iter_content()` so the operator can tell whether response bytes
crossed the proxy. It must not call the worker or mutate application state.

If the existing diagnostic CLI already owns the transport flag, extend it with
an explicit generate target while preserving the current embedding behavior and
default. Do not duplicate proxy parsing or timeout handling.

## Result categories

Use a closed set of safe categories:

- `response_bytes_received`
- `empty_response`
- `http_status`
- `timeout`
- `connection_error`
- `request_error`
- `invalid_proxy_configuration`

The command returns zero only for `response_bytes_received`; every other
category returns non-zero. It must close the response on every connected path.

## Correlation procedure

The operator runs one bounded generate transport attempt from the integrated
Railway shell, records the UTC timestamp and safe result, and checks the
corresponding Ollama access log for a matching `/api/generate` request. Repeat
the command manually for intermittent reproduction. Interpret only the
four-way boundary in the proposal; do not infer success from `tailscale ping`
or a control-plane-ready log alone.

## Failure and rollback

The diagnostic must never retry internally, modify timeout values, or fall back
to a direct/public endpoint. Removing the diagnostic and its focused tests
fully restores the previous code surface; no migration or environment change
is involved.
