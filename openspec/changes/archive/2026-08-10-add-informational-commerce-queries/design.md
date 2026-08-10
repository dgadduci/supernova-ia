# Design: deterministic informational commerce queries

## Authoritative outcomes

| Intent | Authoritative data | Valid response outcomes |
| --- | --- | --- |
| `ver_menu` | Current commerce's active/available/sellable catalog | ordered menu; fixed no-items guidance |
| `consultar_producto` | Current commerce's sellable catalog | one unambiguous detail; fixed clarification/no-match guidance |
| `ver_metodos_de_pago` | Current commerce's active payment associations | ordered options; fixed no-options guidance |
| `ver_metodos_de_entrega` | Current commerce's active delivery associations | ordered options; fixed no-options guidance |
| `consultar_domicilio_comercio` | Current commerce address | rendered address |
| `consultar_horarios_comercio` | No persisted source exists | fixed hours-not-configured guidance |

Missing commerce and technical query failures are technical failures and propagate. They must not be rendered as empty business results. The response never exposes a different commerce's catalog/configuration.

## Execution design

1. Pending contexts remain handled first by `dispatch_pending_context`.
2. The initial dispatcher delegates the six intents to one informational read-only orchestration module.
3. The module obtains `session.id_comercio` only from the supplied session and reuses `ProductoQueryService` / `ConfiguracionComercioService`.
4. Product matching is deterministic: compare normalized sellable product and presentation names against the classified source text; exactly one product/presentation outcome may be detailed. Zero or multiple distinct matches request clarification. No fuzzy/hybrid recognizer is invoked or altered.
5. The orchestration returns an `executed` `ProcessedIntent` containing only safe structured display facts/outcome keys; it performs no state write. A pure response builder renders fixed Spanish text from those facts.
6. The shared mapper handles these six names, preserving existing local/outbox equivalence and generic fallback.

## Focused tests

Tests shall cover commerce isolation; pending-context priority; active/disponible filtering and configured ordering; no-option/no-catalog outcomes; exact one/no/multiple product matches; address formatting; hours-not-configured; technical failure propagation; response ordering and local/outbox equivalence. Assert no commit/rollback and no mutation of session/pedido/pending state.
