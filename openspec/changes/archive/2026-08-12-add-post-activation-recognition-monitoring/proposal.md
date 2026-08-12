# Proposal: post-activation product-recognition monitoring

## Why

Production is healthy in `hybrid_authoritative` mode with an eligible loaded
policy, but the two approved bounded recognition-observability windows returned
no events. Empty bounded results are correctly inconclusive: they do not prove
either recognition behavior or a lack of traffic. Operators need a repeatable,
privacy-safe procedure for collecting only the existing closed observations
when real traffic naturally produces them.

## What Changes

- Define an operator runbook for a finite, separately authorized,
  read-only query of `shadow_product_recognition` through the existing
  `query_production_logs` CLI.
- Define a closed aggregate interpretation of returned events: counts by
  configured/effective mode, authoritative strategy, hybrid decision and
  technical fallback category; no raw event retention.
- Define stop conditions and the required human decision after each window.

## Objective

Establish a minimal post-activation monitoring procedure for authoritative
hybrid product recognition using the existing versioned event catalogue and
bounded Railway query path, without changing runtime behavior or generating
traffic.

## Current execution path

`ShadowMetricsRecorder` emits one closed `shadow_product_recognition` event
per existing observation through `backend.observability.events`.
`backend.cli.query_production_logs` obtains a bounded Railway JSON window,
validates each candidate through that catalogue and returns only validated
events. The current production verification confirmed deploy, policy, factory
and health; its recognition query returned an empty, inconclusive result.

## Scope

- Document a fixed per-window operator procedure using an explicit project,
  environment, service, `--since`, event filter and finite `--limit`.
- Permit only aggregate evidence derived from validated events: event count,
  closed category counts, bounded latency summaries and the queried time
  boundary/limit.
- Require explicit authorization for every production window and a recorded
  human decision after it.

## Non-goals

No code, tests, settings, deployment, Railway mutation, rollout, rollback,
synthetic recognition request, Twilio traffic, dashboard, alert, telemetry
vendor, persistence, migration, retention policy, recalibration, policy
change, candidate analysis, customer or commerce data query.

## Shared boundary, fallback and transactions

The existing `query_production_logs` catalogue remains the sole query boundary;
direct Railway raw-log analysis and a parallel formatter are forbidden. Empty
windows remain inconclusive. `unique`, `ambiguous` and `unknown` are business
outcomes, not fallback. Only the event's existing allowlisted technical
fallback categories may be counted as fallback. The procedure opens no
database session and owns no commit, rollback, flush, close or transaction.

## Observability and stop conditions

The recorded evidence excludes customer text, E.164, commerce/candidate IDs,
correlation IDs, scores, vectors, prompts, payloads, policy values, raw
exceptions and raw Railway lines. Stop the window and request a separate
decision if the CLI reports a contract/parse failure, an unauthorized target,
an event outside the closed shape, or a technical fallback category that needs
operational investigation. Do not change mode or retry with traffic merely
because a window is empty.

## Expected files

- This change's `proposal.md`, `design.md`, specification delta and `tasks.md`.
- No application files.

## Focused validation

```text
openspec validate add-post-activation-recognition-monitoring --strict
git diff --check
```

## Rollback and deferred limits

This documentation-only change is reversible by removing the procedure and
does not mutate production state. Dashboards, automated scheduling, alerting,
traffic generation, statistical quality conclusions and any rollback decision
remain deferred.
