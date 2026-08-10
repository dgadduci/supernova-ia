# Specify deferred provider draft-pedido guarantee

## Why

`ensure-provider-inbound-draft-pedido-7-2` was designed before inbound provider processing was deferred. Its proposed webhook-time session/pedido mutation now conflicts with the archived deferred-processing contract. The implemented deferred processor already creates and associates a draft pedido before the existing message pipeline, but the canonical `provider-inbound-processing` capability does not state that guarantee.

## What Changes

- Add a requirement to `provider-inbound-processing` defining the draft-pedido prerequisite in the leased deferred-processing transaction.
- State the first-processing, existing-orderless-session, existing-associated-session, and technical-failure outcomes already covered by the focused integration tests.

## Scope and non-goals

This is documentation-only. It does not change the webhook acceptance boundary, deferred-work model, coordinator code, repositories, tests, transaction behavior, Railway configuration, Twilio traffic, or runtime behavior. The obsolete `ensure-provider-inbound-draft-pedido-7-2` change is not archived or edited by this change.

## Validation

The user will validate this OpenSpec change and the updated canonical capability locally before any archive is considered.
