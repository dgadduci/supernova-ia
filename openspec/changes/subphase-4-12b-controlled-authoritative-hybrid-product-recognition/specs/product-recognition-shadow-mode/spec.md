## MODIFIED Requirements

### Requirement: Mode selection and observation remain safe across all recognition flows

`Settings.product_recognizer_mode` SHALL continue to accept `fuzzy`, `shadow`,
and `hybrid_authoritative`, with fuzzy as default and safe effective fallback
for invalid values. `fuzzy` is authoritative in fuzzy and shadow; hybrid is
authoritative only in hybrid_authoritative. The existing recorder SHALL reuse
its comparison and hybrid observation structures to record configured mode,
effective mode, authoritative strategy, fuzzy decision, hybrid decision when
evaluated, fallback, and sanitized fallback category.

#### Scenario: Shadow pipeline failure does not affect quitar

- **WHEN** quitar_producto runs with shadow mode and hybrid observation fails
- **THEN** the fuzzy result remains authoritative and is returned unchanged
- **AND** the safe failure category is observed
