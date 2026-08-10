## ADDED Requirements

### Requirement: Deferred processing ensures a draft pedido before the pipeline

The bounded deferred processor SHALL acquire or stage the active conversation session for the accepted receipt before calling the existing message pipeline. When that session has no `id_pedido`, the processor SHALL stage exactly one `borrador` pedido, associate its generated ID to the same session, and then invoke the pipeline. When the session already has an `id_pedido`, the processor SHALL NOT create, replace, or reassociate a pedido. The session, any newly staged pedido and association, pipeline effects, outbound rows, and work-item finalization SHALL become durable only through the processor's one final commit.

#### Scenario: First deferred processing creates the missing draft pedido

- **WHEN** a leased accepted receipt is processed and its acquired or staged active session has no `id_pedido`
- **THEN** exactly one `borrador` pedido is staged and associated to that session before the existing message pipeline runs
- **AND** the session, pedido, association, pipeline effects, outbound rows, and processed work state become durable through the processor's final commit

#### Scenario: Existing orderless session receives one draft pedido

- **WHEN** a leased accepted receipt resolves an existing active session whose `id_pedido` is null
- **THEN** the processor stages and associates exactly one `borrador` pedido before the existing message pipeline runs

#### Scenario: Existing pedido association remains unchanged

- **WHEN** a leased accepted receipt resolves an active session whose `id_pedido` is already non-null
- **THEN** the processor does not create, replace, or reassociate a pedido
- **AND** existing message processing continues

#### Scenario: Technical failure rolls back newly staged business effects

- **WHEN** session/pedido staging, pipeline processing, or outbound staging raises a technical failure before the processor commit
- **THEN** the processor rolls back newly staged session, pedido, association, pipeline, and outbound effects
- **AND** existing bounded failure handling retains or finalizes the work item according to its retry policy
