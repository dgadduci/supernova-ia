## Context

The legacy `query_llm.py` defines the contract for LLM interactions that future intent classification will reuse, but the new project must not import or modify it. Subphase 3.21 introduces a configurable settings module and a clean synchronous HTTP client that honors the same payload semantics while exposing a strict, testable interface for upcoming classifier code.

## Goals / Non-Goals

**Goals:**
- Provide configurable settings with local defaults and environment overrides for the LLM endpoint and model options.
- Provide a synchronous HTTP client that posts prompts and parses JSON responses with explicit error handling.
- Emit structured logging metadata at INFO level and optional content logs at DEBUG only when explicitly enabled.
- Keep the module test-friendly by allowing HTTP transport to be replaced and avoiding shared mutable state.

**Non-Goals:**
- Implementing intent classification, prompt construction, or schema validation.
- SQLAlchemy, Alembic, FastAPI, or Session integration.
- Modifying the legacy classifier prompt or importing the legacy module.

## Decisions

- Use `requests` (or an equivalent HTTP client already in the venv) for synchronous calls because the contract is synchronous and reduces dependency surface.
- Load settings via a small helper that reads environment variables with defaults; keep the values immutable per process to avoid request-time mutation.
- Build the request payload as a frozen mapping per call; never share mutable request state between calls.
- Parse JSON strictly; fall back to extracting the substring between the first `{` and last `}` only when the raw body is non-empty, and raise a clear exception on empty or invalid JSON.
- Define distinct exception types (or reuse simple `RuntimeError` subclasses) for timeout, connection, and HTTP errors so callers can distinguish them.
- Use `logging.getLogger(__name__)` and never configure global handlers inside the module.
- Truncate logged prompts and responses using the configured `LLM_LOG_MAX_CHARS`.
- Make `QueryLlm.request` instance-level so tests can stub the underlying transport per instance without leaking state between cases.

## Risks / Trade-offs

- [Risk] Future tests might depend on global request state → Mitigation: store no per-instance state between calls; expose HTTP transport injection.
- [Risk] Logging prompt content can leak secrets → Mitigation: only log full content at DEBUG with explicit opt-in; truncate and never log headers.
- [Risk] Ad-hoc retry/circuit-breaker logic is omitted → Mitigation: leave retries to a future subphase that introduces a higher-level wrapper.

## Migration Plan

1. Inspect the legacy file only as reference, without importing it.
2. Add `backend/config/settings.py` with the configurable values and overrides.
3. Add `backend/llm/__init__.py` and `backend/llm/query_llm.py` with the HTTP client.
4. Add focused tests mocking the HTTP transport.
5. Run the test suite and the compile check; rollback by deleting the new modules if needed.

## Open Questions

None.
