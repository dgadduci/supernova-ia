## 1. Module scaffolding

- [x] 1.1 Create `backend/scripts/__init__.py` (empty package marker).
- [x] 1.2 Create `backend/scripts/cli_chat_client.py` with: a module-level `__all__` listing only `main`, `_post_json`, `_read_int`, `_print_responses`, `_resolve_base_url`, `_close_session`, `_create_session`; a module docstring stating the script's purpose and the no-server-management boundary.
- [x] 1.3 Add a `__main__` guard that calls `main()` so the script is runnable via `python -m backend.scripts.cli_chat_client`.

## 2. HTTP helpers

- [x] 2.1 Implement `_post_json(url: str, body: dict, timeout: int = 10) -> tuple[int, dict | str]` that builds a `urllib.request.Request` with `Content-Type: application/json`, posts `json.dumps(body).encode("utf-8")`, returns `(status_code, parsed_dict_or_raw_string)`. Catch `urllib.error.HTTPError` to expose its `.code` and decoded body; catch `urllib.error.URLError` and `json.JSONDecodeError` and re-raise as `RuntimeError` with a single-line message.
- [x] 2.2 Implement `_resolve_base_url(argv: list[str]) -> str` that accepts `--base-url <value>` via `argparse`, falls back to `os.environ.get("INCOMING_MESSAGES_BASE_URL")`, then to `http://127.0.0.1:8000`. Return the resolved URL with no trailing slash.

## 3. Session lifecycle

- [x] 3.1 Implement `_create_session(base_url: str, comercio_id: int, cliente_id: int) -> int` that posts `{"id_comercio": comercio_id, "id_cliente": cliente_id}` to `{base_url}/sessions`, raises `SystemExit` with a non-zero code on `409`, and returns the new `id` on `201`.
- [x] 3.2 Implement `_close_session(base_url: str, session_id: int) -> None` that posts to `{base_url}/sessions/{session_id}/cerrar` and swallows every exception, printing `warning: failed to close session <id>: <err>` to stdout on failure.

## 4. Read-eval-print loop

- [x] 4.1 Implement `_read_int(prompt: str) -> int` that wraps `input()` and re-prompts on `ValueError` until the user enters an integer.
- [x] 4.2 Implement `_print_responses(payload: dict) -> None` that iterates `payload.get("responses", [])`, prints `<- message=<value>` when the response has a `message` field, otherwise prints `<- raw=<json.dumps(response, ensure_ascii=False)>`.
- [x] 4.3 Implement `main()` that: resolves the base URL, reads `comercio_id` and `cliente_id`, creates the session, prints `<session N>`, then loops calling `input("[comercio={comercio_id} cliente={cliente_id} session={session_id}]> ")`, breaking on the `exit` rule and skipping empty lines. Each non-empty line is sent to `POST /comercios/{comercio_id}/clientes/{cliente_id}/incoming-messages` and the response is printed via `_print_responses`. The session is closed in a `try/finally` block before `main()` returns.

## 5. Tests

- [x] 5.1 Create `backend/tests/test_cli_chat_client.py` with a `FakeResponse` helper that exposes `.read()`, `.status`, `.getcode()` and is returned by a `fake_urlopen` side_effect callable.
- [x] 5.2 Add `test_creates_session_on_start` that monkey-patches `backend.scripts.cli_chat_client.urlopen` and `builtins.input` with `["1", "8"]`, then exits on `exit`, asserting the first call posts to `/sessions` with both ids and the response id is captured.
- [x] 5.3 Add `test_reuses_session_for_each_message` asserting two typed lines produce exactly two `POST /comercios/.../incoming-messages` calls and no second `POST /sessions` call.
- [x] 5.4 Add `test_prints_pipeline_responses` asserting the printed output matches `<- message=<value>` for the standard response and `<- raw=<dict>` for a response missing `message`.
- [x] 5.5 Add `test_empty_input_makes_no_http_call` asserting a blank line yields zero `urlopen` calls for that iteration.
- [x] 5.6 Add `test_exit_breaks_loop_and_closes_session` asserting `exit` ends the loop and triggers `POST /sessions/{id}/cerrar` exactly once.
- [x] 5.7 Add `test_close_failure_is_non_fatal` asserting that a `URLError` from the close call still produces `SystemExit(0)` and a single warning line.
- [x] 5.8 Add `test_base_url_resolution` covering all three precedence cases (flag, env, default).
- [x] 5.9 Add `test_import_boundary` asserting `backend.scripts.cli_chat_client` does not import any banned module by reading the module's `__dict__` after import and checking every value is not a banned module (use `sys.modules` checks).

## 6. Verification

- [x] 6.1 Run `PYTHONPATH=. ./venv/bin/python -m unittest backend.tests.test_cli_chat_client -v` and confirm all tests pass.
- [x] 6.2 Smoke-test against the live server with seeded ids: `PYTHONPATH=. ./venv/bin/python -m backend.scripts.cli_chat_client` (using `comercio_id=1, cliente_id=8`, then send `hola`, then `exit`), confirming the existing session ends up closed and the printed response lines up with the spec.
- [x] 6.3 Confirm no other module was touched: `git status` (or `git diff --stat` if a git repo) shows only the new files under `backend/scripts/` and `backend/tests/`.
