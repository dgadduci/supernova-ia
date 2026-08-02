# Capability: quitar-producto-contract

## Purpose

Expose a single importable Python constant `QUITAR_PRODUCTO_CONTRACT` that declares the static intent contract for the `quitar_producto` skill, so other modules can introspect the required keys without importing implementation code.

## Requirements

### Requirement: Quitar producto contract module location

The system SHALL expose `QUITAR_PRODUCTO_CONTRACT` from `backend/intents/contracts/quitar_producto.py`.

#### Scenario: Contract is importable
- **WHEN** a module executes `from backend.intents.contracts.quitar_producto import QUITAR_PRODUCTO_CONTRACT`
- **THEN** the import succeeds and the binding is a `dict`

### Requirement: Contract top-level shape

`QUITAR_PRODUCTO_CONTRACT` SHALL be a `dict` with exactly three keys: `intent`, `recognizer`, and `handler`. The `intent` value SHALL be the literal string `"quitar_producto"`. The `recognizer` value SHALL be the literal string `"recognizer_quitar_producto"`. The `handler` value SHALL be the literal string `"quitar_producto"`.

#### Scenario: Top-level fields are exactly the documented values
- **WHEN** the contract dict is inspected
- **THEN** `contract["intent"] == "quitar_producto"`, `contract["recognizer"] == "recognizer_quitar_producto"`, `contract["handler"] == "quitar_producto"`, and the dict has no other top-level keys

### Requirement: Required resolved data is pedido_producto_id

The contract SHALL declare a `requirements` entry for `pedido_producto_id` with `required: True` and `default: None`. The application SHALL derive and validate this value from the active draft Pedido's current `PedidoProducto` rows.

#### Scenario: pedido_producto_id is required
- **WHEN** the contract `requirements` entry for `pedido_producto_id` is inspected
- **THEN** it has `required == True` and `default is None`

#### Scenario: LLM-supplied pedido_producto_id is not trusted
- **WHEN** a candidate `pedido_producto_id` arrives from the recognizer
- **THEN** the application re-validates it against the current draft Pedido's `PedidoProducto` rows before treating it as resolved data

### Requirement: Optional resolved data is cantidad

The contract SHALL declare a `requirements` entry for `cantidad` with `required: False` and `default: None`. When omitted, the handler SHALL remove the entire matching order line.

#### Scenario: cantidad is optional with None default
- **WHEN** the contract `requirements` entry for `cantidad` is inspected
- **THEN** it has `required == False` and `default is None`

#### Scenario: Omitted cantidad means full removal
- **WHEN** a `quitar_producto` intent resolves with `pedido_producto_id` only and no `cantidad`
- **THEN** the handler removes the complete matching `PedidoProducto` row

### Requirement: Forbidden LLM-supplied data

The contract SHALL NOT declare any requirement, default, or extension that lets the LLM supply `precio`, `subtotal`, the current line quantity, or any catalog-level id that has not been derived and validated by the application. The handler SHALL ignore any such field present in `resolved_data` and SHALL raise a deterministic rejected outcome if a forbidden value is required for execution.

#### Scenario: Forbidden fields are not in the contract
- **WHEN** the contract `requirements` is iterated
- **THEN** none of the requirement names is `precio`, `subtotal`, `cantidad_actual`, or `producto_presentacion_id`

#### Scenario: Forbidden resolved_data is ignored
- **WHEN** a `ProcessedIntent` carries `resolved_data["precio"]` or any other field not declared by the contract
- **THEN** the handler does not read the value and does not use it for mutation

### Requirement: Public surface is limited

The contract module SHALL export only `QUITAR_PRODUCTO_CONTRACT` through `__all__` and SHALL NOT introduce a registry, dataclass wrapper, TypedDict, or runtime validator.

#### Scenario: Single public contract symbol
- **WHEN** the module's `__all__` is inspected
- **THEN** it equals `["QUITAR_PRODUCTO_CONTRACT"]`
