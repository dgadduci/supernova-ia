## ADDED Requirements

### Requirement: Inbound processing uses the centralized commerce availability policy

Before accepting or routing provider inbound work for a commerce, the system
SHALL evaluate the centralized availability policy. It SHALL reject blocked,
missing, expired-trial, and quota-exhausted commerce without choosing a
different commerce or creating a replacement order.

#### Scenario: Expired trial is rejected before new work is accepted

- **WHEN** inbound provider work resolves to a commerce whose PRUEBA deadline
  has passed
- **THEN** the result is a typed unavailable-commerce outcome
- **AND** no receipt-derived order/session work for that commerce is created
