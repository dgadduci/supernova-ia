## ADDED Requirements

### Requirement: Browser commerce onboarding and basic profile editing

The authenticated catalog panel SHALL provide a commerce create form and an
exact-commerce basic edit form under `/admin/catalog/comercios`. Creation
shall accept the existing required profile and routing identity fields; edit
SHALL permit only profile, address, locale, and status fields and display
`whatsapp` and `slug` read-only.

#### Scenario: Administrator onboards one commerce

- **WHEN** an authenticated administrator submits valid create data with an
  existing status ID, exact-path nonce, and permitted origin
- **THEN** the panel creates exactly one commerce through the shared service
- **AND** redirects to its exact configuration page
- **AND** creates no catalog, flavor, association, order, session, channel, or
  provider resource

#### Scenario: Forged routing identifier edit is harmless

- **WHEN** an edit POST contains WhatsApp or slug values not accepted by the
  displayed read-only form
- **THEN** stored routing identifiers remain unchanged
- **AND** only documented permitted fields may change

### Requirement: Commerce panel mutations remain protected

Every create/edit POST SHALL retain browser Basic authentication, same-origin
validation, and an exact-path CSRF nonce. Templates SHALL autoescape dynamic
data and expose bounded feedback only.

#### Scenario: Invalid origin or nonce does not mutate commerce state

- **WHEN** a create or edit POST lacks valid credentials, valid nonce, or
  allowed Origin
- **THEN** it is rejected before the commerce service persists any change
