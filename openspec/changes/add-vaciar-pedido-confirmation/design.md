# Design: explicit draft-order clear confirmation

## Authoritative outcomes

| State / next reply | Processed status | Persisted effect | Context after turn |
| --- | --- | --- | --- |
| Initial `vaciar_pedido`, session-owned non-empty `borrador` | `pending_resolution` | Persist one active confirmation intent | `order_clear_confirmation` |
| Initial request with no session pedido, non-borrador pedido, or zero lines | `rejected` | None | Unchanged / none |
| Pending explicit affirmative | `executed` | Delete all rows belonging to the revalidated associated borrador | Cleared |
| Pending explicit negative | `rejected` | None | Cleared |
| Pending unclear / ambiguous reply | `pending_resolution` | None | Preserved |
| Pending affirmative after state became invalid or empty | `rejected` | None | Cleared |
| Technical database failure | `failed` or exception to owner | Outer owner rolls back | Existing failure policy |

The response wording is fixed Spanish and contains no database identifiers. The initial prompt asks the customer to reply `sí` to confirm or `no` to cancel. The affirmative/negative matcher normalizes case, accents, whitespace, and terminal punctuation, but recognizes only an approved finite vocabulary. Text outside that vocabulary is not an affirmative, not a negative, and not a new initial request.

## Execution design

1. With no pending context, the existing classifier emits `vaciar_pedido` and the initial dispatcher calls the dedicated initial orchestrator.
2. The orchestrator loads only `session.id_pedido`, verifies its `Pedido.id_session == session.id`, `estado_pedido == borrador`, and that it has lines. It creates a `pending_resolution` intent with handler `vaciar_pedido`, a pending `confirmacion` requirement, and no candidate IDs; it persists this as `order_clear_confirmation`.
3. The next customer message takes the existing pending-context route before initial classification. The dedicated resolver deterministically returns pending for unclear text, or a ready intent with `confirmacion=True` / `False` for clear acceptance/cancellation.
4. Ready confirmation passes through the existing pending execution primitive. Its new handler branch revalidates the same session-owned draft immediately before deletion. On acceptance it invokes one transaction-neutral service operation that deletes only that pedido's lines. On cancellation it returns a rejected cancellation outcome without touching rows. The primitive clears this non-queued context after either definitive outcome.
5. The existing shared response mapper renders the prompt, cancellation, success, business rejection, or technical failure identically for local responses and staged provider-outbox rows.

## Isolation and mutation boundary

The authoritative target is `session.id_pedido`, and it must point to a `Pedido` whose `id_session` equals the in-memory conversation session's id. The repository delete query is constrained by that validated pedido id; it never accepts arbitrary line IDs, commerce IDs, customer IDs, or catalog candidates. This preserves session/order isolation; commerce isolation follows the session's immutable `id_comercio` relationship and no cross-commerce lookup is performed.

The service validates draft state and loads the current rows before issuing deletion. It stages every deletion in the caller's transaction and does not call the existing single-line `delete`, because that method commits per row. If validation fails, it mutates nothing. If deletion raises, the exception follows existing failure handling and the outer owner rolls back the whole turn.

## Preserved boundaries

This is a single branch in the established pipeline, not a second message consumer. Pending context retains strict priority: a message such as `sí, agregá una pizza` is handled solely as a confirmation reply and must not add a product. No queue promotion, catalog recognizer, classifier invocation on the confirmation reply, LLM, HTTP concern, response rendering in the handler, or transaction control is added.

## Focused tests

Tests shall cover initial valid prompt; affirmative deletion of multiple lines; negative cancellation; invalid reply preserving only the same pending state; no pedido/non-borrador/empty draft rejections; stale-empty/non-borrador state before affirmative; foreign session/order isolation; all-or-nothing transaction behavior on a forced deletion failure; pending priority over a message containing another request; exact mapper responses and provider/local shared ordering. Existing pending-context and response-mapper regressions shall remain focused.
