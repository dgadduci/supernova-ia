## Why

Subphase 4.2 must move product aliases out of the fuzzy recognizer and into PostgreSQL without changing the observable recognition contract frozen in Subphase 4.1. Persisted aliases are needed to support both product-wide alternate expressions and aliases that identify one exact product-presentation while keeping recognition commerce- and candidate-scoped.

## What Changes

- Add a `producto_aliases` persistence model and migration for active normalized aliases scoped either to a product or one product-presentation.
- Enforce alias normalization, product/presentation ownership, non-empty values, and duplicate prevention within each alias scope while allowing the same alias across products.
- Add repository and service operations that return only applicable active aliases for requested product and product-presentation IDs.
- Add an idempotent seeder that resolves stable catalog identities and transfers every safely classified hardcoded product alias without hardcoded database IDs.
- Enrich caller-provided recognizer catalogs with applicable persisted aliases while preserving commerce and restricted-candidate boundaries.
- Remove the hardcoded product alias source after migration and compatibility verification; structured presentation values remain catalog data rather than aliases.
- Preserve fuzzy normalization, thresholds, scores, ordering, grouping, quantity handling, unknown handling, pending-context behavior, resolver behavior, and customer responses.

## Capabilities

### New Capabilities

- `product-alias-persistence`: Defines product-wide and product-presentation alias storage, validation, querying, seeding, scope isolation, and idempotency.

### Modified Capabilities

- `product-recognizer-contract`: Extends the caller-provided catalog projection with applicable persisted alias data while retaining the infrastructure-free protocol and frozen result contract.
- `product-recognizer`: Replaces hardcoded product aliases with caller-provided persisted aliases and constrains presentation-specific aliases to their exact product-presentation without changing fuzzy behavior.

## Impact

Affected areas include SQLAlchemy models and relationships, Alembic migrations, alias repositories and services, the product catalog projection assembled by recognition orchestration paths, the pure fuzzy recognizer's alias input handling, a new `backend.scripts.seed_product_aliases` command, and focused model/service/seeder/recognizer/integration tests. PostgreSQL becomes the authoritative alias source; no HTTP or UI administration surface, pgvector dependency, embeddings, Ollama calls, semantic recognition, resolver redesign, or pending-queue changes are introduced.
