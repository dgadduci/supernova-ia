## ADDED Requirements

### Requirement: Static classification guidance distinguishes category browsing from product detail

The static primary intent-classifier prompt SHALL classify a request to list
products within a category as `ver_menu`, including ordinary category-browse
phrasing such as pizzas, empanadas or beverages. It SHALL preserve
`consultar_producto` for a request about one concrete product, price,
presentation, ingredient or availability. This guidance SHALL not embed
runtime commerce category names or product catalog data in the primary prompt.

#### Scenario: Category browse remains a menu intent

- **WHEN** the customer asks `qué pizzas hay`
- **THEN** the classifier returns `ver_menu`
- **AND THEN** its `mensaje` remains a literal substring of the customer
  message.

#### Scenario: Concrete product detail remains distinct

- **WHEN** the customer asks `cuánto sale la napolitana grande`
- **THEN** the classifier returns `consultar_producto`
- **AND THEN** it does not emit `ver_menu` for that request.

### Requirement: Primary prompt identity captures category-browse guidance

When the static category-browse guidance changes, the primary prompt-template
version SHALL be incremented and its fingerprint SHALL change based only on
the static template body. It SHALL not incorporate customer text or runtime
category candidates.

#### Scenario: Category guidance changes static identity without runtime catalog leakage

- **WHEN** static category-browse guidance changes
- **THEN** the prompt-template version and static fingerprint change
- **AND THEN** runtime category names and the customer message are absent from
  the diagnostic identity.
