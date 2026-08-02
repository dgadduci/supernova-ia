## Context

Subphase 3.29 exposed the modern intents pipeline through `POST /comercios/{comercio_id}/clientes/{cliente_id}/incoming-messages`. Exercising it today requires a manual `curl` per turn, which is tedious for QA and impossible to use as a conversational loop. The active session is resolved server-side by the existing `SessionService.get_active(comercio_id, cliente_id)`, so as long as a single active session exists for the pair, the same session is reused across calls.

There is no current CLI in the project. `backend/old_project/` exists and is explicitly out of scope. The FastAPI/Uvicorn process is already running externally; the script must be a pure HTTP client that never touches FastAPI, SQLAlchemy, or any backend module.

The script lives in `backend/scripts/` (new directory) and is invokable as `python -m backend.scripts.cli_chat_client`. The runtime contract is encoded in `openspec/changes/interactive-cli-http-client-3-30/specs/incoming-messages-interactive-cli/spec.md`.

## Goals / Non-Goals

**Goals:**
- Standalone terminal CLI that drives a continuous conversation via the existing HTTP API.
- Single new session per run; explicit cleanup on exit.
- Strict stdlib-only HTTP client; no new dependency.
- Testable through monkey-patching of `urllib.request.urlopen`.

**Non-Goals:**
- Browser UI, HTMX, WebSocket, REPL endpoint, queue workers, Twilio integration.
- Multi-session orchestration, conversation history persistence, retry/backoff.
- Starting/stopping/restarting the FastAPI/Uvicorn server.
- Importing any `backend.*` module, `fastapi`, `sqlalchemy`, `uvicorn`, `requests`, `httpx`, `aiohttp`, `websockets`.

## Decisions

### 1. stdlib `urllib.request` only

**Why:** the spec mandates stdlib-only HTTP. `urllib.request` is enough for three POSTs with JSON bodies, the response body is read with `response.read().decode("utf-8")` and parsed with `json.loads`. Timeout is set via `urllib.request.urlopen(req, timeout=10)`; failures surface as `URLError` / `HTTPError` which the script catches locally.

**Alternatives considered:**
- `requests` — adds a dependency for three calls, rejected.
- `httpx` — same, rejected.
- raw `socket` — too low-level, rejected.

### 2. Single module `cli_chat_client.py` with `if __name__ == "__main__":` guard

**Why:** the script is small enough (~80 lines) that splitting it into a package would be over-engineering. The module exposes a `main()` function plus a small set of helpers (`_post_json`, `_read_int`, `_print_responses`) so tests can monkey-patch precisely without depending on the full `main()` flow. The `__main__` guard is a single line calling `main()`.

**Alternatives considered:**
- A class encapsulating state — `comercio_id`, `cliente_id`, `session_id`, `base_url` are already cohesive; a small `@dataclass` is acceptable but a plain dict-and-functions split is simpler. Going with functions.
- A `click`/`typer` CLI — adds a dependency for two flags, rejected.

### 3. Base URL precedence: `--base-url` > env > default

**Why:** keeps the same total order already used for `LLM_URL` in `backend/config/settings.py` (env var with default). The flag lets a developer point at a different host without touching the shell env. Implemented in a single `_resolve_base_url(args) -> str` helper so the precedent is explicit and unit-testable.

**Alternatives considered:**
- Only env var — fragments the typical "run against another port" workflow.
- Only flag — requires the flag every time; loses the env-var convenience.

### 4. Session creation is the first HTTP call

**Why:** the script is bound to a single session id from the moment the conversation starts. Creating too early (e.g. at import time) would block any future test that needs to mock the create call; creating inside `main()` after the prompts keeps the boundary clean. The close call lives in a `try/finally` so even an unexpected exception during the loop still triggers the close attempt.

**Alternatives considered:**
- Lazy create on first message — would require a `None` session state and a branch in the loop. Rejected: the spec says "create a new session through the existing HTTP API" up front.

### 5. Response printing: `<- key=value` per response, `raw=<dict>` fallback

**Why:** keeps the output greppable and aligned with the typical CLI pattern (one line per logical message). When the response carries a `message` field, the script prints `message=<value>`; otherwise it prints the whole dict via `json.dumps(payload, ensure_ascii=False)`. The spec dictates the prefix `<- ` and the fallback wording.

**Alternatives considered:**
- Pretty-printed JSON — verbose, harder to skim.
- Just the `message` field — loses the `intent`/`status` context.

### 6. `exit` is case-insensitive after `.strip()`

**Why:** matches the spec's "literal string exit (case-insensitive, after .strip())" rule. Implemented as `if line.strip().lower() == "exit"`, lives in the loop body only — it does not interfere with empty-input handling.

### 7. Close failures are non-fatal

**Why:** the script's job is to drive a conversation; the session will be reaped by the next `POST /sessions` for the same pair anyway. Wrapping the close call in its own `try/except Exception` and printing a single warning line keeps the script predictable for QA workflows that may kill the server between input and exit.

### 8. Tests monkey-patch `urllib.request.urlopen` at the module's import site

**Why:** the spec says scripts SHALL talk to the API via `urllib.request`. Mocking at the import site (`backend.scripts.cli_chat_client.urlopen`) lets the test provide a `MagicMock` returning a fake response object with `.read()`, `.status`, `.getcode()`. The tests feed `input()` via `unittest.mock.patch("builtins.input", side_effect=[...])`.

**Alternatives considered:**
- Spinning up a real `fastapi.testclient.TestClient` — would couple the CLI tests to the FastAPI app, violating the "no FastAPI import" boundary check.
- `responses`/`httpretty` — adds a test dependency; rejected.

## Risks / Trade-offs

- **No connection retry / timeout tuning beyond `timeout=10`** — a hung server will block the loop for 10 seconds. → Mitigation: the script already handles `URLError` by printing the error and continuing the loop (the next message triggers a fresh attempt), so a transient blip is recoverable. Documented in the script's docstring.
- **Concurrent runs against the same `(comercio_id, cliente_id)` collide on the partial unique index** — the active session is unique per pair. → Mitigation: the documented workflow is "one CLI run per pair at a time"; the spec already says a `409` on create is fatal for the script, which is the right behavior for this single-session model.
- **No history persistence across invocations** — by design. The user may want to re-run the script to inspect a clean conversation. → Mitigation: explicit per spec.
- **No internationalization of the printed prefix** — `<- ` is a fixed prefix. → Mitigation: matches the spec exactly; locale-specific output is out of scope.
- **Loss of the response shape if FastAPI returns a non-JSON error body** — the script catches `json.JSONDecodeError` and prints the raw bytes. → Mitigation: keeps the script informative without crashing.

## Migration Plan

Not applicable. This is an additive change that introduces a new script and its tests. No schema, model, migration, dependency, or existing-API change is involved. Rollback is `git rm` of the new files.

## Open Questions

None. The user's input and the spec captured every decision; the rest are mechanical implementations.
