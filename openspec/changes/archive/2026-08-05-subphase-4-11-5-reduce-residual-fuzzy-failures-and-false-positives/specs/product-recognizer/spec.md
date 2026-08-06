## ADDED Requirements

### Requirement: typed-discriminated-union contract for `encontrados_posibles`

The `ProductRecognizerResult` typed contract at `backend/recognizers/product_recognizer_contract.py` SHALL formally type `encontrados_posibles` as a backward-compatible discriminated union containing exactly two variants:

1. the **product-level ambiguity group** — the existing `PossibleMatchGroup` (`texto_origen: str`, `productos: list[RecognizedProduct]`), preserved byte-identically (no `kind` field is added to this variant); and
2. the **category-level ambiguity group** — a new `CategoryAmbiguityGroup(TypedDict, total=True)` with the explicit discriminator `kind: Literal["category"]`, plus `categoria_nombre: str` and `texto_origen: str`. The group carries NO `productos` field and exposes NO product ids.

The `ProductRecognizerResult.encontrados_posibles` element type SHALL widen from `list[PossibleMatchGroup]` to `list[PossibleMatchGroup | CategoryAmbiguityGroup]`. The four top-level result keys (`encontrados`, `encontrados_posibles`, `encontrados_no_disponibles`, `no_encontrados`) are preserved unchanged. The `ProductRecognizerProtocol.recognize` signature is preserved unchanged. The `FuzzyProductRecognizer.recognize` adapter at `backend/recognizers/fuzzy_product_recognizer.py` continues to delegate to `detectar_productos` and to return the same `ProductRecognizerResult` shape (now widened through the union). The discriminable union is the contract; every consumer MUST branch on `group.get("kind") == "category"` (or equivalently `"kind" in group`) BEFORE accessing `productos`. The new typed contract is exported via `__all__`.

The widening is strictly backward-compatible: existing callers that operate only on the product-level variant continue to receive the existing shape (no `kind` field is added to the product-level variant). New callers that operate on the category-level variant must branch on the `kind: "category"` discriminator before accessing any field beyond the documented category-level shape.

#### Scenario: existing product-level variant shape is byte-identical

- **WHEN** the test calls `detectar_productos` with any input that produces a product-level candidate via `_extraer_candidatos` (e.g., `"pizza muzzarella"` against a catalog containing `Pizza de Muzzarella`)
- **THEN** the resulting `encontrados_posibles` entry carries exactly the fields `texto_origen` (str) and `productos` (list of dicts with the catalog fields plus `cantidad` and `texto_origen`)
- **AND** the entry does NOT carry a `kind` field
- **AND** the entry shape is byte-identical to the pre-Subphase-4.11.5 result for the same input

#### Scenario: category-level variant carries the explicit discriminator

- **WHEN** the test calls `detectar_productos("un postre", [...Postres entries...])` and the existing fuzzy pipeline produced no product-level candidate
- **THEN** the resulting `encontrados_posibles` entry carries exactly the fields `kind: "category"`, `categoria_nombre` (str), and `texto_origen` (str)
- **AND** the entry does NOT carry a `productos` list
- **AND** the discriminator check `group.get("kind") == "category"` returns `True` for the category-level entry and `False` for the product-level entry

#### Scenario: ProductRecognizerResult formally types both variants

- **WHEN** the test imports `ProductRecognizerResult`, `PossibleMatchGroup`, and `CategoryAmbiguityGroup` from `backend.recognizers.product_recognizer_contract`
- **AND** the test imports `CategoryAmbiguityGroup` as a `TypedDict` subclass
- **THEN** the type relationships resolve cleanly under `mypy --strict`
- **AND** `ProductRecognizerResult["encontrados_posibles"]` is typed as a list whose elements type-check as either `PossibleMatchGroup` or `CategoryAmbiguityGroup`
- **AND** the `ProductRecognizerProtocol.recognize` return type is `ProductRecognizerResult` (preserved unchanged)

#### Scenario: every production reader handles both variants

- **WHEN** the test inspects every production reader of `encontrados_posibles` documented in the Subphase 4.11.5 proposal (the calibration runner, the shadow service, the `agregar_producto` resolver, the `quitar_producto` recognizer and orchestrator, the `modificar_producto` recognizer and resolver, the product-selection context resolver, the order-line selection resolver, and the product modification resolver)
- **THEN** every reader branches on `group.get("kind") == "category"` BEFORE accessing `productos`
- **AND** every reader skips category-level groups safely (no candidate ids are extracted; no `KeyError` is raised)
- **AND** no unchecked `grupo["productos"]` access remains in any execution path where a category group can arrive (verified by a per-reader grep / static assertion)

#### Scenario: no unsafe direct access to `grupo["productos"]` remains

- **WHEN** the test greps the source of each adapted production reader for the literal pattern `group["productos"]` (direct dict access)
- **THEN** every occurrence is either (a) guarded by a preceding `group.get("kind") == "category"` check that `continue`s / `return`s, or (b) inside a test file (not in production code)
- **AND** no production reader does `grupo["productos"]` access without a discriminator check

### Requirement: muzarrella alias closes the residual fuzzy-misspelling gap

The document-level `ALIASES_PALABRAS` map at `backend/recognizers/product_recognizer.py:53-68` SHALL include the entry `"muzarrella": "mozzarella"`. The entry is read by the existing `_aplicar_aliases` helper (`backend/recognizers/product_recognizer.py:166-168`) during the `_normalizar_palabras_pedido` tokenization at `backend/recognizers/product_recognizer.py:170-178` and reaches the existing `_extraer_candidatos` pipeline through the same path as every other entry. The runtime alias authority (the catalog-projected aliases carried by `_row_aliases` at `backend/recognizers/product_recognizer.py:71-80`) and the Subphase 4.2 PostgreSQL alias persistence surface are unchanged. The 11 existing alias entries (including the 10 other mozzarella variants) are preserved verbatim; the new entry is added between `"mozarella"` and `"muzzarela"` to keep the mozzarella variants visually grouped.

#### Scenario: muzarrella closes the residual c1-fuzzy-vector-disagreement-muzarrella case

- **WHEN** the calibration runner evaluates the case `c1-fuzzy-vector-disagreement-muzarrella` (input `"muzarrella"`, `id_comercio: 1`, `expected_decision: unique`, `allowed_candidate_ids: [1, 2]`, expected `producto_presentacion_id: 1`)
- **THEN** the fuzzy recognizer normalizes `"muzarrella"` via `_normalizar_palabras_pedido` to the singular form
- **AND** `_aplicar_aliases` rewrites the token to `"mozzarella"` through the new `ALIASES_PALABRAS` entry
- **AND** the fuzzy matches the rewritten token against the catalog entries `pid=1` (`Pizza de Muzzarella GRANDE`) and `pid=2` (`Pizza de Muzzarella CHICA`) via the existing `_extraer_candidatos` and `_filtrar_por_tokens_clave` pipeline
- **AND** the case is classified as `correct` (the residual `real_fuzzy_recognizer_failure` for this case is eliminated)

#### Scenario: existing alias entries are preserved

- **WHEN** the test imports `ALIASES_PALABRAS` from `backend.recognizers.product_recognizer`
- **THEN** every entry in the list `["muza", "muzza", "muzarela", "muzarella", "mozarela", "mozarella", "muzzarela", "muzzarella", "musarela", "musarella", "fugazeta", "fugazetta", "napoli", "calabreza"]` is a member of the map
- **AND** every entry maps to the documented canonical form (`"mozzarella"`, `"fugazzeta"`, `"napolitana"`, `"calabresa"`)

#### Scenario: new entry is reachable through the same path as the existing entries

- **WHEN** the test calls `detectar_productos("muzarrella", [{"producto_presentacion_id": 1, "producto_nombre": "Pizza de Muzzarella", "producto_id": 1, "presentacion_id": 1, "categoria_id": 1, "categoria_nombre": "Pizzas", "presentacion_codigo": "GRANDE", "presentacion_descripcion": "Pizza grande de muzzarella", "activo": True, "disponible": True}])`
- **THEN** the result contains the entry in `encontrados` (or `encontrados_posibles`), not in `no_encontrados` and not in `encontrados_no_disponibles`
- **AND** the result shape, the per-entry fields, and the `cantidad` / `texto_origen` discipline are identical to the result the existing `"muzza"` alias entry produces

#### Scenario: new entry is documented as a static alias

- **WHEN** the test inspects the source of `ALIASES_PALABRAS`
- **THEN** the entry `"muzarrella": "mozzarella"` is a frozen constant in the module-level map
- **AND** the entry is not duplicated at runtime, not read from the database, not read from the catalog, and not read from any environment variable
- **AND** the runtime alias authority for production recognition continues to be the catalog-projected aliases carried by `_row_aliases`

### Requirement: category-scope matching signals category-level ambiguity through the typed-discriminated-union `encontrados_posibles` flow

The `detectar_productos` function SHALL include a category-scope matching pass that runs after `_extraer_candidatos` (at `backend/recognizers/product_recognizer.py:402-498`) and `_filtrar_por_tokens_clave` (at `backend/recognizers/product_recognizer.py:340-364`) and signals category-level ambiguity through the typed-discriminated-union `encontrados_posibles` flow without exposing every entry in the matched category as an ordinary product candidate. The pass builds a per-call index of the catalog's `categoria_nombre` values (lowercased and singularized via the existing `_singularizar_simple` helper at `backend/recognizers/product_recognizer.py:156-163`) and matches each significant user token from `texto_segmento` (after the existing `tokens_significativos` filter at `backend/recognizers/product_recognizer.py:343-350` that excludes `STOPWORDS`, `TAMANIOS`, `PALABRAS_CANTIDAD`, digits, and tokens shorter than 3 characters) against the index. When a significant user token matches a catalog `categoria_nombre`, the pass appends a `CategoryAmbiguityGroup` to `encontrados_posibles` carrying `kind: "category"`, `categoria_nombre` (the normalized category name), and `texto_origen` (the original segment) — the group does NOT carry a `productos` list and the matched catalog entries are NOT exposed as ordinary product candidates.

The pass is purely additive: it never removes a candidate that the existing fuzzy pipeline already produced, it never bypasses the existing `_extraer_candidatos` / `_filtrar_por_tokens_clave` / `_extraer_presentacion` / `_calcular_score` discipline, it never bypasses the `STOPWORDS` / `TAMANIOS` / `PALABRAS_CANTIDAD` filter, it never bypasses the four top-level result keys (`encontrados`, `encontrados_posibles`, `encontrados_no_disponibles`, `no_encontrados`), and it never adds a product candidate via the category-level signal. The pass runs only when the existing fuzzy pipeline produced no product candidate for the segment; when the existing pipeline produced at least one candidate, the pass is skipped (the existing behavior is preserved). The pass is deterministic (no randomness, no clock, no environment variable, no module-level state). The recognizer SHALL NOT consult `allowed_candidate_ids`, `restricted_candidate_ids`, `expected_producto_presentacion_id`, or any calibration label — the recognizer signature and the recognizer's responsibility are unchanged.

The `encontrados_posibles` element type is the typed-discriminated-union `list[PossibleMatchGroup | CategoryAmbiguityGroup]` documented under the `### Requirement: typed-discriminated-union contract for encontrados_posibles` requirement. The matched catalog entries are NOT exposed as evaluable product candidates and are NOT routed through the `encontrados` / `encontrados_posibles[].productos[]` / `encontrados_no_disponibles` split — the runner's `_flag_fuzzy_boundary_violation` (`runner.py:667-689`) does NOT fire for category-level inputs because no product ids are extracted from the category-level group (the existing `_fuzzy_ids` extraction walks `encontrados_posibles[].productos[]` and the category-level group carries no `productos`).

#### Scenario: "un postre" produces category-level ambiguity without promoting the full category as evaluable product candidates

- **WHEN** the test calls `detectar_productos("un postre", [{"producto_presentacion_id": 69, "producto_nombre": "Flan casero", "producto_id": 800, "presentacion_id": 1, "categoria_id": 4, "categoria_nombre": "Postres", "presentacion_codigo": "UNIDAD", "presentacion_descripcion": "Porción de flan casero", "activo": True, "disponible": True}, ...])` against the Subphase 4.11.4 `commerce_catalog_inventory["1"]` `Postres` entries (pids 69, 70, 71, 72)
- **THEN** `encontrados` is empty (the existing fuzzy pipeline produced no product candidate for the segment)
- **AND** `encontrados_posibles` contains exactly one category-level group with `kind: "category"`, `categoria_nombre: "Postres"`, and `texto_origen: "un postre"`
- **AND** the category-level group does NOT carry a `productos` list — the 4 `Postres` product ids are NOT exposed as evaluable product candidates and are NOT routed through the `encontrados` / `encontrados_posibles[].productos[]` / `encontrados_no_disponibles` split
- **AND** the calibration case `c1-ambiguous-postre` (input `"un postre"`, `expected_decision: ambiguous`, `allowed_candidate_ids: [69, 70, 71, 72]`) is classified as `correct` (the residual `real_fuzzy_recognizer_failure` for this case is eliminated)

#### Scenario: "otra pizza" produces category-level ambiguity without candidate-boundary violations

- **WHEN** the test calls `detectar_productos("otra pizza", [{"producto_presentacion_id": 1, "producto_nombre": "Pizza de Muzzarella", "producto_id": 771, "presentacion_id": 1, "categoria_id": 1, "categoria_nombre": "Pizzas", "presentacion_codigo": "GRANDE", "presentacion_descripcion": "Pizza grande de muzzarella", "activo": True, "disponible": True}, ...])` against the Subphase 4.11.4 `commerce_catalog_inventory["1"]` `Pizzas` entries (30 entries)
- **THEN** `encontrados` is empty
- **AND** `encontrados_posibles` contains exactly one category-level group with `kind: "category"`, `categoria_nombre: "Pizzas"`, and `texto_origen: "otra pizza"`
- **AND** the category-level group does NOT carry a `productos` list — the 30 `Pizzas` product ids are NOT exposed as evaluable product candidates
- **AND** the runner's `_flag_fuzzy_boundary_violation` (`runner.py:667-689`) does NOT fire when processing this case against `allowed_candidate_ids: [1, 2, 3, 4]` because no product ids are extracted from the category-level group (the existing `_fuzzy_ids` extraction walks `encontrados_posibles[].productos[]` and the category-level group carries no `productos`)
- **AND** the calibration case `c1-ambiguous-pizza-again` (input `"otra pizza"`, `expected_decision: ambiguous`, `allowed_candidate_ids: [1, 2, 3, 4]`) is classified as `correct` (the residual `real_fuzzy_recognizer_failure` for this case is eliminated)

#### Scenario: no allowed_candidate_ids leakage exists

- **WHEN** the test inspects `backend.recognizers.product_recognizer`
- **THEN** `inspect.signature(detectar_productos)` is unchanged (parameters: `texto: str`, `productos_presentaciones: list[dict]`)
- **AND** the module does NOT import anything named `allowed_candidate_ids`, `restricted_candidate_ids`, `expected_producto_presentacion_id`, or any calibration label
- **AND** the `_coincidencia_categoria` helper signature is `(texto_segmento: str, catalogo: list[dict]) -> str | None` and does NOT accept or expose any calibration label
- **AND** the recognizer signature and the recognizer's responsibility are unchanged

#### Scenario: ordinary product-level matches are byte-identical to the pre-4.11.5 result

- **WHEN** the test calls `detectar_productos("pizza muzzarella", [{"producto_presentacion_id": 1, "producto_nombre": "Pizza de Muzzarella", "producto_id": 771, "presentacion_id": 1, "categoria_id": 1, "categoria_nombre": "Pizzas", "presentacion_codigo": "GRANDE", "presentacion_descripcion": "Pizza grande de muzzarella", "activo": True, "disponible": True}, {"producto_presentacion_id": 2, "producto_nombre": "Pizza Napolitana", "producto_id": 772, "presentacion_id": 1, "categoria_id": 1, "categoria_nombre": "Pizzas", "presentacion_codigo": "GRANDE", "presentacion_descripcion": "Pizza grande napolitana", "activo": True, "disponible": True}])`
- **THEN** the result contains `pid=1` in `encontrados` (the existing fuzzy pipeline matched the input against `producto_nombre`)
- **AND** the category pass does NOT add a category-level group to `encontrados_posibles` because the existing pipeline already produced a candidate for the segment
- **AND** the result is byte-identical to the pre-Subphase-4.11.5 result for this input (the existing product-level `encontrados_posibles` shape is preserved — no `kind` field is added)

#### Scenario: category pass is purely additive

- **WHEN** the existing fuzzy pipeline produced at least one product candidate for the segment
- **THEN** the category pass does NOT run (the existing fuzzy pipeline result is preserved verbatim)
- **AND** the category pass does NOT add a category-level group to `encontrados_posibles`
- **AND** the category pass does NOT remove any pre-existing product candidate

#### Scenario: category pass respects the stopword / size / digit / quantity-word filter

- **WHEN** the test calls `detectar_productos("un grande postre", [{"producto_presentacion_id": 69, "producto_nombre": "Flan casero", "producto_id": 800, "presentacion_id": 1, "categoria_id": 4, "categoria_nombre": "Postres", "presentacion_codigo": "UNIDAD", "presentacion_descripcion": "Porción de flan casero", "activo": True, "disponible": True}])`
- **THEN** the tokens `un`, `grande`, `postre` are computed via the existing `tokens_significativos` filter
- **AND** `un` is excluded (PALABRAS_CANTIDAD)
- **AND** `grande` is excluded (TAMANIOS)
- **AND** `postre` is the only significant token
- **AND** the category pass matches `postre` against the catalog's `Postres` category
- **AND** the result contains a category-level `encontrados_posibles` group with `kind: "category"` and `categoria_nombre: "Postres"`

#### Scenario: category pass does not run when the input reduces to no significant tokens

- **WHEN** the test calls `detectar_productos("un de con", [{"producto_presentacion_id": 69, "producto_nombre": "Flan casero", "producto_id": 800, "presentacion_id": 1, "categoria_id": 4, "categoria_nombre": "Postres", "presentacion_codigo": "UNIDAD", "presentacion_descripcion": "Porción de flan casero", "activo": True, "disponible": True}])`
- **THEN** the tokens `un`, `de`, `con` are all excluded by the `tokens_significativos` filter
- **AND** the category pass has no significant tokens to match
- **AND** the result is `no_encontrados` containing the original segment (matching the existing recognizer behavior for no-significant-token inputs) and no category-level group is added

#### Scenario: category pass is deterministic

- **WHEN** the test calls `detectar_productos("un postre", [...same catalog as before...])` twice with the same supplied catalog
- **THEN** the two results are byte-identical (same `encontrados`, same `encontrados_posibles`, same `encontrados_no_disponibles`, same `no_encontrados`, same `cantidad`, same `texto_origen`, same `producto_presentacion_id` order, same `kind`, same `categoria_nombre`)

#### Scenario: false positives do not increase

- **WHEN** the runner evaluates the 47-case dataset
- **THEN** the 39 currently correct cases remain `correct` (no regression)
- **AND** the 4 other hybrid failures (`product-plus-presentation`, `fuzzy-misspelling-mozzarella`, `supported-mozza-alias`, `multi-word-jamon-queso-dynamic`) remain classified as `real_hybrid_recognizer_failure` (no false promotion)
- **AND** the new category-level signals do NOT promote any case to `unique` when the expected decision is `unknown`

#### Scenario: public recognizer result schema is widened through the typed union

- **WHEN** the test calls `detectar_productos` with any input that triggers the category pass
- **THEN** the returned dict has exactly the four keys `encontrados`, `encontrados_posibles`, `encontrados_no_disponibles`, `no_encontrados`
- **AND** each entry in `encontrados` preserves the documented catalog fields (`producto_presentacion_id`, `producto_id`, `presentacion_id`, `categoria_id`, `producto_nombre`, `categoria_nombre`, `presentacion_codigo`, `presentacion_descripcion`, `activo`, `disponible`) plus `cantidad` (int) and `texto_origen` (str)
- **AND** each product-level entry in `encontrados_posibles` has the documented `texto_origen` and `productos` fields and does NOT carry a `kind` field (the existing shape is preserved byte-identically)
- **AND** each category-level entry in `encontrados_posibles` has the documented `kind: "category"`, `categoria_nombre`, and `texto_origen` fields and DOES NOT carry a `productos` list
- **AND** the `FuzzyProductRecognizer.recognize` adapter at `backend/recognizers/fuzzy_product_recognizer.py` continues to delegate to `detectar_productos` and returns the same `ProductRecognizerResult` shape (widened through the union)
- **AND** the `ProductRecognizerResult` protocol at `backend/recognizers/product_recognizer_contract.py` formally types both variants in the `encontrados_posibles` element type
- **AND** the `__all__` of `backend/recognizers/product_recognizer` continues to export exactly `{"detectar_productos"}`
