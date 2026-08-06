## Why

NovaOrders has a complete local incoming-message pipeline, but its caller already
knows `comercio_id` and `cliente_id`. A WhatsApp transport must resolve its
destination channel and commerce before the classifier, recognizers, handlers,
catalog or order flow runs. Phase 5.1 establishes that routing foundation
without connecting Twilio or changing the existing local endpoint.

## Objective

Introduce the persistent channel model and a pure, database-backed
dedicated-channel resolver. The model supports the approved future shared
channel design through opaque, non-reassignable routing-code reservations.

## Review correction (2026-08-06)

The first implementation must be corrected before approval. Its lifecycle
service and new-table repositories call `Session.flush()`, despite the approved
transaction boundary forbidding `commit`, `rollback`, `begin`, and `flush` in
Phase 5.1. The declarative `CanalWhatsapp` metadata also omits the partial
unique provider/destination index that the migration creates, leaving schema
metadata divergent from the database.

## Current execution path

`POST /comercios/{comercio_id}/clientes/{cliente_id}/incoming-messages`
resolves an existing `Session` and delegates to
`process_incoming_message_with_responses`. `Session` requires a non-null
`id_comercio` and the transactional message processor commits its own work.
Neither can represent a customer who has not selected a commerce.

## Scope

- Add `CanalWhatsapp` as the canonical, provider-scoped destination-number
  authority, with `dedicated` and `shared` modes.
- Model a dedicated channel by direct `id_comercio_exclusivo`; use
  `ComercioCanalCompartido` only for shared membership and routing-code
  reservation.
- Add repository/service boundaries and a read-only resolver whose supported
  5.1 success outcome is an active dedicated channel resolved from provider
  plus destination number.
- Add one reversible Alembic migration, focused tests, and a permanent
  OpenSpec capability.
- Keep all new services and repositories free of transaction-control calls;
  the caller owns flushing and persistence synchronization.
- Declare the canonical partial unique active-channel index in SQLAlchemy
  metadata as well as in the existing migration.

## Non-goals

- No Twilio SDK, credentials, webhook, signature validation, TwiML, outbound
  delivery, callbacks, retries, or provider-message receipt.
- No customer-channel context, automatic client/session creation, shared-code
  activation, manual selection, message preservation, or commerce switching
  (5.2–5.5).
- No changes to `Comercio.whatsapp`, the local endpoint, recognizers, catalog
  queries, handlers, pending contexts, or transaction ownership.
- No sync, archive, commit, or Phase-5.2 work.

## Architectural constraints

- `Comercio.whatsapp` is not a transport-channel authority; reusing it would
  make a shared number impossible and conflate business contact with provider
  destination.
- Destination numbers are canonical E.164 values without `whatsapp:`; provider
  is part of their uniqueness boundary.
- Dedicated ownership is direct, not a generic many-to-many relation. Shared
  membership for a dedicated channel is rejected by the service.
- Routing codes are opaque public identifiers, never internal commerce IDs.
  Revocation disables a code but never permits reassignment.
- The resolver may read channel and commerce state only. It must not create a
  client/session, classify text, call recognizers, query product data, mutate,
  commit, or roll back.

## Acceptance criteria

1. An active dedicated channel resolves exactly one active commerce from its
   provider plus normalized destination.
2. Unknown, inactive, malformed, shared, or unavailable inputs return typed
   non-resolved outcomes and never select a commerce.
3. Shared membership reserves an opaque routing code uniquely for the full
   channel history; a revoked value cannot be reassigned.
4. Dedicated channels cannot receive shared membership, and shared channels
   cannot carry dedicated-commerce ownership.
5. The resolver, channel service, and new-table repositories perform no
   transaction control (`commit`, `rollback`, `begin`, or `flush`) or
   business-pipeline call.
6. The migration is reversible and focused pytest, Ruff, compileall,
   `git diff --check`, and strict validation pass.

## Expected files

- `backend/models/canal_whatsapp.py`
- `backend/models/comercio_canal_compartido.py`
- `backend/models/__init__.py`
- `backend/alembic/versions/<revision>_add_whatsapp_channel_routing.py`
- `backend/repositories/canal_whatsapp_repository.py`
- `backend/repositories/comercio_canal_compartido_repository.py`
- `backend/services/canal_whatsapp_service.py`
- `backend/services/commerce_channel_resolver.py`
- focused tests under `backend/tests/`

## Rollback and deferred limitations

The migration downgrades only its two new tables and indexes; no existing row
is rewritten. The resolver is not wired to HTTP until the idempotent,
single-transaction design of 5.4 and validated webhook boundary of 5.5 exist.
