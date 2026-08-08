# Subphase 6.3: diagnose and restore the Railway–Tailscale–Ollama embedding return path

## Objective

Diagnose and correct the infrastructure path between the Railway web service's
colocated userspace Tailscale SOCKS proxy and the private Ollama node so that
the existing `POST /api/embed` response body returns to Railway. Preserve the
already-passing generate contract and do not change application recognition,
embedding, model, Twilio, or order behaviour.

## Verified starting point

- Railway uses a colocated `tailscaled --tun=userspace-networking` SOCKS5
  proxy bound to `127.0.0.1:1055`; only existing Ollama HTTP calls consume it.
- Railway generate passes with `qwen2.5-coder:7b-ctx8192` in approximately
  0.77 seconds.
- Railway's proxied `all-minilm:latest` `/api/embed` call times out after
  30–45 seconds with no response bytes, including a streaming diagnostic.
- During that attempt the Ollama host records `POST /api/embed` as HTTP 200
  in approximately 41–64 ms. A direct non-Railway `/api/embed` call returns
  HTTP 200 in approximately 0.75 seconds.
- Railway-to-Ollama `tailscale ping` is direct UDP (approximately 235 ms),
  not DERP. It proves reachability only, not return-body delivery through the
  SOCKS transport.
- The deployed bounded diagnostic timed out after approximately 30.81 seconds
  with no HTTP status or received bytes. Concurrent capture on the Ollama
  host's `tailscale0` interface proves that the host emitted approximately
  4941 response bytes after its HTTP 200, while Railway never acknowledged
  the first response byte and eventually reset the connection with `ack 1`.
- A reversible Railway image-pin experiment upgraded `tailscaled` from
  `v1.98.9` to `v1.102.2`, verified the latter version in the deployed
  container, and produced the same timeout after approximately 30.80 seconds.
  The experiment was rolled back to `v1.98.9`. Version alignment is therefore
  not a remedy, and no root cause is demonstrated.

## Scope

- Establish a safe, repeatable bidirectional transport diagnostic from the
  integrated Railway container through its loopback SOCKS proxy to Ollama.
- Inspect and, only after evidence identifies the fault, correct the smallest
  Railway/Tailscale/Ollama infrastructure configuration or lifecycle boundary
  needed for proxied response bytes to return.
- Preserve loopback-only proxy exposure, `tag:railway`, least-privilege ACLs,
  direct local development behaviour, and the existing client-scoped proxy.
- Record sanitized evidence for generate and embed: status/category, elapsed
  time, byte receipt, and vector dimension; never record request text,
  generated output, vectors, URLs with credentials, keys, or raw status JSON.

## Non-goals

- No changes to classification, recognition, embedding payload/parsing,
  models, timeouts, concurrency, fallbacks, product data, migrations, Twilio,
  WhatsApp, orders, or public Ollama exposure.
- No end-to-end Twilio verification until the integrated embed gate passes.
- No model substitution, retry amplification, timeout increase, process-wide
  proxy, DERP forcing, exit node, Funnel/Serve endpoint, reverse tunnel, or
  alternate direct/public route as a workaround.

## Shared boundary and outcomes

| Condition | Authoritative outcome | Required action |
| --- | --- | --- |
| Proxied request receives a complete valid embed response | private transport gate passes | retain existing application contracts; proceed to separate readiness work |
| Ollama logs 200 but Railway receives zero bytes or times out | return-path infrastructure fault remains open | diagnose/correct infra only; keep business gate failed |
| Request never reaches Ollama or is denied | forward-path/ACL/service fault | diagnose/correct infra only; keep business gate failed |
| Generate passes but embed fails | generate is non-authoritative for embedding readiness | do not infer success or alter the embedding client |
| Any diagnostic is inconclusive | no infrastructure change is authorized | retain current deployment and gather bounded sanitized evidence |
| Version-alignment experiment returns the same no-byte timeout | image-version mismatch is not the remedy | roll back the image pin; do not repeat the experiment or infer a root cause |

## Transaction ownership and observability

This change owns no application transaction and shall not alter request
transactions. Diagnostics are operator-run and read-only apart from an
explicit approved infrastructure configuration/deployment correction. Safe
output may include component/version identifiers, transport mode, route class,
HTTP status, elapsed time, response-byte count, and embedding dimension.

## Expected files

- This OpenSpec change and its capability delta.
- Only if the evidence warrants a correction: `Dockerfile`,
  `docker-entrypoint.sh`, `railway.toml`, `backend/development/railway.md`,
  and focused deployment-boundary tests or safe diagnostic tooling.

## Focused validation and rollback

Validation requires the deployed integrated generate/embed contract helper,
the bounded byte-receipt diagnostic, safe Ollama access-log correlation, and
focused static/startup checks for any touched deployment files. The user runs
any Python validation with the project `venv` locally and supplies the full
output. Before approval for implementation, the user runs these exact commands
locally and supplies their complete output:

```sh
openspec validate diagnose-railway-tailscale-ollama-embed-return-path-6-3 --strict
git diff --check
```

If implementation touches `docker-entrypoint.sh`, the focused static check is:

```sh
sh -n docker-entrypoint.sh
```

Any correction is reversible by Railway deployment rollback and restoring the
previous user-owned Tailscale/Ollama configuration. It must not include a
database downgrade or an automatic ACL/key mutation.

## Deferred limitations

This subphase does not add high availability, metrics infrastructure, or a
general network troubleshooting framework. It resolves only the proven
response-return failure for the private Ollama embedding route.
