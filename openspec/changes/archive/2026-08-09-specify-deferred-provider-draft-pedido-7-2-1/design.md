# Design

## Current execution path

`ProviderInboundMessageCoordinator.accept()` commits only the accepted receipt and pending work item. `process_lease()` owns a separate transaction that acquires or stages the active session, creates and associates one `borrador` pedido only when the session lacks one, runs the existing pipeline, stages outbound rows, finalizes the work item, and commits once.

## Decision

Document the prerequisite in `provider-inbound-processing`, where it belongs. The receipt capability remains limited to webhook acceptance and deferred-work idempotency.

## Shared boundary and fallback

The deferred processor owns the business-effects transaction. A technical failure after staging rolls back the session, pedido, association, pipeline, and outbound effects; existing bounded retry finalization remains responsible for retaining retryable work. Fuzzy and product-recognition policies are outside this change.

## Boundaries

- No implementation or test modifications.
- No new transactions, flushes, retries, or fallback paths.
- No Twilio/WhatsApp operation, deployment, sync, commit, or archive without separate authority.
