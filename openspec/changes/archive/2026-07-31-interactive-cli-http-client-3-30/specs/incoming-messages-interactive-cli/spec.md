## ADDED Requirements

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
