# Add an HTTP proxy transport for Railway Ollama access

## Objective

Add a reversible HTTP-proxy alternative to the existing loopback Tailscale
SOCKS5 path used by the Railway `supernova-ia` service to reach private
Ollama. The change is intended as a controlled A/B transport test for the
intermittent `requests.post` boundary failure; it must not silently change
the current test deployment from SOCKS5 to HTTP.

## Current execution path

The deployed container runs Tailscale in userspace mode and starts a
loopback-only SOCKS5 listener at `127.0.0.1:1055`. `OLLAMA_PROXY_URL` is
validated as a SOCKS5 URL and is passed only to the existing Ollama generate
and embedding clients. The current path is:

`worker/coordinator` → `QueryLlm` or `OllamaEmbeddingClient` → Requests/client
transport → `OLLAMA_PROXY_URL` → userspace Tailscale → private Ollama.

The isolated repeated probes pass, while real worker requests can remain in
`requests.post` without Ollama receiving a request. An HTTP userspace proxy
provides a transport comparison without requiring Railway to expose
`/dev/net/tun`.

## Scope

- Start a second loopback-only Tailscale userspace listener for HTTP proxy
  traffic, while retaining the existing SOCKS5 listener and port.
- Allow `OLLAMA_PROXY_URL` to select either the existing SOCKS5 schemes or a
  loopback HTTP proxy URL.
- Preserve the existing proxy scope: only the Ollama generate and embedding
  clients receive the proxy mapping.
- Update the deployment contract diagnostic, focused tests, and Railway
  runbook so the operator can select HTTP explicitly in `test`.
- Keep the selection reversible by restoring the existing SOCKS5 variable.

## Non-goals

- No automatic SOCKS5→HTTP fallback, retries, pooling, timeout changes, or
  direct/public Ollama route.
- No change to the worker, coordinator, business pipeline, leases, outbox,
  Twilio, T-C, or order behavior.
- No `TS_USERSPACE=false`, `/dev/net/tun`, `NET_ADMIN`, subnet-router, Serve,
  Funnel, firewall, ACL, or Ollama-host change.
- No Railway variable mutation, deployment, sync, archive, commit, or PR by
  Minimax.
- No unrelated lint cleanup or migration.

## Shared boundary

The single configured `OLLAMA_PROXY_URL` remains the authoritative transport
selection. At runtime exactly that configured proxy is passed to the existing
Ollama clients; the presence of both local Tailscale listeners must not make
the application use both or select one implicitly.

## Fallback behavior

There is no runtime fallback. An unsupported, malformed, or unavailable
configured proxy remains a configuration or transport failure. Operators can
roll back by restoring `OLLAMA_PROXY_URL=socks5h://127.0.0.1:1055` and
redeploying the same implementation.

## Transaction ownership

No database session, transaction, lease, retry, or business mutation is
introduced or moved.

## Observability

Startup and diagnostic output may identify the selected proxy scheme or a
closed configuration category, but must not print proxy URLs, credentials,
Tailscale state, endpoint secrets, prompts, responses, or exception text.

## Expected files

- `docker-entrypoint.sh`
- `backend/config/settings.py`
- `backend/scripts/check_railway_ollama_contracts.py`
- `backend/development/railway.md`
- Focused settings, entrypoint, transport-contract, and client contract tests
- This OpenSpec change directory only

## Focused tests and validation

- Validate SOCKS5 and HTTP proxy parsing, rejection of unsupported schemes,
  and preservation of no-proxy local development behavior.
- Verify entrypoint starts both loopback-only listeners and keeps userspace
  mode, readiness, and fail-closed behavior.
- Verify both generate and embedding contract diagnostics accept the selected
  proxy scheme without leaking values.
- Run focused pytest, Ruff on touched Python files, `compileall` on touched
  Python files, strict OpenSpec validation, and `git diff --check`.
- Do not run deployment or change Railway variables as implementation work.

## Rollback and deferred limitations

Rollback is configuration-only: restore the existing SOCKS5 proxy URL and
redeploy. The HTTP listener may remain available on loopback but is not used
when SOCKS5 is selected. This change does not establish that HTTP fixes the
intermittent worker failure; that requires an operator-run A/B test after
deployment.
