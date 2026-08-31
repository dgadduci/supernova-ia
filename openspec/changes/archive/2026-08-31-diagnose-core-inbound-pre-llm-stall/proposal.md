# Proposal: diagnose the core inbound pre-LLM stall

## Objective

Obtain decisive, privacy-safe evidence for the intermittent provider inbound
stall observed after a receipt is leased. The latest live audit shows that a
third turn can remain `leased` without an LLM timestamp and later become
`retryable` with `llm_resultado=timeout`; therefore the diagnostic must
distinguish a block before the LLM boundary from a timeout after that boundary.

The change is diagnostic only. It does not attempt to repair the worker,
change the timeout, or add recovery. Its purpose is to identify the last
completed checkpoint among availability, session/order staging and the start
of the business pipeline, while reusing the existing `llm_request` and
`provider_inbound_stage` events as authoritative boundary evidence.

## Current execution path

The T-C accepts the inbound request and NovaOrders persists a provider
receipt plus a pending processing row. The worker claims that row and the
coordinator then evaluates commerce availability, stages the active session
and draft pedido, enters `process_incoming_message`, dispatches either the
initial classifier or a pending-context flow, stages outbound rows and
finalizes the processing row. The existing `llm_request` event marks the
intent-classifier boundary; the existing provider-flow audit records durable
processing and outbox state.

The observed third-turn evidence is:

- ingress accepted and processing claimed;
- no outbound row while the item was leased;
- in the later terminal snapshot, `llm_resultado=timeout`,
  `llm_solicitado_en` present, `llm_finalizado_en` about three minutes later,
  and `retryable` with `database_error/processor_error`;
- direct repeated `QueryLlm` probes can still succeed, so this change must
  localize the worker boundary rather than assume the LLM is the root cause.

## Scope

- Add a closed, privacy-safe `provider_inbound_checkpoint` event to the
  existing provider-worker diagnostics capability.
- Emit bounded checkpoints for the existing availability result, session
  lookup/staging, draft-pedido decision, session-order flush, and business
  dispatch branch.
- Preserve the existing `provider_inbound_stage` events for stage entry/exit
  and the existing `llm_request` events for the actual LLM boundary.
- Make the event correlation usable with the current opaque provider
  correlation value and document how to interpret each last checkpoint.
- Add focused tests for the event contract, checkpoint order, timeout/partial
  traces and fail-soft emission.

## Non-goals

- No change to worker cadence, leases, retries, timeout values, cancellation,
  supervisor behavior or stuck-turn recovery.
- No change to availability policy, session/order business rules, classifier,
  semantic recognizer, prompts, Ollama, proxy, T-C, Twilio, outbox dispatch or
  HTTP/TwiML behavior.
- No replay, fallback response, automatic repair, second LLM call or new
  processing pipeline.
- No schema, migration, dashboard, alerting service or persistent diagnostic
  table.
- No raw inbound text, prompts, model responses, vectors, phone numbers,
  database IDs, provider IDs, URLs, credentials, exception messages or
  tracebacks in events.

## Shared boundary

The provider inbound coordinator remains the single observation root and the
owner of the caller-provided SQLAlchemy transaction. Checkpoints wrap the
existing seams; they do not add a transaction, flush, commit, rollback, lease
operation or database connection. The existing `QueryLlm` boundary remains
the only evidence that the classifier request was actually reached.

## Diagnostic contract

The new event SHALL use only these closed values and bounded fields:

- `checkpoint`: `availability_evaluated`, `session_loaded`,
  `draft_stage_decision`, `session_order_flushed`, or
  `business_dispatch_started`;
- `availability_status`: `available` or `unavailable`, only for the
  availability checkpoint;
- `availability_reason`: `blocked_state`, `trial_expired` or
  `trial_quota_exhausted`, only when availability is unavailable;
- `session_present`, `pedido_present`, `pedido_created` and
  `flush_completed`, as booleans only where applicable;
- `dispatch_branch`: `initial`, `pending_context` or `unsupported`, only for
  the business dispatch checkpoint;
- bounded non-negative `elapsed_ms` and the existing opaque
  `correlation_id`.

The event is evidence, not durable state. A checkpoint is emitted only after
the corresponding operation has returned. Existing stage `started` events
remain the evidence that a seam was entered; no completion is fabricated if
the operation does not return.

## Fallback behavior

Checkpoint construction and emission are best effort. If validation or
serialization fails, the original business call continues unchanged. Missing
checkpoint evidence never triggers timeout, retry, lease repair, replay or
fallback. Existing exception, rollback and finalization behavior remains
authoritative.

## Transaction ownership

The coordinator retains ownership of all transaction controls. The new
observability code SHALL not call `flush`, `commit`, `rollback`, `refresh`,
`begin`, or `close`, and SHALL not open a side session. A checkpoint may be
emitted after an existing flush returns, but it does not perform that flush.

## Observability and privacy

Operators must be able to correlate the checkpoint event with
`provider_inbound_stage`, `llm_request`, `provider_inbound_processing_outcome`
and the live audit by the same bounded opaque correlation value. The event
must never expose business content or infrastructure secrets. Emission
failures must not print rejected payloads or exception text.

## Expected files

- `backend/observability/events.py`
- `backend/observability/__init__.py`
- `backend/services/provider_inbound_message_coordinator.py`
- `backend/intents/orchestration/incoming_message_orchestrator.py` only if
  the shared dispatch seam is required for the closed branch value
- `backend/tests/test_provider_message_receipt_core_integration.py`
- `backend/tests/test_production_observability.py`
- `backend/tests/test_provider_processing_worker.py` only if worker-boundary
  coverage is required
- This change's OpenSpec files

## Focused validation

The implementer must run and report complete output from:

```text
PYTHONPATH=. venv/bin/python -m pytest backend/tests/test_provider_message_receipt_core_integration.py backend/tests/test_production_observability.py backend/tests/test_provider_processing_worker.py -q
PYTHONPATH=. venv/bin/ruff check backend/observability/events.py backend/observability/__init__.py backend/services/provider_inbound_message_coordinator.py backend/intents/orchestration/incoming_message_orchestrator.py backend/tests/test_provider_message_receipt_core_integration.py backend/tests/test_production_observability.py backend/tests/test_provider_processing_worker.py
PYTHONPATH=. venv/bin/python -m compileall -q backend/observability/events.py backend/observability/__init__.py backend/services/provider_inbound_message_coordinator.py backend/intents/orchestration/incoming_message_orchestrator.py
openspec validate diagnose-core-inbound-pre-llm-stall --strict
git diff --check
```

Local Python validation is to be run by the user in the project terminal, as
required by the repository instructions. No sync, archive, commit, push, PR,
Railway action or deploy is part of this change.

## Rollback / reversibility

Removing the event registration and checkpoint calls restores the prior
diagnostic surface. No migration or persisted business-state change is
introduced.

## Deferred limitations

This change identifies the last observed core boundary; it does not prove why
that boundary stalls and does not fix the cause. A trace ending at
`business_dispatch_started` with no `llm_request` points to work before the
LLM client; an `llm_request` timeout points to the existing LLM transport
boundary; a completed pipeline with no outbox evidence points downstream.
Root-cause correction requires a separate approved change after the evidence
is collected.
