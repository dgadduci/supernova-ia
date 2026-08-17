# Tasks: administrative catalog panel

## 1. Specification and Shared Boundaries

- [x] 1.1 Inspect each existing commerce/flavor/catalog create route and its
  service, transaction, synchronization, error, and commerce-isolation
  contract; identify the smallest shared operation needed to avoid duplicate
  orchestration.
- [x] 1.2 Finalize browser authentication and stateless same-origin CSRF
  contract without changing the JSON `X-Admin-Token` or pilot local-test
  authentication contracts.

## 2. Panel Foundation and Commerce Configuration

- [x] 2.1 Add the `backend.admin` panel package and dark, accessible,
  responsive server-rendered layout under `/admin/catalog`.
- [x] 2.2 Implement bounded commerce list/detail configuration read and
  flavor assignment/clear through the existing authoritative boundary.
- [x] 2.3 Link—but do not refactor or broaden—the existing pilot-order panel.

## 3. Catalog Navigation and Existing Creates

- [x] 3.1 Implement commerce-scoped navigation for categories, products,
  presentations, and prices without broadening queries across commerces.
- [x] 3.2 Add creation forms for only the operations currently supported;
  preserve validation, transaction ownership, and embedding synchronization
  semantics through shared application boundaries.

## 4. Focused Tests and Validation

- [x] 4.1 Add focused authentication/CSRF, view, privacy, accessibility,
  commerce-isolation, flavor, and per-create-operation regression tests.
- [x] 4.2 Run and report the exact focused pytest, Ruff, compileall, strict
  OpenSpec validation, and `git diff --check` commands determined after source
  inspection.
