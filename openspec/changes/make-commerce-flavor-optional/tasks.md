# Tasks: make commerce communication flavor optional

## 1. Specification and Migration

- [ ] 1.1 Inspect the existing flavor migration, model, creation service,
  assignment API/schema, read projections, and styler; finalize the exact
  nullable migration and downgrade contract without changing active styling
  eligibility.
- [ ] 1.2 Add a reversible migration that maps only canonical `neutro`
  assignments to `NULL`, preserves all other assignments, and makes the
  commerce foreign key nullable while retaining integrity/indexes.

## 2. Application Semantics

- [ ] 2.1 Make creation leave flavor absent and remove the runtime special case
  for a `neutro` code; absent configuration is the safe deterministic no-op.
- [ ] 2.2 Extend only the existing assignment boundary to support explicit
  clear-to-`NULL`, preserving auth, active-flavor validation, response privacy,
  and caller-owned transactions.

## 3. Focused Tests and Validation

- [ ] 3.1 Cover migration upgrade/downgrade, creation without flavor,
  assign/clear behavior, non-neutral preservation, absent-flavor deterministic
  local/provider behavior, valid-flavor styling, privacy, and transactions.
- [ ] 3.2 Run and report focused pytest, Ruff, compileall, strict OpenSpec
  validation, relevant migration checks, and `git diff --check`.

## 4. Post-Deploy Gate

- [ ] 4.1 Verify an existing commerce formerly assigned `neutro` has no flavor
  selected and produces deterministic output; verify a newly created commerce
  starts without flavor; assign `joven`, verify a permitted menu can style,
  clear the assignment, and verify it returns to deterministic output.
