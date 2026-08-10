# Automate durable provider processing

## Objective

Run the already durable inbound-processing and outbound-dispatch passes
automatically in Railway so a valid WhatsApp receipt reaches its existing
outbox and provider delivery without an operator invoking two CLIs by hand.

## Verified current execution path

Production has validated this path:

`Twilio webhook -> receipt + inbound work item -> run_inbound_processing ->
outbox -> run_outbound_dispatch -> delivered`.

Both CLIs are bounded and reuse lease-protected repositories. The WhatsApp
guided-order closure was completed with one client: the resulting draft order
was confirmed exactly once as `ingresado`, with its selected payment and
delivery. The manual procedure also demonstrated the operational limitation:
pending work is delivered only when an operator runs each pass, and delivery
order between separate receipts is not a global customer-visible ordering
guarantee.

## Scope

- Add one opt-in, long-running worker entry point that repeatedly invokes the
  existing bounded inbound CLI pass and then the existing bounded outbound CLI
  pass.
- Start that worker as a supervised child of the existing Railway entrypoint
  only when an explicit environment flag is enabled.
- Add typed, validated non-secret settings for enablement, poll interval and
  bounded inbound/outbound work per cycle.
- Preserve the existing manual CLIs as operational/recovery controls.
- Add safe cycle-level observability and focused worker/entrypoint tests.

## Non-goals

- No migration, queue schema change, new receipt/outbox pipeline, FastAPI
  background task, LangGraph, separate Railway service, or external scheduler.
- No changes to Twilio webhook acknowledgement, LLM/product recognition,
  payment/delivery matching, retry policy, work ordering rules, or provider
  delivery callback handling.
- No attempt to make Twilio delivery order globally ordered across distinct
  receipts; this phase only removes manual polling.

## Shared boundary, fallback, and transaction ownership

The worker is an orchestrator of the two current CLI boundaries only. Inbound
lease/processing transactions remain owned by
`ProviderInboundMessageCoordinator`; outbound claim/send/finalization
transactions remain owned by `OutboundMessageDispatcher`. The worker MUST NOT
open a business transaction, create a session/pedido, send through Twilio
directly, or alter retry state.

`PROVIDER_PROCESSING_WORKER_ENABLED=false` is the authoritative default and
leaves current manual operation unchanged. Enabling it with invalid worker
configuration or missing outbound dispatch configuration MUST fail startup
before the web process receives traffic. Once running, a completed pass,
`no_due_row`, retryable work and terminal work are valid business/operational
outcomes and MUST NOT stop the loop. An unexpected worker exception is a
technical failure: it is logged with safe type/category metadata and causes the
supervisor to restart the service, relying on existing leases for recovery.

The worker must not fall back to a second queue, inline webhook processing,
unbounded drain, direct send, or reordered per-conversation processing.

## Observability

Each cycle emits only safe counts/outcomes, duration and configuration bounds.
It MUST NOT log inbound or outbound bodies, E.164 destinations, prompts,
provider signatures, URLs, account identifiers, tokens, or environment dumps.
Existing CLI summaries and receipt/outbox states remain the source of detailed
operational evidence.

## Expected files and focused validation

Expected implementation surface:

- `backend/config/settings.py` and focused settings tests;
- a new worker CLI plus focused tests;
- `docker-entrypoint.sh` and an entrypoint-oriented test/seam if one is needed;
- this OpenSpec change and the new capability spec.

The user will run locally:

```bash
PYTHONPATH=. venv/bin/python -m pytest backend/tests/test_run_inbound_processing_cli.py backend/tests/test_run_outbound_dispatch_cli.py backend/tests/test_provider_processing_worker.py backend/tests/test_settings.py -q
PYTHONPATH=. venv/bin/python -m ruff check backend/config/settings.py backend/cli/run_provider_processing_worker.py backend/tests/test_provider_processing_worker.py
PYTHONPATH=. venv/bin/python -m compileall -q backend/config backend/cli/run_provider_processing_worker.py
openspec validate automate-provider-processing-worker --strict
```

## Rollback and deferred limitations

Disable `PROVIDER_PROCESSING_WORKER_ENABLED` and redeploy to return to the
manual CLI operation without a data migration. Existing leases, retries and
durable rows remain valid. A future phase may add customer-visible ordering
semantics, an operator suppression state for stale outbox rows, metrics, or a
separate scalable worker service.
