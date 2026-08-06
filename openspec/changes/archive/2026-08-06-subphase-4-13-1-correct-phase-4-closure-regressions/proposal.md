## Why

Subphase 4.13 correctly blocks Phase 4 closure on three independently verified
regressions:

1. `PRESENTACION_ALIASES` again contains `"picante": "picante"`, so a
   product descriptor incorrectly activates presentation filtering and the
   required fuzzy suite fails two tests.
2. `backend/recognizers/product_recognizer.py` has 17 strict-mypy errors
   rather than the archived baseline of 16. Parameterizing
   `matches_por_indice` exposed an additional `[assignment]` error because a
   `(None, 0)` fallback contradicts the declared `tuple[str, float]` value.
3. `api_smoke.py::test_product_selection_context_resolver` is a fifth smoke
   failure. Inspection shows its patched two-argument lambda is incompatible
   with the additive `intent_metadata` keyword now sent by
   `resolve_product_selection`; this is a test-double compatibility regression,
   not a runtime/business failure.

The correct next step is one narrow corrective change because all three
regressions have a known, local cause and two touch the same recognizer module.
It restores the previously accepted Phase-4 behavior and the documented static
baseline, then re-runs only the affected 4.13 checks. It does not close Phase
4; closure remains conditional on the 4.13 matrix after this correction.

The first corrective execution recorded reviewable evidence, but it exposed
two specification deviations: the type change introduced the 17th mypy
finding, and the mandated combined Ruff command fails exclusively on
pre-existing `api_smoke.py` debt. This revision authorizes one behavior-neutral
local correction to the mapping lookup, and classifies that unchanged Ruff
inventory as optional debt rather than requiring unrelated cleanup. It also
requires scope review against the documented 4.13.1 allowed hunks; this
worktree is already dirty, so a comparison to `main` alone cannot attribute
unrelated Phase-4 changes to this corrective execution.

## Current execution path

`detectar_productos` derives a presentation alias from
`PRESENTACION_ALIASES` and filters fuzzy candidates by presentation. `picante`
is product identity in the verified catalog, never a presentation, so it must
not enter that filter. `resolve_product_selection()` forwards the restricted
catalog scope through the shared recognizer boundary as keyword-only
`intent_metadata`; ordinary production recognizers accept it, but the legacy
smoke-test double must accept and verify it too.

## Scope

- Remove only `"picante": "picante"` from
  `backend/recognizers/product_recognizer.py`; preserve every other alias and
  all fuzzy scoring, segmentation, ranking, and four-key result semantics.
- Keep `matches_por_indice` as `dict[int, tuple[str, float]]` and replace its
  unreachable `(None, 0)` lookup fallback with direct indexed access while
  iterating that mapping's own keys. This removes only the new strict-mypy
  error and preserves its values and ranking behavior; the archived 16-error
  inventory remains deferred.
- Update only the affected `api_smoke.py` mock callback to accept the optional
  keyword-only `intent_metadata` argument and assert the resolver sends
  `{"catalog_scope": "pending_product_selection_restricted"}`. The smoke
  test must continue to exercise the existing resolver, not a replacement.
- Execute every validation command in `design.md` and record in `tasks.md` the
  exact command, exit code, pytest pass/fail/subtest count, mypy finding
  inventory, smoke failure node IDs, and strict OpenSpec result. A checkbox
  SHALL remain unchecked until its corresponding evidence is recorded.
- Preserve fuzzy as fallback, commerce isolation, pending candidate narrowing,
  caller-owned transactions, hybrid configuration behavior, and no-op
  recognition observability.

## Non-goals

- No embeddings, vector search, calibration, policy/data changes, settings,
  factory, hybrid-mode, API/endpoint, migration, LangGraph, or transaction
  change.
- No broad mypy or Ruff cleanup: the 16 archived generic-type findings and the
  separately documented unchanged `api_smoke.py` Ruff findings remain
  deferred debt unless a separately approved change addresses them.
- No changes to the four historical smoke failures, no test weakening,
  xfail/skip, sync, archive, or Phase-4 closure.

## Acceptance criteria

1. `picante` is absent from `PRESENTACION_ALIASES`; both named fuzzy tests
   pass, and legitimate presentation aliases remain covered by the existing
   focused suite.
2. Strict mypy reports exactly the archived 16 generic-type findings for
   `product_recognizer.py`; no 17th finding remains at the
   `matches_por_indice` lookup.
3. `test_product_selection_context_resolver` accepts the additive shared
   context and verifies the restricted-scope value; the full smoke command
   has only the four documented historical failures.
4. Ruff reports zero findings for `product_recognizer.py`. The combined Ruff
   command may retain only the recorded, unchanged `api_smoke.py` inventory;
   it is optional debt and does not block this change unless a finding occurs
   in `product_recognizer.py` or differs materially from that inventory.
   Compileall passes. The relevant 4.13 fuzzy, smoke, mypy, and Ruff commands
   are re-run and their exact outputs reported.
5. No production behavior outside the restored fuzzy alias classification is
   changed, and no application transaction is committed or rolled back by
   recognition.
6. The task checklist contains sufficient raw result detail for an independent
   reviewer to verify every acceptance criterion without relying on an
   unsupported summary assertion.

## Impact

- `backend/recognizers/product_recognizer.py` (alias removal, mapping
  annotation, and behavior-neutral lookup correction)
- `backend/tests/api_smoke.py` (one mock compatibility assertion)
- New OpenSpec proposal artifacts only under this change directory.

The change is reversible: restoring the single alias line and the prior type
annotation/test callback restores the former state; it makes no database or
external-state change.
