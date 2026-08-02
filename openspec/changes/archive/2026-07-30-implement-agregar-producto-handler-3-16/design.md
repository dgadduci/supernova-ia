## Context

`PedidoProductoService` already owns the application rules for creating order lines, including product-presentation validation, draft-pedido checks, and current-price snapshotting. The new handler must translate a ready typed intent into that service call without introducing a second business-rule or database-access path.

## Goals / Non-Goals

**Goals:**
- Validate handler ownership and ready intent data.
- Delegate line creation to `PedidoProductoService`.
- Return an immutable-style copied `ProcessedIntent` with `executed`, `rejected`, or `failed` status.
- Preserve pending-context state and caller-owned transaction behavior.

**Non-Goals:**
- Direct SQLAlchemy or repository access.
- FastAPI/router concerns or HTTP exceptions.
- Context cleanup, queue promotion, dispatch, or responses.
- New generic handler abstractions.

## Decisions

- Place the handler in `backend/intents/handlers/agregar_producto_handler.py` and export only `execute_agregar_producto`.
- Use `DatabaseSession` and `ConversationSession` aliases to make the two session roles explicit in the signature.
- Validate intent metadata and resolved values before invoking the service, returning a new rejected intent while preserving all original fields.
- Obtain `conversation_session.id_pedido` and delegate creation to `PedidoProductoService`; do not accept or pass `precio_unitario` from intent data.
- Map expected business-rule failures to rejected status and unexpected exceptions to failed status without translating to HTTP exceptions.
- Preserve `pending_intents` and `context_type`; a future orchestration layer owns cleanup.

## Risks / Trade-offs

- [Risk] Handler validation diverges from the service's rules → Mitigation: keep validation limited to intent shape/types and delegate pedido/product rules to `PedidoProductoService`.
- [Risk] A rejected handler result could be mistaken for a transport error → Mitigation: return typed status values and leave exception translation to a future boundary.
- [Risk] Session has no pedido → Mitigation: reject before service invocation and test the case explicitly.

## Migration Plan

1. Inspect `PedidoProductoService`, its exceptions, and session/pedido relationships.
2. Implement the handler and typed status transitions.
3. Add focused tests against `supernova_test` for success and rejection paths.
4. Run the minimum handler test subset and compile check.
5. Roll back by removing the handler and tests; existing services remain unchanged.

## Open Questions

None.
