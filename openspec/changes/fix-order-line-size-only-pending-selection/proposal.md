# Proposal: fix order-line size-only pending selection

## Why

After the valid `quitar_producto` ambiguity between `Mozzarella Grande` and
`Mozzarella Chica`, replies such as `Chica`, `chica`, `Grande`, or `la grande`
repeat the clarification. The initial request and its restricted
`order_line_selection` pending context are correct. The follow-up resolver
passes every message through `recognize_quitar_producto`, which needs a
product reference and can return no candidate for a presentation-only reply.

The prior `fix-pilot-order-line-category-recognition` change restored initial
category/product recognition. It intentionally does not resolve this later
presentation-only refinement, so this needs a separate active change.

## What Changes

- Add one deterministic presentation-only pre-check to the existing
  `order_line_selection` resolver, only for pending `quitar_producto`.
- Read only lines from `session.id_pedido`, filter strictly to persisted
  `candidate_ids`, and compare an exact normalized bare reply with the
  candidate presentation codes already shown in the clarification.
- Exactly one match follows the existing ready intent and handler path. Zero
  or multiple matches fall through to the existing recognizer/intersection
  behavior without guessing.
- Add resolver and smallest dispatcher/handler proofs for `Chica` and
  `Grande`, exact ownership, cleanup, and fallback behavior.

## Current execution path

```text
quitar pizza de mozzarella
  -> initial recognizer restricted to session.id_pedido lines
  -> two pedido_producto_id values persist as order_line_selection
  -> pending_context_dispatcher -> resolve_order_line_selection
  -> recognize_quitar_producto("Chica") returns no product candidate
  -> pending_resolution persists and clarification repeats
```

## Scope and shared boundary

The persisted active `candidate_ids` are the sole authoritative universe. The
new read may inspect only their own PedidoProducto rows and each related
presentation code. It cannot select a candidate from another Pedido, commerce,
product or catalog.

Permit the normalized exact presentation code, optionally preceded by one
article (`la`, `el`, `una`, `un`, `las`, `los`). Thus `chica` and `la chica`
can match; `napolitana chica` is not a bare presentation reply and proceeds
through the existing restricted recognizer.

| Condition | Outcome |
| --- | --- |
| One exact active size match | Existing ready intent for that `pedido_producto_id`; existing handler owns removal. |
| Zero or multiple exact matches | Existing recognizer/intersection path; no guess. |
| Existing recognizer finds only outside candidates | Current rejection and context cleanup. |
| Missing association, malformed relation or technical read failure | Existing no-match/technical semantics; never invent a selection. |

The successful deterministic path must not invoke the product recognizer,
hybrid/LLM boundary, handler or transaction control itself. It is not a new
mutation authority.

## Non-goals

- No initial product/category recognition, fuzzy/hybrid policy, LLM,
  classifier, prompt, catalog-wide fallback, candidate widening, response,
  panel, provider, Twilio, outbox, schema or migration change.
- No aliases, fuzzy/partial size matching, broader natural-language parsing,
  quantity interpretation, modification or `set_observacion_producto` change.
- No unrelated repair of the pre-existing fixture/import debt documented in
  `fix-pilot-order-line-category-recognition`.

## Transaction ownership, privacy and observability

Resolver and service reads remain caller-owned transaction collaborators: no
commit, rollback, flush, begin, refresh or close. The existing dispatcher
persists/executes the returned intent. No new event, log, diagnostic field,
customer text, identifier, label or price is emitted.

## Expected files

- `backend/intents/context/order_line_selection_resolver.py`
- `backend/tests/test_order_line_selection_resolver.py`
- the smallest existing pending-dispatch or quitar-producto focused test
- this OpenSpec change only

## Focused validation

Run in the user's local terminal:

```text
PYTHONPATH=. venv/bin/python -m pytest backend/tests/test_order_line_selection_resolver.py backend/tests/test_pending_context_dispatcher.py backend/tests/test_quitar_producto_initial.py backend/tests/test_quitar_producto_handler.py backend/tests/test_quitar_producto_response.py -q
PYTHONPATH=. venv/bin/python -m ruff check backend/intents/context/order_line_selection_resolver.py backend/tests/test_order_line_selection_resolver.py backend/tests/test_pending_context_dispatcher.py backend/tests/test_quitar_producto_initial.py backend/tests/test_quitar_producto_handler.py backend/tests/test_quitar_producto_response.py
PYTHONPATH=. venv/bin/python -m compileall -q backend/intents/context/order_line_selection_resolver.py
openspec validate fix-order-line-size-only-pending-selection --strict
git diff --check
```

## Rollback and production gate

This source-only change is reversible by removing the deterministic pre-check.
After approval, implementation, review and deploy, use a clean active draft in
the panel-local channel: create the Grande/Chica ambiguity, test `Chica` and
`Grande` in separate runs, and verify only the selected line changes and the
pending context clears. Resume WhatsApp gates only after this controlled test.
No archive is implied.
