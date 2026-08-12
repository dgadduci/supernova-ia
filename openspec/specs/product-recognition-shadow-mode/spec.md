# Capability: product-recognition-shadow-mode

## Purpose

TBD
## Requirements
### Requirement: Product recognizer mode setting

`Settings.product_recognizer_mode` SHALL accept `"fuzzy"`, `"shadow"`, or
`"hybrid_authoritative"`, defaulting to `"fuzzy"` and overridable through the
same-named environment variable. Valid values are accepted verbatim. An invalid
value, including empty, SHALL safely resolve to `"fuzzy"`, emit one sanitized
warning with `configured_mode`, `effective_mode`, and `reason`, and SHALL NOT
prevent startup or customer processing. `InvalidProductRecognizerMode` remains
a reserved marker and is not raised by the environment resolver.

Fuzzy is authoritative in fuzzy and shadow. Shadow is observational and must
never alter the returned fuzzy result. Hybrid is authoritative only in
`hybrid_authoritative`. Existing observation structures SHALL record configured
mode, effective mode, authoritative strategy, fuzzy decision, hybrid decision
when evaluated, explicit fallback, and a sanitized fallback category.

#### Scenario: Default mode is fuzzy

- **WHEN** `Settings.load()` is called without an explicit override
- **THEN** `settings.product_recognizer_mode == "fuzzy"`
- **AND** no warning is emitted

#### Scenario: Shadow mode override is accepted

- **WHEN** `PRODUCT_RECOGNIZER_MODE=shadow` is set before `Settings.load()`
- **THEN** `settings.product_recognizer_mode == "shadow"`
- **AND** no warning is emitted

#### Scenario: Hybrid authoritative mode override is accepted

- **WHEN** `PRODUCT_RECOGNIZER_MODE=hybrid_authoritative` is set before
  `Settings.load()`
- **THEN** `settings.product_recognizer_mode == "hybrid_authoritative"`
- **AND** no warning is emitted

#### Scenario: Invalid mode falls back to fuzzy with a sanitized warning

- **WHEN** `PRODUCT_RECOGNIZER_MODE=hybrid_active` is set before
  `Settings.load()`
- **THEN** `Settings.load()` completes without raising
- **AND** `settings.product_recognizer_mode == "fuzzy"`
- **AND** exactly one structured warning carries `configured_mode`,
  `effective_mode`, and `reason`
- **AND** the hybrid authoritative policy file is NOT loaded

#### Scenario: Shadow pipeline failure does not affect quitar

- **WHEN** quitar_producto runs with shadow mode and hybrid observation fails
- **THEN** the fuzzy result remains authoritative and is returned unchanged
- **AND** the safe failure category is observed

### Requirement: Shadow vector top-k setting

`backend.config.settings.Settings` SHALL expose a
`shadow_vector_top_k` attribute accepting positive integers
(`> 0`). The default value SHALL be `5`. The setting SHALL be
overridable through an environment variable of the same name and
SHALL be validated at `Settings.load()` time. When the value is
non-positive, `Settings.load()` SHALL raise
`InvalidShadowVectorTopK(ValueError)`. The shadow service SHALL use
`settings.shadow_vector_top_k` as the `top_k` argument for the
4.9 `ProductPresentationVectorSearchService.search_similar` call.

#### Scenario: Default top-k is 5

- **WHEN** `Settings.load()` is called without an explicit override
- **THEN** `settings.shadow_vector_top_k == 5`

#### Scenario: Positive top-k override is accepted

- **WHEN** the environment variable `SHADOW_VECTOR_TOP_K=10` is set
  before `Settings.load()` is called
- **THEN** `settings.shadow_vector_top_k == 10`

#### Scenario: Zero top-k is rejected at load time

- **WHEN** `SHADOW_VECTOR_TOP_K=0` is set before `Settings.load()`
  is called
- **THEN** `Settings.load()` raises `InvalidShadowVectorTopK`

#### Scenario: Negative top-k is rejected at load time

- **WHEN** `SHADOW_VECTOR_TOP_K=-1` is set before `Settings.load()`
  is called
- **THEN** `Settings.load()` raises `InvalidShadowVectorTopK`

### Requirement: Shadow hybrid min score gap setting

`backend.config.settings.Settings` SHALL expose a
`shadow_hybrid_min_score_gap` attribute accepting `float` values
in the closed interval `[0.0, 1.0]`. The default value SHALL be
`0.05`. The setting SHALL be overridable through an environment
variable of the same name and SHALL be validated at
`Settings.load()` time. When the value is outside `[0.0, 1.0]`
(e.g. negative, strictly greater than `1.0`, or `NaN`),
`Settings.load()` SHALL raise
`InvalidShadowHybridMinScoreGap(ValueError)` and the loaded
settings SHOULD NOT be used to build any shadow service or hybrid
observation. The setting is **provisional** and **non-authoritative**:
it is used only by the shadow-mode observational hybrid decision
recorded on `ProductRecognitionHybridObservation.min_score_gap`,
and is explicitly marked as such so Subphase 4.11 calibration can
replace it without changing the observation surface. The setting
SHALL NOT be consumed by the fuzzy recognizer, the orchestrator,
the handlers, the pending context, the responses, or any
persistence.

#### Scenario: Default min score gap is 0.05

- **WHEN** `Settings.load()` is called without an explicit override
- **THEN** `settings.shadow_hybrid_min_score_gap == 0.05`

#### Scenario: Valid min score gap override is accepted

- **WHEN** the environment variable
  `SHADOW_HYBRID_MIN_SCORE_GAP=0.1` is set before `Settings.load()`
  is called
- **THEN** `settings.shadow_hybrid_min_score_gap == 0.1`

#### Scenario: Zero min score gap is accepted

- **WHEN** `SHADOW_HYBRID_MIN_SCORE_GAP=0.0` is set before
  `Settings.load()` is called
- **THEN** `settings.shadow_hybrid_min_score_gap == 0.0`

#### Scenario: One min score gap is accepted

- **WHEN** `SHADOW_HYBRID_MIN_SCORE_GAP=1.0` is set before
  `Settings.load()` is called
- **THEN** `settings.shadow_hybrid_min_score_gap == 1.0`

#### Scenario: Negative min score gap is rejected at load time

- **WHEN** `SHADOW_HYBRID_MIN_SCORE_GAP=-0.01` is set before
  `Settings.load()` is called
- **THEN** `Settings.load()` raises
  `InvalidShadowHybridMinScoreGap`

#### Scenario: Above-one min score gap is rejected at load time

- **WHEN** `SHADOW_HYBRID_MIN_SCORE_GAP=1.01` is set before
  `Settings.load()` is called
- **THEN** `Settings.load()` raises
  `InvalidShadowHybridMinScoreGap`

#### Scenario: NaN min score gap is rejected at load time

- **WHEN** `SHADOW_HYBRID_MIN_SCORE_GAP=NaN` is set before
  `Settings.load()` is called
- **THEN** `Settings.load()` raises
  `InvalidShadowHybridMinScoreGap`

#### Scenario: Min score gap is provisional and non-authoritative

- **WHEN** the shadow service uses
  `settings.shadow_hybrid_min_score_gap` to compute the
  observational hybrid decision
- **THEN** the value is recorded as
  `ProductRecognitionHybridObservation.min_score_gap` and as
  `hybrid_min_score_gap` on the recorder log record
- **AND** the value is marked with `non_authoritative=True`
  semantics on the observation
- **AND** no authoritative path consumes it
- **AND** the fuzzy result, the visible candidates, the pending
  context, the handlers, the responses, and any persistence are
  unchanged

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

#### Scenario: Dataclass is frozen

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

### Requirement: Shadowed recognizer decorator preserves the fuzzy result contract

The system SHALL expose a `ShadowedProductRecognizer` decorator in
`backend/services/product_recognition_shadow_service.py` that
implements `ProductRecognizerProtocol` and exposes the same
`recognize(text: str, catalog: list[dict]) -> ProductRecognizerResult`
signature as `FuzzyProductRecognizer`. The decorator SHALL:

1. Invoke the injected inner recognizer (`FuzzyProductRecognizer`
   in production) **exactly once**, measure its latency, and use
   the result as the authoritative fuzzy result for the request.
2. Look up the commerce id from the caller-supplied catalog by
   reading `catalog[0]["categoria_id"]` through an injected
   `commerce_id_resolver` callable that defaults to `None`; when
   the resolver is `None` or returns `None`, skip shadow
   comparison and return the fuzzy result unchanged.
3. When the resolver yields a commerce id, delegate to
   `ProductRecognitionShadowService.compare(text, catalog,
   fuzzy_result, fuzzy_latency_ms, id_comercio)` (the already-
   computed fuzzy result and measured fuzzy latency) and forward
   the comparison and the observational hybrid observation to the
   injected `ShadowMetricsRecorder`.
4. Return the inner recognizer result unchanged, byte-for-byte.
5. Never re-invoke the inner recognizer (the shadow service
   receives the already-computed result and does not invoke the
   fuzzy recognizer) and never mutate the fuzzy result.

The decorator SHALL NOT introduce any HTTP, FastAPI, database
session, persistence, or transaction logic. The decorator SHALL
NOT mutate the inner recognizer's result, the candidates visible
to the consumer, the pending context, the handlers, the responses,
or any persistence.

#### Scenario: Recognizer protocol is preserved

- **WHEN** `ShadowedProductRecognizer` is inspected
- **THEN** it exposes a `recognize(text: str, catalog: list[dict])
  -> ProductRecognizerResult` method
- **AND** it is assignable to `ProductRecognizerProtocol`

#### Scenario: Fuzzy result is returned unchanged

- **WHEN** the inner recognizer produces a fuzzy result
- **THEN** `ShadowedProductRecognizer.recognize` returns the exact
  same `ProductRecognizerResult` object
- **AND** every field on the result (`encontrados`,
  `encontrados_posibles`, `encontrados_no_disponibles`,
  `no_encontrados`) is identical to the inner recognizer's output

#### Scenario: Commerce id resolution failure skips shadow comparison

- **WHEN** the injected `commerce_id_resolver` returns `None`
- **THEN** `ShadowedProductRecognizer.recognize` returns the fuzzy
  result unchanged
- **AND** the shadow service's `compare` method is NOT invoked
- **AND** the recorder is NOT invoked

#### Scenario: Recognizer is integration-only at the shared boundary

- **WHEN** the project source is inspected
- **THEN** `ShadowedProductRecognizer` is wired into the shared
  product-recognition boundary at
  `backend/intents/orchestration/agregar_producto_orchestrator.py`
  through the
  `get_product_recognizer(settings)` factory
- **AND** the `agregar_producto`, `quitar_producto`, and
  `modificar_producto` orchestrators import `detectar_productos`
  from that boundary and call it without modification

#### Scenario: Hybrid observation does not alter the fuzzy result

- **WHEN** `ShadowedProductRecognizer.recognize` is called in
  shadow mode
- **THEN** the returned fuzzy result is byte-for-byte the inner
  recognizer's output
- **AND** the candidates, the pending context, the handlers, the
  responses, and any persistence are unchanged
- **AND** the hybrid observation is recorded only by the
  recorder; it is never consumed by the orchestrator, the
  handlers, or the persistence layer

### Requirement: Observational hybrid ranking is recorded without becoming authoritative

The system SHALL expose a frozen
`ProductRecognitionHybridObservation` dataclass in
`backend/services/product_recognition_shadow_comparison.py` with
exactly these fields: `hybrid_candidate_ranking: tuple[int, ...]`,
`hybrid_combined_scores: tuple[float, ...]`,
`hybrid_top1_top2_gap: float`, `exact_canonical_match: bool`,
`exact_alias_match: bool`, `decision: str`, `fuzzy_weight: float`,
`vector_weight: float`, `unique_threshold: float`,
`ambiguous_threshold: float`, `min_score_gap: float`,
`non_authoritative: bool`. The `non_authoritative` field SHALL be
the literal `True` and the provisional weights and thresholds
(including `min_score_gap`, sourced from
`settings.shadow_hybrid_min_score_gap`) SHALL be marked as
non-authoritative so Subphase 4.11 calibration can replace them
without changing the observation surface.

The hybrid observation is computed by the shadow service as
follows:

1. Build a candidate score map keyed by `producto_presentacion_id`
   from the union of `fuzzy_candidate_ids` (with their
   `fuzzy_candidate_scores`) and `vector_candidate_ids` (with
   their `vector_candidate_scores`). Candidates present in only
   one side use `0.0` for the missing score.
2. For each candidate, compute the observational combined score
   as `fuzzy_weight * fuzzy_score + vector_weight * vector_score`
   using the provisional weights configured on the shadow
   service (defaults `fuzzy_weight=0.5`, `vector_weight=0.5`,
   `unique_threshold=0.7`, `ambiguous_threshold=0.4`,
   `min_score_gap=settings.shadow_hybrid_min_score_gap`).
3. Order candidates by descending combined score, breaking ties
   by ascending encounter order across the union; produce
   `hybrid_candidate_ranking` (tuple of `producto_presentacion_id`)
   and `hybrid_combined_scores` (tuple of `float` aligned with
   the ranking).
4. Compute `hybrid_top1_top2_gap` as the difference between top-1
   and top-2 combined scores (`0.0` when fewer than two-ranked
   candidates).
5. Compute `exact_canonical_match` as `True` when the normalized
   input text (using `_normalizar_texto`) equals a catalog
   `producto_nombre` for a candidate in the hybrid ranking.
   Compute `exact_alias_match` as `True` when the normalized input
   text equals any applicable alias (`general_aliases` or
   `specific_aliases`) for a candidate in the hybrid ranking.
6. Compute `decision` in this exact order, returning the first
   matching case:
   - `"unique"` when `exact_canonical_match` is `True` and the
     canonical-matched candidate is in `hybrid_candidate_ranking`.
   - `"unique"` when `exact_alias_match` is `True` and the
     alias-matched candidate is in `hybrid_candidate_ranking`.
   - `"unique"` when `hybrid_candidate_ranking` is non-empty AND
     the top-1 combined score is `>= unique_threshold` AND
     (`len(hybrid_candidate_ranking) == 1` OR
     `hybrid_top1_top2_gap >= min_score_gap`).
   - `"ambiguous"` when `hybrid_candidate_ranking` has more than
     one candidate AND the top-1 combined score is
     `>= ambiguous_threshold`.
   - `"unknown"` otherwise.

The hybrid observation is **strictly observational**: it never
modifies the fuzzy result, the visible candidates, the pending
context, the handlers, the responses, or any persistence. The
provisional weights and thresholds are non-authoritative and are
explicitly configurable for later calibration in Subphase 4.11.
This subphase does NOT introduce active hybrid mode, final
calibrated thresholds, or fuzzy fallback switching.

#### Scenario: Hybrid observation dataclass is frozen

- **WHEN** a `ProductRecognitionHybridObservation` instance is
  created and assigned to one of its fields
- **THEN** the assignment raises `dataclasses.FrozenInstanceError`

#### Scenario: Observation is non-authoritative

- **WHEN** a `ProductRecognitionHybridObservation` instance is
  constructed
- **THEN** `non_authoritative` equals `True`
- **AND** the weights and thresholds are labeled as provisional
- **AND** no authoritative path consumes them

#### Scenario: Hybrid ranking is ordered by combined score

- **WHEN** the shadow service computes a hybrid observation
- **THEN** `hybrid_candidate_ranking` is ordered by descending
  `hybrid_combined_scores`
- **AND** `len(hybrid_candidate_ranking) ==
  len(hybrid_combined_scores)`
- **AND** ties are broken by ascending encounter order across
  the union of fuzzy and vector candidates

#### Scenario: Top-1/top-2 gap is recorded

- **WHEN** `hybrid_candidate_ranking` has at least two entries
- **THEN** `hybrid_top1_top2_gap` equals the difference between
  the top-1 and top-2 combined scores
- **AND** `hybrid_top1_top2_gap` is a non-negative `float`

#### Scenario: Gap is zero when fewer than two candidates

- **WHEN** `hybrid_candidate_ranking` has fewer than two entries
- **THEN** `hybrid_top1_top2_gap == 0.0`

#### Scenario: min_score_gap is recorded on the observation

- **WHEN** the shadow service computes a hybrid observation
- **THEN** `ProductRecognitionHybridObservation.min_score_gap`
  equals the configured
  `settings.shadow_hybrid_min_score_gap`
- **AND** `min_score_gap` is in `[0.0, 1.0]`
- **AND** `min_score_gap` is marked as non-authoritative via
  `non_authoritative=True`

#### Scenario: Clear top-1/top-2 gap classifies as unique

- **WHEN** `hybrid_candidate_ranking` has at least two candidates
- **AND** the top-1 combined score is `>= unique_threshold`
- **AND** `hybrid_top1_top2_gap >= min_score_gap`
- **THEN** `decision` is `"unique"`

#### Scenario: Insufficient top-1/top-2 gap classifies as ambiguous

- **WHEN** `hybrid_candidate_ranking` has at least two candidates
- **AND** the top-1 combined score is `>= unique_threshold`
- **AND** `hybrid_top1_top2_gap < min_score_gap`
- **THEN** `decision` is `"ambiguous"`

#### Scenario: Multiple candidates above ambiguous threshold with insufficient gap classify as ambiguous

- **WHEN** `hybrid_candidate_ranking` has at least two candidates
- **AND** the top-1 combined score is `>= ambiguous_threshold`
- **AND** the top-1 combined score is `< unique_threshold` OR
  `hybrid_top1_top2_gap < min_score_gap`
- **THEN** `decision` is `"ambiguous"`

#### Scenario: Single candidate can be unique

- **WHEN** `hybrid_candidate_ranking` has exactly one candidate
- **AND** the top-1 combined score is `>= unique_threshold`
- **THEN** `decision` is `"unique"`

#### Scenario: Exact match remains unique regardless of gap

- **WHEN** `exact_canonical_match` is `True` OR `exact_alias_match`
  is `True`
- **AND** the matched candidate is in `hybrid_candidate_ranking`
- **THEN** `decision` is `"unique"`
- **AND** the `hybrid_top1_top2_gap` constraint and the
  `min_score_gap` constraint are NOT consulted because the
  exact-match short-circuits to `"unique"` before the gap rule

#### Scenario: Exact canonical match sets the unique flag

- **WHEN** the normalized input text equals a catalog
  `producto_nombre` for a candidate
- **THEN** `exact_canonical_match` is `True`
- **AND** the canonical-matched candidate is in
  `hybrid_candidate_ranking`
- **AND** `decision` is `"unique"`

#### Scenario: Exact alias match sets the unique flag

- **WHEN** the normalized input text equals an applicable alias
  for a candidate
- **THEN** `exact_alias_match` is `True`
- **AND** the alias-matched candidate is in
  `hybrid_candidate_ranking`
- **AND** `decision` is `"unique"`

#### Scenario: Vector-then-fuzzy decision order is applied

- **WHEN** neither exact canonical nor exact alias matches apply
- **AND** `hybrid_candidate_ranking` is non-empty
- **THEN** the decision is computed using the vector signal first
  (combined score driven primarily by `vector_weight`) and the
  fuzzy signal as a complementary signal
- **AND** the decision is `"unique"` when the top-1 combined
  score is `>= unique_threshold` AND the ranked candidate set
  either has exactly one candidate or the top-1/top-2 gap is
  `>= min_score_gap`
- **AND** the decision is `"ambiguous"` when there is more than
  one ranked candidate and the top-1 combined score is
  `>= ambiguous_threshold`
- **AND** the decision is `"unknown"` otherwise

#### Scenario: Decision order is exact canonical → exact alias → vector → fuzzy

- **WHEN** the shadow service produces a hybrid observation
- **THEN** the `decision` reflects the first matching case in the
  fixed order: exact canonical, exact alias, vector signal,
  fuzzy complementary signal, unique / ambiguous / unknown
- **AND** later cases in the order do not override an earlier
  `"unique"` short-circuit

#### Scenario: Hybrid observation does not alter the fuzzy result

- **WHEN** the shadow service produces a hybrid observation
- **THEN** the returned fuzzy result is byte-for-byte equivalent
  to the inner recognizer's output
- **AND** the visible candidates, the pending context, the
  handlers, the responses, and any persistence are unchanged

#### Scenario: Provisional weights, thresholds, and min_score_gap are configurable

- **WHEN** the shadow service is constructed with custom
  `fuzzy_weight`, `vector_weight`, `unique_threshold`,
  `ambiguous_threshold`, or `min_score_gap` values
- **THEN** the hybrid observation carries those values
- **AND** the `non_authoritative` flag remains `True`
- **AND** no authoritative path consumes them

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

### Requirement: Settings-driven factory resolves the shared recognizer boundary

The system SHALL expose a `get_product_recognizer(settings:
Settings) -> ProductRecognizerProtocol` factory in
`backend/services/product_recognition_factory.py`. The factory SHALL:

1. Construct a `FuzzyProductRecognizer` instance.
2. When `settings.product_recognizer_mode == "fuzzy"`, return the
   fuzzy recognizer unchanged.
3. When `settings.product_recognizer_mode == "shadow"`, return a
   `ShadowedProductRecognizer` that wraps the fuzzy recognizer and
   delegates comparison to a `ProductRecognitionShadowService`
   constructed from the same settings and an injected
   `ShadowMetricsRecorder` instance.
4. When `settings.product_recognizer_mode == "hybrid_authoritative"`,
   return a `HybridAuthoritativeProductRecognizer` that wraps the
   fuzzy recognizer and delegates the hybrid decision to a
   `HybridAuthoritativeProductRecognizer` constructed from the same
   settings, the calibrated `HybridDecisionPolicy` loaded by
   `HybridAuthoritativePolicySource.load(settings)`, an injected
   `ShadowMetricsRecorder` instance, and the existing
   `embedding_client`, `session_provider`, and
   `commerce_id_resolver` injection points. A failure from the policy
   loader SHALL propagate as `HybridAuthoritativePolicyError` before
   any recognizer is built.

`backend/intents/orchestration/agregar_producto_orchestrator.py`
SHALL resolve its module-level `_product_recognizer` through
`get_product_recognizer(load_settings())` once at module import
time and SHALL continue to re-export `detectar_productos =
_product_recognizer.recognize` as the shared product-recognition
boundary used by the `agregar_producto`, `quitar_producto`, and
`modificar_producto` orchestrators. The local `detectar_productos`
symbol in `product_selection_context_resolver`,
`product_modification_resolver`, `quitar_producto_recognizer`, and
`modificar_producto_recognizer` SHALL be a thin wrapper that accepts
and forwards `intent_metadata`.

#### Scenario: Fuzzy mode resolves to the fuzzy recognizer

- **WHEN** `get_product_recognizer(settings)` is called with
  `settings.product_recognizer_mode == "fuzzy"`
- **THEN** the returned recognizer is a `FuzzyProductRecognizer`
  instance

#### Scenario: Shadow mode resolves to the shadowed recognizer

- **WHEN** `get_product_recognizer(settings)` is called with
  `settings.product_recognizer_mode == "shadow"`
- **THEN** the returned recognizer is a `ShadowedProductRecognizer`
  instance
- **AND** the wrapped inner recognizer is a `FuzzyProductRecognizer`
  instance

#### Scenario: Hybrid authoritative mode resolves to the hybrid authoritative recognizer

- **WHEN** `get_product_recognizer(settings)` is called with
  `settings.product_recognizer_mode == "hybrid_authoritative"` and
  `settings.hybrid_authoritative_policy_path` pointing at a valid
  eligible calibration report
- **THEN** the returned recognizer is a
  `HybridAuthoritativeProductRecognizer` instance
- **AND** the wrapped inner recognizer is a `FuzzyProductRecognizer`
  instance

#### Scenario: Safe-fuzzy fallback resolves the factory to the fuzzy recognizer

- **WHEN** `get_product_recognizer(load_settings())` is called after
  `PRODUCT_RECOGNIZER_MODE=hybrid_active` resolved the effective mode
  to `"fuzzy"` through the safe-fuzzy fallback
- **THEN** the returned recognizer is a `FuzzyProductRecognizer`
  instance
- **AND** no hybrid policy file is read

#### Scenario: Orchestrator binding uses the factory

- **WHEN** the orchestrator module is imported
- **THEN** `_product_recognizer` is the result of
  `get_product_recognizer(load_settings())`
- **AND** `detectar_productos = _product_recognizer.recognize` is
  re-exported from the orchestrator module as a thin wrapper that
  forwards `intent_metadata`
- **AND** the import fails closed with `HybridAuthoritativePolicyError`
  when the policy path is missing or non-eligible in
  `hybrid_authoritative` mode

### Requirement: Subphase 4.5–4.9 surface is unchanged

Subphases 4.5–4.9 public surfaces — the
`ProductEmbeddingDocumentBuilder`, the `OllamaEmbeddingClient`,
the `ProductoPresentacionEmbeddingIndexer` /
`ProductoPresentacionEmbeddingSeeder`, the
`ProductoPresentacionEmbeddingAdminService`, the
`CatalogEmbeddingSynchronizationService`, the
`ProductPresentationVectorSearchService`, the
`ProductoPresentacionEmbeddingSearchRepository`, the
`ProductPresentationVectorMatch` dataclass, the
`backend/recognizers/product_recognizer`, and the
`ProductRecognizerProtocol` contract — SHALL remain unchanged by
the shadow service. The shadow service SHALL NOT import or
subclass any of them. The shadow service SHALL depend only on the
`ProductRecognizerProtocol` (abstract), the
`ProductPresentationVectorSearchService` (4.9 search surface),
and a `Protocol` describing the embedding client's
`embed_query` method (no concrete dependency on
`OllamaEmbeddingClient`).

#### Scenario: 4.5–4.9 modules are not imported by the shadow surface

- **WHEN** the shadow service module, the shadowed recognizer
  module, the shadow comparison module, the recorder module, and
  the factory module are inspected
- **THEN** they do NOT import `ProductEmbeddingDocumentBuilder`,
  `ProductoPresentacionEmbeddingIndexer`,
  `ProductoPresentacionEmbeddingSeeder`,
  `ProductoPresentacionEmbeddingAdminService`,
  `CatalogEmbeddingSynchronizationService`,
  `ProductoPresentacionEmbeddingStatusRepository`,
  `ProductoPresentacionEmbeddingIndexRepository`,
  `backend.routers.admin_product_embeddings`, or any 4.7 schema

#### Scenario: 4.5–4.9 focused tests remain green

- **WHEN** the existing 4.5, 4.6, 4.7, 4.8, and 4.9 focused
  tests are executed after the shadow service lands
- **THEN** they continue to pass without modification
- **AND** the 4.6 migration is the only migration for
  `producto_presentacion_embeddings`
- **AND** the `OllamaEmbeddingClient(settings, transport=None,
  clock=None)` constructor is unchanged
- **AND** the `ProductPresentationVectorSearchService.search_similar`
  signature is unchanged

### Requirement: Offline calibration preserves shadow-mode authority and contracts

Subphase 4.11 SHALL reuse the observational ranking and decision semantics established by product-recognition shadow mode only inside the offline calibration runner. It SHALL NOT change `ProductRecognitionShadowComparison`, `ProductRecognitionHybridObservation`, `ShadowMetricsRecorder`, `ProductRecognitionShadowService`, the recognizer factory, runtime settings, provisional values, or any runtime call site.

Fuzzy recognition SHALL remain authoritative, shadow mode SHALL remain observational, and no `hybrid` runtime mode SHALL be added. The selected offline policy and its dataset fingerprint SHALL NOT be promoted automatically into runtime defaults or settings. Handlers, resolvers, pending contexts, intents, orders, responses, and persistence contracts SHALL remain unchanged.

#### Scenario: Calibration does not alter runtime behavior

- **WHEN** the offline calibration runner evaluates one or more policies
- **THEN** runtime fuzzy and shadow behavior remains byte-for-byte equivalent to Subphase 4.10.1
- **AND** `PRODUCT_RECOGNIZER_MODE` is neither read for policy authority nor modified
- **AND** no selected policy is installed as a runtime default

#### Scenario: Existing shadow failures remain observational

- **WHEN** an embedding or vector failure occurs during offline calibration
- **THEN** the runner records a sanitized calibration failure and continues
- **AND** no runtime comparison, observation, recorder, response, pending context, or persistence contract is changed

#### Scenario: Existing subphase regressions remain green

- **WHEN** Subphase 4.11 implementation is verified
- **THEN** focused tests for Subphases 4.5 through 4.10.1 pass unchanged except for test harness reuse needed by the offline calibration tests
- **AND** fuzzy remains authoritative in existing agregar, quitar, and modificar flows

### Requirement: Hybrid authoritative policy path setting

`backend.config.settings.Settings` SHALL expose a
`hybrid_authoritative_policy_path` attribute accepting either `None`
or a `str` path to a JSON calibration report. The default value SHALL
be `None`. The setting SHALL be overridable through an environment
variable of the same name. The validator SHALL run ONLY when the
effective `product_recognizer_mode` is `"hybrid_authoritative"`. In
that mode, the validator SHALL raise
`InvalidHybridAuthoritativePolicyPath(ValueError)` when the value is
anything other than `None` or a non-empty `str`. When the effective
mode is `"fuzzy"` (including the safe-fuzzy fallback case) or
`"shadow"`, the validator SHALL NOT run and a non-`None` value SHALL
be silently ignored.

#### Scenario: Default policy path is None

- **WHEN** `Settings.load()` is called without an explicit override
- **THEN** `settings.hybrid_authoritative_policy_path is None`

#### Scenario: Explicit path override is accepted

- **WHEN** `PRODUCT_RECOGNIZER_MODE=hybrid_authoritative` AND
  `HYBRID_AUTHORITATIVE_POLICY_PATH=/tmp/report.json` are set before
  `Settings.load()` is called
- **THEN** `settings.hybrid_authoritative_policy_path ==
  "/tmp/report.json"`

#### Scenario: Empty path override is rejected at load time in hybrid_authoritative mode

- **WHEN** `PRODUCT_RECOGNIZER_MODE=hybrid_authoritative` AND
  `HYBRID_AUTHORITATIVE_POLICY_PATH=` (empty string) are set before
  `Settings.load()` is called
- **THEN** `Settings.load()` raises
  `InvalidHybridAuthoritativePolicyPath`

#### Scenario: Path override is ignored in fuzzy mode

- **WHEN** `PRODUCT_RECOGNIZER_MODE=fuzzy` AND
  `HYBRID_AUTHORITATIVE_POLICY_PATH=/tmp/report.json` are set
  before `Settings.load()` is called
- **THEN** `Settings.load()` completes without raising
- **AND** the factory does NOT read the policy path

### Requirement: Safe-fuzzy fallback for unrecognised `PRODUCT_RECOGNIZER_MODE` literals

The `PRODUCT_RECOGNIZER_MODE` env-var resolver in
`backend.config.settings` SHALL treat any literal other than
`"fuzzy"`, `"shadow"`, and `"hybrid_authoritative"` as an unrecognised
value. The resolver SHALL return `"fuzzy"` as the effective mode and
SHALL emit exactly one sanitized structured log record through the
standard `logging` mechanism carrying the fields
`configured_mode` (the raw env-var literal the operator set),
`effective_mode` (the literal `"fuzzy"`), and `reason` (the sanitized
literal `"invalid_mode"`). The resolver SHALL NOT raise
`InvalidProductRecognizerMode(ValueError)`. The application SHALL
continue loading so the module-import-time
`get_product_recognizer(load_settings())` call resolves to the
`fuzzy` branch. The hybrid authoritative policy file SHALL NOT be
loaded and the `HybridAuthoritativeProductRecognizer` SHALL NOT be
constructed. The `InvalidProductRecognizerMode(ValueError)` class
SHALL remain defined as a reserved internal marker for callers that
want to validate settings coming from a non-env source; the env-var
resolver SHALL NOT raise it.

#### Scenario: Invalid literal falls back to fuzzy with a sanitized warning

- **WHEN** `PRODUCT_RECOGNIZER_MODE=hybrid_active` is set before
  `Settings.load()` is called
- **THEN** `Settings.load()` completes without raising
- **AND** `settings.product_recognizer_mode == "fuzzy"`
- **AND** exactly one structured log record is emitted carrying
  `configured_mode == "hybrid_active"`,
  `effective_mode == "fuzzy"`, and `reason == "invalid_mode"`
- **AND** the log record does NOT carry the raw exception text, a
  Python stack trace, the customer message, the database
  credentials, the host name, or any internal exception detail

#### Scenario: Capitalised typo falls back to fuzzy with a sanitized warning

- **WHEN** `PRODUCT_RECOGNIZER_MODE=HybridAuthoritative` is set
  before `Settings.load()` is called
- **THEN** `settings.product_recognizer_mode == "fuzzy"`
- **AND** exactly one structured log record is emitted carrying
  `configured_mode == "HybridAuthoritative"`,
  `effective_mode == "fuzzy"`, and `reason == "invalid_mode"`

#### Scenario: Empty value falls back to fuzzy with a sanitized warning

- **WHEN** `PRODUCT_RECOGNIZER_MODE=` (empty string) is set before
  `Settings.load()` is called
- **THEN** `Settings.load()` treats the empty string as an
  unrecognised literal and falls back to `"fuzzy"` with the same
  warning shape as the documented invalid-literal scenario

#### Scenario: Safe-fuzzy fallback does not raise InvalidProductRecognizerMode

- **WHEN** `PRODUCT_RECOGNIZER_MODE=hybrid_active` is set before
  `Settings.load()` is called
- **THEN** `Settings.load()` does NOT raise
  `InvalidProductRecognizerMode(ValueError)`

### Requirement: Hybrid authoritative mode records `mode` and `hybrid_non_authoritative=False` through the existing recorder

The `ShadowMetricsRecorder` SHALL accept a new optional `mode` argument
on `record(...)`. The recorder SHALL emit a new `mode` log field on
every record whose value equals the `mode` argument (defaulting to
`"shadow"` when the argument is omitted, so existing shadow-mode
callers do not have to change). When `mode == "hybrid_authoritative"`,
the recorder SHALL emit `hybrid_non_authoritative=False`; otherwise the
recorder SHALL emit `hybrid_non_authoritative` as the value carried by
the `ProductRecognitionHybridObservation.non_authoritative` field
(preserving the 4.10 shadow-mode semantics). The recorder SHALL NOT
emit `hybrid_non_authoritative=False` for `mode == "shadow"` or any
other mode.

#### Scenario: Recorder defaults mode to shadow

- **WHEN** `record(...)` is called without a `mode` argument
- **THEN** the emitted log record carries `mode="shadow"`
- **AND** the emitted log record carries
  `hybrid_non_authoritative` matching
  `hybrid_observation.non_authoritative`

#### Scenario: Recorder marks hybrid_authoritative decisions as authoritative

- **WHEN** `record(..., mode="hybrid_authoritative")` is called
- **THEN** the emitted log record carries
  `mode="hybrid_authoritative"`
- **AND** the emitted log record carries
  `hybrid_non_authoritative=False`

#### Scenario: Recorder preserves existing shadow-mode semantics

- **WHEN** `record(..., mode="shadow")` is called
- **THEN** the emitted log record carries `mode="shadow"`
- **AND** the emitted log record carries
  `hybrid_non_authoritative` matching
  `hybrid_observation.non_authoritative`

### Requirement: Backward-compatible shared boundary carries the catalog scope to the hybrid recognizer

The `ProductRecognizerProtocol.recognize` method SHALL gain a
keyword-only optional `intent_metadata` argument that callers use to
declare the catalog scope of the recognition call. The argument
SHALL carry a `RecognizeContext` TypedDict defined in
`backend/recognizers/product_recognizer_contract.py` with the
documented field
`catalog_scope: Literal["pending_product_selection_restricted",
"commerce_dynamic_database"]`. The `FuzzyProductRecognizer.recognize`
and `ShadowedProductRecognizer.recognize` methods SHALL accept the
new keyword argument and SHALL ignore it. The new
`HybridAuthoritativeProductRecognizer.recognize` (added by
`controlled-hybrid-product-recognition`) SHALL read `catalog_scope`
from the argument to fire the 4.11.5 guard. Every call site that
omits the argument SHALL continue to work without modification. The
change SHALL NOT add any intent-specific import inside any
recognizer. The single call site that passes
`intent_metadata={"catalog_scope": "pending_product_selection_restricted"}`
SHALL be the `detect` call inside
`backend/intents/context/product_selection_context_resolver.py`. The
local `detectar_productos` symbol in each affected module SHALL be
rewritten as a thin wrapper that accepts and forwards
`intent_metadata`. The change SHALL NOT move caller-owned
transactions and SHALL NOT re-query the full commerce catalog.

#### Scenario: Fuzzy recognizer accepts the new intent_metadata argument

- **WHEN** `FuzzyProductRecognizer.recognize(text, catalog,
  intent_metadata=RecognizeContext(catalog_scope=
  "pending_product_selection_restricted"))` is called
- **THEN** the call succeeds
- **AND** the fuzzy result is byte-for-byte equivalent to the call
  without the argument
- **AND** no intent-specific import is added to the recognizer

#### Scenario: Shadowed recognizer accepts the new intent_metadata argument

- **WHEN** `ShadowedProductRecognizer.recognize(text, catalog,
  intent_metadata=RecognizeContext(catalog_scope=
  "pending_product_selection_restricted"))` is called
- **THEN** the call succeeds
- **AND** the shadow service does not read `intent_metadata`
- **AND** the fuzzy result returned to the caller is unchanged
- **AND** the shadow comparison payload is recorded with the
  existing `mode="shadow"` semantics

#### Scenario: Product recognizer protocol accepts the new intent_metadata argument

- **WHEN** `ProductRecognizerProtocol` is inspected
- **THEN** the `recognize` method signature includes a keyword-only
  optional `intent_metadata: RecognizeContext | None = None`
  argument
- **AND** every implementation of the protocol accepts the argument

#### Scenario: Product selection context resolver passes the restricted catalog scope

- **WHEN** the resolver inside
  `backend/intents/context/product_selection_context_resolver.py`
  invokes `detectar_productos` against the restricted candidate
  catalog for the active pending intent
- **THEN** the call passes
  `intent_metadata={"catalog_scope":
  "pending_product_selection_restricted"}`

#### Scenario: Other call sites omit the intent_metadata argument

- **WHEN** the `agregar_producto` orchestrator's initial commerce-
  catalog call, the `modificar_producto` destination selection call,
  or the `quitar_producto` order-line call invokes `detectar_productos`
- **THEN** the call omits the `intent_metadata` argument (or passes
  `None`)
- **AND** the call is unaffected by the new argument

