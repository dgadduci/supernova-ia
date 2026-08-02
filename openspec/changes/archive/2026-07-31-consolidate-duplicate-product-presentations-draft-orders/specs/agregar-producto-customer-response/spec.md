## MODIFIED Requirements

### Requirement: Executed confirmation

For `intent.intent == "agregar_producto"` and `intent.status == "executed"`, the builder SHALL read `resolved_data["producto_presentacion_id"]` and the quantity key from `resolved_data` (using `resolved_data["cantidad_final"]` when present and falling back to `resolved_data["cantidad"]` otherwise), load the presentation through `ProductoQueryService.list_presentaciones_by_ids([producto_presentacion_id])`, and return a `CustomerResponse` whose `message` confirms the product name, presentation name, and quantity added. The quantity phrasing SHALL use the singular form when the resolved quantity is `1` and the plural form when it is greater than `1`. The message SHALL NOT include database IDs or prices. The `linea_creada` and `cantidad_agregada` keys in `resolved_data` are accepted but SHALL NOT be surfaced in the customer-facing message text — the executed message reflects the line's final quantity, not the operation's internal "newly created vs incremented" distinction.

#### Scenario: Executed intent with a new line and cantidad_final == 1 confirms one unit

- **WHEN** the builder receives an `executed` intent whose `resolved_data == {"producto_presentacion_id": pp_id, "cantidad": 1, "cantidad_agregada": 1, "cantidad_final": 1, "linea_creada": True}` and the service returns `("Pizza Mozzarella", "grande")`
- **THEN** the returned `CustomerResponse.message` contains `"Pizza Mozzarella"`, `"grande"`, the literal `"1"`, and the singular phrasing marker (e.g., `"agregué"`), and does NOT contain `str(pp_id)`, any price string, or the literal strings `"linea_creada"` / `"cantidad_agregada"`

#### Scenario: Executed intent with an incremented line and cantidad_final == 4 confirms four units

- **WHEN** the builder receives an `executed` intent whose `resolved_data == {"producto_presentacion_id": pp_id, "cantidad": 1, "cantidad_agregada": 1, "cantidad_final": 4, "linea_creada": False}` (an existing line with quantity 3 was incremented by 1) and the service returns `("Pizza Mozzarella", "chica")`
- **THEN** the returned `CustomerResponse.message` contains `"Pizza Mozzarella"`, `"chica"`, the literal `"4"`, and the plural phrasing marker (e.g., `"se agregaron"`), and does NOT contain the literal string `"3"`, `"1"` (as the line's final quantity), or any of the words `"increment"`, `"sumamos"`, or `"anterior"`

#### Scenario: Executed intent without the new resolved_data keys falls back to cantidad

- **WHEN** the builder receives an `executed` intent whose `resolved_data == {"producto_presentacion_id": pp_id, "cantidad": 2}` (no `cantidad_final`, no `cantidad_agregada`, no `linea_creada` — produced by a legacy or test caller)
- **THEN** the returned `CustomerResponse.message` contains `"Pizza Mozzarella"`, `"grande"`, and the literal `"2"`, matching the existing pre-3.30.3 fallback behavior

#### Scenario: Executed intent with missing presentation returns the failed fallback

- **WHEN** the builder receives an `executed` intent whose `resolved_data["producto_presentacion_id"]` does not resolve through the service
- **THEN** the returned `CustomerResponse.message` equals the fixed retry message, `CustomerResponse.intent == "agregar_producto"`, and `CustomerResponse.status == "failed"`

#### Scenario: Executed intent with invalid quantity returns the failed fallback

- **WHEN** the builder receives an `executed` intent whose resolved quantity (taken from `cantidad_final` when present, otherwise from `cantidad`) is missing, non-integer, or less than 1
- **THEN** the returned `CustomerResponse.message` equals the fixed retry message and `CustomerResponse.status == "failed"`