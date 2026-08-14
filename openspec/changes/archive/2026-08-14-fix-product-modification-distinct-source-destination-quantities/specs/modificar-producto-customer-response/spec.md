## ADDED Requirements

### Requirement: Distinct quantity confirmation reflects durable mutation

For an executed modification with distinct source and destination operation
amounts, the customer response SHALL render both actual values and must not
reuse the source value for destination. Existing wording for equal-quantity
legacy outcomes remains unchanged.

#### Scenario: Confirmation of 2 to 1 partial replacement

- **WHEN** the durable operation decrements Napolitana by 2, increments Mozzarella by 1, and leaves 5 Napolitana
- **THEN** the confirmation communicates 2 Napolitana replaced by 1 Mozzarella and that 5 Napolitana remain

#### Scenario: Consolidated destination reports the actual destination total

- **WHEN** the destination already existed and the distinct operation adds 1 unit
- **THEN** the response may include the durable destination final total, but never reports the source amount as the amount added to destination
