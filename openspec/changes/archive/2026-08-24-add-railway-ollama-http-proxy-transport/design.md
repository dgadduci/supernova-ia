# Design: selectable loopback HTTP proxy for Railway Ollama

## Tailscale listeners

Keep `--tun=userspace-networking` and the current
`--socks5-server=127.0.0.1:1055`. Add
`--outbound-http-proxy-listen=127.0.0.1:1056` to the same `tailscaled`
process. Both listeners are loopback-only; neither receives a Railway public
port. Existing bounded Tailscale readiness and process-supervision behavior
remain unchanged.

The implementation must not infer the active listener from the configured
URL, disable the other listener, or create a fallback route. The application
uses only the URL selected by `OLLAMA_PROXY_URL`.

## Proxy setting contract

Extend the existing `OLLAMA_PROXY_URL` parser to accept absolute URLs with
one of these schemes:

- `socks5://` or `socks5h://`, preserving the current port and semantics;
- `http://`, for the loopback Tailscale HTTP proxy.

Continue rejecting missing host, credentials, path, query, fragment, blank
values, unsupported schemes, and malformed URLs. Do not accept `https://` for
this local listener unless the existing client contract requires it.

The configured value remains optional for local development and required by
the Railway entrypoint. The same value is passed only to `QueryLlm` and
`OllamaEmbeddingClient`; no process-wide `HTTP_PROXY`, `HTTPS_PROXY`, or
`ALL_PROXY` mutation is introduced.

## Existing client and diagnostic contracts

`QueryLlm` and `OllamaEmbeddingClient` already receive a proxy value at their
existing transport boundaries. Preserve their payloads, URLs, models,
timeouts, parsing, error mapping, and transaction behavior. Update only
validation/contracts that incorrectly assume SOCKS5 is the sole supported
scheme.

The Railway generate/embed contract diagnostic must validate the selected
proxy as supported rather than requiring the literal SOCKS5 URL. Its safe
output must continue to omit proxy and endpoint values.

## Operational A/B procedure

After the user deploys the change to `test`, the operator may set exactly one
of these values and redeploy/restart:

```text
OLLAMA_PROXY_URL=socks5h://127.0.0.1:1055
OLLAMA_PROXY_URL=http://127.0.0.1:1056
```

Run the existing isolated contract/repeated probes first, then test real
provider messages with the live audit. The result is evidence only; the
application must not switch transports automatically.

## Failure behavior

- If the selected proxy URL is invalid, startup/settings loading fails with
  the existing secret-free configuration error.
- If Tailscale fails readiness, the application does not start.
- If the selected HTTP proxy fails, the existing Ollama client error and
  worker retry semantics remain unchanged.
- No direct/private alternate route is attempted by the application.

## Test seams

Use focused unit seams for settings parsing, entrypoint source/argument
ordering, diagnostic proxy acceptance, and existing client proxy propagation.
Do not add a live-network test, database fixture, worker test, or a mock that
changes production call shape unless required to assert the existing proxy
boundary.
