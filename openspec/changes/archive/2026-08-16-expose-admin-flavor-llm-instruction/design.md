# Design: protected flavor-instruction listing

## Design

Use the existing `GET /flavors-comunicacion` endpoint rather than adding a
parallel endpoint. Its router already applies `require_admin_token` to every
route. Expand `FlavorComunicacionResponse` with the bounded persisted
`instruccion_llm` field, while leaving `FlavorComunicacionSummary` unchanged.

```text
authenticated administrator
  -> GET /flavors-comunicacion
  -> existing active-only service read
  -> FlavorComunicacionResponse (includes instruccion_llm)

commerce/configuration response
  -> FlavorComunicacionSummary (does not include instruccion_llm)
```

This preserves one catalog reading path and the existing commerce projection
boundary. There is no new repository query, database schema, router prefix,
or transaction owner.

## Security and Privacy

- Router-level `require_admin_token` remains mandatory; no unauthenticated
  route or query flag can expose the instruction.
- The response contains no customer, session, order, or provider content.
- The instruction must not be rendered in logs, diagnostics, exception
  details, assignment responses, or nested commerce/configuration objects.
- The existing header authentication has no finer-grained roles. That is an
  accepted current boundary, not a reason to introduce an authorization
  framework in this small change.

## Failure and Transaction Behavior

Authentication failure happens before service creation. Existing service and
framework error behavior stays unchanged. The route remains a pure read and
must not control the session transaction.

## Compatibility

Clients of the list endpoint receive one additive field. Clients of commerce
and configuration endpoints retain their exact flavor-summary shape. The
outbound styler continues reading the same model value; neither prompt content
nor LLM invocation count changes.
