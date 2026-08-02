## Context

Phase 3 (Intents) is layering up from leaves toward the runtime center. Subphase 3.1 introduced the static contract (the "what" of an intent), and subphase 3.2 introduced the per-requirement state object (the "how one slot looks" once a recognizer has run). The next layer is the *envelope* — the value object that ties together one intent's intent-name, source text, recognizer/handler attribution, the resolved data slots, the per-requirement states, and a list of candidate identifiers for ambiguous cases. The future recognizer will produce one of these; the future handler will consume one. Subphase 3.3 introduces only the schema; no recognizer, no handler, no registry, no processor.

## Goals / Non-Goals

**Goals:**

- Create a single Python file under `backend/intents/schemas/` exporting `IntentStatus` and `ProcessedIntent`.
- `IntentStatus` is a `typing.Literal["pending_resolution", "ready", "executed", "rejected", "failed"]` — a five-state lifecycle.
- `ProcessedIntent` is a Pydantic `BaseModel` with eight fields: `intent`, `source_text`, `status`, `recognizer` (nullable), `handler`, `resolved_data`, `requirements`, and `candidate_ids`.
- Default factories are used for the three collection fields so each instance gets its own empty `dict` / `list`.
- The file is importable: `from backend.intents.schemas.processed_intent import ProcessedIntent, IntentStatus` works without side effects.
- One test asserts valid creation, default empty collections, nested `RequirementState` validation, and rejection of an invalid `status`.

**Non-Goals:**

- No methods, no validators beyond the type checks Pydantic provides by default, no `model_config`.
- No other intent contracts, no recognizer, no handler, no processor, no registry, no DB model, no migration, no FastAPI endpoint.
- No introduction of `enum.Enum` — the spec mandates `Literal`, consistent with subphase 3.2.

## Decisions

- **D1 — `IntentStatus` is `Literal`, not `Enum`.** Consistent with `RequirementStatus` in subphase 3.2. Pydantic renders it as `enum` in OpenAPI; runtime validation is a closed string set. Promoting to `Enum` is out of scope.
- **D2 — `recognizer` is `str | None = None`.** The recognizer is determined at runtime by the dispatch path, and not every flow runs through a recognizer (e.g. a programmatic test or a future manual override). `None` means "no recognizer was involved" or "not yet determined". The `handler` is non-nullable because every intent has a handler (a `None` handler would be a configuration error).
- **D3 — `resolved_data` is `dict[str, Any]`, not a `BaseModel`.** The slot values come from heterogeneous requirements and are not statically known. A future subphase may introduce typed slot schemas per intent; that is out of scope here. `Any` lets the recognizer populate any JSON-compatible value per slot.
- **D4 — `requirements` is `list[RequirementState]`, not a `dict` keyed by name.** The order of requirements carries semantic information (the recognizer may produce them in resolution order). A list preserves that. A future subphase may add an indexed lookup helper if needed.
- **D5 — `candidate_ids` is `list[int]`, not `list[str]`.** Future candidate ids will reference `comercios.id` / `productos.id` / etc., all `int`. The future recognizer will populate this when the LLM returns a short list of plausible matches; the handler will use it to disambiguate. `list[str]` would force casts downstream.
- **D6 — Default factories on every collection field.** Pydantic requires `default_factory` (not `default`) when the default is a mutable container. Three collection fields use it: `resolved_data`, `requirements`, `candidate_ids`. Without this, every instance would share the same default `dict`/`list` and mutations would leak across instances.
- **D7 — Field order matches the spec.** The spec lists the eight fields in order; the implementation uses the same order. The order is not semantically significant but a deterministic order makes `model_dump()` and `repr` stable.
- **D8 — File layout is consistent with subphase 3.2.** The same `backend/intents/schemas/` package. The package's `__init__.py` (from subphase 3.2) is sufficient; no new package marker is needed. `__all__` is declared to make the public surface explicit.

## Risks / Trade-offs

- **[Risk] `dict[str, Any]` for `resolved_data` is not type-safe.** → Acceptable for the active subphase: the spec mandates `dict[str, Any]`. A future subphase can introduce a per-intent typed schema (e.g. `AgregarProductoData(BaseModel)`) and a discriminator.
- **[Risk] `list[RequirementState]` shares the same `Any`-typed `value` field as the parent `ProcessedIntent`.** → Acceptable: the per-slot value type guard, if any, is a future concern. The active subphase keeps the runtime shape uniform.
- **[Trade-off] No discriminators between intent types.** → Matches the spec. The `intent: str` field is the only discriminator today; a future subphase can introduce a `Union[IntentA, IntentB, ...]` once concrete intent schemas exist.

## Open Questions

- None. The schema fields, types, defaults, and the "do not add business logic or other schemas" rule are all fixed by Subphase 3.3 in `project.md`.