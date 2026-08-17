# Proposal: add administrative catalog panel

## Objective

Provide a single, browser-oriented administrative panel that removes the need
to manually invoke the existing safe commerce and catalog endpoints for
routine setup. The first delivery makes commerce configuration and catalog
navigation/creation usable to an authenticated operator, while preserving the
existing pilot-order panel as a separate operational surface.

## Current Execution Path

All current JSON management routes use `X-Admin-Token`. Commerce reads are
available through `/comercios` and `/comercios/{id}/configuracion`; flavor
selection or clearing is available through the dedicated authenticated route
and `ComunicacionFlavorService`. Categories, products, presentations and
prices have scoped read/create routes. Their creation paths own their existing
validation, transaction, and—where applicable—catalog embedding
synchronization behavior. The only rendered browser UI is the Basic-authenticated
`/admin/pilot/orders` panel; it is specialized for order diagnosis and local
pilot testing.

## Scope

- Add a browser administrative surface for commerce setup and catalog work,
  grouped as **Comercios**, **Catálogo**, and a link to the existing
  **Operación** pilot-order panel.
- Render a bounded commerce list and an exact commerce detail/configuration
  view, including selected flavor (or explicitly no flavor), existing payment
  and delivery configuration, and catalog navigation.
- Permit flavor assignment and explicit clearing only through the existing
  flavor service boundary.
- Permit the already-supported creation operations for categories, products,
  presentations, and prices with their current validation and side-effect
  contracts; do not call routers through internal HTTP or write models/repositories
  directly from templates.
- Use server-rendered FastAPI/Jinja templates and modest browser JavaScript
  only where it materially improves form feedback; no SPA, external UI
  framework, CDN, API gateway, or separate frontend deployment.
- Establish an attractive, accessible dark visual system: near-black
  background, high-contrast text, vivid purple and fluorescent-green accents,
  clear focus/error/success states, and responsive layouts. Colour is
  decorative, never the only meaning-bearing signal.
- Generalize the existing browser-only Basic authentication boundary for this
  new panel family while retaining the same configured administrative secret
  and leaving every JSON API `X-Admin-Token` contract unchanged.

## Non-Goals

- No commerce-profile edit, flavor CRUD, catalog edit/delete/deactivation,
  payment/delivery configuration mutation, client administration, order or
  session mutation, provider/worker controls, embeddings UI, migrations, or
  API contract changes.
- No changes to outbound styling behavior, `add-safe-outbound-response-styling`,
  flavor instructions, or the deployed optional-flavor semantics. `NULL`
  remains the normal no-styling selection.
- No move/refactor of the existing pilot-order panel in this delivery.

## Shared Boundaries, Transactions, and Fallback

The panel is an HTTP/rendering adapter, not a parallel application pipeline.
It must use the same application-service operation boundaries as the existing
JSON routes. If a complete create operation currently spans a service and
post-create embedding synchronization, implementation may extract a small
shared application use case; both the API route and panel must call that one
boundary afterwards. The panel must not internally call its own JSON endpoints.

Each mutation keeps the current authoritative transaction owner and rollback
behavior. A successful flavor change or catalog creation displays the freshly
read exact resource. Expected domain validation failures leave the prior
state intact and render a bounded, escaped form error; technical failures show
a generic safe error without identifiers, secrets, prompts, or exception text.
Missing resources are not resolved through fallback lookups.

## Observability and Privacy

No new logs, diagnostic events, provider calls, or customer-data search are
introduced. Browser credentials, flavor instructions, tokens, raw exception
detail, embeddings payloads, and provider data must never be rendered or
stored client-side. The panel may show commerce configuration and catalog data
that the authenticated administrator needs. Templates autoescape all dynamic
content and forms must carry same-origin protection appropriate to the chosen
browser session boundary.

## Expected Files

- `backend/admin/` for panel-specific route adapters, typed form/view shapes,
  and templates; existing domain services/repositories remain authoritative.
- `backend/dependencies.py` only to make the browser authentication dependency
  reusable without changing its credential semantics.
- `backend/main.py` and router exports to mount the new panel family.
- A minimal shared application operation only if needed to prevent duplicate
  catalog-create transaction/synchronization orchestration between JSON API
  and panel.
- Focused panel/authentication/template tests plus focused regression coverage
  for each reused catalog operation.
- This change's OpenSpec files and an `administrative-catalog-panel` spec
  delta.

## Focused Tests and Validation

- Browser authentication rejects missing/invalid/misconfigured credentials;
  JSON APIs still require `X-Admin-Token` and the pilot panel remains valid.
- Exact commerce list/detail configuration, flavor assignment/clear,
  missing/inactive flavor rejection, and no instruction leakage.
- Scoped catalog navigation and each creation form's existing validation,
  commerce isolation, transaction/synchronization outcome, and escaped error
  rendering.
- Visual regression-by-markup coverage for semantic navigation, keyboard
  focus, non-colour status text, responsive layout hooks, and no external
  asset dependency.

The implementation plan shall name exact files after source inspection. The
user runs focused pytest, Ruff, compileall, strict OpenSpec validation, and
`git diff --check` locally and supplies the complete output for review.

## Rollback and Deferred Limitations

This is source-only and reversible by unmounting/removing the new panel
package; it does not require a migration. New domain operations—for example
editing/deactivating catalog rows or configuring payment/delivery methods—are
deferred to separate changes that first define their invariants and embedding
effects.
