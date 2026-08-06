## Context

Subphase 4.11.5 closed the substantive recognition and calibration work for the Subphase 4.11 chain. The proposal establishes that the only remaining closure issue is six Ruff `C401` findings — `unnecessary-generator-set` — in two files within the contexts package. The findings exist because Ruff detects `set(<genexpr>)` constructs that can be more concisely expressed as a set comprehension, and it requires the rewrite purely on style grounds; the runtime semantics are byte-identical.

The relevant Ruff documentation ([`C401`](https://docs.astral.sh/ruff/rules/unnecessary-generator-set/)) classifies the rule as `UNSAFE` only in the rare case where the generator's iteration order matters. Here the values are immediately intersected with another `set` (returning a `set` whose ordering is undefined and irrelevant) and then sorted via `sorted(...)`. The intersection result type is `set[int]` and the surrounding `sorted(...)` call sorts the materialized list, so the order is fully determined by `sorted` — the iteration order of the generator is never observable. Therefore this is the standard `safe` case for which Ruff would normally issue a fix; the only reason `ruff check --fix` does not auto-apply the rewriting is that the rule is classified as `UNSAFE` in Ruff's default policy and `openspec/config.yaml` does not enable unsafe fixes (and this change respects that constraint by editing the lines explicitly).

The two affected files are:

- `backend/intents/context/order_line_selection_resolver.py` — `_resolve_order_line_selection` intersects the IDs returned by the `quitar_producto` recognizer with the active intent's `candidate_ids` to confirm that the user's "quitar X" message targets one of the pending lines.
- `backend/intents/context/product_modification_resolver.py` — `_resolve_source_selection` and `_resolve_destination_selection` intersect the recognized presentation IDs with the source / destination candidate sets during the two-phase "modificar X por Y" flow.

In both cases the intersection is the de-duplicated set of integer presentation IDs. Each rewritten expression preserves the `set[int]` type, the iteration semantics, the `&` operator semantics, and the `sorted(...)` ordering — the rewriting is purely cosmetic at the bytecode and source levels.

## Goals / Non-Goals

**Goals:**

- Eliminate all six Ruff `C401` findings that block closure of the Subphase 4.11 calibration chain.
- Preserve byte-identical runtime behaviour across both resolvers.
- Keep the source change to the smallest possible surface (6 lines total across 2 files).
- Allow the existing 193-test surface (Subphase 4.11 through 4.11.5) to remain green without modification.

**Non-Goals:**

- Refactoring the `sorted(...)` wrapper, the `&` operator, or the surrounding intersection logic.
- Introducing helper functions, named constants, or new abstractions.
- Changing variable names, function signatures, return types, or module exports.
- Touching unrelated files in `backend/intents/context/` or elsewhere in the resolver / orchestrator / recognizer / calibration surface.
- Disabling Ruff rule `C401` in `pyproject.toml` or `ruff.toml`.
- Introducing an opinion about whether `set(...)` calls or set comprehensions are preferred (the rewrite is purely to satisfy Ruff; both forms are equivalent).
- Running Ruff with `--unsafe-fixes` to auto-apply the rewrite (the change edits the lines explicitly per `openspec/config.yaml`).
- Updating `openspec/specs/project.md` (the placeholder entry stays pending until implementation and will be replaced as a post-`/opsx:archive` step, consistent with the Subphase 4.11.4 / 4.11.5 convention).
- Synchronizing any capability spec or archiving the change (per `openspec/config.yaml`, sync and archive are explicit user commands, not part of `/opsx:apply`).

## Decisions

### Decision 1: Rewrite `set(<genexpr>)` to `{<genexpr>}` directly in source

**Rationale.** Ruff's `C401` is the canonical "use a set comprehension" rule. The two forms are byte-equivalent at the AST level of the produced `set` instance — both constructs build a `set` by iterating the generator and adding each result to the freshly-constructed set. The downstream `sorted(...)` call uses `set` order as input but re-orders via the sort, so the iteration order is never observed. Therefore the rewrite is safe and minimal.

**Alternatives considered.**

- **`ruff check --fix --unsafe-fixes`** — would apply the rewriting automatically. Rejected because `openspec/config.yaml` and the AGENTS constraint forbid running unsafe fixes, and an explicit source edit keeps the change auditable.
- **Disable `C401` in `pyproject.toml`** — would silence the rule but defeat its purpose: Ruff would silently accept the same pattern in future code, and the codebase would carry a documented style debt. Rejected because disabling is a regression compared to fixing the actual pattern.
- **Extract a helper `_to_int_set(iterable)`** — would centralize the conversion but introduces an abstraction for a 1-line transformation used in exactly 3 places. Rejected for clarity and minimalism; the AGENTS rule "Do not anticipate future requirements or create unused abstractions" applies.
- **Convert to `frozenset`** — would change the type contract (`set[int]` → `frozenset[int]`), which is observable to callers and to the surrounding `&` / `sorted(...)` operations. Rejected to preserve behaviour exactly.

### Decision 2: Hand-edit the three intersection sites individually rather than bulk-editing

**Rationale.** The three sites are independent (different local variable names, different surrounding branches, different call sites downstream) and each site has a single, deterministic rewrite. Editing them individually keeps each diff line reviewable and avoids the risk of accidentally touching unrelated lines.

**Alternatives considered.**

- **`Edit` tool with `replaceAll` on a shared substring** — there is no shared substring across the three sites (each uses a different variable name), so `replaceAll` is not applicable.
- **Bulk `ruff --fix --unsafe-fixes` followed by a manual review** — would mix the safe fix into the same edit as the three unsafe fixes, requiring manual disentanglement. Rejected for clarity.

### Decision 3: Do not touch `product_recognizer.py`, `fuzzy_product_recognizer.py`, or any recognizer file

**Rationale.** The pre-flight `ruff check . --select C401` confirms that zero `C401` findings exist in any recognizer, calibration runner, shadow service, handler, or orchestrator file. The findings are concentrated exclusively in the two context resolvers. Touching a recognizer file would be out-of-scope and is not required.

**Alternatives considered.**

- **Re-scan for `set(...)` patterns across the codebase by hand** — already done as part of pre-flight; no other instances of the same pattern exist in the calibration-adjacent code paths. Rejected as a no-op.

### Decision 4: Do not modify the existing test files

**Rationale.** The existing 193 tests across `test_product_recognition_calibration_*.py`, `test_product_recognition_calibration_4_11_*.py`, `test_product_recognition_calibration_runner.py`, etc. already exercise both resolvers through the orchestrator and shadow flows. Because the rewrite is expression-equivalent, the existing tests pin the behaviour byte-for-byte: any regression would surface as a test failure, and any non-regression would leave the suite green. No new tests are needed.

**Alternatives considered.**

- **Add focused regression tests pinning the byte-identical equivalence between `set(int(cid) for cid in xs)` and `{int(cid) for cid in xs}`** — overkill for a stylistic-only closure; the existing test surface already pins the intersection result type and values. Rejected to avoid overtesting.

## Risks / Trade-offs

- **[Risk] The rewrite changes the source-level parentheses nesting** → Mitigation: the rewrite is purely syntactical; Ruff's `C401` rule (and `compileall` / `mypy --strict` / the existing test surface) all verify that the rewritten comprehension parses, type-checks, and produces the same `set[int]` runtime value. The change will be validated by running `ruff check --select C401` on the two files post-edit, by running `mypy --strict` on the two files post-edit, and by re-running the Subphase 4.11–4.11.5 suites green.
- **[Risk] A future contributor could confuse the rewritten comprehension with a structural refactor** → Mitigation: the surrounding `sorted(...)` wrapper and `&` intersection are unchanged; the comment in the proposal explicitly states the rewrite is expression-equivalent. The `git diff` is limited to 6 single-line character substitutions.
- **[Risk] The change could be (mis)classified as "noise" that hides real defects** → Mitigation: the proposal documents the exact 6 file+line pairs and the exact before/after syntax; the `ruff check` post-fix output diff (zero `C401` findings, zero new findings) is the proof that the change is complete and scoped. No issue-tracker entry is required because the placeholder entry in `openspec/specs/project.md` already documents the scope.
- **[Risk] Ruff's `UNSAFE` classification could mask an iteration-order-dependent case** → Mitigation: every rewritten comprehension is immediately intersected with another `set` (yielding another `set`) and the result is passed through `sorted(...)` (yielding a `list[int]` with sorted order). The iteration order of the generator is never observable in either the intersection result or the sorted list, so the rewrite is safe per Ruff's `safe` semantics.

## Migration Plan

This change has no deployment surface. The two resolver files are exercised only via the `agregar_producto` / `modificar_producto` / `quitar_producto` orchestration paths and the calibration / shadow services that wrap them. All paths converge on a `ProcessedIntent` whose contract is unchanged. Deployment is implicit: any commit that resolves these `C401` findings is automatically in production on the next deploy.

Rollback is a 6-line git revert with no data migration, no schema change, and no cache invalidation; the rollback re-introduces the six `C401` findings, which is the only operational risk, and the rollback is described in `git log` for auditability.

## Open Questions

(none — the rewrite is fully determined by the existing Ruff diagnostic; no design-time ambiguity remains.)
