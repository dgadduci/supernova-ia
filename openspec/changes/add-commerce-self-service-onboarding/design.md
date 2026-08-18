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

Supabase is only the authentication system. NovaOrders stores no password and
uses the verified external `sub` as the account's immutable identity key.
`CuentaUsuario` and `ComercioUsuario` are application-owned authorization data;
therefore deleting/updating browser claims cannot grant access to another
commerce.

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

## Identity flow

1. Visitor selects the landing CTA and sees an email request screen.
2. The request is sent to Supabase Auth with a fixed allowlisted callback URL.
   The answer shown is generic whether the account exists or not.
3. Supabase emails a single-use, time-bound magic link. Its hosted service
   manages email verification and session issuance.
4. Callback establishes the application session from a validated Supabase JWT.
   The backend validates signature/JWKS, issuer, audience, expiry and subject.
5. The account-provisioning service upserts `CuentaUsuario` by external subject
   after successful validation. Email is profile/contact data, not the stable
   authorization key.
6. The authenticated owner is redirected to its draft or dashboard.

The callback accepts only configured redirect origins. Tokens, callback URLs
containing tokens, full headers and raw identity-provider errors are never
logged. Logout clears the local session/cookie and does not mutate commerce
data. Rate-limit/CAPTCHA selection is a pre-implementation approval item;
there is no permissive fallback when the protection is unavailable.

## Data model

`CuentaUsuario`

- `id` internal PK;
- `supabase_subject` unique, immutable external ID;
- `email` and `email_verificado_en` as current verified profile projection;
- `activo`, `fecha_alta`, `fecha_ultima_modificacion`, `fecha_baja`.

`ComercioUsuario`

- `id` internal PK;
- `cuenta_usuario_id` and `comercio_id` FKs with unique pair;
- closed enum `OWNER` for this change;
- `activo`, timestamps and optional revocation timestamp/reason category.

`BorradorOnboardingComercio`

- exactly one active draft per owner for the first iteration;
- private owner FK, version/timestamps and structured basic-commerce fields;
- explicit progress marker derived from validated sections, not client input;
- terminal `completado_en` and resulting `comercio_id` after success.

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
