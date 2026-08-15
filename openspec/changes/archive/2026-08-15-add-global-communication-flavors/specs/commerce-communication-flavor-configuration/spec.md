## ADDED Requirements

### Requirement: Every commerce has one selected global communication flavor

Every existing and newly-created commerce SHALL reference one global
communication flavor. Existing rows and new commerces without an explicit
selection SHALL use the canonical active `neutro` flavor.

#### Scenario: Existing commerce is backfilled safely

- **WHEN** the migration upgrades a database that already contains commerces
- **THEN** every such commerce references the global `neutro` flavor
- **AND THEN** the foreign key is non-null after backfill.

### Requirement: Administrators can select only active global flavors

An authenticated administrator SHALL be able to select an active global flavor
for one commerce through a focused configuration operation. Unknown or inactive
flavor IDs SHALL be rejected without changing that commerce or another
commerce.

#### Scenario: Inactive flavor cannot replace a commerce selection

- **WHEN** an administrator submits an inactive flavor ID
- **THEN** the operation is rejected
- **AND THEN** the commerce retains its prior flavor selection.

### Requirement: Flavor configuration does not activate response rewriting

This phase SHALL not invoke an LLM or alter any current deterministic customer
response. The selected flavor is stored configuration only until a separate
response-embellishment change is approved.

#### Scenario: Neutral assignment preserves the current response

- **WHEN** a commerce has the required `neutro` flavor association
- **AND WHEN** it produces an existing customer response
- **THEN** the response text remains unchanged
- **AND THEN** no outbound style LLM request occurs.
