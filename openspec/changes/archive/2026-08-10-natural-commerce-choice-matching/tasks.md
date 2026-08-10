# Tasks

## 1. Specification and approval

- [x] 1.1 Record the production natural-phrase rejection and inspect the scoped choice path.
- [x] 1.2 Define exact-first, token-containment fallback and ambiguity/no-mutation rules.
- [x] 1.3 Obtain approval before implementation.

## 2. Implementation

- [x] 2.1 Implement the pure exact-first description-token fallback in the existing matcher only.
- [x] 2.2 Add natural payment/delivery success tests plus exact-match regression.
- [x] 2.3 Add ambiguity, foreign/inactive exclusion, whole-token and no-mutation tests.
- [x] 2.4 Review commerce isolation, transaction ownership and response compatibility.

## 3. Validation and production check

- [ ] 3.1 User runs focused pytest, Ruff, compileall and strict OpenSpec validation locally.
- [ ] 3.2 Deploy and test a clean draft WhatsApp flow with natural payment/delivery phrases, without widening choices or duplicates.
- [ ] 3.3 Review evidence and obtain separate authorization before sync/archive.
