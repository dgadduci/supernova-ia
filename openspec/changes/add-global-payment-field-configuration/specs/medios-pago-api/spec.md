## ADDED Requirements

### Requirement: Manage global payment detail availability

The authenticated global payment-method surface SHALL expose
`habilita_titular` and `habilita_alias` in payment responses and SHALL permit
an administrator to set both values when creating or updating a global payment
method. The API update operation SHALL return `404 Not Found` for an unknown
method and SHALL leave its prior state unchanged for invalid input or a failed
write.

#### Scenario: Administrator enables fields on an existing method

- **WHEN** an authenticated administrator updates an existing payment method
  with `habilita_titular = true` and `habilita_alias = true`
- **THEN** the response and subsequent reads expose both values as `true`
- **AND** no commerce association or order is modified

#### Scenario: Invalid update is atomic

- **WHEN** a global payment-method update fails validation or persistence
- **THEN** the existing row retains its prior flags and catalog data
- **AND** the service rolls back any failed database transaction

### Requirement: Browser global payment administration is protected

The browser administration surface for global payment methods SHALL require
the existing Basic authentication and SHALL protect every mutation with the
existing path-bound nonce and same-origin validation. It SHALL call the global
payment service directly and SHALL NOT call the JSON endpoint through internal
HTTP.

#### Scenario: Cross-origin or nonce-less form is rejected

- **WHEN** a global payment create or update form lacks a valid nonce or fails
  the same-origin check
- **THEN** the request is rejected before the global payment service mutates
  any row
