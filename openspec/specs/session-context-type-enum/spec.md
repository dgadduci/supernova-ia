# Capability: session-context-type-enum

## Purpose

Define the closed set of `ContextType` values that the system recognizes for a `Session`'s current resolution flow. This capability is the narrowest declaration of the vocabulary; future subphases will add a `context_type` column to the `Session` model and route messages by context.

## Requirements

### Requirement: ContextType enum exists
The system SHALL export a `ContextType` enum (a `StrEnum`) from `backend.sessions.enums.context_type`. The enum SHALL declare exactly one member: `ContextType.PRODUCT_SELECTION` with string value `"product_selection"`. The enum SHALL be importable without side effects.

#### Scenario: Import succeeds
- **WHEN** any module executes `from backend.sessions.enums.context_type import ContextType`
- **THEN** the import completes without raising and the binding is a `StrEnum` subclass

#### Scenario: Enum has exactly one member
- **WHEN** the test inspects `list(ContextType)`
- **THEN** the list is exactly `[ContextType.PRODUCT_SELECTION]`

#### Scenario: PRODUCT_SELECTION value
- **WHEN** the test reads `ContextType.PRODUCT_SELECTION.value`
- **THEN** the value equals the string `"product_selection"`

### Requirement: ContextType is string-compatible
A `ContextType` member SHALL compare equal to its underlying string value (because `ContextType` is a `StrEnum`).

#### Scenario: PRODUCT_SELECTION equals its string value
- **WHEN** the test evaluates `ContextType.PRODUCT_SELECTION == "product_selection"`
- **THEN** the result is `True`

#### Scenario: PRODUCT_SELECTION is an instance of str
- **WHEN** the test evaluates `isinstance(ContextType.PRODUCT_SELECTION, str)`
- **THEN** the result is `True`

#### Scenario: str() round-trips
- **WHEN** the test evaluates `str(ContextType.PRODUCT_SELECTION)`
- **THEN** the result is `"product_selection"`

### Requirement: ContextType rejects invalid values
Constructing a `ContextType` member from a string that is not in the enum's value set SHALL raise `ValueError`.

#### Scenario: Unknown value raises ValueError
- **WHEN** the test calls `ContextType("unknown")`
- **THEN** the call raises `ValueError`

#### Scenario: Different-case value raises ValueError
- **WHEN** the test calls `ContextType("Product_Selection")`
- **THEN** the call raises `ValueError` (case-sensitive)

#### Scenario: Empty string raises ValueError
- **WHEN** the test calls `ContextType("")`
- **THEN** the call raises `ValueError`

### Requirement: Module is importable without side effects
The system SHALL make `ContextType` importable from `backend.sessions.enums.context_type` without side effects, errors, or required dependencies beyond the standard library.

#### Scenario: Import succeeds and the symbol is present
- **WHEN** any module executes `from backend.sessions.enums.context_type import ContextType`
- **THEN** the import completes without raising and the binding is the enum class

### Requirement: __all__ declares the public surface
The system SHALL declare `__all__ = ["ContextType"]` in the module.

#### Scenario: __all__ is exactly the one symbol
- **WHEN** the test inspects `getattr(module, "__all__", ())`
- **THEN** the set is exactly `{"ContextType"}`

### Requirement: No additional implementation
The subphase SHALL NOT introduce a `backend/sessions/enums.py` (single-module shortcut), additional enum values, a model, a migration, a router, a FastAPI endpoint, a service, or any business logic. The only new code is the enum module, the two `__init__.py` package markers, and the verification test.

#### Scenario: No backend/sessions/enums.py exists
- **WHEN** the test checks for `backend/sessions/enums.py`
- **THEN** the file does not exist; only `backend/sessions/enums/__init__.py` and `backend/sessions/enums/context_type.py` are present

#### Scenario: The sessions package has only one file
- **WHEN** the test lists files under `backend/sessions/enums/`
- **THEN** the file set is exactly `{"__init__.py", "context_type.py"}`
