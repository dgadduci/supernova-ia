## Context

Mirrors `seeds-estado-comercio`, `seeds-comercios`, and `seeds-medios-pago`. Code under `backend/db/seeds/` (with the script placed in the `seeds/` subfolder per the same convention as `estados_comercio.py`). DB selection via `SUPERNOVA_DATABASE_URL` with default `supernova_test`.

`MetodosEntrega.codigo` is declared `unique=True` in the model, same as `MediosPago.codigo`. Idempotency on `codigo` is the natural choice.

One model-specific note: `MetodosEntrega.orden` has no Python-side or server-side default — every row must supply it explicitly. The JSON includes an `orden` value per row, so this is satisfied at insert time.

## Decisions

- **D1 — One script, one DB at a time.** Same convention as prior seed subphases.
- **D2 — Idempotent on `codigo`.** Matches the model's natural unique key.
- **D3 — JSON data file, not embedded constants.** Source of truth lives next to the script.
- **D4 — `orden` supplied explicitly per row in the JSON.** Required by the model; no default exists.

## Risks / Trade-offs

- **[Trade-off] No global "seed everything" runner.** A future subphase may add one. Out of scope here.
