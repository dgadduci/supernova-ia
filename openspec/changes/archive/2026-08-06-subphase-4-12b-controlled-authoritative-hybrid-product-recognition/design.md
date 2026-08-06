## Context

Subphase 4.10 introduced the
`ProductRecognitionShadowService` +
`ShadowedProductRecognizer` decorator (in
`backend/services/product_recognition_shadow_service.py`) and the
`ShadowMetricsRecorder` (in
`backend/services/shadow_metrics_recorder.py`). The factory
`backend/services/product_recognition_factory.py` already builds the
shadow decorator when `settings.product_recognizer_mode == "shadow"`,
and the orchestrator binding
`backend/intents/orchestration/agregar_producto_orchestrator.py:19`
resolves the shared `detectar_productos` symbol through
`get_product_recognizer(load_settings())` at module import time.

Subphase 4.11 introduced the offline calibration runner
`backend/services/product_recognition_calibration_runner.py` together
with the typed `HybridDecisionPolicy` dataclass
(`backend/services/product_recognition_calibration_policy.py:17`) and
the calibration report writer
`backend/services/product_recognition_calibration_report.py`. The
runner already emits `selected_policy` and
`eligibility.status` in its JSON report (see
`backend/services/product_recognition_calibration_runner.py:947`
and `:960`).

Subphases 4.11.5 and 4.11.7 added the two runtime guards inside the
calibration runner's `_hybrid_prediction` helper
(`backend/services/product_recognition_calibration_runner.py:200`):

- 4.11.5 guard — `catalog_scope == "pending_product_selection_restricted"`
  AND `fuzzy_decision == "ambiguous"` → force `ambiguous` (see the
  `hybrid guard preserves fuzzy ambiguity for
  pending_product_selection_restricted cases` requirement in
  `openspec/specs/calibrate-hybrid-product-recognition-4-11/spec.md`).
- 4.11.7 guard — `fuzzy_decision == "unique"` AND `len(vector_ids) == 0`
  → force `unique` (see the
  `hybrid-fuzzy-unique-fallback-4-11-7 closes the 4 residual
  hybrid_recognizer_failure cases by guarding fuzzy_unique +
  empty_vector` requirement in
  `openspec/specs/hybrid-fuzzy-unique-fallback-4-11-7/spec.md`).

Both guards are conditional returns at the top of the helper and do
not modify the scoring formula, the policy grid, the JSON report
schema, the diagnostic surface, or the CLI surface.

Subphase 4.12A (just archived at
`openspec/changes/archive/2026-08-05-subphase-4-12a-pending-product-ambiguity-resolution/`)
closed the deterministic reply vocabulary for the
`product_selection_context_resolver` path. Subphase 4.12B is the
complementary runtime half: now that the calibration chain has
reached the `eligible` verdict on the 47-case dataset, promote the
hybrid pipeline from observational to authoritative, but in a
controlled way so an embedding or vector failure cannot break the
production conversation and the 4.11.5/4.11.7 regression fixes remain
in force.

## Goals / Non-Goals

**Goals:**

- Add a new opt-in `product_recognizer_mode = "hybrid_authoritative"`
  literal and a new `hybrid_authoritative_policy_path` setting with
  validation scoped to the effective mode. An unrecognised
  `PRODUCT_RECOGNIZER_MODE` value SHALL be resolved to the safe
  default `"fuzzy"` with a single sanitized structured warning — no
  startup-blocking exception.
- Add `HybridAuthoritativePolicySource.load(settings)` that reads the
  JSON calibration report the 4.11 runner already emits, fails closed
  when the file is missing, malformed, or carries
  `eligibility.status != "eligible"`, and returns a validated
  `HybridDecisionPolicy` instance. The loader is invoked ONLY when
  the effective mode is `"hybrid_authoritative"`.
- Add `HybridAuthoritativeProductRecognizer` that wraps
  `FuzzyProductRecognizer`, runs the embedding + vector pipeline the
  4.10 shadow service already runs, applies the 4.11.5 and 4.11.7
  guards verbatim, translates the hybrid decision into the
  `ProductRecognizerResult` four-key contract, and falls back to the
  fuzzy result byte-for-byte on any embedding or vector failure.
- Add a backward-compatible shared context mechanism
  (`RecognizeContext` TypedDict + keyword-only optional
  `intent_metadata` argument on `ProductRecognizerProtocol.recognize`)
  and wire the single call site that owns the
  `pending_product_selection_restricted` catalog scope — the
  `product_selection_context_resolver` detect call — so the 4.11.5
  guard is operational at runtime.
- Extend `get_product_recognizer` to wire the new mode.
- Extend `ShadowMetricsRecorder.record(...)` to accept a new optional
  `mode` argument (default `"shadow"`) and to emit
  `hybrid_non_authoritative=False` when `mode == "hybrid_authoritative"`.
- Keep the existing `fuzzy` and `shadow` modes verbatim; keep the
  existing 4.5–4.11 module surfaces verbatim; keep the calibration
  runner, calibration policy module, calibration report module,
  calibration dataset, and policy grid verbatim.

**Non-Goals:**

- No SQLAlchemy schema change, no Alembic migration, no FastAPI
  endpoint, no router, no handler, no response builder, no
  pending-context change.
- No new recognizer contract; the hybrid authoritative recognizer
  returns the existing `ProductRecognizerResult` four-key shape and
  the existing `ProductRecognizerProtocol` signature gains only a
  keyword-only optional `intent_metadata` argument.
- No new hybrid decision algorithm; the runtime uses the same
  scoring formula the 4.11 runner uses.
- No new policy grid, no new dataset, no new calibration report
  schema; the runtime loads the existing JSON report.
- No automatic promotion of the calibrated policy into the runtime
  defaults; promotion is a manual env-variable change.
- No LLM call from the hybrid authoritative path; the embedding
  client is the only LLM dependency and it is non-blocking in the
  fallback path (the fallback returns the fuzzy result).
- No embedding client, vector search service, sync service, seeder,
  indexer, document builder, admin router, or persistence change.
- No per-commerce policy override; the single calibrated policy file
  applies to every commerce that goes through
  `get_product_recognizer` in `hybrid_authoritative` mode.
- No per-request telemetry change beyond the new `mode` log field
  and the `hybrid_non_authoritative=False` branch; the rest of the
  recorder surface is preserved verbatim.
- No LangGraph, no endpoint work, no recalibration, no database
  migrations.
- The `InvalidProductRecognizerMode(ValueError)` class is retained
  as a reserved internal marker; it is no longer raised by the
  env-var resolver (see Decision 2).

## Decisions

### Decision 1: New `product_recognizer_mode` literal, not a new setting

- **Choice**: Extend the existing
  `Literal["fuzzy", "shadow"]` to a three-value
  `Literal["fuzzy", "shadow", "hybrid_authoritative"]` rather than
  introducing a separate `hybrid_authoritative_enabled: bool`
  setting.
- **Rationale**: A single setting keeps the mode-switching surface
  uniform across `fuzzy`, `shadow`, and `hybrid_authoritative`,
  makes it impossible to enable `hybrid_authoritative` while the
  factory still resolves the shadow branch, and matches the
  validator's "fall back to safe default" behaviour (see
  Decision 2). The orchestrator's module-import-time
  `get_product_recognizer(load_settings())` resolves exactly one
  of the three branches and never two at the same time.
- **Alternatives considered**:
  - *Separate `hybrid_authoritative_enabled: bool`* → rejected:
    would require the factory to branch on two settings and would
    silently allow contradictory combinations (e.g. enabled + shadow).
  - *New `hybrid_observability_level` enum* → rejected: would
    re-shape the existing `Literal` without semantic gain; the
    current three modes are distinct enough to be literals.

### Decision 2: Safe-fuzzy fallback for unrecognised `PRODUCT_RECOGNIZER_MODE`, not a hard rejection

- **Choice**: When the `PRODUCT_RECOGNIZER_MODE` env value is set to
  any literal other than `"fuzzy"`, `"shadow"`, or
  `"hybrid_authoritative"`, the env-var resolver
  (`backend/config/settings.py::_product_recognizer_mode_env`)
  returns `"fuzzy"` as the effective mode and emits a single
  sanitized structured warning through the standard `logging`
  mechanism. The warning carries the documented fields:
  - `configured_mode`: the raw env-var literal the operator set;
  - `effective_mode`: the literal `"fuzzy"`;
  - `reason`: the sanitized reason category `"invalid_mode"`.
  The warning is sanitized: it never carries the raw exception
  text, a Python stack trace, the customer message, the database
  credentials, the host name, or any internal exception detail. The
  `Settings.load()` call completes normally; the orchestrator
  module-import-time `get_product_recognizer(load_settings())` call
  resolves to the `fuzzy` branch; no startup-blocking exception is
  raised; customer processing continues.
- **Rationale**: A literal typo in the env file, an operator
  mistake, or a leftover value from a previous deploy MUST NOT be
  able to take the application offline or block customer
  processing. The safe default `"fuzzy"` is the recognizer that
  every customer flow already runs against; falling back to it
  preserves the conversation. The structured warning makes the
  fallback observable to the operator through the standard log
  pipeline so they can correct the typo without discovering it
  through a customer complaint.
- **Alternatives considered**:
  - *Hard rejection (`InvalidProductRecognizerMode`) at
    `Settings.load()` time* → rejected: this is the previous
    proposal's deviation. A literal typo in
    `PRODUCT_RECOGNIZER_MODE` cannot take the application offline
    in any other recognizer-mode setting, and the hybrid
    authoritative path is strictly opt-in. Hard rejection in this
    branch alone would make the recognizer-mode surface the only
    settings surface that can break startup through a typo, which
    is a regression. The exception class is retained as a reserved
    marker for callers that want to validate settings coming from a
    non-env source, but the env-var path no longer raises it.
  - *Silent coercion to `"fuzzy"` with no observability* →
    rejected: would let a misconfiguration persist undetected and
    would silently disable an operator's intended mode promotion
    to `hybrid_authoritative`. The structured warning is the
    observability hook that closes that gap.
  - *Hard rejection in production but soft coercion in dev* →
    rejected: would split the behaviour by environment, would
    make the test suite unable to reproduce the production
    failure mode, and would still be a startup blocker in
    production.

### Decision 3: Hybrid authoritative recognizer mirrors the 4.10 shadow recognizer

- **Choice**: `HybridAuthoritativeProductRecognizer` is structured
  as a sibling of `ShadowedProductRecognizer` that wraps the same
  `FuzzyProductRecognizer`, calls the same `_normalizar_texto`
  helper, calls the same `OllamaEmbeddingClient.embed_query`, calls
  the same `ProductPresentationVectorSearchService.search_similar`,
  and produces a `ProductRecognitionShadowComparison` +
  `ProductRecognitionHybridObservation` pair for the recorder. The
  only structural difference is what the recognizer *returns* to the
  caller: the shadow recognizer returns the fuzzy result
  unchanged; the hybrid authoritative recognizer returns the
  translated hybrid decision (with a fuzzy fallback on failure).
- **Rationale**: Mirroring the shadow service preserves the
  exception-translation discipline (sanitized failure categories,
  no semantic-path exception raised to the caller) and reuses the
  recorder surface verbatim. The structural symmetry makes the
  runtime diff a single recognizer implementation, not a parallel
  pipeline that could drift from the shadow one.
- **Alternatives considered**:
  - *Refactor `ShadowedProductRecognizer` into a generic
    "HybridObservabilityDecorator" parameterised by a "return
    fuzzy or return hybrid" flag* → rejected: would couple the
    shadow observability path to the authoritative decision
    logic, would make `ShadowedProductRecognizer`'s contract
    depend on the policy loader, and would require updating every
    shadow-mode scenario.
  - *Build the hybrid pipeline inline inside the factory* →
    rejected: would inflate the factory beyond its current
    single-purpose "resolve one of three recognizers" contract.

### Decision 4: 4.11.5 and 4.11.7 guards ported verbatim, not re-derived

- **Choice**: The hybrid authoritative recognizer ports the two
  guards from
  `backend/services/product_recognition_calibration_runner.py:200-228`
  verbatim. The conditions, the early-return semantics, and the
  decision value (`"ambiguous"` and `"unique"`) are byte-for-byte
  identical. The 4.11.5 guard reads `catalog_scope` exclusively
  from the `intent_metadata` argument the recognizer receives; when
  `intent_metadata` is `None` or its `catalog_scope` field is not
  the documented `pending_product_selection_restricted` literal,
  the guard is short-circuited and cannot fire. The 4.11.7 guard is
  scope-independent and ports verbatim. The guards do not depend on
  any intent-specific import inside the recognizer.
- **Rationale**: Porting the guards verbatim eliminates any chance
  of a divergent interpretation between the calibration runner and
  the runtime recognizer and removes the need for a parallel test
  surface for the guards themselves (the existing 4.11.5 and 4.11.7
  focused tests already cover the guard logic).
- **Alternatives considered**:
  - *Re-derive the guards inside the hybrid authoritative
    recognizer's `_hybrid_decision` helper* → rejected: would
    silently allow semantic drift between the calibration runner
    and the runtime recognizer.
  - *Have the hybrid authoritative recognizer import the runner
    and call its `_hybrid_prediction` helper* → rejected: would
    couple the runtime recognizer to the offline calibration
    module and would force the runtime to import
    `sqlalchemy`/`sqlalchemy.orm` for `Session` even when no
    session is in scope.

### Decision 5: The 4.11.5 guard is operational at runtime through a backward-compatible shared boundary

- **Choice**: The shared product-recognition boundary used by the
  `agregar_producto`, `quitar_producto`, `modificar_producto`, and
  pending-product-selection flows is the
  `ProductRecognizerProtocol.recognize(text, catalog)` method
  exposed by every recognizer the factory returns. The protocol
  method gains a keyword-only optional
  `intent_metadata: RecognizeContext | None = None` argument that
  carries the documented scope literal `catalog_scope`. Every
  existing implementation (`FuzzyProductRecognizer.recognize` and
  `ShadowedProductRecognizer.recognize`) accepts the new argument
  and ignores it; the new `HybridAuthoritativeProductRecognizer
  .recognize` reads `catalog_scope` from it. The
  `RecognizeContext` TypedDict is defined in
  `backend/recognizers/product_recognizer_contract.py` and carries
  exactly one field for now:
  `catalog_scope: Literal["pending_product_selection_restricted",
  "commerce_dynamic_database"]`.
- **Rationale**: The four flows already converge on
  `ProductRecognizerProtocol.recognize(text, catalog)`. Adding a
  keyword-only optional argument is the smallest backward-
  compatible surface change that lets the runtime deliver
  `catalog_scope == "pending_product_selection_restricted"` to
  the hybrid authoritative recognizer without (a) duplicating
  recognition logic per handler, (b) introducing an intent-specific
  import inside the recognizer, (c) re-querying the full catalog,
  (d) reintroducing candidates the existing narrowing discarded,
  or (e) breaking the single-load/in-memory-filter discipline the
  4.12A resolver established. The four flows continue to use the
  factory-bound recognizer: the existing
  `_product_recognizer = get_product_recognizer(load_settings())`
  binding at the top of the `agregar_producto` orchestrator and
  the per-module local `detectar_productos = _product_recognizer
  .recognize` aliases in the `quitar_producto` and `modificar_producto`
  recognizers and in `product_modification_resolver` continue to
  resolve to the factory output. The single new call site that
  passes `intent_metadata={"catalog_scope":
  "pending_product_selection_restricted"}` is the
  `detect` call inside
  `backend/intents/context/product_selection_context_resolver.py`
  — the one place in the runtime that loads the restricted
  candidate catalog for the active pending intent and is therefore
  the only place the 4.11.5 guard needs to fire. Each module's
  local `detectar_productos` symbol is rewritten as a thin wrapper
  that accepts and forwards `intent_metadata` so every call site
  can declare its scope without duplicating recognizer wiring or
  breaking caller-owned transactions.
- **Alternatives considered**:
  - *Re-derive the catalog scope inside the recognizer by querying
    the active `session` and `ProcessedIntent`* → rejected: would
    couple the recognizer to the SQLAlchemy session, the
    `ProcessedIntent` schema, and the pending-context lifecycle;
    would force the recognizer to query the active intent; would
    duplicate the catalog-restriction logic the 4.12A resolver
    already owns.
  - *Re-query the full commerce catalog inside the recognizer and
    intersect with the narrowed candidate set* → rejected: would
    violate the 4.12A single-load/in-memory-filter invariant and
    would silently re-widen the candidate set on every hybrid call.
  - *Per-handler `intent_metadata` literal hardcoded inside the
    orchestrators* → rejected: would duplicate the wiring in four
    handlers and would couple each handler to the recognizer's
    private keyword argument.
  - *Thread-local context* → rejected: would make the scope
    implicit and would couple the recognizer to a hidden global;
    explicit argument passing is auditable.

### Decision 6: Fuzzy fallback, not `unknown`, on embedding or vector failure

- **Choice**: When the embedding pipeline or the vector search
  service raises any exception, the hybrid authoritative
  recognizer returns the fuzzy `ProductRecognizerResult`
  unchanged (byte-for-byte, including all four keys and the
  ordering). The recognizer does NOT translate the failure into
  `"unknown"`; the conversation continues with the fuzzy result
  the customer would have seen in the `"fuzzy"` mode. The same
  behaviour applies when the configured mode is unrecognised: the
  safe-fuzzy fallback at `Settings.load()` time resolves the
  effective mode to `"fuzzy"` BEFORE the factory is consulted, so
  no hybrid policy file is loaded and no hybrid recognizer is
  constructed.
- **Rationale**: "Controlled authoritative" means the new mode
  cannot make the conversation worse than the existing `fuzzy`
  mode. Returning the fuzzy result on failure preserves the
  Subphase 4.10 discipline (no semantic exception raised to the
  caller) and guarantees that flipping the env variable from
  `fuzzy` to `hybrid_authoritative` cannot regress any customer
  flow when the embedding or vector pipeline is degraded. The
  failure is recorded through the existing
  `ShadowMetricsRecorder` so the operator can detect the
  degradation and revert.
- **Alternatives considered**:
  - *Return `"unknown"` on failure (i.e. a three-key
    `no_encontrados` result)* → rejected: would make
    `hybrid_authoritative` strictly worse than `fuzzy` whenever
    Ollama is down, would block the customer conversation, and
    would force the operator to revert the env variable under
    load.
  - *Return the hybrid observation `decision` verbatim without
    translating it to a result* → rejected: would break the
    `ProductRecognizerProtocol` four-key contract and would force
    every orchestrator to learn a new result shape.

### Decision 7: Hybrid decision translation into the four-key result contract

- **Choice**: The hybrid decision is translated into a
  `ProductRecognizerResult` by a small `_translate_hybrid_decision`
  helper that mirrors the translation rules the existing fuzzy
  recognizer uses:
  - `"unique"` → one entry in `encontrados` with `cantidad=1` and
    `texto_origen` set to the normalised input text; the other
    three collections are empty.
  - `"ambiguous"` → one group in `encontrados_posibles` whose
    `productos` list is the hybrid ranking in descending combined
    score order; the other three collections are empty.
  - `"unknown"` → exactly one `{"texto_origen": <normalised
    text>}` in `no_encontrados`; the other three collections are
    empty.
- **Rationale**: The four-key shape is the existing
  `ProductRecognizerProtocol` contract and every downstream
  consumer (orchestrators, handlers, response builders,
  pending-context resolvers) already consumes it. Translating the
  hybrid decision into the existing shape keeps every downstream
  consumer unchanged and lets the change be a single recognizer
  swap at the shared boundary.
- **Alternatives considered**:
  - *Add a new `hybrid_decision` field to `ProductRecognizerResult`
    so the consumer can read both the hybrid verdict and the
    fuzzy verdict* → rejected: would break the frozen
    `ProductRecognizerResult` TypedDict from
    `backend/recognizers/product_recognizer_contract.py` and would
    require every consumer to learn the new field.
  - *Return the hybrid observation object directly* → rejected:
    same reason, plus the observation is a data-only dataclass
    that the consumer has no business consuming.

### Decision 8: Telemetry uses the existing recorder with a new `mode` argument

- **Choice**: The hybrid authoritative recognizer calls
  `ShadowMetricsRecorder.record(..., mode="hybrid_authoritative")`.
  The recorder emits the same log fields it already emits, plus a
  new `mode` field and the `hybrid_non_authoritative=False` branch
  documented in the modified capability spec.
- **Rationale**: The recorder surface is already the single
  observability sink for the 4.10 shadow path. Adding a `mode`
  argument instead of a parallel recorder keeps the telemetry
  pipeline uniform and lets a single log filter distinguish
  `"fuzzy"` (no record), `"shadow"`, and `"hybrid_authoritative"`
  in production. The `hybrid_non_authoritative=False` flag tells
  the operator that the recorded decision was the one the customer
  saw, not an observational parallel — a critical difference for
  post-mortem analysis.
- **Alternatives considered**:
  - *Add a second recorder for the hybrid authoritative path* →
    rejected: would duplicate the recorder surface and would force
    the operator to maintain two log filters.
  - *Skip telemetry in the hybrid authoritative path* → rejected:
    would remove the operator's only window into the calibrated
    policy's runtime behaviour and would silently break the
    auditability of the 4.11 calibration chain.

### Decision 9: Policy loaded once at factory call time, not per request

- **Choice**: The factory calls
  `HybridAuthoritativePolicySource.load(settings)` exactly once
  inside `get_product_recognizer` and stores the resulting
  `HybridDecisionPolicy` on the recognizer. The recognizer's
  `recognize` method does NOT reload the policy on every call. The
  loader runs ONLY when the effective mode is
  `"hybrid_authoritative"`; in the safe-fuzzy fallback case the
  loader does not run, no policy file is consulted, and the
  factory resolves to the `fuzzy` branch.
- **Rationale**: A policy reload per request would force a
  filesystem read on every customer message, would couple the
  recognizer's hot path to disk I/O, and would allow a mid-run
  policy swap that could silently regress customer-visible
  behaviour. Loading the policy once at factory call time matches
  the existing shadow service's "trust the Settings; validate at
  load time" discipline and keeps the recognizer hot path free of
  I/O. Skipping the loader on the safe-fuzzy fallback is required
  to honour the "no hybrid policy file is loaded when the
  configured mode is invalid" requirement.
- **Alternatives considered**:
  - *Reload the policy on every call* → rejected: see rationale.
  - *Watch the file and reload on change* → rejected: would
    require an OS-level file watcher that does not exist in the
    current dependencies and would add operational complexity
    out of proportion with the subphase's scope.

### Decision 10: `hybrid_authoritative_policy_path` validator scoped to the effective mode

- **Choice**: The
  `HYBRID_AUTHORITATIVE_POLICY_PATH` validator runs ONLY when the
  effective mode is `"hybrid_authoritative"`. When the effective
  mode is `"fuzzy"` (including the safe-fuzzy fallback case) or
  `"shadow"`, the validator does not run, a non-`None` value is
  silently ignored, and the factory does not consult the path.
  When the effective mode is `"hybrid_authoritative"`, the
  validator raises `InvalidHybridAuthoritativePolicyPath` for
  non-`None` non-`str` or empty `str` values.
- **Rationale**: The path is only meaningful when the hybrid
  authoritative recognizer is going to read it. Validating the
  path in the other modes would either (a) raise a startup-
  blocking exception for a path the factory is going to ignore
  or (b) require a more complex "validate-later" flow. Scoping
  the validator to the effective mode keeps the failure path
  identical to the existing `shadow_vector_top_k` and
  `shadow_hybrid_min_score_gap` validators (which already only
  matter when the shadow mode is active).
- **Alternatives considered**:
  - *Always validate the path regardless of the effective mode* →
    rejected: would create a startup-blocker for a setting the
    runtime is going to ignore, and would force operators to
    remove the path before flipping the mode to anything other
    than `hybrid_authoritative`.

### Decision 11: Explicit catalog-scope filter on the hybrid authoritative recognizer

- **Choice**: The `HybridAuthoritativeProductRecognizer.recognize`
  method (a) builds `allowed_candidate_ids` exclusively from the
  `catalog` argument it receives (deduplicated), treating that
  catalog as the complete authoritative candidate universe for
  the current recognition call; (b) filters the raw `vector_ids`
  and `vector_scores` returned by the injected
  `ProductPresentationVectorSearchService.search_similar` against
  `allowed_candidate_ids` BEFORE applying the 4.11.5 guard, the
  4.11.7 guard, computing the hybrid score, building the hybrid
  ranking, and translating the final decision; and (c) consumes
  only the filtered vector side from that point onward.
  - **Build step**: `allowed_candidate_ids` is constructed once
    per `recognize(...)` call from the catalog rows the caller
    passed. Duplicates in the catalog are deduplicated when
    building the set. The recognizer does NOT query the
    SQLAlchemy session, the embedding client, the vector search
    service, or any other data source to expand the set.
  - **Filter step**: any raw vector result whose
    `producto_presentacion_id` is not present in
    `allowed_candidate_ids` is discarded before guards/scoring/
    ranking/translation. If no raw vector candidate survives, the
    filtered vector side is empty (`vector_ids == []`,
    `vector_scores == []`).
  - **Consume step**: the 4.11.5 guard (step 4.7 in
    `tasks.md`), the 4.11.7 guard (step 4.8), the hybrid scoring
    and ranking step (step 4.9), the decision translation step
    (step 4.10), and the recorder observation payload (step
    4.11) all consume the filtered vector side. The raw search
    results are NEVER consulted by any of these steps.
  - **No-widening invariant**: the recognizer MUST NOT query or
    reload the full commerce catalog to expand the candidate
    set, MUST NOT reintroduce candidates the 4.12A narrowing
    flow discarded, and MUST NOT widen a restricted pending
    candidate set. The 4.12A single-load/in-memory-filter
    discipline is preserved verbatim.
  - **Empty-filtered-vector side**: when every raw vector
    candidate is filtered out, the recognizer does NOT trigger
    a technical fallback to fuzzy. The vector side is treated
    as empty, the 4.11.7 guard activates verbatim when
    `fuzzy_decision == "unique"`, ambiguous and unknown hybrid
    outcomes (after the 4.11.5 / 4.11.7 guards) remain
    authoritative, and the conversation continues with the
    hybrid decision derived from the filtered empty vector
    side. This is a valid semantic outcome, not an
    infrastructure failure.
  - **Catalog-agnostic rule**: the filter applies for every
    catalog passed to `recognize(...)`, not only when
    `intent_metadata["catalog_scope"] == "pending_product_selection_restricted"`.
    Commerce isolation is enforced by the filter against the
    commerce-specific `allowed_candidate_ids` derived from the
    passed catalog, so a vector result from another commerce
    cannot appear in the final result.
  - **Duplicate handling**: duplicate `producto_presentacion_id`s
    in the raw vector results are deduplicated only AFTER the
    filter step, not before. Candidates outside
    `allowed_candidate_ids` are dropped by the filter before
    dedupe.
- **Rationale**: The 4.12A resolver established the single-load
  /in-memory-filter discipline that loads the commerce catalog
  exactly once and narrows it in memory. The 4.10 shadow service
  passes that narrowed catalog to the embedding and vector
  pipeline, and the 4.11 calibration runner validates the
  candidate boundary at the evaluator after recognition. Without
  an explicit catalog-scope filter inside the hybrid authoritative
  recognizer, however, a vector result outside the passed catalog
  (whether from another commerce, from a candidate the 4.12A
  narrowing discarded, or from a stray vector-index entry) could
  silently re-enter the hybrid ranking and bypass the 4.11.5
  restricted-scope guard. The filter is the smallest runtime
  mechanism that keeps the candidate universe consistent with
  the catalog the caller actually handed to the recognizer, and
  it does so without re-querying the database, without
  reintroducing 4.12A-discarded candidates, and without coupling
  the recognizer to any SQLAlchemy session. The
  "no-fallback-on-empty-filtered-vector" rule preserves the
  semantic path: a fuzzy-unique decision that survives the
  filter still returns unique via the 4.11.7 guard; an ambiguous
  or unknown hybrid outcome is the recognizer's authoritative
  answer when the filter discarded the vector side.
- **Alternatives considered**:
  - *Re-query the full commerce catalog inside the recognizer
    and intersect with the narrowed candidate set* → rejected:
    would violate the 4.12A single-load/in-memory-filter
    invariant, would silently re-widen the candidate set on
    every hybrid call, and would force the recognizer to
    depend on a SQLAlchemy session.
  - *Pass `candidate_producto_presentacion_ids` to
    `search_similar` and rely on the vector service to filter*
    → rejected: the 4.11 calibration runner and the 4.10
    shadow service both call `search_similar` with
    `candidate_producto_presentacion_ids=None` to preserve the
    observability of vector behavior; restricting the search
    at the service layer would change the recorded telemetry
    and would couple the recognizer's hot path to the vector
    service's internal filter. The post-search catalog-scope
    filter keeps the recorded observation comparable to the
    existing 4.11 calibration chain while enforcing the
    runtime invariant.
  - *Fall back to fuzzy whenever the filter discards every raw
    vector result* → rejected: would mask a semantic outcome
    (e.g. fuzzy-`unique` + filtered-empty-vector) as a
    technical failure, would violate the 4.11.7 guard's
    preconditions (the guard requires the filtered vector
    side to be empty, not the raw side), and would make
    `hybrid_authoritative` strictly worse than `fuzzy`
    whenever the vector index returns out-of-scope hits.
  - *Apply the filter only when
    `catalog_scope == "pending_product_selection_restricted"`* →
    rejected: the catalog-scope filter is a candidate-isolation
    invariant that must hold for every catalog the recognizer
    receives (commerce isolation, 4.12A narrowing preservation,
    and the no-reload invariant are catalog-agnostic).

## Risks / Trade-offs

- **Risk**: A stale calibration report could be promoted into the
  runtime by an operator flipping
  `PRODUCT_RECOGNIZER_MODE=hybrid_authoritative` weeks after the
  runner last produced it. A catalogue change between the report
  and the runtime would silently skew the vector search.
  - **Mitigation**: The loader fails closed on missing path,
    unparsable JSON, non-eligible status, or any malformed
    `selected_policy`. The operator must explicitly point the env
    variable at a fresh report. A future subphase can add an
    `staleness` check (mtime + dataset fingerprint) without
    changing this contract.

- **Risk**: An operator typo in `PRODUCT_RECOGNIZER_MODE` (e.g.
  `hybrid_auth`, `HybridAuthoritative`, `hybrid-active`) could
  silently disable an intended promotion to the hybrid
  authoritative path.
  - **Mitigation**: The safe-fuzzy fallback at `Settings.load()`
    time emits a single sanitized structured warning that names
    the configured literal, the effective mode `"fuzzy"`, and the
    reason category `"invalid_mode"`. The operator can grep the
    application logs for the `reason == "invalid_mode"` field to
    detect every fallback. The factory does not load the hybrid
    policy file in the fallback case, so the customer-visible
    behaviour is identical to a clean `"fuzzy"` mode.

- **Risk**: The runtime recognizer's 4.11.5 guard needs
  `catalog_scope == "pending_product_selection_restricted"` from
  the active pending-product-selection flow. Without a shared
  boundary, the guard would remain permanently short-circuited.
  - **Mitigation**: The new `RecognizeContext` TypedDict and the
    keyword-only optional `intent_metadata` argument on
    `ProductRecognizerProtocol.recognize` carry the catalog scope
    from the one call site that owns the restricted candidate
    catalog (`product_selection_context_resolver.detectar_productos`)
    to the hybrid authoritative recognizer. Every other runtime
    call site omits the argument or passes `None`, so the guard
    fires only for the restricted pending-product-selection path.
    The change is additive at every call site that omits the
    argument, so no existing recognizer contract is broken and no
    transaction ownership moves.

- **Risk**: Without an explicit catalog-scope filter inside the
  hybrid authoritative recognizer, a raw vector result outside
  the catalog passed to `recognize(...)` could silently re-enter
  the hybrid ranking — bypassing the 4.11.5 restricted-scope
  guard, reintroducing candidates the 4.12A narrowing flow
  discarded, or crossing commerce boundaries. The previous
  proposal only asserted the candidate-scope invariant in the
  focused tests; it did not pin the runtime filter step.
  - **Mitigation**: Decision 11 pins the catalog-scope filter
    inside the hybrid authoritative recognizer. The recognizer
    builds `allowed_candidate_ids` exclusively from the
    `catalog` argument, filters the raw vector results against
    that set before any guard, scoring, ranking, or translation,
    and consumes only the filtered vector side from that point
    onward. The recognizer does NOT query or reload the full
    commerce catalog and does NOT widen a restricted pending
    candidate set; the 4.12A single-load/in-memory-filter
    discipline is preserved verbatim. Commerce isolation is
    enforced by the filter because `allowed_candidate_ids` is
    derived from the commerce-specific catalog the caller
    passed. The empty-filtered-vector side is a valid semantic
    outcome (the 4.11.7 guard activates verbatim, ambiguous
    and unknown hybrid outcomes remain authoritative) and does
    NOT trigger a technical fallback to fuzzy. The focused
    tests pin every clause of this invariant.

- **Risk**: The fuzzy fallback on embedding/vector failure could
  mask a degraded pipeline in production if the operator does not
  watch the recorder logs.
  - **Mitigation**: The recorder log carries the
    `failure_category` field exactly as the shadow mode already
    emits it. A log filter on `failure_category != None` is the
    operator's degradation signal.

- **Risk**: Adding a third `product_recognizer_mode` literal is
  a breaking change for any consumer that imports the
  `Literal["fuzzy", "shadow"]` type and pattern-matches on it.
  - **Mitigation**: The `Literal` is exported only through
    `backend.config.settings.Settings`, which is imported by the
    factory and the orchestrator. The two consumers are updated
    in this change. No other module imports the literal; a
    repository grep confirms it. The new keyword-only optional
    `intent_metadata` argument on `ProductRecognizerProtocol
    .recognize` is additive: every implementation gains it and
    every call site that omits it is unaffected.

- **Risk**: The hybrid authoritative recognizer depends on the
  embedding client and the vector search service. If either
  raises an exception during a request, the fallback returns
  the fuzzy result but the latency budget documented for the
  4.11 calibration chain could be exceeded.
  - **Mitigation**: The latency budget is checked by the
    calibration runner, not by the runtime recognizer. The
    runtime recognizer preserves the fuzzy latency on fallback
    (the fuzzy call already happened) and adds zero additional
    latency when the embedding or vector pipeline is degraded.

## Migration Plan

No migration. No schema change, no Alembic revision, no data
backfill. The change is a code-only extension that:

1. Adds one new mode literal (`hybrid_authoritative`) and one new
   setting (`hybrid_authoritative_policy_path`) to `Settings`.
2. Switches the existing `PRODUCT_RECOGNIZER_MODE` env-var
   resolver from "raise on invalid literal" to "fall back to
   `fuzzy` and emit a sanitized structured warning" so an
   unrecognised mode cannot break startup.
3. Adds one new module (`hybrid_authoritative_policy_source.py`)
   and one new module
   (`hybrid_authoritative_recognizer.py`).
4. Adds one new factory branch in
   `product_recognition_factory.py`.
5. Adds one new `mode` argument to
   `ShadowMetricsRecorder.record`.
6. Adds the `RecognizeContext` TypedDict and the keyword-only
   optional `intent_metadata` argument on
   `ProductRecognizerProtocol.recognize`; updates the
   `FuzzyProductRecognizer`, `ShadowedProductRecognizer`, and the
   new `HybridAuthoritativeProductRecognizer` to accept the
   argument; rewrites the per-module local `detectar_productos`
   aliases as thin wrappers that forward `intent_metadata`.
7. Adds the explicit catalog-scope filter inside the hybrid
   authoritative recognizer (Decision 11): builds
   `allowed_candidate_ids` exclusively from the `catalog` argument
   received by `recognize(...)`, filters the raw vector results
   against that set before any guard, scoring, ranking, or
   translation, and consumes only the filtered vector side from
   that point onward. The 4.12A single-load/in-memory-filter
   discipline is preserved verbatim; commerce isolation is
   enforced by the passed catalog; the empty-filtered-vector
   side is a valid semantic outcome and does NOT trigger a
   technical fallback to fuzzy.
8. Adds one new test file
   (`test_controlled_hybrid_product_recognition.py`); modifies
   the existing
   `test_settings_product_recognizer_mode.py` and
   `test_product_recognition_factory.py` to cover the safe-fuzzy
   fallback, the new shared boundary, and the catalog-scope
   filter (every clause from the focused test list).

Rollback is a single revert: remove the two new modules, remove
the third factory branch, remove the new mode literal and
setting, revert the resolver to the raise-on-invalid behaviour,
revert the recorder change, revert the `RecognizeContext` /
`intent_metadata` addition. The `fuzzy` and `shadow` modes remain
operational and the orchestrator binding is preserved.

Promotion is manual: an operator who wants to enable the new
mode must

1. Run the 4.11 calibration CLI against an up-to-date
   `supernova_test` database and capture the JSON report.
2. Confirm the report's `eligibility.status == "eligible"`.
3. Point `HYBRID_AUTHORITATIVE_POLICY_PATH=<report.json>` at the
   report.
4. Set `PRODUCT_RECOGNIZER_MODE=hybrid_authoritative`.
5. Restart the orchestrator process so the module-import-time
   `get_product_recognizer(load_settings())` re-resolves.

A typo or stale value in `PRODUCT_RECOGNIZER_MODE` does NOT
prevent restart and does NOT require intervention: the safe-
fuzzy fallback resolves the effective mode to `"fuzzy"` and
emits the documented structured warning. Reverting to fuzzy
remains `PRODUCT_RECOGNIZER_MODE=fuzzy` and a restart.

## Open Questions

- None blocking. The 4.12B contract — opt-in third mode, JSON
  policy loader, 4.11.5/4.11.7 guards verbatim (with the 4.11.5
  guard operational at runtime through the shared
  `RecognizeContext` mechanism), explicit catalog-scope filter on
  the hybrid authoritative recognizer (`allowed_candidate_ids`
  built exclusively from the passed catalog; raw vector results
  filtered against that set before any guard, scoring, ranking,
  or translation; commerce isolation enforced by the passed
  catalog; empty filtered vector side is a valid semantic
  outcome, not a technical fallback), fuzzy fallback, recorder
  surface, safe-fuzzy fallback for unrecognised mode literals —
  is specified explicitly in the
  `controlled-hybrid-product-recognition` capability spec and in
  the modified `product-recognition-shadow-mode` capability spec.
  The policy loader's eligibility gate
  (`eligibility.status == "eligible"`) is the explicit source of
  truth for what is allowed to be promoted into the runtime.
