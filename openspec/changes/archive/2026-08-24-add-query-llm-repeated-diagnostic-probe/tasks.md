# Tasks: repeated QueryLlm diagnostic probe

## 1. Standalone diagnostic

- [x] 1.1 Add the module entry point under `backend/scripts/`.
- [x] 1.2 Reuse `QueryLlm.request()` with service settings and safe correlation
  ids; do not reimplement transport.
- [x] 1.3 Implement count, delay and prompt arguments with the documented
  defaults and validation.
- [x] 1.4 Print each sent message and parsed response, plus bounded timing and
  outcome information, without persisting output or exposing secrets.
- [x] 1.5 Continue after an individual failure and return the documented final
  exit status.

## 2. Focused tests

- [x] 2.1 Test defaults and argument validation.
- [x] 2.2 Test ten sequential calls and exact prompt propagation.
- [x] 2.3 Test delay placement without real sleeping.
- [x] 2.4 Test visible message/response output and safe error output.
- [x] 2.5 Test mixed outcomes and final exit status.

## 3. Validation and handoff

- [x] 3.1 Run focused pytest.
- [x] 3.2 Run Ruff on touched Python files.
- [x] 3.3 Run compileall on touched Python files.
- [x] 3.4 Run strict OpenSpec validation.
- [x] 3.5 Report exact commands and output; do not run sync, archive, commit,
  push, PR or deploy.
