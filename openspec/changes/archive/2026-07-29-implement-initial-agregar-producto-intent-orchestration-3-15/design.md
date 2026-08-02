## Context

The project has separate components for commerce-scoped product catalog loading, product recognition, raw-result normalization, typed `ProcessedIntent` construction, context classification, and pending-context state updates. No component currently coordinates the initial `agregar_producto` message flow. The orchestrator must compose these existing functions without absorbing their logic or invoking the eventual order handler.

## Goals / Non-Goals

**Goals:**
- Provide one initial orchestration entry point with a stable typed return.
- Reuse the existing service, recognizer, resolver, processor, context-type resolver, and pending-context service.
- Persist only valid pending product-selection context.
- Leave ready intents and invalid pending results available to future handler/dispatch work.

**Non-Goals:**
- Executing `agregar_producto` or any order handler.
- Creating or modifying orders/order lines.
- Generating responses, calling routers, committing, or rolling back.
- Changing recognizer, resolver, processor, or context rules.

## Decisions

- Place the function in `backend/intents/orchestration/agregar_producto_orchestrator.py` because it coordinates multiple intent components and is not a service or repository.
- Use the existing product query service method that loads the commerce catalog; the orchestrator will not construct SQLAlchemy statements.
- Compose the pipeline in explicit order: catalog service → recognizer → product intent resolver → `process_agregar_producto` → context classification/persistence.
- Call `set_pending_intent` only after both the processor returns `pending_resolution` and `resolve_context_type` returns a non-null context. This prevents invalid pending state from being written.
- Return the exact `ProcessedIntent` produced by the processor for ready and non-persisted pending results; persistence is limited to the existing pending-context service mutation.

## Risks / Trade-offs

- [Risk] Existing product service APIs may expose catalog data in a different shape → Mitigation: inspect and reuse the established service method and add only a minimal adapter if required.
- [Risk] Persisting pending state before context validation could corrupt session state → Mitigation: classify first, then call `set_pending_intent` only for a valid context.
- [Risk] Future handler integration may expect orchestration to execute ready intents → Mitigation: explicitly keep ready intents unexecuted in this subphase and test that boundary.

## Migration Plan

1. Inspect existing component signatures and catalog service methods.
2. Implement the orchestration function using the existing pipeline.
3. Add unit and integration coverage for ready, pending, invalid, and side-effect cases.
4. Run the smoke suite and compilation check.
5. Roll back by removing the orchestrator and tests; existing components remain independently usable.

## Open Questions

None.
