# Proposal: diagnose provider worker inbound path

## Objective

Identify the exact stage that stalls or fails when a provider inbound message
is processed by the automatic worker, despite the same production
`IntentClassifier` and Ollama semantic-embedding probes succeeding repeatedly
outside the worker. The investigation SHALL add bounded, privacy-safe evidence
to the existing worker/provider observability path without changing business
outcomes, retry policy, transactions, LLM configuration, or provider
transport.

The observed production symptom is a third Emulator turn that was accepted by
T-C and the Emulator, remained displayed as `processed`, produced no
`Messages.json` outbound request, and was followed by a roughly 180-second
LLM-boundary failure. The direct classifier and semantic embedding probes now
complete ten consecutive calls, including the complex order-modification
message, with zero delay and normal latency.

## Current execution path

The isolated T-C accepts the signed inbound and forwards it to NovaOrders. The
core ingress commits one provider receipt and one pending processing item. The
automatic worker then runs the bounded inbound pass, which leases the item,
re-evaluates commerce availability, stages the active session and draft pedido
when required, and invokes `process_incoming_message`.

Depending on session context, that pipeline enters the pending-context path or
the initial classifier/orchestration path. Product recognition may call the
Ollama semantic embedding endpoint. The pipeline then maps responses and
stages receipt-linked outbound rows. The coordinator finalizes the processing
row and commits; only after that does the bounded outbound pass contact the
T-C, which can cause the Emulator to record `Messages.json`.

## Scope

- Add one closed `provider_inbound_stage` event through the existing
  observability catalogue for the bounded coordinator stages: availability,
  session/order staging, business pipeline, outbound staging and processing
  finalization.
- Emit stage-start evidence before each potentially long-running seam and
  matching completion/failure evidence only when that seam returns.
- Correlate provider-scoped `llm_request` and `embedding_request` events with
  the same already-authorized opaque synthetic inbound value, so generation
  and semantic embedding activity can be separated for one turn.
- Preserve the existing production log parser/query surface and add focused
  tests proving event order, correlation, bounded values and privacy.
- Document how to interpret a stage start without a matching completion and
  how to compare it with the existing processing outcome, timing timeline and
  worker-liveness events.

## Non-goals

- No change to the LLM model, URL, timeout, prompt, generation options,
  embedding model, embedding URL, embedding timeout or Tailscale configuration.
- No change to the classifier, semantic recognizer, fuzzy fallback, candidate
  set, order/session business rules, response mapper, outbound staging,
  dispatcher, T-C, Twilio Emulator or HTTP/TwiML contracts.
- No automatic timeout, cancellation, replay, fallback response, lease
  release, retry, worker restart or recovery based only on missing diagnostic
  evidence.
- No new database columns, migrations, dashboard, alerting service, cron,
  parallel worker or alternate processing pipeline.
- No raw message text, prompts, model responses, vectors, phone numbers,
  pedido/session/client identifiers, provider IDs, URLs, credentials, tokens,
  exception messages or tracebacks in events or reports.
- No commit, sync, archive, Railway change, environment-variable change or
  deployment as part of this change.

## Shared boundary

The provider coordinator remains the single owner of the leased inbound
processing boundary and its caller-owned SQLAlchemy transaction. The existing
`QueryLlm` and `OllamaEmbeddingClient` remain the only model transport seams.
The new stage event and correlation context are observational wrappers around
those seams; they do not create a second request, transaction, lease or worker
path.

## Authoritative outcomes and interpretation

- A stage `started` event proves that the worker reached that boundary.
- A matching `completed` or `failed` event proves that the boundary returned.
- The absence of a matching terminal stage event is evidence of an incomplete
  or externally interrupted call, not evidence that the stage succeeded.
- `provider_inbound_processing_outcome` remains authoritative for durable
  processed, retryable, terminal, unavailable and lease-lost outcomes.
- `provider_worker_liveness` remains authoritative for worker cycle and pass
  boundaries. The new event refines the inbound pass and does not replace it.

## Fallback behavior

Event validation, correlation-context setup and serialization are best effort.
If any diagnostic operation fails, the existing business call continues with
its current behavior. A stage that does not return receives no fabricated
completion or failure event, and no diagnostic absence may trigger recovery.
Existing exception, rollback, lease and retry handling remains authoritative.

## Transaction ownership

The coordinator retains ownership of commit, rollback, lease finalization and
body scrubbing. The observability code SHALL not begin, commit, rollback,
flush, close or open a side transaction. Stage events are emitted around
existing boundaries and carry no durable business data.

## Observability and privacy

The new event SHALL use only closed stage/outcome values, bounded elapsed
milliseconds, a safe exception type name when applicable, and the existing
bounded opaque correlation value. Provider-scoped LLM and embedding events may
carry that same correlation value, but never request content or response data.
Emission failures remain fail-soft and SHALL not print rejected payloads.

## Expected files

- `backend/observability/events.py`
- `backend/observability/__init__.py`
- A minimal provider correlation-context seam under `backend/observability/`
  or `backend/llm/`, only if needed to share the existing opaque value between
  generation and embedding clients
- `backend/services/provider_inbound_message_coordinator.py`
- `backend/llm/query_llm.py`
- `backend/llm/embedding_client.py`
- Focused tests in the provider coordinator, production observability,
  QueryLlm and Ollama embedding-client suites

## Focused validation

Run in the user's local terminal after implementation:

```text
PYTHONPATH=. venv/bin/python -m pytest backend/tests/test_provider_message_receipt_core_integration.py backend/tests/test_provider_processing_worker.py backend/tests/test_production_observability.py backend/tests/test_query_llm.py backend/tests/test_ollama_embedding_client.py -q
PYTHONPATH=. venv/bin/python -m ruff check backend/observability/events.py backend/observability/__init__.py backend/services/provider_inbound_message_coordinator.py backend/llm/query_llm.py backend/llm/embedding_client.py backend/tests/test_provider_message_receipt_core_integration.py backend/tests/test_provider_processing_worker.py backend/tests/test_production_observability.py backend/tests/test_query_llm.py backend/tests/test_ollama_embedding_client.py
PYTHONPATH=. venv/bin/python -m compileall -q backend/observability/events.py backend/observability/__init__.py backend/services/provider_inbound_message_coordinator.py backend/llm/query_llm.py backend/llm/embedding_client.py
openspec validate diagnose-provider-worker-inbound-path --strict
git diff --check
```

## Rollback and deferred limitations

The change is source-only and reversible by removing the event registration,
stage wrappers and correlation propagation. It does not alter stored records
or production configuration. It does not fix a discovered worker, transaction,
recognizer or upstream infrastructure defect; that correction requires a
separate approved change after the evidence identifies the failing boundary.

