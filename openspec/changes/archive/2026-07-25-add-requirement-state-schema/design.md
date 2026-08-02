## Context

The static contract introduced in subphase 3.1 declares requirements as `{required, default}` entries in a `dict`. A future subphase will introduce a recognizer that produces per-requirement values and a handler that consumes them. Between those two halves, the system needs a typed value object: a single class that represents "the state of one requirement at one moment" — its name, whether it is pending or completed, and the value the recognizer has produced for it. This subphase introduces only that value object. No recognizer, no handler, no registry, no dispatch — those land in their own subphases.

## Goals / Non-Goals

**Goals:**

- Create a single Python file under `backend/intents/schemas/` exporting `RequirementStatus` and `RequirementState`.
- `RequirementStatus` is a `typing.Literal["pending", "completed"]` type alias — the smallest typed representation of the status enum.
- `RequirementState` is a Pydantic `BaseModel` with three fields: `name: str`, `status: RequirementStatus`, `value: Any | None = None`.
- The file is importable: `from backend.intents.schemas.requirement_state import RequirementState, RequirementStatus` works without side effects.
- One test asserts valid creation, default `value=None`, and rejection of an invalid status.

**Non-Goals:**

- No other schemas, no business logic, no methods, no validators beyond the type checks Pydantic provides by default.
- No registry, no recognizer, no handler, no processor, no DB model, no migration, no FastAPI endpoint.
- No other intent contracts beyond what subphase 3.1 introduced.
- No introduction of `enum.Enum` — the spec mandates `Literal`, which gives Pydantic-native validation without the runtime cost of an Enum class.

## Decisions

- **D1 — `RequirementStatus` is `Literal["pending", "completed"]`, not `enum.Enum`.** The spec mandates this exact form. Pydantic renders `Literal` types as `enum` in the OpenAPI schema when used in a `BaseModel`, so JSON consumers see the same wire contract; inside Python, `Literal` is the cheapest way to encode a closed string set. A future subphase may promote it to `enum.Enum` if `is`-checks or iteration become useful.
- **D2 — `value` is `Any | None = None`.** The spec mandates this exact annotation. `Any` (not `object`, not a union of specific types) is the right choice because the future recognizer will produce different Python types per requirement — `int` for `cantidad`, a product-presentation identifier (likely `int`) for `producto_presentacion_id`, possibly a `str` later. The schema's only job here is to hold the value; a future subphase may add `model_validator`s for per-requirement type checks.
- **D3 — `BaseModel`, not `BaseModel` with `model_config`.** The spec says "Use Pydantic `BaseModel`". The default config is sufficient; the active subphase does not need `extra="forbid"`, `from_attributes=True`, or `frozen=True`. A future subphase can add a `model_config` if validation or immutability requirements emerge.
- **D4 — Field order matches the spec.** `name` first, then `status`, then `value`. The default is on `value` only. A future `created_at` / `updated_at` (if needed for audit) is out of scope.
- **D5 — `value` is exposed in the model (not a `model_validator`-only field).** Recognizer output goes into `value`; the schema is the canonical runtime representation. There is no computed-only field.
- **D6 — File layout mirrors subphase 3.1.** `backend/intents/schemas/__init__.py` is an empty package marker so future schemas (`Intent`, `IntentResult`, etc.) slot in naturally. The active subphase introduces only `requirement_state.py`.
- **D7 — Test lives in `backend/tests/api_smoke.py`.** Consistent with the established layout. Pure import + `assert` — no DB, no FastAPI client.

## Risks / Trade-offs

- **[Risk] `Any` erases type safety for `value`.** → Acceptable for the active subphase: the spec mandates `Any`. A future subphase can add a per-requirement type guard by extending the contract with `expected_type` and adding a `model_validator` on `RequirementState`.
- **[Risk] `Literal` does not survive JSON round-trip as a type.** → Acceptable: Pydantic re-validates the string on parse; invalid strings raise `ValidationError` at the API boundary.
- **[Trade-off] No `Enum` class for `RequirementStatus`.** → Matches the spec; defer to a future subphase if needed.

## Open Questions

- None. The schema fields, types, defaults, and the "do not add business logic or other schemas" rule are all fixed by Subphase 3.2 in `project.md`.