# Design: commerce self-service onboarding

> **Status:** The Phase 4A/4B onboarding implementation is retained as current
> state, but further onboarding and operational handoff work is paused. The
> provider architecture below is the approved direction for the next design
> pass; it is documentation only and does not authorize implementation.

## Architecture decision

Use a three-boundary design:

```text
Public landing → Supabase magic-link identity → NovaOrders owner authorization
                                         ↓
                         private onboarding draft → atomic commerce creation
                                         ↓
               existing lifecycle/configuration/channel availability controls
```

Supabase is only the authentication system. NovaOrders stores no password.
Phase 2 creates no NovaOrders identity or authorization row: it exposes a
validated request principal containing only the immutable external `sub` and a
short-lived local session. `CuentaUsuario` is application-owned identity data
deferred to Phase 3 and `ComercioUsuario` is commerce authorization data
deferred to Phase 4; therefore a valid Supabase session alone cannot grant
access to any commerce.

## Future provider boundary: one T-C adapter per commerce

The target provider design intentionally moves the Twilio-specific edge out of
the NovaOrders core. Each commerce owns its Meta/WABA/Twilio relationship and
has one isolated T-C web service created from the shared adapter implementation.
T-C services may be distributed across multiple Railway projects as service
capacity is consumed. There is no shared NovaOrders WhatsApp sender in this
design.

```text
Twilio webhook (merchant sender)
        │ form POST + X-Twilio-Signature
        ▼
Commerce T-C adapter
        │ canonical inbound event
        ▼
NovaOrders core/order domain
        │ one idempotent outbound command
        ▼
Commerce T-C adapter ── one Twilio API send ──► merchant Twilio account
        │
        └── empty <Response></Response> acknowledgement to inbound webhook
```

The T-C adapter validates the signature before any forwarding, derives the
commerce installation from its deployment/configuration, and translates the
native form payload into a versioned canonical event. It forwards that event to
a fast core-acceptance boundary that only authenticates, deduplicates and
persists deferred work; it does not run recognition, LLM or order processing in
the provider request. After acceptance, T-C returns the empty acknowledgement
and the core later delivers an idempotent outbound command to T-C. The core
never receives the merchant webhook directly or stores the merchant's Twilio
credentials. The adapter is the only component that calls Twilio.

The empty TwiML acknowledgement is deliberately not a customer response. The
adapter must not include a `<Message>` in that acknowledgement and then send a
second API message for the same event. Exactly one real outbound API send is
created for each accepted outbound command, protected by an idempotency key and
the existing bounded retry/status policy.

The owner is responsible for Meta/Twilio registration, sender/WABA status,
templates, billing, credentials and webhook configuration. NovaOrders may later
provision a T-C service in whichever Railway project has capacity, but that
does not make the core the owner of provider assets or authorize automated
Meta/Twilio onboarding. T-C services in the same project may use Railway
private networking to reach the core; services in another project must use the
core's stable authenticated HTTPS endpoint. Sandbox and production share the
same adapter contract; only provider configuration and provider capabilities
differ.

Any invalid signature, missing edge configuration, unknown installation,
cross-commerce identifier or technical provider failure fails closed for that
commerce. If the core cannot confirm inbound acceptance, T-C returns a
non-success provider response so the provider can retry; it never acknowledges
a lost event. No fallback to another sender/channel is permitted. Diagnostics
are bounded and privacy-safe: no message bodies, phone numbers, credentials,
signatures or raw provider payloads.

## Visual experience decision

The public experience is a product surface, not an Admin variation. It uses a
small tokenized visual system shared by landing, authentication confirmation,
and onboarding screens:

- one clear primary CTA, human Spanish copy and no operational jargon;
- generous whitespace, readable type, restrained color and purposeful icons;
- a real visual hierarchy: outcome first, proof/process second, form last;
- mobile-first layout with touch targets of at least 44px;
- semantic HTML, keyboard-only completion, visible focus, labels, error text
  linked to fields, contrast meeting WCAG AA and reduced-motion support;
- no blocking hero media, autoplay, tracker dependence, or client-side-only
  essential content.

The first implementation uses Jinja templates and small local CSS assets to
fit the existing application. A new SPA/design-system platform is explicitly
out of scope. Visual acceptance requires rendered desktop and mobile review,
not only template/unit assertions.

## Phase 2 identity flow

1. Visitor selects the landing CTA and sees an email request screen.
2. The request is sent to Supabase Auth with one fixed HTTPS callback URL and
   the configured abuse guard. The answer shown is generic whether the email
   exists or not.
3. Supabase emails a single-use, time-bound magic link.
4. The server callback exchanges/verifies the provider result, validates
   signature/JWKS, issuer, audience, expiry and non-empty immutable subject,
   then establishes a short-lived local session. The callback immediately
   redirects to a clean URL; token-bearing query values are never rendered or
   logged.
5. The authenticated result is a request principal only. No account,
   membership, draft, commerce or other application row is created.
6. The visitor sees a bounded "identidad verificada; onboarding aún no
   habilitado" view. Account provisioning and private draft routing begin in
   Phase 3.

The callback accepts only the one configured exact redirect URL. Tokens,
callback URLs containing tokens, full headers and raw identity-provider errors
are never logged. Logout clears the local session/cookie and does not mutate
commerce data. The production abuse control is edge/hosting rate limiting;
CAPTCHA is deferred. If the configured guard is unavailable, link issuance
fails closed rather than falling back to an in-process permissive path.

The application settings are feature-gated and fail closed: the Supabase
project URL/issuer, exact callback URL, publishable/anon key used only for the
link request, `authenticated` audience, local session secret and HTTPS cookie
policy must be complete before the route can issue or accept a session. A
service-role key is never accepted. JWKS verification is the only local
signature path; missing/empty JWKS or unsupported signing material is an
authentication failure.

## Approved Phase 3 data model and route boundary

The following model is intentionally not part of Phase 2 and must not be
created by its callback or session dependency.

`CuentaUsuario`

- `id` internal PK;
- `supabase_subject` unique, immutable external ID;
- `activo`, `fecha_alta`, `fecha_ultima_modificacion`, `fecha_baja`.

Phase 3 does not store email or other provider profile metadata. The validated
external `sub` is its sole external identity input.

`BorradorOnboardingComercio`

- exactly one draft row per owner account, enforced by a unique owner FK;
- private owner FK, optimistic version/timestamps and structured basic-commerce
  fields, including the required immutable `slug`;
- progress derived from server-side validation, not a client-provided flag;
- no terminal state or resulting commerce FK until Phase 4A.

The owner surface is server-rendered at `/onboarding`. Authentication resolves
the existing signed session principal first; only then does a narrow resolver
load or create the account for that exact immutable subject. Every draft query
is scoped by that account id. State-changing form posts require same-origin and
CSRF proof; they never accept a commerce id. Missing/tampered authentication,
an unavailable identity configuration, or persistence failure has no fallback
to email, Admin, another account or another draft.

`ComercioUsuario` (Phase 4A)

- `id` internal PK;
- `cuenta_usuario_id` and `comercio_id` FKs with unique pair;
- closed `OWNER` role enforced by a database check and unique `(comercio_id,
  rol)` so the created commerce has exactly one owner membership;
- `activo`, timestamps and optional revocation timestamp/reason category.

The draft has no provider secrets, trial counter, Admin decision, or catalogue
data. A new `Comercio` remains canonical for legal/routing fields after
completion. The migration must not mutate existing commerce/order data.

## Phase 4A onboarding completion

The completion route resolves the authenticated subject to its exact
`CuentaUsuario`, loads the one draft for that account and locks that draft with
`FOR UPDATE`. It never accepts a commerce id or a second copy of the commerce
payload. The server recomputes completeness from persisted fields, including
`slug`, then delegates all commerce validation to the existing validation logic
through a new `ComercioService.stage_create()` seam.

`stage_create()` and the completion service only flush/stage. The caller owns
the surrounding `session.begin()` and the single commit/rollback boundary. A
successful transaction creates the commerce with the canonical `INACTIVO`
state, one active `OWNER` membership and the draft's terminal `comercio_id` /
`completado_en` values. The existing committing `ComercioService.create()`
remains unchanged for Admin callers except for delegating to the shared staging
logic.

The terminal draft stores `comercio_id` and `completado_en`; a database check
requires both to be null or both to be present, and the commerce FK is unique.
After terminal completion, draft saves are rejected. A repeated completion
locks and returns the exact existing result. A terminal draft with a missing
membership or any other inconsistent state fails closed and is not repaired by
the owner route.

The transaction creates no channel, customer, session, pedido, catalogue row,
payment, delivery, trial reservation, provider work or readiness flag.

## Phase 4B — approved read-only readiness

Phase 4B adds only a membership-scoped read projection to the existing owner
onboarding surface. It is not a configuration panel. The route resolves the
validated Supabase principal to its `CuentaUsuario`, derives the terminal
commerce from that account's single draft, and verifies an active `OWNER`
`ComercioUsuario` for that exact commerce before it reads any projection fact.
It accepts no `comercio_id` from the browser. Missing, inactive or mismatched
membership is a bounded fail-closed result and never falls back to a different
commerce.

The projection is recomputed on every GET and owns no transaction, lock, commit
or rollback. It has no mutable readiness row and does not call a mutation
service. The dashboard uses plain next-action language while keeping the
commerce in `INACTIVO`; a displayed complete checklist is never an activation
decision or an assertion that orders can be accepted.

Payment/delivery owner configuration is deferred. The existing
`CommercePaymentDeliveryConfigurationService` is an Admin-authorized mutation
boundary that owns `commit`/`rollback`; using it for owner self-service needs a
separate approval of authorization, payment-field handling, CSRF and transaction
ownership. Phase 4B must not mutate a payment/delivery bridge, lifecycle, trial,
channel, catalogue, availability, provider or outbox.

Readiness is a read-only projection composed from exact facts:

| Requirement | Authority |
| --- | --- |
| Verified owner and active membership | `CuentaUsuario` / `ComercioUsuario` |
| Basic profile complete | canonical `Comercio` |
| At least one eligible active payment | commerce payment association |
| At least one eligible active delivery method | commerce delivery association |
| Channel ready | Admin/provisioning/channel resolver |
| Trial or active lifecycle | existing lifecycle/Admin authority |
| Catalogue ready | no approved authority exists; it is not a Phase 4B prerequisite |

An eligible payment/delivery association requires both an active commerce bridge
row and an active corresponding global catalog row. Channel configuration is
reported only from its existing authoritative rows (active dedicated channel for
the commerce or active shared-channel membership); an absent, inactive or
technically indeterminate channel is reported as pending, never inferred ready.
The projection reports bounded missing requirements. It cannot write a "ready"
state, set `prueba_hasta`, change quota, activate a channel or alter
`EstadoComercio`. Only after all approved activation requirements are satisfied
may Admin use the existing lifecycle path to grant `PRUEBA` or `ACTIVO`.

## Authorization matrix

| Surface | Visitor | Authenticated owner | Admin |
| --- | --- | --- | --- |
| Landing/link request | allowed | allowed | allowed |
| Own draft | denied | own only | support view only if separately approved |
| Commerce configuration | denied | membership-scoped only | existing admin scope |
| Trial dates/counter/state | denied | read-only derived view | existing authoritative mutation |
| Channel provisioning | denied | request/status only | provisioning authority |
| Catalog future | denied | deferred | deferred |

Every owner route has one dependency that produces authenticated account plus
authorized membership. It runs before the database/service work that uses the
commerce ID. Admin dependencies remain separate; an owner JWT is never an
Admin credential and vice versa.

## Failure behavior

| Condition | Outcome |
| --- | --- |
| Link requested for any email | Same neutral confirmation screen. |
| Invalid/expired/missing provider session | Bounded sign-in-required state; no database mutation. |
| JWT/JWKS/provider configuration failure | Fail closed; generic service-unavailable state; no fallback identity. |
| Draft outside authenticated account | 404/forbidden-safe outcome; no existence disclosure or alternative draft. |
| Draft incomplete or slug invalid | Preserve the exact draft; no commerce-side write occurs. |
| Missing INACTIVO state or lifecycle misconfiguration | Fail closed; no fallback to ACTIVO, PRUEBA or another state. |
| Concurrent double completion | Exactly one commerce/membership result; other request reloads exact terminal draft. |
| Terminal draft with inconsistent membership | Fail closed; do not repair or create a second commerce. |
| Persistence failure | Caller rollback removes commerce, membership and draft terminal transition together. |
| Missing, globally inactive or technically indeterminate readiness prerequisite | Show it as pending; commerce remains INACTIVO. |
| Channel/lifecycle unavailable | Existing fail-closed availability behavior; never route elsewhere. |

## Testing and release gates

Tests cover JWT verification with synthetic keys, issuer/audience/expiry
rejection, owner tenancy isolation, direct-ID tampering, generic link responses,
completion atomicity/concurrency, slug validation, INACTIVO creation, terminal
draft idempotency, caller-owned transaction control and no forbidden side
effects. Readiness derivation is a Phase 4B gate, not a Phase 4A acceptance
requirement. UI checks cover server
rendered semantic landmarks, labels, focusable controls, escape-safe content,
small-screen layout snapshots and critical CTA/callback navigation.

Release requires a real visual QA pass at narrow and wide viewport sizes,
keyboard-only flow, supported-browser manual pass, production callback/domain
configuration review, and a controlled test account. No production secrets,
Supabase project changes, Railway mutation or deploy are authorized by this
design.
