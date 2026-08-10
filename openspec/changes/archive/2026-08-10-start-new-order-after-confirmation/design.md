# Design: explicit new order after a confirmed order

## Authoritative outcomes

| Condition after authoritative `iniciar_pedido` | Outcome | Persisted effect |
| --- | --- | --- |
| Associated pedido is `borrador` | `rejected`, reason `pedido_borrador_activo` | None; continue the existing draft |
| Associated pedido is `ingresado` or later, including `cancelado` | `executed` | Close current session; create one new active session and one empty `borrador` pedido |
| `session.id_pedido` is null or missing | `rejected`, reason `no_pedido_asociado` | None |
| Session is not active | `rejected`, reason `session_not_active` | None |
| Technical DB/constraint failure | exception propagates | Outer transaction rolls back the complete turn |

`iniciar_pedido` is authoritative only when emitted by the existing classifier from explicit customer wording. The dispatcher retains the normal unsupported-intent rejection for every other intent. No product-recognition or commerce-choice fallback applies.

## Execution design

1. `initial_intent_dispatcher` receives `INICIAR_PEDIDO` while `session.context_type is None` and delegates to the new orchestration function.
2. The function reads only `session.id_pedido` with `db.get(Pedido, ...)`, verifies `session.estado_session == ACTIVA`, and derives commerce/client exclusively from that supplied session.
3. A `borrador` is never replaced. For any non-borrador order, it stages `CERRADA` on the supplied session and flushes that update before staging the successor, satisfying the existing partial unique index on active `(id_comercio, id_cliente)` sessions.
4. It stages a new active `Session` for those same IDs, flushes to obtain its identity, stages a new `Pedido(id_session=<new session>, estado_pedido=Borrador)`, flushes to obtain its identity, and associates that ID to the new session.
5. It returns one typed `ProcessedIntent` with the successor IDs in `resolved_data`, not raw message data. A dedicated fixed Spanish response confirms a fresh empty order and invites products.
6. The dispatcher stops processing later classifier items after a successful successor transition. This prevents a multi-intent payload from executing product/closure mutations against the now-closed prior session. A later customer message is processed through the successor active session by the existing provider/local entry path.

The new components have no independent transaction boundary: no `commit`, `rollback`, `begin`, `close`, `refresh`, or `expire`. The existing provider coordinator commits session transition, new pedido, outbox rows, and work finalization together; its technical-failure path rolls them all back. The existing local transactional processor remains equivalent.

## Isolation and preserved history

The only new rows use the active session's `id_comercio` and `id_cliente`; neither parameter nor lookup permits a different authority. The old session retains its old `id_pedido`, all prior pending data, timestamps, and historical link. The successor has an empty/default pending state and only a new empty order. No order lines, payment/delivery IDs, metadata, or session context is copied.

## Focused tests

PostgreSQL-backed integration tests shall cover: one confirmed (`ingresado`) order creates exactly one closed predecessor, one active successor, and one empty draft with no copied choices/lines; every later order state does the same; a draft remains the sole active session/order; no association/non-active session has no mutation; commerce/customer isolation; full provider-turn rollback after outbound/technical failure; and dispatcher stopping later intents after a successful transition. Unit dispatcher tests shall assert the new branch and existing unsupported behavior.
