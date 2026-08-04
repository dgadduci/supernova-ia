## 1. Characterize and Classify Existing Aliases

- [x] 1.1 Inventory every active `ALIASES_PALABRAS` entry with raw alias, recognizer-normalized alias, current canonical substitution, eligible product candidates, scope classification, matching/ranking effect, and separate legacy/test-only copies.
- [x] 1.2 Confirm that `PRESENTACION_ALIASES`, structured values such as `chica`, `grande`, `unidad`, and `1 litro`, and resolver-specific `picante`/`tradicional` behavior remain outside persisted product aliases.
- [x] 1.3 Resolve the ten mozzarella spelling aliases to exact canonical product name(s) per commerce; stop implementation and report if any required ownership remains zero-match, multi-match, or otherwise unsafe.
- [x] 1.4 Add pre-migration characterization tests for every safely owned current product alias, including normalized input, candidate IDs, ambiguity, presentation behavior, ranking, and observable scores where available.

## 2. Add PostgreSQL Alias Storage

- [x] 2.1 Create the `ProductoAlias` SQLAlchemy model with project-standard ID/timestamps, required product FK, nullable product-presentation FK, raw and normalized alias fields, active default, relationships, and model exports/import registration.
- [x] 2.2 Create a reversible Alembic migration for `producto_aliases` with project-convention foreign-key deletion behavior, lookup indexes, and partial unique indexes for product-wide and presentation-specific normalized alias scopes.
- [x] 2.3 Add migration/model tests that persist general and presentation-specific aliases, reject empty normalized aliases through the service, enforce foreign keys and both duplicate scopes, allow shared aliases across products, and inspect required indexes.
- [x] 2.4 Upgrade and downgrade the test database migration, verify unrelated product/presentation rows are unchanged, and leave the test database at Alembic head.

## 3. Implement Repository and Service Boundaries

- [x] 3.1 Add `ProductoAliasRepository` queries for create, same-scope lookup, requested product IDs, requested product-presentation IDs, active recognition data, and exact stable seed target resolution.
- [x] 3.2 Add `ProductoAliasService` normalization and validation using the recognizer-compatible normalization contract, including empty-value rejection, product-presentation ownership validation, duplicate handling, and recognition-ready grouping.
- [x] 3.3 Ensure all alias SQLAlchemy queries remain in repositories, service methods perform no commit/rollback/close/begin operations, and catalog lookups batch IDs without per-row queries.
- [x] 3.4 Add repository/service tests for active filtering, requested-ID scoping, sibling-presentation isolation, cross-commerce isolation, duplicate errors, shared aliases, and transaction ownership.

## 4. Build the Idempotent Seeder

- [x] 4.1 Implement exact stable seed definitions for every safely classified current product alias without database IDs or partial product-name matching.
- [x] 4.2 Create executable module `backend.scripts.seed_product_aliases` with one outer transaction, exact target cardinality checks, normalized same-scope idempotency checks, and inserted/unchanged/skipped/failed reporting.
- [x] 4.3 Ensure a failed required mapping aborts the transaction without silently persisting a partial set and that unrelated database aliases are never deleted or modified.
- [x] 4.4 Add seeder tests for expected first-run inserts, zero second-run inserts, no duplicates, safe failure rollback, exact target matching, cross-commerce behavior, and preservation of unrelated aliases.
- [x] 4.5 Run the seeder twice against the test database and verify the second run reports zero inserts and no failed required mappings.

## 5. Enrich Recognition Catalogs

- [x] 5.1 Extend the recognizer contract types with optional infrastructure-free alias projection data while preserving ordinary dictionaries, additional caller fields, and catalogs without aliases.
- [x] 5.2 Enrich commerce-wide recognizer catalog rows with all active general aliases for each product and only active aliases for each exact product-presentation.
- [x] 5.3 Enrich restricted `list_presentaciones_by_ids`, pending selection, active order-line removal/modification source, and modification destination catalogs using only their existing candidate/product-presentation boundaries.
- [x] 5.4 Add catalog projection tests proving inactive, unrequested, sibling-presentation, and another-commerce aliases are excluded and that alias loading is batched.

## 6. Replace the Hardcoded Product Alias Authority

- [x] 6.1 Adapt the pure fuzzy pipeline to consume caller-provided row-scoped aliases while preserving existing normalization, thresholds, scoring, segmentation, ranking, grouping, ordering, quantity, availability, and unknown handling.
- [x] 6.2 Preserve general-alias ambiguity across eligible presentations and constrain presentation-specific aliases to their exact `producto_presentacion_id`.
- [x] 6.3 Keep `PRESENTACION_ALIASES`, `_extraer_presentacion`, structured presentation matching, resolver narrowing, `detectar_productos`, and `FuzzyProductRecognizer` compatibility unchanged.
- [x] 6.4 Remove `ALIASES_PALABRAS` as a production source after persisted alias projection and compatibility tests pass; verify no fallback or second authoritative alias source remains.
- [x] 6.5 Add recognizer tests for migrated unique aliases, general aliases with multiple presentations, presentation-specific aliases, absent aliases, shared ambiguous aliases, structured presentation regression, and restricted-catalog non-expansion.

## 7. Verify Frozen Flows and Quality Gates

- [x] 7.1 Run the reusable product recognizer contract and Subphase 4.1 baseline dataset against the persisted-alias projection and verify exact, alias, ambiguous, refinement, quantity, unknown, availability, ordering, and known-limitation compatibility.
- [x] 7.2 Run focused regressions for initial `agregar_producto`, pending product selection, `quitar_producto`, and `modificar_producto` source/destination flows, including restricted candidates and cross-commerce isolation.
- [x] 7.3 Run `PYTHONPATH=. venv/bin/python -m compileall backend`, `PYTHONPATH=. venv/bin/python -m ruff check backend`, and `PYTHONPATH=. venv/bin/python -m mypy backend`; fix only issues introduced by this change.
- [x] 7.4 Run the focused alias/model/seeder/recognizer/integration tests and then `PYTHONPATH=. venv/bin/python -m pytest backend/tests/`; record any pre-existing failures separately.
- [x] 7.5 Run `openspec validate persist-product-aliases-4-2 --strict`, verify all completed task checkboxes reflect implemented and tested work, and leave the change active without synchronization or archival.
