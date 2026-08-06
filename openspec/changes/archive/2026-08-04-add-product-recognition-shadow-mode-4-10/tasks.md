## 1. Settings — mode, top-k, and min score gap

- [x] 1.1 Add `product_recognizer_mode: Literal["fuzzy", "shadow"]`,
  `shadow_vector_top_k: int`, and `shadow_hybrid_min_score_gap:
  float` to `backend/config/settings.py` with defaults `"fuzzy"`,
  `5`, and `0.05`. Validate at `Settings.load()` time: invalid
  mode raises `InvalidProductRecognizerMode(ValueError)`,
  non-positive top-k raises `InvalidShadowVectorTopK(ValueError)`,
  and `shadow_hybrid_min_score_gap` outside `[0.0, 1.0]` (or
  `NaN`) raises `InvalidShadowHybridMinScoreGap(ValueError)`.
  Document `shadow_hybrid_min_score_gap` as provisional and
  non-authoritative in code comments. Re-export all three
  exception classes from `backend/services/exceptions.py`.
- [x] 1.2 Add focused settings tests in
  `backend/tests/test_settings_product_recognizer_mode.py` covering:
  default mode is fuzzy; valid shadow override is accepted; invalid
  mode is rejected at load time; default top-k is 5; valid top-k
  override is accepted; zero top-k is rejected at load time;
  negative top-k is rejected at load time; default
  `shadow_hybrid_min_score_gap` is `0.05`; valid
  `shadow_hybrid_min_score_gap` overrides (0.0, 0.1, 1.0) are
  accepted; negative `shadow_hybrid_min_score_gap` is rejected
  at load time; above-one `shadow_hybrid_min_score_gap` is
  rejected at load time; `NaN` `shadow_hybrid_min_score_gap`
  is rejected at load time.

## 2. Comparison dataclass and recorder

- [x] 2.1 Create
  `backend/services/product_recognition_shadow_comparison.py` with
  the frozen `ProductRecognitionShadowComparison` dataclass
  (eleven fields: `fuzzy_best_id`, `vector_best_id`,
  `fuzzy_candidate_ids`, `vector_candidate_ids`,
  `fuzzy_candidate_scores`, `vector_candidate_scores`,
  `agreement`, `fuzzy_latency_ms`, `embedding_latency_ms`,
  `vector_latency_ms`, `vector_available`) and the frozen
  `ProductRecognitionHybridObservation` dataclass (twelve
  fields: `hybrid_candidate_ranking`, `hybrid_combined_scores`,
  `hybrid_top1_top2_gap`, `exact_canonical_match`,
  `exact_alias_match`, `decision`, `fuzzy_weight`,
  `vector_weight`, `unique_threshold`, `ambiguous_threshold`,
  `min_score_gap`, `non_authoritative`). Re-export both dataclasses
  from `backend/services/__init__.py`. Confirm the module exposes
  no other public symbol and no Pydantic / SQLAlchemy / FastAPI
  imports.
- [x] 2.2 Create `backend/services/shadow_metrics_recorder.py` with
  `ShadowMetricsRecorder` exposing `record(comparison, *,
  hybrid_observation, id_comercio, intent, correlation_id) -> None`.
  The recorder emits exactly one structured log record per call
  through the standard `logging` mechanism
  (`logging.getLogger(__name__).info(..., extra={...})`) carrying
  the documented safe operational fields, including the
  observational hybrid ranking (`hybrid_candidate_ranking`,
  `hybrid_combined_scores`, `hybrid_top1_top2_gap`,
  `exact_canonical_match`, `exact_alias_match`, `hybrid_decision`,
  the four provisional weights and thresholds, the provisional
  `hybrid_min_score_gap`, and `hybrid_non_authoritative=True`).
  The module MUST NOT import FastAPI, HTTP, the embedding client
  module, the vector search service module, the sync service, the
  admin router, or any persistence model.
- [x] 2.3 Add `backend/tests/test_shadow_metrics_recorder.py` with
  focused tests covering: recorder logs the documented safe
  operational fields including the observational hybrid ranking;
  recorder skips when the comparison is unavailable by emitting
  `failure_category="unknown"`; recorder is module-boundary clean
  (no FastAPI / HTTP / persistence imports); recorder marks
  provisional weights and thresholds as non-authoritative with
  `hybrid_non_authoritative=True`; recorder does not log the
  customer message, the raw vector, the embedding prompt, or a
  stack trace.

## 3. Shadow service — comparison and exception handling

- [x] 3.1 Create
  `backend/services/product_recognition_shadow_service.py` with
  `ProductRecognitionShadowService`. Constructor:
  `__init__(self, *, embedding_client: EmbeddingClientProtocol,
  vector_search_service: ProductPresentationVectorSearchService,
  settings: Settings, fuzzy_weight: float = 0.5, vector_weight:
  float = 0.5, unique_threshold: float = 0.7, ambiguous_threshold:
  float = 0.4, min_score_gap: float | None = None, clock:
  Callable[[], float] = time.monotonic)`. The service SHALL NOT
  hold a fuzzy recognizer. When `min_score_gap` is `None`, the
  service reads `settings.shadow_hybrid_min_score_gap`; otherwise
  the explicit value is used. The service exposes a single
  `compare(text: str, catalog: list[dict], fuzzy_result:
  ProductRecognizerResult, fuzzy_latency_ms: float, id_comercio: int)
  -> tuple[ProductRecognitionShadowComparison,
  ProductRecognitionHybridObservation]` method. Internally:
  consume the caller-supplied `fuzzy_result` and `fuzzy_latency_ms`
  (never re-invoke the fuzzy recognizer), attempt the embedding
  pipeline, attempt the vector pipeline, populate the comparison
  (with `fuzzy_candidate_scores` and `vector_candidate_scores`),
  compute the observational hybrid observation with the
  provisional weights and thresholds (including `min_score_gap`),
  and return the `(comparison, hybrid_observation)` tuple. Wrap
  the embedding and vector steps in `try / except Exception`;
  never raise a semantic exception to the caller. The module MUST
  NOT import FastAPI, HTTP, the embedding client concrete class,
  the fuzzy recognizer module, the document builder, the seeder,
  the indexer, the sync service, or any router.
- [x] 3.2 Add the `ShadowedProductRecognizer` decorator class in
  the same module. Constructor:
  `__init__(self, *, inner: ProductRecognizerProtocol, shadow:
  ProductRecognitionShadowService, recorder:
  ShadowMetricsRecorder, commerce_id_resolver: Callable[[list[dict]],
  int | None] | None = None)`. The decorator exposes
  `recognize(text: str, catalog: list[dict]) ->
  ProductRecognizerResult`. It invokes the inner recognizer
  **exactly once**, measures the fuzzy latency, resolves the
  commerce id through the injected callable (skipping shadow work
  when the resolver is `None` or returns `None`), delegates to
  `shadow.compare(text, catalog, fuzzy_result, fuzzy_latency_ms,
  id_comercio)`, hands the comparison and the hybrid observation to
  `recorder.record`, and returns the inner recognizer result
  unchanged.
- [x] 3.3 Add a `Protocol` for the embedding client in
  `backend/services/product_recognition_shadow_service.py` (or in
  `backend/embeddings/embedding_client_protocol.py` if the project
  already has one) describing `embed_query(text: str) -> list[float]`.
  Confirm the shadow service depends on the Protocol only.
- [x] 3.4 Re-export `ProductRecognitionShadowService`,
  `ShadowedProductRecognizer`, and the embedding client Protocol
  from `backend/services/__init__.py`.

## 4. Settings-driven factory

- [x] 4.1 Create
  `backend/services/product_recognition_factory.py` with
  `get_product_recognizer(settings: Settings) ->
  ProductRecognizerProtocol`. The function constructs a
  `FuzzyProductRecognizer`, returns it directly when
  `settings.product_recognizer_mode == "fuzzy"`, and returns a
  `ShadowedProductRecognizer` when `settings.product_recognizer_mode
  == "shadow"`. The factory MUST accept an injected recorder
  (default `ShadowMetricsRecorder()`) so tests can swap it.
- [x] 4.2 Add `backend/tests/test_product_recognition_factory.py`
  covering: fuzzy mode resolves to a `FuzzyProductRecognizer`;
  shadow mode resolves to a `ShadowedProductRecognizer` whose inner
  recognizer is a `FuzzyProductRecognizer`; the factory honors an
  injected recorder.

## 5. Orchestrator binding

- [x] 5.1 Replace the module-level `_product_recognizer:
  ProductRecognizerProtocol = FuzzyProductRecognizer()` in
  `backend/intents/orchestration/agregar_producto_orchestrator.py`
  with
  `_product_recognizer = get_product_recognizer(load_settings())`.
  Keep the `detectar_productos = _product_recognizer.recognize`
  re-export. Confirm no other handler, resolver, or
  intent-orchestration module imports
  `ShadowedProductRecognizer`, `ProductRecognitionShadowService`,
  `get_product_recognizer`, `ShadowMetricsRecorder`, or
  `ProductRecognitionShadowComparison`.
- [x] 5.2 Re-run the existing
  `agregar_producto` / `quitar_producto` / `modificar_producto`
  flow tests to confirm the byte-for-byte fuzzy equivalence
  contract is preserved.

## 6. Focused tests — shadow service and integration

- [x] 6.1 Add
  `backend/tests/test_product_recognition_shadow_service.py` with
  focused tests covering the 15 minimum scenarios from the project
  playbook plus the validation-order tests:
  1. fuzzy mode does not call embedding or vector search
     (verified by injecting fake collaborators and asserting no
     call);
  2. shadow mode returns the exact fuzzy result (the inner
     recognizer is the only thing the caller sees);
  3. matching top result records `same_top1`;
  4. different top result records `different`;
  5. matching candidate sets with reordered tops record
     `same_candidate_set`;
  6. fuzzy-only result is classified correctly;
  7. vector-only result is classified correctly;
  8. no-result case is classified correctly;
  9. commerce isolation is preserved (the shadow service passes
     `id_comercio` to the vector search service and the vector
     search service returns only matching candidates);
  10. embedding failure does not affect fuzzy output
     (`vector_available=False`, `agreement="fuzzy_only"` or
     `"no_result"` as appropriate, no exception raised);
  11. vector-search failure does not affect fuzzy output
     (`vector_available=False`, `agreement="fuzzy_only"` or
     `"no_result"` as appropriate, no exception raised);
  12. safe metrics contain no message text or vectors (the
     recorder does not see the customer message or the raw
     `query_embedding`);
  13. component latencies are recorded (the fuzzy latency comes
     from the caller-supplied `fuzzy_latency_ms`; the embedding
     and vector latencies are non-negative finite `float` values
     measuring their respective steps);
  14. add/remove/modify product flows remain unchanged (re-run
     the existing `agregar_producto` / `quitar_producto` /
     `modificar_producto` flow tests against the orchestrator
     with `product_recognizer_mode="shadow"` and confirm byte-for-
     byte equivalence);
  15. existing 4.5–4.9 focused tests remain green (re-run them).
  Additional scenarios:
  - validation-order: matching fuzzy and vector with empty
    candidate sets records `"no_result"` even when the embedding
    client returned a valid vector;
  - no-retry: an embedding exception is NOT followed by a second
    `embed_query` call;
  - normalizer-reuse: `compare` invokes
    `backend.recognizers.product_recognizer._normalizar_texto` on
    the input text before calling the embedding client.
  Observational hybrid ranking tests:
  - fuzzy-once invariant: the inner recognizer is invoked
    exactly once per `ShadowedProductRecognizer.recognize` call,
    and the shadow service `compare` method does NOT invoke the
    fuzzy recognizer (verified via spy fakes).
  - `fuzzy_candidate_scores` are aligned with
    `fuzzy_candidate_ids` in encounter order, non-increasing in
    `[0.0, 1.0]`, with the top entry equal to `1.0`.
  - `vector_candidate_scores` are aligned with
    `vector_candidate_ids` in match order, populated from
    `ProductPresentationVectorMatch.score`.
  - hybrid observation carries the ordered hybrid ranking,
    observational combined scores, top-1/top-2 gap, exact
    canonical / exact alias flags, the provisional
    `min_score_gap`, and a `decision` of `unique`, `ambiguous`,
    or `unknown`.
  - decision order is exact canonical → exact alias → vector
    signal → fuzzy complementary signal.
  - provisional weights, thresholds, and `min_score_gap` are
    recorded as non-authoritative (`non_authoritative=True` on
    the observation, `hybrid_non_authoritative=True` on the log
    record).
  - the hybrid observation does NOT alter the fuzzy return
    value, the visible candidates, the pending context, the
    handlers, the responses, or any persistence.
  Gap-threshold tests (`shadow_hybrid_min_score_gap`):
  - clear gap → `unique`: when the top-1 score reaches
    `unique_threshold` and `hybrid_top1_top2_gap >=
    shadow_hybrid_min_score_gap`, the decision is `unique`.
  - insufficient gap → `ambiguous`: when the top-1 score reaches
    `unique_threshold` but `hybrid_top1_top2_gap <
    shadow_hybrid_min_score_gap`, the decision is `ambiguous`.
  - exact match remains `unique`: when `exact_canonical_match`
    or `exact_alias_match` is `True`, the decision is `unique`
    regardless of the gap.
  - one candidate can be `unique`: when the ranking has exactly
    one candidate and the top-1 score reaches
    `unique_threshold`, the decision is `unique`.
  - invalid setting values are rejected: `Settings.load()`
    raises `InvalidShadowHybridMinScoreGap` for negative,
    above-one, and `NaN` `shadow_hybrid_min_score_gap` values.
- [x] 6.2 Add
  `backend/tests/test_product_recognition_shadow_module_boundaries.py`
  covering: the shadow service does not import the embedding client
  concrete class, the document builder, the seeder, the indexer,
  the sync service, the admin router, or any 4.7 schema; the
  shadow service does not call `session.commit()`, `session.
  rollback()`, `session.close()`, or `session.begin()`; the
  shadowed recognizer does not mutate the inner recognizer's
  result; the comparison dataclass is frozen and exposes only the
  eleven documented fields; the hybrid observation dataclass is
  frozen and exposes only the twelve documented fields
  (including `min_score_gap`); the shadow service does NOT hold a
  fuzzy recognizer; the recorder does not log the customer
  message, the raw vector, the embedding prompt, or a stack
  trace; the recorder marks provisional weights, thresholds, and
  `min_score_gap` as non-authoritative.

## 7. Validation and final report

- [x] 7.1 Run `python -m compileall backend/services/
  product_recognition_shadow_comparison.py backend/services/
  product_recognition_shadow_service.py backend/services/
  shadow_metrics_recorder.py backend/services/
  product_recognition_factory.py backend/tests/
  test_product_recognition_shadow_service.py backend/tests/
  test_product_recognition_factory.py backend/tests/
  test_shadow_metrics_recorder.py backend/tests/
  test_settings_product_recognizer_mode.py backend/tests/
  test_product_recognition_shadow_module_boundaries.py` and
  confirm a clean exit.
- [x] 7.2 Run `ruff check backend/services/
  product_recognition_shadow_comparison.py backend/services/
  product_recognition_shadow_service.py backend/services/
  shadow_metrics_recorder.py backend/services/
  product_recognition_factory.py backend/intents/orchestration/
  agregar_producto_orchestrator.py backend/tests/
  test_product_recognition_shadow_service.py backend/tests/
  test_product_recognition_factory.py backend/tests/
  test_shadow_metrics_recorder.py backend/tests/
  test_settings_product_recognizer_mode.py backend/tests/
  test_product_recognition_shadow_module_boundaries.py` and fix
  any reported issues.
- [x] 7.3 Run `mypy --strict backend/services/
  product_recognition_shadow_comparison.py backend/services/
  product_recognition_shadow_service.py backend/services/
  shadow_metrics_recorder.py backend/services/
  product_recognition_factory.py` and fix any reported errors.
- [x] 7.4 Run the focused 4.10 test modules (including the
  observational hybrid ranking tests) and the existing
  4.5, 4.6, 4.7, 4.8, 4.9 focused test modules and the
  `agregar_producto` / `quitar_producto` / `modificar_producto`
  flow tests. Confirm: the new 4.10 tests pass; the 4.5–4.9 tests
  stay green; the add/remove/modify flow tests stay green in both
  modes; the fuzzy-once invariant holds.
- [x] 7.5 Run
  `openspec validate add-product-recognition-shadow-mode-4-10
  --strict` and confirm the change validates cleanly. The
  OpenSpec change identifier is
  `add-product-recognition-shadow-mode-4-10` (the kebab-case
  folder name is the single source of truth — no alternate
  identifier is accepted).
- [x] 7.6 Report files added, files touched, integration point,
  exact fuzzy result contract preserved, metrics recorded,
  failure categories, focused tests proposed, validation
  results, and any mismatch found in the real codebase.
