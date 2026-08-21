# Design: scrollable Emulator conversation history

## Decision

Keep the feature entirely in the existing server-rendered detail page and its
existing inline browser handler. Replace the Emulator result container's
single-snapshot rendering with a bounded in-memory collection of turns keyed
by `synthetic_inbound_id`. Do not add a backend endpoint or a second status
source.

## Browser state

The handler maintains a page-local map and ordered list:

```text
synthetic_inbound_id
  -> { sentText, status, responseText, providerSid, renderedState }
```

The ordered list preserves submission order. A new submission creates one
`Enviado` row immediately. The existing polling callback updates the same
turn for `accepted`, `pending`, `processed` and terminal outcomes. A response
body or error is rendered at most once for that turn.

The state is intentionally volatile. It must not use localStorage,
sessionStorage, cookies, URL parameters or server persistence.

## Rendering

The detail page exposes a dedicated container such as
`data-debug-emulator-conversation` with list semantics. Each row uses safe DOM
construction and `textContent`; operator input and response text are never
interpreted as markup. Metadata is bounded using the existing display-string
guard and the list has a fixed maximum number of rows.

The list has a fixed height and `overflow-y: auto`, wraps long text and scrolls
to the newest row after a new turn or response update. The newest state remains
available in the existing status/result area only if that area is needed for
backward-compatible selectors; the conversation list is the primary handoff
surface.

## Status mapping

```text
submit accepted       -> Enviado + Estado: accepted/pending
processed/sent body   -> one Respuesta recibida row
retryable/terminal    -> one bounded Error/Estado row
transport/rejection   -> one generic Error row
duplicate poll        -> update existing turn, no duplicate row
```

The implementation must use the existing allowed status set and terminal
polling set. It must not infer business success from an HTTP 200 alone or
invent response text when the server returns no outbound body.

## Accessibility and handoff

Use a visible heading, a list/listitem structure, readable labels and an
`aria-live` strategy that does not replace the whole conversation on every
poll. Text remains selectable so the operator can copy the visible history.
The UI must continue to identify that the history is only for the current
page.

## Failure and compatibility

If a status payload is malformed or the container is absent, preserve the
existing generic status/rejection path. Keep the local channel's
`data-debug-transcript` handler and selectors unchanged. Keep existing
Emulator form selectors, JSON request body, origin header, status URL and
polling limits unchanged.

## Testing strategy

Extend the existing server-rendered panel contract tests. Assert structure and
script contracts rather than adding a live browser dependency. Cover safe DOM
rendering, fixed scroll viewport, page-local state, sent/received labels and
synthetic-id deduplication markers. Do not add integration calls to Railway,
Twilio, the Emulator or the worker.
