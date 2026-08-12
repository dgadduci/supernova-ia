# Capability: intent-classifier

## ADDED Requirements

### Requirement: Order observation vs delivery method boundary

The system SHALL document, in the static prompt template of
`IntentClassifier`, a numbered rule that distinguishes
`set_metodo_de_entrega` from `set_observacion_pedido` whenever the
customer message contains the word "entrega". The rule SHALL state
that `set_metodo_de_entrega` is reserved for selecting or changing the
modality of reception (delivery / home delivery, pickup at the shop,
dine-in / consumir en salón) and SHALL NOT be emitted for messages
that describe logistics, access, route, portón, timbre, building,
security, pets, care, or any other operational indication, even when
the message contains the word "entrega". The rule SHALL state that,
in case of doubt, messages that describe CÓMO / CUÁNDO / DÓNDE to
deliver or that name a recipient must be classified as
`set_observacion_pedido`. The rule SHALL preserve the existing
substring-literal, `no inventes`, `no reutilices`, and
`una única acción → exactamente un intent` contracts. The rule SHALL
NOT introduce a new intent name, a new field, a new dispatcher path,
a keyword heuristic, a second classifier, a second LLM call, or any
change to the model, transport, settings, enum, schema, dispatcher,
pending context, persistence of `Pedido`, observations persistence,
order mapper, outbox, transactions, product recognition, migrations,
endpoints, workers, Railway configuration, or deploy.

#### Scenario: Access / route / pets messages route to set_observacion_pedido

- **WHEN** the static prompt is rendered for the customer message
  `La entrega es por el portón lateral` or `Cuidado con el perro`
- **THEN** the rendered prompt documents the new numbered rule and
  the example for that customer message routes it to
  `set_observacion_pedido`

#### Scenario: Modality selection routes to set_metodo_de_entrega

- **WHEN** the static prompt is rendered for the customer message
  `Quiero envío a domicilio` or `Lo retiro por el local`
- **THEN** the rendered prompt documents the new numbered rule and
  the example for that customer message routes it to
  `set_metodo_de_entrega`

### Requirement: Calibration corpus pins four boundary fixtures

The controlled corpus `CONTROLLED_INTENT_CORPUS` SHALL include four
fixtures that pin the new boundary contract. Each fixture SHALL carry
the exact customer message as its `message`, SHALL pin exactly one
expected intent (`SET_OBSERVACION_PEDIDO` for the two access / care
fixtures, `SET_METODO_DE_ENTREGA` for the two modality fixtures), and
SHALL keep the existing substring-literal contract: the rendered
prompt must contain the fixture message verbatim. The fixtures SHALL
follow the existing regression fixture naming convention
(`F-REG-<slug>`). The corpus SHALL remain safe to render in the
prompt and safe to serialize in the audit report; no fixture SHALL
introduce real customer PII or secrets.

#### Scenario: Two access / care fixtures pin set_observacion_pedido

- **WHEN** the controlled audit runs the
  `La entrega es por el portón lateral` and `Cuidado con el perro`
  fixtures
- **THEN** each fixture pins exactly one intent equal to
  `set_observacion_pedido`

#### Scenario: Two modality fixtures pin set_metodo_de_entrega

- **WHEN** the controlled audit runs the
  `Quiero envío a domicilio` and `Lo retiro por el local` fixtures
- **THEN** each fixture pins exactly one intent equal to
  `set_metodo_de_entrega`

#### Scenario: Boundary fixtures are substrings of their rendered prompts

- **WHEN** each of the four boundary fixtures is rendered through
  `IntentClassifier._build_prompt`
- **THEN** the customer `message` is present verbatim in the rendered
  prompt
