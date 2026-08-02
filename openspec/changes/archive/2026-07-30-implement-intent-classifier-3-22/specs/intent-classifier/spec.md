## ADDED Requirements

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