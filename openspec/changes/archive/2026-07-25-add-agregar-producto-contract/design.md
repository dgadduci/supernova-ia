## Context

Phase 3 introduces the intents layer. The WhatsApp channel receives a free-text message, an LLM-based recognizer classifies it into one of the known intents, and a handler carries out the action. The "contract" sits between those two halves: it is a static, importable declaration of "this intent has this name, this recognizer, this handler, and these required inputs." Future subphases will introduce a registry, a recognizer adapter, a handler adapter, and other intent contracts. Subphase 3.1 introduces only the `agregar_producto` contract — nothing else.

## Goals / Non-Goals

**Goals:**

- Create a single Python file under `backend/intents/contracts/` that exports `AGREGAR_PRODUCTO_CONTRACT`.
- The contract is a static dictionary literal — no classes, no functions, no runtime logic.
- The contract's structure and values exactly match the spec in `project.md` (Subphase 3.1).
- The file is importable: `from backend.intents.contracts.agregar_producto import AGREGAR_PRODUCTO_CONTRACT` works without side effects.
- One test asserts the contract's keys, value types, and the specific values defined in the spec.

**Non-Goals:**

- No registry, no recognizer, no handler, no processor, no schema, no Pydantic model, no DB model, no migration, no router, no FastAPI endpoint.
- No other intent contracts (e.g. `cerrar_pedido`, `confirmar_pedido`) — those land in their own subphases.
- No validation framework around the contract. The contract is data; future subphases may add a `Contract` dataclass for type safety, but that is out of scope.
- No documentation file beyond the spec.

## Decisions

- **D1 — The contract is a `dict`, not a class or dataclass.** The spec says "Python dictionary". A `dict` is the simplest data structure that satisfies the requirement and is the natural format for downstream registry code (which can later coerce it into a typed shape if needed). Sticking to a `dict` keeps the contract free of dependencies on `dataclasses` / `pydantic` and matches the spec verbatim.
- **D2 — Values follow the spec literally.** The spec defines:
  - `intent`: `"agregar_producto"`
  - `recognizer`: `"recognizer_productos"`
  - `handler`: `"agregar_producto"`
  - `requirements`: `{"producto_presentacion_id": {"required": True, "default": None}, "cantidad": {"required": True, "default": 1}}`
  The implementation SHALL NOT alter these values. The test asserts them.
- **D3 — The `requirements` values are themselves dicts with `required` and `default` keys.** This is the smallest representation that captures both the necessity and the fallback for each parameter. Future subphases may extend each requirement with `type`, `description`, `validators`, etc.; that is out of scope here.
- **D4 — `default: 1` for `cantidad` is an `int` literal.** The contract is data — it does not parse or coerce values. A future runtime adapter will interpret `default` according to the requirement's type; that is out of scope.
- **D5 — File layout mirrors the rest of `backend/`.** `backend/intents/__init__.py` and `backend/intents/contracts/__init__.py` are empty package markers. The contract file lives one level deep, so a future `backend/intents/recognizers/` or `backend/intents/handlers/` slot in naturally.
- **D6 — Test lives in `backend/tests/api_smoke.py`.** Consistent with the existing test layout. The test imports the contract, asserts the four top-level keys, and asserts each value. No DB, no FastAPI client, no fixtures — pure import + `assert`.

## Risks / Trade-offs

- **[Risk] A `dict` contract is not type-safe at runtime.** → Acceptable for the active subphase: the spec mandates a dict, the values are simple strings/booleans/ints/None, and the test pins the exact values. A future subphase can introduce a `TypedDict` or `dataclass` if type safety becomes a concern.
- **[Risk] Future intent contracts may diverge in shape.** → Mitigation: this subphase introduces a single contract; the next intent contract subphase will set the precedent for additional keys. If divergence emerges, a follow-up subphase can introduce a `Contract` schema.
- **[Trade-off] No test for the intent dispatch path.** → Out of scope: there is no recognizer, no handler, no registry yet. The test asserts the contract only.

## Open Questions

- None. The contract shape, values, and the "do not implement handlers / processors / registries / schemas / database models / migrations / other intent contracts" rule are all fixed by Subphase 3.1 in `project.md`.