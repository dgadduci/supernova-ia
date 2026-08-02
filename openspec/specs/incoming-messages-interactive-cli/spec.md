# incoming-messages-interactive-cli Specification

## Purpose
Standalone, stdlib-only Python CLI that drives the local FastAPI incoming-messages endpoint through HTTP, bootstraps a session plus its draft Pedido, prints pipeline responses, and closes the session on exit. The CLI also prints the current draft Pedido as a terminal table after every successful order modification so the operator can verify the committed state without leaving the CLI.
## Requirements
### Requirement: CLI bootstrap creates and associates a draft Pedido through the existing HTTP API

After `POST /sessions` returns a `201` with the new session id, the script SHALL issue `POST /pedidos` with body `{"id_session": <session_id>}` and SHALL store the returned `pedido_id` in memory. The script SHALL then issue `PUT /sessions/{session_id}/pedido` with body `{"id_pedido": <pedido_id>}` exactly once. The script SHALL NOT create the pedido through any other code path. The script SHALL NOT pass `id_pedido` to `POST /sessions`. The script SHALL NOT import `sqlalchemy`, `backend.repositories`, `backend.services`, `backend.models`, `backend.alembic`, `backend.dependencies`, `backend.intents`, `backend.llm`, `fastapi`, `uvicorn`, `requests`, `httpx`, `aiohttp`, or `websockets` to perform these calls.

#### Scenario: Successful bootstrap creates session and pedido

- **WHEN** the user enters a valid `comercio_id` and `cliente_id`, the API returns `201` from `POST /sessions`, `201` from `POST /pedidos`, and `200` from `PUT /sessions/{session_id}/pedido`
- **THEN** the script stores the returned `session_id` and `pedido_id` in memory, prints `<session {session_id}>` followed by `<pedido {pedido_id}>`, and enters the read-eval-print loop with the same session id and the pedido associated through the existing HTTP endpoints

#### Scenario: Pedido creation fails with 5xx

- **WHEN** `POST /pedidos` returns a non-2xx status after the session is created
- **THEN** the script closes the session it created via `POST /sessions/{session_id}/cerrar` exactly once, prints the API error detail, and exits non-zero

#### Scenario: Pedido association fails with 4xx

- **WHEN** `PUT /sessions/{session_id}/pedido` returns a non-2xx status after the pedido is created
- **THEN** the script closes the session it created via `POST /sessions/{session_id}/cerrar` exactly once, prints the API error detail, and exits non-zero

#### Scenario: Bootstrap issue order is session-first then pedido then association

- **WHEN** the script runs successfully against the API
- **THEN** the script issues `POST /sessions` exactly once, then `POST /pedidos` exactly once, then `PUT /sessions/{session_id}/pedido` exactly once, before any `POST /comercios/.../incoming-messages` call

### Requirement: CLI conversation exposes a working agregar_producto handler

The script SHALL make it possible for a real `agregar_producto` conversation against a seeded catalog to reach `executed` without manual intervention between the typed line and the resulting `PedidoProducto` row. The script SHALL NOT add a confirmation prompt, a `[y/N]` step, or any additional turn between the user's last refinement message and the executed outcome.

#### Scenario: CLI run ends on executed without an extra turn

- **WHEN** the user runs the CLI, types `quiero dos pizzas` against a five-pizza catalog, then types `la grande`, then types `Pizza de Muzzarella Grande`
- **THEN** the third response printed by the CLI carries `status == "executed"` and the API persists exactly one `PedidoProducto` row with `cantidad == 2` and the seeded `precio_unitario`

### Requirement: CLI cleanup closes only the session it created

The script SHALL continue to issue `POST /sessions/{session_id}/cerrar` exactly once on exit, where `session_id` is the id returned by the script's own `POST /sessions` call. The script SHALL NOT issue `POST /pedidos/{pedido_id}/...` or any pedido-mutation endpoint during cleanup. The pedido is closed transitively via the existing session cascade; the script SHALL NOT close the pedido explicitly.

#### Scenario: Exit cleanup still closes only the session

- **WHEN** the user types `exit` after a successful bootstrap
- **THEN** the script issues `POST /sessions/{session_id}/cerrar` exactly once and no other HTTP request, and exits with status `0`

### Requirement: CLI client creates a fresh session on start
The script SHALL, after collecting `comercio_id` and `cliente_id`, send `POST {base_url}/sessions` with body `{"id_comercio": <comercio_id>, "id_cliente": <cliente_id>}` and hold the returned `id` as the only session used for the rest of the run. The script SHALL NOT create sessions through any other code path.

#### Scenario: Successful session creation
- **WHEN** the user enters a valid `comercio_id` and `cliente_id` and the API returns `201` with `{"id": <n>, ...}`
- **THEN** the script stores `<n>` in memory and prints a single line containing the new session id

#### Scenario: Duplicate active session
- **WHEN** the API returns `409` because a session is already active for that `(comercio_id, cliente_id)` pair
- **THEN** the script prints the API error detail and exits non-zero

### Requirement: CLI client reuses the same session for every message
The script SHALL send every typed line to `POST {base_url}/comercios/{comercio_id}/clientes/{cliente_id}/incoming-messages` with body `{"message": <line>}` and SHALL NOT call `POST /sessions` again during the conversation.

#### Scenario: Multiple messages on the same session
- **WHEN** the user types two non-empty lines in the same run
- **THEN** the script sends exactly two `POST /comercios/.../incoming-messages` requests, both targeting the same session id, and makes no further `POST /sessions` calls

### Requirement: CLI client prints the pipeline responses
For each non-empty line, the script SHALL read the JSON response body, iterate the `responses` list, and print exactly one line per response prefixed with `<- `. If a response carries a `message` field, the script SHALL print `message=<value>`; otherwise it SHALL print `raw=<dict>`.

#### Scenario: Pipeline returns text responses
- **WHEN** the API returns `{"responses": [{"message": "Hola", "intent": "saludo", "status": "rejected"}]}`
- **THEN** the script prints `<- message=Hola`

#### Scenario: Pipeline returns a response without a message field
- **WHEN** the API returns `{"responses": [{"intent": "x", "status": "y"}]}`
- **THEN** the script prints `<- raw={"intent": "x", "status": "y"}`

### Requirement: Empty input is silently ignored
The script SHALL NOT issue any HTTP request when the user submits an empty line (after `.strip()`) and SHALL continue the read-eval-print loop.

#### Scenario: User presses enter on an empty line
- **WHEN** the user submits an empty line
- **THEN** the script makes zero HTTP requests for that iteration and re-prompts

### Requirement: Exit command ends the loop and closes the session
When the user submits a line whose `.strip().lower()` equals `exit`, the script SHALL break the read-eval-print loop and send `POST {base_url}/sessions/{session_id}/cerrar` exactly once.

#### Scenario: Exiting with the literal word exit
- **WHEN** the user types `exit` (case-insensitive, ignoring surrounding whitespace)
- **THEN** the script ends the loop, calls `POST /sessions/{session_id}/cerrar` exactly once, and exits with status `0`

#### Scenario: Exiting with surrounding whitespace
- **WHEN** the user types `   EXIT   `
- **THEN** the script treats it as `exit`, ends the loop, closes the session, and exits with status `0`

### Requirement: Close failure is non-fatal
If the `POST /sessions/{session_id}/cerrar` call raises any exception (network error, non-2xx status, already-closed session returning `409`), the script SHALL print a single warning line and exit with status `0`.

#### Scenario: Server is already down when the script tries to close
- **WHEN** the close request raises `URLError`
- **THEN** the script prints a warning and exits with status `0`

#### Scenario: Session was already closed
- **WHEN** the close request returns `409` because the session is already closed
- **THEN** the script prints a warning and exits with status `0`

### Requirement: Base URL is configurable with documented precedence
The base URL the script uses SHALL be resolved in this order: `--base-url` CLI flag, then `INCOMING_MESSAGES_BASE_URL` environment variable, then the default `http://127.0.0.1:8000`. The script SHALL never start, stop, or mutate the FastAPI/Uvicorn process.

#### Scenario: Flag overrides everything
- **WHEN** the user runs `python -m backend.scripts.cli_chat_client --base-url http://example:9000`
- **THEN** all HTTP calls target `http://example:9000`

#### Scenario: Env var used when flag is absent
- **WHEN** `INCOMING_MESSAGES_BASE_URL=http://env:8000` is set and no flag is passed
- **THEN** all HTTP calls target `http://env:8000`

#### Scenario: Default used when neither is set
- **WHEN** neither flag nor env var is set
- **THEN** all HTTP calls target `http://127.0.0.1:8000`

### Requirement: Strict implementation boundaries
The script SHALL NOT import `fastapi`, `sqlalchemy`, `uvicorn`, `requests`, `httpx`, `aiohttp`, or `websockets`. The script SHALL NOT import any `backend.routers`, `backend.services`, `backend.repositories`, `backend.intents`, `backend.llm`, `backend.models`, `backend.alembic`, or `backend.dependencies` module. The script SHALL use only the standard library (`urllib.request`, `json`, `argparse`, `sys`, `os`) to talk to the running API.

#### Scenario: Static boundary check
- **WHEN** the script is loaded
- **THEN** the imports of its module contain none of the banned modules and contain only standard-library modules plus optionally `__future__` annotations

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

### Requirement: CLI accepts --debug-flow and --debug-components flags

The script SHALL accept an `--debug-flow` flag (`action="store_true"`) and an optional `--debug-components` argument that is a comma-separated list of `classifier`, `resolver`, and `pending`. When `--debug-flow` is absent, the script SHALL send no `X-Debug-Flow` header on any HTTP request and SHALL print no diagnostic tables. When `--debug-flow` is present, the script SHALL send `X-Debug-Flow: 1` on every `POST /comercios/{comercio_id}/clientes/{cliente_id}/incoming-messages` request and SHALL render the diagnostic tables embedded in the response. When `--debug-components` is empty under `--debug-flow`, the script SHALL render all three categories. When `--debug-components` lists a subset, the script SHALL render only the categories whose name appears in the list. Unknown values SHALL cause the script to print a clear error message and exit with status `2`.

#### Scenario: Flag absent keeps default behavior
- **WHEN** the operator runs `python -m backend.scripts.cli_chat_client` without `--debug-flow`
- **THEN** the script sends no `X-Debug-Flow` header, prints no `CLASSIFIER INPUT` / `CLASSIFIER OUTPUT` / `RESOLVER INPUT` / `RESOLVER OUTPUT` tables, and the existing customer-facing and order-table behavior is unchanged

#### Scenario: Flag present activates debug mode
- **WHEN** the operator runs `python -m backend.scripts.cli_chat_client --debug-flow`
- **THEN** the script sends `X-Debug-Flow: 1` on every `POST /comercios/.../incoming-messages` request and renders the diagnostic tables included in the response payload

#### Scenario: Unknown component value exits with error
- **WHEN** the operator runs `python -m backend.scripts.cli_chat_client --debug-flow --debug-components foo`
- **THEN** the script prints a clear error message that mentions `foo` and exits with status `2`

### Requirement: CLI prints diagnostic tables between customer responses and order table

When `--debug-flow` is enabled and the response payload contains a `diagnostics` list, the script SHALL render the diagnostic tables between the customer-facing `<- message=...` / `<- raw=...` lines and the `Pedido actual:` table. The script SHALL print the tables in chronological order by `(sequence, phase)` tuple. The script SHALL use only the Python standard library to render the tables; it SHALL NOT introduce a third-party table-formatting dependency. The script SHALL NOT add additional HTTP calls for diagnostics.

#### Scenario: Output order is customer-facing then diagnostics then order table
- **WHEN** the API returns an executed `agregar_producto` response with a `diagnostics` list and the detail endpoint returns a non-empty order
- **THEN** the script prints the customer response first, then the diagnostic tables, then the `Pedido actual:` table

#### Scenario: Diagnostic tables do not trigger extra HTTP calls
- **WHEN** the API returns a response with a `diagnostics` list
- **THEN** the script issues no additional HTTP requests to render the diagnostic tables and uses only the data already in the response payload

### Requirement: CLI redacts secrets in diagnostic tables

The script SHALL walk the response payload (including the `diagnostics` field) and replace any value whose key (case-insensitive) is one of `password`, `token`, `api_key`, `authorization`, `secret`, `database_url`, `DATABASE_URL`, `Authorization`, `X-API-Key`, or `X-API-KEY` with the string `<redacted>` before printing.

#### Scenario: Password field is redacted in the CLI
- **WHEN** the response payload contains a `diagnostics` event with a `password` field
- **THEN** the rendered table contains `<redacted>` and never contains the literal password value

#### Scenario: Database URL is redacted in the CLI
- **WHEN** the response payload contains a `diagnostics` event with a `database_url` field
- **THEN** the rendered table contains `<redacted>` and never contains the literal URL

### Requirement: CLI preserves import boundary in debug mode

The new diagnostic helpers (`_format_kv_table`, `_format_intent_table`, `_format_pending_state_snapshot`, `_format_pending_queue_table`, `_extract_diagnostics`, `_render_diagnostics`, `_redact_payload`, `_parse_debug_components`) SHALL use only the standard library (`urllib.request`, `json`, `argparse`, `sys`, `os`, `dataclasses`) and SHALL NOT introduce a third-party table library, a third-party HTTP client, or any `backend.*` module.

#### Scenario: Static import boundary still holds for diagnostic helpers
- **WHEN** the module `backend.scripts.cli_chat_client` is loaded
- **THEN** the imports of the module and the source code contain none of `fastapi`, `sqlalchemy`, `uvicorn`, `requests`, `httpx`, `aiohttp`, `websockets`, and none of `backend.routers`, `backend.services`, `backend.repositories`, `backend.intents`, `backend.llm`, `backend.models`, `backend.alembic`, `backend.dependencies`

