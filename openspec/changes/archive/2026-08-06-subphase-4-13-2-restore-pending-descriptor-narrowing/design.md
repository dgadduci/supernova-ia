## Decision

Keep the existing structured alias path unchanged. When
`_extraer_presentacion(message)` returns `None`, derive a resolver-local
refinement token only if a normalized reply word exactly matches a whole word
in at least one row's `producto_nombre` **or** `presentacion_codigo` in the
already passed restricted catalog. Match that token against both fields using
whole-word membership. This fallback is reachable only after the real
recognizer returned neither `encontrados` nor product-level
`encontrados_posibles`.

This allows `picante` to select the active `PICANTE` row without classifying
it as a global presentation alias. The existing active-ID intersection remains
the only selection boundary.

## Authoritative outcomes

| Condition | Result |
| --- | --- |
| Recognizer returns products or product-level possible groups | Existing branch is authoritative and unchanged |
| No recognizer candidates; one active row has an exact descriptor word in name or code | `ready` via the existing unique-intent helper |
| No recognizer candidates; multiple active rows match | `pending_resolution` with only the ordered intersection |
| No exact match, substring-only match, or unrelated terms fail the guard | Active intent unchanged |
| Recognizer technical failure | Existing fuzzy fallback behavior, unchanged |

## Invariants

- `PRESENTACION_ALIASES` and fuzzy filtering remain unchanged.
- Exact whole-word membership rejects `picantes` for the token `picante`.
- The fallback never reads a catalog outside the passed projection and never
  selects outside `active_intent.candidate_ids`.
- The existing recognizer-result branches, diagnostics, quantity, requirements,
  and caller-owned transaction boundary remain unchanged.

## Validation

Run from repository root:

```bash
PYTHONPATH=. venv/bin/pytest -q backend/tests/test_product_selection_context_resolver.py
PYTHONPATH=. venv/bin/pytest -q backend/tests/test_product_recognizer.py backend/tests/test_product_recognizer_contract.py backend/tests/test_product_recognizer_baseline.py backend/tests/test_product_recognizer_persisted_alias.py
PYTHONPATH=. venv/bin/pytest -q backend/tests/test_product_selection_context_resolver.py backend/tests/test_pending_product_ambiguity_resolution.py backend/tests/test_pending_product_ambiguity_resolution_e2e.py
PYTHONPATH=. venv/bin/python -m ruff check backend/intents/context/product_selection_context_resolver.py backend/tests/test_product_selection_context_resolver.py backend/recognizers/product_recognizer.py
PYTHONPATH=. venv/bin/python -m compileall backend/intents/context/product_selection_context_resolver.py backend/tests/test_product_selection_context_resolver.py
openspec validate subphase-4-13-2-restore-pending-descriptor-narrowing --strict
git diff --check
```

All must succeed. Record exact commands, exit codes, test totals, and every
failure in `tasks.md`. Do not run the global closure matrix yet.
