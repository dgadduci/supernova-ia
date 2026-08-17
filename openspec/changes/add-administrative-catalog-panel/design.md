# Design: administrative catalog panel

## Decision

Add a focused `backend.admin` package within the existing backend deployment.
It owns only browser route adapters, typed panel form/view shapes, and
templates. Existing services, repositories, schemas, and domain rules remain
the authority. This avoids a second deployment and prevents the panel from
becoming a direct database console.

```text
authenticated browser
  -> reusable browser-admin Basic boundary
  -> backend.admin route/form adapter
  -> existing shared application operation
  -> existing domain services/repositories and synchronization
```

The existing `admin_pilot_orders` module is intentionally not moved. The new
panel links to it as an independent operation tool; a later, explicitly scoped
refactor may consolidate rendered panels once this foundation is stable.

## Navigation and Views

The new panel family is mounted under `/admin/catalog`:

- `/admin/catalog/comercios`: bounded commerce list, showing name, current
  state, flavor summary/no flavor, and links to exact details.
- `/admin/catalog/comercios/{id}`: exact configuration read, selected flavor
  control, payment/delivery read sections, and scoped catalog navigation.
- nested catalog pages/forms for the commerce's categories, products,
  presentations, and prices, limited to the creation operations already
  supported by the domain.

Every path resolves its exact positive identifier. A missing or unrelated
resource returns a safe not-found page; no cross-commerce or inferred lookup
is allowed. Creation forms select only valid parent resources in the same
commerce scope.

## Authentication and Request Safety

Browser navigation uses HTTP Basic with the existing configured admin secret;
the user name stays irrelevant and the comparison remains constant time. The
current pilot-specific dependency is generalized or wrapped under a neutral
name while preserving its response behavior and compatibility. It creates no
cookie, token persistence, URL token, or alternate credential. JSON endpoints
remain untouched and keep their `X-Admin-Token` boundary.

State-changing form submissions use POST/redirect/GET. The implementation
must use a same-origin anti-CSRF measure compatible with stateless Basic
authentication, such as a required, server-rendered non-secret nonce checked
with the submission origin; it must be explicitly tested and must not weaken
the existing pilot local-test origin protection.

## Mutation Reuse

Flavor forms invoke `ComunicacionFlavorService.assign_to_comercio` and retain
the existing router-level commit/rollback semantics through an extracted
shared operation only if required. `None` is the sole clear command; no magic
code or zero substitutes it.

Catalog forms must preserve complete current endpoint behavior, including
post-create embedding synchronization where it exists. The implementation
must not duplicate that coordination in two router modules. If the current
JSON router owns work beyond a service call, factor the smallest reusable
application operation and call it from both HTTP adapters. A best-effort
embedding synchronization failure retains exactly the existing create outcome;
the UI reports only a bounded generic outcome, never model/configuration or
exception content.

## Visual System

The visual language is intentionally operational but distinctive:

- near-black page and panel surfaces, with readable neutral text;
- violet for primary navigation/actions and fluorescent green for confirmed
  safe completion; restrained pink/amber/red for warnings and errors;
- colour tokens in local CSS, no remote fonts or assets;
- visible keyboard focus ring, sufficient text/background contrast, status
  icons/labels in addition to colour, and readable validation errors;
- dense-but-scannable desktop tables, responsive cards/stacking on narrow
  displays, and forms with clear field grouping and destructive-looking
  actions absent from this phase.

The screen must remain fully usable if JavaScript is unavailable. Jinja
autoescape is enabled; dynamic values are never inserted into CSS, URLs,
scripts, or unescaped HTML.

## Risks and Deferred Work

The main risk is silently diverging from current catalog creation side effects.
Shared-operation extraction is allowed only to preserve—not change—the
existing API behavior. The remaining risk is browser CSRF because Basic
credentials may be replayed by a browser; same-origin validation is mandatory.

Editing/deactivation, payments/delivery configuration, clients, order writes,
embedding control, external assets, and a full frontend application remain
out of scope.
