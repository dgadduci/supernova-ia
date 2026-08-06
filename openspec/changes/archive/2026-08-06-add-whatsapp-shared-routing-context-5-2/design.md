## Context model

`ContextoClienteCanalWhatsapp` is the sole Phase-5.2 pre-commerce state. It
has `canal_id`, `cliente_id`, nullable `comercio_id_seleccionado`, nullable
`mensaje_original_pendiente`, lifecycle timestamps, and one unconditional
unique constraint on `(canal_id, cliente_id)`. Foreign keys use `RESTRICT`.

The context is intentionally keyed by the WhatsApp channel plus the existing
client; phone alone is insufficient because one customer can interact with
multiple provider destinations. It is not a `Session`: sessions require a
non-null commerce and belong to the existing order flow.

## Activation decision table

| Condition | Outcome | Mutation |
| --- | --- | --- |
| Missing or inactive client | `invalid_context` | none |
| Active shared channel, active membership/code, active commerce, no selection | `activated` | set commerce and exact original text |
| Same active membership/code as existing selection | `already_selected` | none |
| Different active membership/code with existing selection | `requires_explicit_switch` | none |
| Dedicated/inactive/unknown channel | `invalid_context` / `inactive_channel` | none |
| Invalid code syntax | `invalid_routing_code` | none |
| Missing or inactive membership / revoked code | `unknown_or_revoked_code` | none |
| Membership commerce inactive | `unavailable_commerce` | none |

The service accepts the raw routing-code envelope and raw original text as
separate arguments. It normalizes only the routing code. `mensaje_original_pendiente`
is stored byte-for-byte as supplied, subject only to a non-empty string type
validation; it is never sent to recognizers or stripped of the code in 5.2.

## Isolation and switching

Every membership lookup includes both `canal_id` and normalized code and
requires `activo = true`; it never queries memberships from another channel.
The resulting commerce is read only from that one membership. An existing
selection is authoritative for the context. A conflicting code is observable
but does not mutate it; Phase 5.3 owns explicit confirmation/cancellation.

## Transaction and integration boundary

Repositories/service construct and modify pending ORM state only. They do not
call `flush`, `commit`, `rollback`, `begin`, or existing pipeline code. The
Phase-5.2 surface is a service API, not an HTTP route. Phase 5.4 will later
compose channel resolution, client/context, session, processing and reply in a
single caller-owned transaction after provider-message deduplication.

The service loads the existing `Cliente` directly from the caller-owned session
before routing. A missing or inactive client returns `invalid_context` and
performs no membership/context mutation. The service does not catch
`IntegrityError` around `session.add()`: constraint conflicts emerge when the
caller synchronizes, and their concurrent receipt semantics are Phase-5.4 work.
