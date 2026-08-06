## Context

Subphase 4.10 shipped the shadow-mode telemetry as a frozen
`ProductRecognitionShadowComparison` dataclass in
`backend/services/product_recognition_shadow_comparison.py`. The
dataclass documents eleven fields and the spec requires the
dataclass to behave as a true frozen dataclass. To surface the
sanitized shadow-pipeline failure category to the recorder, the
shipped implementation attaches the value through
`object.__setattr__(comparison, "_failure_category", ...)` inside
`ProductRecognitionShadowService.compare` and reads it back
through `getattr(comparison, "_failure_category", None)` inside
`ShadowMetricsRecorder.record` (and its two helpers
`_failure_category_unset` and `_failure_category_from`). The
mutation is a hidden attribute the public dataclass schema does
not declare, breaking the "frozen dataclass" contract for an
undocumented field and forcing every reader to use `getattr`
defensively.

The four code touch points today are:

- `backend/services/product_recognition_shadow_comparison.py`
  (declares the dataclass and the field list).
- `backend/services/product_recognition_shadow_service.py:230`
  (mutates the constructed comparison through
  `object.__setattr__`).
- `backend/services/shadow_metrics_recorder.py:50-57, 106-125`
  (reads the hidden attribute; defines the
  `_failure_category_unset` / `_failure_category_from` helpers).
- `backend/tests/test_shadow_metrics_recorder.py:228` and
  `backend/tests/test_product_recognition_shadow_service.py:419`
  (set up the hidden attribute and read it back through
  `getattr`).

The constraint set is fixed: the fuzzy result stays
authoritative, the shadow ranking and hybrid observation stay
observational, the settings and thresholds stay unchanged, the
customer-visible results and pending contexts stay unchanged, the
`Callable[[], ProductPresentationVectorSearchService]` dependency
shape stays unchanged, and the logging safety rules stay
unchanged.

## Goals / Non-Goals

**Goals:**

- Make the sanitized shadow-pipeline failure category a declared
  field of `ProductRecognitionShadowComparison` so the public
  shape carries it without any hidden mutation.
- Remove the `object.__setattr__(comparison, "_failure_category", ...)`
  mutation and the `getattr(comparison, "_failure_category", None)`
  reads.
- Update the recorder to read the failure category from the
  explicit field, keeping the recorder-side `"unknown"` fallback
  when `vector_available is False` and `failure_category is None`.
- Preserve the existing 4.10 behavior: shadow ranking, hybrid
  observational decisions, settings, thresholds, customer-visible
  outputs, dependency shapes, and logging safety rules.
- Cover the refactor with focused tests: no `object.__setattr__` in
  `backend/services/`, no hidden `_failure_category` attribute,
  the eight scenarios listed in the project.md test plan, and
  the regression of the existing 4.10 focused tests.

**Non-Goals:**

- Introduce an internal "shadow result" wrapper tuple
  (alternative from project.md). The "add an explicit field"
  option is the smallest implementation that fits the existing
  code and is the approved approach.
- Change any other field of `ProductRecognitionShadowComparison`
  or `ProductRecognitionHybridObservation`.
- Change the recorder's `record(...)` signature or the shadow
  service's `compare(...)` return shape.
- Run `/opsx:sync` or `/opsx:archive`. The change sits under
  `openspec/changes/clean-shadow-failure-reporting-4-10-1/`
  until the user explicitly syncs and archives.

## Decisions

### Decision 1 — Add `failure_category: str | None` as an explicit field on the comparison

The preferred solution from project.md is one of:

- add `failure_category: str | None` as an explicit field of
  `ProductRecognitionShadowComparison`; or
- return a dedicated internal result containing comparison,
  hybrid observation, and failure category.

The first option is the smallest implementation that fits the
existing code:

- It keeps the current tuple return shape of
  `ProductRecognitionShadowService.compare` (no new internal
  result type to thread through the recorder).
- It keeps the current `record(...)` signature; the recorder
  still takes the comparison and the hybrid observation.
- It makes the failure category discoverable through the public
  dataclass schema (no hidden attribute), so the test that
  inspects the dataclass can encode the field directly.
- It keeps the recorder-side `"unknown"` fallback in exactly one
  place (`ShadowMetricsRecorder.record`).

The second option was rejected because it introduces a new
internal type and a new field on the recorder's `record(...)`
signature, increasing the surface area for a 4.10.1 cleanup
that is meant to be the smallest change. It also loses the
ability to inspect the failure category on the dataclass
directly when the recorder is bypassed.

**Alternatives considered:**

- *Internal shadow result wrapper* — rejected, see above.
- *Add a `failure_category` to the `ProductRecognitionHybridObservation`
  dataclass instead* — rejected because the failure category is a
  property of the shadow-pipeline call, not of the hybrid ranking.
  Mixing them would corrupt the hybrid observation surface that
  Subphase 4.11 calibration is allowed to replace.
- *Keep the hidden attribute but rename it to a documented name*
  — rejected; the spec forbids hidden attributes on the frozen
  dataclass and the project.md requirement explicitly states "do
  not add hidden attributes to frozen dataclasses".

### Decision 2 — The recorder continues to own the `"unknown"` fallback

The recorder's `record` method is the only place that emits
`"unknown"` and the rule stays the same: when
`comparison.vector_available is False` AND
`comparison.failure_category is None`, the recorder emits
`failure_category="unknown"`; otherwise the recorder emits the
value of `comparison.failure_category` (which is `None` or one
of `"embedding_failure"` / `"vector_failure"`).

The shadow service never emits `"unknown"`. The shadow service
sets `failure_category` to the sanitized pipeline category
(`"embedding_failure"`, `"vector_failure"`, or `None`).

This split keeps the responsibility clean: the shadow service
records what the pipelines did, the recorder records what it
emitted.

### Decision 3 — Drop the `_failure_category_unset` and `_failure_category_from` helpers

Today the two helpers wrap the `getattr(comparison,
"_failure_category", None)` read. After the refactor the
recorder reads `comparison.failure_category` directly in a
single expression, so the helpers are dead code and can be
removed. The "hidden source of truth" comment in
`shadow_metrics_recorder.py:113-115` becomes obsolete.

### Decision 4 — Frozen dataclass boundary stays clean

`ProductRecognitionShadowComparison` stays a plain
`@dataclass(frozen=True)`. The new field is supplied through
the constructor; the only change to the constructor is the
extra positional / keyword argument. The dataclass is still
NOT a Pydantic model, a SQLAlchemy ORM model, or a class with
side effects in `__post_init__`. The assignment-to-field
frozen check still raises `FrozenInstanceError`.

## Risks / Trade-offs

- [Test refactor couples the recorder and the comparison
  constructor] → The new test for the recorder passes the
  `failure_category` through the constructor, mirroring the
  new typed contract. The previous test attached the category
  through `object.__setattr__`; it is replaced.
- [Speculative compatibility risk for downstream consumers of
  the comparison dataclass] → The comparison is an internal
  Subphase 4.10 surface; the only consumer is the recorder and
  the focus tests. The new field is appended at the end of the
  field list and uses `None` / `"embedding_failure"` /
  `"vector_failure"` (the sanitized literals the previous
  hidden attribute already produced), so the recorder's log
  record is byte-for-byte the same.
- [Drift between the delta spec and the focused test
  scenarios] → The focused tests are the single source of
  truth for the new behavior; the delta spec scenarios
  (`#### Scenario:` blocks) must match the focus tests once
  `/opsx:sync` lands. The implementation tasks enforce this
  by running the focus tests and the spec validation together.
- [Risk that the spec validation rejects the
  `failure_category` field on the previously-11-field
  requirement] → The delta spec already declares the
  requirement as having twelve fields; the focus tests must
  pass after the implementation lands. The subphase explicitly
  runs `openspec validate clean-shadow-failure-reporting-4-10-1
  --strict` as the last validation step.

## Migration Plan

This is a behavior-preserving refactor of an internal shadow
telemetry surface. There is no database migration, no API
change, no settings change, and no observability schema change:

1. Update `ProductRecognitionShadowComparison` to declare
   `failure_category: str | None` and update its docstring.
2. Update `ProductRecognitionShadowService.compare` to pass
   `failure_category` through the constructor and drop the
   `object.__setattr__` mutation.
3. Update `ShadowMetricsRecorder.record` to read the category
   from the explicit field, drop the two helpers, and keep the
   `"unknown"` fallback.
4. Update the focused tests to use the constructor argument and
   the explicit field access.
5. Run the validation chain:
   - `python -m compileall backend`
   - `ruff check backend`
   - `mypy --strict backend/services`
   - `pytest` over the focused 4.10 tests plus the new 4.10.1
     tests.
   - `openspec validate clean-shadow-failure-reporting-4-10-1 --strict`

**Rollback strategy:** revert the change. Because no database
state, settings, or persistence schema is touched, the rollback
is a single `git revert` of the change.

## Open Questions

None. The preferred solution from project.md is unambiguous,
the field semantics match the existing sanitized literals,
and the recorder's `"unknown"` fallback is preserved.
