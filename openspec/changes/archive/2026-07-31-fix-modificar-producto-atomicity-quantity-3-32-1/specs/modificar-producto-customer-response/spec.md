# Capability: modificar-producto-customer-response

## Purpose

Provide a deterministic response builder for `modificar_producto` that renders every outcome (source pending, destination pending, full-line executed with omitted or explicit quantity, partial executed, consolidated executed, excess quantity with Pedido-preserved confirmation, source absent, destination unavailable with Pedido-preserved confirmation, unknown destination with Pedido-preserved confirmation, source equals destination, generic failed) using only the order lines, presentations, and product names already loaded by the orchestration layer, without LLM beautification, prompt construction, or exposure of database identifiers.

## MODIFIED Requirements

### Requirement: Full-line executed rendering

When `intent.status == "executed"` and `resolved_data["origen_eliminado"] is True` and `resolved_data["destino_creado"] is True`, the builder SHALL render `Cambié <cantidad_a_modificar> <origen_nombre> por <cantidad_a_modificar> <destino_nombre>.`

#### Scenario: Full-line swap with omitted quantity renders the corrected message

- **WHEN** the service reports a full-line swap with `cantidad_modificada == 4`, `producto_origen_nombre="Empanadas de Verdura"`, `producto_destino_nombre="Empanadas de Carne Picante"`, `presentacion_origen` and `presentacion_destino` omitted from the rendered message because the full transfer quantity equals the source quantity
- **THEN** `CustomerResponse.message` equals `Cambié 4 Empanadas de Verdura por 4 Empanadas de Carne Picante.`

### Requirement: Destination unavailable rejected rendering

When `intent.status == "rejected"` and the rejection reason is `destination_unavailable` (including the unknown-destination case surfaced as `destination_unavailable`), the builder SHALL render `El producto de reemplazo no está disponible. Tu pedido no fue modificado.` so the customer sees an explicit confirmation that the Pedido is unchanged.

#### Scenario: Destination unavailable renders the Pedido-preserved message

- **WHEN** the rejection reason is `destination_unavailable`
- **THEN** `CustomerResponse.message` equals `El producto de reemplazo no está disponible. Tu pedido no fue modificado.`

### Requirement: Excess quantity rejected rendering

When `intent.status == "rejected"` and the rejection reason is `quantity_exceeds_source`, the builder SHALL render `Solo tenés <cantidad_actual> <origen_nombre> para cambiar. Tu pedido no fue modificado.` so the customer sees an explicit confirmation that the Pedido is unchanged.

#### Scenario: Excess quantity renders the Pedido-preserved message

- **WHEN** `cantidad_actual == 3`, `origen_nombre="Empanadas de Verdura"`
- **THEN** `CustomerResponse.message` equals `Solo tenés 3 Empanadas de Verdura para cambiar. Tu pedido no fue modificado.`

### Requirement: Unknown destination rejected rendering

When `intent.status == "rejected"` and the destination product does not exist in the comercio catalog (the unknown-destination case surfaced as `destination_unavailable` or `no_destination_candidates`), the builder SHALL render `No encontré el producto de reemplazo. Tu pedido no fue modificado.` so the customer sees an explicit confirmation that the Pedido is unchanged.

#### Scenario: Unknown destination renders the documented message

- **WHEN** the rejection reason is `destination_unavailable` and the destination product does not exist in the comercio catalog
- **THEN** `CustomerResponse.message` equals `No encontré el producto de reemplazo. Tu pedido no fue modificado.`

### Requirement: Single customer response per modification

The response builder SHALL be invoked exactly once per `modificar_producto` outcome. The system SHALL NOT produce a remove response followed by an add response, SHALL NOT produce two `CustomerResponse` instances per modification, and SHALL NOT split the modification across multiple response builders. The incoming-message response orchestrator SHALL route every `modificar_producto` outcome to `build_modificar_producto_response` and SHALL NOT use the generic fallback.

#### Scenario: Exactly one CustomerResponse per modification

- **WHEN** `process_incoming_message_transactional(db, session, message)` returns for a `modificar_producto` message
- **THEN** `build_modificar_producto_response` is invoked exactly once and the response orchestrator emits exactly one `CustomerResponse`

#### Scenario: No separate remove and add responses

- **WHEN** the user sends `cambia las empanadas de verdura por empanadas carne picante` against a Pedido with `Empanada de Verdura x4`
- **THEN** the rendered `CustomerResponse.message` is the single modification message; the response does not contain `Quité` and `Agregué` substrings together

#### Scenario: Response orchestrator never uses the generic fallback for modificar_producto

- **WHEN** the active intent is `modificar_producto` for any status
- **THEN** `incoming_message_response_orchestrator` delegates to `build_modificar_producto_response` and never to the generic fallback builder

## ADDED Requirements

### Requirement: Executed partial explicit-quantity message format

When `intent.status == "executed"` and `resolved_data["destino_creado"] is True` and `resolved_data["origen_eliminado"] is False` (a partial modification where the source is decremented and a new destination line is created), the builder SHALL render `Cambié <cantidad_modificada> <origen_nombre> por <cantidad_modificada> de <destino_nombre>. Quedan <cantidad_origen_restante> <origen_nombre>.`

#### Scenario: Partial explicit-quantity transfer renders the corrected message

- **WHEN** `cantidad_modificada == 2`, `cantidad_origen_restante == 3`, `producto_origen_nombre="Empanadas de Verdura"`, `producto_destino_nombre="Empanadas de Carne Picante"`
- **THEN** `CustomerResponse.message` equals `Cambié 2 Empanadas de Verdura por 2 de Empanadas de Carne Picante. Quedan 3 Empanadas de Verdura.`