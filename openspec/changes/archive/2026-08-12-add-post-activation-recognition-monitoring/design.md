# Design: post-activation product-recognition monitoring

## Decision

Reuse `python -m backend.cli.query_production_logs` as the only production
reader. The change adds an operator procedure, not an application pipeline or
automation. Each window is independently authorized, explicitly targeted and
finite.

## Per-window procedure

```text
explicit authorization + explicit Railway target
  -> bounded CLI query for shadow_product_recognition
  -> catalogue validation and local event filter
  -> safe aggregate only
  -> human decision: record / investigate separately / stop
```

The command uses the existing required `--project`, `--environment`,
`--service`, `--since`, `--event shadow_product_recognition` and a finite
`--limit` (at most 1000). It is never invoked as a daemon or scheduled task.

## Aggregate contract

For a successful non-empty response, the operator may retain only:

- query target identifiers, `since` boundary and limit;
- total validated event count;
- counts by `configured_mode`, `effective_mode`, `authoritative_strategy`,
  `hybrid_decision`, `fallback` and allowlisted `fallback_category`;
- count/min/max of each bounded latency field when present.

The raw events and the CLI's raw Railway source lines are not retained or
reprinted. A zero-count response is recorded verbatim as `inconclusive` and
does not trigger retry, traffic generation, a mode change or a conclusion
about business behavior.

## Decision and stop rules

| Observation | Required action |
| --- | --- |
| Valid empty response | Record as inconclusive; maintain state. |
| Valid events, no technical fallback | Record aggregates; require human decision before another window. |
| Valid events with technical fallback | Stop monitoring and open a separately authorized investigation; do not rollback automatically. |
| CLI invocation/contract failure | Stop; retain only safe failure category and request a separate decision. |

`unique`, `ambiguous` and `unknown` are valid observations and never trigger a
technical fallback response by themselves. Fuzzy remains the defined safe
fallback should a later separately authorized rollback be required.

## Privacy, transactions and reversibility

The procedure neither sends customer input nor opens database sessions. It
does not invoke Twilio or Ollama directly, and it changes no transaction
ownership. It excludes all unbounded values and raw logs. No operational state
is changed, so no rollback is required.
