# Design: diagnose provider-worker progress stalls

## Decision

Extend the existing `provider_worker_liveness` vocabulary rather than create a
second event family, database record or monitor. Two nested phases give the
missing resolution while preserving the current cycle/phase grammar and the
worker's direct, synchronous control flow.

```text
cycle_started
  inbound started
    SIGALRM handler installed and timer armed
    inbound_runner started
      run_inbound_processing_main(bound)
    inbound_runner completed | failed
  inbound completed | failed
  outbound started/completed | failed
  cycle_summary started/completed | failed
cycle_completed
  sleep started/completed | failed
next cycle_started
```

The active `diagnose-core-inbound-pre-llm-stall` change starts inside
`run_inbound_processing_main`. This change must not duplicate its coordinator
checkpoints or modify its event contract.

## Liveness contract

Add `inbound_runner` and `cycle_summary` to the closed phase allowlist of
`provider_worker_liveness`. Existing outcomes remain unchanged:
`phase_started`, `phase_completed` and `phase_failed` require a phase;
`cycle_started` and `cycle_completed` do not. Existing bounds for
`cycle_index`, `elapsed_ms`, failure category and exception type apply without
new fields.

Both phases follow the existing semantics:

| Phase | Start | Completion | Failure |
|---|---|---|---|
| `inbound_runner` | immediately before calling the injected runner, after SIGALRM is armed | only after runner returns | only if runner raises, then re-raise unchanged |
| `cycle_summary` | immediately before the existing writer call | only after writer returns | only if writer raises, then re-raise unchanged |

The timeout guard setup itself has no new phase: it is deliberately bracketed
by the existing `inbound` start and `inbound_runner` start. Thus the absence
of `inbound_runner` start is the only safe evidence that execution did not
reach the real runner after the outer inbound boundary began.

## Implementation boundaries

1. `_run_inbound_with_timeout` accepts the already existing cycle context only
   through a narrowly scoped internal emission seam, or is split into a small
   private helper that retains its public test/caller behavior. It must install
   SIGALRM and arm `ITIMER_REAL` exactly as today before emitting
   `inbound_runner` start and calling the runner.
2. Its `finally` continues to cancel the timer and restore the signal handler
   exactly as today. Neither completion nor failure is fabricated when a timer
   interrupts execution.
3. `run_cycle` wraps only the existing `cycle_summary_writer(summary)` call in
   `cycle_summary` phase evidence. Aggregate production, summary construction,
   outbound behavior and return value retain their current order.
4. The existing `inbound`, `outbound`, `sleep` and cycle emissions are not
   removed, renamed or reordered except for the documented nested events.

No call site obtains a new database or transport dependency. Event emission
remains best effort through `_emit_liveness_event` and must not change the
exception which owns worker restart behavior.

## Partial trace interpretation

| Last evidence | Supported conclusion | Not supported |
|---|---|---|
| `inbound` started | bounded pass began | that a row was claimed or LLM was reached |
| `inbound_runner` started | runner invocation began after timer arming | that the coordinator or LLM was reached |
| `inbound_runner` completed | whole inbound CLI pass returned | that a particular item succeeded |
| `cycle_summary` started | inbound/outbound sequence and summary construction returned | that summary logging returned |
| `cycle_summary` completed | writer returned | why a later cycle is absent |
| existing `sleep` started | normal cadence sleep began | that sleep will return |

The existing durable audit, core checkpoint change and LLM transport events
remain the only sources for deeper, item-level conclusions.

## Failure, privacy and transactions

If a runner or writer raises, emit safe `phase_failed` evidence then propagate
the original exception through the existing supervisor path. If telemetry
cannot be emitted, do not call the seam again and do not alter the business
result. Events must reject arbitrary phase tokens, IDs, text, URLs, proxy
details, exception messages and tracebacks. No transaction control is added.

## Tests

Focused tests must prove:

- the two new phase tokens round-trip through production observability and all
  former allowlist/forbidden-field guarantees remain;
- normal event order nests `inbound_runner` in inbound and places
  `cycle_summary` between outbound completion and cycle completion;
- an inbound runner failure produces `inbound_runner` and outer inbound
  failure evidence, no fabricated completions and no outbound work;
- summary-writer failure produces only `cycle_summary` failure after the
  already completed runner phases and preserves the existing re-raise path;
- fail-soft telemetry does not invoke a runner/writer more than once or alter
  timeout/signal restoration behavior;
- no event contains a customer, provider, database or content value.

## Operational use

`backend/development/railway.md` will document a bounded, read-only query for
the structured liveness event and its cycle ordering. It must not display raw
provider payloads or modify Railway state. Operators compare timestamps to the
configured poll interval; they must not infer a recovery action from a missing
event.
