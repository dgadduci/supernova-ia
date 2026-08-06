# Delta Spec: product-recognition-shadow-mode (Subphase 4.10.1)

## MODIFIED Requirements

### Requirement: Shadow comparison dataclass

The system SHALL expose a frozen
`ProductRecognitionShadowComparison` dataclass in
`backend/services/product_recognition_shadow_comparison.py` with
exactly twelve fields:
`fuzzy_best_id: int | None`,
`vector_best_id: int | None`,
`fuzzy_candidate_ids: tuple[int, ...]`,
`vector_candidate_ids: tuple[int, ...]`,
`fuzzy_candidate_scores: tuple[float, ...]` (normalized fuzzy
scores in `[0.0, 1.0]`, aligned with `fuzzy_candidate_ids` in
encounter order),
`vector_candidate_scores: tuple[float, ...]` (cosine similarity
scores in `[0.0, 1.0]`, aligned with `vector_candidate_ids` in
match order),
`agreement: str`,
`fuzzy_latency_ms: float`,
`embedding_latency_ms: float`,
`vector_latency_ms: float`,
`vector_available: bool`,
`failure_category: str | None` (sanitized shadow-pipeline failure
category: `"embedding_failure"`, `"vector_failure"`, or `None`
when the embedding and vector pipelines both succeeded). The
dataclass SHALL inherit only from `dataclass(frozen=True)`; it
SHALL NOT be a Pydantic model, a SQLAlchemy ORM model, or a class
with side effects in `__post_init__`. The dataclass SHALL NOT be
mutated through `object.__setattr__` after construction; the
`failure_category` SHALL be supplied through the constructor and
SHALL NOT be attached as a hidden attribute. The dataclass SHALL
NOT expose the input text, the customer message, the raw vectors,
the prompt, the source documents, the correlation identifier, the
database credentials, or any internal exception trace. `agreement`
SHALL be one of the literals `"same_top1"`, `"same_candidate_set"`,
`"different"`, `"fuzzy_only"`, `"vector_only"`, or `"no_result"`.

`fuzzy_candidate_scores` SHALL be empty when
`fuzzy_candidate_ids` is empty; otherwise the top fuzzy candidate's
score is `1.0` and subsequent entries are non-increasing in
encounter order. `vector_candidate_scores` SHALL be empty when
`vector_candidate_ids` is empty; otherwise the entries SHALL be
populated from `ProductPresentationVectorMatch.score` returned by
the 4.9 search service. `failure_category` SHALL be `None` when
both the embedding pipeline and the vector-search pipeline succeed;
SHALL be `"embedding_failure"` when the embedding client raises
any exception during `embed_query` (or when normalizing the input
text raises any exception); and SHALL be `"vector_failure"` when
the vector search service raises any exception during
`search_similar`. The recorder MAY replace a `None` value with
`"unknown"` when the category is `None` and `vector_available is
False`; the shadow service SHALL NOT emit `"unknown"`.

#### Scenario: Dataclass exposes only the twelve documented fields

- **WHEN** the `ProductRecognitionShadowComparison` class is
  inspected
- **THEN** it exposes exactly
  `fuzzy_best_id`, `vector_best_id`, `fuzzy_candidate_ids`,
  `vector_candidate_ids`, `fuzzy_candidate_scores`,
  `vector_candidate_scores`, `agreement`, `fuzzy_latency_ms`,
  `embedding_latency_ms`, `vector_latency_ms`, `vector_available`,
  `failure_category`
- **AND** no field carries the input text, the customer message,
  the raw vector, the prompt, the source document, the correlation
  identifier, the database credential, or an internal exception
  trace

#### Scenario: Hidden `_failure_category` attribute is not used

- **WHEN** the source under `backend/services/` is inspected
- **THEN** the codebase does NOT call
  `object.__setattr__(comparison, "_failure_category", ...)` or
  read the comparison through `getattr(comparison,
  "_failure_category", None)`
- **AND** the shadow service supplies `failure_category` as a
  constructor argument to `ProductRecognitionShadowComparison`
- **AND** the recorder reads the category from the explicit
  `comparison.failure_category` field

#### Scenario: Failure category is set on embedding-pipeline exception

- **WHEN** the shadow service produces a comparison and the
  embedding client raised any exception during `embed_query` (or
  normalizing the input text raised any exception)
- **THEN** the returned `ProductRecognitionShadowComparison`
  carries `failure_category == "embedding_failure"`

#### Scenario: Failure category is set on vector-pipeline exception

- **WHEN** the shadow service produces a comparison and the
  vector search service raised any exception during
  `search_similar`
- **THEN** the returned `ProductRecognitionShadowComparison`
  carries `failure_category == "vector_failure"`

#### Scenario: Failure category is None on a successful comparison

- **WHEN** the shadow service produces a comparison and both the
  embedding pipeline and the vector-search pipeline succeed
- **THEN** the returned `ProductRecognitionShadowComparison`
  carries `failure_category is None`

#### Scenario: Dataclass is frozen after construction

- **WHEN** a `ProductRecognitionShadowComparison` instance is
  created and assigned to one of its fields
- **THEN** the assignment raises `dataclasses.FrozenInstanceError`

#### Scenario: Agreement is one of the documented literals

- **WHEN** a `ProductRecognitionShadowComparison` instance is
  created with any value of `agreement`
- **THEN** `agreement` is one of `"same_top1"`,
  `"same_candidate_set"`, `"different"`, `"fuzzy_only"`,
  `"vector_only"`, or `"no_result"`

#### Scenario: Fuzzy candidate scores align with the fuzzy candidate ids

- **WHEN** a `ProductRecognitionShadowComparison` instance is
  produced with a non-empty `fuzzy_candidate_ids`
- **THEN** `len(fuzzy_candidate_scores) == len(fuzzy_candidate_ids)`
- **AND** every score is a `float` in `[0.0, 1.0]`
- **AND** the score sequence is non-increasing in encounter order
- **AND** the first score is `1.0`

#### Scenario: Vector candidate scores align with the vector candidate ids

- **WHEN** a `ProductRecognitionShadowComparison` instance is
  produced with a non-empty `vector_candidate_ids`
- **THEN** `len(vector_candidate_scores) == len(vector_candidate_ids)`
- **AND** every score is a `float` in `[0.0, 1.0]` populated from
  the corresponding `ProductPresentationVectorMatch.score`

### Requirement: Shadow service compares fuzzy and vector results without affecting the fuzzy outcome

The system SHALL expose a
`ProductRecognitionShadowService` in
`backend/services/product_recognition_shadow_service.py` that
implements a single
`compare(text: str, catalog: list[dict], fuzzy_result:
ProductRecognizerResult, fuzzy_latency_ms: float, id_comercio: int)
-> tuple[ProductRecognitionShadowComparison,
ProductRecognitionHybridObservation]` method. The fuzzy recognizer
SHALL be invoked **exactly once** per shadow call: the
`ShadowedProductRecognizer` decorator runs the inner fuzzy
recognizer, measures its latency, and forwards the already-computed
result and latency to the shadow service. The shadow service SHALL
NOT accept a fuzzy recognizer as a collaborator and SHALL NOT
invoke any fuzzy recognizer. The method SHALL:

1. Consume the caller-supplied `fuzzy_result` and
   `fuzzy_latency_ms` directly; never re-invoke the fuzzy
   recognizer.
2. After the fuzzy call has been consumed, attempt the embedding
   pipeline: `embedding_query_text = _normalizar_texto(text)` from
   `backend.recognizers.product_recognizer`; call the injected
   `OllamaEmbeddingClient` (or any object implementing
   `embed_query`) to obtain a `query_embedding`; capture the
   embedding latency as `embedding_latency_ms`.
3. When a `query_embedding` is available, call the injected
   `ProductPresentationVectorSearchService.search_similar` with
   `id_comercio=id_comercio`,
   `query_embedding=query_embedding`,
   `top_k=settings.shadow_vector_top_k`,
   `candidate_producto_presentacion_ids=None`. Capture the vector
   latency as `vector_latency_ms`. The shadow service SHALL NOT
   call `search_similar` when the embedding pipeline raised any
   exception.
4. If any step of the embedding or vector pipeline raises any
   exception, mark `vector_available=False`, set `vector_best_id=
   None`, set `vector_candidate_ids=()`, set
   `vector_candidate_scores=()`, supply a sanitized
   `failure_category` to the `ProductRecognitionShadowComparison`
   constructor (`"embedding_failure"` for embedding-pipeline
   exceptions, `"vector_failure"` for vector-service exceptions,
   `None` when both pipelines succeed), and continue without
   raising the semantic exception to the caller. The fuzzy latency
   and the elapsed time up to the failure SHALL be preserved. The
   shadow service SHALL NOT mutate the constructed comparison
   through `object.__setattr__` and SHALL NOT attach a hidden
   `_failure_category` attribute.
5. When the embedding and vector steps succeed, mark
   `vector_available=True`, set `vector_best_id` to the first
   `ProductPresentationVectorMatch.id_producto_presentacion` (or
   `None` if the match list is empty), set `vector_candidate_ids`
   to a tuple of all returned `id_producto_presentacion` values in
   match order, set `vector_candidate_scores` to a tuple of
   the corresponding `ProductPresentationVectorMatch.score`
   values in match order, and pass `failure_category=None` to the
   constructor.
6. Populate `fuzzy_best_id` from the first
   `RecognizedProduct.producto_presentacion_id` in
   `fuzzy_result["encontrados"]` (or `None` when the list is
   empty), and `fuzzy_candidate_ids` from the union of every
   `producto_presentacion_id` in `encontrados` and every
   `producto_presentacion_id` inside each
   `encontrados_posibles[*]["productos"]` group, in encounter
   order. Populate `fuzzy_candidate_scores` aligned with
   `fuzzy_candidate_ids`, with the top entry equal to `1.0` and
   subsequent entries non-increasing in encounter order.
7. Compute `agreement` in this exact order, returning the first
   matching case:
   - `"no_result"` when both `fuzzy_candidate_ids` and
     `vector_candidate_ids` are empty.
   - `"same_top1"` when `fuzzy_best_id == vector_best_id` and
     `fuzzy_best_id is not None`.
   - `"same_candidate_set"` when
     `set(fuzzy_candidate_ids) == set(vector_candidate_ids)`
     AND `fuzzy_best_id != vector_best_id` AND neither side is
     empty.
   - `"different"` when both sides are non-empty and the candidate
     sets are not equal AND the top ids differ.
   - `"fuzzy_only"` when `fuzzy_candidate_ids` is non-empty and
     `vector_candidate_ids` is empty.
   - `"vector_only"` when `vector_candidate_ids` is non-empty and
     `fuzzy_candidate_ids` is empty.
8. Compute the strictly observational `ProductRecognitionHybridObservation`
   dataclass (see the dedicated requirement below). The hybrid
   observation is a parallel, data-only structure that NEVER
   alters the fuzzy result, the visible candidates, the pending
   context, the handlers, the responses, or any persistence.
9. The service SHALL NOT modify the fuzzy result, SHALL NOT raise
   a semantic exception to the caller, SHALL NOT retry the
   embedding or vector pipeline automatically, and SHALL NOT
   write any `producto_presentacion_embeddings` row or call any
   `mark_status` / `mark_stale` / `mark_inactive` method.
10. The service SHALL NOT import FastAPI, HTTP, the embedding
    client transport implementation, the document builder, the
    seeder, the indexer, the sync service, or any router. The
    service SHALL import the abstract
    `ProductRecognizerProtocol` only for type-level imports (the
    service does not hold a fuzzy recognizer), the
    `ProductPresentationVectorSearchService`, and a Protocol for
    the embedding client (`embed_query` method) so test fakes
    can be injected through the constructor.

#### Scenario: Fuzzy path is unaffected by the shadow service

- **WHEN** `compare(text, catalog, fuzzy_result, fuzzy_latency_ms,
  id_comercio)` is called
- **THEN** the returned fuzzy recognizer result is the exact
  `ProductRecognizerResult` produced by the inner fuzzy recognizer
  (the caller-supplied `fuzzy_result` is passed through unchanged)
- **AND** the caller receives no exception, no `None`, and no
  semantic-path state from the shadow service

#### Scenario: Fuzzy mode is a no-op for embedding and vector

- **WHEN** the shadow mode is `"fuzzy"` and the orchestrator
  factory builds the recognizer
- **THEN** the shadow service's `compare` method is NOT invoked by
  the product-recognition boundary
- **AND** the embedding client and the vector search service are
  NOT called

#### Scenario: Fuzzy recognizer is invoked exactly once

- **WHEN** `ShadowedProductRecognizer.recognize` is called in
  shadow mode
- **THEN** the inner fuzzy recognizer is invoked exactly once
- **AND** the shadow service's `compare` method does NOT invoke
  the fuzzy recognizer
- **AND** the `fuzzy_latency_ms` carried by the comparison equals
  the latency the decorator measured

#### Scenario: Matching top results classify as same_top1

- **WHEN** `compare` is called with a `fuzzy_result` that yields
  fuzzy top id `42` and the vector pipeline yields top id `42`
- **THEN** `agreement == "same_top1"`

#### Scenario: Different top results classify as different

- **WHEN** `compare` is called with `fuzzy_result` whose top id
  is `42` and vector top id `99`
- **THEN** `agreement == "different"`

#### Scenario: Matching candidate sets with reordered top classify as same_candidate_set

- **WHEN** `compare` is called with `fuzzy_result` whose
  candidate ids are `[42, 99]` and fuzzy best id is `42`, and
  vector candidate ids `[99, 42]` with vector best id `99`
- **THEN** `agreement == "same_candidate_set"`

#### Scenario: Fuzzy-only result is classified correctly

- **WHEN** `compare` is called with a `fuzzy_result` whose
  candidate ids are non-empty and an empty vector candidate list
  (because the vector service returned no matches or
  `vector_available=False`)
- **THEN** `agreement == "fuzzy_only"`

#### Scenario: Vector-only result is classified correctly

- **WHEN** `compare` is called with a `fuzzy_result` whose
  candidate ids are empty and a non-empty vector candidate list
- **THEN** `agreement == "vector_only"`

#### Scenario: No-result case is classified correctly

- **WHEN** `compare` is called with empty fuzzy and vector
  candidate lists
- **THEN** `agreement == "no_result"`

#### Scenario: Commerce isolation is preserved

- **WHEN** `compare` is called with `id_comercio=1` and the
  vector search service is configured to return matches for
  comercio 1 only
- **THEN** the shadow service passes `id_comercio=1` to the
  vector search service
- **AND** the shadow service never passes a different
  `id_comercio` to the vector search service

#### Scenario: Embedding failure does not affect fuzzy output

- **WHEN** the embedding client raises any exception during
  `embed_query`
- **THEN** `compare` returns a
  `ProductRecognitionShadowComparison` with `vector_available=
  False`, `vector_best_id=None`, `vector_candidate_ids=()`,
  `vector_candidate_scores=()`,
  `embedding_latency_ms` set to the elapsed time up to the
  failure, `vector_latency_ms=0.0`,
  `failure_category="embedding_failure"`
- **AND** the agreement reflects `fuzzy_only` when the fuzzy side
  produced any candidate, otherwise `"no_result"`
- **AND** the fuzzy recognizer is NOT re-invoked

#### Scenario: Vector-search failure does not affect fuzzy output

- **WHEN** the vector search service raises any exception during
  `search_similar`
- **THEN** `compare` returns a
  `ProductRecognitionShadowComparison` with `vector_available=
  False`, `vector_best_id=None`, `vector_candidate_ids=()`,
  `vector_candidate_scores=()`,
  `vector_latency_ms` set to the elapsed time up to the failure,
  `failure_category="vector_failure"`
- **AND** the agreement reflects `fuzzy_only` when the fuzzy side
  produced any candidate, otherwise `"no_result"`
- **AND** the fuzzy recognizer is NOT re-invoked

#### Scenario: Component latencies are recorded

- **WHEN** `compare` completes successfully with fuzzy consumed
  from the caller and all three steps (embedding, vector) running
- **THEN** `fuzzy_latency_ms` equals the caller-supplied
  `fuzzy_latency_ms`
- **AND** `embedding_latency_ms > 0.0`
- **AND** `vector_latency_ms > 0.0`
- **AND** the latencies are non-negative finite `float` values
- **AND** `failure_category is None`

#### Scenario: No retry is performed

- **WHEN** the embedding client raises any exception during
  `embed_query`
- **THEN** the shadow service does NOT invoke the embedding
  client a second time
- **AND** the shadow service does NOT invoke the vector search
  service
- **AND** the shadow service does NOT invoke the fuzzy recognizer

#### Scenario: Hybrid observation is returned alongside the comparison

- **WHEN** `compare` is called with a non-empty `fuzzy_result`
  and vector pipeline succeeds
- **THEN** the return value is a `(comparison, hybrid_observation)`
  tuple
- **AND** `hybrid_observation` is a `ProductRecognitionHybridObservation`
  with a non-empty hybrid ranking and a `decision` of `"unique"`,
  `"ambiguous"`, or `"unknown"`

### Requirement: Shadow metrics recorder logs only safe operational data

The system SHALL expose a `ShadowMetricsRecorder` in
`backend/services/shadow_metrics_recorder.py` that implements a
single
`record(comparison: ProductRecognitionShadowComparison, *,
hybrid_observation: ProductRecognitionHybridObservation,
id_comercio: int, intent: str | None, correlation_id: str) -> None`
method. The recorder SHALL emit exactly one structured log record
per call through the standard `logging` mechanism. The recorder
SHALL read the sanitized shadow-pipeline failure category from the
explicit `comparison.failure_category` field; the recorder SHALL
NOT attach or read a hidden `_failure_category` attribute through
`object.__setattr__` or `getattr`. When `comparison.vector_available
is False` AND `comparison.failure_category is None`, the recorder
SHALL emit `failure_category="unknown"` as the only recorder-side
fallback; otherwise the recorder SHALL emit the value of
`comparison.failure_category` (or `None` when the comparison
carries no failure). The fields included in the log record SHALL
be exactly:

- `id_comercio`
- `intent` (or `None`)
- `correlation_id` (the value supplied by the caller; expected to
  be a pre-normalized or pre-hashed identifier)
- `fuzzy_best_id`
- `vector_best_id`
- `fuzzy_candidate_count`
- `vector_candidate_count`
- `fuzzy_candidate_scores` (tuple of normalized fuzzy scores,
  aligned with the fuzzy candidate ids)
- `vector_candidate_scores` (tuple of cosine similarity scores,
  aligned with the vector candidate ids)
- `agreement`
- `fuzzy_latency_ms`
- `embedding_latency_ms`
- `vector_latency_ms`
- `vector_available`
- `failure_category` (the value derived from
  `comparison.failure_category` with the `unknown` fallback
  described above)
- `hybrid_candidate_ranking` (tuple of `producto_presentacion_id`
  in descending observational combined score)
- `hybrid_combined_scores` (tuple of `float` combined scores
  aligned with the hybrid ranking)
- `hybrid_top1_top2_gap` (`float` gap between top-1 and top-2)
- `exact_canonical_match` (`bool`)
- `exact_alias_match` (`bool`)
- `hybrid_decision` (one of `"unique"`, `"ambiguous"`, `"unknown"`)
- `hybrid_fuzzy_weight` (`float` provisional, non-authoritative)
- `hybrid_vector_weight` (`float` provisional, non-authoritative)
- `hybrid_unique_threshold` (`float` provisional, non-authoritative)
- `hybrid_ambiguous_threshold` (`float` provisional, non-authoritative)
- `hybrid_min_score_gap` (`float` provisional, non-authoritative,
  sourced from `settings.shadow_hybrid_min_score_gap`)
- `hybrid_non_authoritative` (`bool` literal `True` recording the
  provisional nature of the weights, thresholds, and min_score_gap)

The recorder SHALL NOT log the customer message, the raw
`query_embedding`, the embedding prompt, the source document text,
the database credentials, a Python stack trace, or the raw text of
any infrastructure exception. The recorder SHALL NOT import
FastAPI, HTTP, the embedding client, the vector search service,
the sync service, the admin router, or any persistence model. The
recorder SHALL be a plain class with no `commit`, `rollback`,
`close`, or `begin` semantics.

#### Scenario: Recorder logs the safe operational fields

- **WHEN** `record` is invoked with a populated comparison, a
  populated `hybrid_observation`, and safe operational metadata
- **THEN** exactly one log record is emitted
- **AND** the log record carries `id_comercio`, `intent`,
  `correlation_id`, `fuzzy_best_id`, `vector_best_id`,
  `fuzzy_candidate_count`, `vector_candidate_count`,
  `fuzzy_candidate_scores`, `vector_candidate_scores`, `agreement`,
  `fuzzy_latency_ms`, `embedding_latency_ms`, `vector_latency_ms`,
  `vector_available`, `failure_category` (populated from
  `comparison.failure_category`),
  `hybrid_candidate_ranking`, `hybrid_combined_scores`,
  `hybrid_top1_top2_gap`, `exact_canonical_match`,
  `exact_alias_match`, `hybrid_decision`, `hybrid_fuzzy_weight`,
  `hybrid_vector_weight`, `hybrid_unique_threshold`,
  `hybrid_ambiguous_threshold`, `hybrid_min_score_gap`, and
  `hybrid_non_authoritative=True`
- **AND** the log record does NOT carry the customer message, the
  raw `query_embedding`, the embedding prompt, the source
  document text, the database credentials, a Python stack trace,
  or any raw infrastructure exception text

#### Scenario: Recorder skips when the comparison is unavailable

- **WHEN** `record` is invoked with a `comparison` whose
  `vector_available` is `False` and `failure_category` is `None`
- **THEN** the recorder emits a single log record with
  `failure_category="unknown"` and the rest of the documented
  fields
- **AND** the recorder does NOT raise an exception
- **AND** the recorder does NOT mutate the comparison to supply
  the `"unknown"` fallback

#### Scenario: Recorder preserves an explicit failure category

- **WHEN** `record` is invoked with a `comparison` whose
  `failure_category` is `"embedding_failure"` or `"vector_failure"`
- **THEN** the emitted log record carries that exact value as
  `failure_category`
- **AND** the recorder does NOT overwrite the explicit field with
  `"unknown"`

#### Scenario: Recorder marks provisional weights, thresholds, and min_score_gap as non-authoritative

- **WHEN** `record` is invoked with a `hybrid_observation` whose
  `fuzzy_weight`, `vector_weight`, `unique_threshold`,
  `ambiguous_threshold`, and `min_score_gap` are populated
- **THEN** the emitted log record carries `hybrid_non_authoritative=True`
- **AND** the log record carries the actual weights, thresholds,
  and min_score_gap with non-authoritative semantics so Subphase
  4.11 calibration can replace them without changing the
  observation surface

#### Scenario: Recorder is module-boundary clean

- **WHEN** the recorder module is inspected
- **THEN** it does NOT import FastAPI, HTTP, the embedding client
  module, the vector search service module, the sync service, the
  admin router, or any persistence model
- **AND** it does NOT call any `commit`, `rollback`, `close`, or
  `begin` method
- **AND** it does NOT attach or read a hidden `_failure_category`
  attribute on the comparison
