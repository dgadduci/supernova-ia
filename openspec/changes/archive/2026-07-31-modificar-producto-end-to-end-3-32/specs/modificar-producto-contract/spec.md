# Capability: modificar-producto-contract

## Purpose

Declare the static contract that wires `modificar_producto` into the modern intent pipeline, in the same shape as `AGREGAR_PRODUCTO_CONTRACT` and `QUITAR_PRODUCTO_CONTRACT`. The contract is the single source of truth for the intent's name, recognizer, handler, and required/optional fields, and is the only entry through which the contract registry, initial dispatcher, pending-context dispatcher, ready-handler execution, and customer-response orchestrator discover the intent.

## ADDED Requirements

### Requirement: Static contract module location

The system SHALL expose `MODIFICAR_PRODUCTO_CONTRACT` from `backend/intents/contracts/modificar_producto.py` and SHALL NOT import from `backend/old_project/`.

#### Scenario: Contract is importable from the modern intents contracts package

- **WHEN** a module executes `from backend.intents.contracts.modificar_producto import MODIFICAR_PRODUCTO_CONTRACT`
- **THEN** the import succeeds and no symbol from `backend.old_project` is loaded

### Requirement: Contract top-level shape

`MODIFICAR_PRODUCTO_CONTRACT` SHALL be a `dict` (or `Contract` instance with dict-compatible access) with the keys `"intent"`, `"recognizer"`, `"handler"`, and `"requirements"` — mirroring the structure of `AGREGAR_PRODUCTO_CONTRACT` and `QUITAR_PRODUCTO_CONTRACT`.

#### Scenario: Contract exposes the four canonical keys

- **WHEN** `MODIFICAR_PRODUCTO_CONTRACT` is inspected
- **THEN** it has keys `"intent"`, `"recognizer"`, `"handler"`, and `"requirements"`, and no other required key

#### Scenario: Contract intent name is modificar_producto

- **WHEN** `MODIFICAR_PRODUCTO_CONTRACT["intent"]` is read
- **THEN** it equals the literal string `"modificar_producto"`

#### Scenario: Contract recognizer is modificar_producto_recognizer

- **WHEN** `MODIFICAR_PRODUCTO_CONTRACT["recognizer"]` is read
- **THEN** it equals the literal string `"modificar_producto_recognizer"` and matches the registered callable's `__name__`

#### Scenario: Contract handler is modificar_producto

- **WHEN** `MODIFICAR_PRODUCTO_CONTRACT["handler"]` is read
- **THEN** it equals the literal string `"modificar_producto"`

### Requirement: Required fields

The contract's `requirements` list SHALL contain exactly two entries, in order: `pedido_producto_origen_id` and `producto_presentacion_destino_id`. Both SHALL be marked required (`required=True`).

#### Scenario: Contract requirements include source identifier

- **WHEN** `MODIFICAR_PRODUCTO_CONTRACT["requirements"]` is read
- **THEN** the first entry has `name == "pedido_producto_origen_id"` and `required is True`

#### Scenario: Contract requirements include destination identifier

- **WHEN** `MODIFICAR_PRODUCTO_CONTRACT["requirements"]` is read
- **THEN** the second entry has `name == "producto_presentacion_destino_id"` and `required is True`

### Requirement: Optional cantidad field

The contract SHALL declare `cantidad` as an optional requirement (`required=False`, default `None`) so the handler can detect omitted quantity and modify the entire source line.

#### Scenario: Contract declares optional cantidad

- **WHEN** `MODIFICAR_PRODUCTO_CONTRACT["requirements"]` is read
- **THEN** it contains an entry with `name == "cantidad"`, `required is False`, and `default is None`

### Requirement: Forbidden LLM-provided database fields

The contract SHALL NOT declare price, subtotal, current line quantity, Pedido ID, PedidoProducto ID, or `producto_presentacion` ID as authoritative database values supplied by the LLM. All identifiers SHALL be derived and validated by application code; the contract SHALL NOT include any `*_db_id`, `price`, or `subtotal` requirement.

#### Scenario: Contract does not list price or subtotal

- **WHEN** `MODIFICAR_PRODUCTO_CONTRACT["requirements"]` is read
- **THEN** no entry has `name` matching `price`, `subtotal`, `precio`, or `id`

#### Scenario: Contract does not list Pedido ID

- **WHEN** `MODIFICAR_PRODUCTO_CONTRACT["requirements"]` is read
- **THEN** no entry has `name == "pedido_id"` or `name == "id_pedido"`

### Requirement: Contract registry inclusion

`MODIFICAR_PRODUCTO_CONTRACT` SHALL be importable and discoverable through the same registry that already exposes `AGREGAR_PRODUCTO_CONTRACT` and `QUITAR_PRODUCTO_CONTRACT`.

#### Scenario: Contract registry lists modificar_producto

- **WHEN** the contract registry enumerates all registered intents
- **THEN** the registry returns `modificar_producto` alongside `agregar_producto` and `quitar_producto`

### Requirement: Public surface is limited

The contract module SHALL export only `MODIFICAR_PRODUCTO_CONTRACT` through `__all__` and SHALL NOT introduce additional helpers, registries, or side effects.

#### Scenario: Only one public symbol is exported

- **WHEN** the module is imported and `__all__` is inspected
- **THEN** `__all__` equals `["MODIFICAR_PRODUCTO_CONTRACT"]`

#### Scenario: Module has no additional public functions

- **WHEN** the contract module is inspected for top-level `def` statements
- **THEN** only the contract literal is defined (private constants and imports are permitted)
