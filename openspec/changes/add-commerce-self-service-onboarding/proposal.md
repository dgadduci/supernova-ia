# Proposal: add commerce self-service onboarding

## Status and pause decision

Phase 4A commerce creation and the Phase 4B read-only readiness projection are
complete. Further onboarding work is paused by product decision while the
provider boundary is redesigned. In particular, the current Phase 5 trial and
channel-handoff path must not be implemented, synced or archived as if it were
still the target architecture.

The future target is a commerce-isolated Twilio edge: each commerce owns its
Meta/Twilio account, sender and credentials and runs one small T-C web service.
Those services reuse one adapter implementation and may be distributed across
multiple Railway projects when a project reaches its service capacity;
NovaOrders remains the central order domain and data store. Revisiting the
owner wizard, review flow and readiness requirements is deferred until this
boundary is specified in an approved implementation change. This document
records the direction; it does not authorize implementation of the adapter or
a rewrite of onboarding.

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

The current Twilio webhook path is a central application path and is retained
only as historical/current-state context for the already completed work. It is
not the target for new commerce onboarding. The target provider boundary is
documented below and must be implemented as a separately approved, isolated
adapter change before the onboarding flow is extended.

## Target provider architecture (documented, not implemented)

The target is one small T-C (Twilio–Commerce) web service per commerce, with no
shared WhatsApp sender. Multiple T-C services can live in the core Railway
project or in later Railway projects; this is a deployment-capacity decision,
not a change to commerce isolation:

```text
Customer WhatsApp
      │
      ▼
Merchant Meta/WABA/Twilio sender
      │ signed form webhook
      ▼
Commerce T-C web service
      │ normalized inbound event
      ▼
NovaOrders core ── outbound command ──► T-C adapter
      ▲                                  │
      └──────── order/business logic ◄───┘
                                         │ one real API send
                                         ▼
                                  Merchant Twilio account
```

### Ownership boundary

- The commerce owner performs and maintains the Meta/Twilio onboarding,
  sender/WABA registration, billing, templates and webhook configuration.
- The commerce's T-C service stores only the provider configuration needed by
  that commerce's integration. It validates Twilio signatures, translates the
  provider payload, sends outbound messages through the commerce's account and
  returns provider acknowledgement. The service may run in any NovaOrders
  Railway project assigned to it; it is not a separate business database.
- The NovaOrders core owns commerce identity, customer/order/session logic,
  isolation, and the normalized inbound/outbound contract. It does not store
  merchant Twilio credentials, receive the merchant's Twilio webhook directly,
  or send through a shared number.

### Message and acknowledgement contract

Twilio's inbound WhatsApp request is accepted as its native
`application/x-www-form-urlencoded` webhook. The T-C adapter validates
`X-Twilio-Signature` against the exact public URL and configured credential,
then maps the request to a versioned canonical event. The adapter must not
make the core depend on raw Twilio field names; optional provider fields are
preserved only in a bounded, privacy-safe extension area.

The T-C adapter forwards the event to a fast core-acceptance boundary. That
boundary authenticates the adapter, deduplicates the provider identifier and
durably records deferred work; it must not run recognition, LLM or order
processing in the webhook request. Only after the core confirms acceptance does
T-C immediately return an empty TwiML response
(`<Response></Response>`) to Twilio. That is an HTTP/provider acknowledgement,
not a customer message. If the core cannot confirm acceptance, T-C returns a
non-success response so Twilio can retry; it must not acknowledge a lost event.

The core processes the accepted work asynchronously, emits one outbound
command (with an idempotency key), and delivers it to T-C. T-C performs the
single real Twilio API send. T-C must not both return a `<Message>` in the
acknowledgement and send the same response through the API, because that would
duplicate the customer message and its provider charge.

The inbound path is idempotent by provider/message identifier. The outbound
path is idempotent by core command identifier and must retain the existing
bounded retry/status rules at the edge. T-C and the core must keep transaction
ownership explicit: adapters do not commit the core database, and the core
does not commit a commerce's provider-side state.

### Sandbox and production

Sandbox and production use the same canonical adapter contract and differ only
in provider configuration and capabilities. Sandbox uses Twilio's shared test
sender, join requirement and pre-approved test templates; production uses the
commerce's registered sender/WABA and its approved templates. The adapter must
not assume that sandbox-only numbers, templates or join behavior exist in
production.

### Isolation, failure and observability

The commerce identity is derived from the isolated deployment/configuration and
is not trusted from an arbitrary inbound body field. A missing or invalid
signature, missing edge configuration, unknown installation, invalid outbound
command or provider technical failure fails closed for that commerce and never
falls back to another commerce, sender or channel. Core business failures do
not cause T-C to invent a provider success or send a second message.

Logs and metrics contain only bounded event names, installation/commerce
surrogates, provider/message identifiers where operationally necessary, status
categories and latency. They must not contain message bodies, phone numbers,
credentials, signatures, access tokens, templates with customer data or raw
provider payloads.

### Deployment shape and deferred work

The core service and central PostgreSQL remain in the main NovaOrders Railway
project. Each commerce receives one T-C web service, created from the shared
adapter image/code and configured with that commerce's installation and Twilio
secrets. T-C services may be placed in the core project until its service limit
is reached and then in additional Railway projects. A T-C in another project
cannot use Railway private DNS to reach the core; it uses the core's stable
HTTPS endpoint with installation-scoped authentication. Twilio uses each T-C
service's own public HTTPS domain.

Railway plan limits and resource pricing are operational inputs, not business
guarantees; they must be rechecked before each capacity decision. Cross-project
HTTP traffic, shared-project resource contention, project-wide outages and
service provisioning rate limits must be measured before onboarding more
commerces. Project/service provisioning, secret delivery, health checks,
rotation, owner-facing setup guidance and deprovisioning require a later
implementation decision.

The following remain explicitly deferred: Meta/Twilio onboarding automation or
Embedded Signup, owner self-service correction rules, payment/delivery
configuration, catalogue loading, lifecycle activation/trial policy, a shared
WhatsApp channel, and the future native NovaOrders chat.

## Scope

- Add a public landing and a small coherent visual language for the onboarding
  journey: product value, simple process, trust cues, a primary free-trial CTA,
  responsive layout and accessible interaction states.
- Integrate Supabase Auth email magic links. A verified Supabase JWT proves
  identity; it never grants commerce access by itself.
- Add a NovaOrders account, commerce-membership and private onboarding-draft
  model. A membership maps an authenticated account to exactly authorized
  commerce resources; the initial role is `OWNER`.
- Let a verified owner create/resume one private draft, including the required
  immutable routing slug, and atomically create an `INACTIVO` commerce plus its
  owner membership.
- Keep payment/delivery associations, readiness, review requests and channel
  handoff in later phases; this phase creates no operational configuration.
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
own draft. This approved phase deliberately creates neither `Comercio` nor
`ComercioUsuario`: the latter has no valid target before commerce creation and
both records belong to the future atomic completion transaction. The visual
flow is a short progress-aware wizard with save/resume, plain-language field
help and exact validation beside the relevant field.

The minimal persisted account contains only its internal id, immutable unique
`supabase_subject`, active flag and audit timestamps. It does not project or
store an email in this phase. The draft has exactly one row per account,
version/timestamps and structured basic-commerce input; progress is derived
server-side. It has no lifecycle, catalogue, provider, channel, payment,
delivery, trial or readiness data. `GET /onboarding` and its state-changing
form submissions require the existing authenticated principal, an
account-resolution boundary and dedicated same-origin/CSRF protection. No
route accepts or authorizes a commerce id in this phase.

### Phase 4A — create commerce and owner membership

On completion, the authenticated owner submits no commerce identifier and no
second copy of the commerce payload: the application validates the exact
account-owned draft and atomically stages `Comercio` in `INACTIVO`,
`ComercioUsuario(OWNER)`, and the terminal transition of that draft.
`Comercio.slug` is collected in the draft, validated with the existing commerce
rules and remains immutable after creation.

The completion service and repositories are staging-only. The endpoint/caller
owns one explicit transaction around the commerce, membership and terminal
draft writes. Existing `ComercioService.create()` keeps its current
commit/rollback contract through a new non-committing staging seam; onboarding
does not call the committing method.

The owner sees a bounded completed state. No channel, customer, session, order,
catalogue, payment, delivery, trial, provider work or readiness projection is
created.

### Phase 4B — approved read-only readiness

Phase 4B is limited to a membership-scoped, read-only readiness dashboard with
clear next actions. It derives the exact terminal commerce from the authenticated
account-owned draft and its active `OWNER` membership; it does not accept a
browser-selected commerce id. The dashboard reports only authoritative facts:
basic commerce profile, eligible active payment/delivery associations, channel
configuration, and existing lifecycle availability. It does not persist a
mutable "ready" flag and the commerce remains `INACTIVO` throughout this phase.

Self-service payment/delivery configuration is explicitly deferred to a later
subphase. The existing Admin service owns its own commit/rollback boundary and
uses a separate Admin authorization model; reusing it for an owner would require
a separately approved owner authorization, sensitive-field and transaction
contract. Phase 4B cannot mutate lifecycle, trial, channels, catalogue,
availability, payment or delivery associations.

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
unique and immutable. When implemented in Phase 4A, `ComercioUsuario` will use
unique `(cuenta_usuario_id, comercio_id)` membership, unique
`(comercio_id, rol)` to keep one `OWNER` membership for the new commerce, an
active flag and a closed `OWNER` role constraint. Phase 2 has no commerce
authorization boundary because it has no
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
transactions. Phase 2 owns no application persistence transaction. In Phase
4A, repositories, `ComercioService.stage_create()` and the completion service
never call `commit` or `rollback`; the route/application caller owns one
explicit transaction around the exact commerce, owner membership and terminal
draft transition. Any failure rolls all three back. Existing
`ComercioService.create()` retains its current Admin-facing transaction
contract. Scoped payment/delivery services retain their established
transaction ownership. Lifecycle quota reservation stays caller-owned in
`CommerceAvailabilityService`.

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
- Account and draft models, repositories, schemas, service, owner-onboarding
  route/templates and an Alembic migration are Phase 3 work. Phase 4A adds the
  draft slug, `ComercioUsuario`, terminal draft columns, the non-committing
  commerce staging seam, completion route/templates and its migration.
- The Phase 4B read-only readiness route/template and focused isolation,
  incomplete-readiness and no-write tests extend the existing owner-onboarding
  surface. Scoped payment/delivery owner routes remain deferred work, not Phase
  4B work.
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

For the approved Phase 3 boundary, the implementer must run locally and
provide complete output:

```text
PYTHONPATH=. venv/bin/python -m pytest backend/tests/test_owner_onboarding_draft.py backend/tests/test_owner_onboarding_migration.py backend/tests/test_supabase_magic_link_auth.py -q
PYTHONPATH=. venv/bin/ruff check backend/models/cuenta_usuario.py backend/models/borrador_onboarding_comercio.py backend/repositories/cuenta_usuario_repository.py backend/repositories/borrador_onboarding_comercio_repository.py backend/services/owner_onboarding_service.py backend/routers/owner_onboarding.py backend/tests/test_owner_onboarding_draft.py backend/tests/test_owner_onboarding_migration.py
PYTHONPATH=. venv/bin/python -m compileall -q backend/models/cuenta_usuario.py backend/models/borrador_onboarding_comercio.py backend/repositories/cuenta_usuario_repository.py backend/repositories/borrador_onboarding_comercio_repository.py backend/services/owner_onboarding_service.py backend/routers/owner_onboarding.py
PYTHONPATH=. venv/bin/openspec validate add-commerce-self-service-onboarding --strict
git diff --check
```

For the approved Phase 4A boundary, the implementer must run locally and
provide complete output:

```text
PYTHONPATH=. venv/bin/python -m pytest backend/tests/test_owner_onboarding_completion.py backend/tests/test_owner_onboarding_migration.py backend/tests/test_commerce_lifecycle_policy.py -q
PYTHONPATH=. venv/bin/ruff check backend/models backend/repositories backend/services/comercio_service.py backend/services/owner_onboarding_completion_service.py backend/routers/owner_onboarding.py backend/tests/test_owner_onboarding_completion.py backend/tests/test_owner_onboarding_migration.py
PYTHONPATH=. venv/bin/python -m compileall -q backend/models backend/repositories backend/services/comercio_service.py backend/services/owner_onboarding_completion_service.py backend/routers/owner_onboarding.py
PYTHONPATH=. venv/bin/openspec validate add-commerce-self-service-onboarding --strict
git diff --check
```

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
