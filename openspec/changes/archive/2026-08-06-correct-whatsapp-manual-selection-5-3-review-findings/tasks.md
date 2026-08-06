## 1. Correct service behavior

- [x] 1.1 Make `list_manual_options` reject active non-shared channels with
  `invalid_channel_mode`, no options and no staged mutation.
- [x] 1.2 Make a `request_switch` for the already selected commerce a
  non-mutating no-op that preserves an existing pending target.
- [x] 1.3 Preserve all existing transaction and no-pipeline boundaries.

## 2. Focused regression tests

- [x] 2.1 Add a dedicated-channel option-listing regression test.
- [x] 2.2 Extend the current-commerce switch test to begin with a pending
  different target and assert state/message preservation.
- [x] 2.3 Keep coverage for no-pending current-commerce requests and valid
  target replacement.

## 3. Validation

- [x] 3.1 Run the focused Phase-5.2/5.3 pytest command from `design.md`.
- [x] 3.2 Run Ruff and `compileall` from `design.md`.
- [x] 3.3 Run strict OpenSpec validation and `git diff --check`.
- [x] 3.4 Record exact results and pre-existing/environmental blockers here.

### Recorded results

- `PYTHONPATH=. venv/bin/pytest -q backend/tests/test_shared_channel_manual_selection.py backend/tests/test_shared_channel_routing_context.py`
  → 60 passed, 29 subtests passed in 1.33s (exit 0). No new failures.
- `PYTHONPATH=. venv/bin/python -m ruff check backend/services/shared_channel_routing_service.py backend/tests/test_shared_channel_manual_selection.py`
  → `All checks passed!` (exit 0).
- `PYTHONPATH=. venv/bin/python -m compileall backend/services/shared_channel_routing_service.py backend/tests/test_shared_channel_manual_selection.py`
  → exit 0 (both files compiled without errors).
- `openspec validate correct-whatsapp-manual-selection-5-3-review-findings --strict`
  → `Change 'correct-whatsapp-manual-selection-5-3-review-findings' is valid` (exit 0).
- `git diff --check` (with intent-to-add markers on the two touched files)
  → exit 0, no whitespace or conflict markers reported.

### Environmental notes

- `backend/tests/test_shared_channel_manual_selection.py` and
  `backend/services/shared_channel_routing_service.py` were untracked in the
  working tree at session start (not committed on `main`); they were edited
  in place. `git diff --check` was re-run after `git add -N` of the two
  files, then the intent-to-add markers were reset (`git reset HEAD -- …`)
  to leave the repository untouched for the user.
- The workspace contained many pre-existing modifications outside this
  change (product recognizer phase 4.x, alembic env, settings,
  doc/Excel lock files, etc.) that were not touched and remain outside
  this change's scope.
- LSP reported pre-existing `int | None` → `int(...)` narrowing diagnostics
  on `int(persisted.comercio_id_seleccionado)` /
  `int(persisted.comercio_id_cambio_pendiente)` calls in test code; those
  patterns already existed in the file before this change and match the
  surrounding test style, so they were preserved. No new diagnostics were
  introduced.
- No new failures, no pre-existing failures touched, no blockers
  encountered.

## Deferred

- [ ] Phase 5.4 provider receipt/idempotency and common non-transactional
  core remain deferred.
