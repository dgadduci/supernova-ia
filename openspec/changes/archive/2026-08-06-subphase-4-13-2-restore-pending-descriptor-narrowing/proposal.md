## Why

4.13.1 correctly removed `picante` from `PRESENTACION_ALIASES`: it is not a
global fuzzy-presentation signal. The required pending-selection matrix then
found six failures. In a persisted candidate set for `Empanada de Carne`, the
catalog represents the variants as the exact codes `PICANTE` and
`TRADICIONAL`; the resolver can no longer use the reply `picante` because its
only code-narrowing token comes from `_extraer_presentacion()`.

The resolver needs a separate, deterministic refinement rule for an exact
descriptor/code word inside its already restricted candidate catalog. This is
not a fuzzy alias and must not alter fuzzy recognition.

## Current execution path

`resolve_product_selection()` first delegates to the real recognizer with the
persisted restricted catalog. Its result remains authoritative. Only when it
returns no product candidates does `_narrow_by_presentacion_alias()` run.
That helper currently obtains the sole code token from
`_extraer_presentacion(message)`, which returns `None` for `picante` after
4.13.1. It therefore cannot distinguish `PICANTE` from `TRADICIONAL` in the
active set, despite the reply exactly naming the first code.

## Scope

- In `backend/intents/context/product_selection_context_resolver.py`, add a
  deterministic fallback refinement used only after zero recognizer results:
  an exact normalized reply word may match either a whole word in
  `producto_nombre` or a whole word in `presentacion_codigo` of rows already
  passed to the resolver.
- Keep `_extraer_presentacion()` as the sole authority for normal structured
  presentation aliases and canonical variants (`grandi -> grande`).
- Keep the existing recognizer-result (`encontrados` / `encontrados_posibles`)
  branches byte-for-byte in behavior; do not filter or reinterpret their
  candidates.
- Restore the six existing required resolver assertions rather than weakening
  them. Add only focused tests required for exact whole-word and scope
  protection.
- Update only this change's OpenSpec artifacts and its spec delta.

## Non-goals

- Do not restore or add `"picante": "picante"` to `PRESENTACION_ALIASES`.
- Do not modify `backend/recognizers/product_recognizer.py`, fuzzy scoring,
  output semantics, aliases, hybrid/vector behavior, factories, settings,
  endpoints, migrations, or transactions.
- Do not add a parallel recognizer, query/reload/widen the catalog, change the
  pending ambiguity resolver, or clean unrelated debt.
- Do not sync, archive, commit, or close Phase 4.

## Acceptance criteria

1. The original six resolver regressions again pass: replies `picante`, `la
   picante`, and `carne picante` uniquely resolve the `PICANTE` candidate in
   the restricted Carne catalog; quantity is preserved.
2. Exact `picante` narrows a `producto_nombre` discriminator when present and
   also an exact `presentacion_codigo` discriminator in the restricted set.
3. `picantes` does not match `PICANTE` or a product-name `picante` token.
4. `picante` remains absent from `PRESENTACION_ALIASES`; no fuzzy candidate is
   filtered using it as a presentation.
5. Existing recognizer-result branches remain unchanged, `la grande` retains
   its structured-alias behavior, and no row outside `candidate_ids` can be
   selected.
6. All focused checks in `design.md` pass. Global 4.13 re-verification waits
   for implementation review.

## Reversibility

No database or external state changes. Reverting the local resolver fallback
restores the prior unresolved behavior.
