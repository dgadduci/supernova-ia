# Add read-only commerce information queries

## Objective

Answer the existing classifier's informational intents with deterministic, commerce-isolated data: `ver_menu`, `consultar_producto`, `ver_metodos_de_pago`, `ver_metodos_de_entrega`, `consultar_domicilio_comercio`, and `consultar_horarios_comercio`.

## Current execution path

The classifier already names all six intents, but the initial dispatcher rejects them and the shared mapper renders `GENERIC_MESSAGE`. Both provider and local traffic now share `initial_intent_dispatcher` → `ProcessedIntent` → `build_customer_responses` → outbox/local response. `ProductoQueryService` exposes the commerce catalog; `ConfiguracionComercioService` exposes the supplied commerce and its configured payment/delivery associations and address.

## Scope and non-goals

- Add read-only initial orchestration and deterministic response builders in the existing pipeline.
- Menu lists only active, available, sellable catalog entries for the current session commerce, in configured order.
- Product detail returns only catalog facts for names/presentations unambiguously contained in the classified source text; no product match gets a fixed clarification response.
- Payment and delivery list only active options configured for the current commerce.
- Address is rendered from the current commerce record.
- Since no operating-hours field/model exists, hours returns a fixed “not configured” response.
- Do not add models, migrations, LLM generation/styling, catalog writes, address/date delivery capture, observations, order state/cancellation, or another pipeline.

## Shared boundary, fallback, and transactions

The supplied session's `id_comercio` is the sole authority for every lookup; no lookup accepts a commerce ID from the message or switches commerce. A non-null pending context retains current precedence and bypasses informational initial dispatch.

An empty catalog/options set, unmatched/ambiguous product reference, missing commerce, and unavailable hours data are valid read-only outcomes with fixed guidance. The generic mapper fallback remains for unimplemented intents. Database/service failures propagate unchanged to the caller-owned transaction and must not become an empty-menu or unknown-product response. The change never commits, rolls back, begins, or otherwise owns a transaction.

## Observability, expected files, and validation

Reuse the existing services and response mapper. Record structured intent/outcome/reason only; do not log raw message or rendered text. Expected files: initial dispatcher, a narrow informational orchestration/builder module, mapper, and focused tests. No service/repository/model change is expected unless inspection proves a required read projection is missing.

The user will run locally:

`venv/bin/python -m pytest backend/tests/test_initial_intent_dispatcher.py backend/tests/test_incoming_message_response_orchestrator.py backend/tests/test_outbound_response_mapper.py backend/tests/test_informational_commerce_queries.py -q`

`venv/bin/python -m ruff check backend/intents/orchestration/initial_intent_dispatcher.py backend/intents/orchestration/informational_commerce_queries.py backend/intents/responses/informational_commerce_queries.py backend/services/outbound_response_mapper.py backend/tests/test_informational_commerce_queries.py`

`venv/bin/python -m compileall -q backend/intents/orchestration/initial_intent_dispatcher.py backend/intents/orchestration/informational_commerce_queries.py backend/intents/responses/informational_commerce_queries.py backend/services/outbound_response_mapper.py`

`openspec validate add-informational-commerce-queries --strict`

## Reversibility and deferred limitations

This is reversible by removing dispatcher/mapper branches; it writes no data. Per-commerce hours configuration, richer semantic product search, product descriptions/ingredients beyond persisted catalog fields, pagination, promotions, and LLM styling are deferred.
