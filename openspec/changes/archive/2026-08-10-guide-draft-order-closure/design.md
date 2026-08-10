# Design: guided draft-order closure

## Authoritative outcomes

| Intent | Successful outcome | Valid non-mutating business outcomes |
| --- | --- | --- |
| `consultar_resumen_pedido` | render persisted draft lines and selected choices | no associated draft; draft has no lines |
| `set_metodo_de_entrega` | set an enabled method belonging to the session commerce | no/ambiguous selection; method inactive or unavailable; no draft |
| `set_metodo_de_pago` | set an enabled payment method belonging to the session commerce | no/ambiguous selection; method inactive or unavailable; no draft |
| `confirmar_pedido` | atomically transition a complete non-empty `borrador` to `ingresado` | no draft; empty draft; missing payment; missing delivery; already non-borrador |

The summary is descriptive, not a calculation or price quote. It uses persisted order lines and displays selected choices. “Complete” means at least one line plus active payment and delivery associations for the session commerce. Address, scheduled time, and payment authorization are intentionally not completion requirements.

## Execution and failure design

1. The classifier preserves existing names and order.
2. The initial dispatcher delegates these four intents to closure orchestration.
3. Closure resolves only `session.id_pedido`, requires that pedido to be `borrador`, and derives commerce from the authoritative session.
4. Matching is limited to active commerce association rows. It accepts one unique normalized `codigo` or `descripcion`; zero or multiple matches yields clarification, never arbitrary selection.
5. Handlers stage the permitted update or transition and return typed `ProcessedIntent`; they never control the transaction.
6. Dedicated response builders render customer-facing Spanish. Existing provider mapping stages one outbound row per returned response and existing coalescing remains unchanged.

All reads and mutations share the existing outer message transaction. Technical exceptions roll back the complete turn; valid business outcomes do not trigger provider retry/fallback. No product-recognition fallback is introduced and pending product candidate sets are never read or widened.

## Focused tests

PostgreSQL-backed integration tests shall cover summary fidelity; valid ordered payment/delivery selection; inactive, foreign, unknown and ambiguous non-mutation; incomplete confirmation guidance; exactly-once `borrador → ingresado`; full-turn rollback after technical failure; and one provider-path business result with one outbound response.
