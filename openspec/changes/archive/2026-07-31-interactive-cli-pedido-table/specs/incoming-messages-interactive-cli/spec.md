## ADDED Requirements

### Requirement: CLI prints current draft Pedido as a terminal table after a successful order modification

After a successful `POST /comercios/{comercio_id}/clientes/{cliente_id}/incoming-messages` call, the script SHALL inspect the returned `responses` list. When at least one `CustomerResponse` in the list carries `status == "executed"` and `intent in {"agregar_producto", "quitar_producto"}`, the script SHALL issue exactly one `GET /pedidos/{pedido_id}/detalle` using the `pedido_id` it stored at bootstrap, then print the customer-facing responses first, then `Pedido actual:` followed by a plain-text table whose columns are `Producto`, `Presentación`, and `Cantidad`. When the same response list contains multiple executed order-mutating responses, the script SHALL issue the detail retrieval exactly once and SHALL print exactly one table reflecting the committed state. When no response in the list carries an executed order-mutating intent (e.g. `pending_resolution`, `rejected`, `failed`, conversational responses, consultation responses), the script SHALL NOT issue any detail retrieval and SHALL NOT print any table. The script SHALL NOT recompute the order state locally between calls. The script SHALL use only the Python standard library to format the table; it SHALL NOT introduce a third-party table-formatting dependency.

#### Scenario: Executed agregar_producto triggers one detail retrieval and one table

- **WHEN** the API returns `{"responses": [{"intent": "agregar_producto", "status": "executed", "message": "..."}]}` and `GET /pedidos/{pedido_id}/detalle` returns two line items
- **THEN** the script prints the customer response first, then `Pedido actual:`, then a table with `Producto`, `Presentación`, `Cantidad` columns and exactly two rows

#### Scenario: Executed quitar_producto triggers one detail retrieval and one table

- **WHEN** the API returns `{"responses": [{"intent": "quitar_producto", "status": "executed", "message": "..."}]}` and `GET /pedidos/{pedido_id}/detalle` returns one line item
- **THEN** the script prints the customer response first, then `Pedido actual:`, then a table with exactly one row

#### Scenario: pending_resolution does not trigger a detail retrieval or table

- **WHEN** the API returns `{"responses": [{"intent": "agregar_producto", "status": "pending_resolution", "message": "..."}]}`
- **THEN** the script issues zero `GET /pedidos/{pedido_id}/detalle` calls and prints no table for that line

#### Scenario: rejected does not trigger a detail retrieval or table

- **WHEN** the API returns `{"responses": [{"intent": "quitar_producto", "status": "rejected", "message": "..."}]}`
- **THEN** the script issues zero `GET /pedidos/{pedido_id}/detalle` calls and prints no table for that line

#### Scenario: failed does not trigger a detail retrieval or table

- **WHEN** the API returns `{"responses": [{"intent": "agregar_producto", "status": "failed", "message": "..."}]}`
- **THEN** the script issues zero `GET /pedidos/{pedido_id}/detalle` calls and prints no table for that line

#### Scenario: Conversational response does not trigger a detail retrieval or table

- **WHEN** the API returns `{"responses": [{"intent": "saludo", "status": "rejected", "message": "Hola"}]}`
- **THEN** the script issues zero `GET /pedidos/{pedido_id}/detalle` calls and prints no table for that line

#### Scenario: Multiple executed mutations trigger one detail retrieval

- **WHEN** the API returns `{"responses": [{"intent": "agregar_producto", "status": "executed", ...}, {"intent": "quitar_producto", "status": "executed", ...}]}`
- **THEN** the script issues exactly one `GET /pedidos/{pedido_id}/detalle` call and prints exactly one table

#### Scenario: Customer responses are printed before the table

- **WHEN** the detail retrieval returns a non-empty order
- **THEN** the script prints all customer-facing response lines before the `Pedido actual:` header and the table

#### Scenario: Table does not expose database ids

- **WHEN** the detail retrieval returns any line items
- **THEN** the printed table contains no value that looks like a database id (no integer keys such as `id`, `id_pedido`, `id_producto_presentacion`, etc.)

#### Scenario: Column widths adapt to long names

- **WHEN** the detail retrieval returns line items whose product names or presentation descriptions are longer than the column header
- **THEN** the printed table widens the affected column to fit the longest value and the table remains aligned

#### Scenario: Empty order prints the vacio fallback

- **WHEN** the detail retrieval returns `lineas: []`
- **THEN** the script prints `Pedido actual: vacío` and does not print an empty bordered table

#### Scenario: Detail retrieval failure prints a warning and the loop continues

- **WHEN** the API returned an executed order-mutating response but `GET /pedidos/{pedido_id}/detalle` returns a non-2xx status or raises a connection / JSON error
- **THEN** the script keeps the already printed customer response, prints a single-line warning that mentions the HTTP status or error detail, and continues the read-eval-print loop on the next typed line

#### Scenario: Strict import boundary still holds for the new helpers

- **WHEN** the module `backend.scripts.cli_chat_client` is loaded
- **THEN** the imports of the module and the source code contain none of `fastapi`, `sqlalchemy`, `uvicorn`, `requests`, `httpx`, `aiohttp`, `websockets`, and none of `backend.routers`, `backend.services`, `backend.repositories`, `backend.intents`, `backend.llm`, `backend.models`, `backend.alembic`, `backend.dependencies`

#### Scenario: Existing session creation, message loop, exit, and cleanup behavior remain unchanged

- **WHEN** the operator types `exit` after any number of typed lines
- **THEN** the script breaks the loop, closes the session it created via `POST /sessions/{session_id}/cerrar` exactly once, and exits with status `0`; the table branch does not change bootstrap, session reuse, empty-input skipping, `exit` matching, base-URL precedence, close-failure non-fatality, or the import boundary
