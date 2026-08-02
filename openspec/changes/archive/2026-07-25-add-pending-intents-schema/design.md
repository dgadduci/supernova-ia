## Context

Phase 3 (Intents) is layering up from the static contract (3.1) to per-requirement state (3.2), to the per-intent envelope (3.3). The next layer is the *conversation-wide* state — what the WhatsApp channel needs to track when a user is in the middle of a multi-intent flow. A user may be inside an `agregar_producto` resolution (the `active` intent), with other `agregar_producto` invocations queued behind it. The system also needs a JSON-round-trippable representation so a future subphase can persist the state on the `Session` row and resume the conversation after an interruption (e.g. a network blip, a worker restart). Subphase 3.4 introduces only the schema; no recognizer, no handler, no registry, no persistence.

## Goals / Non-Goals

**Goals:**

- Create a single Python file under `backend/intents/schemas/` exporting `PendingIntents` and a `__all__`.
- `PendingIntents` is a Pydantic `BaseModel` with three fields: `version: int = 1`, `active: ProcessedIntent | None = None`, and `queue: list[ProcessedIntent] = Field(default_factory=list)`.
- The schema is JSON-round-trippable: `model_dump(mode="json")` followed by `model_validate(...)` reconstructs an equivalent instance.
- The file is importable: `from backend.intents.schemas.pending_intents import PendingIntents` works without side effects.
- One test asserts default creation, creation with an active and queued intents, nested `ProcessedIntent` validation, and the JSON round-trip.

**Non-Goals:**

- No methods, no validators beyond the type checks Pydantic provides by default, no `model_config`.
- No other intent contracts, no recognizer, no handler, no processor, no registry, no DB model, no migration, no FastAPI endpoint, no persistence of the state to a `Session` row — that lands in a future subphase.
- No new `version` validation logic (e.g. refusing to load older `version` values); the field is declared but not enforced.

## Decisions

- **D1 — `version: int = 1` is a forward-compatibility hook.** The spec mandates it. The current subphase does not enforce any version-checking logic; a future subphase may add a `model_validator` that rejects unknown versions, refuses to downgrade, or migrates old shapes forward. Today the field exists so persisted blobs already carry a version tag from day one.
- **D2 — `active: ProcessedIntent | None = None` reflects the natural conversation state.** Between user messages the channel has no active intent (None). When the user speaks and the recognizer runs, the recognizer produces a `ProcessedIntent` and the runtime sets `active = produced`. When the handler finishes (status → `executed` or `rejected`), the runtime clears `active` to `None` and promotes the head of `queue` (if any). The active subphase declares the shape; the lifecycle lands in a future subphase.
- **D3 — `queue: list[ProcessedIntent]` (not `dict`) preserves arrival order.** Order matters: a recognizer that produces multiple plausible intents in one message will queue them in confidence order. The future handler drains the queue head-first.
- **D4 — `Field(default_factory=list)` on `queue` is mandatory.** Same rationale as subphase 3.3: a mutable default shared across instances is a classic Python footgun. `Field(default_factory=list)` gives each instance its own list.
- **D5 — `version` is required to be a JSON integer (not `Literal[1]`).** A future subphase may set `version = 2` after a migration. The current default is `1`; the test pins it.
- **D6 — File layout is consistent with subphases 3.2 and 3.3.** The same `backend/intents/schemas/` package. The package's `__init__.py` is sufficient; no new package marker is needed. `__all__` is declared.
- **D7 — JSON round-trip via `model_dump(mode="json")` and `model_validate()`.** The spec mandates this exact pair. `mode="json"` coerces non-JSON-native types (`Decimal`, `datetime`) to their JSON representation; `model_validate` re-parses the dict into a typed instance. The test asserts that the round-tripped instance is equivalent (not necessarily `is` identical) to the original.

## Risks / Trade-offs

- **[Risk] `version` is not enforced.** → Acceptable for the active subphase: the spec only declares the field. A future subphase can add a `model_validator(mode="after")` that raises on `version > 1` until a migration is shipped.
- **[Risk] JSON round-trip may not preserve equality of nested `Any` values.** → Acceptable: the test asserts structural equivalence (same intent name, same status, same nested list of `RequirementState` values). Strict identity of every `Any` value is a future concern.
- **[Trade-off] No persistence yet.** → Matches the spec. The state lives in memory; a future subphase will serialize it to a `Session` metadata column (likely a JSONB or a `Text` blob).

## Open Questions

- None. The schema fields, types, defaults, and the JSON round-trip requirement are all fixed by Subphase 3.4 in `project.md`.