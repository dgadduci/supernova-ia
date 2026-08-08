## 1. Provider transaction implementation

- [x] 1.1 Add a non-transaction-owning `PedidoRepository` staging helper for
  one draft pedido tied to an existing session ID.
- [x] 1.2 In `ProviderInboundMessageCoordinator`, after receipt claim and
  active-session acquisition, stage and associate a draft pedido only when
  `session.id_pedido is None`; retain one coordinator commit/rollback owner.
- [x] 1.3 Preserve invalid-context, duplicate-receipt, existing-associated
  session, pipeline, outbox, routing, and observability behavior.

## 2. Focused verification

- [x] 2.1 Extend coordinator unit tests for staging order, absence on duplicate
  paths, existing association preservation, and transaction ownership.
- [x] 2.2 Extend real PostgreSQL coordinator integration tests for first and
  existing-orderless sessions, exact one draft pedido, rollback, and retry.
- [ ] 2.3 Run and report every validation command in `proposal.md`.

## 3. Review boundary

- [x] 3.1 Do not sync, archive, deploy, run production dispatch, or perform
  direct Railway data repair as part of this change.
