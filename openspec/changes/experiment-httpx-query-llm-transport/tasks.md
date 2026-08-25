# Tasks: reversible HTTPX QueryLlm transport experiment
## 1. Configuration and dependency

- [x] 1.1 Add the exact HTTPX SOCKS support dependency required for the existing proxy contract.
- [x] 1.2 Add and validate the closed `LLM_HTTP_CLIENT` setting, defaulting to `requests`.

## 2. QueryLlm transport boundary

- [x] 2.1 Preserve the existing injected test transport and Requests default path.
- [x] 2.2 Add one synchronous HTTPX streaming path with the identical payload, proxy scope, timeout, extraction, close and event contracts.
- [x] 2.3 Map only equivalent HTTPX technical failures to the existing QueryLlm errors; do not retry or fallback between clients.

## 3. Tests and validation

- [x] 3.1 Cover selection, invalid configuration, proxy forwarding, success, timeout/connection/stream failures, event phases, single-request behavior and privacy.
- [x] 3.2 Run all commands in `proposal.md`; report complete local output for `venv/bin/python` commands.
- [ ] 3.3 Obtain review before commit, sync, archive or deploy.

## 4. Test operation (after separate authorization)

- [ ] 4.1 Deploy the committed default-Requests code only to Railway Test.
- [ ] 4.2 Set `LLM_HTTP_CLIENT=httpx` only in Test, run controlled turns, and compare safe Railway/Ollama evidence.
- [ ] 4.3 Remove the setting to return Test to Requests, record the outcome, and decide a separate permanent fix or archive.