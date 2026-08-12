# Proposal: safe product-recognition decision observability

## Why

Existing product-recognition shadow observations were not safely queryable by
the bounded production-observability CLI: the recorder used Python log extras
that included decision data unsuitable for production queries. Operators need
bounded evidence that distinguishes normal hybrid business outcomes from
approved technical fallback without exposing customer or commerce data.

## What Changes

- Add the closed `shadow_product_recognition` event to the shared operational
  event catalogue and route the existing recorder through that boundary.
- Allow only sanitized mode, strategy, decision, fallback and aggregate
  latency fields; reject all other recognition data.
- Make the existing bounded production-log CLI validate and return the new
  event through its normal catalogue path.

## Objective

Make the existing `shadow_product_recognition` observation queryable through
the bounded Railway CLI without exposing customer or commerce data. The change
adds one versioned, allowlisted event contract for recognition observations so
operators can distinguish normal hybrid decisions from technical fallback.

## Current execution path

`get_product_recognizer(load_settings())` constructs the shared recognizer.
`ShadowMetricsRecorder.record(...)` receives one observation from the fuzzy,
shadow, or hybrid-authoritative path and currently writes a Python log record
with both safe diagnostic fields and fields unsuitable for production queries
(IDs, scores and correlation data). `backend.observability.events` and
`backend.cli.query_production_logs` already provide the single safe stdout
event catalogue and bounded Railway reader, but do not catalogue this event.

## Scope

- Add a `shadow_product_recognition` event to the existing versioned
  operational-event catalogue and make the recorder emit it through that
  existing shared boundary.
- Allow only configured/effective mode, authoritative strategy, hybrid
  decision category, fallback boolean/category, and non-negative aggregate
  latency values already calculated by the recognizer.
- Extend the existing CLI's validated parsing/filtering through the catalogue;
  retain explicit Railway target, `--since`, event, level and finite-limit
  bounds.
- Add focused privacy, event-contract and CLI tests.

## Non-goals

No recognizer decision, policy, fallback condition, candidate set, commerce
isolation, transaction ownership, handler, pending-context, setting, Railway
variable or deployment changes. No endpoint, database table, migration,
telemetry vendor, dashboard, raw-log reader, Twilio traffic or synthetic
recognition request.

## Shared boundary and fallback

`backend.observability.events` remains the sole production-log contract and
`ShadowMetricsRecorder` becomes its recognition-specific caller; a second
logger/formatter or query pipeline is forbidden. Valid hybrid business
outcomes (`unique`, `ambiguous`, `unknown`) are observations, never fallback.
Only the existing sanitized technical fallback categories may mark fallback.
If event construction/emission fails, existing observability failure handling
must swallow the error and never change recognition or customer processing.
Absent queried events are inconclusive and must not cause retries, mode change
or recognition conclusions.

## Transaction ownership and observability

The recorder and emitter own no session and never commit, rollback, flush,
close or begin a transaction. The new event must exclude text, E.164,
`commerce_id`, product/candidate IDs, correlation IDs, scores, vectors,
prompts, payloads, policy weights/thresholds and raw exception content.

## Expected files

- `backend/observability/events.py` and exports for the allowlisted event.
- `backend/services/shadow_metrics_recorder.py` for the single safe emitter
  call.
- Focused observability, recorder and query-CLI tests.
- This change's OpenSpec artifacts and the resulting synced specification.

## Focused validation

```text
PYTHONPATH=. venv/bin/python -m pytest backend/tests/test_production_observability.py backend/tests/test_shadow_metrics_recorder.py backend/tests/test_query_production_logs.py -q
PYTHONPATH=. venv/bin/python -m ruff check backend/observability/events.py backend/services/shadow_metrics_recorder.py backend/tests/test_production_observability.py backend/tests/test_shadow_metrics_recorder.py backend/tests/test_query_production_logs.py
PYTHONPATH=. venv/bin/python -m compileall -q backend/observability/events.py backend/services/shadow_metrics_recorder.py
openspec validate add-safe-product-recognition-observability --strict
```

## Rollback and deferred limits

The change is reversible by removing the event integration; it does not alter
stored data or Railway state. A later, separately authorized read-only query
may inspect a bounded production window. Aggregation, dashboards, alerting,
retention changes and any conclusion about recognition quality remain deferred.
