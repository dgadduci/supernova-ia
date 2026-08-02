## ADDED Requirements

### Requirement: Incoming initial outcomes represent only work processed on that turn
For an initial message containing multiple `agregar_producto` items, the incoming-message orchestrator SHALL propagate the dispatcher's ordered outcomes unchanged and SHALL NOT expose queued inactive additions as responses.

#### Scenario: Initial HTTP turn exposes one clarification
- **WHEN** the initial message produces two ambiguous additions
- **THEN** the orchestrator returns exactly one `pending_resolution` outcome for the active first addition

#### Scenario: Ready work before ambiguity remains visible
- **WHEN** the initial message produces ready A followed by pending B
- **THEN** the orchestrator returns A `executed` then B `pending_resolution`

### Requirement: Incoming pending outcomes preserve promotion order
For a message routed to active pending context, the incoming-message orchestrator SHALL return the pending dispatcher's complete list unchanged, including a definitive active outcome followed by any automatically executed ready outcomes and at most one promoted clarification.

#### Scenario: Resolution response includes next clarification
- **WHEN** resolving active Carne promotes unresolved Pizza
- **THEN** the orchestrator returns Carne `executed` followed by Pizza `pending_resolution` without wrapping, truncating, reordering, or duplicating either item

### Requirement: Clarification-only messages bypass initial classification
While `session.context_type` identifies an active pending interaction, the incoming-message orchestrator SHALL route a clarification-only message to pending dispatch and SHALL NOT invoke the initial classifier for that message.

#### Scenario: Active-only clarification is not a new intent
- **WHEN** Carne is active with queued Pizza and the customer sends `picante`
- **THEN** the message resolves Carne through pending dispatch and is not classified as an independent intent

### Requirement: Multi-outcome processing remains one transaction per HTTP message
Sequential promotion SHALL preserve the existing transactional boundary: one successful incoming message commits once after all returned outcomes, and any raised exception causes one rollback with no false success response.

#### Scenario: Executed then promoted-ready success commits once
- **WHEN** one clarification executes the active addition and one or more promoted ready additions
- **THEN** the transactional wrapper commits exactly once after the complete ordered result is produced

#### Scenario: Later promotion exception rolls back the turn
- **WHEN** a later promoted handler raises after an earlier mutation in the same message
- **THEN** the transactional wrapper rolls back once and no customer response list is returned
