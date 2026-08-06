# Product Selection Context Orchestration

## Purpose

Provide an orchestration service that connects the database-backed product catalog service to the pure `ProductSelectionContextResolver`, keeping database access, selection resolution, persistence, and handler responsibilities in separate, layered components.

## Requirements

### Requirement: Product selection context orchestration capability
The system SHALL provide an orchestration service that connects the database-backed product catalog service to the pure `ProductSelectionContextResolver` without moving persistence or handler responsibilities into either component.

#### Scenario: Orchestration delegates catalog and resolution
- **WHEN** the service receives a session, message, and pending product-selection intent
- **THEN** it loads candidate presentations through the product service and delegates selection to the pure context resolver

#### Scenario: Orchestration preserves resolver output
- **WHEN** the delegated resolver returns a new intent
- **THEN** the orchestration service returns it without altering its status, requirements, resolved data, or candidate IDs

### Requirement: Layered database access
The orchestration service SHALL access product-presentation data through a product service and repository, following the internal component → service → repository → SQLAlchemy layering rule.

#### Scenario: Service boundary is used
- **WHEN** the orchestration service loads a restricted catalog
- **THEN** it does not construct direct SQLAlchemy queries and delegates data access to the product service

### Requirement: No orchestration side effects
The orchestration service SHALL NOT commit, persist pending context, execute handlers, generate responses, or mutate the session model.

#### Scenario: Resolution remains non-persistent
- **WHEN** the orchestration service resolves a selection
- **THEN** the database session has no commit or persistence operation caused by the orchestration

## ADDED Requirements

### Requirement: Orchestration consults the pending-product-ambiguity resolver as a sibling step
The orchestration service SHALL invoke `resolve_pending_product_ambiguity` as a sibling step after `resolve_product_selection`. The orchestration service SHALL bind the existing path's result to `fragment_result`. If `fragment_result.status == "ready"`, the orchestration service SHALL return `fragment_result` directly and the new resolver SHALL NOT be consulted. Otherwise (the existing path did not resolve uniquely):
1. The orchestration service SHALL call `resolve_pending_product_ambiguity` with **`fragment_result`** as the active intent argument (NOT the original `active_intent`).
2. The orchestration service SHALL pass a catalog projection restricted to `fragment_result.candidate_ids` (a subset of the original `active_intent.candidate_ids` when the existing path narrowed). The orchestration service SHALL NOT widen the catalog beyond `fragment_result.candidate_ids` and SHALL NOT reload the catalog via `list_presentaciones_by_ids` for the new resolver.
3. Because `resolve_pending_product_ambiguity` is scoped to its passed-in catalog and `active_intent.candidate_ids`, it SHALL NOT be capable of selecting a candidate that the existing narrowing path discarded.
4. When `resolve_pending_product_ambiguity` returns a `ready` intent, the orchestration service SHALL return that intent instead of `fragment_result`. When `resolve_pending_product_ambiguity` does NOT return a `ready` intent (returns `fragment_result` unchanged or further narrowed), the orchestration service SHALL return `fragment_result` — the existing path's narrowed candidate list is preserved.

#### Scenario: New resolver resolves uniquely after the existing path is ambiguous
- **WHEN** `resolve_product_selection` returns `fragment_result` with `status != "ready"` because no presentacion alias or fragment matched (e.g. for the message `"la que no es zero"`) and the orchestration service invokes `resolve_pending_product_ambiguity(message, fragment_result, catalog_filtered_to_fragment_result.candidate_ids)` which returns a new intent with `status == "ready"`
- **THEN** the orchestration service returns the new resolver's `ready` intent without altering its `resolved_data`, `requirements`, or `candidate_ids`

#### Scenario: Existing path wins when it resolves uniquely
- **WHEN** `resolve_product_selection` returns `fragment_result` with `status == "ready"` (e.g. for the message `"la grande"` or `"picante"`)
- **THEN** the orchestration service returns `fragment_result` directly and does NOT invoke `resolve_pending_product_ambiguity`

#### Scenario: Both paths ambiguous returns the existing path's narrowed result
- **WHEN** `resolve_product_selection` returns `fragment_result` with `status != "ready"` (e.g. narrows to a subset of candidates) and `resolve_pending_product_ambiguity` also does NOT return a `ready` intent
- **THEN** the orchestration service returns `fragment_result`; the new resolver's narrowed result is NOT used to overwrite `fragment_result`

#### Scenario: Candidate discarded by the existing narrowing path cannot be reintroduced by the new resolver
- **WHEN** `active_intent.candidate_ids == [A, B, C]`, `resolve_product_selection` narrows to `fragment_result` with `fragment_result.candidate_ids == [B, C]` (discarding `A`), and the new resolver is consulted against that narrowed catalog projection
- **THEN** the new resolver's catalog projection does not include `A`; even if the customer's reply would otherwise uniquely select `A` under Layer 5 / Layer 7 (e.g. the message names a distinguishing token `A` carries), the new resolver CANNOT select `A` and SHALL fall through or return a non-`ready` intent; the orchestration service returns `fragment_result` with `candidate_ids == [B, C]` preserved

### Requirement: Orchestration loads the candidate catalog exactly once and narrows it for the new resolver
The orchestration service SHALL load the restricted catalog through `ProductoQueryService.list_presentaciones_by_ids(active_intent.candidate_ids)` exactly once per call. The catalog projection passed to `resolve_product_selection` SHALL be the full loaded catalog (rows restricted to `active_intent.candidate_ids`). When the new resolver is consulted, the orchestration service SHALL pass the in-memory catalog filtered to `fragment_result.candidate_ids` (without issuing another `list_presentaciones_by_ids` call). The orchestration service SHALL NOT widen the catalog beyond `fragment_result.candidate_ids` for the new resolver.

#### Scenario: Catalog is loaded once per orchestration call and narrowed before being handed to the new resolver
- **WHEN** the orchestration service consults `resolve_product_selection` and then `resolve_pending_product_ambiguity`
- **THEN** `ProductoQueryService.list_presentaciones_by_ids` is called exactly once (for `active_intent.candidate_ids`); the new resolver receives the in-memory catalog filtered to `fragment_result.candidate_ids`; no SQLAlchemy query is issued for the filtered projection

### Requirement: Orchestration does not introduce new side effects
The orchestration service SHALL NOT introduce new commit, rollback, flush, refresh, expire, or `begin` calls, SHALL NOT mutate the `Session` model, and SHALL NOT log anything as part of the new sibling step.

#### Scenario: New sibling step does not commit
- **WHEN** the orchestration service consults `resolve_pending_product_ambiguity`
- **THEN** the database session's `commit` is not called by the orchestration service; the existing pending-context transaction ownership remains in the dispatcher and execution layers

### Requirement: Existing orchestration scenarios remain green
The existing scenarios (`Orchestration delegates catalog and resolution`, `Orchestration preserves resolver output`, `Layered database access`, `Resolution remains non-persistent`) SHALL continue to pass without modification. The new sibling step SHALL NOT alter the observable behaviour of the orchestration service for any input that the existing path resolves uniquely.

#### Scenario: Existing fragment-resolution input returns the existing intent unchanged
- **WHEN** the active candidates are `[EmpanadaCarneUnidad, EmpanadaCarnePicanteUnidad]` and the message is `"picante"`
- **THEN** the orchestration service returns the `ready` intent produced by `resolve_product_selection` (Empanada de Carne Picante Unidad); the new resolver is not consulted and the existing scenario remains green
