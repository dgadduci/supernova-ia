## ADDED Requirements

### Requirement: Browser administration of global delivery methods

The authenticated administrative catalog panel SHALL provide a global delivery
method list, create form, and edit form under
`/admin/catalog/metodos-entrega`. The list SHALL render each global row's
code, description, global order, and active state and link to the exact global
row's edit form. Create SHALL accept `codigo`, `descripcion`, global
non-negative `orden`, and `activo`; edit SHALL expose the same information but
keep `codigo` immutable.

#### Scenario: Administrator creates and edits one global method

- **WHEN** an authenticated administrator submits valid create or edit data
  with a valid exact-path nonce and allowed same origin
- **THEN** the panel invokes the shared global delivery service directly
- **AND** it redirects after a successful mutation to the global list
- **AND** no `ComercioMetodoEntrega` or `Pedido` row is changed

#### Scenario: Global inactive method remains historical per commerce

- **WHEN** an administrator deactivates a global delivery method that has a
  commerce association
- **THEN** the panel updates only the global method
- **AND** the commerce detail projection continues to show the existing
  association as read-only historical configuration

### Requirement: Global delivery panel mutations remain protected

Every global delivery create or edit POST SHALL require the established
browser Basic authentication, same-origin validation, and an exact-path CSRF
nonce. Templates SHALL autoescape dynamic data and shall not display raw
exceptions or credentials.

#### Scenario: Forged global delivery mutation is rejected

- **WHEN** a create or edit POST has missing/invalid Basic credentials, an
  invalid nonce, or a disallowed Origin
- **THEN** the request is rejected before a global delivery row is mutated
