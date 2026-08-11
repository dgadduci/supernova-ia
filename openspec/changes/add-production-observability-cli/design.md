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

## Railway `--json` envelope evidence (recorded during the controlled
production validation)

The controlled production query surfaced two concrete behaviours of the
Railway CLI `--json` output that the CLI had to tolerate without breaking
the catalogue contract:

1. **Structured events are passed through as JSON objects.** A line that the
   application wrote as ``{"event":"outbound_attempt_outcome",...}`` is
   returned by ``railway logs --json`` with two extra platform envelope
   fields appended: ``level`` (always the string ``"info"``) and ``message``
   (the empty string). Example observed shape:

   ```json
   {"component":"outbound_dispatch","event":"outbound_attempt_outcome",
    "level":"info","message":"","outcome":"no_due_row","schema_version":1,
    "timestamp":"2026-08-11T18:44:05.822058+00:00"}
   ```

   The two extra fields are platform metadata; they are NOT part of the
   catalogue. The CLI strips them before catalogue validation so the
   strict allowlist is preserved and the platform can evolve the envelope
   without leaking into operator output.

2. **Plain stdout lines are wrapped into the same envelope shape.** A line
   the application wrote as free-form stdout (for example the worker
   cycle summary ``provider_worker_cycle cycle_index=...`` or the
   dispatcher per-attempt line ``mensaje_id=... outcome=sent``) is
   returned as ``{"level":"info","message":"<the original text>",
   "timestamp":"..."}``. The CLI does NOT try to parse the
   ``message`` text as a structured event: it only parses the message
   when the original stdout line was itself JSON, and it never reflects
   the wrapped text back to the operator.

3. **``--filter` is NOT a viable source-side filter for our catalogue.**
   Railway's text-search filter (``-f``/``--filter``) operates on the
   envelope ``message`` field. For our structured events that field
   is the empty string, so a source-side filter against the event
   name would always return zero matches even though the events are
   present in the bounded ``--lines`` window. The CLI therefore
   applies ``--event`` ONLY as a local filter on the parsed events
   (``_match_event``) and never forwards it as ``--filter`` to
   Railway. ``--lines`` and ``--since`` remain the only
   source-side bounds the CLI pushes to Railway.

The CLI therefore has a single envelope-stripping helper applied at the
catalogue boundary and a single local-filter chain (``--event``,
``--level``, ``--since``) applied to the parsed events. The catalogue
itself is unchanged; the helper only removes the two platform-known
envelope fields before validation so the allowlist remains strict.

## Tests and constraints

Focused unit tests cover event allowlists/redaction, formatter failure safety,
CLI argument construction, bounded parsing, no-result and Railway error
classification, and retention inventory state/age counts. Source-boundary
tests confirm no message fields, credentials, direct network calls outside
the Railway CLI invocation, SQLAlchemy in the log-query CLI or transaction
calls in emitters. No migration is expected.
