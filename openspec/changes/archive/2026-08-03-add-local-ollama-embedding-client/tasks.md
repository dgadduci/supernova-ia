## 1. Embedding Configuration

- [x] 1.1 Extend frozen settings with independent embedding URL, model, timeout-seconds, and batch-size defaults while retaining configured embedding dimension
- [x] 1.2 Add settings tests for defaults, environment overrides, independence from `LLM_*`, immutability, and invalid non-positive numeric values

## 2. Client Contract and Errors

- [x] 2.1 Define `EmbeddingClientProtocol` with single-query and ordered multi-document methods
- [x] 2.2 Define the embedding client base error plus connection, timeout, response, and dimension exceptions with safe actionable messages

## 3. Ollama Client Implementation

- [x] 3.1 Implement `OllamaEmbeddingClient` with injectable HTTP transport, configured `/api/embed` payloads, timeout enforcement, and safe lifecycle logging
- [x] 3.2 Implement upfront query/document input validation, including indexed empty-document errors and no-request behavior for empty document lists
- [x] 3.3 Implement sequential batch-size chunking that preserves input order, returns every result, and exposes no partial result on failure
- [x] 3.4 Validate HTTP status, JSON shape, result count, non-empty finite numeric vectors, and configured dimensions before returning results
- [x] 3.5 Map timeout, connection, HTTP, malformed response, dimension, and unexpected transport failures to the domain exception hierarchy without exposing texts or vectors

## 4. Automated Verification

- [x] 4.1 Add deterministic client unit tests for single inputs, request payload/configuration, batch chunking, complete ordered output, empty inputs, and protocol compatibility
- [x] 4.2 Add response-validation tests for malformed JSON/shape, wrong counts, empty or invalid values, and wrong dimensions
- [x] 4.3 Add exception-mapping and safe-message tests for timeout, connection, non-success HTTP, and unexpected request failures
- [x] 4.4 Add an opt-in real-Ollama smoke test that skips when unavailable and confirms the configured model returns the expected dimension

## 5. Manual Verification and Quality Gates

- [x] 5.1 Add `backend.scripts.check_embedding_client` to print model, dimension, and elapsed time while hiding the complete vector unless explicit debug output is requested
- [x] 5.2 Run focused settings/client tests and the real local Ollama smoke test when the configured server is available
- [x] 5.3 Run `PYTHONPATH=. venv/bin/python -m compileall backend` and the repository lint/typecheck commands if configured
- [x] 5.4 Run strict OpenSpec validation and leave the completed change active without syncing or archiving it
