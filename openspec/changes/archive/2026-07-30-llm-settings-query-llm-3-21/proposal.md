## Why

The project needs configurable LLM settings and a synchronous HTTP client that future intent classification will reuse. Subphase 3.21 introduces those building blocks without implementing any classifier logic, so the legacy prompt and contracts remain untouched.

## What Changes

- Add configurable LLM settings (`LLM_URL`, `LLM_MODEL`, `LLM_TIMEOUT`, `LLM_KEEP_ALIVE`, `LLM_NUM_CTX`, `LLM_NUM_PREDICT`, `LLM_LOG_CONTENT`, `LLM_LOG_MAX_CHARS`) with environment overrides and local defaults.
- Add `backend/llm/query_llm.py` providing a synchronous HTTP client with strict payload, JSON parsing, and exception handling.
- Use Python `logging` for request lifecycle and optional content logs without exposing secrets.
- Add focused tests that mock HTTP and verify the new contract.
- Do not modify or import the legacy `query_llm.py`.

## Capabilities

### New Capabilities
- `llm-settings`: Defines the configurable LLM settings with local defaults and environment overrides.
- `llm-query-client`: Defines the synchronous HTTP client used by future classification flows.

### Modified Capabilities

## Impact

- New file `backend/config/settings.py` for LLM settings.
- New file `backend/llm/query_llm.py` for the HTTP client.
- New tests for settings and `QueryLlm` HTTP behavior.
- No changes to recognizer, resolver, processor, dispatcher, handler, services, pending context execution, or intent classification logic.
- No SQLAlchemy, Alembic, FastAPI, or Session integration changes.
