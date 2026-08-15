## MODIFIED Requirements

### Requirement: Authenticated local test channel processes only the selected draft

The panel SHALL expose one clearly labelled local-test message route beneath
its existing HTTP Basic authenticated route family. The route SHALL require a
same-origin custom request header and a bounded nonblank plain-text body. For
the exact selected active draft, it SHALL revalidate `session.id_pedido`,
client/comercio association, and `borrador` state before calling the existing
`process_incoming_message_with_responses` seam for that exact Session. The
existing transactional processor remains the only transaction owner for this
draft path.

For the exact selected active non-draft order, the route SHALL permit only a
clean-context, classifier-derived status query. It SHALL invoke the existing
classifier only to interpret language, accept only exactly one
`consultar_estado_pedido` result, and execute the existing read-only status
orchestration and shared response mapper. It SHALL reject every other
classifier result, multi-intent result, classifier failure, pending context,
or identity/ownership inconsistency using the existing generic rejection. It
SHALL NOT invoke the normal message processor, global dispatcher, mutating
handler, provider, worker, outbox, or Twilio path for a non-draft order.

#### Scenario: Flexible status language is allowed only for the exact confirmed order

- **WHEN** an authenticated operator submits a local message for an exact
  active selected order in a non-draft state with no pending context
- **AND WHEN** the existing classifier returns exactly one
  `consultar_estado_pedido` intent from natural-language status phrasing
- **THEN** the route returns the existing read-only status response and safe
  snapshot for that same order/session identity
- **AND THEN** it does not create, replace, reopen, or modify a session, order,
  order line, pending context, provider row, or outbox row.

#### Scenario: Confirmed-order classifier output cannot authorize a mutation

- **WHEN** an authenticated operator submits a local message for an exact
  active selected order in a non-draft state
- **AND WHEN** classifier output is non-status, multi-intent, invalid, or fails
- **THEN** the route emits the existing generic local rejection without calling
  the normal message processor or any business mutation path
- **AND THEN** it does not search for a successor session or another order.
