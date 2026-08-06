## MODIFIED Requirements

### Requirement: Restricted selection declares its recognition scope

The pending product-selection resolver SHALL call the shared recognition
boundary with keyword-only
`intent_metadata={"catalog_scope": "pending_product_selection_restricted"}`
when resolving a pending candidate set. This call remains backward-compatible
for recognizers and test doubles that implement the shared boundary.

#### Scenario: Restricted scope is forwarded through the resolver boundary

- **WHEN** the pending product-selection resolver invokes recognition for an
  active intent with candidate IDs
- **THEN** the recognizer receives
  `intent_metadata == {"catalog_scope": "pending_product_selection_restricted"}`
- **AND** the candidate catalog is not widened
