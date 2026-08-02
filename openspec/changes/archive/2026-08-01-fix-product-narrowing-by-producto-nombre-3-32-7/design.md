## Context

`ProductSelectionContextResolver.resolve_product_selection` calls `_narrow_by_presentacion_alias` when `detectar_productos` returns no hits. Today that helper matches the extracted alias only against `presentacion_codigo` (`backend/intents/context/product_selection_context_resolver.py:108-110`). When the alias is `picante` or `tradicional` — keys whose target value lives in `producto_nombre` (e.g. "Empanada de Carne Picante") rather than `presentacion_codigo` ("UNIDAD") — the loop produces an empty `matching_ids`, the intersection is empty, and the helper returns `None`, so the resolver returns the unchanged `active_intent`. The 3.32.5 extraneous-token guard fixes the *guard* branch but does not change the match predicate, so the message still does not narrow.

The minimal fix is additive: extend the per-candidate match so it accepts a hit when the alias token (the canonical form returned by `_extraer_presentacion`) appears as a whole word in the candidate's `producto_nombre`. The presentacion_codigo path stays exactly as it is, the alias table is not extended, the threshold/tuning knobs are untouched, and the 3.32.4 drain-and-promote loop is untouched.

## Goals / Non-Goals

**Goals:**
- Allow product-level aliases (`picante`, `tradicional`) to narrow the active intent's `candidate_ids` to a single entry when the catalog carries the discriminator in `producto_nombre`.
- Preserve quantity, `resolved_data`, and `requirements` exactly as `_build_resolved_unique_intent` does today.
- Keep the existing `presentacion_codigo` match path unchanged (size aliases like `grande`, `chica`, `familiar` keep working).
- Keep the 3.32.5 extraneous-token guard active for tokens unrelated to the active intent's `source_text` or `resolved_data`.
- Keep the diagnostic surface from 3.32.6 unchanged: the existing `RESOLVER CANDIDATES` table now shows why the narrowing landed.

**Non-Goals:**
- No new alias entries in `PRESENTACION_ALIASES`.
- No change to `detectar_productos`, no new recognizer code path, no change to `_extraer_presentacion`.
- No change to classifier behavior, prompts, intent ordering, or transaction ownership.
- No change to the `modificar_producto` path, the `quitar_producto` path, or the pending queue mechanics.
- No new diagnostic fields, no new CLI flags, no new HTTP headers.
- No new dependencies, no new threshold.

## Decisions

- **Match predicate is a union, not a replacement.** Each candidate is considered a match if either `_presentacion_matches(codigo, alias)` (existing path) **or** the alias token appears as a whole word (case-insensitive) in `producto_nombre`. The whole-word check uses the same `_normalizar_texto` normalization as the rest of the recognizer, then splits on whitespace and tests membership — exactly the style of the existing `_presentacion_matches` "split" branch. This keeps the existing size-alias path byte-for-byte equivalent and only widens the set when the alias is product-level.
- **Use the canonical alias returned by `_extraer_presentacion`, not the raw input token.** `_extraer_presentacion` already normalizes the variant (`grandi` → `grande`, `fami` → `familiar`, etc.), so testing against the canonical form keeps `grandi` working and avoids re-implementing alias normalization in the resolver. This is the same value that the existing `presentacion_codigo` path already uses, so the two branches stay consistent.
- **Preserve the intersection step verbatim.** The existing `intersection = [cid for cid in active_intent.candidate_ids if cid in matching_ids]` is the single point that filters against the active intent's persisted candidate catalog. We do not bypass it. The whole fix is "produce a larger `matching_ids` set" — the narrowing decision logic is unchanged.
- **Keep status transitions driven by `_build_resolved_unique_intent`.** The same helper used by the existing presentacion_codigo path is the one that flips `producto_presentacion_id` to `completed` and recomputes the status (`ready` when all requirements are completed, `pending_resolution` otherwise). The 3.32.4 queue promotion and exactly-once handler sequencing consume that result unchanged.
- **Reject substring-of-name matches.** A bare substring check would let `picante` match a product name that happens to contain the letters `picante` mid-word. The whole-word check via `_normalizar_texto(...).split()` membership eliminates that risk and keeps the predicate symmetric with the existing `presentacion_codigo` "split" branch.
- **Do not extend `PRESENTACION_ALIASES`.** `picante` and `tradicional` are already in the table; they just weren't reachable from this code path. Adding new keys would be a separate change.

## Risks / Trade-offs

- **[Risk] A product name that contains the alias token in a non-discriminating position (e.g. "Empanada Picante de Pollo") could now be auto-selected against an active intent that is "1 empanada de carne".** → Mitigation: the existing `intersection` step filters against `active_intent.candidate_ids`, so the resolver only narrows within the active intent's persisted catalog. A pizza-active intent cannot be hijacked by `picante` because the active candidate set does not contain a Carne Picante candidate. The 3.32.5 extraneous-token guard still fires for `pollo` (it is not in the active intent's source_text or resolved_data) and would block the narrowing for that active intent.
- **[Risk] Accent/case variants in the candidate's `producto_nombre`.** → Mitigation: apply the same `_normalizar_texto` pipeline used everywhere else in the recognizer, which lower-cases, strips diacritics, and collapses punctuation.
- **[Risk] A future catalog row with `producto_nombre` containing two distinct alias tokens (e.g. "Empanada Picante Tradicional") could be ambiguous.** → Mitigation: the resolver returns `active_intent` unchanged when the intersection is empty, and narrows to a copy with the reduced `candidate_ids` when the intersection is multi-element. The customer is asked to clarify only when the reduced set still has more than one element, which is the same behavior as the existing path.
- **[Trade-off] The candidate set used here is the one already passed to the resolver** (the active intent's catalog projection). The fix does not introduce any new query.

## Migration Plan

- No data migration. No database column change. No Alembic revision.
- Deploy path: ship the change behind the same FastAPI process; the existing tests exercise the new path and the existing tests continue to pass because the presentacion_codigo branch is unchanged.
- Rollback: revert the single loop in `_narrow_by_presentacion_alias`; the previous behavior is restored.
- No feature flag, no rollout step, no DB backfill.
