## ADDED Requirements

### Requirement: Independent embedding configuration
The system SHALL configure local embedding generation independently from text generation, using an embedding endpoint defaulting to `http://localhost:11434/api/embed`, model defaulting to `all-minilm:latest`, timeout defaulting to 30 seconds, batch size defaulting to 32, and the configured expected embedding dimension.

#### Scenario: Default embedding settings
- **WHEN** no embedding-specific environment overrides are present
- **THEN** the embedding client uses the default Ollama embed endpoint, `all-minilm:latest`, a 30-second timeout, a batch size of 32, and the configured default dimension

#### Scenario: Text-generation settings differ
- **WHEN** `LLM_URL` or `LLM_MODEL` is configured with values different from the embedding endpoint or model
- **THEN** the embedding client continues to use only its `EMBEDDING_*` endpoint and model settings

#### Scenario: Invalid bounded setting
- **WHEN** the configured embedding timeout, batch size, or dimension is not a positive integer
- **THEN** settings loading fails with a clear configuration error

### Requirement: Reusable embedding client interface
The system SHALL define an `EmbeddingClientProtocol` with `embed_query(text: str) -> list[float]` and `embed_documents(texts: list[str]) -> list[list[float]]`, and SHALL provide an `OllamaEmbeddingClient` implementation that is independent from persistence and catalog concerns.

#### Scenario: Client supports required operations
- **WHEN** a consumer is typed against `EmbeddingClientProtocol`
- **THEN** an `OllamaEmbeddingClient` can generate either one query vector or an ordered list of document vectors through that interface

#### Scenario: Client is used without persistence
- **WHEN** the client generates vectors
- **THEN** it performs no SQLAlchemy, repository, transaction, product, recognizer, or vector-persistence operation

### Requirement: Single-query embedding generation
The client SHALL reject empty or whitespace-only query text before network activity, send valid query text to the configured Ollama `/api/embed` endpoint using the configured model and timeout, and return exactly one validated vector.

#### Scenario: Valid query embedding
- **WHEN** `embed_query` receives non-empty text and Ollama returns one valid vector of the configured dimension
- **THEN** the client returns that vector

#### Scenario: Empty query
- **WHEN** `embed_query` receives empty or whitespace-only text
- **THEN** the client raises a clear input error without sending an HTTP request

### Requirement: Ordered bounded document batching
The client SHALL accept multiple document texts, validate all inputs before network activity, divide them into requests no larger than the configured batch size, and return all vectors in input order without truncation.

#### Scenario: Empty document collection
- **WHEN** `embed_documents` receives an empty list
- **THEN** it returns an empty list without sending an HTTP request

#### Scenario: Inputs exceed one batch
- **WHEN** the number of valid documents exceeds the configured batch size
- **THEN** the client sends sequential bounded requests and returns one vector for every input in the original order

#### Scenario: Empty document in collection
- **WHEN** a non-empty document collection contains empty or whitespace-only text
- **THEN** the client raises a clear input error identifying the invalid index before sending any HTTP request

### Requirement: Ollama response validation
The client SHALL treat provider responses as untrusted and validate HTTP success, JSON shape, result count, vector presence, finite numeric values, and configured vector dimension before returning any result.

#### Scenario: Malformed response shape
- **WHEN** Ollama returns invalid JSON or a payload without a valid `embeddings` list
- **THEN** the client raises `EmbeddingResponseError`

#### Scenario: Wrong result count
- **WHEN** Ollama returns a number of vectors different from the number of submitted texts
- **THEN** the client raises `EmbeddingResponseError` and returns no partial result

#### Scenario: Invalid vector values
- **WHEN** an embedding is empty or contains a boolean, non-numeric, NaN, or infinite value
- **THEN** the client raises `EmbeddingResponseError`

#### Scenario: Wrong vector dimension
- **WHEN** an embedding length differs from the configured expected dimension
- **THEN** the client raises `EmbeddingDimensionError` with expected and actual dimensions

### Requirement: Domain-specific failure mapping
The client SHALL expose embedding-domain exceptions for timeout, connection, response, and dimension failures and SHALL NOT expose full input payloads, complete vectors, credentials, or unrelated configuration in error messages or normal logs.

#### Scenario: Request timeout
- **WHEN** the HTTP transport times out
- **THEN** the client raises `EmbeddingTimeoutError`

#### Scenario: Connection failure
- **WHEN** the HTTP transport cannot connect to Ollama
- **THEN** the client raises `EmbeddingConnectionError`

#### Scenario: Non-success HTTP response
- **WHEN** Ollama returns a non-success HTTP status
- **THEN** the client raises `EmbeddingResponseError` with safe status context

#### Scenario: Unexpected transport failure
- **WHEN** the transport raises an unexpected request-related failure
- **THEN** the client raises a domain embedding error rather than leaking the raw transport exception

### Requirement: Safe local verification
The system SHALL provide a manual verification entry point that generates a real embedding using configured Ollama settings and reports the model name, vector dimension, and elapsed time without printing the complete vector unless an explicit debug option is enabled.

#### Scenario: Default manual verification output
- **WHEN** the manual verification command succeeds without a debug option
- **THEN** it prints the configured model, returned dimension, and elapsed time but not the complete embedding vector

#### Scenario: Local Ollama smoke test unavailable
- **WHEN** the optional integration smoke test cannot reach local Ollama
- **THEN** the smoke test is skipped without weakening deterministic unit-test coverage
