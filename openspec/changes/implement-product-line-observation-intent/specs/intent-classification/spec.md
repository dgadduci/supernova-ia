## ADDED Requirements

### Requirement: Declarative product-specific instruction is classified as a line observation

The static intent-classifier prompt SHALL instruct that a declarative
product-specific instruction without a request to add a product maps to
exactly one `set_observacion_producto` intent. It SHALL preserve the literal
customer message in `mensaje`. This classification is based only on message
wording; it SHALL NOT inspect current Pedido lines or authorize a mutation.

#### Scenario: Declarative instruction reaches product-line observation

- **WHEN** the customer sends `La pizza de mozzarella chica es sin aceitunas`
- **THEN** the classifier returns exactly one `set_observacion_producto`
- **AND** its `mensaje` is the original literal message
- **AND** the existing dispatcher routes it to the existing observation
  orchestrator.

#### Scenario: Add wording remains distinct

- **WHEN** the customer sends `quiero una pizza de mozzarella chica sin aceitunas`
- **THEN** the classifier keeps the existing `agregar_producto` intent
- **AND** it does not reinterpret the message as an update because a matching
  line may exist.

## MODIFIED Requirements

### Requirement: Prompt-template identity records intentional static revisions

The prompt-template version SHALL be updated when static intent-classification
guidance changes, including declarative product-observation guidance. The
diagnostic fingerprint SHALL remain derived only from the static template body
and SHALL NOT include the customer message.

#### Scenario: Static prompt body change updates identity and version without leaking the customer message

- **WHEN** the static prompt body of the intent classifier changes
- **THEN** the static prompt-template identity / fingerprint changes
- **AND** the prompt-template version is incremented
- **AND** the identity does not incorporate any text from the customer message.
