# Capability: controlled-hybrid-product-recognition

## Purpose

Promote the Subphase 4.10/4.11 hybrid (fuzzy + vector) recognition pipeline
from observational (shadow) to authoritative in a **controlled** way: opt-in
via a new `product_recognizer_mode = "hybrid_authoritative"` literal, driven
by the calibrated `HybridDecisionPolicy` the 4.11 runner already emits in its
JSON report, preserving the 4.11.5 `pending_product_selection_restricted` +
`fuzzy_ambiguous` guard and the 4.11.7 `fuzzy_unique` + empty `vector_ids`
guard verbatim at runtime, falling back to the fuzzy result byte-for-byte
when the embedding or vector pipeline fails, and recording the same
`ProductRecognitionShadowComparison` + `ProductRecognitionHybridObservation`
payloads through the existing `ShadowMetricsRecorder`. Fuzzy remains the
default and is the sole authoritative recognizer in the existing
`fuzzy` and `shadow` modes; the new mode is strictly opt-in. An
unrecognised `PRODUCT_RECOGNIZER_MODE` value SHALL fall back to the safe
default `"fuzzy"` with a sanitized structured warning and SHALL NOT prevent
application startup or customer processing.

The 4.11.5 guard receives the `catalog_scope` information from the active
pending-product-selection flow through the new shared `RecognizeContext`
mechanism on `ProductRecognizerProtocol.recognize` so the guard is
operational at runtime for real customer traffic. The mechanism is
backward-compatible: every call site that omits the new
`intent_metadata` argument is unaffected.

## Requirements

### Requirement: Hybrid authoritative mode is opt-in via a third `product_recognizer_mode` literal with a safe-fuzzy fallback

The system SHALL add a third value `"hybrid_authoritative"` to the
`product_recognizer_mode` setting accepted by
`backend.config.settings.Settings.load()`. The default SHALL remain
`"fuzzy"`. The setting SHALL remain overridable through the existing
`PRODUCT_RECOGNIZER_MODE` environment variable. When the environment
variable is set to `"fuzzy"`, `"shadow"`, or `"hybrid_authoritative"`,
`Settings.load()` SHALL accept the literal verbatim and `settings
.product_recognizer_mode` SHALL equal that literal. When the
environment variable is set to any other literal (including the empty
string, a typo such as `hybrid_auth` or `HybridAuthoritative`, a
stale value such as `hybrid_active`, or any other non-empty value
outside the documented set), `Settings.load()` SHALL:

1. resolve the effective mode to `"fuzzy"` so `settings
   .product_recognizer_mode == "fuzzy"`;
2. NOT raise `InvalidProductRecognizerMode(ValueError)` from the
   env-var resolver;
3. emit exactly one sanitized structured log record through the
   standard `logging` mechanism carrying the documented fields
   `configured_mode` (the raw env-var literal the operator set),
   `effective_mode` (the literal `"fuzzy"`), and `reason` (the
   sanitized literal `"invalid_mode"`);
4. allow the application to continue loading so the module-import-
   time `get_product_recognizer(load_settings())` call resolves to
   the `fuzzy` branch and customer processing is uninterrupted.

The `InvalidProductRecognizerMode(ValueError)` class SHALL remain
defined as a reserved internal marker for callers that want to
validate settings coming from a non-env source. The env-var
resolver SHALL NOT raise it. The safe-fuzzy fallback SHALL NOT
load the hybrid authoritative policy file and SHALL NOT
construct the `HybridAuthoritativeProductRecognizer`.

#### Scenario: Default mode remains fuzzy

- **WHEN** `Settings.load()` is called without an explicit override
- **THEN** `settings.product_recognizer_mode == "fuzzy"`
- **AND** no warning is emitted
- **AND** the new mode is not active

#### Scenario: Hybrid authoritative override is accepted

- **WHEN** the environment variable
  `PRODUCT_RECOGNIZER_MODE=hybrid_authoritative` is set before
  `Settings.load()` is called
- **THEN** `settings.product_recognizer_mode == "hybrid_authoritative"`
- **AND** no warning is emitted

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
- **AND** the hybrid authoritative policy file is NOT loaded
- **AND** no `HybridAuthoritativeProductRecognizer` is constructed

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

#### Scenario: Safe-fuzzy fallback resolves the factory to the fuzzy recognizer

- **WHEN** `get_product_recognizer(load_settings())` is called
  after the safe-fuzzy fallback resolved the effective mode to
  `"fuzzy"`
- **THEN** the returned recognizer is a `FuzzyProductRecognizer`
  instance
- **AND** the `HybridAuthoritativePolicySource.load` method is
  NOT called
- **AND** no policy file is read

### Requirement: `hybrid_authoritative_policy_path` validator is scoped to the effective mode

The system SHALL expose
`hybrid_authoritative_policy_path` as a `str | None` attribute on
`backend.config.settings.Settings`. The default SHALL be `None`.
The setting SHALL be overridable through an environment variable
of the same name. The validator SHALL run ONLY when the effective
mode is `"hybrid_authoritative"`; in that case, the validator
SHALL raise `InvalidHybridAuthoritativePolicyPath(ValueError)`
when the value is anything other than `None` or a non-empty
`str`. When the effective mode is `"fuzzy"` (including the safe-
fuzzy fallback case) or `"shadow"`, the validator SHALL NOT run
and a non-`None` value SHALL be silently ignored.

#### Scenario: Default policy path is None

- **WHEN** `Settings.load()` is called without an explicit override
- **THEN** `settings.hybrid_authoritative_policy_path is None`

#### Scenario: Explicit path override is accepted

- **WHEN** `PRODUCT_RECOGNIZER_MODE=hybrid_authoritative` AND
  `HYBRID_AUTHORITATIVE_POLICY_PATH=/tmp/report.json` are set
  before `Settings.load()` is called
- **THEN** `settings.hybrid_authoritative_policy_path ==
  "/tmp/report.json"`

#### Scenario: Empty path override is rejected at load time in hybrid_authoritative mode

- **WHEN** `PRODUCT_RECOGNIZER_MODE=hybrid_authoritative` AND
  `HYBRID_AUTHORITATIVE_POLICY_PATH=` (empty string) are set
  before `Settings.load()` is called
- **THEN** `Settings.load()` raises
  `InvalidHybridAuthoritativePolicyPath`

#### Scenario: Path override is ignored in fuzzy mode

- **WHEN** `PRODUCT_RECOGNIZER_MODE=fuzzy` AND
  `HYBRID_AUTHORITATIVE_POLICY_PATH=/tmp/report.json` are set
  before `Settings.load()` is called
- **THEN** `Settings.load()` completes without raising
- **AND** the factory does NOT read the policy path

### Requirement: Calibrated policy source loads the JSON calibration report

The system SHALL expose
`HybridAuthoritativePolicySource` in
`backend/services/hybrid_authoritative_policy_source.py` with a single
`load(settings) -> HybridDecisionPolicy` classmethod that:

1. Reads `settings.hybrid_authoritative_policy_path` as a `pathlib.Path`
   and opens it in `utf-8` mode.
2. Parses the file as JSON. If parsing fails or the JSON is not a JSON
   object, the loader SHALL raise `HybridAuthoritativePolicyError`.
3. Requires the top-level `selected_policy` key to be a JSON object whose
   keys are exactly `fuzzy_weight`, `vector_weight`, `unique_threshold`,
   `ambiguous_threshold`, `minimum_score_gap`, and `vector_top_k`. Any
   missing key, extra key, or wrong-type value SHALL raise
   `HybridAuthoritativePolicyError`.
4. Requires the top-level `eligibility.status` key to equal the literal
   `"eligible"`. Any other value (`"not_eligible"`, `"pending"`, missing,
   wrong type) SHALL raise `HybridAuthoritativePolicyError`.
5. Constructs `HybridDecisionPolicy(**selected_policy)` so the existing
   `HybridDecisionPolicy.__post_init__` validators run on every load.
   Any constructor failure SHALL propagate as
   `HybridAuthoritativePolicyError` (the loader wraps the constructor
   error).
6. Returns the resulting `HybridDecisionPolicy` instance.

The loader SHALL NOT mutate the file system, SHALL NOT write to any
JSON file, SHALL NOT hold module-level mutable state, SHALL NOT cache
the loaded policy across calls, SHALL NOT import FastAPI, the embedding
client transport, the vector search service, the shadow service, the
shadowed recognizer, the shadow recorder, the recognizer factory, or
any router. The loader SHALL depend only on the existing
`HybridDecisionPolicy` dataclass, the existing `pathlib`, `json`, and
the new `HybridAuthoritativePolicyError` exception.

#### Scenario: Loader succeeds on a valid eligible calibration report

- **WHEN** the loader reads a JSON file whose `selected_policy` matches
  the documented keys with valid values and whose `eligibility.status`
  equals `"eligible"`
- **THEN** it returns a `HybridDecisionPolicy` instance with the
  documented fields

#### Scenario: Loader fails closed on missing file

- **WHEN** the loader reads a path that does not exist
- **THEN** it raises `HybridAuthoritativePolicyError` naming the missing
  path
- **AND** no `HybridDecisionPolicy` is returned

#### Scenario: Loader fails closed on non-eligible eligibility

- **WHEN** the JSON file carries `eligibility.status == "not_eligible"`
  or `"pending"` or is missing the `eligibility` block
- **THEN** the loader raises `HybridAuthoritativePolicyError`
- **AND** no `HybridDecisionPolicy` is returned

#### Scenario: Loader fails closed on malformed selected_policy

- **WHEN** the JSON file is missing a required `selected_policy` key or
  carries an extra key or a non-numeric value
- **THEN** the loader raises `HybridAuthoritativePolicyError`
- **AND** no `HybridDecisionPolicy` is returned

### Requirement: Backward-compatible shared boundary carries the catalog scope to the hybrid recognizer

The system SHALL expose a `RecognizeContext` TypedDict in
`backend/recognizers/product_recognizer_contract.py` carrying exactly
the field `catalog_scope: Literal["pending_product_selection_restricted",
"commerce_dynamic_database"]`. The
`ProductRecognizerProtocol.recognize` method SHALL gain a keyword-only
optional `intent_metadata: RecognizeContext | None = None` argument
that callers use to declare the catalog scope of the recognition call.
The `FuzzyProductRecognizer.recognize`, `ShadowedProductRecognizer
.recognize`, and `HybridAuthoritativeProductRecognizer.recognize`
methods SHALL accept the new keyword argument; the first two SHALL
ignore it; the third SHALL read `catalog_scope` from it to fire the
4.11.5 guard. Every call site that omits the argument SHALL continue
to work without modification. The change SHALL NOT add any intent-
specific import inside any recognizer.

The single call site that passes
`intent_metadata={"catalog_scope": "pending_product_selection_restricted"}`
SHALL be the `detect` call inside
`backend/intents/context/product_selection_context_resolver.py`,
which is the only place in the runtime that loads the restricted
candidate catalog for the active pending intent. Every other runtime
call site (the `agregar_producto` orchestrator's initial commerce-
catalog call, the `modificar_producto` destination selection call,
the `quitar_producto` order-line call, and any future call site that
operates against the full commerce catalog or against a non-restricted
subset) SHALL omit the argument or pass `None`. The local
`detectar_productos` symbol in each affected module SHALL be rewritten
as a thin wrapper that accepts and forwards `intent_metadata` so
every call site can declare its scope without duplicating recognizer
wiring. The change SHALL NOT move caller-owned transactions and
SHALL NOT re-query the full commerce catalog.

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

### Requirement: Hybrid authoritative recognizer returns the hybrid decision with the 4.11.5 guard operational at runtime

The system SHALL expose `HybridAuthoritativeProductRecognizer` in
`backend/services/hybrid_authoritative_recognizer.py` that implements
`ProductRecognizerProtocol` and exposes a
`recognize(text, catalog, *, intent_metadata=None) ->
ProductRecognizerResult` method. The recognizer SHALL:

1. Invoke the injected inner fuzzy recognizer exactly once, measure its
   latency, and use the result as the authoritative fuzzy side.
2. Read the commerce id from `catalog[0]["categoria_id"]` through an
   injected `commerce_id_resolver` callable that defaults to `None`.
   When the resolver is `None` or returns `None`, the recognizer SHALL
   skip the embedding/vector pipeline and return the fuzzy result
   unchanged (byte-for-byte, including all four keys).
3. When the resolver yields a commerce id, run the embedding pipeline:
   `_normalizar_texto(text)` from `backend.recognizers.product_recognizer`,
   the injected `OllamaEmbeddingClient` (or any object implementing
   `embed_query`), and the injected `ProductPresentationVectorSearchService`
   with `top_k=policy.vector_top_k`,
   `candidate_producto_presentacion_ids=None`. The recognizer SHALL
   reuse the same exception-translation behaviour the 4.10 shadow
   service documents: on any exception, fall back to the fuzzy result
   byte-for-byte and set `failure_category` to `"embedding_failure"` or
   `"vector_failure"` as appropriate. The raw `vector_ids` and
   `vector_scores` returned by the search service SHALL be passed to
   the catalog-scope filter step (the next clause) before any guard,
   scoring, ranking, or translation is performed.
4. Build `allowed_candidate_ids` exclusively from the `catalog`
   argument received by `recognize(...)` (every `producto_presentacion_id`
   in the catalog rows, deduplicated). The catalog passed to
   `recognize(...)` is the complete authoritative candidate universe
   for the current recognition call; the recognizer SHALL NOT query
   or reload the full commerce catalog to expand this set and SHALL
   NOT reintroduce candidates discarded by the 4.12A narrowing flow.
5. Filter the raw `vector_ids` and `vector_scores` returned by the
   search service against `allowed_candidate_ids` BEFORE applying the
   4.11.5 guard, the 4.11.7 guard, hybrid scoring, ranking, and
   decision translation. Any raw vector result whose
   `producto_presentacion_id` is not present in `allowed_candidate_ids`
   is discarded. The filtered `vector_ids` and `vector_scores` SHALL
   be the only vector side consumed by every subsequent step. If no
   raw vector candidate survives, the vector side is empty
   (`vector_ids == []`, `vector_scores == []`); the 4.11.7 guard
   SHALL evaluate the filtered empty vector side and SHALL activate
   as documented when `fuzzy_decision == "unique"`. Filtering every
   raw vector result out SHALL NOT trigger a technical fallback to
   fuzzy; the recognizer SHALL continue with the filtered empty vector
   side and the existing fuzzy pipeline (this is a valid semantic
   outcome, not an infrastructure failure). Commerce isolation is
   enforced by this filter because `allowed_candidate_ids` is derived
   from the commerce-specific catalog passed to `recognize(...)`; a
   vector result from another commerce cannot appear in the final
   result. Duplicate vector IDs in the retained results SHALL be
   deduplicated AFTER the filter step, not before. The recognizer
   SHALL apply this rule for every catalog passed to `recognize(...)`,
   not only when
   `intent_metadata["catalog_scope"] == "pending_product_selection_restricted"`.
6. When the embedding and vector pipelines both succeed, compute the
   hybrid decision via the SAME scoring rule the 4.11 runner uses in
   `_hybrid_prediction`: `policy.fuzzy_weight * fuzzy_score +
   policy.vector_weight * vector_score` with `fuzzy_score` aligned to
   `observation.fuzzy_ids` (top score `1.0`, subsequent scores
   non-increasing in encounter order, identical to the
   `_fuzzy_candidate_scores` rule in the 4.10 shadow service) and
   `vector_score` aligned to the first `policy.vector_top_k` elements
   of the FILTERED `vector_ids` from step 5 (cosine similarity scores
   from `ProductPresentationVectorMatch.score`). The hybrid ranking
   SHALL be built from the filtered candidates only; no candidate
   outside `allowed_candidate_ids` SHALL appear in the ranking.
7. Apply the 4.11.5 `catalog_scope == "pending_product_selection_restricted"`
   + `fuzzy_decision == "ambiguous"` → `ambiguous` guard verbatim (see
   the `calibrate-hybrid-product-recognition-4-11` capability, the
   `hybrid guard preserves fuzzy ambiguity for
   pending_product_selection_restricted cases (including
   category-level ambiguity)` requirement, for the exact rule and
   scenarios). The guard SHALL read `catalog_scope` exclusively from
   `intent_metadata.get("catalog_scope")`. When `intent_metadata` is
   `None`, or when `intent_metadata["catalog_scope"]` is not the
   documented `pending_product_selection_restricted` literal, the
   guard SHALL be short-circuited and SHALL NOT fire. The guard
   SHALL consume the FILTERED `vector_ids` from step 5; the raw
   search results SHALL NOT be consulted by the guard.
8. Apply the 4.11.7 `fuzzy_decision == "unique"` + empty
   `vector_ids` → `unique` guard verbatim (see the
   `hybrid-fuzzy-unique-fallback-4-11-7` capability, the
   `hybrid-fuzzy-unique-fallback-4-11-7 closes the 4 residual
   hybrid_recognizer_failure cases by guarding fuzzy_unique +
   empty_vector` requirement, for the exact rule and scenarios).
   The guard is scope-independent and SHALL NOT inspect
   `catalog_scope`. The guard SHALL consume the FILTERED
   `vector_ids` from step 5 (not the raw search results); it
   SHALL fire whenever the fuzzy decision is `"unique"` AND the
   FILTERED vector side is empty, regardless of whether the raw
   search returned results that were discarded by the
   catalog-scope filter.
9. Translate the hybrid decision into a `ProductRecognizerResult`:
   - `"unique"` → the recognised top candidate is the single entry of
     `encontrados` (with `cantidad=1`, `texto_origen` set to the
     normalised input text) and the three other collections are empty.
   - `"ambiguous"` → the hybrid ranking is preserved in
     `encontrados_posibles` as a single `{"texto_origen", "productos"}`
     group whose `productos` list is ordered by descending combined
     score; `encontrados` and `encontrados_no_disponibles` are empty;
     `no_encontrados` is empty.
   - `"unknown"` → `encontrados`, `encontrados_posibles`, and
     `encontrados_no_disponibles` are empty; `no_encontrados` contains
     exactly `{"texto_origen": <normalised text>}`.
   The translated `ProductRecognizerResult` SHALL satisfy the existing
   `ProductRecognizerProtocol` four-key contract
   (`encontrados`, `encontrados_posibles`, `encontrados_no_disponibles`,
   `no_encontrados`) and SHALL preserve the documented
   `ProductRecognizerResult` invariants: empty values are lists, not
   `None`; ordering follows segment order, descending confidence, and
   stable ties; duplicate product-presentation IDs are deduplicated to
   the strongest match. The `ranking` consumed by the translator
   SHALL be the filtered ranking from step 6 only; no raw,
   unfiltered, or out-of-scope candidate SHALL appear in the
   translated result.
10. When the embedding or vector pipeline fails, the recognizer SHALL
    return the fuzzy `ProductRecognizerResult` unchanged (the same
    object the inner fuzzy recognizer produced). The recognizer SHALL
    NOT fall back to `unknown`; the conversation MUST continue with the
    fuzzy result the customer would have seen in the `"fuzzy"` mode.
11. Record the runtime observation through the injected
    `ShadowMetricsRecorder` exactly as the 4.10 shadow service does.
    The recorder log carries the same fields it already carries,
    plus a new `mode="hybrid_authoritative"` field and
    `hybrid_non_authoritative=False` (the hybrid decision is
    authoritative in this mode, unlike in `"shadow"`). The recorded
    observation SHALL carry the FILTERED `vector_ids` and
    `vector_scores` from step 5, not the raw search results, so the
    recorded telemetry reflects what the runtime guards, scoring,
    ranking, and translation actually consumed.

The recognizer SHALL NOT import FastAPI, the recognizer factory, the
shadow service, the shadowed recognizer, the calibration runner, the
calibration policy module, the seeder, the indexer, the document
builder, the sync service, the admin router, or any persistence model.
The recognizer SHALL NOT call `session.commit`, `session.rollback`,
`session.close`, or `session.begin`. The recognizer SHALL NOT add any
intent-specific import. The recognizer SHALL depend only on
`FuzzyProductRecognizer`, the embedding client protocol, the 4.9
`ProductPresentationVectorSearchService`, the `HybridDecisionPolicy`
dataclass, the four-key `ProductRecognizerResult` contract, the
existing `ShadowMetricsRecorder`, and the existing `_normalizar_texto`
helper.

#### Scenario: Recognizer is assignable to the product recognizer protocol

- **WHEN** `HybridAuthoritativeProductRecognizer` is inspected
- **THEN** it exposes a
  `recognize(text: str, catalog: list[dict], *, intent_metadata:
  RecognizeContext | None = None) -> ProductRecognizerResult` method
- **AND** it is assignable to `ProductRecognizerProtocol`

#### Scenario: Hybrid unique decision is translated to a single-entry encontrados

- **WHEN** the calibrated policy classifies the input as
  `"unique"` with top candidate id `42` and the commerce resolver
  returns a valid id
- **THEN** the recognizer returns a `ProductRecognizerResult` whose
  `encontrados` list contains exactly one entry with
  `producto_presentacion_id == 42`, `cantidad == 1`, and the
  normalised input text in `texto_origen`
- **AND** the other three collections are empty

#### Scenario: Hybrid ambiguous decision is translated to a single possible group

- **WHEN** the calibrated policy classifies the input as `"ambiguous"`
  with hybrid ranking `[42, 99]`
- **THEN** the recognizer returns a `ProductRecognizerResult` whose
  `encontrados_posibles` list contains exactly one
  `{"texto_origen", "productos"}` group
- **AND** the `productos` list contains exactly the two ranking entries
  in the order `[42, 99]`
- **AND** the other three collections are empty

#### Scenario: Hybrid unknown decision is translated to no_encontrados

- **WHEN** the calibrated policy classifies the input as `"unknown"`
- **THEN** the recognizer returns a `ProductRecognizerResult` whose
  `no_encontrados` list contains exactly
  `{"texto_origen": <normalised input>}`
- **AND** the other three collections are empty

#### Scenario: 4.11.5 restricted ambiguous guard fires verbatim at runtime

- **WHEN** `intent_metadata == {"catalog_scope":
  "pending_product_selection_restricted"}` AND the fuzzy decision
  is `"ambiguous"`
- **THEN** the hybrid decision is `"ambiguous"` regardless of the
  vector top-1 contribution
- **AND** the recognizer returns the ambiguous translation above
- **AND** the scoring formula is preserved verbatim

#### Scenario: 4.11.5 guard does NOT fire at runtime for normal commerce-catalog recognition

- **WHEN** `intent_metadata is None` AND the fuzzy decision is
  `"ambiguous"`
- **THEN** the hybrid decision follows the calibrated scoring rule
- **AND** the 4.11.5 guard does NOT force the decision to `"ambiguous"`

#### Scenario: 4.11.5 guard does NOT fire when intent_metadata carries a non-restricted catalog_scope

- **WHEN** `intent_metadata == {"catalog_scope":
  "commerce_dynamic_database"}` AND the fuzzy decision is `"ambiguous"`
- **THEN** the hybrid decision follows the calibrated scoring rule
- **AND** the 4.11.5 guard does NOT fire

#### Scenario: 4.11.5 guard is short-circuited when intent_metadata is None

- **WHEN** the recognizer is invoked with `intent_metadata=None` AND
  the fuzzy decision would otherwise be `"ambiguous"`
- **THEN** the hybrid decision follows the calibrated scoring rule
- **AND** the recognizer does NOT raise any intent-specific exception

#### Scenario: 4.11.7 fuzzy_unique + empty_vector guard fires verbatim

- **WHEN** the fuzzy decision is `"unique"` AND `len(vector_ids) == 0`
- **THEN** the hybrid decision is `"unique"` with the fuzzy top id
  regardless of the scoring formula
- **AND** the recognizer returns the unique translation above
- **AND** the scoring formula is preserved verbatim

#### Scenario: Fuzzy fallback on embedding failure preserves the fuzzy result

- **WHEN** the embedding client raises any exception during
  `embed_query`
- **THEN** the recognizer returns the fuzzy `ProductRecognizerResult`
  unchanged (byte-for-byte)
- **AND** the recorder receives a record with
  `failure_category="embedding_failure"`
- **AND** the conversation continues with the fuzzy result the
  customer would have seen in the `"fuzzy"` mode

#### Scenario: Fuzzy fallback on vector failure preserves the fuzzy result

- **WHEN** the vector search service raises any exception during
  `search_similar`
- **THEN** the recognizer returns the fuzzy `ProductRecognizerResult`
  unchanged (byte-for-byte)
- **AND** the recorder receives a record with
  `failure_category="vector_failure"`
- **AND** the conversation continues with the fuzzy result

#### Scenario: Commerce id resolution failure skips the hybrid pipeline

- **WHEN** the injected `commerce_id_resolver` returns `None`
- **THEN** the recognizer returns the fuzzy `ProductRecognizerResult`
  unchanged (byte-for-byte)
- **AND** the embedding client and the vector search service are NOT
  invoked
- **AND** the recorder is NOT invoked

#### Scenario: Fuzzy recognizer is invoked exactly once

- **WHEN** the recognizer is called in any of the documented paths
  (unique, ambiguous, unknown, restricted, fuzzy_unique + empty_vector,
  embedding failure, vector failure, resolver returns `None`)
- **THEN** the inner `FuzzyProductRecognizer.recognize` is invoked
  exactly once
- **AND** the recognizer does NOT mutate the fuzzy result

#### Scenario: Telemetry carries the hybrid_authoritative mode field

- **WHEN** the recognizer invokes the recorder in
  `hybrid_authoritative` mode
- **THEN** the recorder log record carries `mode="hybrid_authoritative"`
- **AND** the recorder log record carries
  `hybrid_non_authoritative=False`
- **AND** the recorder log record does NOT carry the customer message,
  the raw query embedding, the embedding prompt, the source document
  text, the database credentials, a Python stack trace, or any raw
  infrastructure exception text
- **AND** the recorder log record's `vector_ids` and `vector_scores`
  are the FILTERED vector side, not the raw search results

#### Scenario: Vector result outside the received catalog is discarded

- **WHEN** the injected vector search service returns raw results
  whose `producto_presentacion_id`s include at least one id that is
  NOT present in the `catalog` argument received by
  `recognize(...)`
- **THEN** the discarded id does NOT appear in the filtered
  `vector_ids`
- **AND** the discarded id does NOT appear in the hybrid ranking
- **AND** the discarded id does NOT appear in any translated
  `ProductRecognizerResult` collection (`encontrados`,
  `encontrados_posibles`, `encontrados_no_disponibles`,
  `no_encontrados`)

#### Scenario: Candidate excluded by the 4.12A narrowed pending set cannot reappear

- **WHEN** the `catalog` argument received by `recognize(...)` is
  the 4.12A narrowed in-memory catalog projection (a strict subset
  of the original `active_intent.candidate_ids`) AND the injected
  vector search service returns raw results that include a
  `producto_presentacion_id` the 4.12A narrowing discarded
- **THEN** the discarded id does NOT appear in the filtered
  `vector_ids`
- **AND** the discarded id does NOT appear in the hybrid ranking
- **AND** the recognizer does NOT re-query or reload the full
  commerce catalog to expand the candidate set

#### Scenario: Vector result from another commerce cannot appear in the final result

- **WHEN** the `catalog` argument received by `recognize(...)` is
  the catalog for commerce `A` AND the injected vector search
  service returns raw results that include a
  `producto_presentacion_id` that belongs to commerce `B`
- **THEN** the cross-commerce id does NOT appear in the filtered
  `vector_ids`
- **AND** the cross-commerce id does NOT appear in the hybrid
  ranking
- **AND** the cross-commerce id does NOT appear in any translated
  `ProductRecognizerResult` collection

#### Scenario: Filtering every raw vector result does not trigger technical fallback

- **WHEN** every raw `producto_presentacion_id` returned by the
  injected vector search service is filtered out because none of
  them are present in `allowed_candidate_ids`
- **THEN** the recognizer does NOT fall back to the fuzzy result
- **AND** the recognizer continues with the filtered empty vector
  side (`vector_ids == []`, `vector_scores == []`)
- **AND** the fuzzy pipeline is invoked exactly once
- **AND** the recorder is invoked exactly once with the filtered
  empty vector observation

#### Scenario: Fuzzy unique + filtered empty vector activates the 4.11.7 guard

- **WHEN** the fuzzy decision is `"unique"` AND the FILTERED
  vector side is empty (whether or not the raw search returned
  results that were discarded by the catalog-scope filter)
- **THEN** the 4.11.7 guard fires verbatim
- **AND** the hybrid decision is `"unique"` with the fuzzy top id
- **AND** the recognizer returns the unique translation with
  `encontrados` containing exactly one entry

#### Scenario: Ambiguous outcome remains authoritative after filtering

- **WHEN** the calibrated policy classifies the hybrid decision
  as `"ambiguous"` AND every raw vector result that would have
  contributed to the ranking is filtered out
- **THEN** the hybrid decision is `"ambiguous"`
- **AND** the recognizer returns the ambiguous translation
- **AND** the recognizer does NOT fall back to the fuzzy result

#### Scenario: Unknown outcome remains authoritative after filtering

- **WHEN** the calibrated policy classifies the hybrid decision
  as `"unknown"` AND every raw vector result that would have
  contributed to the ranking is filtered out
- **THEN** the hybrid decision is `"unknown"`
- **AND** the recognizer returns the unknown translation
- **AND** the recognizer does NOT fall back to the fuzzy result

#### Scenario: Duplicate vector IDs are deduplicated only after scope filtering

- **WHEN** the raw vector results contain duplicate
  `producto_presentacion_id`s AND some of those duplicates are
  outside `allowed_candidate_ids`
- **THEN** the duplicates outside `allowed_candidate_ids` are
  discarded by the filter BEFORE dedupe
- **AND** the duplicates inside `allowed_candidate_ids` are
  deduplicated AFTER the filter (the strongest match wins)
- **AND** the deduped set is the only vector side consumed by
  scoring, ranking, and translation

#### Scenario: No extra catalog query is issued by the recognizer

- **WHEN** the recognizer is invoked with any `catalog` argument
  (any `intent_metadata`, including `None`,
  `"pending_product_selection_restricted"`, and
  `"commerce_dynamic_database"`)
- **THEN** the recognizer issues NO additional catalog query or
  reload (no SQLAlchemy session, no embedding-client catalog
  fetch, no vector-search-service catalog expansion)
- **AND** `allowed_candidate_ids` is derived exclusively from the
  catalog rows the caller passed

### Requirement: Recognizer is wired into the shared product-recognition boundary

The system SHALL extend
`backend/services/product_recognition_factory.py` so that
`get_product_recognizer(settings)` returns a
`HybridAuthoritativeProductRecognizer` when
`settings.product_recognizer_mode == "hybrid_authoritative"`. The
factory SHALL:

1. Construct a `FuzzyProductRecognizer` instance.
2. Resolve the calibrated policy through
   `HybridAuthoritativePolicySource.load(settings)` exactly once at
   factory call time (not lazily and not on every recognizer call). A
   failure from the loader SHALL propagate as
   `HybridAuthoritativePolicyError` so the orchestrator-import-time
   `get_product_recognizer(load_settings())` call fails closed before
   any recognizer is built.
3. Construct the embedding client (`OllamaEmbeddingClient(settings)`
   by default, overridable through `embedding_client=`), the
   per-call vector-search-service factory (using the existing
   `session_provider` injection), the hybrid authoritative recognizer
   (wrapping the fuzzy recognizer, the calibrated policy, the
   embedding client, the vector-search-service factory, an optional
   `commerce_id_resolver`, and the `ShadowMetricsRecorder`).
4. Return the hybrid authoritative recognizer.

When the effective mode is `"fuzzy"` (the default and the safe-fuzzy
fallback case), the factory SHALL return the `FuzzyProductRecognizer`
instance directly without consulting the hybrid policy path. When the
effective mode is `"shadow"`, the factory SHALL return the
`ShadowedProductRecognizer` exactly as the 4.10 spec documents.

The existing `fuzzy` and `shadow` branches of
`get_product_recognizer` SHALL remain unchanged. The orchestrator
module (`backend/intents/orchestration/agregar_producto_orchestrator.py`)
SHALL continue to call `get_product_recognizer(load_settings())` once at
module import time and SHALL continue to re-export
`detectar_productos = _product_recognizer.recognize` as a thin
wrapper that forwards `intent_metadata`. The
`agregar_producto`, `quitar_producto`, and `modificar_producto`
orchestrators SHALL remain unchanged and SHALL continue to call
`detectar_productos` through the shared boundary.

#### Scenario: Factory returns a HybridAuthoritativeProductRecognizer in hybrid_authoritative mode

- **WHEN** `get_product_recognizer(settings)` is called with
  `settings.product_recognizer_mode == "hybrid_authoritative"` and a
  valid `hybrid_authoritative_policy_path`
- **THEN** the returned recognizer is a
  `HybridAuthoritativeProductRecognizer` instance
- **AND** the wrapped inner recognizer is a `FuzzyProductRecognizer`
  instance

#### Scenario: Factory fails closed on a missing or non-eligible policy file

- **WHEN** `get_product_recognizer(settings)` is called with
  `settings.product_recognizer_mode == "hybrid_authoritative"` and a
  `hybrid_authoritative_policy_path` that does not exist (or carries
  `eligibility.status != "eligible"`)
- **THEN** the factory raises `HybridAuthoritativePolicyError`
- **AND** no recognizer is built and returned

#### Scenario: Factory returns a FuzzyProductRecognizer in fuzzy mode (unchanged)

- **WHEN** `get_product_recognizer(settings)` is called with
  `settings.product_recognizer_mode == "fuzzy"`
- **THEN** the returned recognizer is a `FuzzyProductRecognizer`
  instance (no hybrid wiring)

#### Scenario: Factory returns a FuzzyProductRecognizer after the safe-fuzzy fallback

- **WHEN** `get_product_recognizer(load_settings())` is called after
  `PRODUCT_RECOGNIZER_MODE=hybrid_active` resolved the effective mode
  to `"fuzzy"` through the safe-fuzzy fallback
- **THEN** the returned recognizer is a `FuzzyProductRecognizer`
  instance
- **AND** no hybrid policy file is read
- **AND** no `HybridAuthoritativeProductRecognizer` is constructed

#### Scenario: Factory returns a ShadowedProductRecognizer in shadow mode (unchanged)

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
  re-exported from the orchestrator module as a thin wrapper that
  forwards `intent_metadata`
- **AND** the import fails closed with `HybridAuthoritativePolicyError`
  when the policy path is missing or non-eligible in
  `hybrid_authoritative` mode

### Requirement: Recognizer preserves existing 4.5–4.11 module surfaces

The Subphase 4.5–4.11 public surfaces — the
`ProductEmbeddingDocumentBuilder`, the `OllamaEmbeddingClient`,
the `ProductoPresentacionEmbeddingIndexer` /
`ProductoPresentacionEmbeddingSeeder`, the
`ProductoPresentacionEmbeddingAdminService`, the
`CatalogEmbeddingSynchronizationService`, the
`ProductPresentationVectorSearchService`, the
`ProductoPresentacionEmbeddingSearchRepository`, the
`ProductPresentationVectorMatch` dataclass, the
`backend/recognizers/product_recognizer`, the `FuzzyProductRecognizer`,
the `ProductRecognizerProtocol` contract, the `ProductRecognizerResult`
typed dict, the `ShadowedProductRecognizer` decorator, the
`ProductRecognitionShadowService`, the `ProductRecognitionShadowComparison`
and `ProductRecognitionHybridObservation` dataclasses, the
`ShadowMetricsRecorder`, the calibration runner, the calibration policy
module, the calibration report module, the calibration dataset, and the
calibration policy grid — SHALL remain unchanged by this capability.
The `HybridAuthoritativeProductRecognizer` and the
`HybridAuthoritativePolicySource` SHALL NOT import or subclass any of
the 4.5–4.11 modules they do not need (the embedding client protocol,
the 4.9 vector search service, the `HybridDecisionPolicy` dataclass,
the `ShadowMetricsRecorder`, and the `FuzzyProductRecognizer`).

#### Scenario: 4.5–4.11 modules are not imported by the new modules

- **WHEN** the
  `backend/services/hybrid_authoritative_policy_source.py` and
  `backend/services/hybrid_authoritative_recognizer.py` modules are
  inspected
- **THEN** they do NOT import `ProductEmbeddingDocumentBuilder`,
  `ProductoPresentacionEmbeddingIndexer`,
  `ProductoPresentacionEmbeddingSeeder`,
  `ProductoPresentacionEmbeddingAdminService`,
  `CatalogEmbeddingSynchronizationService`,
  `ProductoPresentacionEmbeddingStatusRepository`,
  `ProductoPresentacionEmbeddingIndexRepository`,
  `backend.routers.admin_product_embeddings`, the calibration runner,
  the calibration report module, the calibration commerce catalog
  module, or any 4.7 schema

#### Scenario: 4.5–4.11 focused tests remain green

- **WHEN** the existing 4.5, 4.6, 4.7, 4.8, 4.9, 4.10, 4.10.1, 4.11,
  4.11.1, 4.11.2, 4.11.3, 4.11.4, 4.11.5, 4.11.6, and 4.11.7 focused
  tests are executed after this capability lands
- **THEN** they continue to pass without modification
- **AND** fuzzy and shadow behaviour is preserved verbatim
- **AND** the calibration runner still produces the same JSON report
  with `selected_policy` and `eligibility.status == "eligible"`

### Requirement: Reusable contract test surface for the hybrid authoritative path

The system SHALL provide focused pytest tests in
`backend/tests/test_controlled_hybrid_product_recognition.py` that
exercise the `HybridAuthoritativePolicySource`, the
`HybridAuthoritativeProductRecognizer`, the safe-fuzzy fallback,
and the shared `RecognizeContext` boundary without requiring an LLM,
an embedding client transport, a real PostgreSQL session, or
production database state. The tests SHALL cover:

1. The safe-fuzzy fallback:
   - the env value `hybrid_active` resolves the effective mode to
     `"fuzzy"` and emits one structured warning carrying
     `configured_mode`, `effective_mode`, and `reason`;
   - the env value `HybridAuthoritative` (capitalised typo) resolves
     to `"fuzzy"` with the same warning shape;
   - the env value empty string resolves to `"fuzzy"` with the same
     warning shape;
   - the safe-fuzzy fallback resolves the factory to the
     `FuzzyProductRecognizer` without consulting the hybrid policy
     file and without constructing the
     `HybridAuthoritativeProductRecognizer`;
   - the safe-fuzzy fallback does NOT raise
     `InvalidProductRecognizerMode` from the env-var resolver;
   - the safe-fuzzy fallback does NOT load the hybrid policy file
     when `HYBRID_AUTHORITATIVE_POLICY_PATH` points at a missing or
     invalid path.
2. The `hybrid_authoritative_policy_path` validator:
   - non-`None` non-`str` raises `InvalidHybridAuthoritativePolicyPath`
     when the effective mode is `"hybrid_authoritative"`;
   - empty `str` raises `InvalidHybridAuthoritativePolicyPath` when
     the effective mode is `"hybrid_authoritative"`;
   - the validator does NOT run when the effective mode is `"fuzzy"`
     (including the safe-fuzzy fallback) or `"shadow"`.
3. The policy loader: valid eligible file yields the documented
   `HybridDecisionPolicy` instance.
4. The recognizer protocol surface: assignable to
   `ProductRecognizerProtocol`, four-key result contract preserved,
   `intent_metadata` keyword accepted.
5. The runtime guards:
   - the 4.11.5 guard fires verbatim when
     `intent_metadata == {"catalog_scope":
     "pending_product_selection_restricted"}` AND the fuzzy decision
     is `"ambiguous"`;
   - the 4.11.5 guard does NOT fire when `intent_metadata is None`
     AND the fuzzy decision is `"ambiguous"`;
   - the 4.11.5 guard does NOT fire when
     `intent_metadata == {"catalog_scope":
     "commerce_dynamic_database"}` AND the fuzzy decision is
     `"ambiguous"`;
   - the 4.11.7 guard fires verbatim under the documented
     preconditions and does not fire outside them.
6. The catalog-scope filter:
   - `allowed_candidate_ids` is built exclusively from the
     `catalog` argument received by `recognize(...)`; the
     recognizer issues no additional catalog query or reload;
   - a vector result whose `producto_presentacion_id` is outside
     the received catalog is discarded before the 4.11.5 guard,
     the 4.11.7 guard, scoring, ranking, and translation;
   - a candidate excluded by the 4.12A narrowed pending set
     cannot reappear in the hybrid ranking;
   - a vector result from another commerce cannot appear in the
     final result;
   - filtering every raw vector result does NOT trigger a
     technical fallback to fuzzy;
   - fuzzy unique + filtered empty `vector_ids` activates the
     4.11.7 guard verbatim;
   - hybrid `"ambiguous"` and `"unknown"` outcomes remain
     authoritative after filtering;
   - duplicate vector IDs are deduplicated only after scope
     filtering (duplicates outside `allowed_candidate_ids` are
     dropped by the filter before dedupe).
7. The hybrid decision translation (`"unique"`, `"ambiguous"`,
   `"unknown"`) yields the documented `ProductRecognizerResult`
   shape.
8. The fuzzy fallback: embedding failure, vector failure, and
   `commerce_id_resolver` returning `None` all return the fuzzy result
   byte-for-byte.
9. The telemetry surface: the recorder receives a record carrying
   `mode="hybrid_authoritative"`, `hybrid_non_authoritative=False`,
   and no forbidden sensitive fields.
10. The shared boundary:
    - `agregar_producto`, `quitar_producto`, `modificar_producto`,
      and the `product_selection_context_resolver` all use the same
      factory-bound recognizer;
    - the `product_selection_context_resolver` detect call is the
      sole call site that passes
      `intent_metadata={"catalog_scope":
      "pending_product_selection_restricted"}`;
    - the other call sites omit the argument and continue to work
      without modification.

#### Scenario: Focused tests run without infrastructure

- **WHEN** the focused pytest file is executed in an isolated unit-
  test mode that injects a stub embedding client, stub vector search
  service, stub recorder, and stub policy source
- **THEN** it exercises the safe-fuzzy fallback, the policy loader,
  the recognizer, the guards, the fuzzy fallback, the telemetry
  surface, and the shared boundary end-to-end without importing the
  embedding client transport, the document builder, the seeder, the
  indexer, the sync service, or any router

#### Scenario: Existing focused tests remain green

- **WHEN** the existing 4.5–4.11 focused tests are executed after
  the focused pytest file lands
- **THEN** they continue to pass without modification
- **AND** no existing test file is modified by this capability
  except for the documented
  `test_settings_product_recognizer_mode.py` (safe-fuzzy fallback
  scenario replacement) and
  `test_product_recognition_factory.py` (safe-fuzzy fallback
  scenario addition)
