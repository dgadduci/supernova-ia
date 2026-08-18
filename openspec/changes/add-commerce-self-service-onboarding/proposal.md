# Proposal: add commerce self-service onboarding

## Objective

Create the future-facing entry journey for NovaOrders: a public, polished and
accessible landing page that explains the product and leads a prospective
commerce through passwordless email access, initial setup, and a controlled
trial request. The journey must make a commerce feel welcomed and informed
without weakening the existing operational controls that decide whether it can
receive orders.

The first identity provider is Supabase Auth email magic link. The NovaOrders
database remains authoritative for commerce ownership, onboarding progress,
configuration readiness, lifecycle, and availability.

## Current execution path

The application is FastAPI with server-rendered Jinja panels. Phase 1 now adds
the public server-rendered landing and the transparent `/comenzar` placeholder;
neither opens a database session or accepts identity data. Every existing
business/admin route uses one global administrative token or browser Basic
authentication; there is no application user/account, JWT session, commerce
role, or self-service panel model.

`Comercio` requires complete legal, routing, address and lifecycle data, so it
cannot safely be used as a partially completed registration. `ComercioService`
is the existing authoritative create/update boundary. New commerces have no
public channel automatically: provider routing requires an explicit active
`CanalWhatsapp` configuration. `CommerceAvailabilityService` is the only
availability authority; `INACTIVO`, expired `PRUEBA`, and exhausted `PRUEBA`
are fail-closed at inbound, processing and confirmation boundaries.

Payment and delivery associations are commerce-scoped and currently
operator-configured. Catalogue ownership is intentionally deferred to a future
commerce panel; it must not be continued through Admin by this change.

## Scope

- Add a public landing and a small coherent visual language for the onboarding
  journey: product value, simple process, trust cues, a primary free-trial CTA,
  responsive layout and accessible interaction states.
- Integrate Supabase Auth email magic links. A verified Supabase JWT proves
  identity; it never grants commerce access by itself.
- Add a NovaOrders account, commerce-membership and private onboarding-draft
  model. A membership maps an authenticated account to exactly authorized
  commerce resources; the initial role is `OWNER`.
- Let a verified owner create/resume one private draft, complete basic commerce
  data, and atomically create an `INACTIVO` commerce plus its owner membership.
- Let an owner configure only its own eligible payment/delivery associations
  through a future commerce panel boundary, and request trial/channel review.
- Provide an owner-visible readiness checklist that is derived from exact
  configuration rather than a user-editable "ready" flag.
- Give Admin the existing authority to grant/extend PRUEBA, configure its
  deadline/quota, approve operational readiness, configure/verify channels,
  and activate/deactivate a commerce.
- Add safe, bounded audit/diagnostic events for onboarding milestones; no raw
  email magic links, JWTs, credentials, customer messages or payment details.

## Non-goals

- No password, password recovery, social login, MFA, SSO, billing, plan
  catalogue, invites, staff roles beyond `OWNER`, or self-service activation.
- No automatic Twilio account/number/WhatsApp provisioning, provider-secret
  exposure, channel fallback, or changes to webhook/provider/outbox logic.
- No catalogue UI, product/category/presentation/price mutations, imports, or
  Admin catalogue expansion.
- No changes to fuzzy/hybrid recognition, pending candidate behavior, global
  pedido IDs, historical orders, or `add-safe-outbound-response-styling`.
- No deletion of accounts, commerces, memberships, historical configuration,
  orders, or trial counters in this change.

## Proposed staged delivery

### Phase 0 — product and visual foundation

Approve target customer, name/voice, CTA copy, brand assets, legal/privacy
links, supported email domain policy, and the activation definition. Produce a
small design system (type scale, color tokens, spacing, buttons, form/error/
success states) and page wireframes before building screens. The visual aim is
credible, calm and operationally clear—not a generic admin form.

### Phase 1 — public acquisition surface

Add a public server-rendered landing. It contains a focused hero, three or
fewer benefit cards, an honest "how the trial works" sequence, trust/privacy
copy, and the free-trial CTA. It is mobile-first, keyboard navigable, uses
semantic headings, visible focus, sufficient contrast, no autoplaying media,
and graceful no-JavaScript content. It does not load commerce data or expose
operational routes.

### Phase 2 — passwordless identity boundary

Add the code boundary for Supabase Auth email magic links: request-link,
server callback/session establishment, logout, JWT validation and bounded
failure views. The server validates issuer, audience, expiration and
signature/key material; it does not trust frontend claims or Supabase email
metadata for authorization. This phase creates no `CuentaUsuario`,
`ComercioUsuario`, draft, commerce, migration or other application record.
The authenticated result is an in-memory/request principal containing only the
validated external subject, followed by a bounded "onboarding not yet
enabled" view. Magic-link issuance and resend requests always return a generic
response. Production rate limiting is an edge/hosting prerequisite; if the
configured abuse guard is unavailable, issuance fails closed. No CAPTCHA is
added in this phase.

### Phase 3 — account and draft ownership

Persist `CuentaUsuario` keyed by immutable external subject, plus a private
`BorradorOnboardingComercio`. An authenticated account can read/write only its
own draft. The visual flow is a short progress-aware wizard with save/resume,
plain-language field help and exact validation beside the relevant field.

### Phase 4 — create commerce and configure essentials

On completion, one onboarding application service validates the draft and
atomically creates `Comercio` in `INACTIVO`, `ComercioUsuario(OWNER)`, and a
completed draft record. The owner then configures eligible payment and delivery
associations for that exact commerce through a scoped panel; no internal HTTP
calls or Admin credential reuse.

### Phase 5 — controlled operational handoff

The owner requests review/trial. Admin performs channel setup/verification and
sets `PRUEBA` with authoritative `prueba_hasta` and
`prueba_max_pedidos`, or activates an approved commerce. The owner dashboard
shows a human-readable readiness checklist and trial usage, never controls the
counter, deadline, quota or state transition.

### Phase 6 — quality, measurement and release gate

Perform responsive/device review, accessibility testing, link/callback tests,
funnel measurement using privacy-safe aggregate events, and a small controlled
pilot. Refine wording and visual friction only from observed evidence. Do not
deploy, change Railway/Supabase secrets, sync or archive without separate user
approval.

## Roles and authoritative outcomes

| Actor | Authoritative actions |
| --- | --- |
| Visitor | Reads public landing and requests a magic link. |
| Supabase Auth | Verifies control of the email and issues a signed session/JWT. |
| Authenticated owner | Owns its draft, then only its membership-scoped commerce configuration and review request. |
| Admin operator | Approves trial/readiness, manages lifecycle limits, and provisions/verifies a provider channel. |
| Automation | Evaluates existing availability/readiness; it never expands a trial or activates a commerce. |

Expected outcomes for Phase 2 are: link requested, bounded neutral
confirmation, verified external subject, authenticated session, onboarding not
enabled, and bounded authentication failure. A missing/invalid membership,
invalid JWT, absent or misconfigured provider verification, unknown commerce,
unavailable commerce, or technical persistence error is not a valid success
state. Draft, commerce and readiness outcomes remain later-phase outcomes.

## Security, isolation and fallback

When implemented in Phase 3, the `CuentaUsuario` external subject will be
unique and immutable. `ComercioUsuario` will use unique
`(cuenta_usuario_id, comercio_id)` membership, an active flag and a closed
role set. Phase 2 has no commerce authorization boundary because it has no
application account or membership. Later commerce-panel queries must derive
scope from the authenticated membership; route IDs are selectors only and
must match it. No request may select an arbitrary commerce, inherit global
Admin access, or fall back to another account/draft/membership/channel.

JWT validation failure is fail-closed before session/database business work.
Supabase unavailability, JWKS/key fetch failure or database error fails the
request safely and does not create an account, commerce, membership, order,
channel or outbound response. A landing-page failure never opens an
administrative route. Existing Twilio signature and `CommerceAvailabilityService`
boundaries remain unchanged and are not replaced by this identity flow.

## Transactions, rollback and reversibility

Auth/JWT dependencies and readiness projections are read-only and own no
transactions. Phase 2 owns no application persistence transaction. The
onboarding completion service owns one explicit atomic
transaction only when it creates the exact commerce, owner membership and
draft completion; any failure rolls all three back. Scoped payment/delivery
services retain their established transaction ownership. Lifecycle quota
reservation stays caller-owned in `CommerceAvailabilityService`.

Rollback of a release is feature-route removal/disablement and revoking new
sessions, not deletion of persisted onboarding records. An account or commerce
can be deactivated/revoked safely; historical operational data stays intact.
The migration downgrade path requires an approved data-retention plan and is
not an automatic incident action.

## Observability

Use bounded event names/counters: landing CTA selected, link requested,
authentication accepted/rejected category, draft started/saved/completed,
commerce created, readiness state, review requested, and operator decision.
Measure aggregate funnel transitions and page errors, not raw email addresses,
JWTs, URLs with tokens, payment values, message content or provider secrets.

## Expected files

- A new public/onboarding route and server-rendered templates plus deliberately
  small scoped CSS/static assets.
- Settings and authentication dependency/adapters for Supabase JWT validation.
- Phase 2 request/callback/logout templates and routes plus focused JWT/auth
  denial tests. No account, membership, draft or migration files belong to
  this phase.
- Account, membership and draft models, repositories, schemas, services and an
  Alembic migration remain Phase 3 work.
- Scoped commerce-owner routes/views and readiness projection remain later
  phases.
- Focused tests for public UX contracts and Phase 2 authentication; tenancy
  isolation, draft/completion atomicity, lifecycle handoff and readiness tests
  remain later-phase gates.
- Spec deltas in this change only.

## Focused validation

For Phase 2, the implementer must run locally and provide complete output:

```text
PYTHONPATH=. venv/bin/python -m pytest backend/tests/test_public_onboarding_landing.py backend/tests/test_supabase_magic_link_auth.py -q
PYTHONPATH=. venv/bin/ruff check backend/config/settings.py backend/dependencies.py backend/routers/public_onboarding.py backend/auth backend/tests/test_public_onboarding_landing.py backend/tests/test_supabase_magic_link_auth.py
PYTHONPATH=. venv/bin/python -m compileall -q backend/config/settings.py backend/dependencies.py backend/routers/public_onboarding.py backend/auth
PYTHONPATH=. venv/bin/openspec validate add-commerce-self-service-onboarding --strict
git diff --check
```

The broader onboarding, tenancy, completion, readiness and lifecycle test
commands remain release gates for their respective later phases and are not a
Phase 2 acceptance requirement.

## Decisions required before implementation

1. Approve Supabase Auth hosted magic link as the initial identity provider and
   decide production-plan/domain/email-branding timing.
2. Approve whether self-service registration is public, invite-only, or both.
3. Approve brand, landing copy/assets, legal/privacy URLs, and whether product
   analytics is permitted.
4. Define trial defaults, who may extend them, and the exact Admin review SLA.
5. Decide whether a verified dedicated channel is mandatory for every new
   commerce or whether shared-channel onboarding is in scope.
6. Decide whether public activation must wait for the future commerce catalogue
   panel. Recommended: yes; no commerce receives public orders before its
   catalogue is explicitly ready.
