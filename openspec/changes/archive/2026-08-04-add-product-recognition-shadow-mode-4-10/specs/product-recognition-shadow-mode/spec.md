## ADDED Requirements

### Requirement: Product recognizer mode setting

`backend.config.settings.Settings` SHALL expose a `product_recognizer_mode`
attribute accepting the literals `"fuzzy"` or `"shadow"`. The default
value SHALL be `"fuzzy"`. The setting SHALL be overridable through an
environment variable of the same name and SHALL be validated at
`Settings.load()` time. When the value is anything other than
`"fuzzy"` or `"shadow"`, `Settings.load()` SHALL raise
`InvalidProductRecognizerMode(ValueError)` and the loaded settings
SHOULD NOT be used to build any recognizer, shadow service, or
orchestrator binding. The fuzzy recognizer SHALL remain the sole
authoritative recognizer in both modes; the `"shadow"` value is
purely observational.

#### Scenario: Default mode is fuzzy

- **WHEN** `Settings.load()` is called without an explicit override
- **THEN** `settings.product_recognizer_mode == "fuzzy"`

#### Scenario: Shadow mode override is accepted

- **WHEN** the environment variable `PRODUCT_RECOGNIZER_MODE=shadow`
  is set before `Settings.load()` is called
- **THEN** `settings.product_recognizer_mode == "shadow"`

#### Scenario: Invalid mode is rejected at load time

- **WHEN** `PRODUCT_RECOGNIZER_MODE=hybrid` is set before
  `Settings.load()` is called
- **THEN** `Settings.load()` raises `InvalidProductRecognizerMode`
- **AND** no recognizer, shadow service, or orchestrator binding is
  built from the invalid settings

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
exactly eleven fields:
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
`vector_available: bool`. The dataclass SHALL inherit only from
`dataclass(frozen=True)`; it SHALL NOT be a Pydantic model, a
SQLAlchemy ORM model, or a class with side effects in
`__post_init__`. The dataclass SHALL NOT expose the input text, the
customer message, the raw vectors, the prompt, the source documents,
the correlation identifier, the database credentials, or any
internal exception trace. `agreement` SHALL be one of the literals
`"same_top1"`, `"same_candidate_set"`, `"different"`, `"fuzzy_only"`,
`"vector_only"`, or `"no_result"`.

`fuzzy_candidate_scores` SHALL be empty when
`fuzzy_candidate_ids` is empty; otherwise the top fuzzy candidate's
score is `1.0` and subsequent entries are non-increasing in
encounter order. `vector_candidate_scores` SHALL be empty when
`vector_candidate_ids` is empty; otherwise the entries SHALL be
populated from `ProductPresentationVectorMatch.score` returned by
the 4.9 search service.

#### Scenario: Dataclass exposes only the eleven documented fields

- **WHEN** the `ProductRecognitionShadowComparison` class is
  inspected
- **THEN** it exposes exactly
  `fuzzy_best_id`, `vector_best_id`, `fuzzy_candidate_ids`,
  `vector_candidate_ids`, `fuzzy_candidate_scores`,
  `vector_candidate_scores`, `agreement`, `fuzzy_latency_ms`,
  `embedding_latency_ms`, `vector_latency_ms`, `vector_available`
- **AND** no field carries the input text, the customer message,
  the raw vector, the prompt, the source document, the correlation
  identifier, the database credential, or an internal exception
  trace

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
   `vector_candidate_scores=()`, record a sanitized
   failure category (`"embedding_failure"` for embedding-client
   exceptions, `"vector_failure"` for vector-service exceptions),
   and continue without raising the semantic exception to the
   caller. The fuzzy latency and the elapsed time up to the
   failure SHALL be preserved.
5. When the embedding and vector steps succeed, mark
   `vector_available=True`, set `vector_best_id` to the first
   `ProductPresentationVectorMatch.id_producto_presentacion` (or
   `None` if the match list is empty), set `vector_candidate_ids`
   to a tuple of all returned `id_producto_presentacion` values in
   match order, and set `vector_candidate_scores` to a tuple of
   the corresponding `ProductPresentationVectorMatch.score`
   values in match order.
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
  failure, `vector_latency_ms=0.0`
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
  `vector_latency_ms` set to the elapsed time up to the failure
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
per call through the standard `logging` mechanism. The fields
included in the log record SHALL be exactly:

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
- `failure_category` (or `None` when no failure occurred)
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
  `vector_available`, `failure_category` (or `None`),
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

### Requirement: Settings-driven factory resolves the shared recognizer boundary

The system SHALL expose a `get_product_recognizer(settings:
Settings) -> ProductRecognizerProtocol` factory in
`backend/services/product_recognition_factory.py`. The factory
SHALL:

1. Construct a `FuzzyProductRecognizer` instance.
2. When `settings.product_recognizer_mode == "fuzzy"`, return the
   fuzzy recognizer unchanged.
3. When `settings.product_recognizer_mode == "shadow"`, return a
   `ShadowedProductRecognizer` that wraps the fuzzy recognizer and
   delegates comparison to a `ProductRecognitionShadowService`
   constructed from the same settings and an injected
   `ShadowMetricsRecorder` instance.

`backend/intents/orchestration/agregar_producto_orchestrator.py`
SHALL resolve its module-level `_product_recognizer` through
`get_product_recognizer(load_settings())` once at module import
time and SHALL continue to re-export `detectar_productos =
_product_recognizer.recognize` as the shared product-recognition
boundary used by the `agregar_producto`, `quitar_producto`, and
`modificar_producto` orchestrators.

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

#### Scenario: Orchestrator binding uses the factory

- **WHEN** the orchestrator module is imported
- **THEN** `_product_recognizer` is the result of
  `get_product_recognizer(load_settings())`
- **AND** `detectar_productos = _product_recognizer.recognize` is
  re-exported from the orchestrator module

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
