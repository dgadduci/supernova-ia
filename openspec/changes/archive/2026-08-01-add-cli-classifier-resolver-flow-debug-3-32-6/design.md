## Context

`backend/scripts/cli_chat_client.py` is a strict HTTP-only Python client that drives a long-running conversation against the local FastAPI server through `urllib.request`. It does not import any `backend.*` module, does not start, stop, or restart the server, and does not inject anything into the running process. Every line typed by the operator is sent as `POST /comercios/{comercio_id}/clientes/{cliente_id}/incoming-messages`, and the CLI prints whatever the response payload contains — currently the customer-facing response, the order-mutating intent set (`agregar_producto`, `quitar_producto`, `modificar_producto`), and, when an order modification is detected, the draft `Pedido` table fetched from `GET /pedidos/{pedido_id}/detalle`.

The modern pipeline inside the server runs in a separate process. The intent classifier (`backend/llm/intent_classifier.py`) is invoked exactly once per incoming message, and every resolver in the product flow (`ProductSelectionContextResolver`, the pending-context resolver, the resolvers invoked after a queued intent is promoted, and the `modificar_producto` resolver when it shares the path) is invoked zero or more times per incoming message. None of those in-process calls is reachable from the CLI today: the CLI only sees the final response payload, the customer-facing text, and the order state through the existing detail endpoint.

Subphase 3.32.6 mandates an opt-in `--debug-flow` mode that prints the exact input and output of each classifier call and each resolver call in chronological order, so the operator can trace the data flow without leaving the CLI. The mandatory architecture inspection (per the project.md subphase definition) drove the mechanism choice below.

### Mandatory architecture inspection

1. **Does the CLI call the FastAPI endpoint over HTTP?** Yes. The CLI is a standalone `urllib.request`-only client; it never imports `fastapi`, `sqla`, `backend.*`, or any backend module. The server runs in a separate process started by `uvicorn backend.main:app`.
2. **Do the classifier and resolver execute in the same process as the CLI?** No. They execute inside the FastAPI server process. The CLI cannot inject Python objects into the server.
3. **Does current dependency injection permit an observer/sink?** Yes — process-local. The server uses `Depends(...)` for the database session and for service/repo wiring. A request-scoped `DiagnosticSink` is a clean fit: the FastAPI dependency can construct a `CollectingDiagnosticSink` when the request carries the `X-Debug-Flow` header and a `NoopDiagnosticSink` otherwise. The classifier and resolvers already receive the dependency-injected context they need to emit events; the only addition is an optional sink parameter that defaults to `NoopDiagnosticSink()`.
4. **Do the response schemas currently allow debug metadata?** Yes — the incoming-messages response is a `dict` payload assembled in the router from `responses`. The router can attach a `diagnostics` field when the `X-Debug-Flow` header is present and skip it otherwise. The default response shape is unchanged.
5. **Does structured logging already exist?** Yes — `logging.getLogger(__name__)` is used in the classifier and resolvers. The sink is an additional, opt-in, structured event channel that is independent of the existing logging setup. The two coexist; the sink is silent by default and emits only when the debug header is on.
6. **Smallest and safest mechanism?** A debug-only `X-Debug-Flow` request header that activates a request-scoped `CollectingDiagnosticSink` in the orchestrator. The header is opt-in (CLI only sends it when `--debug-flow` is on), the default response omits any diagnostic field, and the server emits exactly the same number of classifier and resolver calls with and without the header. There is no need for a new endpoint, a new table, a new file format, or a new process.
7. **Why does the chosen mechanism not duplicate calls or alter business flow?** The sink is invoked immediately before and after the real classifier call and each real resolver call. It never re-runs the call, never re-classifies, never re-resolves, never queries the database for diagnostics, never commits, never rolls back. The sink observes the real call and returns; the next instruction is the unmodified business flow.

### Constraints

- Stdlib-only CLI; no `fastapi`, `sqlalchemy`, `requests`, `httpx`, `aiohttp`, `websockets`, or `backend.*` import in the CLI.
- The default response payload (no `X-Debug-Flow` header) keeps the exact same shape and size as before.
- Secrets must be redacted as `<redacted>`: `password`, `token`, `api_key`, `authorization`, `secret`, `database_url`.
- No duplicate classifier or resolver calls. The sink observes the real call; it never re-runs it.
- No new third-party dependency. The serializer and the table formatter use only the standard library and the existing `format_order_table` style.
- No commit, rollback, flush, or new SQLAlchemy query for diagnostics.

## Goals / Non-Goals

**Goals:**

- Add an opt-in `--debug-flow` CLI flag and an optional `--debug-components classifier,resolver,pending` filter to `backend/scripts/cli_chat_client.py`.
- Add a backend `diagnostics` module with a `DiagnosticSink` protocol, a `NoopDiagnosticSink` default, a `CollectingDiagnosticSink` that aggregates events for the current request, and structured event types (`ClassifierCallStarted`, `ClassifierCallCompleted`, `ResolverCallStarted`, `ResolverCallCompleted`, `PendingStateSnapshot`).
- Add a safe recursive serializer that supports dataclasses, Pydantic models, enums, already-detached SQLAlchemy projection rows, dicts, lists, tuples, and primitives; redacts secret-named fields; avoids lazy-loading and recursion loops; produces deterministic output.
- Instrument the real `IntentClassifier.query` call and every real resolver call reachable from the incoming-message pipeline. The sink is a no-op by default; the existing call sites keep their exact behavior.
- Extend the FastAPI incoming-messages router to accept an `X-Debug-Flow` header. When present, the response payload includes a `diagnostics: list[dict]` field sorted by sequence number. When absent, the field is absent.
- Render the CLI tables (`CLASSIFIER INPUT`, `CLASSIFIER OUTPUT`, `RESOLVER INPUT`, `RESOLVER CANDIDATES`, `RESOLVER OUTPUT`, `RESOLVER MATCHES`, `PENDING STATE`, `PENDING QUEUE`) using the same stdlib-only table style as the existing `format_order_table`, with sequential `CLS-NNN` / `RES-NNN` call IDs and `TURN N` headers.
- Add focused unit tests for the serializer, the sink, the event shape, the `X-Debug-Flow` header activation, the CLI flag parsing, the disabled-by-default contract, the no-duplicate-call contract, and the existing business regressions.

**Non-Goals:**

- Changing the classifier prompt, the selection thresholds, the matching rules, the queue promotion logic, the response ordering, the transaction ownership, or the customer-facing text.
- Adding a new production endpoint, a new database column, a new model, a new Alembic migration, a new dependency, a new logging framework, or a new third-party table library.
- Persisting diagnostic events to disk, to a database, or to a queue. Diagnostics live in the response payload only.
- Diagnostic fields in the default response. The `diagnostics` field appears only when the `X-Debug-Flow` header is present.
- Exposing diagnostics to Twilio, WhatsApp, or any external HTTP caller. The CLI is the only consumer.
- Re-running the classifier or any resolver solely to produce debug output. The sink observes the real call.
- Adding new intent types, new handlers, or new response builders.
- Modifying the existing `format_order_table` behavior, the existing `ORDER_MUTATING_INTENTS` constant, or the existing `pedido-detalle` endpoint.
- Synchronizing specs or archiving the change automatically. Both require manual `/opsx-sync` and `/opsx-archive` invocations.

## Decisions

### D1. Diagnostic transport: `X-Debug-Flow` header + response-side `diagnostics` field

**Decision.** The CLI sends `X-Debug-Flow: 1` on every `POST /comercios/{comercio_id}/clientes/{cliente_id}/incoming-messages` request when `--debug-flow` is enabled. The FastAPI router reads the header via a `Header(None)` dependency and, when present, builds a request-scoped `CollectingDiagnosticSink` that the orchestrator consults at every instrumented call site. When the header is absent, the dependency returns a `NoopDiagnosticSink`. The router also returns the `diagnostics` field in the response payload only when the header is set.

**Rationale.** The CLI is HTTP-only and runs in a separate process, so a process-local observer is impossible. An HTTP header is the smallest mechanism that lights up an in-process sink without duplicating calls. The header is opt-in (CLI only sends it when the flag is on), the default response stays byte-for-byte identical, and the sink is silent by default. The transport mechanism is hidden from the rest of the application: services, resolvers, and the classifier see only a dependency-injected `DiagnosticSink` interface.

**Alternatives considered.** A separate `GET /admin/diagnostics/...` endpoint was rejected because it would require the CLI to issue a second HTTP call per incoming message and would risk polluting the cache with stale events. A persistent event log consumed by an external tool was rejected because the spec is explicit: "no persisted diagnostic state". Structured logging to a sidecar file was rejected because it would require the CLI to tail a file and would couple the CLI to the server's logging configuration. A new Response field always-on was rejected because the spec is explicit: "Do not blindly add diagnostic fields to normal production responses".

### D2. `DiagnosticSink` protocol and `NoopDiagnosticSink` default

**Decision.** Define a `DiagnosticSink` protocol in `backend/diagnostics/sink.py` with five methods: `on_classifier_started`, `on_classifier_completed`, `on_resolver_started`, `on_resolver_completed`, `on_pending_state_snapshot`. The protocol is the only thing the classifier and resolver call sites depend on. The default implementation is `NoopDiagnosticSink`, which has empty methods and is constructed in the FastAPI dependency when the header is absent. The active implementation is `CollectingDiagnosticSink`, which records events in a list and is constructed when the header is present.

**Rationale.** A protocol is the standard Python shape for "dependency-inject a strategy that does nothing by default". The classifier and resolvers must always call the sink (no `if sink is not None:` branch), so the call sites stay linear and the no-op default imposes no runtime cost beyond a couple of method calls. The `CollectingDiagnosticSink` is constructed once per request and lives in the request scope; the events are serialized and returned in the response at the end of the request.

**Alternatives considered.** A `None` default with `if sink is not None:` checks at every call site was rejected because it pollutes the call sites and makes it easy to forget a signal. A global module-level sink was rejected because it would leak events across requests and would be impossible to disable per request. A logger-only sink was rejected because logs are not the right shape for structured per-call data and would not be machine-readable.

### D3. Structured event types in `backend/diagnostics/events.py`

**Decision.** Define five dataclasses:

- `ClassifierCallStarted(call_id, turn_id, component, method, timestamp, raw_message, normalized_message, active_context_type, has_active_pending_intent, active_pending_intent, queued_intent_count, classifier_class, classifier_method, prompt_name, model)`
- `ClassifierCallCompleted(call_id, turn_id, component, method, timestamp, result, intent_count, unknown_fragments, raw_response_metadata, parse_errors, fallback_state)`
- `ResolverCallStarted(call_id, turn_id, component, method, resolver_purpose, session_id, context_type, incoming_text, normalized_text, intent, source_text, quantity, status_before, requirements_before, resolved_data_before, candidate_ids_before, candidate_count, candidate_catalog, queued_intent_count)`
- `ResolverCallCompleted(call_id, turn_id, component, method, result_type, status_after, selected_candidate_id, selected_product, quantity_after, requirements_after, resolved_data_after, candidate_ids_after, candidate_count_after, rejection_reason, clarification_message, raw_result, matches)`
- `PendingStateSnapshot(call_id, turn_id, snapshot_phase, active_intent, active_status, active_source_text, active_quantity, active_candidate_ids, queue_length, queue_intents, queue_sources, context_type)`

Each event has a `to_dict()` method that runs the safe recursive serializer. The router iterates the collected events in arrival order and serializes each one with the serializer.

**Rationale.** Dataclasses are the standard library shape for "structured value with named fields". Pydantic could also work, but the diagnostics module is at the bottom of the import graph and should not depend on Pydantic runtime cost. The five types match the five events the spec mandates. The fields match the project.md table contracts.

**Alternatives considered.** Pydantic models were rejected because the diagnostics module is meant to be cheap and importable from anywhere. A single `dict` payload was rejected because it loses compile-time type hints and makes the redactor less precise. A `TypedDict` was rejected because the spec calls for "structured event types" and dataclasses are clearer.

### D4. Safe recursive serializer with redaction

**Decision.** `backend/diagnostics/serializer.py` exports `serialize(value, *, redact=True, _seen=None) -> object`. The serializer handles:

- `None` → `None`.
- `bool`, `int`, `float`, `str` → identity (with `str` serialized as the raw UTF-8 string).
- `Enum` → `value.value`.
- `dict` → `{k: serialize(v, ...)` sorted by key (with non-string keys coerced to `str`). Skips keys whose lowercase name is in `_REDACTED_KEYS` (replaced with `<redacted>` when `redact=True`).
- `list`, `tuple`, `set`, `frozenset` → serialized element-wise. Tuples become lists; sets and frozensets are emitted in sorted order when the elements are sortable, otherwise in iteration order.
- `dataclasses` (including `is_dataclass(instance)` and not `is_dataclass(cls)`) → `serialize(asdict(instance))`.
- Pydantic v2 models → `serialize(instance.model_dump(mode="json"))`.
- SQLAlchemy ORM model instances whose class has a `__table__` attribute → enumerate `__table__.columns`, read the value, recurse. Skip relationship attributes (anything starting with `_` or anything whose name collides with a column on a related table, to avoid lazy loading).
- Anything else → the string `"<ClassName>"`, where `ClassName` is `type(value).__name__`.

Recursion is bounded by a `_seen` id-set per call. The serializer also caps depth at 64 levels and the total field count at 4096 per call to avoid pathological inputs.

**Rationale.** The serializer must handle the real return types — `IntentClassificationResult` (Pydantic), `ProcessedIntent` (Pydantic), `RequirementState` (Pydantic), `ContextType` (enum), `Pedido` (SQLAlchemy ORM), `ProductoPresentacion` (SQLAlchemy ORM), and primitive dicts — without lazy-loading or calling the database. The redaction set matches the project.md spec exactly. Bounded recursion and bounded depth prevent a malformed event from blowing the response.

**Alternatives considered.** Reusing `pydantic.json.dumps` was rejected because it does not handle SQLAlchemy ORM instances, dataclasses, set-like values, or the redaction policy. A flat `json.dumps(value, default=str)` was rejected because it produces unreadable output for SQLAlchemy instances and does not redact. Building a custom serializer per event type was rejected because the event shape is large and the serializer must be reusable.

### D5. Instrumented call sites — real calls only, no duplicates

**Decision.** The classifier and resolver call sites are wrapped with a `try / finally` block: `sink.on_*_started(...)` is called immediately before the real call, the real call is invoked, and `sink.on_*_completed(...)` is called immediately after with the real output. The instrumented sites are:

- `IntentClassifier.query` in `backend/llm/intent_classifier.py` (or, more precisely, the single call site in the incoming-message orchestrator that delegates to `IntentClassifier.query`).
- `ProductSelectionContextResolver.resolve` in `backend/intents/context/product_selection_context_resolver.py`.
- The pending-context resolver invoked from `backend/services/pending_context_service.py` (or wherever the drain-and-promote loop lives; it is the same call site that handles `pending_resolution` and `pending_selection` outcomes).
- The candidate refinement resolver invoked after a queued intent is promoted (the same code path that runs for the second item in `quiero una empanada de carne y una pizza`).
- The `modificar_producto` resolver when it shares the same diagnostic mechanism (the existing resolver instance is reused; the sink emits `RES-N` events for each call).

**Rationale.** Instrumenting the real call sites — not new functions — guarantees that the diagnostic output reflects the actual business flow. The `try / finally` ensures that `on_*_completed` is called even when the real call raises, so the CLI can render an error table with the exception type and the input that caused the failure. The `NoopDiagnosticSink` default means no observable cost in the default path.

**Alternatives considered.** Wrapping the classifier in a `DebugInstrumentedClassifier` subclass was rejected because it would require changing the dependency injection wiring in the classifier's construction sites and would risk drifting from the real call. A global monkey-patch was rejected because it would be invisible to type checkers and would not survive a refactor.

### D6. CLI flag parsing and `--debug-components` filter

**Decision.** The CLI's existing `_resolve_base_url` helper already uses `argparse.ArgumentParser(add_help=False)`. The CLI introduces a new `argparse.ArgumentParser` with `add_help=True` in `main()` and moves the `--base-url` flag there. Two new flags are added:

- `--debug-flow`: `action="store_true"`. When `True`, the CLI sends `X-Debug-Flow: 1` on every incoming-messages request and renders the diagnostic tables after each response.
- `--debug-components`: comma-separated list of `classifier`, `resolver`, `pending`. Defaults to all three when `--debug-flow` is enabled. Unknown values produce a clear error message and exit 2.

When `--debug-flow` is disabled, the CLI behavior is unchanged: no header is sent, no diagnostic tables are printed, no extra HTTP calls are made, no extra logging is produced.

**Rationale.** Keeping `--debug-flow` opt-in preserves the default behavior byte-for-byte. The `--debug-components` filter lets the operator focus on one component when the conversation is long. A separate `--debug-flow` flag (instead of a `DEBUG=1` env var) keeps the contract explicit and clear in the help text.

**Alternatives considered.** A `DEBUG=1` environment variable was rejected because the spec explicitly mentions a CLI flag. An `--all-debug` flag was rejected because the only valid scope is the data flow, and the spec uses `--debug-flow`. A `--debug-resolver` flag was rejected because the spec mandates `--debug-flow` and `--debug-components`. Implementing only `--debug-flow` and skipping `--debug-components` was rejected because the spec says "Optional filtering is recommended but not mandatory" — adding the filter is cheap and the spec nudges toward it.

### D7. Stdlib-only table formatter

**Decision.** Reuse the existing `format_order_table` style for the new diagnostic tables. The shared helpers live in a new module-level section of `backend/scripts/cli_chat_client.py` (no new module, no new dependency). The new helpers are:

- `_format_kv_table(title: str, rows: list[tuple[str, str]]) -> str`: a two-column key/value table with dynamic column widths.
- `_format_intent_table(title: str, headers: tuple[str, ...], rows: list[tuple[str, ...]]) -> str`: a multi-column table that reuses the same border layout as `format_order_table`.
- `_format_pending_state_snapshot(title: str, snapshot: dict) -> str`: a key/value table for the pending state.
- `_format_pending_queue_table(title: str, queue: list[dict]) -> str`: a multi-column table for the queue.

The `__all__` list expands to include the new helpers. No third-party table library is introduced.

**Rationale.** The existing `format_order_table` is stdlib-only, dependency-free, and tested. The new tables follow the same look and feel so the operator does not have to learn a new format. The dynamic-width computation is already implemented; the new helpers reuse it.

**Alternatives considered.** Introducing `tabulate` or `prettytable` was rejected because the spec forbids new dependencies. Implementing a new ad-hoc format was rejected because the existing one is already correct and tested. Writing the tables by hand in `_print_responses` was rejected because the existing renderer is the right home.

### D8. Redaction helper `_redact_payload`

**Decision.** The CLI exposes a `_redact_payload(payload: dict | list) -> dict | list` helper that walks the payload and replaces any value whose key is in `{"password", "token", "api_key", "authorization", "secret", "database_url", "DATABASE_URL", "Authorization", "X-API-Key", "X-API-KEY"}` with the string `<redacted>`. The helper is invoked once on every payload before the table is rendered. The helper is also used by the backend response builder to ensure the `diagnostics` field never contains secrets, even when the request handler accidentally includes a config dump.

**Rationale.** The spec is explicit about the redaction set. The CLI redaction is a defense-in-depth measure: even if the backend serializer forgot a field, the CLI would still redact it. The backend redaction is the source of truth: it prevents the secret from ever being sent on the wire.

**Alternatives considered.** Backend-only redaction was rejected because the spec explicitly tests the CLI redaction. CLI-only redaction was rejected because the server should not send secrets to the client in the first place. Both-belt-and-suspenders redaction is the right answer.

### D9. Routing the `diagnostics` field through the existing response builder

**Decision.** The router's existing handler returns a `dict` payload assembled from `responses`. The router is extended to read the `X-Debug-Flow` header, build a `CollectingDiagnosticSink` when the header is present, pass the sink to the orchestrator service, invoke the service, and then merge the sink's collected events into the response payload under the `diagnostics` key. When the header is absent, the router builds a `NoopDiagnosticSink` and the response payload omits the `diagnostics` key.

**Rationale.** The current response builder already returns a `dict`; adding a `diagnostics` key conditionally is the smallest change. The default response shape is unchanged. The header is read in the router (not in the service) so the service does not grow a transport concern.

**Alternatives considered.** A new `IncomingMessageResponseWithDiagnostics` Pydantic model was rejected because the spec forbids new schemas for the default response and the in-`dict` approach is simpler. A new `Response.add_diagnostics` helper was rejected because the existing builder is a one-line return and the in-`dict` approach is enough.

### D10. `call_id` allocation and event ordering

**Decision.** The `CollectingDiagnosticSink` allocates a global monotonic counter per request. The first classifier call gets `CLS-001`, the next `CLS-002`, and so on. The first resolver call gets `RES-001`, the next `RES-002`, and so on. The CLI renders the events in the order they were emitted, sorted by a `(phase, sequence)` tuple (`phase` is `classifier` for `CLS-*`, `resolver` for `RES-*`, `pending` for snapshots). The `TURN N` header is computed from the per-request turn counter incremented by the router.

**Rationale.** The spec calls for "deterministic sequence numbers" and "chronological order". The simplest ordering is arrival order. Sorting by `(phase, sequence)` keeps the tables grouped by component while preserving arrival order within each component.

**Alternatives considered.** Timestamps were considered but rejected because the spec says "Ordering must primarily use deterministic sequence numbers". Per-class counters (one for `CLS-*`, one for `RES-*`) were rejected because a single monotonic counter is simpler and the spec only requires the prefix to be unique.

## Risks / Trade-offs

- **The default response grows by a `diagnostics` field when the header is set, breaking the assumption that "the response is always the same shape".** → Mitigation: the field is present only when the CLI asks for it via the `X-Debug-Flow` header. The default response (no header) is byte-for-byte identical to before. The schemas list this field as optional.

- **The serializer might leak `<ClassName>` fallbacks for non-trivial Python objects.** → Mitigation: the instrumentation call sites emit only known event types (dataclasses, Pydantic models, primitives, dicts, lists, and SQLAlchemy ORM instances whose columns are listed). The serializer is tested with a fixture set of event payloads and asserts each field is either a primitive or a structured value.

- **Instrumenting call sites could accidentally add latency in the hot path.** → Mitigation: the `NoopDiagnosticSink` is a final class with empty methods; the JIT (CPython) inlines the call. The five `sink.on_*` calls per incoming message add < 1µs per call. The `CollectingDiagnosticSink` activation is gated on the `X-Debug-Flow` header, which is sent only by the CLI in debug mode.

- **Adding a `diagnostics` field to the response payload leaks Pydantic and SQLAlchemy internals to the CLI.** → Mitigation: the serializer never serializes Python `repr`, never lazy-loads, never calls the database, and never exposes private attributes. The CLI renders only the structured tables.

- **The CLI redaction helper could miss a new secret field added by a future subphase.** → Mitigation: the set of redacted keys is centralized in one constant (`_REDACTED_KEYS`) on both the backend and the CLI. The spec explicitly lists the keys; a new key requires updating both sides and the test suite.

- **Adding a `X-Debug-Flow` header in the CLI could be confused with a production header.** → Mitigation: the header is documented as debug-only and is never sent unless the CLI operator types `--debug-flow`. The server's CORS / API gateway configuration (when added) can block the header in production.

- **The change adds new tests and might fail in CI if the test database is not available.** → Mitigation: the new tests are unit tests that mock the FastAPI dependency (`TestClient` with a stub `NoopDiagnosticSink`) and the CLI's `urllib.request.urlopen`. No database fixture is required.

- **The new `backend/diagnostics/` module grows the import graph.** → Mitigation: the module is plain stdlib (no Pydantic, no SQLAlchemy), imports only from `__future__`, `dataclasses`, `enum`, `typing`, and the standard library. It does not import any other `backend.*` module, so the graph stays acyclic.

- **A future subphase might add a new resolver call site and forget to instrument it.** → Mitigation: the spec mandates "Instrument every resolver involved in the real product flow". The audit step in the test suite verifies that the drain-and-promote loop emits at least one resolver event per promoted intent.

- **The `diagnostics` field could be large for a multi-intent message.** → Mitigation: the field is plain JSON; the server caps the response size at 1 MB by overriding the default `Response` size. The serializer also caps field count and depth.

- **The CLI's `_format_pending_state_snapshot` and `_format_pending_queue_table` rely on the `PendingIntents` payload being a `dict`.** → Mitigation: the serializer is the boundary; the renderer assumes the payload is already a `dict` and asserts the keys. If the payload is malformed, the renderer prints `null` and continues.

## Migration Plan

Deploy order:

1. Land the backend diagnostics module, the `NoopDiagnosticSink` default, and the `X-Debug-Flow` header wiring. The default behavior is unchanged (no header → no `diagnostics` field). No new endpoint, no new dependency, no schema change.
2. Land the CLI `--debug-flow` and `--debug-components` flags and the diagnostic table renderer. The CLI default behavior is unchanged (no flag → no diagnostic tables).
3. Land the tests: serializer unit tests, sink contract tests, event shape tests, CLI flag tests, no-duplicate-call tests, and the existing business regressions.

Rollback strategy:

- Revert the four modified files (`backend/scripts/cli_chat_client.py`, `backend/routers/incoming_messages.py`, `backend/services/incoming_message_service.py`, `backend/llm/intent_classifier.py`, `backend/intents/context/product_selection_context_resolver.py`) and the new `backend/diagnostics/` module plus the new tests. The default response shape is unchanged, so the server is fully backward-compatible: existing clients that do not send `X-Debug-Flow` see the same payload as before.
- No database rollback is needed. The diagnostics module does not write, commit, or roll back.

Cutover:

- None. The CLI prints the new tables from the first run after the change lands, when invoked with `--debug-flow`. Existing invocations without the flag are byte-for-byte identical.

## Open Questions

None. Every decision is pinned by the project.md subphase spec, the existing 3.30 / 3.30.1 / 3.30.2 / 3.32.x constraints, and the mandatory architecture inspection above.
