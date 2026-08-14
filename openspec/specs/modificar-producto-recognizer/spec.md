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

### Requirement: Destination-only quantity means full source replacement

When a modification message has no explicit positive quantity before `por` and
one explicit positive quantity after it, the recognizer SHALL emit
`cantidad is None` and `cantidad_destino == M`. It SHALL not copy M into
legacy source `cantidad`.

#### Scenario: Full one-unit source becomes two destination units

- **WHEN** the message is `cambia la napolitana grande por dos mozzarella grande` and the selected source line has quantity 1
- **THEN** the ready intent preserves `cantidad is None` and `cantidad_destino == 2`, so execution removes the source line and adds 2 destination units

#### Scenario: Legacy pending remains unchanged

- **WHEN** an existing pending payload has `cantidad == 2` and no `cantidad_destino`
- **THEN** it continues to mean source 2 -> destination 2

### Requirement: Explicit paired source and destination quantities

When a `modificar_producto` message has the existing `por` separator and
contains an explicit positive quantity on both sides, the recognizer SHALL
emit the source amount as `cantidad` and the destination amount as optional
`cantidad_destino`. It SHALL derive both only with the existing normalized
quantity vocabulary; no LLM, hybrid, or candidate result may supply them.

#### Scenario: Two source units become one destination unit

- **WHEN** the message is `cambiar dos napolitanas grandes por una pizza de mozzarella`
- **THEN** the recognizer emits `cantidad == 2` and `cantidad_destino == 1`

#### Scenario: One explicit quantity remains compatible

- **WHEN** the message is `cambiar dos napolitanas grandes por mozzarella`
- **THEN** `cantidad == 2` and `cantidad_destino is None`, preserving the existing equal-quantity transfer contract

### Requirement: Modification source catalog includes owned category context

The `modificar_producto` recognizer SHALL build its source catalog only from
`PedidoProductoService.list_by_pedido(session.id_pedido)`. Each source row
SHALL carry its `pedido_producto_id`, `producto_presentacion_id`, product
name, already eager-loaded product category description as `categoria_nombre`,
presentation code, presentation description, and current quantity. The
category description is token context only and SHALL NOT widen the candidate
universe beyond those PedidoProducto rows.

#### Scenario: Category-qualified specific source resolves an owned line

- **WHEN** the active draft contains `Mozzarella Grande` in category `Pizzas`
- **AND** the customer requests `cambia una pizza de mozzarella grande por 1 empanada de pollo`
- **THEN** source recognition returns only that own `pedido_producto_id`
- **AND** no commerce-catalog order line is introduced.

#### Scenario: Category-qualified source ambiguity stays restricted

- **WHEN** the active draft contains `Mozzarella Grande`, `Mozzarella Chica`,
  and unrelated `Napolitana Chica`, all in category `Pizzas`
- **AND** the customer requests `cambia una pizza de mozzarella por una empanada de pollo`
- **THEN** source recognition returns exactly the two own Mozzarella line IDs
- **AND** the existing `source_selection` pending flow owns clarification.

#### Scenario: Category context does not create a source line

- **WHEN** a category-qualified source product exists in the commerce catalog
  but is absent from the active draft
- **THEN** source recognition returns no candidate
- **AND** the existing source-absent rejection preserves the Pedido.

### Requirement: Source category projection is read-only

The source category projection SHALL reuse the category relationship already
loaded by the existing order-line query. It SHALL NOT issue a catalog-wide or
per-line category query, own transaction control, or alter destination and
quantity recognition.

#### Scenario: Missing category relation fails safely

- **WHEN** an otherwise malformed order-line row has no usable category
  description
- **THEN** the recognizer does not invent category context or a candidate
- **AND** retains the existing no-match or technical-failure behavior.
