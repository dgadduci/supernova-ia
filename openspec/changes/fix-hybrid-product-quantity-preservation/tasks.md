# Tasks
## 1. Preserve quantity at the hybrid boundary

- [x] 1.1 Replace the hard-coded unique hybrid quantity only with the existing
  deterministic parsed quantity, preserving candidate and policy authority.
- [x] 1.2 Preserve default-one, ambiguous/unknown and technical fuzzy-fallback
  behavior without transaction or observability changes.

## 2. Focused proof

- [x] 2.1 Add hybrid unit coverage for word quantities two/three, omitted
  quantity, candidate bounds and fuzzy technical fallback quantity.
- [x] 2.2 Update/add a real-hybrid local-test route regression for raw text
  quantities `1`, `2`, `3`, requiring response/snapshot/durable totals
  `1`, `3`, `6` and one line.
- [x] 2.3 Run focused pytest, Ruff, compileall, strict OpenSpec validation and
  `git diff --check`; report complete output and pre-existing failures.

## 3. Production gate

- [x] 3.1 After approved deploy, add two then three of the same exact pilot
  presentation and verify cumulative totals, correct responses, one line and
  empty pending/context.
- [ ] 3.2 Resume the product-flow TODO and consider archival only after 3.1
  succeeds and explicit user approval is given.
