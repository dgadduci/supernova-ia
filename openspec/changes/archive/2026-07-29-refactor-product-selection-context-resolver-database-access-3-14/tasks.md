## 1. Existing Layer Inventory

- [x] 1.1 Inspect current product repositories, services, model relationships, and all `ProductSelectionContextResolver` call sites.
- [x] 1.2 Select the existing service/repository extension point and document the final orchestration module location in the implementation.

## 2. Layered Catalog Loading

- [x] 2.1 Add or reuse a repository method that queries only candidate `ProductoPresentacion` IDs and eagerly loads product, presentation, and category relationships.
- [x] 2.2 Add or reuse a product service method that converts loaded rows into the exact 12-field recognizer catalog.
- [x] 2.3 Add a thin orchestration service that accepts the database session, loads the restricted catalog, and delegates to the pure context resolver without side effects.

## 3. Pure Context Resolver

- [x] 3.1 Change `resolve_product_selection` to accept `message`, `active_intent`, and the prebuilt catalog, removing SQLAlchemy, session, model, repository, and service access.
- [x] 3.2 Preserve candidate validation, unique-selection behavior, resolved-data quantity preservation, requirement updates, readiness calculation, and unchanged-result behavior.

## 4. Verification

- [x] 4.1 Add repository tests proving candidate-ID filtering and eager relationship loading.
- [x] 4.2 Add service tests proving the exact 12-field catalog shape and real activation/availability values.
- [x] 4.3 Add purity tests proving the context resolver has no database access or SQLAlchemy imports.
- [x] 4.4 Add an orchestration integration test using the real recognizer with `la grande` and verify original `cantidad` preservation.
- [x] 4.5 Run `PYTHONPATH=. venv/bin/python backend/tests/api_smoke.py` and report the final responsibility of each component.
- [x] 4.6 Run `PYTHONPATH=. venv/bin/python -m compileall backend`.
