# Tasks: expose admin flavor LLM instruction

## 1. Protected catalog contract

- [x] 1.1 Extend only the active catalog-list response schema with
  `instruccion_llm`; retain the safe commerce summary schema unchanged.
- [x] 1.2 Align router/schema documentation with the administrative-only
  exposure contract without changing authentication or list semantics.

## 2. Focused regressions

- [x] 2.1 Cover authenticated list inclusion, active-only behavior, exact
  persisted value, and read-only/no-transaction behavior.
- [x] 2.2 Cover missing/invalid admin authentication and prove instruction
  remains absent from commerce/configuration/assignment paths.

## 3. Validation

- [x] 3.1 Run the focused pytest, Ruff, compileall, strict OpenSpec validation
  and `git diff --check` commands from `proposal.md`.

### Known baseline limitation

The focused pytest command was run during implementation. All coverage for
this change passed; the command still reports the pre-existing unrelated
failure
`backend/tests/test_remaining_fastapi_surface_security.py::RemainingFastApiSurfaceAuthorizedTest::test_comercios_get_with_matching_token_uses_session`
(`500 != 200`). It was reproduced after stashing this change's touched files,
does not exercise the flavor catalog/schema/router, and is not a regression
introduced here. Ruff, compileall, strict OpenSpec validation and
`git diff --check` passed. This limitation is recorded for review only and
does not change the completed task status.
