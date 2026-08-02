## MODIFIED Requirements

### Requirement: Function exists
The system SHALL export `resolve_product_selection(message: str, active_intent: ProcessedIntent, productos_presentaciones: list[dict]) -> ProcessedIntent` from `backend.intents.context.product_selection_context_resolver`. The function SHALL be importable without SQLAlchemy, database session, repository, or service dependencies and SHALL remain pure: no persistence, commits, handlers, responses, or session mutation.

#### Scenario: Pure resolver is importable
- **WHEN** a module imports `resolve_product_selection`
- **THEN** the import succeeds without requiring a database session or SQLAlchemy query setup

#### Scenario: Pure resolver accepts a prebuilt catalog
- **WHEN** the resolver receives a restricted 12-field catalog and a pending intent
- **THEN** it invokes the existing recognizer and returns the selection result without database access

### Requirement: Input validation
The function SHALL return `active_intent` unchanged when its status is not `pending_resolution` or its `candidate_ids` are empty. The function SHALL also return it unchanged when the supplied catalog cannot produce a unique valid selection.

#### Scenario: Invalid pending context is unchanged
- **WHEN** the resolver receives a ready intent or an intent with no candidates
- **THEN** it returns the same intent instance without invoking the recognizer

### Requirement: Unique selection applies
When the recognizer returns exactly one item in `encontrados` and its `producto_presentacion_id` belongs to the original `candidate_ids`, the resolver SHALL return a new `ProcessedIntent` with the selected presentation applied, the original resolved data preserved, the selection requirement completed, and `candidate_ids` cleared.

#### Scenario: Unique selection from prebuilt catalog
- **WHEN** the resolver receives a catalog restricted to the active intent candidates and the real recognizer uniquely matches `la grande`
- **THEN** the result contains the selected `producto_presentacion_id`, preserves `cantidad`, marks the selection requirement completed, and clears candidates

### Requirement: No database access in context resolver
The context resolver SHALL contain no SQLAlchemy imports, database session parameter, repository calls, service calls, commits, persistence, or model loading. Database access SHALL be performed outside the resolver.

#### Scenario: Resolver source has no database dependency
- **WHEN** the resolver module is inspected
- **THEN** it contains no SQLAlchemy or database-session access

## ADDED Requirements

### Requirement: Candidate catalog repository access
The product repository SHALL provide a query operation that loads only `producto_presentaciones` whose IDs are supplied by the caller and eagerly loads product, presentation, and category relationships.

#### Scenario: Repository restricts candidate IDs
- **WHEN** the repository is asked to load candidate IDs `[1, 2, 3]`
- **THEN** its query filters by those IDs and does not return other presentations

### Requirement: Product service builds recognizer catalog
The product service SHALL load the restricted candidate presentations through the repository and build the exact 12-field catalog consumed by `detectar_productos`, preserving real activation and availability values.

#### Scenario: Service returns exact catalog shape
- **WHEN** the service loads candidate presentations
- **THEN** each catalog item contains exactly the recognizer fields and values for identifiers, product, category, presentation, activation, and availability

### Requirement: Product selection orchestration
An orchestration service SHALL receive the database session, load the restricted catalog through the product service, and invoke the pure context resolver with the message, active intent, and catalog. It SHALL not commit, persist pending context, execute handlers, or generate responses.

#### Scenario: Orchestration resolves a presentation
- **WHEN** the orchestration service receives an active intent with candidate IDs and the message `la grande`
- **THEN** it loads only those candidates, invokes the real resolver/recognizer path, and returns the resolved intent with original quantity preserved

#### Scenario: Orchestration has no side effects
- **WHEN** the orchestration service completes resolution
- **THEN** it has not committed, modified session state, invoked a handler, or generated a response
