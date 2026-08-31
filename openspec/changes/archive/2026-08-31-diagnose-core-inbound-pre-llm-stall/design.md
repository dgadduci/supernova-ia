# Design: diagnose the core inbound pre-LLM stall

## Decision

Extend the existing `provider-worker-inbound-diagnostics` capability with one
small closed event instead of adding arbitrary logs or another probe pipeline.
The coordinator remains the trace root and the existing model events remain
the model boundaries.

The intended trace is:

```text
provider_inbound_stage availability started
  -> provider_inbound_checkpoint availability_evaluated
provider_inbound_stage availability completed
provider_inbound_stage session_order started
  -> session_loaded
  -> draft_stage_decision
  -> session_order_flushed
provider_inbound_stage session_order completed
provider_inbound_stage business_pipeline started
  -> business_dispatch_started
  -> existing llm_request started/completed or timeout
provider_inbound_stage business_pipeline completed/failed
```

The event order is observational. It must not alter the order of existing
business calls or transaction operations.

## Event contract

Register `provider_inbound_checkpoint` with component `provider_worker` and
the existing schema/version and safe-field validation machinery.

| Field | Contract |
|---|---|
| `checkpoint` | Closed token listed in the proposal; required |
| `availability_status` | `available` or `unavailable`; only at `availability_evaluated` |
| `availability_reason` | Closed unavailable reason; only with `unavailable` |
| `session_present` | Boolean; only at `session_loaded` |
| `pedido_present` | Boolean; only at `session_loaded` or `draft_stage_decision` |
| `pedido_created` | Boolean; only at `draft_stage_decision` |
| `flush_completed` | Boolean true; only at `session_order_flushed` |
| `dispatch_branch` | `initial`, `pending_context` or `unsupported`; only at `business_dispatch_started` |
| `elapsed_ms` | Optional bounded non-negative integer |
| `correlation_id` | Existing bounded opaque provider correlation value |

Unknown fields, invalid combinations, free-form checkpoint values, negative
or oversized durations, and sensitive values must be rejected by the existing
event validation contract. The event must not accept IDs, text, URLs, prompts,
responses, exception strings or tracebacks.

## Emission points

1. After the existing availability evaluation returns, emit
   `availability_evaluated` with only its closed status and, when needed, its
   closed reason.
2. After `stage_active` returns, emit `session_loaded` with presence booleans.
3. After the draft decision and any existing draft staging returns, emit
   `draft_stage_decision` with booleans indicating whether a draft was already
   present and whether one was created by this turn.
4. After the existing session-order flush returns, emit
   `session_order_flushed` with `flush_completed=true`.
5. Immediately before the existing initial or pending-context dispatch is
   invoked, emit `business_dispatch_started` with the closed branch value.

The implementation must use the current provider correlation context. If the
shared orchestrator cannot safely access that context without a broad API
change, the coordinator may emit the branch checkpoint immediately before
calling the existing `process_incoming_message` seam using the already known
session context. No public endpoint or caller contract should be expanded.

## Partial traces and timeout interpretation

- `availability` stage started with no checkpoint means availability did not
  return.
- `session_order` started with no `session_loaded` means the active session
  lookup/staging did not return.
- `session_loaded` without `draft_stage_decision` or
  `session_order_flushed` points to draft decision/staging or its flush.
- `business_pipeline` started and `business_dispatch_started` is absent
  points to entry/setup before dispatch.
- `business_dispatch_started` with no `llm_request` points to work inside the
  selected dispatch branch before the existing classifier LLM boundary.
- `llm_request` started with timeout evidence points to the existing model
  transport boundary; this change does not relabel or recover it.
- Completed business processing with no outbox row remains interpreted by the
  existing processing-outcome and outbox diagnostics.

No missing event may be converted into a synthetic failure or timeout.

## Failure and transaction semantics

Checkpoint emission is best effort and must be outside transaction-control
responsibility. The coordinator's existing exceptions, rollback, lease
finalization, retry scheduling and terminal outcomes remain unchanged. An
emission error is swallowed by the observability seam; a business exception is
still re-raised into the existing coordinator path.

## Tests

Focused tests must prove:

- every valid checkpoint round-trips through the event parser;
- invalid checkpoint/field combinations, out-of-range values and sensitive
  payloads are rejected;
- a successful coordinator turn emits the checkpoints in the documented
  order without changing the existing stage/outcome order;
- availability unavailable outcomes expose only the closed reason;
- a session with an existing draft and a session requiring a staged draft are
  distinguishable through booleans only;
- initial and pending-context dispatch branches are distinguishable;
- an injected blocked seam leaves only the evidence reached before the block;
- an injected emitter failure does not change the business result or invoke
  transaction control;
- an LLM timeout remains represented by the existing `llm_request`/processing
  timing and outcome contracts, without fabricated checkpoint completion.

## Operational interpretation

After deployment, operators should correlate one synthetic inbound value over
the event stream. The last checkpoint, the presence/absence of
`llm_request`, and the durable processing snapshot together identify the
boundary for the next root-cause change. The event is not a health check and
must not be used to trigger manual recovery automatically.
