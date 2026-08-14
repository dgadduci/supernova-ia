# Proposal: classify removal wording as product removal

## Why

With an own `Mozzarella Chica` line at quantity 3, the pilot processed `saca
una de mozzarella chica` as `agregar_producto`, increasing the line to 4.
`sacar dos de mozzarella chica` likewise reached add and increased it to 6.
The existing forms `quita` and `quitar` work correctly.

This occurs before line recognition and mutation. The static LLM classifier
prompt describes removal generically but does not provide enough semantic
guidance and representative removal wording; the dispatcher then correctly
follows the returned `agregar_producto` branch. This is unrelated to
modification, quantity, category projection, or pending-context behavior.

## What Changes

- Add semantic prompt guidance for requests to remove a product from the
  current order. Use representative wording such as `quita`, `quitar`,
  `saca`, `sacar`, `retirá`, `retirar`, `eliminá`, and `eliminar`, all mapping
  to `quitar_producto`, never `agregar_producto` when the expressed action is
  removal.
- Bump the static prompt-template version so diagnostics expose the intentional
  prompt revision.
- Add focused static prompt, controlled classifier-schema, dispatcher-routing,
  and pilot coverage.

## Scope and non-goals

Scope is `backend/diagnostics/prompt_template.py` and its focused tests. No
intent enum, dispatcher branch, recognizer, handler, service, product matching,
quantity, pending context, hybrid/fuzzy policy, provider, panel, migration, or
authentication change is allowed.

Do not add a deterministic pre-classifier, exhaustive verb table, verb-regex
dispatcher override, or fallback from `agregar_producto` to
`quitar_producto`. The LLM remains the semantic classification authority;
existing own-line recognition and handler validation remain the authority
before mutation. The representative examples are guidance, not a closed
vocabulary or a claim that every Spanish verb is safely a removal request.

## Current path and contract

```text
saca una de mozzarella chica
  -> prompt lacks sufficient removal semantic guidance
  -> LLM emits agregar_producto              # observed
  -> dispatcher runs add pipeline
  -> quantity increases

corrected
  -> revised static prompt
  -> LLM emits one quitar_producto
  -> existing Pedido-scoped removal pipeline
```

| Condition | Required outcome |
| --- | --- |
| A clear request to remove from the current order, e.g. `saca`, `sacar`, `retirá`, `retirar`, `eliminá`, or `eliminar` a product | One `quitar_producto`, original message preserved; existing remove path applies its existing semantics. |
| `saca una de mozzarella chica` | One `quitar_producto`; existing remove path decrements one. |
| `sacar dos de mozzarella chica` | One `quitar_producto`; existing remove path decrements two or applies its existing safe rejection. |
| `quita` / `quitar` | Existing removal behavior unchanged. |
| Add wording | Existing `agregar_producto` behavior unchanged. |
| Ambiguous/technical classification failure | Existing safe outcome; no mutation inferred from the prompt rule. |

The rule applies only when the message expresses removal from the current
order. It must not classify unrelated uses of the representative words as
product removal. Each classified `mensaje` stays a literal substring of the
current message.

## Transaction ownership, privacy, and observability

The prompt template, classifier, and dispatcher remain transaction-neutral:
they do not commit, roll back, flush, refresh, begin, or close sessions. The
existing diagnostic continues to expose only static template version and
fingerprint; it must not retain prompt or customer-message content.

## Expected files

- `backend/diagnostics/prompt_template.py`
- `backend/tests/test_intent_classifier.py`
- `backend/tests/test_initial_intent_dispatcher.py` only if existing coverage
  cannot express the route
- `openspec/changes/fix-remove-product-verb-classification/`

## Focused validation

Run in the user's local terminal:

```text
PYTHONPATH=. venv/bin/python -m pytest backend/tests/test_intent_classifier.py backend/tests/test_initial_intent_dispatcher.py backend/tests/test_production_observability.py -q
PYTHONPATH=. venv/bin/python -m ruff check backend/diagnostics/prompt_template.py backend/tests/test_intent_classifier.py backend/tests/test_initial_intent_dispatcher.py backend/tests/test_production_observability.py
PYTHONPATH=. venv/bin/python -m compileall -q backend/diagnostics/prompt_template.py backend/llm/intent_classifier.py backend/intents/orchestration/initial_intent_dispatcher.py
openspec validate fix-remove-product-verb-classification --strict
git diff --check
```

## Rollback and pilot gate

Rollback is a prompt-template revert; no persisted state changes. After an
approved deploy, send the two reported messages and one representative
synonym such as `retirá una de mozzarella chica` against a known own line and
verify decrement/deletion, no add, no unrelated line mutation, and cleared
context/pending. Archive only with explicit user approval.
