# Diagnose provider flow with a live read-only audit

## Objective

Provide an operator-run Python auditor for the integrated `supernova-ia`
Railway service that can be started before a controlled Twilio test and poll
the durable provider-flow rows while messages arrive. The auditor must show
where each turn stops without changing business state.

## Current execution path

`T-C → NovaOrders ingress → recepciones_mensajes_proveedor →
procesamientos_mensajes_proveedor → worker/coordinator → QueryLlm →
mensajes_proveedor_salientes → outbound dispatcher/T-C`.

The direct generate probe already passes 10/10, including the complex prompt.
The remaining uncertainty is the worker-side path and its durable
finalization/outbox effects.

## Scope

- Add one standalone operator CLI that reuses existing SQLAlchemy settings,
  session factory and ORM models.
- Poll read-only joins across receipt, processing and outbound rows.
- Detect and print safe lifecycle snapshots and changes for rows created after
  the auditor starts, including numeric row ids, opaque receipt fingerprint,
  processing state, attempts, safe failure category/code, LLM outcome and the
  existing LLM requested/finished timestamps.
- Show whether a processed turn has zero, one or multiple outbound rows.
- Support an explicit polling interval and bounded duration, with clean Ctrl-C
  termination. The command must be suitable for a Railway service shell.
- Document the exact command and how to correlate the printed timeline with
  the sent Twilio messages.

## Non-goals

- No worker, coordinator, QueryLlm, Twilio, T-C, outbox dispatcher or schema
  changes.
- No database writes, commits, row locks, lease claims, retries, replays or
  repairs.
- No reading or printing of message bodies, phone numbers, outbound bodies,
  provider SIDs, signatures, URLs, prompts, responses, credentials or raw
  exception text.
- No attempt to consume Railway stdout or replace Railway log inspection. The
  auditor reports durable database evidence only.

## Decision boundary

The output must distinguish evidence from inference:

| Durable observation | Safe interpretation |
| --- | --- |
| receipt absent | ingress/acceptance evidence is not persisted yet, or the test was not received |
| receipt present, processing absent | acceptance-to-staging boundary is incomplete |
| processing pending with no LLM timestamps | worker has not reached the LLM boundary for that row |
| LLM requested timestamp present, no finished timestamp | LLM attempt remains in flight or the process stopped before finalization |
| LLM finished with safe outcome, processing non-terminal | finalization/transaction path needs investigation |
| processing processed, outbound count zero | response/outbox mapping produced no durable outbound row |
| outbound row present | outbound dispatch is a separate subsequent boundary |

The auditor must label these as observations and must not claim a root cause
from a single snapshot.

## Privacy and transaction ownership

The auditor owns no business transaction. Each polling iteration opens a
read-only application session, performs bounded SELECTs, closes the session,
and never calls `commit`, `flush`, `update`, `delete`, lease, or dispatcher
code. Output contains only safe numeric ids, closed states/categories,
bounded counts, opaque fingerprints and timestamps.

## Expected files

- `backend/scripts/audit_provider_flow_live.py` (new standalone CLI).
- One focused test module for filtering, snapshots, transitions, duration,
  Ctrl-C/clean termination and privacy.
- `backend/development/railway.md` for the operator command and interpretation.

## Rollback and deferred limitations

Removing the CLI, tests and documentation fully reverts the change. The
auditor cannot observe transient stdout-only events such as a live
`llm_request` event; it relies on the durable processing LLM timing fields and
state transitions. Railway log correlation remains a separate operator step.
