# Capability: modificar-producto-recognizer

## Purpose

Detect `modificar_producto` source candidates among the active draft Pedido's `PedidoProducto` lines and destination candidates among the comercio's active and available `ProductoPresentacion` rows, plus an optional explicit positive integer quantity, without ever falling back to the commerce catalog for source resolution or to the draft Pedido for destination resolution.

## Requirements

### Requirement: Recognizer module location

The system SHALL expose `recognize_modificar_producto` from `backend/intents/recognizers/modificar_producto_recognizer.py` and SHALL NOT import from `backend/old_project/`.

#### Scenario: Recognizer is importable from the modern intents recognizers package

- **WHEN** a module executes `from backend.intents.recognizers.modificar_producto_recognizer import recognize_modificar_producto`
- **THEN** the import succeeds and no symbol from `backend.old_project` is loaded

### Requirement: Recognizer signature

The system SHALL expose `recognize_modificar_producto(db: DatabaseSession, session: ConversationSession, message: str) -> RecognizerResult` aliased via typing exactly as `Session as DatabaseSession` for the SQLAlchemy session and `Session as ConversationSession` for the modern conversation model from `backend.models.session`.

#### Scenario: Function is callable with the documented signature

- **WHEN** a caller invokes `recognize_modificar_producto(db, session, "cambiá la pizza de muzzarella chica por una grande")`
- **THEN** the recognizer returns a `RecognizerResult` without raising

### Requirement: Source catalog scope

The recognizer SHALL build the source candidate catalog exclusively from `PedidoProductoService.list_by_pedido(session.id_pedido)`. Catalog products absent from the active draft Pedido SHALL NOT appear as source candidates.

#### Scenario: Source catalog is limited to current order lines

- **WHEN** the active draft Pedido contains exactly two `PedidoProducto` lines
- **THEN** the recognizer emits `source_candidate_ids` whose values equal exactly the two `PedidoProducto.id` values from those lines and no others

#### Scenario: Source catalog is empty when the draft Pedido has no lines

- **WHEN** the active draft Pedido has zero `PedidoProducto` rows
- **THEN** the recognizer emits `source_candidate_ids = []` and a downstream orchestrator can return a deterministic `rejected` outcome

#### Scenario: Recognizer never queries the commerce catalog for source

- **WHEN** the recognizer completes for any input
- **THEN** no SQLAlchemy query has been issued against `Producto`, `ProductoPresentacion`, or `Comercio` for source resolution

### Requirement: Destination catalog scope

The recognizer SHALL build the destination candidate catalog exclusively from the comercio's active and available `ProductoPresentacion` rows, obtained through the existing product-query services. PedidoProducto lines that do not match an active and available catalog presentation SHALL NOT appear as destination candidates.

#### Scenario: Destination catalog is limited to active and available presentations

- **WHEN** the comercio has three active presentations and one inactive presentation
- **THEN** the recognizer emits `destination_candidate_ids` containing exactly the three active presentation IDs and never the inactive one

#### Scenario: Inactive catalog products are not destination candidates

- **WHEN** a `ProductoPresentacion` exists but is marked inactive or unavailable
- **THEN** the recognizer excludes that presentation ID from `destination_candidate_ids`

### Requirement: Quantity extraction

When the message contains an explicit positive integer, the recognizer SHALL extract it as the requested quantity. When the message omits a quantity, the recognizer SHALL emit `cantidad = None` so the handler treats the request as a full-line modification.

#### Scenario: Explicit positive integer is preserved

- **WHEN** the message is `cambiá 2 empanadas de carne por 2 de jamón y queso`
- **THEN** the recognizer emits `cantidad == 2`

#### Scenario: Omitted quantity produces None

- **WHEN** the message is `cambiá las empanadas de carne por jamón y queso`
- **THEN** the recognizer emits `cantidad is None`

#### Scenario: Zero or negative quantity is rejected

- **WHEN** the message contains `0`, `-1`, or any non-positive integer
- **THEN** the recognizer returns a `RecognizerResult` whose `cantidad is None` and emits zero destination candidates for that quantity, leaving the orchestrator to surface a deterministic `rejected` outcome

### Requirement: Source and destination identifier separation

The recognizer SHALL emit `source_candidate_ids` and `destination_candidate_ids` as distinct fields, never combining the two identifier domains into one list.

#### Scenario: Recognizer emits two distinct candidate lists

- **WHEN** the recognizer completes for any input that produces at least one candidate in either domain
- **THEN** `RecognizerResult.source_candidate_ids` and `RecognizerResult.destination_candidate_ids` are both present, both are lists of integers, and they never share an entry

#### Scenario: Source and destination domains never overlap

- **WHEN** the recognizer completes for any input
- **THEN** the intersection of `source_candidate_ids` and `destination_candidate_ids` is empty

### Requirement: No fallback to the full commerce catalog or full Pedido

The recognizer SHALL NOT broaden the source candidate set to the commerce catalog and SHALL NOT broaden the destination candidate set to the full PedidoProducto history. The two domains remain strictly separated.

#### Scenario: Source remains restricted to current PedidoProducto lines

- **WHEN** the recognizer runs against any message
- **THEN** `source_candidate_ids` is a subset of `PedidoProductoService.list_by_pedido(session.id_pedido)` IDs

#### Scenario: Destination remains restricted to the active catalog

- **WHEN** the recognizer runs against any message
- **THEN** `destination_candidate_ids` is a subset of the comercio's active and available `ProductoPresentacion` IDs

### Requirement: Recognizer does not mutate or commit

The recognizer SHALL NOT issue `db.commit()`, `db.rollback()`, `db.add()`, `db.delete()`, or generate a customer-facing response. Persistence and response generation remain downstream responsibilities.

#### Scenario: Recognizer performs no commit or rollback

- **WHEN** `recognize_modificar_producto(db, session, message)` completes
- **THEN** `db.commit` and `db.rollback` have not been called by the recognizer module

#### Scenario: Recognizer does not generate responses

- **WHEN** the recognizer module source is inspected
- **THEN** it does not import any response builder, any LLM client, or any HTTP / FastAPI module

### Requirement: Public surface is limited

The recognizer module SHALL export only `recognize_modificar_producto` through `__all__` and SHALL NOT introduce additional helpers, classifiers, or registry entries.

#### Scenario: Only one public symbol is exported

- **WHEN** the module is imported and `__all__` is inspected
- **THEN** `__all__` equals `["recognize_modificar_producto"]`
