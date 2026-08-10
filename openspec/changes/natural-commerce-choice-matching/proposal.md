# Accept natural commerce-scoped payment and delivery choices

## Objective

Let a customer select an enabled payment or delivery option using a natural phrase such as `Pago en Efectivo (prueba cierre)`, while preserving strict commerce isolation and ambiguity safety.

## Production evidence and current path

The classifier correctly produced `set_metodo_de_pago` for `Pago en Efectivo (prueba cierre)`. The guided-closure handler then rejected it because `_match_choice` accepted only normalized equality with the selected commerce candidate's code or description. The active row was `EFECTIVO_PRUEBA_CIERRE` / `Efectivo (prueba cierre)`. Exact description and code succeeded; the natural prefix `Pago en` did not.

`_set_commerce_scoped_choice` already loads only active options linked to the current session commerce before invoking `_match_choice`; it owns no transaction and stages only the selected pedido field.

## Scope

- Extend the local choice matcher used by guided payment and delivery selection.
- Keep exact normalized code/description matching authoritative.
- As a second, bounded fallback, match a candidate description only when every normalized description token appears in the customer phrase and exactly one active commerce candidate qualifies.
- Preserve `missing`, `not_active` and `ambiguous` outcomes and existing option rendering.
- Add focused tests for natural payment/delivery text, ambiguity, foreign/inactive exclusion and no mutation on rejection.

## Non-goals

- No LLM/prompt/intents change, aliases table, fuzzy/global catalog search, migration, settings, new recognizer, code-token partial matching, transaction change, or automatic choice selection among multiple candidates.
- No change to product recognition, worker, queues, retry policy or provider flow.

## Authoritative outcomes and fallback

1. Exact normalized code or description match remains the first authoritative match.
2. If exact matching finds none, description-token containment is evaluated only among the existing active candidates for the session commerce.
3. One candidate qualifies: set it. More than one qualifies: return `ambiguous`, mutate nothing and render only those existing scoped options. None qualifies: return `not_active`, mutate nothing.

The fallback must not use candidate code tokens, inactive/global/foreign candidates, partial substrings, edit distance, synonyms, LLM or any candidate set outside the repository result. Empty input remains `missing`.

## Boundaries, validation and rollback

The matcher is pure relative to DB state. The existing orchestrator retains caller-owned transaction behavior: no commit/rollback/flush/session changes. Expected implementation surface is `backend/intents/orchestration/draft_order_closure.py`, `backend/tests/test_draft_order_closure.py`, this delta and tasks.

```bash
PYTHONPATH=. venv/bin/python -m pytest backend/tests/test_draft_order_closure.py backend/tests/test_initial_intent_dispatcher.py -q
PYTHONPATH=. venv/bin/python -m ruff check backend/intents/orchestration/draft_order_closure.py backend/tests/test_draft_order_closure.py
PYTHONPATH=. venv/bin/python -m compileall -q backend/intents/orchestration/draft_order_closure.py
openspec validate natural-commerce-choice-matching --strict
```

Rollback is restoring exact-only matching; no migration or data repair is needed. General synonyms, typo tolerance and configurable aliases remain deferred.
