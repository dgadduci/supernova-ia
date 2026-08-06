## Why

The Subphase 4.11 calibration chain has reached the `eligible` verdict on the
47-case dataset (fuzzy decision accuracy 45/47, false positives 0, incorrect
unique decisions 0, the 4.11.5 restricted-ambiguity guard and the 4.11.7
fuzzy_unique + empty_vector guard both firing correctly on the cases they were
designed for), so the hybrid recognition pipeline (fuzzy + vector) is now
proven to outperform fuzzy on the frozen dataset while the runtime still runs
purely on `FuzzyProductRecognizer`. There is no longer a calibration reason to
keep hybrid observational: promoting it to authoritative would let the 4.11
gains reach the production conversation. The promotion must be **controlled**,
i.e. opt-in via a new `product_recognizer_mode` literal, driven by the
calibrated policy the runner already emits in its JSON report, and guarded by
the 4.11.5 and 4.11.7 guards and a deterministic fallback to fuzzy so an
embedding or vector failure never breaks the conversation.

The previous draft of this proposal raised
`InvalidProductRecognizerMode(ValueError)` at `Settings.load()` time whenever
`PRODUCT_RECOGNIZER_MODE` carried any literal outside the documented set.
That rejection blocked the orchestrator module-import-time
`get_product_recognizer(load_settings())` call from completing and therefore
prevented both startup and customer processing. The proposal now resolves an
unrecognised mode to the safe default `"fuzzy"`, emits a single sanitized
structured warning that names the configured mode, the effective mode, and a
sanitized reason category, and continues to load the application. The
exception class is retained only as a reserved marker that no longer fires
from the env-var path; no startup-blocking exception is raised for an
unrecognised `PRODUCT_RECOGNIZER_MODE`.

The previous draft also introduced an `intent_metadata` injection point on
the new hybrid authoritative recognizer without wiring it from any caller.
That left the 4.11.5 `catalog_scope == "pending_product_selection_restricted"`
guard permanently short-circuited at runtime. The proposal now threads the
catalog-scope information the runtime already owns through a small
backward-compatible shared context mechanism (`RecognizeContext`) on the
existing `ProductRecognizerProtocol.recognize` method, makes the
`product_selection_context_resolver` the single call site that sets
`catalog_scope == "pending_product_selection_restricted"`, and keeps the
existing `agregar_producto`, `quitar_producto`, and `modificar_producto`
flows on the same shared recognition boundary so the 4.11.5 guard can fire
for real customer traffic.

The previous draft pinned the candidate-scope invariant in the focused tests
("candidates excluded by the narrowed pending set cannot reappear in the
hybrid ranking; the 4.12A single-load/in-memory-filter discipline is
preserved") but did not require the runtime implementation to filter the
vector-search results against the `catalog` argument the recognizer
receives. Without that explicit filter, a raw vector result whose
`producto_presentacion_id` is outside the passed catalog (whether from
another commerce, from a candidate the 4.12A narrowing discarded, or from
a stray vector-index entry) could silently re-enter the hybrid ranking and
bypass the 4.11.5 guard. The proposal now requires the hybrid authoritative
recognizer to build `allowed_candidate_ids` exclusively from the `catalog`
argument received by `recognize(...)`, filter every raw vector-search
result against `allowed_candidate_ids` BEFORE applying the 4.11.5 guard,
the 4.11.7 guard, computing the hybrid score, building the hybrid ranking,
and translating the final decision, and consume only the filtered vector
side from that point onward. Commerce isolation, the 4.12A narrowing
invariant, and the "no extra catalog query" invariant are enforced by
this filter for every catalog passed to the recognizer (not only when
`catalog_scope == "pending_product_selection_restricted"`); the empty
filtered vector side is a valid semantic outcome (the 4.11.7 guard
activates verbatim when the fuzzy decision is `"unique"`, ambiguous and
unknown hybrid outcomes remain authoritative) and does NOT trigger a
technical fallback to fuzzy.

## What Changes

- Extend the literal `product_recognizer_mode` in
  `backend.config.settings.Settings` to
  `Literal["fuzzy", "shadow", "hybrid_authoritative"]` with
  `PRODUCT_RECOGNIZER_MODE` env override. The default remains `"fuzzy"`. When
  the env value is any other literal, `Settings.load()` resolves the
  effective mode to `"fuzzy"` and emits a single sanitized structured
  warning (via the standard `logging` mechanism) carrying the configured
  literal, the effective mode `"fuzzy"`, and a sanitized reason category
  `invalid_mode`. The `InvalidProductRecognizerMode(ValueError)` class is
  retained only as a reserved internal marker and is no longer raised by
  the env-var resolver; no startup-blocking exception is raised.
- New setting `hybrid_authoritative_policy_path: str | None` (env
  `HYBRID_AUTHORITATIVE_POLICY_PATH`, default `None`) pointing at the JSON
  calibration report the 4.11 runner emits. The path validator runs ONLY
  when the effective mode is `"hybrid_authoritative"`: a missing,
  non-`str`, or empty `str` value raises
  `InvalidHybridAuthoritativePolicyPath(ValueError)`. When the effective
  mode is `"fuzzy"` (including the safe-fallback case) or `"shadow"`, the
  path is ignored entirely and the validator does not run.
- New `HybridAuthoritativePolicySource` in
  `backend/services/hybrid_authoritative_policy_source.py` that loads the
  calibrated `selected_policy` from the JSON file and produces a
  `HybridDecisionPolicy`. Fails closed with `HybridAuthoritativePolicyError`
  when the file is missing, unparsable, or carries an ineligible
  `eligibility.status`. No module-level mutable state.
- New `HybridAuthoritativeProductRecognizer` decorator in
  `backend/services/hybrid_authoritative_recognizer.py` that implements
  `ProductRecognizerProtocol`, wraps `FuzzyProductRecognizer`, runs the
  same fuzzy → embedding → vector pipeline as the 4.10 `ShadowedProductRecognizer`,
  computes the hybrid decision with the calibrated policy, applies the
  4.11.5 (`catalog_scope == "pending_product_selection_restricted"`
  + `fuzzy_decision == "ambiguous"` → `ambiguous`) and 4.11.7
  (`fuzzy_decision == "unique"` + empty `vector_ids` → `unique`) guards
  verbatim, and returns the hybrid decision as the
  `ProductRecognizerResult` consumed by the orchestrators. Falls back to the
  fuzzy result byte-for-byte when the embedding or vector pipeline fails
  (failure category is recorded through the existing
  `ShadowMetricsRecorder` exactly as in shadow mode). The 4.11.5 guard
  reads `catalog_scope` exclusively from the `intent_metadata` argument
  the recognizer receives; when `intent_metadata` is `None` or its
  `catalog_scope` is not the restricted literal, the guard is short-
  circuited exactly as the calibration runner documents.
- Explicit catalog-scope filter on the hybrid authoritative recognizer
  (closes the blocking deviation): the recognizer MUST build
  `allowed_candidate_ids` exclusively from the `catalog` argument
  received by `recognize(...)`, MUST treat that catalog as the
  complete authoritative candidate universe for the current
  recognition call, and MUST filter every raw vector-search result
  (by `producto_presentacion_id`) against `allowed_candidate_ids`
  BEFORE applying the 4.11.5 guard, the 4.11.7 guard, computing the
  hybrid score, building the hybrid ranking, and translating the
  final decision. Any vector result whose `producto_presentacion_id`
  is not in `allowed_candidate_ids` is discarded. The recognizer
  MUST NOT query or reload the full commerce catalog to expand the
  candidate set and MUST NOT reintroduce candidates the 4.12A
  narrowing flow discarded. This rule applies for every catalog
  passed to `recognize(...)`, not only when
  `intent_metadata["catalog_scope"] == "pending_product_selection_restricted"`.
  After filtering, `vector_ids` and `vector_scores` are derived only
  from the retained results; if no allowed vector candidate remains,
  the vector side is empty, the 4.11.7 guard consumes the filtered
  empty `vector_ids`, and the recognizer does NOT fall back to fuzzy
  merely because every raw vector candidate was filtered out (this is
  a valid semantic outcome, not an infrastructure failure).
  Commerce isolation is enforced by the passed catalog: the hybrid
  ranking cannot include a candidate from another commerce, a
  restricted pending candidate set cannot be widened, duplicate IDs
  are deduplicated only after scope filtering, and ordering and
  scoring operate only on retained candidates.
- New backward-compatible shared context mechanism `RecognizeContext`
  TypedDict in `backend/recognizers/product_recognizer_contract.py`
  carrying the documented scope literals. The existing
  `ProductRecognizerProtocol.recognize` method gains a keyword-only
  optional `intent_metadata: RecognizeContext | None = None` argument.
  `FuzzyProductRecognizer.recognize` and `ShadowedProductRecognizer
  .recognize` accept the new argument and ignore it; the new
  `HybridAuthoritativeProductRecognizer.recognize` reads `catalog_scope`
  from it to fire the 4.11.5 guard. The change is additive at every
  call site that omits the argument.
- The single existing call site that owns
  `catalog_scope == "pending_product_selection_restricted"` — the
  `detectar_productos(text, productos_presentaciones)` call inside
  `backend/intents/context/product_selection_context_resolver.py:165`
  — is the sole call site that passes
  `intent_metadata={"catalog_scope": "pending_product_selection_restricted"}`.
  All other runtime call sites (the `agregar_producto` orchestrator's
  initial commerce-catalog call, the `modificar_producto` destination
  selection call, the `quitar_producto` order-line call, etc.) omit the
  argument or pass `None`, so the 4.11.5 guard fires only for the
  restricted pending-product-selection path. The local
  `detectar_productos` symbol in each module is rewritten as a thin
  wrapper that accepts and forwards `intent_metadata` so every call
  site can declare its scope without duplicating recognizer wiring.
- Extend `backend/services/product_recognition_factory.py` so
  `get_product_recognizer(settings)` returns the
  `HybridAuthoritativeProductRecognizer` for the new mode. The existing
  `fuzzy` and `shadow` branches are unchanged.
- The existing `agregar_producto`, `quitar_producto`, and `modificar_producto`
  orchestrators continue to call `detectar_productos` through the shared
  factory-bound recognizer; no orchestrator change. The
  `product_selection_context_resolver`'s local wrapper is the only
  additional call site that passes `intent_metadata`.
- Telemetry: in `hybrid_authoritative` mode the recognizer produces the same
  `ProductRecognitionShadowComparison` + `ProductRecognitionHybridObservation`
  payloads that the shadow mode already produces, and records them through
  the existing `ShadowMetricsRecorder`. The recorder emits the same fields
  it already emits, with `hybrid_non_authoritative=True` set to `False` for
  the hybrid decision (because the hybrid decision IS authoritative in this
  mode) and a new `mode="hybrid_authoritative"` log field. The fuzzy and
  shadow modes are untouched.
- New exception `HybridAuthoritativePolicyError` and the corresponding
  `InvalidHybridAuthoritativePolicyPath` validator in
  `backend/services/exceptions.py` and `backend/config/settings.py`.
- New capability spec `openspec/specs/controlled-hybrid-product-recognition/spec.md`
  pinning the runtime recognizer, the policy loader, the guards, the fuzzy
  fallback, the telemetry, the catalog-scope propagation, and the test
  surface.
- Modified capability spec delta
  `openspec/specs/product-recognition-shadow-mode/spec.md` extending the
  `product_recognizer_mode` setting to a three-value literal, extending
  `get_product_recognizer` to wire the new mode, extending the recorder to
  record `mode` and `hybrid_non_authoritative=False` for the new mode,
  adding the `hybrid_authoritative_policy_path` setting with its validator,
  and pinning the safe-fuzzy fallback for unrecognised env values.
- No SQLAlchemy schema change, no Alembic migration, no FastAPI endpoint, no
  handler, no response builder, no pending-context change, no recognizer
  contract change (the new decorator still returns the same
  `ProductRecognizerResult`), no calibration dataset or policy grid change,
  no embedding client change, no vector search service change, no per-
  commerce configuration, no LangGraph, no LLM call from the hybrid
  authoritative path. The recognizer does NOT query or reload the full
  commerce catalog to expand the candidate set and does NOT reintroduce
  candidates discarded by the 4.12A narrowing flow; the catalog passed to
  `recognize(...)` is the complete authoritative candidate universe for the
  current recognition call, and the catalog-scope filter operates on the
  raw vector-search results returned by the injected
  `ProductPresentationVectorSearchService.search_similar`.

## Capabilities

### New Capabilities

- `controlled-hybrid-product-recognition`: runtime hybrid pipeline that lets
  the calibrated `HybridDecisionPolicy` decide the
  `ProductRecognizerResult` returned to the orchestrators, driven by the
  JSON calibration report the 4.11 runner emits, preserves the 4.11.5 and
  4.11.7 guards verbatim (with the 4.11.5 guard operational at runtime via
  the new shared `RecognizeContext` mechanism), applies an explicit
  catalog-scope filter on the hybrid authoritative recognizer so
  `allowed_candidate_ids` is built exclusively from the catalog the
  recognizer receives and the raw vector results are filtered against that
  set before any guard, scoring, ranking, or translation (the 4.12A
  single-load/in-memory-filter discipline is preserved verbatim; commerce
  isolation is enforced by the passed catalog; the empty filtered vector
  side is a valid semantic outcome and does NOT trigger a technical
  fallback to fuzzy), falls back to the fuzzy result when the embedding
  or vector pipeline fails, and records the same
  `ProductRecognitionShadowComparison` + `ProductRecognitionHybridObservation`
  payloads the shadow mode already records through the existing
  `ShadowMetricsRecorder`. The capability also documents the safe-fuzzy
  fallback for unrecognised `PRODUCT_RECOGNIZER_MODE` values.

### Modified Capabilities

- `product-recognition-shadow-mode`: extend `Settings.product_recognizer_mode`
  to a three-value literal (`"fuzzy"`, `"shadow"`,
  `"hybrid_authoritative"`) with the safe-fuzzy fallback documented above,
  add `Settings.hybrid_authoritative_policy_path` with its validator,
  extend `get_product_recognizer` to wire the new mode to the
  `HybridAuthoritativeProductRecognizer`, extend `ShadowMetricsRecorder
  .record` to add a `mode` log field and to set
  `hybrid_non_authoritative=False` when the recognizer ran in
  `hybrid_authoritative` mode, and add the
  `RecognizeContext` / `intent_metadata` shared boundary for catalog-scope
  propagation. The fuzzy and shadow mode behaviours and contracts are
  preserved verbatim.

## Impact

- `backend/config/settings.py` (modify) — extend mode literal, switch the
  env-var resolver to the safe-fuzzy fallback with the structured warning,
  add policy path setting + validator scoped to the effective mode, add
  `InvalidHybridAuthoritativePolicyPath`.
- `backend/recognizers/product_recognizer_contract.py` (modify) — add the
  `RecognizeContext` TypedDict and the keyword-only optional
  `intent_metadata` argument to `ProductRecognizerProtocol.recognize`.
- `backend/recognizers/fuzzy_product_recognizer.py` (modify) — accept and
  ignore the new `intent_metadata` argument; no semantic change.
- `backend/services/product_recognition_shadow_service.py` (modify) — make
  `ShadowedProductRecognizer.recognize` accept and forward the new
  `intent_metadata` argument; shadow mode remains purely observational.
- `backend/services/exceptions.py` (modify) — add
  `HybridAuthoritativePolicyError`; retain
  `InvalidProductRecognizerMode` as a reserved internal marker that is no
  longer raised by the env-var resolver.
- `backend/services/hybrid_authoritative_policy_source.py` (new) — JSON
  policy loader.
- `backend/services/hybrid_authoritative_recognizer.py` (new) — runtime
  authoritative hybrid recognizer with guards and fuzzy fallback.
- `backend/services/product_recognition_factory.py` (modify) — wire the new
  mode; pass `intent_metadata` through to the new recognizer.
- `backend/services/shadow_metrics_recorder.py` (modify) — add the `mode`
  log field and the `hybrid_non_authoritative=False` branch.
- `backend/intents/context/product_selection_context_resolver.py` (modify)
  — rewrite the local `detectar_productos` as a thin wrapper that forwards
  `intent_metadata` and pass
  `intent_metadata={"catalog_scope": "pending_product_selection_restricted"}`
  on the single `detect` call; no other module imports or behaviour change.
- `backend/intents/context/product_modification_resolver.py` (modify),
  `backend/intents/recognizers/quitar_producto_recognizer.py` (modify),
  `backend/intents/recognizers/modificar_producto_recognizer.py` (modify),
  `backend/intents/orchestration/agregar_producto_orchestrator.py` (modify)
  — rewrite each module's local `detectar_productos` as a thin wrapper
  that forwards `intent_metadata` (defaulting to `None`); no orchestrator
  or handler semantics change.
- `backend/tests/test_controlled_hybrid_product_recognition.py` (new) —
  focused tests covering the safe-fuzzy fallback warning, the policy
  loader, the guards applied at runtime (with the 4.11.5 guard proven
  operational through the shared `RecognizeContext`), the catalog-scope
  filter (vector result outside the received catalog is discarded;
  candidate excluded by the 4.12A narrowed pending set cannot reappear;
  vector result from another commerce cannot appear in the final
  result; filtering every raw vector result does NOT trigger technical
  fallback; fuzzy unique + filtered empty `vector_ids` activates the
  4.11.7 guard; ambiguous and unknown outcomes remain authoritative
  after filtering; duplicate vector IDs are deduplicated only after
  scope filtering; no extra catalog query is issued by the recognizer),
  the fuzzy fallback, and the telemetry surface.
- `backend/tests/test_settings_product_recognizer_mode.py` (modify) —
  replace the "invalid literal raises" scenario with the safe-fuzzy
  fallback scenario.
- `backend/tests/test_product_recognition_factory.py` (modify) — add a
  scenario covering the safe-fuzzy fallback producing the
  `FuzzyProductRecognizer` without loading the hybrid policy file.
- `openspec/specs/controlled-hybrid-product-recognition/spec.md` (new).
- `openspec/specs/product-recognition-shadow-mode/spec.md` (delta: add the
  third mode literal, the safe-fuzzy fallback, the policy path setting,
  the factory wiring, the recorder mode field, and the
  `RecognizeContext` / `intent_metadata` shared boundary).
- No SQLAlchemy schema change, no Alembic migration, no FastAPI endpoint,
  no handler, no response builder, no pending-context change, no recognizer
  contract change, no calibration dataset or policy grid change, no
  embedding client change, no vector search service change, no per-commerce
  configuration, no LangGraph.
