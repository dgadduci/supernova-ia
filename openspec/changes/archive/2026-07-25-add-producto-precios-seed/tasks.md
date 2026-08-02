## 1. Seed Data and Script

- [x] 1.1 Generate the price JSON by traversing existing product-presentations and applying category/presentation pricing policy outside the persistence script.
- [x] 1.2 Create the idempotent price seed script that reads JSON, validates references and decimal constraints, inserts missing rows, and reports inserted/skipped totals.

## 2. Verification

- [x] 2.1 Validate dataset coverage, category ranges, and presentation-dependent price relationships.
- [x] 2.2 Run the script twice against `supernova_test` and confirm second-run idempotency.
- [x] 2.3 Run the script twice against `supernova` and confirm second-run idempotency.
- [x] 2.4 Run compile, lint, type-check, and relevant regression checks; report unrelated baseline errors without changing unrelated files (compile and Ruff pass; mypy reports only pre-existing model forward-reference errors).
