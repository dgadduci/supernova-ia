## Context

Subphases 4.5–4.9 produced a complete embedding pipeline:

- 4.5 — `ProductEmbeddingDocumentBuilder` produces deterministic
  semantic documents with content hashes.
- 4.6 — `ProductoPresentacionEmbeddingIndexer` /
  `ProductoPresentacionEmbeddingSeeder` persist embeddings into
  `producto_presentacion_embeddings`; the `OllamaEmbeddingClient`
  talks to the local Ollama service.
- 4.7 — `ProductoPresentacionEmbeddingAdminService` and
  `POST /admin/comercios/{comercio_id}/product-embeddings/reindex`
  expose the local admin reindex surface.
- 4.8 — `CatalogEmbeddingSynchronizationService` reindexes the
  narrowest valid embedding scope after catalog mutations.
- 4.9 — `ProductPresentationVectorSearchService` performs
  pgvector-backed similarity search with strict validation order
  (`top_k` first, dimension second, empty candidates last) and a
  frozen typed result (`ProductPresentationVectorMatch`).

The recognizer boundary at
`backend/intents/orchestration/agregar_producto_orchestrator.py`
holds a module-level `_product_recognizer: ProductRecognizerProtocol
= FuzzyProductRecognizer()` and re-exports
`detectar_productos = _product_recognizer.recognize`. The same
`detectar_productos` symbol is consumed by the `agregar_producto`,
`quitar_producto`, and `modificar_producto` orchestrators, and any
future flow that needs the shared product-recognition boundary. The
fuzzy result contract is `ProductRecognizerResult` (the existing
`encontrados` / `encontrados_posibles` /
`encontrados_no_disponibles` / `no_encontrados` TypedDict from
`backend/recognizers/product_recognizer_contract.py`).

The system now needs the calibration data that future hybrid routing
will rely on: agreement between fuzzy and vector, fuzzy-only /
vector-only outcomes, and component latencies. The customer-facing
behaviour, the fuzzy result shape, and the embedding/vector
infrastructure must stay exactly as they are. Subphase 4.10 is the
observational layer that runs them in parallel and records the
comparison safely, without changing any payload that reaches a
handler.

## Goals / Non-Goals

**Goals:**

- Add `Settings.product_recognizer_mode` (`"fuzzy"` or `"shadow"`,
  default `"fuzzy"`), `Settings.shadow_vector_top_k`
  (`int > 0`), and `Settings.shadow_hybrid_min_score_gap`
  (`float` in `[0.0, 1.0]`, default `0.05`, validated at
  `Settings.load()` time and explicitly marked as provisional
  and non-authoritative).
- Add `ProductRecognitionShadowService` that, when invoked in shadow
  mode, runs fuzzy and semantic/vector recognition in parallel,
  returns the exact fuzzy result, and records a frozen
  `ProductRecognitionShadowComparison` through a minimal structured
  recorder. In fuzzy mode the service returns the fuzzy result
  without invoking the embedding client or the vector search
  service.
- Replace the module-level recognizer binding in
  `agregar_producto_orchestrator.py` with a settings-driven factory
  so the shared boundary becomes mode-aware.
- Reuse the existing fuzzy recognizer, `OllamaEmbeddingClient`,
  `ProductPresentationVectorSearchService`, commerce isolation,
  fuzzy result shape, and product-presentation identifiers. Do not
  duplicate fuzzy normalization, embedding transport, vector SQL, or
  document-building logic.
- Record only safe operational data — commerce id, intent /
  operation type when available, normalized or hashed correlation
  identifier, fuzzy top result, vector top result, agreement
  classification, candidate counts, component latencies,
  semantic-path availability, sanitized failure category. Never log
  the customer message, vectors, prompts, source documents, database
  credentials, stack traces, or raw infrastructure exception text.
- Fail closed on the semantic path: if embedding generation or
  vector search fails, the fuzzy result is returned unchanged, the
  comparison is marked `vector_available=False`, and the failure
  category is recorded. Never raise a semantic exception to the
  product-recognition caller.
- Reuse the existing `backend.recognizers.product_recognizer._normalizar_texto`
  helper for query embedding normalization so the recognizer and the
  embedding path share one normalization contract.
- Add focused tests covering the 15 minimum scenarios from the
  project playbook.

**Non-Goals:**

- Weighted fuzzy / vector score fusion, confirmation thresholds,
  score-gap rules, fallback switching, active hybrid decisions, or
  any customer-facing semantic result. Calibration belongs to a
  later subphase.
- Catalog mutations, embedding synchronization changes, HNSW /
  IVFFlat, background jobs, dashboards, monitoring platforms, or
  new external dependencies.
- Subphase 4.11 or later work. Correction of unrelated `api_smoke`
  debt.
- New HTTP endpoints, routers, CLI surface, or handler / resolver /
  orchestrator rewrites.
- Any change to the fuzzy recognizer module, the fuzzy result
  contract, the embedding client, the document builder, the
  indexer, the seeder, the admin surface, the sync service, or the
  vector search service.

## Decisions

### Decision 1 — Single shared recognition boundary: settings-driven factory

The recognizer binding is already a single module-level symbol
(`_product_recognizer`) inside
`backend/intents/orchestration/agregar_producto_orchestrator.py`,
re-exported as `detectar_productos`. The cleanest place to introduce
mode awareness is to keep that symbol and have it resolve through a
factory:

```python
def get_product_recognizer(settings: Settings) -> ProductRecognizerProtocol:
    fuzzy = FuzzyProductRecognizer()
    if settings.product_recognizer_mode == "fuzzy":
        return fuzzy
    return ShadowedProductRecognizer(
        inner=fuzzy,
        shadow=build_shadow_service(settings),
        recorder=build_shadow_recorder(),
    )

_product_recognizer = get_product_recognizer(load_settings())
detectar_productos = _product_recognizer.recognize
```

Alternative considered: dispatching in every orchestrator that uses
`detectar_productos`. Rejected because the playbook calls out the
"shared product-recognition boundary" explicitly and we already have
exactly one binding point to swap.

Alternative considered: introducing a FastAPI dependency. Rejected
because the playbook says "no FastAPI dependency inside the shadow
service" and the integration happens at the orchestrator layer
where there is no FastAPI dependency anyway.

### Decision 2 — `ShadowedProductRecognizer` is a thin decorator, not a subclass

`ShadowedProductRecognizer` implements `ProductRecognizerProtocol`
with `recognize(text, catalog) -> ProductRecognizerResult`. It calls
`inner.recognize(text, catalog)` first, captures the result and the
fuzzy latency, then asks the injected shadow service for a
comparison, records it, and returns the inner result unchanged. The
decorator pattern keeps the public surface (`recognize(text,
catalog)`) byte-for-byte compatible with `FuzzyProductRecognizer`.

Alternative considered: subclassing `FuzzyProductRecognizer`. Rejected
because the decorator makes the wrapping explicit and lets us inject
fakes for the inner recognizer, the shadow service, and the recorder
independently — which the project playbook's testability rule calls
out ("use constructor/factory injection for test fakes").

### Decision 3 — `ProductRecognitionShadowService` owns parallel execution and never raises semantic exceptions to the caller

The shadow service exposes a single
`compare(text, catalog, fuzzy_result, fuzzy_latency_ms, id_comercio)
-> tuple[ProductRecognitionShadowComparison,
ProductRecognitionHybridObservation]`
method. The fuzzy recognizer is invoked **exactly once** per shadow
request: the `ShadowedProductRecognizer` decorator runs the inner
fuzzy recognizer, measures its latency, and forwards the
already-computed result and latency to the shadow service. The
shadow service does not accept a fuzzy recognizer at all and does
not invoke any fuzzy recognizer.

Inside `compare`:

1. Consume the caller-supplied `fuzzy_result` and
   `fuzzy_latency_ms` directly; never re-invoke the fuzzy
   recognizer.
2. Compute the comparison using a `try / except` over the embedding
   + vector pipeline.
3. If embedding generation raises any exception (transport, timeout,
   validation, dimension mismatch, model mismatch), classify the
   failure category (`embedding_failure`), mark
   `vector_available=False`, set `vector_best_id=None`,
   `vector_candidate_ids=()`, `vector_candidate_scores=()`, and
   `embedding_latency_ms` / `vector_latency_ms` to the elapsed time
   up to the failure.
4. If the vector search service raises any exception
   (`InvalidVectorSearchTopK`, `InvalidVectorSearchDimension`, or a
   `SQLAlchemyError`), classify the failure category
   (`vector_failure`), mark `vector_available=False`, and continue.
5. If the embedding client or the vector search service returns
   normally, populate the vector fields and mark
   `vector_available=True`.
6. Build the frozen comparison (with matched candidate score
   tuples) and the strictly observational hybrid observation, and
   return both. Never raise the semantic exception to the
   product-recognition caller.

This satisfies the playbook rule "if embedding generation or vector
search fails, return the fuzzy result normally, mark the semantic
path unavailable, record a sanitized failure category, do not raise
the semantic exception to the product-recognition caller, do not
retry automatically, do not write embedding failure status from this
read-only path" and satisfies the corrected invariant **the fuzzy
recognizer SHALL be invoked exactly once per shadow call**.

Alternative considered: re-using the existing
`ProductPresentationVectorSearchService` validation order and
re-raising `InvalidVectorSearchDimension` /
`InvalidVectorSearchTopK` to the caller. Rejected because the
playbook says the fuzzy path must remain unaffected and the semantic
exceptions must not propagate.

Alternative considered: the shadow service holding a fuzzy
recognizer and re-running it. Rejected because that doubles the
fuzzy cost and breaks the "exactly once" invariant; the shadow
service consumes the decorator's already-computed result and
latency.

### Decision 4 — Comparison dataclass is a frozen `dataclass` with explicit fields

`ProductRecognitionShadowComparison` is a frozen dataclass with
eleven fields: `fuzzy_best_id: int | None`,
`vector_best_id: int | None`,
`fuzzy_candidate_ids: tuple[int, ...]`,
`vector_candidate_ids: tuple[int, ...]`,
`fuzzy_candidate_scores: tuple[float, ...]` (normalized fuzzy
scores in `[0.0, 1.0]`, aligned with `fuzzy_candidate_ids`),
`vector_candidate_scores: tuple[float, ...]` (cosine similarity
scores in `[0.0, 1.0]`, aligned with `vector_candidate_ids`),
`agreement: str`,
`fuzzy_latency_ms: float`,
`embedding_latency_ms: float`,
`vector_latency_ms: float`,
`vector_available: bool`. No `text`, no `query_embedding`, no
`prompt`, no source documents, no correlation raw value. Tuples
instead of lists keep the dataclass hashable and frozen without
extra ceremony.

`fuzzy_candidate_scores` is populated per fuzzy candidate. The
top fuzzy candidate (`fuzzy_best_id`) receives the highest score
(`1.0`); subsequent fuzzy candidates receive descending
confidence proxies aligned with the encounter order in the fuzzy
result. The exact mapping is documented in the implementation but
the invariant is: the score is non-increasing in encounter order,
the top entry equals `1.0` when the fuzzy side produced any
candidate, and the tuple is empty when the fuzzy side produced no
candidates. `vector_candidate_scores` is populated directly from
`ProductPresentationVectorMatch.score` (already a cosine similarity
in `[0.0, 1.0]`).

The `agreement` value is computed in this exact order:

- `"no_result"` when both fuzzy and vector candidate lists are empty.
- `"same_top1"` when fuzzy and vector best ids are equal and both are
  non-`None`.
- `"same_candidate_set"` when the fuzzy candidate id sets equal the
  vector candidate id sets and the top-1 ids do not match (i.e.
  re-ranking with the same set).
- `"different"` when both sides returned non-empty candidate sets and
  the top ids differ but the candidate sets overlap or are non-equal.
- `"fuzzy_only"` when the fuzzy side returned a non-empty candidate
  set and the vector side returned an empty list (or
  `vector_available=False`).
- `"vector_only"` when the vector side returned a non-empty candidate
  set and the fuzzy side returned an empty list.

The order is fixed so the comparison is deterministic.

Alternative considered: a Pydantic model. Rejected because the
playbook keeps the result internal and a frozen dataclass keeps the
immutability and the no-Pydantic-ceremony property aligned with the
4.9 `ProductPresentationVectorMatch` precedent.

### Decision 5 — Recorder is a thin wrapper over `logging`, not a new framework

`ShadowMetricsRecorder` exposes a single
`record(comparison: ProductRecognitionShadowComparison, *,
id_comercio: int, intent: str | None, correlation_id: str) -> None`
method that emits one structured log record through the standard
`logging` mechanism (`logging.getLogger(__name__).info(...)` with
`extra={...}`). The fields included are the safe operational
fields from the playbook. The correlation id is expected to be a
short, normalized or pre-hashed value supplied by the caller; the
recorder never hashes or logs the raw customer message.

No monitoring platform, no dashboard, no metrics framework, no event
bus, no telemetry SDK. The smallest existing logging mechanism is
the standard `logging` module already used throughout the project.

Alternative considered: a Prometheus client or a custom metrics
framework. Rejected because the playbook says "use the smallest
existing logging mechanism. Do not add a monitoring platform,
dashboard, or new external dependency".

### Decision 6 — Settings validation lives in `Settings`, not in the shadow service

`product_recognizer_mode` accepts only `"fuzzy"` or `"shadow"`
(default `"fuzzy"`) and `shadow_vector_top_k` accepts only positive
integers (default `5`). Validators run in `Settings` and raise
`InvalidProductRecognizerMode` / `InvalidShadowVectorTopK` only when
the env var or default value is invalid. The shadow service trusts
the settings and never re-validates.

This matches the existing project pattern (4.4 introduced positive
integer validators on `embedding_timeout_seconds`,
`embedding_batch_size`, `embedding_dimension`).

Alternative considered: validating inside the shadow service.
Rejected because `Settings.load()` is the single boundary the
project uses for env-driven configuration and re-validation would
duplicate the logic.

### Decision 7 — Embedding query text reuses the existing recognizer normalization

The shadow service builds the embedding query by calling the
existing private helper `backend.recognizers.product_recognizer._normalizar_texto`
on `text`. The 4.5 spec explicitly required
`ProductEmbeddingDocumentBuilder.normalize_for_embedding` to be
byte-equivalent to the recognizer's `_normalizar_texto`. Shadow mode
reuses the recognizer's helper directly, so the embedding query text
stays in lockstep with the document text the embeddings were built
from. There is no second normalization helper.

Alternative considered: re-implementing normalization inside the
shadow service. Rejected because the project playbook forbids
duplicating fuzzy normalization.

### Decision 8 — Integration is limited to the shared boundary; handlers stay untouched

`ShadowedProductRecognizer.recognize` is plugged into the single
shared boundary at
`agregar_producto_orchestrator.py:detectar_productos`. The
`agregar_producto`, `quitar_producto`, and `modificar_producto`
orchestrators continue to import `detectar_productos` and the
`ProductRecognizerProtocol` is preserved. No handler, resolver, or
intent-orchestration code path is modified.

This satisfies the playbook rule "integrate shadow execution only
at the shared product-recognition boundary used by: agregar_producto,
quitar_producto, modificar_producto, consultar_producto (if it
already uses that same boundary). Do not rewrite handlers or the
intent interpreter. The result returned to these flows must be
byte-for-byte or structurally equivalent to the existing fuzzy
result."

Alternative considered: instrumenting every handler with shadow
calls. Rejected because the playbook calls out exactly one
integration point and explicitly forbids rewriting handlers.

### Decision 9 — Observational hybrid ranking is purely data, never authoritative

The shadow service produces a frozen
`ProductRecognitionHybridObservation` alongside the comparison
dataclass. The hybrid observation is **observational only**: it is
recorded for measurement and later calibration in Subphase 4.11 and
**never** writes back to the fuzzy result, mutates candidates,
touches pending contexts, alters handlers, modifies responses, or
touches persistence.

The observational hybrid ranking is computed as follows:

1. Build a candidate score map keyed by `producto_presentacion_id`:
   - For each fuzzy candidate not in the vector list, use the
     fuzzy score (normalized to `[0.0, 1.0]`) and a vector score
     of `0.0`.
   - For each vector candidate not in the fuzzy list, use a fuzzy
     score of `0.0` and the vector cosine similarity returned by
     `ProductPresentationVectorMatch.score`.
   - For each candidate present in both lists, take the
     normalized fuzzy score aligned with the fuzzy encounter
     order and the vector cosine similarity from the match
     order.
2. For each candidate, compute the observational combined score
   as `fuzzy_weight * fuzzy_score + vector_weight * vector_score`,
   using the **provisional** weights `fuzzy_weight` (default
   `0.5`) and `vector_weight` (default `0.5`) configured on
   `Settings` (or, for tests, on the shadow service constructor).
   The weights are explicitly **non-authoritative**: the field
   names and the recorder carry the `non_authoritative` semantics
   so future calibration in Subphase 4.11 can replace them
   without changing the observation surface.
3. Order the candidates by descending combined score, breaking
   ties by ascending encounter order across the union of fuzzy
   and vector candidates; materialize the result as
   `hybrid_candidate_ranking` (tuple of `producto_presentacion_id`)
   and `hybrid_combined_scores` (tuple of `float` combined scores
   aligned with the ranking).
4. Compute `hybrid_top1_top2_gap` as the difference between the
   top-1 and top-2 combined scores; `0.0` when fewer than two
   ranked candidates.
5. Compute `exact_canonical_match` as `True` when the normalized
   input text equals a catalog `producto_nombre` for a candidate
   in the hybrid ranking, otherwise `False`. Compute
   `exact_alias_match` as `True` when the normalized input text
   equals an applicable alias (any of `general_aliases` or
   `specific_aliases`) for a candidate in the hybrid ranking,
   otherwise `False`. Both flags are computed against the
   caller-supplied catalog projection only — no database access.
6. Compute `decision` in this fixed order:
   - `"unique"` when `exact_canonical_match` is `True` and the
     canonical-matched candidate is in `hybrid_candidate_ranking`.
   - `"unique"` when `exact_alias_match` is `True` and the
     alias-matched candidate is in `hybrid_candidate_ranking`.
   - `"unique"` when `hybrid_candidate_ranking` is non-empty AND
     the top-1 combined score is `>= unique_threshold`
     (provisional default `0.7`) AND
     (`len(hybrid_candidate_ranking) == 1` OR
     `hybrid_top1_top2_gap >= min_score_gap`).
   - `"ambiguous"` when `hybrid_candidate_ranking` has more than
     one candidate AND the top-1 combined score is
     `>= ambiguous_threshold` (provisional default `0.4`).
   - `"unknown"` otherwise.
   The decision order is the playbook-mandated order:
   `exact canonical` → `exact alias` → `vector signal` →
   `fuzzy complementary signal` → `unique` / `ambiguous` /
   `unknown`. `min_score_gap` is the provisional,
   non-authoritative `shadow_hybrid_min_score_gap`
   (default `0.05`) used to gate the `unique` decision on the
   top-1/top-2 gap. When multiple candidates exceed the ambiguous
   threshold but the top-1/top-2 gap is below `min_score_gap`,
   the decision is `ambiguous` (not `unique`); the exact
   canonical and exact alias short-circuits keep their
   deterministic priority above this rule.

The hybrid observation is consumed only by the recorder and by
focused tests. It is **never** consumed by the orchestrator, the
handlers, the pending context, or any persistence layer. The
fuzzy recognizer remains the sole authoritative recognizer in
this subphase.

The provisional weights (`fuzzy_weight`, `vector_weight`),
thresholds (`unique_threshold`, `ambiguous_threshold`), and
`min_score_gap` (the configurable `shadow_hybrid_min_score_gap`)
are configurable on `Settings` (env-overridable) so Subphase 4.11
calibration can replace them without changing the observation
surface. They are explicitly marked
`non_authoritative=True` semantics on the observation dataclass
and the recorder log line. `shadow_hybrid_min_score_gap` is
validated at `Settings.load()` time to be a `float` in `[0.0, 1.0]`
and the constraint is enforced by the new
`InvalidShadowHybridMinScoreGap(ValueError)` exception.

The hybrid observation explicitly **does not** introduce active
hybrid mode, final calibrated thresholds, or fuzzy fallback
switching. Those belong to Subphase 4.11.

Alternative considered: writing the hybrid observation back into
the fuzzy result. Rejected because the playbook says shadow mode
is observational only and the fuzzy result contract is
byte-for-byte equivalent in both modes.

Alternative considered: calibrating the weights and thresholds in
this subphase. Rejected because calibration requires the
observational data set this subphase is producing; Subphase 4.11
will calibrate.

Alternative considered: an in-memory switch between the
authoritative fuzzy path and an authoritative hybrid path. Rejected
because the playbook forbids it in this subphase; the hybrid
path is observational only.

## Risks / Trade-offs

- [Risk] The shadow service runs fuzzy + embedding + vector per
  recognized text in `shadow` mode. That doubles the per-request
  cost for the recognition step. → [Mitigation] Shadow mode is
  opt-in (`product_recognizer_mode=fuzzy` by default), the semantic
  path is fully read-only, no background job is added, and the
  existing fuzzy recognizer runs **exactly once** per request:
  the `ShadowedProductRecognizer` decorator measures the fuzzy
  latency and forwards the result to the shadow service, which
  never re-invokes the fuzzy recognizer. The embedding transport
  timeout (`embedding_timeout_seconds`, default `30s`) is
  unchanged. The recorder uses structured logs, not synchronous
  network calls.
- [Risk] The recorder logs are observability data, not
  audit-grade. A future audit subphase may want richer traces.
  → [Mitigation] The recorder records only the safe operational
  fields listed in the playbook; the comparison dataclass is the
  single source of truth for the data shape; future audit work
  extends the recorder without changing the public surface.
- [Risk] `ShadowedProductRecognizer` becomes a hidden dependency
  for any future handler that imports `detectar_productos` and
  expects only fuzzy. → [Mitigation] The decorator's `recognize`
  signature is byte-equivalent to `FuzzyProductRecognizer.recognize`
  and the returned `ProductRecognizerResult` is the exact fuzzy
  result. The decorator has no additional side effects when
  `product_recognizer_mode=fuzzy`. The spec includes a regression
  scenario asserting the existing fuzzy result contract is
  preserved.
- [Risk] A wrong-dimension query embedding raises
  `InvalidVectorSearchDimension` from the 4.9 vector service and
  the shadow path must not propagate it. → [Mitigation] The shadow
  service catches `Exception` (broad, intentional) over the
  embedding + vector pipeline and translates every exception to a
  sanitized failure category plus `vector_available=False`. The
  fuzzy result is returned unchanged.
- [Risk] Embedding the recognizer `_normalizar_texto` helper from
  the shadow service crosses the recognizer / service boundary
  (the helper is private, prefix `_`). → [Mitigation] The 4.5 spec
  already locks the helper to be byte-equivalent to the document
  builder; reusing it from the shadow service is the playbook's
  intent ("do not duplicate fuzzy normalization"). A focused test
  asserts the byte-equivalence contract stays intact.
- [Risk] A change in the
  `ProductPresentationVectorMatch` result shape forces a follow-up
  in the shadow service. → [Mitigation] The shadow service reads
  `match.id_producto_presentacion` and `match.score` for the
  per-candidate vector scores and the observational hybrid ranking.
  It never reads `source_type`, `distance`, or any internal field.
  A 4.9 regression scenario confirms the 4.5–4.9 focused tests stay
  green.
- [Risk] The observational hybrid ranking is mistakenly consumed
  by an authoritative path. → [Mitigation] The hybrid observation
  is a return type that is only ever consumed by the recorder and
  focused tests. The orchestrator, the handlers, the pending
  context, and the persistence layer never import it. The shadow
  service returns the fuzzy result byte-for-byte unchanged and
  the hybrid observation is a parallel, purely data structure.
  A focused test asserts no orchestrator / handler / resolver
  imports the hybrid observation or its settings.
- [Risk] Provisional weights and thresholds leak into the
  authoritative path. → [Mitigation] The hybrid weights and
  thresholds — including `min_score_gap`
  (`shadow_hybrid_min_score_gap`) — are recorded on the
  observation dataclass and the recorder with explicit
  `non_authoritative=True` semantics. Subphase 4.11 calibration
  replaces them; this subphase does not consume them to make
  authoritative decisions. The settings surface is documented as
  `non_authoritative` in code comments and in the dataclass.
  `shadow_hybrid_min_score_gap` is validated at `Settings.load()`
  time to be a `float` in `[0.0, 1.0]` and the constraint is
  enforced by the new `InvalidShadowHybridMinScoreGap(
  ValueError)` exception.
- [Risk] The orchestrator binding change accidentally widens the
  import surface (e.g. importing the shadow service from a router
  or a test harness that previously only depended on the fuzzy
  recognizer). → [Mitigation] The factory lives in
  `backend/services/product_recognition_factory.py` and is the only
  module-level binding. Existing imports of `FuzzyProductRecognizer`
  and `ProductRecognizerProtocol` continue to work; the orchestrator
  is the only consumer of the factory.
