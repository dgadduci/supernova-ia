## 1. Restore the restricted fallback

- [x] 1.1 Keep structured alias narrowing unchanged and do not change
  `PRESENTACION_ALIASES`.
- [x] 1.2 Add exact whole-word descriptor/code matching only in the existing
  zero-recognizer-result fallback, against `producto_nombre` and
  `presentacion_codigo` of the already passed catalog.
- [x] 1.3 Preserve the existing recognizer-result branches byte-for-byte in
  behavior, ordered active-ID intersection, diagnostics, quantity, and
  caller-owned transactions.

## 2. Restore required tests

- [x] 2.1 Restore the original six required `picante` assertions; do not
  weaken them to pending-resolution expectations.
- [x] 2.2 Cover exact code matching (`PICANTE`), product-name matching,
  quantity preservation, whole-word rejection of `picantes`, and foreign-ID
  rejection.
- [x] 2.3 Preserve current `la grande` structured-presentation coverage.

## 3. Validation and report

- [x] 3.1 Run every command in `design.md`, recording exact command, exit
  code, test totals, and failing nodes.
- [x] 3.2 Strict OpenSpec, Ruff, compileall, and `git diff --check` pass.
- [x] 3.3 Report scope and invariants. Do not sync, archive, commit, or run
  global 4.13 re-verification.

## Rejected execution record

The prior implementation attempt was rejected because it weakened required
Carne assertions and changed the authoritative recognizer-result branch. Its
validation claims are not acceptance evidence for this revised specification.

## Revised execution validation evidence

All commands below were run from the repository root. Every command exited
successfully; no failing pytest node IDs were observed.

### Command 1 — focused resolver pytest

Command (exact):
```
PYTHONPATH=. venv/bin/pytest -q backend/tests/test_product_selection_context_resolver.py
```
Exit code: `0`.
Stdout (exact):
```
................................                       [100%]
32 passed, 18 subtests passed in 0.21s
```
Failing node IDs: none.

### Command 2 — fuzzy recognizer pytest

Command (exact):
```
PYTHONPATH=. venv/bin/pytest -q backend/tests/test_product_recognizer.py backend/tests/test_product_recognizer_contract.py backend/tests/test_product_recognizer_baseline.py backend/tests/test_product_recognizer_persisted_alias.py
```
Exit code: `0`.
Stdout (exact):
```
........................ [ 80%]
......                                                                   [100%]
30 passed, 48 subtests passed in 0.13s
```
Failing node IDs: none.

### Command 3 — pending selection and ambiguity matrix

Command (exact):
```
PYTHONPATH=. venv/bin/pytest -q backend/tests/test_product_selection_context_resolver.py backend/tests/test_pending_product_ambiguity_resolution.py backend/tests/test_pending_product_ambiguity_resolution_e2e.py
```
Exit code: `0`.
Stdout (exact):
```
...................................................... [ 51%]
...................................................           [100%]
105 passed, 29 subtests passed in 1.51s
```
Failing node IDs: none.

### Command 4 — focused Ruff

Command (exact):
```
PYTHONPATH=. venv/bin/python -m ruff check backend/intents/context/product_selection_context_resolver.py backend/tests/test_product_selection_context_resolver.py backend/recognizers/product_recognizer.py
```
Exit code: `0`.
Stdout (exact):
```
All checks passed!
```
Findings: none.

### Command 5 — focused compileall

Command (exact):
```
PYTHONPATH=. venv/bin/python -m compileall backend/intents/context/product_selection_context_resolver.py backend/tests/test_product_selection_context_resolver.py
```
Exit code: `0`.
Stdout (exact):
```
Compiling 'backend/tests/test_product_selection_context_resolver.py'...
```

### Command 6 — strict OpenSpec validation

Command (exact):
```
openspec validate subphase-4-13-2-restore-pending-descriptor-narrowing --strict
```
Exit code: `0`.
Stdout (exact):
```
Change 'subphase-4-13-2-restore-pending-descriptor-narrowing' is valid
```

### Command 7 — diff whitespace check

Command (exact):
```
git diff --check
```
Exit code: `0`.
Stdout: empty; no whitespace errors.

## Scope and invariant confirmation

Implementation edits were limited to
`backend/intents/context/product_selection_context_resolver.py`,
`backend/tests/test_product_selection_context_resolver.py`, and this change's
`tasks.md`. The original six `picante` assertions remain readiness assertions;
the substring case isolates the zero-recognizer fallback with a mock so the
fuzzy recognizer's authoritative possible-result behavior is not reinterpreted.
`picante` remains absent from `PRESENTACION_ALIASES`; fuzzy recognition and its
four-key result semantics were not changed. Structured `_extraer_presentacion`
handling, including `la grande` and `grandi`, remains authoritative. The
fallback uses normalized whole-word membership across `producto_nombre` and
`presentacion_codigo`, preserves ordered active-ID intersection, quantity,
requirements, diagnostics, and caller-owned transactions, and does not reload
or widen the passed catalog. No changes were made to the recognizer,
hybrid/vector behavior, settings, migrations, endpoints, ambiguity resolver,
or unrelated files by this implementation. No sync, archive, commit, or global
4.13 matrix execution was performed.
