# Proposal: production observability CLI and retention governance

## Objective

Make NovaOrders production diagnostics safely queryable from a terminal while
preserving the existing Python logging, Railway stdout/stderr capture, durable
outbox and transaction boundaries. Establish an explicit, finite retention
policy rather than treating operational logs and durable customer-message data
as the same thing.

## Current execution path

Application components use module-level Python loggers. Railway captures the
service process stdout/stderr and its CLI can query those deployment logs. The
provider worker emits cycle summaries; outbound dispatch emits a safe attempt
event; and the Twilio status callback emits a safe callback outcome. The
current runtime formatter does not establish one documented common JSON event
contract or a repository-owned query interface.

The PostgreSQL tables are different from logs: inbound receipts, processing
work and the durable outgoing outbox are operational records with idempotency,
lease and callback invariants. They must not be deleted as a side effect of
log retention.

## Scope

- Define one privacy-safe, versioned operational-event shape emitted to
  stdout for selected Twilio, worker, LLM/Ollama and database technical
  lifecycle events.
- Add a terminal CLI that queries the existing Railway log source through the
  installed/authenticated Railway CLI, with explicit project/environment/
  service selection, time/event/level filters and bounded JSON output.
- Standardize the safe fields needed to correlate an inbound processing,
  outbox attempt and delivery callback when such identifiers exist.
- Document operator queries for delivery failures, worker health, LLM/Ollama
  failures and database technical failures.
- Define retention ownership: Railway/platform retention is configured at the
  platform/account level; the application does not delete individual Railway
  log lines. The CLI reports the active retention policy and warns when a
  requested window exceeds it.
- Add a read-only inventory command for durable provider-message records by
  age and state, so a later data-retention decision has evidence without
  exposing message bodies or deleting data.

## Non-goals

- No new telemetry vendor, database log table, message pipeline, queue, LLM,
  LangGraph, alerting service or dashboard.
- No changes to Twilio delivery, retries, rate/concurrency policy, callbacks,
  order mutation or caller-owned transactions.
- No automatic purge and no deletion of receipts, processing records, outbox
  rows, orders or conversations in this change.
- No message body, E.164 address, credential, token, signed URL, provider
  payload, prompt, model output, raw exception text or traceback in emitted
  events or CLI output.

## Authoritative outcomes and fallback

An emitted event is an operational observation, not business authority. The
database remains authoritative for inbound processing, outbox and callback
state; Twilio remains authoritative for provider acceptance/delivery status.
The query CLI returns one of: successful bounded result, no matching events,
local validation/configuration error, Railway CLI invocation failure, or
unparseable provider output. It must not retry, mutate state or infer a
delivery state from an absent log line.

If JSON event parsing is unavailable, the CLI returns a clear technical
failure and recommends the documented Railway query; it must not print raw
provider output as a fallback because that could disclose sensitive content.

## Transaction ownership and observability

Emitters do not open transactions or change commit/rollback ownership. The
read-only inventory uses a caller-owned session and performs no mutation.
Events carry only allowlisted metadata such as event name/version, timestamp,
component, outcome/category, duration bucket or milliseconds, HTTP status,
safe provider code, safe exception type, outbox id and a non-reversible
correlation identifier where already available.

## Expected files

- `backend/observability/` safe event formatter/schema helpers.
- `backend/cli/query_production_logs.py` and focused tests.
- `backend/cli/inventory_provider_message_retention.py` and focused tests.
- Narrow changes in existing Twilio worker/dispatcher/callback and LLM/Ollama
  seams only where an allowlisted event is missing.
- Settings/documentation for log output, query defaults and Railway retention
  ownership; no migration.
- `TECHNICAL_DEBT.md` updated to close or narrow this item only after the
  approved work is complete.

## Focused validation

```text
PYTHONPATH=. venv/bin/python -m pytest backend/tests/test_production_observability.py backend/tests/test_query_production_logs.py backend/tests/test_provider_message_retention_inventory.py -q
PYTHONPATH=. venv/bin/python -m ruff check backend/observability backend/cli/query_production_logs.py backend/cli/inventory_provider_message_retention.py backend/services/outbound_message_dispatcher.py backend/routers/twilio_delivery_callback.py backend/cli/run_provider_processing_worker.py
PYTHONPATH=. venv/bin/python -m compileall -q backend/observability backend/cli/query_production_logs.py backend/cli/inventory_provider_message_retention.py
openspec validate add-production-observability-cli --strict
```

## Rollback and deferred limits

The formatter and query CLI are reversible application changes. Disabling
structured operational output restores prior logging; it never alters durable
records. Railway log retention is reversible through platform configuration.

Deleting durable message data remains deferred to a separate, approved data
retention change after the user chooses a period (for example 30/90 days),
legal/support needs, eligible terminal states, backup behavior and a
dry-run/apply/rollback procedure.
