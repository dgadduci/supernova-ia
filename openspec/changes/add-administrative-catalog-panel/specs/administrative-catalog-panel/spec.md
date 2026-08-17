# administrative-catalog-panel Specification

## Purpose

Provide a bounded browser interface for routine commerce configuration and
existing catalog creation operations without duplicating application logic or
changing the administrative JSON API.

## ADDED Requirements

### Requirement: Browser panel uses the existing administrative credential safely

The `/admin/catalog` route family SHALL require the configured administrative
secret through the reusable browser Basic-authentication boundary. It SHALL
use constant-time comparison and generic `401`/`503` failures, create no
credential persistence, and require a same-origin anti-CSRF control for every
state-changing form. Existing JSON routes SHALL continue to require
`X-Admin-Token`, and `/admin/pilot/orders` SHALL retain its existing behavior.

#### Scenario: Browser mutation without same-origin proof is rejected

- **WHEN** an otherwise authenticated browser submits a catalog or flavor form
  without the required same-origin anti-CSRF proof
- **THEN** the request performs no mutation and returns a bounded rejection

### Requirement: Panel renders exact commerce configuration and optional flavor

The panel SHALL list bounded commerce summaries and render an exact selected
commerce configuration, including its payment/delivery read projection and
selected flavor summary or an explicit no-flavor state. It SHALL allow only
assignment of an active flavor or explicit clear to `NULL` through the existing
flavor selection boundary.

#### Scenario: Clear flavor preserves safe optional-flavor semantics

- **WHEN** an authenticated administrator clears the selected flavor for an
  exact commerce through the panel
- **THEN** the service persists `NULL`, the detail renders no selected flavor,
  and the panel exposes neither the flavor instruction nor styling diagnostics

### Requirement: Panel reuses catalog create operations without a parallel pipeline

The panel SHALL provide commerce-scoped navigation and forms for the existing
category, product, presentation, and price creation operations. Each form
SHALL use the same validation, transaction, and applicable embedding
synchronization boundary as the corresponding JSON API operation. The panel
SHALL NOT use internal HTTP calls, direct repository/model writes, or bypass
commerce isolation.

#### Scenario: Invalid product form retains the existing domain outcome

- **WHEN** an authenticated administrator submits a product creation form with
  a duplicate name in the selected category
- **THEN** no product is created, the selected commerce/catalog context is
  preserved, and the form presents an escaped bounded validation error

### Requirement: Panel is an accessible dark operational interface

The panel SHALL use a near-black visual foundation with vivid violet and
fluorescent-green accents, responsive layouts, visible keyboard focus, and
textual/icon status signals in addition to colour. It SHALL use no external
assets or CDN and SHALL remain usable without JavaScript.

#### Scenario: Status remains understandable without colour perception

- **WHEN** a form succeeds or fails
- **THEN** the result includes readable text or an equivalent semantic label,
  not colour alone
