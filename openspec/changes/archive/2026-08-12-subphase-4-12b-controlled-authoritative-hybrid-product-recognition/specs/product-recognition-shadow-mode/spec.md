## MODIFIED Requirements

### Requirement: Product recognizer mode setting

`Settings.product_recognizer_mode` SHALL accept `"fuzzy"`, `"shadow"`, or
`"hybrid_authoritative"`, defaulting to `"fuzzy"` and overridable through the
same-named environment variable. Valid values are accepted verbatim. An invalid
value, including empty, SHALL safely resolve to `"fuzzy"`, emit one sanitized
warning with `configured_mode`, `effective_mode`, and `reason`, and SHALL NOT
prevent startup or customer processing. `InvalidProductRecognizerMode` remains
a reserved marker and is not raised by the environment resolver.

Fuzzy is authoritative in fuzzy and shadow. Shadow is observational and must
never alter the returned fuzzy result. Hybrid is authoritative only in
`hybrid_authoritative`. Existing observation structures SHALL record configured
mode, effective mode, authoritative strategy, fuzzy decision, hybrid decision
when evaluated, explicit fallback, and a sanitized fallback category.

#### Scenario: Default mode is fuzzy

- **WHEN** `Settings.load()` is called without an explicit override
- **THEN** `settings.product_recognizer_mode == "fuzzy"`
- **AND** no warning is emitted

#### Scenario: Shadow mode override is accepted

- **WHEN** `PRODUCT_RECOGNIZER_MODE=shadow` is set before `Settings.load()`
- **THEN** `settings.product_recognizer_mode == "shadow"`
- **AND** no warning is emitted

#### Scenario: Hybrid authoritative mode override is accepted

- **WHEN** `PRODUCT_RECOGNIZER_MODE=hybrid_authoritative` is set before
  `Settings.load()`
- **THEN** `settings.product_recognizer_mode == "hybrid_authoritative"`
- **AND** no warning is emitted

#### Scenario: Invalid mode falls back to fuzzy with a sanitized warning

- **WHEN** `PRODUCT_RECOGNIZER_MODE=hybrid_active` is set before
  `Settings.load()`
- **THEN** `Settings.load()` completes without raising
- **AND** `settings.product_recognizer_mode == "fuzzy"`
- **AND** exactly one structured warning carries `configured_mode`,
  `effective_mode`, and `reason`
- **AND** the hybrid authoritative policy file is NOT loaded

#### Scenario: Shadow pipeline failure does not affect quitar

- **WHEN** quitar_producto runs with shadow mode and hybrid observation fails
- **THEN** the fuzzy result remains authoritative and is returned unchanged
- **AND** the safe failure category is observed
