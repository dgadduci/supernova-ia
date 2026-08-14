# Tasks

## 1. Destination-only interpretation

- [x] 1.1 Route source-omitted/destination-positive messages to
  `cantidad=None`, `cantidad_destino=M`; keep the other matrix branches and
  invalid-destination rejection unchanged.
- [x] 1.2 Preserve the two fields through existing initial and pending
  modification paths without candidate expansion or transaction control.

## 2. Focused proof

- [x] 2.1 Cover word/digit destination-only extraction, legacy source-only,
  omitted, paired, invalid and historical-pending compatibility.
- [x] 2.2 Cover ambiguous destination -> `grande`: full source -> destination
  M, exact persisted lines, response, and cleaned context/pending.
- [x] 2.3 Run focused pytest, Ruff, compileall, strict OpenSpec validation and
  `git diff --check`; report complete output and pre-existing failures.

## 3. Pilot gate

- [ ] 3.1 After approved deploy test `cambia la napolitana grande por dos
  mozzarella grande`, select `grande` if asked, and verify source full removal
  / destination +2.
- [ ] 3.2 Re-run source-only, paired and omitted quantity regressions; archive
  only with explicit user approval.
