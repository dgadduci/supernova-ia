# Tasks: Admin/Pilot Emulator timing observability

## 0. Approval and boundaries

- [x] 0.1 User authorized creation of the timing-observability change.
- [x] 0.2 Obtain approval before implementation; keep Railway, production,
  calibration, secrets and deployment out of scope.

## 1. Timing contract and persistence

- [x] 1.1 Define the closed nullable timeline response model and UTC-to-local
  `HH:MM:SS.mmm` display contract.
- [x] 1.2 Add the minimum nullable provider-processing LLM timing/outcome
  fields and an additive reversible migration only if required.
- [x] 1.3 Capture the existing QueryLlm request and completion/timeout times
  through the provider worker boundary without changing its behavior.
- [x] 1.4 Preserve safe timing metadata through existing rollback, retry and
  terminal finalization paths.
- [x] 1.5 Correlate provider-path LLM events with the opaque synthetic inbound
  identifier using only the existing safe correlation field.

## 2. Admin/Pilot status projection

- [x] 2.1 Extend the exact synthetic-inbound status projection with the
  bounded nullable timeline and no cross-target data.
- [x] 2.2 Preserve all existing status values, fail-closed guards, polling
  behavior, outbound body and provider SID contracts.

## 3. Conversation history rendering

- [x] 3.1 Add bounded local observation timestamps to sent, status, received
  and error rows without duplicating rows on repeated polling.
- [x] 3.2 Render server worker/LLM milestones distinctly from browser-observed
  timestamps using safe DOM APIs and `HH:MM:SS.mmm`.
- [x] 3.3 Render unavailable timeline fields as `—` and preserve existing
  generic fallback behavior; do not expose internal error details.

## 4. Focused tests and validation

- [x] 4.1 Add focused tests for model/migration timing fields, normal LLM
  completion, timeout, correlation and retry/rollback retention.
- [x] 4.2 Add focused tests for status projection scoping, nullable timeline,
  closed response keys and privacy boundaries.
- [x] 4.3 Add focused panel tests for formatting, per-kind timestamps,
  server/local distinction, polling updates and bounded safe rendering.
- [x] 4.4 Run focused pytest, Ruff, compileall, strict OpenSpec validation
  and `git diff --check`; report complete output.
- [x] 4.5 Add a focused integration test that drives an LLM timeout
  through the real ``ProviderInboundMessageCoordinator`` and the live
  PostgreSQL ``procesamientos_mensajes_proveedor`` row to prove the
  captured ``llm_solicitado_en``, ``llm_finalizado_en`` and
  ``llm_resultado='timeout'`` survive the existing rollback/retry
  finalization path, with ``estado='retryable'`` and a scheduled
  ``proximo_intento_en``.

## 5. Handoff

- [x] 5.1 Do not run OpenSpec sync/archive, commit, create a PR, modify
  Railway, change variables or deploy as part of implementation.
