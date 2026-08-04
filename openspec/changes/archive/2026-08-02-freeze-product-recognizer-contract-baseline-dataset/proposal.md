## Why

Subphase 4.1 needs a stable product-recognition boundary before semantic or vector-based matching is introduced. The current fuzzy recognizer is reached through multiple paths across the complete `backend/` package, but its shared input/output contract, handoff semantics, and representative evaluation cases are not isolated as reusable compatibility checks.

## What Changes

- Inventory every production recognizer path across `backend/`, including direct fuzzy calls, recognizer adapters, resolvers, pending-context dispatch and execution, modification source and destination recognition, and queued-intent promotion.
- Freeze the exact current input projection and four-key output contract, including names, types, nested structures, empty-value behavior, preserved catalog fields, quantity semantics, and ordering guarantees.
- Introduce a protocol and explicit type aliases or `TypedDict` definitions without changing runtime dictionary behavior.
- Keep the protocol separate from the concrete fuzzy implementation where practical; retain the existing fuzzy module and `detectar_productos` compatibility function.
- Make the existing fuzzy recognizer conform to the abstraction without changing its matching algorithm, thresholds, ranking, resolver behavior, or pending-context behavior.
- Add reusable contract tests that can run against the fuzzy implementation and future recognizer implementations.
- Add a version-controlled baseline evaluation dataset using real IDs from the existing test catalog, with restricted pending-flow catalogs for refinement cases and explicit metadata for known fuzzy limitations.
- Keep semantic, vector, Ollama, pgvector, and hybrid-recognizer work out of scope.

## Capabilities

### New Capabilities

- `product-recognizer-contract`: Defines the exact recognizer input/output types, protocol, implementation compatibility checks, and frozen observable contract used by all consumers.
- `product-recognizer-baseline-dataset`: Defines the version-controlled evaluation-case schema and validation rules for representative current product-recognition behavior and known fuzzy limitations.

### Modified Capabilities

- `product-recognizer`: Clarifies and preserves the existing fuzzy recognizer behavior while requiring compatibility with the new abstraction; no observable recognition behavior changes.

## Impact

Affected code and tests span the complete `backend/` package: `backend/recognizers/product_recognizer.py`, the separate contract and fuzzy-adapter modules, direct callers under `backend/intents/`, pending-context dispatch/execution and queue promotion, recognizer adapters, resolvers, diagnostics, and focused integration tests. A version-controlled fixture under `backend/tests/fixtures/` will use actual existing test-catalog IDs and restricted candidate catalogs. No database schema, HTTP contract, dependency installation, production catalog data, or runtime recognition behavior changes are required.
