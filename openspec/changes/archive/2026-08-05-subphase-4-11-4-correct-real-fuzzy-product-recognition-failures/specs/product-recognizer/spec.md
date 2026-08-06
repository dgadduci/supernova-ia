## ADDED Requirements

### Requirement: Fuzzy recognizer receives the full runtime-compatible commerce catalog for database-backed calibration cases

When the fuzzy product recognizer is invoked against a `catalog_scope: "commerce_dynamic_database"` calibration case, the caller MUST hand the recognizer the **full runtime-compatible commerce catalog** for the case's `id_comercio` — every commerce-scoped `producto_presentacion` entry that the real runtime catalog assembly would provide, including entries whose availability flags are `false` — exactly as the runtime call sites (`backend/intents/context/product_selection_context_resolver.py:165` and the matching paths in `product_modification_resolver.py`, `quitar_producto_recognizer.py`, `modificar_producto_recognizer.py`, and the manual loader at `backend/tests/manual_product_recognizer.py::_load_catalog`) hand the recognizer the runtime catalog.

The catalog MUST include every commerce-scoped `producto_presentacion` row for `id_comercio` returned by the real runtime catalog assembly, regardless of any expected-case field. No inactive or unavailable entry may be filtered out before recognition. The catalog entry shape MUST be the documented runtime field set:

- `producto_presentacion_id` (int);
- `producto_id` (int);
- `presentacion_id` (int);
- `categoria_id` (int);
- `producto_nombre` (str);
- `categoria_nombre` (str);
- `presentacion_codigo` (str);
- `presentacion_descripcion` (str);
- `activo` (bool);
- `producto_activo` (bool);
- `presentacion_activo` (bool);
- `disponible` (bool).

Entries MUST be sorted by `producto_presentacion_id` ascending. Inactive and unavailable entries (where any of `activo`, `producto_activo`, `presentacion_activo`, `disponible` is `false`) MUST remain present in the catalog with their original flags preserved exactly and MUST be classified by the recognizer's existing `disponibles` / `encontrados_no_disponibles` split (`backend/recognizers/product_recognizer.py:543-561`): available matches remain in `disponibles`; unavailable or inactive matches remain in `encontrados_no_disponibles`.

No expected-case field MAY influence catalog construction. Specifically, `allowed_candidate_ids`, `restricted_candidate_ids`, `expected_decision`, `expected_producto_presentacion_id`, `expected_producto_presentacion_id_ref`, and any other label MUST NOT be consulted when the catalog is built. The catalog is determined solely by `id_comercio` and the current PostgreSQL state (loaded fresh from the database at calibration time, never read from the persisted `commerce_catalog_inventory`).

The fuzzy recognizer contract documented under the existing `### Requirement: Fuzzy baseline product recognition`, `### Requirement: Product name normalization`, and any other fuzzy requirement is preserved verbatim; this requirement governs the catalog assembly performed by the calibration caller, not the recognizer implementation.

#### Scenario: Catalog contains every commerce-scoped producto_presentacion entry returned by the real runtime catalog assembly

- **WHEN** the calibration runner evaluates a `commerce_dynamic_database` case whose `id_comercio == 1` and whose fresh DB load returns every commerce-scoped `producto_presentacion` entry returned by the real runtime catalog assembly (active and inactive alike, with all four runtime flags preserved)
- **THEN** the fuzzy recognizer is invoked with a catalog that contains exactly those entries
- **AND** the entries are sorted by `producto_presentacion_id` ascending
- **AND** every entry carries the documented field set with its original availability flags
- **AND** the catalog handed to the recognizer is the fresh DB catalog — not the persisted `commerce_catalog_inventory`, even when both contain the same entries

#### Scenario: Catalog does not narrow on allowed_candidate_ids

- **WHEN** a case has `allowed_candidate_ids = [1, 9, 39]` but the fresh DB catalog for `id_comercio == 1` contains 80 entries
- **THEN** the catalog handed to the recognizer contains all 80 entries
- **AND** entries for ids `1`, `9`, `39` are not specially marked, sorted differently, or removed
- **AND** `allowed_candidate_ids` is used only by the evaluator after recognition

#### Scenario: Catalog does not narrow on expected_producto_presentacion_id

- **WHEN** a case has `expected_producto_presentacion_id = 33` but the fresh DB catalog for `id_comercio == 1` contains 80 entries
- **THEN** the catalog handed to the recognizer contains all 80 entries
- **AND** the entry for id `33` is not specially marked, scored differently, or removed

#### Scenario: Restricted candidates remain present in the catalog

- **WHEN** a case has `restricted_candidate_ids = [9]` and the fresh DB catalog for `id_comercio == 1` contains entries for ids `[1, 9, 39, ...]`
- **THEN** the catalog handed to the recognizer contains the entry for id `9`
- **AND** the evaluator flags id `9` as a boundary violation only if the recognizer returns it as a candidate
- **AND** no pre-recognition removal of id `9` happens

#### Scenario: Entries from another commerce are absent

- **WHEN** a case has `id_comercio == 1` and the fresh DB catalog for commerce `1` contains 80 entries
- **THEN** the catalog handed to the recognizer contains only entries from commerce `1`
- **AND** no entry from commerce `2` (or any other commerce) is present

#### Scenario: Inactive and unavailable entries are present with their original flags and classified by the recognizer

- **WHEN** the fresh DB catalog for `id_comercio == 1` contains an entry with `producto_activo == false`, `activo == false`, `presentacion_activo == false`, or `disponible == false`
- **THEN** the catalog handed to the recognizer contains that entry
- **AND** the entry's four runtime availability flags (`activo`, `producto_activo`, `presentacion_activo`, `disponible`) are preserved exactly
- **AND** the recognizer classifies it under `encontrados_no_disponibles` (or equivalent unavailable surface) per the existing `disponibles` / `encontrados_no_disponibles` split
- **AND** matching available entries still appear in `disponibles`
- **AND** no inactive entry is silently removed before recognition

#### Scenario: Competing product outside allowed_candidate_ids is present and reachable

- **WHEN** the fresh DB catalog for `id_comercio == 1` contains an entry whose `producto_nombre` is a strong fuzzy match for the case's input text and whose `producto_presentacion_id` is NOT in the case's `allowed_candidate_ids`
- **THEN** the catalog handed to the recognizer contains that entry
- **AND** the recognizer MAY return it as a candidate
- **AND** the evaluator flags it as a boundary violation (or out-of-allowed) at evaluation time, not at catalog construction time

#### Scenario: 11 preserved in-memory cases continue to use embedded catalogs

- **WHEN** the runner evaluates a `catalog_scope: "in_memory"` case (one of the 11 preserved Subphase 4.11 cases)
- **THEN** the full-commerce catalog path is not used
- **AND** the case's embedded `catalogs[*].entries` is passed to the fuzzy recognizer unchanged
- **AND** the existing Subphase 4.11 fuzzy decision semantics are preserved
