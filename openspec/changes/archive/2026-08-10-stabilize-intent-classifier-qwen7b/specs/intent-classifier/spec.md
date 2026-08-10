## ADDED Requirements

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
