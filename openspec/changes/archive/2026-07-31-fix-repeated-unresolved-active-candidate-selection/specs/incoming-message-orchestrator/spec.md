## ADDED Requirements

### Requirement: Clarification-only resolution propagates all ordered advancement outcomes
While active pending context exists, the incoming-message orchestrator SHALL route the customer reply only to pending dispatch and SHALL return its complete ordered list unchanged. It SHALL NOT invoke initial classification, wrap the list again, truncate it, reorder it, or duplicate an outcome.

#### Scenario: Picante returns execution then promoted clarification
- **WHEN** `picante` resolves active Carne, executes it, and promotes unresolved Pizza
- **THEN** the orchestrator returns Carne `executed` first and Pizza `pending_resolution` second, exactly once each

#### Scenario: Picante bypasses initial classification
- **WHEN** Carne is active with queued Pizza and the incoming message is `picante`
- **THEN** the orchestrator calls pending dispatch and does not create or classify a new initial intent

### Requirement: Multi-outcome pending processing preserves one transaction per message
Returning an active definitive outcome and a promoted clarification SHALL NOT add transaction control to the incoming-message orchestrator. The transactional wrapper SHALL commit once after the complete successful result or roll back once when any internal step raises.

#### Scenario: Active execution and promotion commit once
- **WHEN** one clarification executes Carne and promotes Pizza without error
- **THEN** the complete ordered result is produced before the transactional wrapper commits exactly once

#### Scenario: Promotion failure returns no false success
- **WHEN** a later execution or promotion step raises after an earlier in-memory order mutation
- **THEN** the exception propagates and the transactional wrapper rolls back once without returning a partial response list
