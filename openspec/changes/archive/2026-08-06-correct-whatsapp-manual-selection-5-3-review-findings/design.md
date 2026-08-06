## Decision

Keep all Phase-5.3 operations inside the existing
`SharedChannelRoutingService`; introduce neither a new service nor a parallel
routing path.

`list_manual_options` shall validate channel mode immediately after the common
active-channel precondition succeeds. If the channel is not `SHARED`, it shall
return `invalid_channel_mode`, expose no options, and leave context untouched.

For `request_switch`, the target membership is still validated against the
same active shared channel and active commerce. When that target's commerce
equals `comercio_id_seleccionado`, the operation is a no-op: it returns the
existing `switch_requested` outcome shape with the persisted pending target
unchanged. It must not call a repository mutation helper. Only
`cancel_switch` clears a target; a request for a different valid commerce may
replace it; confirmation may consume it.

## Authoritative outcomes

| Condition | Result | Mutation |
| --- | --- | --- |
| Active dedicated channel lists options | `invalid_channel_mode` | None |
| Current-commerce request with no pending target | `switch_requested` | None |
| Current-commerce request with a different pending target | `switch_requested` | None; target preserved |
| Different valid membership request | Existing `switch_requested` | Existing target replacement behavior |

## Invariants

- Manual options exist only on an active shared channel.
- A pending target is never cleared except by explicit cancellation or by
  successful confirmation; first manual selection may clear an impossible
  stale target only while no selection exists, as already specified.
- The selected commerce and `mensaje_original_pendiente` remain byte-identical
  through both corrective paths.
- Candidate/membership isolation, active-commerce checks, typed outcomes,
  caller-owned transaction behavior and the no-pipeline boundary remain
  unchanged.

## Focused tests

Add or revise tests proving:

1. Listing options on an active dedicated channel returns
   `invalid_channel_mode`, an empty option tuple, and does not mutate the
   existing context.
2. Requesting the current commerce with an already pending different target
   preserves selected commerce, pending target and original message after a
   committed caller transaction.
3. Existing behavior for a current-commerce request with no pending target and
   for replacement by a different valid target remains covered.

## Validation

Run from the repository root:

```bash
PYTHONPATH=. venv/bin/pytest -q backend/tests/test_shared_channel_manual_selection.py backend/tests/test_shared_channel_routing_context.py
PYTHONPATH=. venv/bin/python -m ruff check backend/services/shared_channel_routing_service.py backend/tests/test_shared_channel_manual_selection.py
PYTHONPATH=. venv/bin/python -m compileall backend/services/shared_channel_routing_service.py backend/tests/test_shared_channel_manual_selection.py
openspec validate correct-whatsapp-manual-selection-5-3-review-findings --strict
git diff --check
```

Record exact outputs, exit codes and any environmental blocker in `tasks.md`.
