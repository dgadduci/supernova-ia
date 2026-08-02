## ADDED Requirements

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
