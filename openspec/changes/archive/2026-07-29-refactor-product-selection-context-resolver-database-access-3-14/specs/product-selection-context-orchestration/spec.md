## ADDED Requirements

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
