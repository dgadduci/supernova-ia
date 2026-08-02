## Context

Phase 3 (Intents) is layering up the dispatch and resolution path. Subphase 3.3 introduced the `ProcessedIntent` envelope. Subphase 3.5 introduced the `ProductIntentResolver` (recognizer output → normalized data). Subphase 3.6 introduced the `IntentProcessor` (normalized data → `ProcessedIntent`). Subphase 3.7 introduced the `PendingIntentService` (per-`Session` state machine). Subphase 3.8 introduced the `ContextType` enum. The next layer is the *classifier* that maps a `ProcessedIntent` to a `ContextType`. The future dispatch path will use this on the active intent in a `PendingIntents` state to decide which recognizer / processor / handler chain to invoke next. The active subphase introduces only that classifier — no recognizer, no processor, no handler, no persistence, no DB, no router.

## Goals / Non-Goals

**Goals:**

- Create `backend/intents/context/context_type_resolver.py` exporting one function `resolve_context_type(intent: ProcessedIntent) -> ContextType | None` and a `__all__`.
- The function returns `ContextType.PRODUCT_SELECTION` only when **all three** conditions hold:
  1. `intent.status == "pending_resolution"`
  2. requirement `producto_presentacion_id` exists with `status == "pending"`
  3. `intent.candidate_ids` is non-empty
- Every other case returns `None`.
- The function is **pure**: no I/O, no DB, no recognizer call, no handler invocation, no session mutation, no persistence.
- The file is importable without side effects.
- One test asserts each of the four scenarios: pending product selection returns `PRODUCT_SELECTION`; missing candidates returns `None`; non-pending intent returns `None`; unrelated pending requirement returns `None`.

**Non-Goals:**

- No model, no migration, no router, no FastAPI endpoint, no service class, no recognizer, no handler, no persistence, no logging, no I/O.
- No additional `ContextType` values (the `ContextType` enum is fixed at one value, per subphase 3.8; future subphases will add values to the same enum, not to this resolver).
- No modifications to `PendingIntents` state, no calls to `PendingIntentService`.
- No "intent dispatcher" or "next step" machinery. The active subphase introduces only the pure classifier.

## Decisions

- **D1 — Function returns `ContextType | None`, not a `ContextType`.** Today there is one value in the enum (`PRODUCT_SELECTION`) and one rule that produces it. A future subphase may add a new value (e.g. `CART_REVIEW`) and a new rule; the signature `ContextType | None` accommodates that. The `None` return means "no specific context — fall through to the default dispatch path".
- **D2 — The rule is the AND of three conditions, not OR.** The spec is explicit: "only when" means all three. Any one missing → `None`. The rule captures the precise state: the user has spoken an intent that the recognizer could not finalize (multiple plausible products) and the system is waiting for the user to disambiguate.
- **D3 — `producto_presentacion_id` is the requirement name, not a positional index.** The function looks up the requirement by `name`. If the future contract adds more requirements, the function ignores them. If the future contract renames `producto_presentacion_id`, the function returns `None` for every intent that no longer has a `producto_presentacion_id` requirement — graceful degradation.
- **D4 — `candidate_ids` non-emptiness is checked via truthiness, not `len()`.** A list is falsy iff it is empty. `if intent.candidate_ids:` is the natural Python form and matches the project's existing patterns.
- **D5 — The function is a single expression** (no I/O, no state). It is a `def`, not a `@staticmethod` or `@classmethod`, because the function does not depend on any class state. Mirrors the `ProductIntentResolver` and `IntentProcessor` patterns.
- **D6 — `__all__ = ["resolve_context_type"]`.** One public symbol. Mirrors the prior subphases' `__all__` discipline.
- **D7 — File location: `backend/intents/context/context_type_resolver.py`.** The spec mandates the path. The `backend/intents/context/` package is the new home for intent classification and dispatch concerns. Future resolvers (e.g. `cart_review_resolver.py`) slot in alongside.
- **D8 — No external side effects.** The function does not call `print`, does not log, does not mutate the input, does not raise on unexpected input. It returns `None` when the conditions are not met.

## Risks / Trade-offs

- **[Risk] The function only handles one of N possible `ContextType` values.** → Acceptable for the active subphase: there is exactly one value today. Future subphases will add values to the enum and rules to the resolver; the `ContextType | None` return type accommodates that.
- **[Trade-off] The resolver inspects the `ProcessedIntent` shape directly, not the underlying `pending_intents` state.** → Acceptable: the active subphase introduces only the per-intent classifier. The future dispatch path will iterate `pending_intents.queue` (or `pending_intents.active`) and call this function per intent. The active subphase does not own that wiring.
- **[Trade-off] `status` and requirement `status` are compared as plain strings, not as `IntentStatus` / `RequirementStatus` enum members.** → The Pydantic models type the fields as `Literal` (e.g. `IntentStatus = Literal["pending_resolution", ...]`); comparing against the literal string is the natural form and matches the spec text ("`intent.status == \"pending_resolution\"`").

## Open Questions

- None. The function signature, the rule (AND of three conditions), the return type, the file location, and the "no side effects" constraint are all fixed by Subphase 3.9 in `project.md`.