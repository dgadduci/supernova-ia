# intent-classification Specification

## Purpose
TBD - created by archiving change fix-remove-product-verb-classification. Update Purpose after archive.
## Requirements
### Requirement: Product-removal wording is classified as removal

The static intent-classifier prompt SHALL instruct that a message whose
meaning is to remove products from the current order maps to exactly one
`quitar_producto` intent. It SHALL give representative wording including
`quita`, `quitá`, `quitar`, `saca`, `sacá`, `sacar`, `retirá`, `retirar`,
`eliminá`, and `eliminar`; that wording is guidance for semantic
classification, not a closed vocabulary. It SHALL NOT map a clear product-
removal request to `agregar_producto`.

#### Scenario: Imperative `saca` preserves removal intent

- **WHEN** the customer sends `saca una de mozzarella chica`
- **THEN** the classifier returns one `quitar_producto` intent
- **AND** its `mensaje` is a literal substring of that customer message.

#### Scenario: Infinitive `sacar` preserves removal intent

- **WHEN** the customer sends `sacar dos de mozzarella chica`
- **THEN** the classifier returns one `quitar_producto` intent
- **AND** the dispatcher routes it only to the existing remove path.

#### Scenario: Representative synonym preserves removal intent

- **WHEN** the customer sends `retirá una de mozzarella chica`
- **THEN** the classifier returns one `quitar_producto` intent
- **AND** its `mensaje` is a literal substring of that customer message.

#### Scenario: Product add remains distinct

- **WHEN** the customer expresses an add request without removal wording
- **THEN** existing `agregar_producto` classification remains unchanged.

### Requirement: Prompt-template identity records intentional static revisions

The prompt-template version SHALL be updated when static removal-verb guidance
changes. The diagnostic fingerprint SHALL remain derived only from the static
template body and SHALL NOT include the customer message.

#### Scenario: Static prompt body change updates identity and version without leaking the customer message

- **WHEN** the static prompt body of the intent classifier changes
- **THEN** the static prompt-template identity / fingerprint changes
- **AND** the prompt-template version is incremented
- **AND** the identity does not incorporate any text from the customer message.

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

#### Scenario: Natural category-browse wording remains a menu intent

- **WHEN** the customer asks `qué gustos de empanadas tenés` or
  `qué bebidas tenés`
- **THEN** the classifier returns `ver_menu`
- **AND THEN** it does not classify the message as `consultar_producto`.

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
