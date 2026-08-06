## Why

Subphases 4.5–4.9 produced a complete embedding pipeline: per-document
`producto_presentacion_embeddings` rows, a deterministic document
builder, a local Ollama embedding client, an indexer/seeder/admin
surface, a post-catalog-change synchronization service, and a
pgvector-backed similarity search service. The customer-message flow,
however, still runs only the legacy fuzzy recognizer, so the system
cannot answer the calibration questions that the next hybrid subphase
will need: how often does fuzzy agree with vector, how often does it
miss what vector would catch, and how often does vector hallucinate a
match that fuzzy would reject.

This subphase adds an opt-in **shadow mode** that runs the fuzzy and
semantic/vector recognizers in parallel and records comparison data,
without changing any customer response, intent payload, or order
mutation. Shadow mode is observational only — the fuzzy recognizer
remains the sole authoritative result. The comparison data is the
input the future calibration subphase needs to introduce weighted
fusion, thresholds, and active hybrid decisions.

## What Changes

- Add a new `Settings` field `product_recognizer_mode` accepting the
  literals `"fuzzy"` or `"shadow"`, defaulting to `"fuzzy"`. Add
  `shadow_vector_top_k` as a positive integer (`> 0`). Add
  `shadow_hybrid_min_score_gap` as a `float` in `[0.0, 1.0]`
  (default `0.05`), validated at `Settings.load()` time and
  explicitly marked as provisional and non-authoritative.
- Add `ProductRecognitionShadowService` in
  `backend/services/product_recognition_shadow_service.py` that
  composes the existing fuzzy recognizer, the existing
  `OllamaEmbeddingClient`, the existing
  `ProductPresentationVectorSearchService`, and a minimal structured
  recorder. The fuzzy recognizer is invoked **exactly once** per
  shadow-mode call: the `ShadowedProductRecognizer` decorator runs
  the inner fuzzy recognizer, measures the fuzzy latency, and then
  passes the already-computed fuzzy result and latency to the shadow
  service. The shadow service exposes a single
  `compare(text, catalog, fuzzy_result, fuzzy_latency_ms,
  id_comercio) -> tuple[ProductRecognitionShadowComparison,
  ProductRecognitionHybridObservation]` method that:
  - **does not invoke the fuzzy recognizer** — it consumes the
    result and the latency the decorator already measured;
  - when `product_recognizer_mode == "fuzzy"`, the decorator is
    never reached and the shadow service is never invoked;
  - when `product_recognizer_mode == "shadow"`, runs an embedding
    query through the injected embedding client, hands the resulting
    vector to the vector search service (using
    `settings.shadow_vector_top_k`), classifies the agreement,
    computes a strictly observational hybrid ranking with provisional
    weights and thresholds, and records safe metrics. The fuzzy
    result is returned unchanged in both modes; the hybrid
    observation is data only and never alters the fuzzy result, the
    visible candidates, the pending context, the handlers, the
    responses, or any persistence.
- Add a frozen dataclass
  `ProductRecognitionShadowComparison` carrying exactly:
  `fuzzy_best_id`, `vector_best_id`, `fuzzy_candidate_ids`,
  `vector_candidate_ids`, `fuzzy_candidate_scores`,
  `vector_candidate_scores`, `agreement`, `fuzzy_latency_ms`,
  `embedding_latency_ms`, `vector_latency_ms`, `vector_available`.
  `agreement` is one of `"same_top1"`, `"same_candidate_set"`,
  `"different"`, `"fuzzy_only"`, `"vector_only"`, `"no_result"`.
  `fuzzy_candidate_scores` is a tuple of normalized fuzzy
  scores (`float` in `[0.0, 1.0]`) aligned with
  `fuzzy_candidate_ids` in encounter order. `vector_candidate_scores`
  is a tuple of cosine similarity scores (`float` in `[0.0, 1.0]`)
  aligned with `vector_candidate_ids` in match order. The dataclass
  SHALL NOT carry the input text, the customer message, the
  raw vectors, the prompt, the source documents, or any database
  credential.
- Add a frozen dataclass `ProductRecognitionHybridObservation`
  carrying the strictly observational hybrid ranking data:
  `hybrid_candidate_ranking` (tuple of `producto_presentacion_id` in
  descending observational combined score),
  `hybrid_combined_scores` (tuple of `float` observational combined
  scores aligned with `hybrid_candidate_ranking`),
  `hybrid_top1_top2_gap` (`float` score gap between the top-1 and
  top-2 hybrid candidates; `0.0` when fewer than two candidates),
  `exact_canonical_match` (`bool` true when the normalized input
  text equals a catalog `producto_nombre` for a candidate),
  `exact_alias_match` (`bool` true when the normalized input text
  equals an applicable alias for a candidate),
  `decision` (one of `"unique"`, `"ambiguous"`, `"unknown"`),
  `fuzzy_weight`, `vector_weight`, `unique_threshold`,
  `ambiguous_threshold`, and `min_score_gap` (the **provisional**,
  non-authoritative weights and thresholds used to compute the
  combined score and the decision; they are recorded for
  measurement only and SHALL be marked `non_authoritative=True`
  semantics — the field naming makes the provisional nature
  explicit). `min_score_gap` is the `shadow_hybrid_min_score_gap`
  value used to gate the `unique` decision on the top-1/top-2 gap.
  The dataclass SHALL NOT carry the input text, the customer
  message, the raw vectors, the prompt, the source documents, or
  any database credential.
- The observational hybrid ranking decision order is fixed:
  `exact canonical` → `exact alias` → `vector signal` →
  `fuzzy complementary signal` → `unique` / `ambiguous` /
  `unknown`. The combined score is computed as
  `fuzzy_weight * fuzzy_score + vector_weight * vector_score`
  using the provisional weights above. The decision is `unique`
  when the top-1 candidate's combined score is `>= unique_threshold`
  AND the ranked candidate set either has exactly one candidate or
  the top-1/top-2 gap is `>= min_score_gap`; `ambiguous` when the
  ranking has more than one candidate and the top-1 combined score
  is `>= ambiguous_threshold`; otherwise `unknown`. Exact canonical
  and exact alias matches short-circuit the decision to `unique`
  when their respective flag is `True` and the matched candidate is
  in the hybrid ranking. The hybrid observation is **purely data**:
  it never modifies the fuzzy result, the visible candidates, the
  pending context, the handlers, the responses, or any persistence.
  The provisional weights and thresholds (including
  `min_score_gap`) are configurable for later calibration in
  Subphase 4.11 and are explicitly **non-authoritative** in this
  subphase: no active hybrid mode, no final calibrated thresholds,
  and no fuzzy fallback switching are introduced here.
- Add a minimal `ShadowMetricsRecorder` that emits structured log
  records through the existing `logging` mechanism. Only safe
  operational fields are recorded (commerce id, intent / operation
  type, hashed correlation identifier, top ids, candidate counts,
  candidate score tuples, agreement classification, the observational
  hybrid ranking, the observational hybrid decision, the top-1/top-2
  gap, the exact canonical / exact alias flags, the provisional
  weights and thresholds (including `min_score_gap`) marked as
  non-authoritative, component latencies, semantic-path availability,
  sanitized failure category). No full customer message, no vector
  values, no prompts, no source documents, no stack traces, no raw
  infrastructure exception text.
- Replace the module-level `_product_recognizer` binding in
  `backend/intents/orchestration/agregar_producto_orchestrator.py`
  with a single
  `get_product_recognizer(settings: Settings) -> ProductRecognizerProtocol`
  factory that returns a `FuzzyProductRecognizer` when
  `product_recognizer_mode == "fuzzy"` and a new
  `ShadowedProductRecognizer` decorator when
  `product_recognizer_mode == "shadow"`. The `ShadowedProductRecognizer`
  decorator invokes the inner fuzzy recognizer **exactly once**, times
  the fuzzy call, and forwards the already-computed fuzzy result and
  latency to the shadow service. The shadow service never invokes the
  fuzzy recognizer. The orchestrator's `detectar_productos` re-exports
  the bound recognizer's `recognize` method. The returned fuzzy result
  shape is byte-for-byte equivalent to the existing recognizer output.
- Add new domain exceptions
  `ShadowComparisonUnavailable(RuntimeError)` (raised only by the
  recorder-internal path; never surfaced to callers) and
  `InvalidProductRecognizerMode(ValueError)` /
  `InvalidShadowVectorTopK(ValueError)` /
  `InvalidShadowHybridMinScoreGap(ValueError)` for the new settings
  validators.
- Add focused tests covering the 15 minimum scenarios from the project
  playbook: `fuzzy` mode is a no-op for embedding/vector; `shadow`
  mode returns the exact fuzzy result; matching top results
  classify as `same_top1`; matching candidate sets classify as
  `same_candidate_set`; mismatched top results classify as
  `different`; fuzzy-only / vector-only / no-result are classified
  correctly; commerce isolation is preserved; embedding failure does
  not affect fuzzy output; vector-search failure does not affect fuzzy
  output; recorded metrics carry no message text and no vectors;
  component latencies are recorded; the `agregar_producto`,
  `quitar_producto`, and `modificar_producto` orchestrators remain
  byte-for-byte equivalent in both modes; the existing 4.5–4.9
  focused tests stay green. Plus observational-hybrid tests:
  the fuzzy recognizer is invoked exactly once per `shadow` call;
  the comparison dataclass carries `fuzzy_candidate_scores` and
  `vector_candidate_scores` aligned with the candidate id tuples;
  the hybrid observation carries an ordered hybrid ranking,
  observational combined scores, top-1/top-2 gap, `exact_canonical_match`
  and `exact_alias_match` flags, the provisional `min_score_gap`
  threshold, and a `decision` of `unique`, `ambiguous`, or
  `unknown`; the decision order is exact canonical → exact alias →
  vector signal → fuzzy complementary signal; the observational
  hybrid ranking never alters the fuzzy return value, the visible
  candidates, the pending context, the handlers, the responses, or
  any persistence; the hybrid weights and thresholds are recorded
  as non-authoritative provisional values. Plus gap-threshold tests:
  a clear top-1/top-2 gap classifies as `unique`; an insufficient
  gap classifies as `ambiguous`; an exact canonical or exact alias
  match remains `unique` regardless of the gap; a single
  candidate can be `unique` when the top-1 score reaches
  `unique_threshold`; invalid `shadow_hybrid_min_score_gap` values
  (outside `[0.0, 1.0]`) are rejected at `Settings.load()` time.
- No changes to `backend/recognizers/product_recognizer.py`,
  `backend/recognizers/fuzzy_product_recognizer.py`,
  `backend/recognizers/product_recognizer_contract.py`, the
  `ProductoPresentacionEmbeddingSearchRepository`, the
  `ProductPresentationVectorSearchService`, the embedding client, the
  document builder, the seeder, the indexer, the sync service, or any
  4.6 / 4.7 / 4.8 surface.

## Capabilities

### New Capabilities

- `product-recognition-shadow-mode`: opt-in parallel execution of the
  fuzzy and semantic/vector product recognizers with safe comparison
  metrics, no customer-facing effect, and a single settings-driven
  mode switch (`product_recognizer_mode`).

### Modified Capabilities

- `product-recognizer`: the existing `ProductRecognizerProtocol`
  contract is preserved unchanged. The integration surface at
  `backend/intents/orchestration/agregar_producto_orchestrator.py`
  becomes a settings-driven factory that resolves to either the
  current fuzzy recognizer or a `ShadowedProductRecognizer` decorator
  that delegates to fuzzy and records shadow data. The fuzzy result
  contract observed by `agregar_producto`, `quitar_producto`, and
  `modificar_producto` orchestrators is unchanged.

## Impact

- New code:
  - `backend/services/product_recognition_shadow_service.py`
    (`ProductRecognitionShadowService`,
    `ShadowedProductRecognizer`)
  - `backend/services/product_recognition_shadow_comparison.py`
    (frozen comparison dataclass + `Agreement` literal)
  - `backend/services/shadow_metrics_recorder.py`
    (structured-log recorder; no FastAPI, no DB, no HTTP)
  - `backend/services/product_recognition_factory.py`
    (settings-driven `get_product_recognizer`)
  - `backend/tests/test_product_recognition_shadow_service.py`
  - `backend/tests/test_product_recognition_factory.py`
  - `backend/tests/test_shadow_metrics_recorder.py`
- Touched code:
  - `backend/config/settings.py` — three new settings
    (`product_recognizer_mode`, `shadow_vector_top_k`,
    `shadow_hybrid_min_score_gap`) with validators and a derived
    `embedding_query_text` normalization helper that reuses the
    existing `recognizers.product_recognizer._normalizar_texto` to
    keep a single normalization contract. `shadow_hybrid_min_score_gap`
    is validated to be a `float` in `[0.0, 1.0]` and is
    explicitly marked as provisional and non-authoritative.
  - `backend/intents/orchestration/agregar_producto_orchestrator.py`
    — replace the module-level `_product_recognizer` binding with a
    `get_product_recognizer(settings)` factory; keep
    `detectar_productos = _product_recognizer.recognize` as the
    shared boundary.
  - `backend/services/exceptions.py` — add
    `ShadowComparisonUnavailable`, `InvalidProductRecognizerMode`,
    `InvalidShadowVectorTopK`, `InvalidShadowHybridMinScoreGap`.
- No changes to: `backend/models/*`, `backend/alembic/*`,
  `backend/embeddings/*` (document builder, indexer, seeder, sync),
  `backend/routers/admin_product_embeddings.py`, the
  `OllamaEmbeddingClient`, the `ProductPresentationVectorSearchService`
  / search repository, the fuzzy recognizer module, the contract
  TypedDicts, or any handler / resolver / orchestrator / processor
  beyond the single orchestrator binding.
- No new dependencies. The existing `OllamaEmbeddingClient`,
  `ProductPresentationVectorSearchService`, and `logging` mechanism
  cover all collaborators.
- No migration. No schema change. No new HTTP endpoint. No router
  changes. No CLI surface.
- No customer-facing effect. The fuzzy result returned to the
  `agregar_producto`, `quitar_producto`, and `modificar_producto`
  flows is byte-for-byte equivalent in both modes.
