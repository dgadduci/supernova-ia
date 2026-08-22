# Tasks: diagnose provider worker inbound path

## OpenSpec and event contract

- [x] 1.1 Register the closed `provider_inbound_stage` event, component,
  outcomes, stages, optional fields, bounds and payload-key allowlist.
- [x] 1.2 Export the event through `backend.observability.__init__` and keep
  the existing production-log parser/query contract compatible.
- [x] 1.3 Add a minimal privacy-safe correlation context only if required to
  carry the existing provider opaque value from the coordinator to both
  generation and semantic embedding events.

## Provider path instrumentation

- [x] 2.1 Emit availability and session/order staging boundaries around the
  existing coordinator seams.
- [x] 2.2 Emit business-pipeline boundaries around the existing
  `process_incoming_message` call without changing its arguments, transaction
  ownership or exception behavior.
- [x] 2.3 Emit outbound-staging and processing-finalization boundaries only
  after their existing authoritative return/commit conditions are known.
- [x] 2.4 Propagate the existing safe provider correlation value to
  `llm_request` and `embedding_request` events and clear it on every exit path.
- [x] 2.5 Preserve the existing no-fallback, retry, lease-loss, unavailable,
  rollback and body-scrubbing semantics.

## Tests and validation

- [x] 3.1 Add event catalogue/parser/privacy/bounds tests.
- [x] 3.2 Add coordinator success, failure, incomplete-stage and
  event-emission-failure tests.
- [x] 3.3 Add QueryLlm and Ollama embedding correlation tests while preserving
  direct non-provider behavior.
- [x] 3.4 Run focused pytest, Ruff, compileall, strict OpenSpec validation and
  `git diff --check`; report complete output and any pre-existing failures.

## Handoff restrictions

- [x] 4.1 Do not modify the probe script as part of this change.
- [x] 4.2 Do not execute `openspec sync` or `openspec archive`.
- [x] 4.3 Do not commit, push, create a PR, change Railway variables or deploy.

## Revision: close the BaseException cleanup and finalization coverage blockers

- [x] 5.1 Wrap the provider-scoped recorder install / use / finalize in
  `try/finally` so the safe opaque synthetic inbound correlation is cleared
  on every exit (success, rollback, retryable, terminal, unavailable,
  lease_lost, `Exception` and `BaseException` such as `KeyboardInterrupt`
  or `SystemExit`).
- [x] 5.2 Centralize the `processing_finalization` stage instrumentation in
  `_run_processing_finalization` and route every finalization branch
  (`receipt_missing`, `unavailable`, `finalize_processed`,
  `finalize_retryable`, `finalize_terminal`, lease_lost, exception) through
  it.
- [x] 5.3 Preserve the existing ordering between `finalize` /
  `commit` / `rollback` / `provider_inbound_processing_outcome` so the
  `processing_finalization` `completed` event is emitted only after a
  successful commit and the `failed (LeaseLost)` event is emitted only
  after a rollback.
- [x] 5.4 Keep `KeyboardInterrupt`, `SystemExit` and other
  `BaseException` instances propagating unchanged — they MUST NOT be
  converted to a retry or business outcome by the diagnostic.
- [x] 5.5 Re-validate the focused pytest, Ruff, compileall, strict
  OpenSpec validation and `git diff --check` and report complete output
  after the blocker fixes; surface any pre-existing failure separately.

## Revision: rollback BEFORE the `processing_finalization` failed event

- [x] 6.1 Make `_finalize_processed_and_commit` roll back internally
  when `finalize_processed` returns `False` so the `processing_
  finalization` `failed (LeaseLost)` stage event is emitted only
  AFTER the matching rollback completes.
- [x] 6.2 Make `_run_processing_finalization` roll back the
  caller-owned transaction BEFORE emitting the `failed` stage event
  on any `BaseException` raised inside the finalize seam; the safe
  `exception_type` token is the only piece of the exception that
  leaks through the diagnostic and the original exception is
  re-raised unchanged so the existing rollback / lease / retry /
  terminal paths remain authoritative.
- [x] 6.3 Preserve the existing external rollback in `process_lease`
  unchanged so the caller-owned rollback policy is not altered; the
  external call is an idempotent no-op when the transaction is
  already closed by the helper.
- [x] 6.4 Add `FinalizationOrderingTest` with one explicit ordering
  test per reachable branch — `finalize_processed` (commit success,
  lease_lost, exception, commit-after-success raises),
  `finalize_terminal` via `receipt_missing` (commit success,
  lease_lost, exception), `finalize_terminal` via `unavailable`
  (commit success, lease_lost, exception), `finalize_retryable`
  (commit success, lease_lost, exception), `finalize_terminal`
  exhaustion (commit success, lease_lost, exception) — and a
  guard test that asserts no `processing_outcome` event is
  emitted before the `processing_finalization=failed (LeaseLost)`
  event.
- [x] 6.5 Re-run the focused pytest, Ruff, compileall, strict
  OpenSpec validation and `git diff --check` and report complete
  output; surface any pre-existing failure separately.

