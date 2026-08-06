## Why

Phase 4 has delivered the product-recognition chain through fuzzy baseline,
vector retrieval, shadow observation, calibration, deterministic pending
ambiguity resolution, and opt-in authoritative hybrid recognition. The
repository now contains the corresponding runtime paths and focused suites,
but Phase 4 has no single closure gate that exercises their shared boundaries
and separates a regression introduced by Phase 4 from older unrelated suite
failures.

Subphase 4.13 is a **verification-and-closure** change. It adds no runtime
behavior. Its outcome is an evidence-backed recommendation to close Phase 4
only if the minimum regression surface passes and every observed failure is
either a new Phase-4 regression (blocking) or a documented, reproducible,
out-of-scope pre-existing failure (deferred).

## Verified current state

- There is no active OpenSpec change directory; the latest Phase 4 changes
  are archived, including 4.12A and 4.12B.
- `get_product_recognizer()` constructs `FuzzyProductRecognizer` for the
  default mode, `ShadowedProductRecognizer` for `shadow`, and
  `HybridAuthoritativeProductRecognizer` for `hybrid_authoritative`.
- The authoritative recognizer preserves fuzzy on missing commerce context or
  embedding/vector technical failure, filters vector matches to IDs in the
  caller-supplied catalog before guards/scoring, and does not own transaction
  finalization.
- `resolve_product_selection()` declares
  `pending_product_selection_restricted`; the pending ambiguity resolver is
  a separate deterministic resolver restricted to persisted candidate IDs.
- Existing focused suites cover each path named in this proposal.

## Current execution path and shared boundary

Runtime recognition enters through the shared factory-bound
`ProductRecognizerProtocol.recognize(text, catalog, intent_metadata=...)`
boundary. Fuzzy is the default implementation; shadow decorates fuzzy without
changing its result; authoritative hybrid consumes the same catalog and
returns fuzzy on technical vector-side failure. Pending selection supplies the
restricted catalog scope, while pending ambiguity resolution consumes the
persisted candidate set and delegates completion to the existing dispatcher.
4.13 observes these paths only through their current tests and CLI.

## Fallback, transactions, and observability

The runtime fallback remains unchanged: embedding/vector technical failure in
authoritative hybrid returns the fuzzy result; an empty filtered vector side
is a valid semantic outcome, not a technical fallback. This proposal owns no
transaction and must preserve caller-owned commit/rollback behavior.
Observability consists of existing shadow metrics, calibration JSON and
diagnostic JSON, pytest node IDs, Ruff/mypy output, and the closure report;
no new telemetry is added.

## What Changes

- Add a Phase-4 closure specification and task checklist that define the
  minimum executable regression matrix, expected evidence, and decision
  rules.
- Re-run the existing tests and calibration CLI unchanged. No production
  code, test expectation, dataset, policy grid, migration, or configuration
  will be changed to obtain a green result.
- Record each diagnostic result with command, node ID, observed output,
  baseline class, and Phase-4 relevance. A variation in optional debt blocks
  only when it is materially new, increases the documented debt, changes
  runtime/business behavior, or overlaps the required Phase-4 matrix.
  Reduced findings, line-number drift, and equivalent diagnostic wording are
  documented as variations but do not block closure.
- Run strict OpenSpec validation for this change after the artifacts exist.

## Scope

The minimum Phase-4 regression surface is:

1. Fuzzy contract, baseline, aliases, availability, commerce isolation, and
   persisted-alias behavior.
2. Embedding persistence/indexing/vector-search unit and integration paths.
3. Shadow observation and failure reporting, with fuzzy remaining
   authoritative in shadow mode.
4. Calibration runner, dataset, policy, report, eligibility, diagnostic,
   catalog inventory, and the 4.11.3/4.11.4/4.11.5/4.11.7 regressions.
5. Pending restricted-candidate behavior and 4.12A end-to-end ambiguity
   resolution.
6. Controlled authoritative hybrid mode: factory/settings, policy loading,
   guards, catalog filtering, observability, and fuzzy technical fallback.
7. Focused static checks for the Phase-4 production modules, plus bytecode
   compilation. Full-project static cleanup is not a closure requirement.

## Known debt and closure decision

The following items are known from archived evidence and are not automatically
treated as regressions. 4.13 MUST reproduce and classify them; it MUST NOT
assume they still occur.

- Four `api_smoke.py` cases were recorded in 4.8/4.12A as pre-existing:
  `test_llm_settings_and_query_llm`, `test_pending_context_execution`,
  `test_pending_context_dispatcher`, and `test_agregar_producto_end_to_end`.
  They are outside the Phase-4 recognition closure surface. Their repair has
  low closure benefit and potentially broad Phase-3 orchestration scope, so
  they remain deferred only if the same named failures reproduce unchanged.
- `backend/tests/test_llm_settings.py` has three archived Ruff `B017`
  findings (lines 28, 120, 122). This is test-style debt unrelated to product
  recognition. It remains deferred if unchanged; new Ruff findings in the
  Phase-4 target files block closure.
- The strict-mypy baseline is verified archival evidence, not an inferred
  claim: `openspec/changes/archive/2026-08-04-correct-presentation-alias-misclassification-4-11-2/tasks.md:35`
  records 16 pre-existing `Missing type arguments for generic type "dict"` /
  `"tuple"` errors in `backend/recognizers/product_recognizer.py`, at the
  listed historical lines, confirmed by stash against `main`. This typing
  debt does not alter runtime or the frozen recognizer contract. Reproduction
  remains required to classify its current status; a reduced count,
  line-number drift, or equivalent message remains non-blocking, whereas an
  increased inventory, materially new type failure, or failure affecting a
  required Phase-4 boundary blocks closure.
- Two baseline cases explicitly retain `known_fuzzy_limitation` because a raw
  fuzzy call does not apply the pending presentation-alias fallback. That is
  an accepted boundary, not a defect: pending resolution owns that fallback.
  It remains deferred because moving it into fuzzy would blur the established
  responsibility boundary and risks false promotions.

No listed item blocks closure merely because its diagnostic wording or line
numbers change, or because its findings are reduced. An optional-debt outcome
blocks only if it introduces a materially new issue, increases the documented
debt, changes runtime/business behavior, or overlaps the required Phase-4
matrix. Any required-matrix failure, non-eligible calibration report, widened
pending candidate set, loss of commerce isolation, or hybrid technical
failure that does not return fuzzy is blocking. An environment blocker is not
a regression, but every required command must later run successfully in the
supported local environment before Phase 4 can close.

## Non-Goals

- No feature development, redesign, endpoint, router, schema, migration,
  dataset/policy retuning, LangGraph, embedding-model change, or unrelated
  cleanup.
- No test rewrite, baseline update, `xfail`, skip, or configuration change to
  mask a result.
- No OpenSpec sync or archive; the user retains Phase-4 closure approval.

## Impact

- New proposal artifacts only under
  `openspec/changes/subphase-4-13-global-regression-debt-verification-phase-4-closure/`.
- No application source, tests, migrations, active specifications, or
  archived change is modified.

## Expected files, tests, validation, and reversibility

Expected files are only this change's `proposal.md`, `design.md`, `tasks.md`,
and `specs/phase-4-regression-closure/spec.md`. The exact focused test and
validation commands are in `design.md` and contain no placeholders. The
change is reversible by removing this unimplemented proposal bundle; it makes
no runtime or database change.
