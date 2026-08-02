## Why

Subphase 3.29 exposed the modern intents pipeline through `POST /comercios/{comercio_id}/clientes/{cliente_id}/incoming-messages`, but exercising it still requires `curl` (or equivalent) per message. There is no local, human-driven way to drive a continuous conversation against an active session from the terminal. Subphase 3.30 adds a standalone CLI HTTP client that creates a fresh session, replays each typed line through the 3.29 endpoint, prints the pipeline's responses, and closes the session on exit — so a developer can manually iterate on intents, recognizers, and response builders without leaving the terminal.

## What Changes

- Add a standalone Python CLI script at `backend/scripts/cli_chat_client.py` (no FastAPI router, no service, no DB access) that talks to the running API exclusively over HTTP using the standard library `urllib.request` — no new HTTP client dependency.
- The script prompts for `comercio_id` and `cliente_id` (integers, re-prompted on `ValueError`), then `POST /sessions` with `{"id_comercio": ..., "id_cliente": ...}` to create a brand-new session derived from the running API. The returned session id is held in memory for the duration of the conversation.
- The script enters a read-eval-print loop using `input()`: each non-empty line is sent to `POST /comercios/{comercio_id}/clientes/{cliente_id}/incoming-messages` with `{"message": "<line>"}`; the endpoint's `responses` list is printed to stdout (one line per response, prefixed with `<-`, falling back to `raw=<dict>` if the payload lacks the expected shape). The same session is reused for every turn.
- Empty input is silently ignored (the loop continues without a network call). The literal string `exit` (case-insensitive, after `.strip()`) breaks the loop and triggers session cleanup.
- On exit, the script `POST /sessions/{session_id}/cerrar` to close only the session it created. If the close call fails (network error, server already gone, session already closed), the script prints a single warning line and exits `0` — it never raises.
- The base URL is configurable via a `--base-url` CLI flag (default `http://127.0.0.1:8000`) and an `INCOMING_MESSAGES_BASE_URL` environment variable; the flag wins over the env var, the env var wins over the default. The script never starts, stops, restarts, or mutates the FastAPI/Uvicorn process.
- The script is registered as a console-script-style entry point via `python -m backend.scripts.cli_chat_client` so it can be run without adjusting `PYTHONPATH`.
- Add focused tests in `backend/tests/test_cli_chat_client.py` that monkey-patch `urllib.request.urlopen` to return canned responses and assert: (a) the session-create call is made on start with the supplied ids, (b) each non-empty typed line triggers exactly one `POST /comercios/.../incoming-messages` with the typed text, (c) the printed output matches the pipeline's `responses` list, (d) empty input triggers no HTTP call, (e) entering `exit` ends the loop and triggers `POST /sessions/{id}/cerrar` exactly once, (f) a failure during close is swallowed and the script still exits `0`, (g) the script never imports `fastapi`, `sqlalchemy`, `uvicorn`, or any `backend.routers` / `backend.services` / `backend.repositories` module.

## Capabilities

### New Capabilities

- `incoming-messages-interactive-cli`: Defines the standalone terminal CLI HTTP client that drives a conversation against the existing `POST /incoming-messages` endpoint. Covers the create-session handshake, the read-eval-print loop sending each typed line to the existing endpoint, the response printing contract, the `exit`-only termination path, the single-session close on exit, the configurable base URL precedence (`--base-url` > `INCOMING_MESSAGES_BASE_URL` > `http://127.0.0.1:8000`), and the strict out-of-bounds rules (no FastAPI/uvicorn lifecycle, no DB access, no service/router/repository imports, no new third-party HTTP client, no Twilio integration, no async, no retry/backoff, no logging framework, no session creation by any path other than `POST /sessions`).

### Modified Capabilities

_None._ The existing `incoming-messages-local-http-endpoint` capability is unchanged; 3.30 only consumes it over HTTP.

## Impact

- New files: `backend/scripts/__init__.py`, `backend/scripts/cli_chat_client.py`, `backend/tests/test_cli_chat_client.py`.
- Reused unchanged: `POST /sessions` and `POST /sessions/{id}/cerrar` from `backend/routers/sessions.py`; `POST /comercios/{comercio_id}/clientes/{cliente_id}/incoming-messages` from `backend/routers/incoming_messages.py` (Subphase 3.29); `CustomerResponse` from `backend/intents/schemas/customer_response.py`; the standard library only (`urllib.request`, `json`, `argparse`, `sys`, `os`).
- Not touched: `backend/main.py`, `backend/routers/`, `backend/services/`, `backend/repositories/`, `backend/intents/`, `backend/llm/`, `backend/dependencies.py`, `backend/config/`, `backend/models/`, `backend/alembic/`, `backend/tests/api_smoke.py`, no Alembic migration, no new dependency in `requirements.txt`.
- Not introduced: FastAPI app / uvicorn lifecycle, `requests` / `httpx` / `aiohttp` / `websockets` clients, SQLAlchemy / database access, Twilio adapter, queue promotion, async wrappers, retry/backoff, logging framework, state persistence across invocations, multi-session management, configuration driven by `.env` files, new HTTP endpoints, modifications to schemas, models, recognizers, resolvers, processors, handlers, dispatchers, orchestrators, response builders, contracts, repos, services, or any LLM module.
