# Capability: intent-classifier

## Purpose

Provide the modern `IntentClassifier` class in `backend/llm/intent_classifier.py` that validates inbound customer messages, builds the classification prompt locally, delegates the LLM call to the injected `QueryLlm` substitute, validates the returned dict against the existing `IntentClassificationResult` schema, and propagates `QueryLlm` and Pydantic errors unchanged — exposed only as a single class with no HTTP, FastAPI, database, session, pedido, handler, resolver, processor, dispatcher, recognizer, or response-generation logic so the legacy `backend/old_project/` classifier can be replaced without leaking transport, persistence, or intent-orchestration concerns into the LLM layer.
## Requirements
### Requirement: IntentClassifier module location

The system SHALL expose `IntentClassifier` from `backend/llm/intent_classifier.py` and SHALL NOT import from `backend/old_project/`.

#### Scenario: Classifier is importable from the modern LLM package

- **WHEN** `from backend.llm.intent_classifier import IntentClassifier` is executed
- **THEN** the import succeeds and no symbol from `backend.old_project` is loaded

### Requirement: IntentClassifier construction

The system SHALL allow `IntentClassifier()` to construct a default instance and SHALL allow `IntentClassifier(query_llm=...)` to inject a `QueryLlm` substitute whose `request(prompt) -> dict` method is called instead of the default `QueryLlm`.

#### Scenario: Default construction uses QueryLlm

- **WHEN** `IntentClassifier()` is instantiated without arguments
- **THEN** `isinstance(classifier._query_llm, QueryLlm)` is true

#### Scenario: Injected query_llm is used

- **WHEN** `IntentClassifier(query_llm=stub)` is instantiated with a stub object exposing `request(prompt)`
- **THEN** the stub's `request` method is invoked for classification and no real HTTP call is made

### Requirement: Message validation

`IntentClassifier.query(message)` SHALL reject non-string messages with `TypeError` and empty-after-trim messages with `ValueError` before invoking the LLM.

#### Scenario: Non-string message raises TypeError

- **WHEN** `classifier.query(None)` or `classifier.query(123)` is called
- **THEN** a `TypeError` is raised and the LLM is never contacted

#### Scenario: Empty or whitespace-only message raises ValueError

- **WHEN** `classifier.query("")` or `classifier.query("   ")` is called
- **THEN** a `ValueError` is raised and the LLM is never contacted

### Requirement: QueryLlm delegation

The classifier SHALL build a prompt locally and SHALL delegate the LLM call to `QueryLlm.request(prompt)`, returning the parsed dict without mutating classifier state.

#### Scenario: Prompt is built and delegated to QueryLlm

- **WHEN** a valid message is classified
- **THEN** `QueryLlm.request(prompt)` is called exactly once with a non-empty string and the returned dict is forwarded to validation

#### Scenario: Classifier has no mutable prompt state

- **WHEN** two consecutive `query` calls are made
- **THEN** the second call's prompt is independent of the first call's input and no `_message` or `_prompt` attribute is retained between calls

### Requirement: Result validation and order preservation

The classifier SHALL validate the dict returned by `QueryLlm` with `IntentClassificationResult.model_validate`, preserving `intents` order and rejecting unsupported intents, empty `intents`, extra fields, and empty-after-trim messages through the existing schema.

#### Scenario: Single agregar_producto result is accepted

- **WHEN** `QueryLlm` returns `{"intents": [{"intent": "agregar_producto", "mensaje": "una empanada"}], "mensaje": "quiero una empanada"}`
- **THEN** `classifier.query` returns an `IntentClassificationResult` with exactly one `ClassifiedIntent(intent="agregar_producto", mensaje="una empanada")`

#### Scenario: Multiple intents preserve order

- **WHEN** `QueryLlm` returns two intents in the order `agregar_producto` then `set_metodo_de_pago`
- **THEN** the returned `IntentClassificationResult.intents` preserve that order

#### Scenario: Replacement preserves quitar_producto then agregar_producto

- **WHEN** `QueryLlm` returns `quitar_producto` followed by `agregar_producto` for "cambiame la pizza de mozzarella por una napolitana"
- **THEN** the returned `IntentClassificationResult.intents` lists `quitar_producto` first and `agregar_producto` second

#### Scenario: Unsupported intent is rejected

- **WHEN** `QueryLlm` returns `{"intents": [{"intent": "comprar_casa", "mensaje": "x"}], "mensaje": "x"}`
- **THEN** `classifier.query` raises `pydantic.ValidationError` (or a subclass) and does not return a result

#### Scenario: Malformed output is rejected

- **WHEN** `QueryLlm` returns `{}` or `{"intents": [], "mensaje": "x"}` or `{"intents": [{"intent": "agregar_producto", "mensaje": "x"}], "mensaje": "  "}`
- **THEN** `classifier.query` raises `pydantic.ValidationError`

### Requirement: Exception propagation

The classifier SHALL NOT catch `QueryLlmError` (or its subclasses) or `pydantic.ValidationError`; it SHALL NOT print errors or return `None`.

#### Scenario: QueryLlm errors propagate unchanged

- **WHEN** `QueryLlm.request` raises `QueryLlmTimeoutError`, `QueryLlmConnectionError`, `QueryLlmHttpError`, or `QueryLlmResponseError`
- **THEN** `classifier.query` re-raises the original exception without wrapping

#### Scenario: Validation errors propagate unchanged

- **WHEN** the returned dict fails Pydantic validation
- **THEN** `classifier.query` raises the original `pydantic.ValidationError` without wrapping

### Requirement: Logging boundaries

The classifier SHALL use `logging.getLogger(__name__)` to emit `INFO` for start, success, and failure, and `DEBUG` for the validated result, and SHALL NOT configure global logging handlers or duplicate `QueryLlm` prompt/raw-response logs.

#### Scenario: Start and success are logged at INFO

- **WHEN** a successful classification completes
- **THEN** the module logger emits an INFO start event and an INFO success event with the count of intents

#### Scenario: Failure is logged at INFO with error type

- **WHEN** classification fails with a `QueryLlmError` or `ValidationError`
- **THEN** the module logger emits an INFO failure event containing the exception type name

#### Scenario: Validated result is logged at DEBUG only

- **WHEN** a successful classification completes
- **THEN** the module logger emits the validated result only at DEBUG; INFO never contains the result payload

#### Scenario: No global logging handler is configured

- **WHEN** `backend.llm.intent_classifier` is imported
- **THEN** no `logging.basicConfig`, no handler is attached to the root logger by this module, and `logging.getLogger().handlers` is unchanged

### Requirement: Public surface

`backend.llm.intent_classifier` SHALL export only `IntentClassifier` through `__all__` and SHALL NOT introduce HTTP, FastAPI, database, `Session`, `Pedido`, recognizer, resolver, processor, dispatcher, handler, queue promotion, or response-generation logic.

#### Scenario: Module exports are limited

- **WHEN** the module is imported
- **THEN** `__all__` contains only `IntentClassifier`

#### Scenario: Classifier has no side-effect modules

- **WHEN** the module is imported
- **THEN** it does not import `requests`, `fastapi`, `sqlalchemy`, `backend.sessions`, `backend.pedido` (or any pedido module), `backend.intents.handlers`, `backend.intents.recognizers`, `backend.intents.resolvers`, `backend.intents.processor`, `backend.intents.orchestration`, or `backend.intents.context`

### Requirement: IntentClassifier emits diagnostic events through a sink

The `IntentClassifier.query` method SHALL accept an optional `sink: DiagnosticSink` keyword argument that defaults to `NoopDiagnosticSink()`. The classifier SHALL emit a `ClassifierCallStarted` event immediately before calling `QueryLlm.request` and a `ClassifierCallCompleted` event immediately after validating the returned dict with `IntentClassificationResult.model_validate`. The `Started` event SHALL carry the raw message, the normalized message (if produced), the active context type, the active pending intent (if any), the queued intent count, the classifier class, the classifier method, the prompt name (if available), and the model name (if available). The `Completed` event SHALL carry the validated Pydantic result, the intent count, the unknown fragments, the raw response metadata, the parse errors, and the fallback state. The classifier SHALL NOT wrap or re-raise any exception; it SHALL emit a `ClassifierCallCompleted` event with the exception type in parse errors before letting the original exception propagate unchanged. The classifier SHALL NOT call `QueryLlm.request` twice and SHALL NOT reclassify the message.

#### Scenario: Default sink is a no-op
- **WHEN** `IntentClassifier.query` is called without a `sink` argument
- **THEN** the classifier behaves exactly as before: no event is allocated, and the LLM call is invoked exactly once

#### Scenario: Started event captures the raw message and active context
- **WHEN** `IntentClassifier.query(message="quiero dos pizzas", *, sink=stub)` is called and the caller passes `active_context_type="product_selection"` and `active_pending_intent="agregar_producto"` through the surrounding call site
- **THEN** the emitted `ClassifierCallStarted` event carries `raw_message="quiero dos pizzas"`, `active_context_type="product_selection"`, and `active_pending_intent="agregar_producto"`

#### Scenario: Completed event carries the validated result
- **WHEN** `QueryLlm.request` returns a valid classification dict and the classifier validates it
- **THEN** the emitted `ClassifierCallCompleted` event carries the validated `IntentClassificationResult` and the `intent_count` matches the number of classified intents

#### Scenario: Classifier does not reclassify when sink is active
- **WHEN** the same `IntentClassifier.query` is called with a `CollectingDiagnosticSink` and with a `NoopDiagnosticSink`
- **THEN** the `QueryLlm.request` call count is identical in both runs (1 call per query)

#### Scenario: Exception path emits a Completed event with parse errors
- **WHEN** `QueryLlm.request` raises a `QueryLlmTimeoutError` and the classifier propagates it
- **THEN** the classifier emits a `ClassifierCallCompleted` event whose `parse_errors` lists the exception type name ("QueryLlmTimeoutError") before the original exception propagates

### Requirement: IntentClassifier constructor accepts a sink

The `IntentClassifier.__init__` method SHALL accept an optional `sink: DiagnosticSink` keyword argument that defaults to `NoopDiagnosticSink()`. The constructor SHALL store the sink and SHALL NOT change the existing `QueryLlm` injection contract. The classifier's public surface (`IntentClassifier.query` and `IntentClassifier.__init__`) SHALL remain importable and usable as before.

#### Scenario: Default constructor uses NoopDiagnosticSink
- **WHEN** `IntentClassifier()` is instantiated without arguments
- **THEN** `isinstance(classifier._sink, NoopDiagnosticSink)` is true

#### Scenario: Injected sink is used
- **WHEN** `IntentClassifier(query_llm=stub_query_llm, sink=stub_sink)` is instantiated
- **THEN** the classifier stores the injected sink and uses it on every `query` call

### Requirement: Controlled prompt audit uses the production classifier path

The system SHALL provide an explicitly invoked, read-only audit surface that
executes the same `IntentClassifier` and `QueryLlm` prompt construction path as
production against a versioned controlled corpus. For each fixture it SHALL
report the expected and actual ordered intent sequence, source fragments, exact
rendered prompt, parsed response, prompt-template version, and effective
non-secret model settings. It SHALL NOT access a database, send provider
messages, mutate sessions/pedidos, or print credentials, proxy values, tokens,
or account identifiers.

#### Scenario: Payment fixture is evaluated as a single scoped intent

- **WHEN** the controlled audit runs its payment fixture against the effective
  Railway model
- **THEN** the report records the exact prompt and parsed response for that
  fixture
- **AND** the fixture passes only when the result is exactly
  `set_metodo_de_pago`
- **AND** unrelated product, address, delivery, or multiple intents fail the
  fixture

### Requirement: Runtime classification evidence is privacy-safe and correlated

For every classification attempt, the runtime diagnostic boundary SHALL expose
the prompt-template version or fingerprint, effective model identifier,
validated intent names/count, validation/failure category, and a correlation
identifier sufficient to relate the classification attempt to its message turn.
It SHALL NOT log or persist the raw customer message, full prompt, raw model
response, URL, proxy, credential, token, or account identifier.

#### Scenario: Deferred turn can be diagnosed after body scrubbing

- **WHEN** a deferred provider work item finishes and scrubs its transient
  message body
- **THEN** operators can correlate the classified intent names and prompt/model
  metadata with the turn
- **AND** the diagnostic evidence contains no recoverable inbound message or
  prompt content

### Requirement: Single-intent messages cannot gain unrelated actions

The classifier prompt contract SHALL require every returned intent to be
grounded in the customer message and preserve a single, unambiguous payment or
observation request as one corresponding intent. It SHALL retain existing
multi-intent support only when the customer message actually expresses multiple
ordered actions.

#### Scenario: Payment request does not become product or address work

- **WHEN** the classifier receives `Pago en Efectivo (prueba cierre)`
- **THEN** it returns exactly one `set_metodo_de_pago` intent
- **AND** it returns no `agregar_producto`, `set_direccion_entrega`, or other
  unrelated intent

### Requirement: Order observation vs delivery method boundary

The system SHALL document, in the static prompt template of
`IntentClassifier`, a numbered rule that gives explicit priority to
`set_direccion_entrega` for a concrete address, distinguishes
`set_metodo_de_entrega` from `set_observacion_pedido`, and preserves
the existing address contract. A street, number, neighborhood, city,
or other concrete domicile/address SHALL be `set_direccion_entrega`,
not `set_observacion_pedido`. `set_metodo_de_entrega` is reserved for
selecting or changing the modality of reception (delivery / home
delivery, pickup at the shop, dine-in / consumir en salón). Instructions
that do not establish an address—access, route of entry, portón,
timbre, building, security, pets, care, or another operational
indication—SHALL be `set_observacion_pedido`, even when the message
contains the word "entrega". The rule SHALL preserve the existing
substring-literal, `no inventes`, `no reutilices`, and
`una única acción → exactamente un intent` contracts. The rule SHALL
NOT introduce a new intent name, a new field, a new dispatcher path,
a keyword heuristic, a second classifier, a second LLM call, or any
change to the model, transport, settings, enum, schema, dispatcher,
pending context, persistence of `Pedido`, observations persistence,
order mapper, outbox, transactions, product recognition, migrations,
endpoints, workers, Railway configuration, or deploy.

#### Scenario: Access / route / pets messages route to set_observacion_pedido

- **WHEN** the static prompt is rendered for the customer message
  `La entrega es por el portón lateral` or `Cuidado con el perro`
- **THEN** the rendered prompt documents the new numbered rule and
  the example for that customer message routes it to
  `set_observacion_pedido`

#### Scenario: Modality selection routes to set_metodo_de_entrega

- **WHEN** the static prompt is rendered for the customer message
  `Quiero envío a domicilio` or `Lo retiro por el local`
- **THEN** the rendered prompt documents the new numbered rule and
  the example for that customer message routes it to
  `set_metodo_de_entrega`

#### Scenario: Concrete address retains delivery-address priority

- **WHEN** the static prompt is rendered for `Me lo envias a Tilcara 2020`
- **THEN** it documents that the message is `set_direccion_entrega`
- **AND** it does not reinterpret the address as `set_observacion_pedido`

### Requirement: Calibration corpus pins delivery boundary and address fixtures

The controlled corpus `CONTROLLED_INTENT_CORPUS` SHALL include the four
boundary fixtures and one concrete-address regression that pin the
contract. Each fixture SHALL carry
the exact customer message as its `message`, SHALL pin exactly one
expected intent (`SET_OBSERVACION_PEDIDO` for the two access / care
fixtures, `SET_METODO_DE_ENTREGA` for the two modality fixtures), and
SHALL keep the existing substring-literal contract: the rendered
prompt must contain the fixture message verbatim. The fixtures SHALL
follow the existing regression fixture naming convention
(`F-REG-<slug>`). The corpus SHALL remain safe to render in the
prompt and safe to serialize in the audit report; no fixture SHALL
introduce real customer PII or secrets.

#### Scenario: Two access / care fixtures pin set_observacion_pedido

- **WHEN** the controlled audit runs the
  `La entrega es por el portón lateral` and `Cuidado con el perro`
  fixtures
- **THEN** each fixture pins exactly one intent equal to
  `set_observacion_pedido`

#### Scenario: Two modality fixtures pin set_metodo_de_entrega

- **WHEN** the controlled audit runs the
  `Quiero envío a domicilio` and `Lo retiro por el local` fixtures
- **THEN** each fixture pins exactly one intent equal to
  `set_metodo_de_entrega`

#### Scenario: Boundary fixtures are substrings of their rendered prompts

- **WHEN** each of the four boundary fixtures is rendered through
  `IntentClassifier._build_prompt`
- **THEN** the customer `message` is present verbatim in the rendered
  prompt

#### Scenario: Concrete-address fixture retains set_direccion_entrega

- **WHEN** the controlled audit runs `Me lo envias a Tilcara 2020`
- **THEN** it pins exactly one `set_direccion_entrega` intent
