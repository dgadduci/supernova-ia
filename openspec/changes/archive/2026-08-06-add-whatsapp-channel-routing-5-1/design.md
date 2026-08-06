## Context and approved roadmap

Phase 5 integrates WhatsApp through Twilio without a second order pipeline:
5.1 channel model and dedicated resolution; 5.2 shared context and code; 5.3
manual selection and explicit switch; 5.4 idempotency and one transaction;
5.5 validated Twilio webhook and TwiML; 5.6 outbound delivery and callbacks.
Only 5.1 is implemented by this change.

## Domain model

### `CanalWhatsapp`

| Field | Rule |
| --- | --- |
| `id` | primary key |
| `provider` | initially `twilio`; identity, not a credential |
| `destination_e164` | canonical without `whatsapp:`; unique with provider |
| `mode` | enum `dedicated` or `shared` |
| `id_comercio_exclusivo` | non-null exactly for dedicated; null exactly for shared |
| `activo`, timestamps | lifecycle/audit |

The direct exclusive FK corrects the original generic association proposal: it
makes exclusive ownership representable and directly enforceable. The service
also verifies the referenced commerce is active through the existing boundary.

The SQLAlchemy metadata declares the same named partial unique index as the
migration: `(provider, destination_e164)` with predicate `activo = true`.
This keeps future Alembic metadata comparison from treating the production
identity constraint as unmanaged schema.

### `ComercioCanalCompartido`

This represents only shared membership: `canal_id`, `comercio_id`,
`routing_code_normalized`, `activo`, timestamps. Unique
`(canal_id, routing_code_normalized)` has no active predicate: deactivation
revokes a code and prevents a stale link/QR being reassigned to another
commerce. Service validation rejects dedicated channels.

No customer context is introduced here. `Session` cannot be pre-commerce
state because `id_comercio` is non-null.

## Resolver boundary

`CommerceChannelResolver.resolve_dedicated(provider, destination)` normalizes
the destination and returns `channel_id`, `routing_mode`, `comercio_id | None`,
`resolution_source`, and `status`.

| Condition | Result |
| --- | --- |
| active dedicated channel + active exclusive commerce | `resolved`, `destination_number` |
| unknown/malformed destination | `unknown_channel` / `invalid_destination` |
| inactive channel/commerce | `inactive_channel` / `unavailable_commerce` |
| active shared channel | `requires_shared_routing` |

It is read-only: no sender/text inspection, client/session creation,
classifier/recognizer/handler/catalog call, or transaction control.

## Cross-phase invariants

- Future context is identified by `(canal, cliente)`, not a phone alone.
- Commerce is resolved before all pipeline work; catalog, aliases, prices,
  embeddings, pending contexts and orders are commerce-scoped at query time.
- Shared codes are routing envelopes, not classifier text. A conflicting code
  during an active order requests explicit change; it never silently switches.
- 5.2/5.3 preserve the original message until selection completes.
- 5.4 deduplicates provider IDs before mutation and persists the replay result.
- 5.5 validates Twilio signatures via vendor SDK over public canonical URL and
  all request parameters before mutation; secrets remain configuration only.
- 5.4 owns one transaction for receipt, routing, context, session, processing
  and response, using a shared non-transactional core rather than a second
  business pipeline.

## Transaction and migration constraints

Phase-5.1 services and the two new-table repositories may construct rows,
assign attributes, add rows to the caller-owned session, and issue scoped
queries, but never call `commit`, `rollback`, `begin`, or `flush`. In
particular, registration and deactivation return pending ORM state; the caller
decides when it flushes or commits. Tests that need database-assigned IDs or
constraint evaluation flush from their test/caller boundary, not via this
service/repository API. The migration must target the Alembic head verified at
implementation time: the worktree currently has an uncommitted embedding
migration, so its revision cannot be guessed.

## Validation

```bash
PYTHONPATH=. venv/bin/pytest -q backend/tests/test_canal_whatsapp_model.py backend/tests/test_commerce_channel_resolver.py
PYTHONPATH=. venv/bin/python -m ruff check backend/models/canal_whatsapp.py backend/models/comercio_canal_compartido.py backend/repositories/canal_whatsapp_repository.py backend/repositories/comercio_canal_compartido_repository.py backend/services/canal_whatsapp_service.py backend/services/commerce_channel_resolver.py backend/tests/test_canal_whatsapp_model.py backend/tests/test_commerce_channel_resolver.py
PYTHONPATH=. venv/bin/python -m compileall backend/models/canal_whatsapp.py backend/models/comercio_canal_compartido.py backend/repositories/canal_whatsapp_repository.py backend/repositories/comercio_canal_compartido_repository.py backend/services/canal_whatsapp_service.py backend/services/commerce_channel_resolver.py
openspec validate add-whatsapp-channel-routing-5-1 --strict
git diff --check
```

No endpoint or webhook test belongs to 5.1.
