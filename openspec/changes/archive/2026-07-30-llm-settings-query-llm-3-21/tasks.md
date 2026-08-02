## 1. Settings Module

- [x] 1.1 Inspect the legacy `query_llm.py` only as reference; do not import or modify it.
- [x] 1.2 Create `backend/config/settings.py` defining `LLM_URL`, `LLM_MODEL`, `LLM_TIMEOUT`, `LLM_KEEP_ALIVE`, `LLM_NUM_CTX`, `LLM_NUM_PREDICT`, `LLM_LOG_CONTENT`, and `LLM_LOG_MAX_CHARS` with local defaults and environment overrides.

## 2. QueryLlm HTTP Client

- [x] 2.1 Create `backend/llm/__init__.py` and `backend/llm/query_llm.py` exposing `QueryLlm().request(prompt: str) -> dict`.
- [x] 2.2 Build the payload with `stream=False`, `think=False`, `format="json"`, `temperature=0`, model, prompt, and configured numeric options.
- [x] 2.3 Parse clean JSON, fall back to extracting the substring between the first `{` and last `}` when the raw body is non-empty, and reject empty or invalid JSON with clear exceptions.
- [x] 2.4 Distinguish timeout, connection, and HTTP errors with clear exceptions, never return `None`, never call `print`, and keep no mutable request state between calls.
- [x] 2.5 Emit INFO logs for request start, configured model, request duration, success/failure, and HTTP status when available; emit DEBUG content logs only when `LLM_LOG_CONTENT` is enabled, truncating with `LLM_LOG_MAX_CHARS`; do not configure global logging handlers; use `logging.getLogger(__name__)`.

## 3. Verification

- [x] 3.1 Add focused tests using mocked transport covering payload contents, clean JSON parsing, JSON extraction, empty/invalid response rejection, timeout/HTTP errors, empty prompt rejection, INFO metadata logging, and DEBUG content logging with truncation.
- [x] 3.2 Run the focused tests and report results.
- [x] 3.3 Run `PYTHONPATH=. venv/bin/python -m compileall backend`.
