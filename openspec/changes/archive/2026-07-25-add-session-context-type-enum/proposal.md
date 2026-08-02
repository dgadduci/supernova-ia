## Why

Phase 3 (Intents) has built up the conversation-wide state (`PendingIntents`, subphase 3.4) and the persistence surface (`PendingIntentService`, subphase 3.7). The system has no vocabulary for *what kind of resolution flow* a `Session` is currently in. Without a `ContextType` enum, the future dispatch path cannot decide which recognizer / processor / handler chain to invoke, the WhatsApp channel cannot route the user's reply to the right step, and the `Session` model has nowhere to record the current context. This subphase introduces a single `ContextType` enum as the smallest, narrowest declaration of the closed set of contexts the system supports.

## What Changes

- Add `backend/sessions/__init__.py` and `backend/sessions/enums/__init__.py` (empty package markers).
- Add `backend/sessions/enums/context_type.py` exporting a single `ContextType` enum (a `StrEnum`) and a `__all__`.
- `ContextType` declares exactly one value: `PRODUCT_SELECTION = "product_selection"`.
- Add one test entry to `backend/tests/api_smoke.py` covering: the enum value, string compatibility (e.g. `ContextType.PRODUCT_SELECTION == "product_selection"`), and rejection of an invalid value (constructing an enum member from a non-listed string raises `ValueError`).

## Capabilities

### New Capabilities

- `session-context-type-enum`: The closed set of `ContextType` values the system recognizes for a `Session`'s current resolution flow. Future subphases will add a `context_type` column to the `Session` model and route messages by context.

### Modified Capabilities

- None.

## Impact

- Adds `backend/sessions/__init__.py`, `backend/sessions/enums/__init__.py`, and `backend/sessions/enums/context_type.py`.
- Adds one test entry to `backend/tests/api_smoke.py`.
- No model, no migration, no router, no FastAPI endpoint, no service code, no other enum values, no business logic. The change is a single enum declaration.
- No new runtime dependencies — `enum.StrEnum` is in the standard library from Python 3.11 onward.