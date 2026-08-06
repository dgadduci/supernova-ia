## Design

### Decision 1: correct the alias source, not the filtering pipeline

The archived 4.11.2 evidence establishes that `picante` appears in product
identity and not in catalog presentation values. Removing its alias is the
minimal restoration: `_extraer_presentacion` no longer emits a false
presentation, so the existing filter does not discard `Empanada de Carne
Picante` with `presentacion_codigo == "unidad"`. No special-case or score
change is allowed.

### Decision 2: restore, do not expand, the mypy baseline

`matches_por_indice` stores `(str, float)` values. Its alias loop iterates
only over keys already present in the mapping, so it SHALL use direct indexed
access rather than the incompatible `(None, 0)` fallback. Together with
`dict[int, tuple[str, float]]`, this restores the 16-error baseline without
changing a score, candidate, or fallback outcome. The 16 errors recorded at
`openspec/changes/archive/2026-08-04-correct-presentation-alias-misclassification-4-11-2/tasks.md:35`
are explicitly outside scope.

### Decision 3: update the legacy mock at the shared-boundary seam

The resolver's keyword-only `intent_metadata` is additive and required for
the controlled-hybrid restricted-scope guard. The smoke test callback must
therefore declare `*, intent_metadata=None`, capture it, and assert the exact
restricted-scope dictionary. This pins the real call contract; it is not a
test-only bypass or a production behavior change.

### Validation commands

Run from the repository root:

```bash
PYTHONPATH=. venv/bin/pytest -q backend/tests/test_product_recognizer.py backend/tests/test_product_recognizer_contract.py backend/tests/test_product_recognizer_baseline.py backend/tests/test_product_recognizer_persisted_alias.py
PYTHONPATH=. venv/bin/pytest -q backend/tests/api_smoke.py
PYTHONPATH=. venv/bin/python -m mypy --strict backend/recognizers/product_recognizer.py
PYTHONPATH=. venv/bin/python -m ruff check backend/recognizers/product_recognizer.py backend/tests/api_smoke.py
PYTHONPATH=. venv/bin/python -m compileall backend/recognizers/product_recognizer.py backend/tests/api_smoke.py
openspec validate subphase-4-13-1-correct-phase-4-closure-regressions --strict
```

The first command must have zero failures. The smoke command may retain only
`test_llm_settings_and_query_llm`, `test_pending_context_execution`,
`test_pending_context_dispatcher`, and `test_agregar_producto_end_to_end`;
any other failure blocks this change. Mypy must show the historical 16 finding
inventory and no new error. The combined Ruff command is still executed: zero
findings in `product_recognizer.py` are required. Its current `api_smoke.py`
findings are known optional debt only when their code, count, and affected
file set do not materially increase; a new recognizer finding, a new affected
file, or a material increase blocks approval. `compileall` must pass. An
environment blocker is not a regression, but
all commands must run successfully in the supported local environment before
this change can be approved.

### Evidence recording rule

For every command above, `tasks.md` SHALL record the exact command and its
exit code. Pytest entries SHALL also record passed, failed, and subtest counts
and name every failing node. The mypy entry SHALL record its full finding
count and identify whether the only remaining errors are the archived 16
generic-type findings. The OpenSpec entry SHALL quote the strict validation
result. A bare checkbox, aggregate prose statement, or unverified claim is
not evidence and SHALL NOT complete the validation task.

### Observability and transaction ownership

No telemetry or transaction boundary changes. Existing resolver diagnostics
and hybrid scope propagation remain untouched; the smoke assertion is the
only added verification of the scope value. Recognizers continue not to own
commit or rollback.

### Scope attribution in a dirty worktree

The repository contains independently pre-existing Phase-4 changes. Review
SHALL therefore verify this correction by its allowed hunks, not infer
authorship from the full `main` diff. The only additional implementation hunk
authorized by this revision is replacement of the
`matches_por_indice.get(indice, (None, 0))` lookup with indexed access in the
existing alias-score loop. No removal, alteration, or attribution of other
dirty hunks is authorized here.
