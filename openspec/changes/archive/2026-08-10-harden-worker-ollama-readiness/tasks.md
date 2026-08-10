# Tasks

## 1. Specification and approval

- [x] 1.1 Record receipt-33 post-redeploy failure and receipt-34 automatic recovery.
- [x] 1.2 Define one-time readiness gate, outbound continuity, fallback, privacy and transaction boundaries.
- [x] 1.3 Obtain proposal approval before implementation.

## 2. Implementation

- [x] 2.1 Extract reusable controlled generate+embedding readiness seam without changing diagnostic CLI contract.
- [x] 2.2 Gate inbound until first successful readiness; keep bounded outbound every cycle.
- [x] 2.3 Add safe readiness/cycle observability.
- [x] 2.4 Add focused recovery, caching, outbound-continuity and privacy tests.
- [x] 2.5 Review no-mutation, lease/retry scope and startup behavior.

## 3. Validation and controlled production check

- [x] 3.1 User runs focused pytest, Ruff, compileall and strict OpenSpec validation locally.
- [ ] 3.2 Deploy with worker enabled and verify no inbound claim while readiness is false.
- [ ] 3.3 Controlled restart plus WhatsApp receipt reaches delivered outbound automatically without terminal exhaustion in readiness window.
- [x] 3.4 Review rollback and obtain separate authorization before sync/archive.
