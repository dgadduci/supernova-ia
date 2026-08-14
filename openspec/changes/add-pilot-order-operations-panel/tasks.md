# Tasks

## 1. Read-only administrative boundary

- [x] 1.1 Add the panel-only Basic authentication adapter using the existing
  configured admin token, without modifying existing JSON API authentication.
- [x] 1.2 Add the bounded list/detail routes and mount them without exposing a
  public data route or a state-changing operation.

## 2. Typed order projection and templates

- [x] 2.1 Implement the read-only typed projection for exact pedido detail,
  commerce/client/session, lines, payment/delivery and provider history.
- [x] 2.2 Implement the minimal server-rendered list/detail/error templates
  with escaped values, pagination/filter controls and clear missing-value
  rendering.
- [x] 2.3 Label provider history correctly, including receipt-only inbound
  metadata and the absence of durable inbound text/session linkage.
- [x] 2.4 Stamp every visible timestamp (list, pedido, session,
  `datetime_entrega_programada`, receipt, outbound `fecha_creacion` and
  `estado_proveedor_en`) with a typed `LocalDateTimeView` derived from
  the corresponding `Comercio.zona_horaria` so the operator can read
  the wall clock without manually converting UTC. Missing or invalid
  zones fall back to UTC with the literal label `"UTC"`; the UTC
  semantics of the `from`/`to` filters are kept and the UI states it
  near the filter form.

## 3. Verification

- [x] 3.1 Add focused authentication, router, projection isolation/privacy,
  rendering/escaping, filter-bound and no-mutation tests.
- [x] 3.2 Run every focused pytest, Ruff, compileall and strict OpenSpec
  validation command from `proposal.md` locally; report complete output.
- [x] 3.3 Add focused coverage for the timezone rendering contract:
  conversion to `America/Argentina/Buenos_Aires`, instant preservation,
  invalid-zone UTC fallback, list rows with different zones, detail and
  provider-history entries using the comercio zone, explicit UTC filter
  labelling, and regression coverage for autoescape, HTTP Basic auth and
  the no-mutation contract.

## 4. Operational handoff

- [ ] 4.1 After review and approved deployment, inspect the designated pilot
  order/session using the panel and confirm it shows the required data.
- [ ] 4.2 Resume the paused pending-context production verification only after
  4.1; then follow the original dependent observation production gate.
- [ ] 4.3 Do not add a reset/cancel/close action or archive either prior
  change without a separate approved change and explicit user approval.

## 5. Debug-console amendment

- [x] 5.1 Add a typed, privacy-bounded pending-context execution-state view
  for the exact selected session: context, pending validity, active
  intent/status, counts, schema version and consistency only; never raw
  `pending_intents` or environment/configuration data.
- [x] 5.2 Render the responsive 30/30/40 detail layout: local-test chat,
  existing order detail/history, and safe execution state.
- [x] 5.3 Add the Basic-authenticated, same-origin local-test route. Revalidate
  exact active session + own draft Pedido before using the existing response
  orchestrator; keep all transaction ownership there.
- [x] 5.4 Add the browser-only transcript and bounded request/response UI.
  It must be visibly local-only, escape message text, and never create a
  provider receipt, deferred work, outbox row or Twilio send.
- [x] 5.5 Add focused state-privacy, auth/CSRF, exact-target, no-provider,
  transaction-boundary, escaping and responsive-rendering tests.
- [x] 5.6 Run the exact focused pytest, Ruff, compileall and strict OpenSpec
  validation commands added to this amendment; report complete output.

## 6. Paused dependent production gates

- [ ] 6.1 PAUSED — do not resume real WhatsApp testing for
  `fix-pilot-order-line-category-recognition`,
  `fix-pending-context-recovery-and-status-query` or
  `implement-product-line-observation-intent` until this console is deployed
  and the separate size-only order-line-selection correction has passed its
  local-test reproduction.
- [ ] 6.2 Do not archive any OpenSpec as a consequence of this amendment.

## 7. Console-refresh amendment

- [x] 7.1 Give the browser-only local-test transcript one fixed scroll
  viewport that cannot expand the three-column console.
- [x] 7.2 Return a typed, closed updated execution-state snapshot after a
  successful exact local-test turn and replace only the existing state cells
  with escaped text, without a page reload. The post-turn projection reloads
  the exact Pedido/Session identity via a dedicated helper that does NOT
  re-apply the pre-turn ``borrador``-only eligibility contract, so a
  legitimate ``borrador → ingresado`` turn still surfaces the refreshed
  snapshot.
- [x] 7.3 Add focused fixed-viewport, response/privacy, DOM-update,
  rejection-preservation, auth/exact-target/no-provider and transaction
  boundary regression coverage (including the confirm-order
  ``borrador → ingresado`` regression and the "identity truly gone"
  rejection regression); run and report the amendment validation commands.

## 8. Consistent compact-state amendment

- [x] 8.1 Project the successfully parsed canonical empty pending state as
  `empty` without changing pending persistence, dispatch or transactions.
- [x] 8.2 Compact the diagnostic layout: execution-state `nombre: valor`
  pairs, 12rem scrolling transcript, compact local-only notice below chat,
  and bounded scrolling order-lines container.
- [x] 8.3 Add focused projection, layout/selector, scrolling, escaping and
  regression coverage; run and report the amendment validation commands.
