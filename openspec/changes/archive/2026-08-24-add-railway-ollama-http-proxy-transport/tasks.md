# Tasks

## 1. OpenSpec and runtime contract

- [x] 1.1 Add the delta that permits a loopback HTTP proxy while preserving
  the existing SOCKS5 contract and explicit operator selection.
- [x] 1.2 Update the Tailscale entrypoint to start the loopback HTTP listener
  on `127.0.0.1:1056` alongside the existing SOCKS5 listener on `127.0.0.1:1055`.
- [x] 1.3 Extend `OLLAMA_PROXY_URL` validation to accept `http://` and retain
  rejection of malformed, credentialed, unsupported, or unsafe values.
- [x] 1.3.1 Restrict the `http://` accepted value to host `127.0.0.1` so a
  remote HTTP proxy cannot be configured; apply the same loopback-only
  rule in the generate/embed contract diagnostic, which must report
  `invalid_proxy_configuration` and never invoke `requests.post` when the
  configured HTTP proxy is not loopback.
- [x] 1.4 Keep proxy application scoped to the existing Ollama clients and
  preserve all current payload, timeout, parsing, retry, and transaction
  behavior.
- [x] 1.5 Update the Railway generate/embed contract diagnostic to accept the
  selected supported proxy scheme without printing its value.

## 2. Focused tests and documentation

- [x] 2.1 Add settings tests for valid HTTP, valid SOCKS5/SOCKS5H, invalid
  schemes, malformed values, credentials, and no-proxy local behavior.
- [x] 2.2 Update entrypoint tests for both loopback listeners, userspace mode,
  bounded readiness, supervision, and fail-closed startup.
- [x] 2.3 Update focused client/contract diagnostic tests to verify HTTP proxy
  propagation and safe output where applicable.
- [x] 2.4 Document explicit A/B selection, ports, rollback to SOCKS5, and the
  requirement that no automatic fallback is used.

## 3. Validation and handoff

- [x] 3.1 Run the focused pytest files covering settings, entrypoint, clients,
  and the Railway contract diagnostic.
- [x] 3.2 Run Ruff on every touched Python file.
- [x] 3.3 Run compileall on every touched Python file.
- [x] 3.4 Run `openspec validate add-railway-ollama-http-proxy-transport
  --strict`.
- [x] 3.5 Run `git diff --check` and report exact output plus pre-existing
  failures separately.
- [x] 3.6 Do not run sync, archive, commit, push, PR, deploy, or Railway
  variable changes.

## 4. Scope guard

- [x] 4.1 Do not modify worker, coordinator, QueryLlm business behavior,
  Twilio/T-C, database, outbox, Ollama host, Tailscale ACLs, or migrations.
- [x] 4.2 Do not add automatic transport fallback, retries, pooling, timeout
  changes, direct/public routes, or unrelated cleanup.
