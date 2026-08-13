## ADDED Requirements

### Requirement: Caller-owned line observation mutation seam

`PedidoProductoService` SHALL expose a dedicated operation for setting a
single line observation to a string or `NULL` within a specified active
conversation session and its Pedido. The operation SHALL validate session
ownership, borrador state, and line membership before mutation. It SHALL not
reuse semantics in which `None` means “leave unchanged”, and it SHALL not
commit, roll back, flush, refresh, expire, begin, or close the database
session.

#### Scenario: Clear is distinct from no update

- **WHEN** the caller invokes the dedicated operation with `observaciones=None`
- **THEN** the validated line is assigned `NULL`, rather than retaining its
  previous observation
