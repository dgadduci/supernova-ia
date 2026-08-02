# Capability: cli-classifier-resolver-flow-debug

## Purpose

Provide an opt-in diagnostic mode for the interactive CLI chat client (`backend.scripts.cli_chat_client`) that prints structured classifier and resolver data-flow tables for every real call during a conversation, so the developer can trace the data flow from the CLI without touching the server. The diagnostic mode is disabled by default; it is activated only when the operator passes the `--debug-flow` flag. It exposes zero observable behavior, zero new HTTP calls, and zero duplicate classifier or resolver invocations when disabled, and it produces a single in-memory `diagnostics` array that the CLI renders as tables when enabled.

## ADDED Requirements

### Requirement: Diagnostics package exists

The system SHALL expose a `backend.diagnostics` module containing: a `DiagnosticSink` protocol with five methods (`on_classifier_started`, `on_classifier_completed`, `on_resolver_started`, `on_resolver_completed`, `on_pending_state_snapshot`); a `NoopDiagnosticSink` default implementation whose methods are empty; a `CollectingDiagnosticSink` that records events in a list, allocates sequential `CLS-NNN` / `RES-NNN` call IDs per request, and exposes `events()` and `clear()`; five event dataclasses (`ClassifierCallStarted`, `ClassifierCallCompleted`, `ResolverCallStarted`, `ResolverCallCompleted`, `PendingStateSnapshot`) each with a `to_dict()` method; a `serialize(value, *, redact=True, _seen=None)` function that supports dataclasses, Pydantic v2 models, enums, SQLAlchemy ORM instances whose class has a `__table__` attribute, dicts, lists, tuples, sets, frozensets, and primitives; and a `redact(value)` function that walks the value and replaces values whose key (case-insensitive) is in `{"password", "token", "api_key", "authorization", "secret", "database_url"}` with the string `<redacted>`.

#### Scenario: Modules are importable

- **WHEN** a test executes `from backend.diagnostics import DiagnosticSink, NoopDiagnosticSink, CollectingDiagnosticSink, serialize, redact`
- **THEN** every import succeeds and every binding is the expected callable / class

#### Scenario: NoopDiagnosticSink does not retain state

- **WHEN** a test creates a `NoopDiagnosticSink` and invokes every method
- **THEN** the sink has no readable attribute beyond the methods and does not raise

#### Scenario: CollectingDiagnosticSink assigns sequential call IDs

- **WHEN** a test creates a `CollectingDiagnosticSink` and emits `on_classifier_started`, `on_classifier_completed`, `on_resolver_started`, `on_resolver_completed` in order
- **THEN** the recorded events carry `CLS-001`, `CLS-001`, `RES-001`, `RES-001` call IDs in the right order

#### Scenario: Serializer handles primitives

- **WHEN** `serialize` is called with `None`, `True`, `42`, `3.14`, and `"hola"`
- **THEN** the result is `None`, `True`, `42`, `3.14`, and `"hola"` verbatim

#### Scenario: Serializer sorts dict keys

- **WHEN** `serialize` is called with a dict containing keys `"b"`, `"a"`, `"c"`
- **THEN** the resulting dict's keys are iterated in alphabetical order

#### Scenario: Serializer handles dataclasses and Pydantic models

- **WHEN** `serialize` is called with a dataclass instance and a Pydantic v2 model instance
- **THEN** the result is a dict whose keys match the declared fields, with nested values recursively serialized

#### Scenario: Serializer handles enums

- **WHEN** `serialize` is called with an `Enum` member
- **THEN** the result is the enum's `value`

#### Scenario: Serializer handles SQLAlchemy ORM instances

- **WHEN** `serialize` is called with a SQLAlchemy ORM instance whose class has a `__table__` attribute
- **THEN** the result is a dict built from the table's columns (no relationship loading, no lazy attribute access)

#### Scenario: Serializer falls back to class name for unsupported types

- **WHEN** `serialize` is called with a custom class without a `__table__` attribute and without a `model_dump` method
- **THEN** the result is the string `"<ClassName>"` where `ClassName` is `type(value).__name__`

#### Scenario: Serializer breaks recursion loops

- **WHEN** `serialize` is called with a value that contains a cycle
- **THEN** the cycle is replaced with `"<ClassName>"` and the serializer does not raise `RecursionError`

#### Scenario: Redactor replaces secret fields

- **WHEN** `redact` is called with a dict containing keys `password`, `token`, `api_key`, `authorization`, `secret`, and `database_url` (mixed case)
- **THEN** every value associated with a redacted key is the string `<redacted>` and every other value is preserved

### Requirement: CLI accepts --debug-flow flag

The CLI SHALL accept an `--debug-flow` flag (`action="store_true"`) on the command line. When the flag is absent, the CLI SHALL send no `X-Debug-Flow` header on any HTTP request, SHALL print no diagnostic tables, SHALL make no extra HTTP calls, and SHALL make no extra logging calls. When the flag is present, the CLI SHALL send `X-Debug-Flow: 1` on every `POST /comercios/{comercio_id}/clientes/{cliente_id}/incoming-messages` request and SHALL render the diagnostic tables.

#### Scenario: Flag absent keeps default behavior

- **WHEN** the operator runs `python -m backend.scripts.cli_chat_client` without `--debug-flow`
- **THEN** the script sends no `X-Debug-Flow` header, prints no `CLASSIFIER INPUT` / `CLASSIFIER OUTPUT` / `RESOLVER INPUT` / `RESOLVER OUTPUT` tables, and the existing customer-facing and order-table behavior is unchanged

#### Scenario: Flag present activates debug mode

- **WHEN** the operator runs `python -m backend.scripts.cli_chat_client --debug-flow`
- **THEN** the script sends `X-Debug-Flow: 1` on every `POST /comercios/.../incoming-messages` request and renders the diagnostic tables included in the response payload

### Requirement: CLI accepts --debug-components filter

The CLI SHALL accept an optional `--debug-components` argument that is a comma-separated list of `classifier`, `resolver`, and `pending`. When `--debug-flow` is enabled and `--debug-components` is empty, the CLI SHALL render all three categories. When `--debug-components` lists a subset, the CLI SHALL render only the categories whose name appears in the list. Unknown values SHALL cause the CLI to print a clear error message and exit with status `2`.

#### Scenario: Missing argument enables all categories

- **WHEN** the operator runs `python -m backend.scripts.cli_chat_client --debug-flow` without `--debug-components`
- **THEN** the CLI renders classifier, resolver, and pending-state tables

#### Scenario: Single category limits output

- **WHEN** the operator runs `python -m backend.scripts.cli_chat_client --debug-flow --debug-components classifier`
- **THEN** the CLI renders only `CLASSIFIER INPUT` and `CLASSIFIER OUTPUT` tables and never renders `RESOLVER INPUT` / `RESOLVER OUTPUT` / `PENDING STATE` tables

#### Scenario: Unknown value exits with error

- **WHEN** the operator runs `python -m backend.scripts.cli_chat_client --debug-flow --debug-components foo`
- **THEN** the CLI prints a clear error message that mentions `foo` and exits with status `2`

### Requirement: CLI renders CLASSIFIER INPUT and CLASSIFIER OUTPUT tables

When `--debug-flow` is enabled and the response payload contains a `diagnostics` list with a `ClassifierCallStarted` and a `ClassifierCallCompleted` event, the CLI SHALL render a `CLASSIFIER INPUT` table followed by a `CLASSIFIER OUTPUT` table. The `CLASSIFIER INPUT` table SHALL include the fields `call_id`, `turn_id`, `raw_message`, `active_context_type`, `has_active_pending_intent`, `active_pending_intent`, `queued_intent_count`, `classifier_class`, `classifier_method`, `prompt_name`, and `model`. The `CLASSIFIER OUTPUT` table SHALL include one row per classified intent with the columns `Index`, `Intent`, `Source text`, `Quantity`, `Confidence`, `Status`, `Resolved data`, `Requirements`, `Candidate IDs`, and `Raw payload`. The `call_id` (`CLS-NNN`) and the `turn_id` SHALL appear in the titles.

#### Scenario: Input table contains all required fields

- **WHEN** the response contains a `ClassifierCallStarted` event with the required fields
- **THEN** the rendered `CLASSIFIER INPUT` table contains every field, with `<not available>` for absent values and the literal value for present values

#### Scenario: Output table renders one row per intent

- **WHEN** the response contains a `ClassifierCallCompleted` event whose payload lists two intents
- **THEN** the rendered `CLASSIFIER OUTPUT` table contains exactly two rows in classifier order, with all required columns

#### Scenario: Multiple classified intents preserve source order

- **WHEN** the classifier returns `agregar_producto` followed by `set_metodo_de_pago`
- **THEN** the rendered table lists `agregar_producto` first and `set_metodo_de_pago` second

### Requirement: CLI renders RESOLVER INPUT and RESOLVER OUTPUT tables

When `--debug-flow` is enabled and the response payload contains a `ResolverCallStarted` and a `ResolverCallCompleted` event, the CLI SHALL render a `RESOLVER INPUT` table followed by a `RESOLVER OUTPUT` table. The `RESOLVER INPUT` table SHALL include the fields `call_id`, `resolver_class`, `resolver_method`, `resolver_purpose`, `session_id`, `context_type`, `incoming_text`, `normalized_text`, `intent`, `source_text`, `quantity`, `status_before`, `requirements_before`, `resolved_data_before`, `candidate_ids_before`, `candidate_count`, and `queued_intent_count`. The `RESOLVER OUTPUT` table SHALL include `call_id`, `result_type`, `status_after`, `selected_candidate_id`, `selected_product`, `quantity_after`, `requirements_after`, `resolved_data_after`, `candidate_ids_after`, `candidate_count_after`, `rejection_reason`, `clarification_message`, and `raw_result`. The `call_id` (`RES-NNN`) and the `turn_id` SHALL appear in the titles.

#### Scenario: Input table shows resolver input

- **WHEN** the response contains a `ResolverCallStarted` event with the required fields
- **THEN** the rendered `RESOLVER INPUT` table contains every field, with `<not available>` for absent values

#### Scenario: Output table shows resolver output

- **WHEN** the response contains a `ResolverCallCompleted` event with the required fields
- **THEN** the rendered `RESOLVER OUTPUT` table contains every field, with `<not available>` for absent values

#### Scenario: Input and output share the same call_id

- **WHEN** the response contains a `ResolverCallStarted` and a `ResolverCallCompleted` event for the same resolver call
- **THEN** both tables render with the same `RES-NNN` call_id in the title

### Requirement: CLI renders RESOLVER CANDIDATES table

When the response payload contains a `ResolverCallStarted` event whose `candidate_catalog` is a non-empty list of dicts, the CLI SHALL render a `RESOLVER CANDIDATES` table with one row per candidate and the columns `Index`, `producto_presentacion_id`, `producto_id`, `producto_nombre`, `presentacion_id`, `presentacion_codigo`, `presentacion_descripcion`, `categoria_id`, `categoria_nombre`, `activo`, and `disponible`. Missing fields SHALL render as `<not available>`.

#### Scenario: Three candidates render three rows

- **WHEN** the response contains a `ResolverCallStarted` event with three candidates in `candidate_catalog`
- **THEN** the rendered `RESOLVER CANDIDATES` table contains exactly three rows in the order the candidates were passed to the resolver

#### Scenario: Empty candidate list renders no table

- **WHEN** the response contains a `ResolverCallStarted` event with an empty `candidate_catalog`
- **THEN** the CLI renders no `RESOLVER CANDIDATES` table

### Requirement: CLI renders RESOLVER MATCHES table

When the response payload contains a `ResolverCallCompleted` event whose `matches` is a non-empty list of dicts, the CLI SHALL render a `RESOLVER MATCHES` table with one row per match and the columns `Index`, `Candidate ID`, `Candidate`, `Score`, `Match type`, `Matched text`, and `Accepted`. Missing fields SHALL render as `<not available>`.

#### Scenario: Three matches render three rows

- **WHEN** the response contains a `ResolverCallCompleted` event with three matches
- **THEN** the rendered `RESOLVER MATCHES` table contains exactly three rows

### Requirement: CLI renders PENDING STATE and PENDING QUEUE tables

When the response payload contains a `PendingStateSnapshot` event, the CLI SHALL render a `PENDING STATE` table with the fields `active_intent`, `active_status`, `active_source_text`, `active_quantity`, `active_candidate_ids`, `queue_length`, `queue_intents`, `queue_sources`, and `context_type`. When the `queue_intents` list is non-empty, the CLI SHALL also render a `PENDING QUEUE` table with one row per queued intent and the columns `Position`, `Intent`, `Status`, `Source text`, `Quantity`, `Candidate IDs`, `Requirements`, and `Resolved data`.

#### Scenario: Active pending context renders state table

- **WHEN** the response contains a `PendingStateSnapshot` event with `active_intent="agregar_producto"` and `queue_length=1`
- **THEN** the CLI renders a `PENDING STATE` table with the active intent fields and a `PENDING QUEUE` table with one row

#### Scenario: Empty queue renders no PENDING QUEUE table

- **WHEN** the response contains a `PendingStateSnapshot` event with `queue_length=0`
- **THEN** the CLI renders the `PENDING STATE` table but no `PENDING QUEUE` table

### Requirement: CLI preserves customer-facing output ordering

When `--debug-flow` is enabled, the CLI SHALL print the customer-facing `<- message=...` / `<- raw=...` lines first, then the diagnostic tables (in chronological order by `(sequence, phase)`), then the `Pedido actual:` table when the order mutation triggers a detail retrieval. The existing customer response format SHALL NOT change.

#### Scenario: Order of output is customer-facing then diagnostics then order table

- **WHEN** the API returns an executed `agregar_producto` response with a `diagnostics` list and the detail endpoint returns a non-empty order
- **THEN** the CLI prints the customer response first, then the diagnostic tables, then the `Pedido actual:` table

#### Scenario: Customer response format is unchanged

- **WHEN** the API returns a response with both customer-facing text and a `diagnostics` list
- **THEN** the customer-facing lines are printed with the same `<- message=...` / `<- raw=...` format as without `--debug-flow`

### Requirement: CLI redacts secrets in rendered tables

The CLI SHALL walk the rendered payload and replace any value whose key (case-insensitive) is one of `password`, `token`, `api_key`, `authorization`, `secret`, `database_url`, `DATABASE_URL`, `Authorization`, `X-API-Key`, or `X-API-KEY` with the string `<redacted>` before printing.

#### Scenario: Password field is redacted

- **WHEN** the response contains a `diagnostics` event with a `password` field
- **THEN** the rendered table contains `<redacted>` and never contains the literal password value

#### Scenario: Multiple secret fields are redacted

- **WHEN** the response contains a `diagnostics` event with `token`, `api_key`, and `database_url` fields
- **THEN** the rendered table contains `<redacted>` for each of those fields and the rest of the payload is preserved

#### Scenario: Non-secret fields are not redacted

- **WHEN** the response contains a `diagnostics` event with a `prompt_name` field
- **THEN** the rendered table contains the literal `prompt_name` value

### Requirement: Diagnostics are silent when disabled

When the request does not carry the `X-Debug-Flow` header, the FastAPI server SHALL use a `NoopDiagnosticSink` and SHALL NOT emit any event. The response payload SHALL NOT contain a `diagnostics` field. The number of classifier and resolver calls SHALL be identical to the number of calls in the debug-enabled path.

#### Scenario: Default response shape is unchanged

- **WHEN** the client sends a request without `X-Debug-Flow`
- **THEN** the response payload's keys are exactly the keys produced before this subphase and the `diagnostics` key is absent

#### Scenario: Default call count equals debug-enabled call count

- **WHEN** two identical requests are sent, one with `X-Debug-Flow: 1` and one without
- **THEN** the total number of `IntentClassifier.query` calls and the total number of resolver calls are identical

#### Scenario: NoopDiagnosticSink does not allocate events

- **WHEN** a request without `X-Debug-Flow` runs through the orchestrator
- **THEN** no list or dict is allocated by the sink machinery and no event is appended to a list

### Requirement: Diagnostics include the exact input and output of every real call

Every `ClassifierCallStarted` and `ClassifierCallCompleted` event SHALL carry the exact value passed to and returned from the real `IntentClassifier.query` call — no reclassification, no rerun, no recomputation. Every `ResolverCallStarted` and `ResolverCallCompleted` event SHALL carry the exact input and output of the real resolver call.

#### Scenario: Classifier call count matches CLS-N count

- **WHEN** a request with `X-Debug-Flow: 1` is processed
- **THEN** the number of `ClassifierCallStarted` events equals the number of `IntentClassifier.query` invocations

#### Scenario: Resolver call count matches RES-N count

- **WHEN** a request with `X-Debug-Flow: 1` is processed
- **THEN** the number of `ResolverCallStarted` events equals the number of resolver invocations

#### Scenario: No duplicate classifier call

- **WHEN** the same request is processed with and without `X-Debug-Flow`
- **THEN** the `QueryLlm.request` count is identical in both runs (no debug-induced reclassification)

#### Scenario: No duplicate resolver call

- **WHEN** the same request is processed with and without `X-Debug-Flow`
- **THEN** the total number of resolver calls is identical in both runs (no debug-induced re-resolution)

### Requirement: Server response includes the diagnostics array only when requested

The FastAPI incoming-messages router SHALL attach a `diagnostics: list[dict]` field to the response payload only when the request carries the `X-Debug-Flow` header. The array SHALL be sorted by `(sequence, phase)` tuple before serialization. The default response shape (no header) is unchanged.

#### Scenario: Header absent omits diagnostics

- **WHEN** the client sends a request without `X-Debug-Flow`
- **THEN** the response payload does not contain the `diagnostics` key

#### Scenario: Header present includes diagnostics

- **WHEN** the client sends a request with `X-Debug-Flow: 1`
- **THEN** the response payload contains a `diagnostics` key whose value is a list of event dicts

#### Scenario: Diagnostics array is sorted by sequence

- **WHEN** the orchestrator emits a `PendingStateSnapshot` event at sequence 1, a `ClassifierCallStarted` at sequence 2, and a `ResolverCallStarted` at sequence 3
- **THEN** the `diagnostics` array lists the events in the order (2, 1, 3) only if the `(sequence, phase)` ordering places them in that group ordering; otherwise the order matches the emitted arrival order

### Requirement: Redaction is applied to the response payload on the server

The FastAPI incoming-messages router SHALL walk the response payload (including the `diagnostics` field) and replace any value whose key (case-insensitive) is in the redacted-key set with the literal string `<redacted>` before sending the response.

#### Scenario: Server-side redaction removes database URL

- **WHEN** a `diagnostics` event contains a `database_url` field
- **THEN** the response payload sent to the client contains `<redacted>` instead of the literal URL

#### Scenario: Server-side redaction preserves non-secret fields

- **WHEN** a `diagnostics` event contains a `prompt_name` field alongside a `password` field
- **THEN** the response payload contains the literal `prompt_name` value and `<redacted>` for the `password` value

### Requirement: Diagnostic mode does not change business behavior

When `--debug-flow` is enabled, the customer-facing responses, the order mutation triggers, the queue lifecycle, the queue promotion order, the transaction ownership, and the persisted state SHALL be identical to the no-flag run.

#### Scenario: Customer-facing responses are unchanged

- **WHEN** the operator runs the same conversation with and without `--debug-flow`
- **THEN** the printed `<- message=...` / `<- raw=...` lines are byte-for-byte identical

#### Scenario: Pedido table is unchanged

- **WHEN** the operator runs the same conversation with and without `--debug-flow`
- **THEN** the `Pedido actual:` table content is byte-for-byte identical

#### Scenario: Queue lifecycle is unchanged

- **WHEN** the operator runs the same conversation with and without `--debug-flow`
- **THEN** the `PENDING STATE` snapshots printed by the CLI show the same active intent, queue length, and context type transitions as the no-flag run would produce (verified by reading the persisted state after the conversation)

### Requirement: Diagnostic mode preserves the existing CLI import boundary

The CLI SHALL NOT import `fastapi`, `sqlalchemy`, `uvicorn`, `requests`, `httpx`, `aiohttp`, `websockets`, or any `backend.*` module. The new diagnostic helpers (`_format_kv_table`, `_format_intent_table`, `_format_pending_state_snapshot`, `_format_pending_queue_table`, `_extract_diagnostics`, `_render_diagnostics`, `_redact_payload`, `_parse_debug_components`) SHALL use only the standard library (`urllib.request`, `json`, `argparse`, `sys`, `os`, `dataclasses`) and SHALL NOT introduce a third-party table library.

#### Scenario: Static import boundary still holds

- **WHEN** the module `backend.scripts.cli_chat_client` is loaded
- **THEN** the imports of the module and the source code contain none of `fastapi`, `sqlalchemy`, `uvicorn`, `requests`, `httpx`, `aiohttp`, `websockets`, and none of `backend.routers`, `backend.services`, `backend.repositories`, `backend.intents`, `backend.llm`, `backend.models`, `backend.alembic`, `backend.dependencies`

### Requirement: Manual acceptance covers the multi-intent flow

The implementation SHALL be exercised manually with the CLI flag enabled against a real `supernova_test` database. The exact acceptance scenario is: type `comercio_id=1`, `cliente_id=8`, then `quiero una empanada de carne y una pizza`, then `picante`, then resolve the Pizza candidate, then `exit`. The CLI SHALL display, in chronological order: `CLASSIFIER INPUT`, `CLASSIFIER OUTPUT`, `PENDING STATE`, `RESOLVER INPUT` for Carne, `RESOLVER CANDIDATES`, `RESOLVER OUTPUT`, `PENDING STATE`, the normal clarification response, then on `picante` the `RESOLVER INPUT` with the exact text `picante`, the candidate IDs, the resolver output, and the active/queue state after processing. The operator SHALL be able to identify from the tables: whether both products came from the classifier, which quantities were assigned, which intent became active, which intent entered the queue, what exact candidates reached the resolver, how `picante` was normalized, what the resolver returned, whether the status changed, and whether queue promotion occurred.

#### Scenario: Multi-intent flow renders all expected tables

- **WHEN** the operator runs the manual acceptance scenario above
- **THEN** the CLI prints the classifier input and output tables for the initial message, the first resolver input and candidates and output tables for Carne, the pending-state snapshot showing the queue, the second resolver input and output tables for `picante`, and the final pending-state snapshot showing the queue after the promotion
