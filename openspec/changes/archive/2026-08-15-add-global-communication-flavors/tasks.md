## 1. Global flavor catalog and migration

- [x] 1.1 Add the global `FlavorComunicacion` model, exports and its safe
  relationship from `Comercio`.
- [x] 1.2 Add a reversible Alembic migration that seeds canonical active
  flavors, backfills existing commerces to code `neutro`, then enforces the FK
  and non-null constraint.
- [x] 1.3 Add focused model/migration tests for uniqueness, default/backfill,
  and no assumed numeric seed ID.

## 2. Safe configuration surface

- [x] 2.1 Add read-only active flavor listing and safe flavor response schema;
  exclude `instruccion_llm` from every API/configuration response.
- [x] 2.2 Include safe selected-flavor metadata in commerce/configuration
  reads, preserving existing fields.
- [x] 2.3 Add the authenticated narrow commerce flavor-selection operation;
  accept active global IDs only and preserve caller-owned transactions.
- [x] 2.4 Add focused service/router tests for active selection, unknown and
  inactive rejection, admin auth, isolation and no instruction leakage.

## 3. Non-activation regression and validation

- [x] 3.1 Prove existing deterministic customer response output is unchanged
  for the `neutro` selection and no outbound LLM call is introduced.
- [x] 3.2 Run focused pytest, Ruff, compileall, migration upgrade and strict
  OpenSpec validation.

## 4. Pilot gate

- [x] 4.1 After approved deploy, verify an existing commerce was backfilled to
  `neutro`, an administrator can read active flavors and select another active
  flavor, and customer messages remain factually and textually unchanged.
