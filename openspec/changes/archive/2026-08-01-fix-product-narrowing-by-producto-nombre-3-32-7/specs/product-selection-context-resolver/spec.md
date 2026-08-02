# Delta Spec: product-selection-context-resolver

## ADDED Requirements

### Requirement: Presentacion-alias narrow step matches against producto_nombre

When `detectar_productos` returns zero items in `encontrados` AND an empty `encontrados_posibles`, the resolver SHALL call `_narrow_by_presentacion_alias` with the user message, the active intent, and the candidate catalog already built for the call. For each candidate row in the catalog, the resolver SHALL consider the row a match when the presentacion alias token returned by `_extraer_presentacion` (the canonical form, after the alias normalization) appears as a whole word (case-insensitive) in the candidate's `producto_nombre`. The whole-word test SHALL normalize the product name with `_normalizar_texto`, split on whitespace, and test set membership. The existing `presentacion_codigo` match path SHALL remain unchanged. The resolver SHALL then take the intersection of those matches with the active intent's `candidate_ids` (preserving the original order). When the intersection has exactly one element, the resolver SHALL return a new `ProcessedIntent` with that `producto_presentacion_id` set in `resolved_data`, the `producto_presentacion_id` requirement marked `completed`, `candidate_ids == []`, the original `cantidad` preserved, and `status == "ready"` when all required requirements are completed. When the intersection has more than one element, the resolver SHALL return a copy of the active intent with the reduced `candidate_ids`. When the intersection is empty, the resolver SHALL return the active intent unchanged. The alias table (`PRESENTACION_ALIASES`) and the `_extraer_presentacion` helper SHALL NOT be modified.

#### Scenario: Picante uniquely selects product-level alias candidate

- **WHEN** the active intent is `pending_resolution` with `candidate_ids == [Empanada de Carne Unidad, Empanada de Carne Picante Unidad]` and the message is `picante` and the catalog contains both candidates with `producto_nombre` "Empanada de Carne" and "Empanada de Carne Picante" and `presentacion_codigo` "UNIDAD" for both
- **THEN** the resolver selects only Empanada de Carne Picante Unidad, returns a new `ProcessedIntent` with `status == "ready"`, `resolved_data["producto_presentacion_id"] == 32`, `candidate_ids == []`, the original `cantidad` preserved, and the diagnostic `Completed` event records the unique selection

#### Scenario: Tradicional narrows to a single product-level alias candidate

- **WHEN** the active intent is `pending_resolution` with `candidate_ids == [Pizza Muzzarella Unidad, Pizza Muzzarella Tradicional Unidad]` and the message is `tradicional` and the catalog contains both candidates with the same `presentacion_codigo` "UNIDAD"
- **THEN** the resolver selects only Pizza Muzzarella Tradicional Unidad, returns a new `ProcessedIntent` with `status == "ready"`, `resolved_data["producto_presentacion_id"]` set to the tradicional id, `candidate_ids == []`, and the original `cantidad` preserved

#### Scenario: Discriminating fragment with a product noun narrows to single candidate

- **WHEN** the active intent is `pending_resolution` with `source_text == "1 empanada de carne"` and `candidate_ids == [Empanada de Carne Unidad, Empanada de Carne Picante Unidad]` and the message is `carne picante` and the active intent's extraneous-token guard passes (because `carne` is in the active intent's source_text)
- **THEN** the resolver returns a new `ProcessedIntent` with `resolved_data["producto_presentacion_id"]` set to the Empanada de Carne Picante id, `candidate_ids == []`, `status == "ready"`, the original `cantidad == 1` preserved, and the diagnostic `Completed` event records the unique selection

#### Scenario: Whole-word product name match rejects substring false positive

- **WHEN** the catalog contains a candidate whose normalized `producto_nombre` token list includes a token such as "picantes" (a non-canonical plural form) but does not include the exact token "picante"
- **THEN** the alias `picante` does NOT match that candidate, and the resolver's `matching_ids` excludes that candidate

#### Scenario: Existing presentacion_codigo path remains unchanged

- **WHEN** the active intent is `pending_resolution` with `candidate_ids == [Pizza Muzzarella Chica, Pizza Muzzarella Grande]` and the message is `la grande` and the catalog contains both candidates with the same `producto_nombre` "Pizza Muzzarella" and `presentacion_codigo` "CHICA" and "GRANDE"
- **THEN** the resolver matches via the existing `presentacion_codigo` path, selects Pizza Muzzarella Grande, returns a new `ProcessedIntent` with `status == "ready"`, `candidate_ids == []`, the original `cantidad` preserved, and the diagnostic `Completed` event records the unique selection

#### Scenario: Empty intersection returns the active intent unchanged

- **WHEN** the alias token does not appear in any candidate's normalized `producto_nombre` AND no candidate's `presentacion_codigo` matches the alias
- **THEN** the resolver returns the active intent unchanged (same instance), and the diagnostic `Completed` event records `status_after="pending_resolution"` and `candidate_ids_after` equal to the original `candidate_ids`

#### Scenario: Alias normalization applies to the product-name match

- **WHEN** the user message is `grandi` and the alias normalization maps `grandi` to `grande` and a candidate's `producto_nombre` contains the token "grande" as a whole word
- **THEN** the alias `grande` (the canonical form returned by `_extraer_presentacion`) matches the candidate's `producto_nombre`, and the resolver narrows to that candidate

#### Scenario: Multiple narrowed candidates keep pending_resolution

- **WHEN** the active intent is `pending_resolution` with `candidate_ids == [Empanada de Carne Picante Unidad, Empanada de Carne Picante Docena]` and the message is `picante` and both candidates have `presentacion_codigo` "UNIDAD" and "DOCENA" respectively and both have `producto_nombre` "Empanada de Carne Picante"
- **THEN** the resolver returns a copy of the active intent with `candidate_ids` reduced to both ids, `status == "pending_resolution"`, the original `cantidad` preserved, and the diagnostic `Completed` event records the narrowing

### Requirement: Discriminating fragments that span the active intent and product-level alias

When a message combines a token from the active intent's `source_text` or `resolved_data` (a "narrowing noun" such as `carne`) with a presentacion alias that lives in `producto_nombre` (such as `picante`), the extraneous-token guard added in 3.32.5 SHALL permit the narrowing, and the new product-name match predicate SHALL then resolve the candidate set. The resolver SHALL return a new `ProcessedIntent` with the single remaining `producto_presentacion_id` set, the `producto_presentacion_id` requirement marked `completed`, `candidate_ids == []`, the original `cantidad` preserved, and `status == "ready"` when all required requirements are completed.

#### Scenario: carne picante resolves to Empanada de Carne Picante

- **WHEN** the active intent is `pending_resolution` with `source_text == "1 empanada de carne"`, `candidate_ids == [31, 32]` (Empanada de Carne Unidad and Empanada de Carne Picante Unidad), and the message is `carne picante`
- **THEN** the resolver returns a new `ProcessedIntent` with `status == "ready"`, `resolved_data["producto_presentacion_id"] == 32`, `candidate_ids == []`, `cantidad == 1` preserved, and the diagnostic `Completed` event records the unique selection with the active intent's `source_text` echoed back

#### Scenario: la picante resolves to Empanada de Carne Picante

- **WHEN** the active intent is `pending_resolution` with `source_text == "una empanada de carne"`, `candidate_ids == [31, 32]`, and the message is `la picante`
- **THEN** the resolver returns a new `ProcessedIntent` with `status == "ready"`, `resolved_data["producto_presentacion_id"] == 32`, `candidate_ids == []`, the original `cantidad` preserved, and the diagnostic `Completed` event records the unique selection

#### Scenario: la de carne picante resolves to Empanada de Carne Picante

- **WHEN** the active intent is `pending_resolution` with `source_text == "una empanada de carne"`, `candidate_ids == [31, 32]`, and the message is `la de carne picante`
- **THEN** the resolver returns a new `ProcessedIntent` with `status == "ready"`, `resolved_data["producto_presentacion_id"] == 32`, `candidate_ids == []`, the original `cantidad` preserved, and the diagnostic `Completed` event records the unique selection
