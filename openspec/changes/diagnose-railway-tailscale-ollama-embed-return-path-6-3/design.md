## Decision

Treat this as a bidirectional userspace-SOCKS transport incident, not an
Ollama or application-contract incident. The authoritative proof is a single
bounded request from the Railway web-service container, routed through
`socks5h://127.0.0.1:1055`, for which all three observations agree:

1. the host receives the request;
2. Railway receives response bytes and a terminal HTTP result; and
3. the existing embedding client accepts a 384-dimensional vector.

`tailscale ping`, a connected control-plane state, a direct UDP path, Ollama's
HTTP 200 access log, and passing generate are supporting evidence only. None
proves the response bytes crossed the SOCKS route back to Railway.

## Diagnostic sequence

1. From the integrated Railway container, capture sanitized Tailscale binary
   version, daemon state class, and the local listener binding; do not emit
   auth/node keys or raw status JSON.
2. Run one bounded raw HTTP diagnostic through the configured loopback SOCKS
   proxy to the configured embedding endpoint. Record only connection result,
   HTTP status, elapsed time, and received-byte count. Run the same small
   request directly only from an approved non-Railway diagnostic context, not
   by adding a Railway fallback.
3. Correlate the attempt with Ollama's safe access-log metadata. Distinguish
   no arrival, arrival without a Railway response, malformed/non-success
   response, and successful response delivery.
4. Inspect the exact deployed image/entrypoint and userspace daemon settings,
   plus relevant host-side Tailscale/Ollama service/network settings. Compare
   versions and routing mode with a known successful direct path.
5. Select exactly one minimal infrastructure correction only when the evidence
   identifies a causal configuration/lifecycle incompatibility. Re-run steps
   1–3 and then the existing integrated contract helper.

## Controlled MTU/MSS investigation

The next authorized diagnostic path is a single, reversible MTU/MSS
investigation on the user-owned Ollama host. It is justified by the proved
asymmetry: the host emits an approximately 4941-byte embedding response while
Railway does not acknowledge its first byte. It is not evidence that MTU or
MSS is the root cause.

Before any network mutation, inspect and retain only safe metadata for the
host operating system, active firewall mechanism, Tailscale interface MTU,
and whether an existing MSS-clamping rule already applies. Choose the smallest
host-local, temporary adjustment only after that inspection; do not alter
Railway, tailnet ACLs, model settings, or application code. The adjustment
must have an exact documented rollback command and a bounded before/after
transport diagnostic. If the diagnostic remains a zero-byte timeout, restore
the prior network state immediately and record MTU/MSS as ruled out.

The verified correction is a UFW-managed `mangle` PREROUTING rule, placed
before UFW's `filter` table in `/etc/ufw/before.rules`:

```text
*mangle
:PREROUTING ACCEPT [0:0]
-A PREROUTING -i tailscale0 -p tcp --dport 11434 --tcp-flags SYN,RST SYN -j TCPMSS --set-mss 1160
COMMIT
```

It affects only new inbound Tailscale connections to Ollama's port 11434. A
before/after diagnostic received 4797 bytes with HTTP 200, and the existing
integrated helper passed generate plus the 384-dimension embed contract. The
rule is retained as the minimal operational correction; all broader firewall
rewrites, service restarts, and alternate transport paths remain out of scope.

Diagnostics must be bounded, rate-limited to operator runs, and must not log
payloads, outputs, vectors, credentials, raw routes, or raw daemon status.

## Correction boundary

The permitted correction surface is limited to the Railway image/entrypoint,
Railway deployment settings, userspace Tailscale daemon configuration, and
the user-owned Ollama host/Tailscale configuration. It may not change
`QueryLlm`, `OllamaEmbeddingClient`, `Settings`, payloads, models, configured
timeouts, or proxy scope. The proxy remains loopback-only and only Ollama
clients retain the proxy mapping.

No correction may be chosen merely because it makes a probe pass: it must
explain why the host emitted 200 while the Railway process received zero
bytes, and preserve the established private-network boundary.

## Failure behaviour

| Evidence | Interpretation | Behaviour |
| --- | --- | --- |
| Host has no matching request | forward path is broken | do not touch clients; inspect ACL, destination, and daemon path |
| Host has 200; Railway has zero bytes | return path or SOCKS relay is broken | diagnose daemon/runtime/network configuration only |
| Railway receives non-2xx or malformed body | endpoint/contract issue | retain existing client errors; do not change parser/payload in this change |
| Railway receives valid 384-dimension vector | route passes | run the existing embed contract gate and record safe result |
| Controlled MTU/MSS experiment has unchanged timeout | MTU/MSS is not the remedy | immediately restore the prior host network state; do not retry variants |
| MSS 1160 rule returns response bytes and helper passes | effective return-path segment sizing was insufficient | retain exactly the UFW rule above and keep all other transport settings unchanged |

## Operational gate

Twilio and WhatsApp remain disabled for end-to-end testing until one deployed
integrated invocation reports `generate=passed` and `embed=passed` with
dimension `384`, and the accompanying diagnostic confirms response-byte
receipt through the loopback SOCKS route. Increasing an application timeout
is not an acceptable substitute for this evidence.
