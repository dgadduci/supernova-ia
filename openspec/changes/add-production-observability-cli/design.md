# Design: production observability CLI and retention governance

## Decision

Keep Railway as the log store and Python logging as the emitter. Add a small
shared formatter for explicitly allowlisted JSON operational events on stdout;
do not introduce a parallel storage or observability pipeline. The CLI is an
operator convenience wrapper around the already authenticated Railway CLI,
not an application endpoint and not a direct PostgreSQL inspector.

## Event boundary

Each event has `event`, `schema_version`, `component`, `outcome` or
`failure_category`, and timestamp supplied by the logging/runtime surface.
Optional fields are restricted per event to: `outbox_id`, existing safe
correlation id, attempt count, durable state, safe provider code, HTTP status,
safe exception type and elapsed milliseconds. Formatter input is typed; any
unknown field is rejected before emission.

The first covered events are provider worker cycles, outbound attempts,
Twilio callback outcomes, QueryLlm/Ollama request lifecycle and database
technical boundary failures. Existing business-state logic stays unchanged.
Callback observations include the safe existing outbox id and monotonic
outcome, enabling the controlled production validation performed today to be
queried as `accepted` then `delivered` when Twilio sends both callbacks.

## Query CLI

`python -m backend.cli.query_production_logs` accepts explicit Railway target
arguments plus bounded `--since`, `--event`, `--level` and `--limit` filters.
It invokes only the local Railway CLI JSON-log query, parses the shared JSON
event contract and writes bounded safe JSON lines or a small safe summary.
It never accepts credentials, never prints command environment values and
never passes raw Railway lines through on a parse error.

The CLI has no database session, no HTTP endpoint and no fallback to direct
Twilio/LLM calls. Its command exit classes distinguish no results from local
argument error, Railway invocation failure and event parsing failure.

## Retention

There are two intentionally separate policies:

1. Railway logs: configured and enforced by Railway according to the plan.
   The repository documents the selected finite window and CLI query limit;
   neither application code nor the CLI tries to delete log entries.
2. Durable provider-message data: inventory only in this change. The
   read-only inventory groups records by age and safe state and returns counts
   only. It does not select or reveal message text/address values and does not
   delete data.

A later purge proposal may define a fixed period and explicitly permit a
two-step `--dry-run` then `--apply` command. It must preserve rows needed for
active leases, pending/retry work, idempotency windows and any legal/support
retention obligation; it needs its own data-integrity review and rollback
plan. Keeping operational logs forever is not required or desirable by
default: a finite platform window plus bounded queries is the appropriate
baseline, while durable data needs a separately approved lifecycle.

## Failure behavior

Formatting failures degrade to a safe local event with event name, component
and exception type; they never attach raw `exc_info` or mutate business work.
Railway query problems stop the CLI non-zero with a safe category. An absent
event never triggers a provider retry, customer-intent replay or order
mutation.

## Tests and constraints

Focused unit tests cover event allowlists/redaction, formatter failure safety,
CLI argument construction, bounded parsing, no-result and Railway error
classification, and retention inventory state/age counts. Source-boundary
tests confirm no message fields, credentials, direct network calls outside
the Railway CLI invocation, SQLAlchemy in the log-query CLI or transaction
calls in emitters. No migration is expected.
