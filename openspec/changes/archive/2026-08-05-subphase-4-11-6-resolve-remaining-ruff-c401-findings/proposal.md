## Why

Subphase 4.11.5 is functionally complete and its focused and regression test suites are green:

- 46 tests and 15 subtests passed for `test_product_recognition_calibration_4_11_5.py`.
- 147 tests passed across the existing Subphase 4.11–4.11.4 calibration suites.

The remaining closure issue is a stylistic-only one: six Ruff `C401` findings (`unnecessary-generator-set`) in two files. Each finding is caused by wrapping a generator expression with `set(...)` instead of using the equivalent set comprehension. The runtime semantics are byte-identical — this is a mechanical code-style correction, not a behavioural or architectural change.

## What Changes

Update only these files:

- `backend/intents/context/order_line_selection_resolver.py`
- `backend/intents/context/product_modification_resolver.py`

Replace each pattern of the form

```python
set(int(value) for value in iterable)
```

with

```python
{int(value) for value in iterable}
```

The three affected intersection expressions are:

1. `recognized_ids` ∩ `active_intent.candidate_ids` (`order_line_selection_resolver.py:125-126`).
2. `recognized_pp_ids` ∩ `source_candidate_ids` (`product_modification_resolver.py:160-161`).
3. `recognized_dest_ids` ∩ `destination_candidate_ids` (`product_modification_resolver.py:220-221`).

This resolves all six reported `C401` findings.

## Capabilities

### New Capabilities

- `ruff-c401-closure-4-11-6`: a single-purpose closure capability pinning the rewrite mechanism (every `set(int(value) for value in iterable)` in the context resolvers is rewritten to `{int(value) for value in iterable}` with byte-identical intersection semantics) and the closure criterion (zero `C401` findings remain across the two resolver files after the rewrite, and the existing 193-test Subphase 4.11–4.11.5 surface remains green without modification). This capability exists solely to satisfy the `spec-driven` schema's `specs` artifact and does not introduce a reusable runtime capability — there is no new runtime feature, no new module surface, no new contract, and no new HTTP / persistence / orchestrator surface.

### Modified Capabilities

(none — no requirement-level behaviour is changing. The intersection semantics, the sorting, the type of the returned values, and every surrounding line are preserved. Ruff `C401` is a code-style rule, not a behavioural contract, so no existing capability requirement is added or modified.)

## Impact

- `backend/intents/context/order_line_selection_resolver.py` — replace `set(int(cid) for cid in recognized_ids)` with `{int(cid) for cid in recognized_ids}` at line 125 and `set(int(cid) for cid in active_intent.candidate_ids)` with `{int(cid) for cid in active_intent.candidate_ids}` at line 126 (2 lines touched; same expression semantics; the surrounding `sorted(...)` call, the `&` intersection, and the downstream `if not intersection` / `len(intersection) == 1` branches are unchanged).
- `backend/intents/context/product_modification_resolver.py` — apply the same rewriting at lines 160-161 (`recognized_pp_ids` ∩ `source_candidate_ids`) and 220-221 (`recognized_dest_ids` ∩ `destination_candidate_ids`) (4 lines touched; same expression semantics; the surrounding `sorted(...)` call, the `&` intersection, the early-return `if not intersection` branches, the `_build_ready_intent` / `_build_pending_intent` call sites, and the resolver entry points (`_resolve_source_selection`, `_resolve_destination_selection`) are unchanged).
- Test surface: no test additions or modifications are required. The rewriting is expression-equivalent: `set(g for x in xs)` and `{g for x in xs}` produce the same `set` instance, the same iteration order semantics, and the same `frozenset`-equivalent equality. All 193 tests across the Subphase 4.11–4.11.5 suites continue to apply unchanged.
- Ruff `pyproject.toml` / config: unchanged. `C401` is enabled by the default selection; this change brings the existing code into compliance rather than disabling the rule.
- No `pyproject.toml` change, no `ruff.toml` change, no `[tool.ruff.lint]` change, no `ignore = [...]` change, no per-file-ignore change.
- No runtime behaviour change. No test signature change. No fixture change. No migration change. No documentation change. No OpenSpec spec change.
- No new dependency. No Python-version bump. No typing-change (the result of `{int(cid) for cid in ...}` is `set[int]`, identical to `set(int(cid) for cid in ...)`; `mypy --strict` remains clean on both files).
- The change is non-breaking for every reader of the two files, every resolver entry point, every orchestrator, every handler, every persistence contract, the HTTP contract, the pending-context chain, and the calibration runner. The intersection semantics, the type contract, the sort order, the empty-set semantics, the multi-candidate semantics, and the single-candidate semantics are all preserved.
