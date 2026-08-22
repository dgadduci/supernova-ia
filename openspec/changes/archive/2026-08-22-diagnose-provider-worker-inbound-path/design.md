# Design: diagnose provider worker inbound path

## Decision

Use the existing provider coordinator as the observation root and add a
single closed event rather than adding logs at arbitrary call sites or a
parallel diagnostic runner.

The intended trace for one leased inbound turn is:

```text
availability started -> completed/failed
session_order started -> completed/failed
business_pipeline started
  -> existing llm_request and/or embedding_request events
  -> business_pipeline completed/failed
outbound_staging started -> completed/failed
processing_finalization started -> completed/failed
```

If `business_pipeline started` or a model-request `started` event is the last
record, the trace shows the last boundary reached without inventing a terminal
business result. Existing `provider_inbound_processing_outcome` remains the
source of truth once finalization actually occurs.

## Event contract

Register `provider_inbound_stage` with component `provider_worker` and
schema-version handling through `backend.observability.events`.

The closed fields are:

| Field | Contract |
|---|---|
| `stage` | `availability`, `session_order`, `business_pipeline`, `outbound_staging`, or `processing_finalization` |
| `outcome` | `started`, `completed`, or `failed` |
| `correlation_id` | existing opaque synthetic inbound value, max 64 safe characters; required for provider-scoped evidence and absent outside that scope |
| `elapsed_ms` | absent on `started`; bounded non-negative integer on `completed`/`failed` |
| `exception_type` | optional bounded safe type name only on `failed` |

The catalogue SHALL reject unknown fields, stage/outcome values, negative or
unbounded durations, raw exception text and sensitive payloads. It SHALL not
accept message bodies, prompts, vectors, URLs, provider IDs, account data or
free-form diagnostic labels.

## Correlation propagation

The coordinator already installs the receipt's safe opaque value for
`llm_request` timing events. Reuse that value and extend the smallest possible
shared context so an embedding request reached during the same leased turn
emits the same bounded `correlation_id`. Existing non-provider embedding calls
remain uncorrelated unless their caller already supplies an authorized value.

The implementation SHALL not expose a new public request parameter merely for
diagnostics if a private context seam can preserve the current constructors.
It SHALL clear the context in every coordinator exit path, including
successful commit, rollback, retry, terminal finalization, unavailable
commerce and lease loss. Context cleanup failure must not replace the original
business outcome.

## Stage instrumentation

Wrap only the existing coordinator boundaries:

1. commerce availability evaluation;
2. active session and draft-pedido staging;
3. `process_incoming_message`;
4. `stage_outbound_rows` and its flush;
5. processing-row finalization/commit.

The wrappers capture a monotonic start time, emit `started` before entering
the seam, and emit `completed` only after normal return. If the seam raises,
they emit `failed` with the safe exception type and re-raise into the current
coordinator error path. Conditional finalization and lease-loss behavior stay
unchanged. The finalization wrapper must not emit `completed` before the
existing commit/conditional finalization result is authoritative.

## Failure and transaction semantics

No event is allowed to call `flush`, `commit`, `rollback`, or a separate
database connection. Event emission occurs in the existing best-effort
observability seam. If an event cannot be built or written, the coordinator
continues; if the business seam raises, the coordinator's existing rollback
and `_finalize_failure` behavior decides the durable state.

An incomplete stage is intentionally represented by the last `started` event.
The implementation must not add a watchdog, local timeout, cancellation,
automatic retry, fallback response or lease repair.

## Tests

Tests shall prove:

- valid stage events round-trip through the existing production event parser;
- unknown stage/outcome, negative/oversized duration, PII-like fields,
  message text, prompt text, vectors and raw exception text are rejected;
- the coordinator emits stage events in order on a successful turn;
- a seam exception emits `failed` and preserves the existing failure path;
- an injected non-returning seam leaves only its `started` evidence and does
  not trigger fabricated completion or recovery;
- provider `llm_request` and `embedding_request` events carry the same safe
  correlation value when invoked inside one leased turn;
- non-provider direct client calls retain current behavior and do not acquire
  a provider correlation accidentally;
- an event-emission failure does not alter the business result;
- existing worker liveness, processing-outcome, QueryLlm and embedding-client
  contracts remain green.

## Operational interpretation

The change is read-only evidence. After deployment, operators may compare the
synthetic inbound correlation value across the bounded production-log query,
the existing Emulator timeline and the processing-outcome event. A last
`provider_inbound_stage=business_pipeline, outcome=started` together with a
last `llm_request` or `embedding_request` start identifies the active model
boundary without exposing its content. A completed business pipeline followed
by no outbound staging evidence points to mapping/staging; an accepted
processing outcome followed by no Emulator `Messages.json` remains an outbound
dispatch/T-C investigation and is outside this change.

