## ADDED Requirements

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
