## Why

Subphase 4.4 needs a reusable, provider-focused client that can generate embeddings through the existing local Ollama server without coupling generation to persistence or the Qwen text-generation configuration. This establishes the validated embedding boundary required by later semantic-search phases.

## What Changes

- Add embedding-specific endpoint, model, timeout, batch-size, and dimension configuration independent from `LLM_*` settings.
- Define an `EmbeddingClientProtocol` for single-query and multi-document embedding generation.
- Add an `OllamaEmbeddingClient` that calls `/api/embed`, chunks document requests without truncation, and preserves input order.
- Validate input text, HTTP outcomes, Ollama response shape and count, non-empty vectors, numeric values, and configured dimensions.
- Map timeout, connection, HTTP/response, and dimension failures to domain-specific embedding exceptions without exposing full payloads.
- Add isolated unit/configuration tests, an optional real-Ollama integration smoke test, and a manual verification script that reports metadata without printing vectors by default.
- Keep semantic document construction, persistence, seeding, similarity search, recognizer changes, and later subphases out of scope.

## Capabilities

### New Capabilities
- `ollama-embedding-client`: Generate validated single and batched embeddings through local Ollama with independent configuration, deterministic ordering, bounded batches, and domain-specific failures.

### Modified Capabilities

None.

## Impact

- Affects backend configuration, a new embedding client abstraction/implementation, backend scripts, and focused tests.
- Uses the existing `requests` dependency and local Ollama `/api/embed` API; no new SDK or framework is introduced.
- Does not change database models, repositories, transaction ownership, persistence behavior, or public application endpoints.
