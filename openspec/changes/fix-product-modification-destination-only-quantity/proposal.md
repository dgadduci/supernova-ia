# Proposal: destination-only quantity semantics for product modification

## Why

In the pilot, `cambia la napolitana grande por dos mozzarella grande` found
the correct source and destination candidates but rejected with `Solo tenés 1
Napolitana`. The current recognizer assigns the sole destination-side `dos` to
legacy source `cantidad`, so the handler tries to remove two source units.
The subsequent `por una mozzarella` appeared correct only because destination
one happened to equal the source line quantity one.

## What Changes

- Give an explicit positive quantity appearing only after `por` the meaning
  “full source line -> stated destination quantity”.
- Preserve that destination amount through pending source/destination
  selection and use the existing handler re-read for the full source amount.
- Keep the previously deployed paired, source-only, omitted, invalid, and
  historical-pending behaviors unchanged.

## Objective and current execution path

```text
cambia la napolitana grande por dos mozzarella grande
  -> current: cantidad=2, cantidad_destino=None
  -> handler attempts source -2 / destination +2
  -> source has 1 -> quantity_exceeds_source

corrected: cantidad=None, cantidad_destino=2
  -> handler re-reads source's current full quantity (1)
  -> source -1 / destination +2 atomically
```

## Scope and non-goals

Only the case with **no explicit source quantity** and **one explicit positive
destination quantity** changes. The complete matrix is:

| Source side | Destination side | Required operation |
| --- | --- | --- |
| omitted | omitted | full source -> same quantity |
| explicit N | omitted | N -> N |
| omitted | explicit M | full source -> M |
| explicit N | explicit M | N -> M |

Non-goals: ratio language, multiple source/destination lines, price/totals,
candidate policy, classifier/prompt, hybrid/fuzzy, migrations, panel,
provider/Twilio, and source-side quantity parsing. Persisted pending payloads
with legacy `cantidad` and no `cantidad_destino` remain N -> N; they must not
be reinterpreted.

## Shared boundary and outcomes

The existing normalized `por` split is the sole boundary. The recognizer's
deterministic side probes are authoritative for this routing; LLM/hybrid/fuzzy
output has no quantity or mutation authority. Existing invalid destination
quantities (zero, negative, decimal/non-integer) remain rejected before
pending or mutation.

| Condition | Required outcome |
| --- | --- |
| Omitted source, destination M positive | `cantidad=None`, `cantidad_destino=M`; handler re-reads source at execution. |
| Destination ambiguity | Persist those exact fields; only existing pending candidates may resolve. |
| Source explicit N, destination omitted | Existing `cantidad=N`, `cantidad_destino=None`. |
| Old pending has only `cantidad=N` | Existing N -> N. |
| Invalid destination amount | Existing typed rejection, no pending or mutation. |

## Transaction ownership, privacy, and observability

No collaborator gains transaction ownership: the recognizer/resolver/handler
do not commit or roll back; the existing service validates and mutates in its
caller-owned transaction. No logs, metrics, panel fields, IDs, raw text, or
PII are added.

## Expected files

- `backend/intents/recognizers/modificar_producto_recognizer.py`
- `backend/intents/orchestration/modificar_producto_initial.py` and/or
  `backend/intents/context/product_modification_resolver.py` only if threading
  requires it
- smallest relevant modificar-producto recognizer, initial/resolver, handler,
  response, and end-to-end tests
- `openspec/changes/fix-product-modification-destination-only-quantity/`

## Focused validation

```text
PYTHONPATH=. venv/bin/python -m pytest backend/tests/test_modificar_producto_recognizer.py backend/tests/test_modificar_producto_initial.py backend/tests/test_product_modification_resolver.py backend/tests/test_modificar_producto_handler.py backend/tests/test_modificar_producto_response.py backend/tests/test_modificar_producto_end_to_end.py -q
PYTHONPATH=. venv/bin/python -m ruff check backend/intents/recognizers/modificar_producto_recognizer.py backend/intents/orchestration/modificar_producto_initial.py backend/intents/context/product_modification_resolver.py backend/intents/handlers/modificar_producto_handler.py backend/intents/responses/modificar_producto_response.py backend/tests/test_modificar_producto_recognizer.py backend/tests/test_modificar_producto_initial.py backend/tests/test_product_modification_resolver.py backend/tests/test_modificar_producto_handler.py backend/tests/test_modificar_producto_response.py backend/tests/test_modificar_producto_end_to_end.py
PYTHONPATH=. venv/bin/python -m compileall -q backend/intents/recognizers/modificar_producto_recognizer.py backend/intents/orchestration/modificar_producto_initial.py backend/intents/context/product_modification_resolver.py backend/intents/handlers/modificar_producto_handler.py backend/intents/responses/modificar_producto_response.py
openspec validate fix-product-modification-destination-only-quantity --strict
git diff --check
```

## Rollback and pilot gate

The change is reversible by restoring the former destination-only branch;
existing persisted pending states stay safe because their legacy fields retain
their current meaning. After deploy, verify the exact pilot message above,
resolve `grande` if asked, and confirm full source removal plus destination +2
and a response with both amounts. Re-run N -> N and N -> M regressions. Do
not archive this or dependent changes without explicit user approval.
