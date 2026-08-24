# Tasks

## 1. Diagnostic module

- [x] 1.1 Add `backend/scripts/probe_railway_socks5_repeated.py` as a
  module-runnable operator diagnostic.
- [x] 1.2 Implement `fresh` mode with one top-level `requests.post` per
  attempt and `session` mode with one diagnostic-only `requests.Session`.
- [x] 1.3 Reuse the loaded service target and proxy settings without printing
  them; use a fixed non-business payload and no automatic retries.
- [x] 1.4 Implement independent connect/read timeouts, bounded classifications,
  response consumption/closure, continuation after failures, and exit codes.
- [x] 1.5 Ensure the module imports no worker, coordinator, database, Twilio,
  Tailscale, or Ollama modules and performs no business side effects.

## 2. Focused tests and documentation

- [x] 2.1 Add focused tests for argument validation and no-request-on-invalid
  input.
- [x] 2.2 Test fresh/session call shape, proxy propagation, timeout tuple,
  sequential attempts, and response closure.
- [x] 2.3 Test success, empty response, HTTP failure, connect/read timeout,
  proxy/connection failure, mixed outcomes, and exit codes.
- [x] 2.4 Test that output excludes URL, proxy, payload, response body,
  headers, credentials, exception text, and traceback.
- [x] 2.5 Document the Railway SSH command and the narrow interpretation of
  fresh-versus-session results in `backend/development/railway.md`.

## 3. Validation and handoff

- [x] 3.1 Run focused pytest for the new diagnostic tests.
- [x] 3.2 Run Ruff on the two touched Python files.
- [x] 3.3 Run compileall on the two touched Python files.
- [x] 3.4 Run strict OpenSpec validation.
- [x] 3.5 Run `git diff --check` and report exact outputs and any pre-existing
  failures.
- [x] 3.6 Do not run sync, archive, commit, push, PR, deploy, or Railway
  variable changes.

## 4. Blocker fixes (model + configuration-error safety)

- [x] 4.1 Use `settings.llm_model` in the probe payload; the configured
  model is forwarded to the HTTP request and is never printed or
  surfaced in any return value.
- [x] 4.2 Refuse to run when `settings.ollama_proxy_url` is missing,
  empty, or structurally invalid: do not call `requests.post`, do not
  create `requests.Session`, do not allow a direct call, and emit a
  single bounded `configuration_error` record with exit code `1`.
- [x] 4.3 Capture `load_settings()` failures as a safe
  `configuration_error` record so the operator output never leaks
  tracebacks, exception text, secrets, or proxy/URL values.
- [x] 4.4 Add focused tests covering: configured model in payload
  (fresh and session), `_validate_proxy_url` allowlist behavior,
  missing/invalid proxy URL → `configuration_error`, `load_settings()`
  failures → `configuration_error`, the absence of `requests.post` and
  `requests.Session` calls, exit code `1`, and the absence of URLs,
  secrets, exceptions, and tracebacks in the rendered output and
  returned records.