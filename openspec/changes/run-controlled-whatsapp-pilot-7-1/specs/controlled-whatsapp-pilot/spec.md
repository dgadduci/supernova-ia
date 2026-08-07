## ADDED Requirements

### Requirement: The pilot uses existing bounded operational surfaces

The controlled pilot SHALL exercise the existing CLI, deployed inbound route,
durable outbox, explicit bounded dispatcher and delivery callback path without
introducing an automatic dispatcher, worker, scheduler, direct database
mutation or alternate message pipeline.

#### Scenario: Operator sends a controlled WhatsApp case

- **WHEN** a designated test number sends an approved pilot case to the
  selected commerce channel
- **THEN** the existing signed webhook and provider coordinator own inbound
  processing, and any customer response is dispatched only by the existing
  explicit bounded dispatcher

### Requirement: Pilot routing is provisioned through one safe bounded boundary

Before a controlled inbound case, the pilot SHALL verify that the designated
test client is active and that provider `twilio` has an active dedicated
channel for the configured sender whose exclusive commerce is the selected
active pilot commerce. The setup boundary SHALL reuse the existing client,
channel and resolver contracts; it SHALL NOT use direct SQL, a routing HTTP
endpoint, an inbound webhook, a message pipeline, a worker or a scheduler.

Its default mode SHALL be read-only verification. An explicit apply mode MAY
create the missing active test client and dedicated channel in one transaction,
or reactivate the exact existing test client only after explicit acknowledgement.
It SHALL NOT reactivate, reassign, replace or delete an existing channel.

#### Scenario: Exact routing state is already ready

- **WHEN** the test client is active and the configured Twilio sender resolves
  through an active dedicated channel to the selected active commerce
- **THEN** verification returns a sanitized `ready` result and stages no
  mutation

#### Scenario: Missing pilot routing is explicitly provisioned

- **WHEN** the explicit apply mode receives a valid selected active commerce,
  one or both missing required pilot records, and no existing channel history
  for the configured Twilio sender
- **THEN** it creates only the missing active client and/or active dedicated
  channel in one transaction, commits once only after exact resolver
  verification succeeds, and returns a sanitized `provisioned` result

#### Scenario: Existing channel is not silently repurposed

- **WHEN** verification finds an inactive channel or a channel whose mode or
  exclusive commerce does not exactly match the pilot
- **THEN** apply returns a typed non-ready result, makes no mutation, and the
  pilot inbound case does not proceed

### Requirement: Routing evidence excludes addresses and messages

The routing setup/verification command SHALL expose only status values,
creation/reactivation flags and safe numeric internal IDs. It SHALL NOT print,
log or include in error text an E.164 address, message body, credential,
signature or database URL.

#### Scenario: Operator retains routing readiness evidence

- **WHEN** the command completes in either verify or apply mode
- **THEN** its output can establish the selected channel/client/commerce state
  without revealing the test number, sender number or message content

### Requirement: Pilot evidence is sanitized and decision-oriented

The pilot SHALL retain only safe operational evidence sufficient to classify
each manual case as pass, supported business outcome, technical failure,
recognition-quality follow-up, or unsupported future capability. Evidence
SHALL NOT include raw message content, personal data, credentials, signatures,
database URLs, prompts, model output or embeddings.

#### Scenario: A manual case needs later diagnosis

- **WHEN** an operator records an unsuccessful pilot case
- **THEN** the record contains an opaque case ID, timestamp, safe provider or
outbox identifier when available, observed category and next decision, without
the raw input or response body

### Requirement: Failed gates stop rather than broaden behavior

The pilot SHALL stop the affected live track when a deployment, Ollama,
webhook, dispatch or callback gate fails. It SHALL NOT enable public traffic,
substitute a model/provider, widen pending candidates, retry through an
unbounded loop, or add a direct operational bypass.

#### Scenario: Provider delivery cannot be verified

- **WHEN** the bounded dispatcher or signed callback gate fails
- **THEN** the operator stops the WhatsApp pilot track and records safe
evidence for a separate approved diagnostic change
