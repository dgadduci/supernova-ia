# Design: commerce self-service onboarding

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
  fields;
- progress derived from server-side validation, not a client-provided flag;
- no terminal state or resulting commerce FK until Phase 4.

The owner surface is server-rendered at `/onboarding`. Authentication resolves
the existing signed session principal first; only then does a narrow resolver
load or create the account for that exact immutable subject. Every draft query
is scoped by that account id. State-changing form posts require same-origin and
CSRF proof; they never accept a commerce id. Missing/tampered authentication,
an unavailable identity configuration, or persistence failure has no fallback
to email, Admin, another account or another draft.

`ComercioUsuario` (Phase 4)

- `id` internal PK;
- `cuenta_usuario_id` and `comercio_id` FKs with unique pair;
- closed enum `OWNER` for this change;
- `activo`, timestamps and optional revocation timestamp/reason category.

The draft has no provider secrets, trial counter, Admin decision, or catalogue
data. A new `Comercio` remains canonical for legal/routing fields after
completion. The migration must not mutate existing commerce/order data.

## Onboarding completion and readiness

The completion service first authorizes the account against the exact draft,
validates all required `ComercioService` data and creates the commerce in
selectable `INACTIVO`. In one transaction it creates the owner membership and
marks the exact draft completed. It does not create a channel, customer,
session, pedido, catalogue row or provider work.

Readiness is a read-only projection composed from exact facts:

| Requirement | Authority |
| --- | --- |
| Verified owner and active membership | `CuentaUsuario` / `ComercioUsuario` |
| Basic profile complete | canonical `Comercio` |
| At least one eligible active payment | commerce payment association |
| At least one eligible active delivery method | commerce delivery association |
| Channel ready | Admin/provisioning/channel resolver |
| Trial or active lifecycle | existing lifecycle/Admin authority |
| Catalogue ready | future commerce catalogue authority |

The projection reports bounded missing requirements. It cannot write a
"ready" state, set `prueba_hasta`, change quota, activate a channel or alter
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
| Invalid completion input | Preserve draft; show field-local escaped validation feedback. |
| Concurrent double completion | Exactly one commerce/membership result; other request reloads exact terminal draft. |
| Persistence failure | Roll back commerce, membership and draft terminal transition together. |
| Missing readiness prerequisite | Show exact bounded checklist item; commerce remains INACTIVO. |
| Channel/lifecycle unavailable | Existing fail-closed availability behavior; never route elsewhere. |

## Testing and release gates

Tests cover JWT verification with synthetic keys, issuer/audience/expiry
rejection, owner tenancy isolation, direct-ID tampering, generic link responses,
completion atomicity/concurrency, INACTIVO creation, readiness derivation, and
no changes to existing availability confirmation. UI checks cover server
rendered semantic landmarks, labels, focusable controls, escape-safe content,
small-screen layout snapshots and critical CTA/callback navigation.

Release requires a real visual QA pass at narrow and wide viewport sizes,
keyboard-only flow, supported-browser manual pass, production callback/domain
configuration review, and a controlled test account. No production secrets,
Supabase project changes, Railway mutation or deploy are authorized by this
design.
