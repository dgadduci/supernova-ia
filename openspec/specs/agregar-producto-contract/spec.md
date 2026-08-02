# Capability: agregar-producto-contract

## Purpose

Define a single importable Python constant `AGREGAR_PRODUCTO_CONTRACT` that declares the static intent contract for the `agregar_producto` skill, exposing only the contract itself — no registry, recognizer, handler, schema, or model — so other modules can introspect the required keys without importing implementation code.

## Requirements

### Requirement: agregar_producto intent contract
The system SHALL export a single Python constant `AGREGAR_PRODUCTO_CONTRACT` from `backend.intents.contracts.agregar_producto`. The constant SHALL be a `dict` with exactly four top-level keys: `intent`, `recognizer`, `handler`, and `requirements`.

#### Scenario: Top-level keys are present
- **WHEN** the test imports `AGREGAR_PRODUCTO_CONTRACT`
- **THEN** the value is a `dict` whose keys are exactly `{"intent", "recognizer", "handler", "requirements"}`

#### Scenario: intent is "agregar_producto"
- **WHEN** the test reads `AGREGAR_PRODUCTO_CONTRACT["intent"]`
- **THEN** the value equals the string `"agregar_producto"`

#### Scenario: recognizer is "recognizer_productos"
- **WHEN** the test reads `AGREGAR_PRODUCTO_CONTRACT["recognizer"]`
- **THEN** the value equals the string `"recognizer_productos"`

#### Scenario: handler is "agregar_producto"
- **WHEN** the test reads `AGREGAR_PRODUCTO_CONTRACT["handler"]`
- **THEN** the value equals the string `"agregar_producto"`

#### Scenario: requirements has exactly two entries
- **WHEN** the test reads `AGREGAR_PRODUCTO_CONTRACT["requirements"]`
- **THEN** the value is a `dict` whose keys are exactly `{"producto_presentacion_id", "cantidad"}`

#### Scenario: producto_presentacion_id requirement
- **WHEN** the test reads `AGREGAR_PRODUCTO_CONTRACT["requirements"]["producto_presentacion_id"]`
- **THEN** the value is a `dict` with `required == True` and `default is None`

#### Scenario: cantidad requirement
- **WHEN** the test reads `AGREGAR_PRODUCTO_CONTRACT["requirements"]["cantidad"]`
- **THEN** the value is a `dict` with `required == True` and `default == 1`

### Requirement: Contract file is importable
The system SHALL make `AGREGAR_PRODUCTO_CONTRACT` importable from `backend.intents.contracts.agregar_producto` without side effects, errors, or required dependencies beyond the standard library.

#### Scenario: Import succeeds
- **WHEN** any module executes `from backend.intents.contracts.agregar_producto import AGREGAR_PRODUCTO_CONTRACT`
- **THEN** the import completes without raising and the binding is the dict defined by the contract

### Requirement: No additional implementation
The subphase SHALL NOT introduce a registry, recognizer, handler, processor, schema, Pydantic model, SQLAlchemy model, Alembic migration, FastAPI endpoint, or any other intent contract beyond `AGREGAR_PRODUCTO_CONTRACT`. The only new code is the contract module, the two empty `__init__.py` files, and the verification test.

#### Scenario: No extra symbols beyond the contract
- **WHEN** the test introspects the `agregar_producto` module
- **THEN** the only public symbol it exports is `AGREGAR_PRODUCTO_CONTRACT`

#### Scenario: No other intent contracts in the package
- **WHEN** the test lists modules under `backend.intents.contracts`
- **THEN** the only file present is `agregar_producto.py`
