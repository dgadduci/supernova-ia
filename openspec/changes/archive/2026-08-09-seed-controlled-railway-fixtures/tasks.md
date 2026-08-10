## 1. Approval

- [x] 1.1 Review and approve the fixture identities, fixed catalog, fixed
  prices, and the rule that only the dedicated-labelled commerce may later use
  the existing sender.
- [x] 1.2 Confirm the Railway PostgreSQL target is empty for all fixture-owned
  tables. The local database is preserved and is neither cleaned nor used as a
  source.
- [x] 1.3 Approve the CLI contract: default verification, explicit apply,
  one transaction, idempotent exact rerun, conflict refusal, and sanitized
  output.

## 2. Implementation

- [x] 2.1 Implement the static fixture definitions and a narrow staging
  service without transaction-control calls. The service owns the
  `estado_comercio` table together with the catalog tables; the
  fixture creates the single `ACTIVO` `estado_comercio` row as part of
  the dataset and refuses to operate against any pre-existing row in
  `estado_comercio` (including a pre-existing `ACTIVO`).
- [x] 2.2 Implement the internal fixture CLI with `--verify-only` default,
  explicit `--apply`, empty-target guard, single allowed `flush`, exact
  post-flush verification on the same session, one commit only when the
  verification is exact, rollback on every exception and on every
  non-exact verification result, and safe aggregate output. The CLI is
  the sole owner of one setup transaction; the service, helpers and the
  runtime relationships never call `commit`, `rollback`, `begin` or
  `flush`. The CLI exposes a `verification_recorder` hook so the focused
  order test asserts the exact sequence
  `flush → verify → commit`.
- [x] 2.3 Reuse current catalog models without modifying them; add
  transient back-reference ``relationship`` attributes at import time so
  the staging code can use ORM relationship assignments (e.g.
  ``cat._runtime_comercio = c``) and the unit of work resolves the FK
  dependency graph at the single CLI ``flush`` time. Do not modify
  legacy seed scripts, migrations, HTTP routers, or the WhatsApp
  runtime.
- [x] 2.4 Do not create `CanalWhatsapp`, shared memberships, routing codes,
  real clients, orders, or messages. The fixture dataset contains no
  E.164 destinations, no phone numbers and no other forbidden
  identifiers; the `Comercio.whatsapp` field uses a non-telephone
  identifier (`FIXTURE:DEDICADO`, `FIXTURE:COMPARTIDO-UNO`,
  `FIXTURE:COMPARTIDO-DOS`) that is the minimum value allowed by the
  model and does not represent a number or destination.

## 3. Focused verification

- [x] 3.1 Add focused tests for verification no-op, empty-target guard
  (including `estado_comercio` empty), first apply (creates the single
  `ACTIVO`), exact rerun, counts, product-presentation mapping, price
  coverage, conflict refusal on pre-existing `ACTIVO` in `estado_comercio`,
  conflict refusal on pre-existing non-`ACTIVO` in `estado_comercio`,
  conflict refusal on pre-existing catalog data, rollback on mid-apply
  failure, redacted output, per-comercio exact verification, E.164
  absence in data and output, single CLI flush, exact post-flush
  verification, observable `flush → verify → commit` order,
  `conflict`+rollback when post-flush verification returns `False`,
  zero `flush`/`commit`/`rollback`/`begin` in service, and per-comercio
  corruption of categories, products, one wrong association and one
  wrong price.
- [x] 3.2 Run focused pytest, Ruff, compileall, strict OpenSpec
  validation, and `git diff --check`; report complete output for review.
  See the "Validation report" section at the bottom of this change for
  the full captured output.

## 4. Railway operation

- [x] 4.1 After implementation approval and deployment, run verify-only once
  in Railway and retain sanitized statuses/counts only.
- [x] 4.2 If and only if the target is confirmed empty and status is
  `not_ready`, run one explicit apply and repeat verification.
- [ ] 4.3 Only after `ready`, resume the active pilot's dedicated routing
  provisioning for `piloto-whatsapp-dedicado`; shared routing remains out of
  scope.

## 5. Review and follow-up

- [x] 5.1 Review the complete focused validation and sanitized Railway
  evidence.
- [ ] 5.2 Propose shared-channel provisioning only after a second real
  destination is available; do not extend this change opportunistically.
- [ ] 5.3 Deferred technical debt: the fixture service's transient runtime
  relationship for ``Precio._runtime_producto_presentacion`` emits a SQLAlchemy
  overlap warning with ``ProductoPresentacion.precios`` during mapper
  configuration. Address it only in a separately approved scoped change; do
  not modify catalog models or expand this fixture change during Railway
  operation.
