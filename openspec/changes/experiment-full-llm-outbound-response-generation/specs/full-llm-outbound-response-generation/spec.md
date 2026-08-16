# full-llm-outbound-response-generation Specification

## ADDED Requirements

### Requirement: Experimental full-message generation follows deterministic business execution

For an active selected flavor other than `neutro`, the experimental outbound
styler MAY make at most one LLM batch request per inbound turn for eligible
normal responses. It SHALL run only after deterministic `CustomerResponse`
values are rendered and SHALL not alter persisted state, intent, status, or
response order.

#### Scenario: Generated message is presentation only

- **WHEN** deterministic processing has successfully produced an eligible
  product-add response
- **THEN** the full-message generator receives that response only after the
  product mutation is complete
- **AND THEN** a structurally valid generated message may replace only the
  customer-visible message text
- **AND THEN** the persisted product, quantity, price, session and order state
  remain unchanged.

### Requirement: Full-message prompt uses factual message as its sole business source

The experimental full-message prompt SHALL include the deterministic factual
message and response type for eligible items, plus the selected internal flavor
instruction. It SHALL require the LLM to preserve all supplied concrete facts
and menu lines, add no facts, and return a closed JSON envelope. Raw inbound
text and ineligible response text SHALL NOT be sent to the LLM. Full and
category menus SHALL retain every category, line, product, presentation/unit,
price and factual order from the deterministic message; the LLM may add only
non-factual natural framing around that inventory. Status output SHALL NOT
state preparation, dispatch, delivery, estimated timing or another logistics
fact unless that fact appears explicitly in the deterministic message.

#### Scenario: Menu is supplied intact for natural presentation

- **WHEN** an eligible full or category menu response is styled under a
  non-neutral flavor
- **THEN** the prompt includes its deterministic menu text as the factual
  source
- **AND THEN** it instructs the LLM to preserve every menu line
- **AND THEN** runtime diagnostics do not expose that menu text or rendered
  prompt.

#### Scenario: Status response does not infer logistics absent from factual text

- **WHEN** an eligible order-status response is styled under a non-neutral
  flavor
- **THEN** the prompt instructs the LLM to retain only status and logistics
  facts explicitly present in its deterministic factual message
- **AND THEN** it prohibits inferred preparation, dispatch, arrival or timing
  claims.

### Requirement: Experimental generation has structural fallback but no semantic output validator

The system SHALL reject malformed envelopes, incorrect index/count/order,
empty messages, and technical generation failures and SHALL use the original
deterministic message for affected output. It SHALL NOT implement semantic
comparison of generated text with factual source text in this experiment.

#### Scenario: Structurally invalid output retains deterministic message

- **WHEN** the LLM returns invalid JSON structure or an empty message
- **THEN** the customer receives the original deterministic response
- **AND THEN** the system does not retry, mutate business state, or invoke a
  second LLM call.

### Requirement: Neutral and excluded outcomes remain deterministic

The system SHALL not make a full-message generation request for `neutro`,
missing/inactive/unusable flavor, zero eligible responses, errors, rejections,
pending/ambiguous outcomes, `desconocida`, or customer-free-text acknowledgement
families. Such responses SHALL remain unchanged.

#### Scenario: Ambiguous selection remains exact under a non-neutral flavor

- **WHEN** an active non-neutral flavor has a pending product-selection
  clarification response
- **THEN** the system does not call the full-message LLM
- **AND THEN** it returns the existing deterministic clarification unchanged.
