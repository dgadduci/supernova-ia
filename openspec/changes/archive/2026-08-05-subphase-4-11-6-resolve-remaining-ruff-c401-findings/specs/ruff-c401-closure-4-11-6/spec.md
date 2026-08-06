## ADDED Requirements

### Requirement: Resolve all remaining Ruff `C401` findings in the context resolvers via set-comprehension rewriting

The `C401` (unnecessary-generator-set) findings reported by Ruff MUST be resolved by rewriting every `set(int(value) for value in iterable)` expression in the context resolvers to the equivalent set comprehension `{int(value) for value in iterable}`. The rewriting MUST be byte-identical at the intersection-result level: the produced value MUST be a `set[int]` with the same membership as the original expression and the same observable behaviour when intersected with another `set[int]` and passed through `sorted(...)`.

The two affected resolver files and the three affected intersection sites MUST each be rewritten:

- `backend/intents/context/order_line_selection_resolver.py` lines 125-126 — the intersection of `recognized_ids` with `active_intent.candidate_ids`.
- `backend/intents/context/product_modification_resolver.py` lines 160-161 — the intersection of `recognized_pp_ids` with `source_candidate_ids`.
- `backend/intents/context/product_modification_resolver.py` lines 220-221 — the intersection of `recognized_dest_ids` with `destination_candidate_ids`.

The rewriting MUST NOT alter the variable names, the function signatures, the surrounding branches, the `sorted(...)` wrapper, the `&` intersection operator, the return type, the recognised-set semantics, the empty-set semantics, the multi-candidate semantics, the single-candidate semantics, the orchestrator call sites, the persistence contracts, the HTTP contracts, the pending-context chain, the calibration runner, the recognizer mode, or any test signature. The rewriting MUST NOT introduce helper functions, named constants, new dependencies, or new abstractions. The rewriting MUST NOT disable Ruff rule `C401` or add any `noqa` comments. The rewriting MUST NOT use Ruff's `--unsafe-fixes`.

#### Scenario: All six Ruff `C401` findings are eliminated by the set-comprehension rewrite

- **WHEN** `PYTHONPATH=. venv/bin/python -m ruff check --select C401 backend/intents/context/order_line_selection_resolver.py backend/intents/context/product_modification_resolver.py` is run after the rewrite
- **THEN** Ruff MUST report zero `C401` findings across the two files
- **AND** no new Ruff findings MUST be introduced (e.g., from `E711`, `E712`, `F401`, `I001`, or any other rule)

#### Scenario: `order_line_selection_resolver` intersection is expression-equivalent to the pre-rewrite result

- **WHEN** `_resolve_order_line_selection` is called with a `quitar_producto` message that produces `recognized_ids` and an `active_intent` whose `candidate_ids` overlap with `recognized_ids`
- **THEN** the rewritten intersection `{int(cid) for cid in recognized_ids} & {int(cid) for cid in active_intent.candidate_ids}` MUST produce the same `set[int]` membership as the pre-rewrite `set(int(cid) for cid in recognized_ids) & set(int(cid) for cid in active_intent.candidate_ids)`
- **AND** the downstream `sorted(...)` call MUST produce the same sorted `list[int]` in the same order as the pre-rewrite invocation
- **AND** the `if not intersection`, `len(intersection) == 1`, and multi-candidate branches MUST each take the same path as the pre-rewrite invocation

#### Scenario: `product_modification_resolver` source intersection is expression-equivalent to the pre-rewrite result

- **WHEN** `_resolve_source_selection` is called with a `modificar_producto` message that produces `recognized_pp_ids` and a `source_candidate_ids` list that overlaps with `recognized_pp_ids`
- **THEN** the rewritten intersection `{int(x) for x in recognized_pp_ids} & {int(x) for x in source_candidate_ids}` MUST produce the same `set[int]` membership as the pre-rewrite generator-and-set form
- **AND** the `if not intersection: return active_intent.model_copy(update={"status": "rejected"})` early return MUST fire iff the pre-rewrite invocation also returned a rejected intent
- **AND** the `_build_ready_intent` / `_build_pending_intent` call sites MUST receive the same `intersection` list in the same order

#### Scenario: `product_modification_resolver` destination intersection is expression-equivalent to the pre-rewrite result

- **WHEN** `_resolve_destination_selection` is called with a `modificar_producto` message that produces `recognized_dest_ids` and a `destination_candidate_ids` list that overlaps with `recognized_dest_ids`
- **THEN** the rewritten intersection `{int(x) for x in recognized_dest_ids} & {int(x) for x in destination_candidate_ids}` MUST produce the same `set[int]` membership as the pre-rewrite generator-and-set form
- **AND** the `if not intersection: return active_intent.model_copy(update={"status": "rejected"})` early return MUST fire iff the pre-rewrite invocation also returned a rejected intent
- **AND** the `if len(intersection) == 1` branch and the fallback multi-candidate path MUST produce the same `ProcessedIntent` as the pre-rewrite invocation

#### Scenario: No behavioural regression in the Subphase 4.11-4.11.5 test suites

- **WHEN** `PYTHONPATH=. venv/bin/pytest backend/tests/test_product_recognition_calibration_4_11_5.py backend/tests/test_product_recognition_calibration_4_11_4.py backend/tests/test_product_recognition_calibration_runner.py backend/tests/test_product_recognition_calibration_dataset_4_11_1.py backend/tests/test_product_recognition_calibration_eligibility.py backend/tests/test_product_recognition_calibration_report.py backend/tests/test_product_recognition_calibration_policy.py backend/tests/test_product_recognition_calibration_cli.py backend/tests/test_product_recognition_calibration_4_11_3.py backend/tests/test_product_recognition_calibration_commerce_catalog.py backend/tests/test_product_recognition_calibration_inventory_4_11_4.py -vv` is run after the rewrite
- **THEN** the suite MUST remain 100% green (193 tests + 15 subtests pass) with zero failures, zero errors, and zero skips
- **AND** no test signature, no test fixture, no test parametrisation, and no test expectation MUST be modified to keep the suite green

## REMOVED Requirements

### Requirement: Pre-rewrite `set(int(value) for value in iterable)` pattern at the three intersection sites

**Reason:** The pre-rewrite pattern was flagged by Ruff's `C401` (unnecessary-generator-set) rule. The pattern rewrites to the equivalent set comprehension at every site; the rewriting is expression-equivalent and preserves the `set[int]` return type, so the pre-rewrite pattern is no longer present at the three intersection sites and is removed from the codebase.

**Migration:** None. The pre-rewrite pattern is replaced in-place by the set comprehension at all three sites; every consumer sees the same value, type, and ordering. The pattern remains valid Python outside Ruff's `C401` scope and may continue to appear in modules where Ruff is not configured (none such modules exist in this repo).
