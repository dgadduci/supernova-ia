## Context

The backend can persist pgvector embeddings and already configures the expected model and dimension, but it has no provider abstraction or code that asks Ollama to generate vectors. The existing `QueryLlm` client establishes useful local conventions: frozen environment-backed settings, `requests`, injectable transports, explicit validation, domain exceptions, and safe lifecycle logging. The new client must remain independent of catalog models, SQLAlchemy, repositories, and transaction ownership while providing the validated vectors needed by later phases.

## Goals / Non-Goals

**Goals:**
- Provide a small typed protocol for embedding one query or an ordered collection of documents.
- Configure Ollama embeddings independently with `EMBEDDING_URL`, `EMBEDDING_MODEL`, `EMBEDDING_TIMEOUT_SECONDS`, `EMBEDDING_BATCH_SIZE`, and the existing expected dimension.
- Bound request size by chunking documents, preserve order, and never silently truncate inputs.
- Validate inputs and every response before returning vectors.
- Expose stable domain exceptions and safe diagnostics suitable for callers and tests.
- Provide deterministic unit tests plus optional manual and integration checks against local Ollama.

**Non-Goals:**
- Construct semantic product documents or choose which records to embed.
- Persist, seed, backfill, index, or search vectors.
- Change recognizers, database models, repositories, transactions, or public endpoints.
- Introduce LangChain, LangGraph, an Ollama SDK, retries, or Subphase 4.5 behavior.

## Decisions

1. **Use a provider-neutral protocol with a concrete Ollama implementation.** `EmbeddingClientProtocol` exposes `embed_query(text) -> list[float]` and `embed_documents(texts) -> list[list[float]]`; `OllamaEmbeddingClient` implements it. This keeps later consumers independent from Ollama without creating a broader provider framework. Directly coupling consumers to the concrete client was rejected because the roadmap explicitly requires a reusable boundary; a class hierarchy was rejected because structural typing is sufficient.

2. **Keep embedding configuration separate from generation configuration.** Add `EMBEDDING_URL` defaulting to `http://localhost:11434/api/embed`, `EMBEDDING_MODEL` defaulting to `all-minilm:latest`, `EMBEDDING_TIMEOUT_SECONDS` defaulting to `30`, and `EMBEDDING_BATCH_SIZE` defaulting to `32`; retain `EMBEDDING_DIMENSION` as the response contract. Reusing `LLM_URL`, `LLM_MODEL`, or generation options was rejected because `/api/generate` and `/api/embed` have different endpoints and payloads.

3. **Use direct HTTP with an injectable transport.** Follow `QueryLlm` by using the existing `requests` dependency, a configured timeout, and an optional transport callable. An Ollama SDK was rejected because it adds a dependency without improving this small endpoint integration. Injection allows complete unit coverage without requiring a running server.

4. **Send query input as one item and documents as bounded chunks.** `embed_query` validates one string and delegates to the same request/validation path. `embed_documents([])` returns `[]`; otherwise it validates the complete input before network activity, slices it by configured batch size, concatenates responses in request and item order, and verifies no item is lost. Sending all documents at once was rejected because it ignores the configured bound; parallel batching was rejected because sequential batching is simpler and naturally preserves order.

5. **Validate at the client boundary.** Reject empty or whitespace-only query text, and identify the index of every invalid document input before requests begin. For each Ollama response, require a successful HTTP status, a JSON object with an `embeddings` list, exactly one vector per submitted text, non-empty finite numeric vectors, and exactly the configured dimension. Provider output is untrusted even when Ollama is local; returning partial or malformed vectors was rejected because it would move failures into persistence or retrieval code.

6. **Use a focused exception hierarchy.** A common embedding client error is specialized into connection, timeout, response, and dimension errors. HTTP failures, invalid JSON, malformed payloads, wrong counts, and invalid vector values map to response errors; dimensional mismatch maps separately. Messages include actionable metadata such as status, batch location, expected/actual count, or expected/actual dimension, but not full text payloads or vectors. Exposing raw `requests` errors was rejected because it leaks transport details to callers.

7. **Separate deterministic tests from live verification.** Unit tests use fake responses and injected transports to cover payloads, chunking, ordering, validation, and error mapping. A local integration smoke test is skipped when Ollama is unavailable. A manual module prints model, dimension, and elapsed time, with complete vectors hidden unless an explicit debug option is supplied.

## Risks / Trade-offs

- **[Configured dimension differs from the installed model]** → Fail fast with `EmbeddingDimensionError` and include expected and actual dimensions so configuration can be corrected before persistence.
- **[A later batch fails after earlier requests succeeded]** → Raise the mapped error and return no partial result; callers can retry the full operation safely because this client has no side effects.
- **[Sequential batching is slower for large inputs]** → Accept predictable ordering and simpler failure semantics for this phase; concurrency can be proposed later with explicit limits.
- **[Local Ollama is absent during automated tests]** → Keep all required behavior covered by injected unit tests and mark only the real-server smoke test as conditional.
- **[Exception messages expose input data]** → Log/request-report only model, counts, batch positions, status, dimension, and elapsed time; never include full texts or vectors.

## Migration Plan

1. Add and validate embedding-specific settings with backward-compatible defaults.
2. Add the protocol, exceptions, and Ollama implementation without wiring it into existing services.
3. Add deterministic tests and the opt-in smoke-test/manual verification path.
4. Deploy with no data migration; existing embedding persistence remains unchanged.
5. Roll back by removing the new modules and settings because no existing runtime path or stored data depends on them.

## Open Questions

None for Subphase 4.4. Consumer wiring and persistence orchestration remain deferred to later explicitly scoped changes.
