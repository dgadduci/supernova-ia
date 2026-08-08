## ADDED Requirements

### Requirement: Candidate-compatible category prefixes do not suppress explicit product matches

When evaluating product candidates, the fuzzy recognizer SHALL treat a
significant input token that matches the same candidate's catalog category
(using the existing singular/plural normalization) as context rather than a
required product-name token, but only when at least one other significant
product-identifying token remains and matches that candidate under the existing
key-token rules. It SHALL NOT generate candidates from a category token or
ignore a token for a candidate in another category.

#### Scenario: Explicit category prefix resolves only product candidates in that category

- **WHEN** the input is `3 Pizza napolitana` and the catalog has `Napolitana`
  product-presentations in category `Pizzas` plus unrelated products
- **THEN** the recognizer returns only the existing Napolitana presentation
  candidates with quantity `3`
- **AND** it does not return a category-level group or an unmatched fragment
- **AND** it does not expose an unrelated Pizza or product from another
  category

#### Scenario: Category-only input remains safe ambiguity

- **WHEN** the input is `3 pizza` and there is no product-identifying token
- **THEN** the recognizer keeps the existing category-level ambiguity result
- **AND** it exposes no product IDs as ordinary candidates

#### Scenario: Incompatible category cannot be ignored

- **WHEN** the input category token does not match a candidate's own category
- **THEN** that token remains required under the existing key-token filtering
- **AND** the candidate is not promoted merely because its product name
  otherwise matches
