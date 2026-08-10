## Why

The controlled local pilot exposed a customer-facing inconsistency: a single
quantity request for the same presentation was processed into the correct
final quantity but emitted two successive confirmations. The deployed provider
outbox uses a parallel response-mapping path, so this must be corrected at a
shared response boundary before any controlled WhatsApp inbound case.

## Objective

Emit one final customer confirmation for a consecutive group of equivalent,
executed `agregar_producto` results, while preserving every already-completed
domain mutation and all other response behavior.

## Current execution path

The transactional processor returns ordered `ProcessedIntent` items. The local
HTTP/CLI path maps them in `incoming_message_response_orchestrator`; the
provider outbox maps them in `outbound_response_mapper`. Both currently build
one response per item. When classification supplies two consecutive additions
for the same presentation, the first response reports an intermediate total
and the second reports the final total.

## What Changes

- Add one pure shared response-coalescing helper in the existing response
  package and use it from both response-mapping paths.
- Coalesce only consecutive items that are all `agregar_producto`, `executed`,
  and have the same valid `producto_presentacion_id` in resolved data.
- Render exactly the terminal item of each coalesced group, whose
  `cantidad_final` is authoritative for the confirmation.
- Add focused regression coverage for local responses and provider outbox
  mapping.

## Scope and non-goals

This does not alter classifier output, product recognition, domain mutation,
quantity arithmetic, transaction ownership, ordering of distinct operations,
pending candidate sets, schemas, migrations, Twilio routing, dispatch, or
live traffic. It deliberately does not hide non-consecutive duplicates or
duplicates with different presentation identifiers.

## Shared boundary, fallback and outcomes

The shared pure helper is the only place that recognizes an equivalent
consecutive addition group. A valid group yields the terminal response. Any
missing/non-integer presentation ID, non-executed status, different intent, or
different ID is not a group and follows the existing one-item-per-response
behavior. Technical exceptions continue to propagate unchanged; fuzzy remains
the product-recognition fallback and is outside this change.

## Transaction ownership and observability

The helper is read-only and creates no database work. Existing transactional
processor and outbox owners retain commits/rollbacks. Focused tests make the
grouping decision observable; no message bodies, phone numbers, or live
provider data are logged or persisted by this change.

## Expected files

- `backend/intents/responses/` shared coalescing helper.
- `backend/intents/orchestration/incoming_message_response_orchestrator.py`.
- `backend/services/outbound_response_mapper.py`.
- Focused response-orchestrator and outbox-mapper tests.
- This OpenSpec change and its delta.

## Focused validation

The user will run focused pytest for both paths, Ruff and `compileall` on
touched Python files, strict OpenSpec validation, and `git diff --check`.
No live Twilio/WhatsApp run is authorized by this change; the pending pilot
must repeat the local happy path only after review of validation output.

## Rollback and deferred limitations

The change is reversible by deploying the prior revision; it creates no
durable state. Diagnosing why the classifier produced duplicate intents,
changing classifier multiplicity, or collapsing non-consecutive operations is
deferred to separately approved work.
