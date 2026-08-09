## Design

### Evidence and invariant

A controlled synthetic local request produced two consecutive executed
`agregar_producto` results for the same presentation. The resulting order
quantity was correct, but the customer received an intermediate confirmation
followed by the final confirmation. The invariant is therefore response-only:
all processed intents and mutations remain intact, while each eligible run
produces one final confirmation.

### Eligibility algorithm

Walk the ordered `ProcessedIntent` list once. Start a group only when the item
has intent `agregar_producto`, status `executed`, and a positive integer
`resolved_data["producto_presentacion_id"]`. Extend it only with immediately
following items satisfying the same predicates and identifier. Yield the last
item of the group for rendering. Yield every non-eligible item unchanged.

This preserves order and means a pending, rejected, failed, distinct-product,
or intervening intent terminates a group. The terminal item carries the
authoritative cumulative `cantidad_final` and is the only item rendered for
that group.

### Shared boundary

Place the pure helper in the existing `backend.intents.responses` package.
Both the local response orchestrator and provider outbox mapper call it before
their existing builders. This prevents a new parallel policy and preserves the
orchestrator's prohibition on service/repository imports.

### Transaction and errors

The helper neither accesses the database nor catches errors. Existing callers
continue to own queries, commits, rollbacks, outbox staging and exception
propagation. The helper must not mutate input `ProcessedIntent` objects or
their resolved data.

### Focused acceptance matrix

| Input sequence | Expected responses |
| --- | --- |
| executed same-presentation add, executed same-presentation add | one, from terminal item/final quantity |
| executed adds for two presentations | two, original order |
| executed add, pending add | two |
| pending/rejected/failed add | existing individual behavior |
| add separated by another intent | existing individual behavior |

### Validation commands

Run locally by the user after implementation, adapting only the explicitly
touched test paths:

```bash
venv/bin/python -m pytest backend/tests/test_incoming_message_response_orchestrator.py backend/tests/test_outbound_response_mapper.py
venv/bin/ruff check backend/intents/responses backend/intents/orchestration/incoming_message_response_orchestrator.py backend/services/outbound_response_mapper.py
venv/bin/python -m compileall -q backend/intents/responses backend/intents/orchestration/incoming_message_response_orchestrator.py backend/services/outbound_response_mapper.py
openspec validate coalesce-duplicate-add-product-confirmations-7-1-1 --strict
git diff --check
```

The user must paste complete output. Only after approval and the local pilot
happy-path repeat is successful may the existing pilot change be reconsidered.
