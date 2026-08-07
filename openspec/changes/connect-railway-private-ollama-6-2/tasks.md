## 1. Container and lifecycle boundary

- [x] 1.1 Inspect the current Railpack lifecycle and create the smallest
  Docker image that includes the existing Python runtime and official
  Tailscale binaries, without storing a key or URL in the image.
- [x] 1.2 Add an entrypoint that launches userspace Tailscale on loopback,
  authenticates it with `TS_AUTHKEY`/`TS_HOSTNAME`, has bounded readiness,
  forwards signals, and fails closed before/after Uvicorn as designed.
- [x] 1.3 Update `railway.toml` while preserving separate pre-deploy Alembic
  migration behavior, `$PORT`, `/health`, and restart policy.

## 2. Client-scoped proxy configuration

- [x] 2.1 Add and validate the optional `OLLAMA_PROXY_URL` setting with no
  local default proxy.
- [x] 2.2 Route only real `QueryLlm` and `OllamaEmbeddingClient` HTTP calls
  through that setting; preserve injected-test transports and every existing
  exception contract.
- [x] 2.3 Add focused tests for absent proxy, valid proxy propagation,
  invalid configuration, and isolation from non-Ollama clients.

## 3. Operator configuration and proof

- [x] 3.1 Update the Railway runbook with tag ownership, least-privilege
  grant, variables, node lifecycle, safe logs, rollback, and removal of the
  standalone spike.
- [x] 3.2 Add only a bounded manual helper if required to probe both existing
  client contracts without outputting content or vectors.
- [ ] 3.3 With the user's Railway/Tailscale access, configure the web service
  variables privately, deploy, verify `/health`, and confirm the tagged node
  is connected. Never paste or commit an auth key.
- [ ] 3.4 Run the bounded generate and embed probes from the integrated web
  container; record only safe pass/fail evidence and dimension `384`.
- [ ] 3.5 After 3.4 succeeds, remove the disposable standalone `tailscale`
  service and revoke/replace only the spike auth key as appropriate.

## 4. Focused validation

- [ ] 4.1 Run affected unit tests, Ruff, and `compileall` in the user's local
  terminal and retain the complete output.
- [ ] 4.2 Run strict OpenSpec validation and `git diff --check` in the user's
  local terminal.
- [ ] 4.3 Review Railway logs/configuration for secret leakage, exposed proxy
  ports, accidental global proxy variables, and unintended business changes.
