## Context

`ProductIntentResolver` transforms the current recognizer dictionary into the stable four-key structure consumed by later intent processing. The resolver implementation still uses legacy keys (`id`, `source_text`) while `ProductRecognizer` now emits `producto_presentacion_id` and `texto_origen`. The correction is localized to the resolver and its verification tests; the recognizer contract and downstream output shape remain fixed.

## Goals / Non-Goals

**Goals:**
- Align confident and possible result handling with the recognizer's current identifiers.
- Preserve quantity and ordered message lists.
- Prove legacy `id` is not required.

**Non-Goals:**
- Changing fuzzy matching or recognizer output.
- Changing the resolver's four-key output shape.
- Adding persistence, handlers, contracts, APIs, or dependencies.

## Decisions

- Use `producto_presentacion_id` as the sole candidate identifier because it is the recognizer's current stable identifier and is also used by the context resolver.
- Use `texto_origen` for unavailable and not-found messages because it is the recognizer's current source-text field.
- Keep direct key access for required fields so malformed contracts fail visibly rather than silently falling back to legacy behavior; tests will enforce the current contract.
- Add focused checks to the existing smoke test entry point, matching the repository's current verification convention.

## Risks / Trade-offs

- [Risk] Older callers may still provide `id` or `source_text` → Mitigation: intentionally remove legacy dependency and validate the current recognizer-to-resolver contract; migration belongs to callers.
- [Risk] Existing tests may encode the old field names → Mitigation: update only resolver-specific fixtures to current recognizer output fields.

## Migration Plan

1. Update resolver field access.
2. Update and extend resolver tests.
3. Run the relevant smoke suite and Python compilation check.
4. Roll back by reverting the resolver and test changes if the current contract is not yet available to all callers.

## Open Questions

None.
