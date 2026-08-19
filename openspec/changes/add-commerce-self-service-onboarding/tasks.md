# Tasks: add commerce self-service onboarding

## 0. Approval and discovery

- [x] 0.1 Inspect active/archived commerce lifecycle, payment/delivery,
  channel/Twilio, Admin Pilot, authorization and existing rendering paths.
- [x] 0.2 Verify no existing application user/account/commerce-role model;
  verify PR #99 lifecycle archive is merged into `main`.
- [x] 0.3 Define the Supabase magic-link, account/membership/draft boundary and
  preserve existing lifecycle/channel transaction ownership.
- [x] 0.4 Define staged public experience and aesthetic acceptance criteria.
- [x] 0.5 Obtain explicit approval of the Phase 2 boundary and technical
  decisions before implementation. Product decisions for later phases and
  provider configuration remain separately gated.

## 1. Phase 0 — visual and product decisions

- [ ] 1.1 Approve audience, Spanish value proposition, CTA, brand assets,
  privacy/legal destinations and product analytics consent policy.
- [ ] 1.2 Produce approved responsive wireframes for landing, request-link,
  callback, onboarding wizard, dashboard and readiness states.
- [ ] 1.3 Define visual tokens and accessibility acceptance: WCAG AA contrast,
  keyboard path, focus, labels/errors, motion and 44px touch targets.

## 2. Phase 1 — public landing

- [x] 2.1 Add a public server-rendered landing route/template and minimal
  scoped assets without reading commerce data or exposing Admin surfaces.
- [x] 2.2 Implement hero, benefits, process, transparent trial expectations,
  trust/privacy content and one primary free-trial CTA.
- [x] 2.3 Add responsive and accessibility regressions plus rendered visual QA
  at mobile and desktop widths.

## 3. Phase 2 — Supabase magic-link identity

- [x] 3.1 Add validated, feature-gated Supabase configuration, one exact HTTPS
  callback URL and secret-handling guidance; do not commit provider keys or
  service-role credentials.
- [x] 3.2 Implement link-request, callback/session and logout boundaries with
  neutral enumeration-safe request responses, clean callback redirects and
  bounded failure views.
- [x] 3.3 Implement server-side JWT validation (allowlisted signature/JWKS,
  issuer, audience, expiry and immutable subject) before application access;
  expose only a request principal and do not persist identity.
- [x] 3.4 Integrate the approved edge/hosting abuse-guard contract, fail closed
  when unavailable, defer CAPTCHA, and add focused auth/no-token/expired-
  token/misconfiguration/provider-failure tests.
- [x] 3.5 Verify Phase 2 does not add models, repositories, migrations,
  account/membership/draft persistence or commerce authorization.

## 4. Phase 3 — identity and draft persistence

- [x] 4.1 Approve the narrow Phase 3 boundary: account plus one private draft;
  defer `Comercio`, `ComercioUsuario`, readiness and all scoped commerce
  configuration to Phase 4 or later.
- [x] 4.2 Add account and onboarding-draft models/repositories, migration and
  safe unique constraints without changing historical commerce or order data.
- [x] 4.3 Add the authenticated-account resolver and a server-rendered
  `/onboarding` boundary; prove all draft reads/writes are account-scoped and
  protected by same-origin/CSRF checks.
- [x] 4.4 Implement private draft create/save/resume with a concise,
  progress-aware, accessible owner wizard; do not accept a commerce id.
- [x] 4.5 Add focused account identity, draft isolation, concurrent save,
  migration and no-commerce-side-effect tests.

## 5. Phase 4A — commerce creation and owner membership

- [x] 5.1 Extend the private draft and owner wizard with the required validated
  `slug`; recompute `completo` server-side including that field.
- [x] 5.2 Add `ComercioUsuario` with restricted FKs, unique account/commerce
  pair, unique commerce/role pair, active timestamps and a closed `OWNER`
  constraint. Add terminal draft `comercio_id` / `completado_en` columns and
  paired-nullability/uniqueness constraints.
- [x] 5.3 Extract a non-committing `ComercioService.stage_create()` that reuses
  current normalization, lifecycle-state, duplicate WhatsApp and duplicate
  slug validation. Preserve the existing committing Admin `create()` contract.
- [x] 5.4 Implement the authenticated completion route and stage-only service:
  lock the exact account-owned draft, create `INACTIVO` + `OWNER` + terminal
  draft in one caller-owned transaction, reject terminal edits, and make
  repeated completion idempotent.
- [x] 5.5 Add focused migration, atomicity, rollback, concurrency, isolation,
  idempotency, CSRF and no-side-effect tests. Do not add readiness, payments,
  deliveries, channels, trials, catalogue or provider behavior.

## 6. Phase 4B — approved read-only readiness

- [x] 6.1 Approve the narrow Phase 4B boundary: a membership-scoped,
  read-only readiness dashboard; defer payment/delivery owner mutations to a
  separately approved subphase.
- [x] 6.2 Implement the read-only readiness projection/dashboard with
  understandable next actions, no browser-selected commerce id, no mutable
  readiness/lifecycle state, and `INACTIVO` preserved.
- [x] 6.3 Add focused owner-isolation, incomplete/indeterminate readiness,
  lifecycle read-only and no-write tests.

## Pause gate — provider architecture pivot [x]

This gate records a product decision and documentation only. It does not mark
the future operational-handoff work as implemented.

- [x] Record that the current onboarding track pauses after Phase 4B while the
  owner flow and provider boundary are reconsidered.
- [x] Document the target one-commerce/one-T-C-service boundary, the ability
  to distribute T-C services across multiple Railway projects, the canonical
  core contract, empty TwiML acknowledgement and single real outbound send.
- [x] Update the permanent OpenSpec project context because the prior
  central-WhatsApp description is no longer the target architecture.
- [ ] Revisit and, if approved, rewrite the onboarding proposal, owner setup
  flow and readiness requirements before any further implementation.

Tasks below remain paused and must not be started from this documentation
update alone.

## 7. Phase 5 — controlled trial and channel handoff

- [ ] 7.1 Add an owner review/trial request state that does not mutate lifecycle
  limits or provider configuration.
- [ ] 7.2 Surface Admin's existing approved decision outcomes to the owner:
  pending, changes requested, PRUEBA, available, expired or quota exhausted.
- [ ] 7.3 Reuse existing channel provisioning/lifecycle policies; do not add a
  parallel provider pipeline or route unavailable traffic.

## 8. Phase 6 — verification and handoff

- [ ] 8.1 Run the exact focused pytest, Ruff, compileall, strict OpenSpec and
  diff checks listed in `proposal.md`; report complete output.
- [ ] 8.2 Complete visual QA: narrow/wide viewport, keyboard-only flow,
  contrast, focus, error states, links, empty/loading states and no-JS
  readability where applicable.
- [ ] 8.3 Run a controlled end-to-end test with a synthetic Supabase account
  and non-production commerce; verify no cross-commerce access or provider
  traffic is created before Admin approval.
- [ ] 8.4 Codex reviews implementation, tests, complete validation output,
  visual evidence, scope and transaction boundaries.
- [ ] 8.5 Obtain separate authorization before secrets, Supabase/Railway
  configuration, deploy, sync, archive or production activation.
