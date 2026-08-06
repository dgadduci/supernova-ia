## Why

Phase 5.1 can identify a dedicated WhatsApp destination, but an active shared
destination deliberately returns `requires_shared_routing` without selecting a
commerce. Phase 5.2 supplies the minimum durable selection state needed for a
known customer to activate one shared-channel membership safely.

## Objective

Persist commerce selection per `(canal, cliente)` from an exact shared routing
code, while preserving the original inbound text for a later phase. A valid
code selects only the commerce already bound to that active shared membership.

## Review correction (2026-08-06)

The initial implementation validates only the shape of `cliente_id`; it does
not prove that the referenced client exists and is active before adding context
state. This correction makes active-client validation an explicit activation
gate. It also removes the in-service `IntegrityError` race translation: without
`flush`, that exception cannot arise from `session.add()`, and concurrent
receipt/idempotency ownership remains deferred to Phase 5.4.

## Current execution path

The existing local endpoint receives `comercio_id` and `cliente_id` in its
path, resolves a commerce-bound `Session`, then invokes
`process_incoming_message_with_responses`. It cannot represent pre-commerce
shared-channel state because `Session.id_comercio` is non-null. Phase 5.1's
`CommerceChannelResolver` returns `requires_shared_routing` for a shared
destination and does not mutate state.

## Scope

- Add one durable customer-channel context keyed by `(canal_id, cliente_id)`.
- Resolve an exact, normalized routing code only against active membership of
  the supplied active shared channel.
- On first valid activation, persist the selected commerce and the exact
  original inbound text as pending, unprocessed input.
- Return typed outcomes for invalid/inactive channel, unknown or revoked code,
  inactive commerce, existing matching selection, and conflicting selection.
- Require the supplied client to exist and be active before any membership or
  context mutation; otherwise return `invalid_context`.
- Add focused repository/service tests and one reversible migration.

## Non-goals

- No Twilio SDK, webhook, signature validation, TwiML, outbound delivery,
  provider receipt, idempotency, retry handling, HTTP endpoint, or router.
- No automatic client creation; callers must supply an existing active client.
- No `Session`, order, classifier, recognizer, handler, catalog, or message
  pipeline invocation.
- No manual selection, confirmation, cancellation, or commerce switching;
  those belong to Phase 5.3.
- No commit, rollback, begin, or flush by 5.2 services/repositories.

## Approved business rules

1. A shared routing code is an exact routing envelope, not classifier text.
2. A first valid code selects only that membership's commerce for the given
   `(canal, cliente)` and preserves the caller's raw original text unchanged.
3. Invalid, revoked, inactive, dedicated, or unavailable inputs select no
   commerce and preserve no pending message.
4. Repeating the code for the already selected commerce is idempotent from the
   business perspective and does not overwrite the original pending text.
5. A different valid code while a selection exists returns a conflict and
   never changes the selected commerce or pending original text.
6. A nonexistent or inactive client is invalid context: it selects no commerce
   and creates or updates no context row.

## Shared boundary and transaction ownership

The new service may read the supplied channel, membership, commerce, client,
and customer-channel context and may add or modify caller-owned ORM state. It
does not own transaction control or call the incoming-message processor. The
caller remains responsible for client lookup, persistence synchronization, and
eventual Phase-5.4 single-transaction orchestration.

## Observability and fallback

Typed outcomes must distinguish `activated`, `already_selected`,
`requires_explicit_switch`, `invalid_routing_code`, `unknown_or_revoked_code`,
`inactive_channel`, `unavailable_commerce`, and `invalid_context`. No outcome
may silently fall back to a different commerce, a global client-only context,
or the existing local pipeline.

## Expected files

- `backend/models/contexto_cliente_canal_whatsapp.py`
- `backend/models/__init__.py`
- `backend/alembic/versions/<revision>_add_whatsapp_shared_routing_context.py`
- `backend/repositories/contexto_cliente_canal_whatsapp_repository.py`
- `backend/services/shared_channel_routing_service.py`
- `backend/services/exceptions.py`
- focused tests under `backend/tests/`

## Validation and rollback

Run focused pytest, Ruff, compileall, strict OpenSpec validation and
`git diff --check`. The migration adds only the new context table and can be
downgraded by dropping that table; it does not rewrite existing data. Deferred
limitations are manual switch (5.3), idempotent receipt/one transaction (5.4),
validated webhook (5.5), and outbound delivery (5.6).
