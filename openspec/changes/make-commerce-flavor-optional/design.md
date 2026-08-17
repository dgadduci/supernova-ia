# Design: optional commerce communication flavor

## Target Model

```text
Comercio.flavor_comunicacion_id = NULL
    -> no configured presentation flavor
    -> deterministic responses; no style call

Comercio.flavor_comunicacion_id = active flavor ID
    -> selected flavor instruction
    -> existing bounded styler for approved response types only
```

The absence of a foreign-key value is the only no-style sentinel. The styler
must not interpret any flavor code as a special value.

## Migration

The migration order is:

1. Resolve the global row with `codigo = 'neutro'` if it exists.
2. Set `comercios.flavor_comunicacion_id` to `NULL` only for rows referencing
   that row.
3. Alter the foreign-key column to nullable while retaining its foreign key
   and index.

The migration must be safe when no `neutro` row exists and must not change any
non-neutral assignment. Its downgrade must restore a valid non-null value for
`NULL` rows before restoring the constraint; it may resolve the retained
`neutro` catalog row and fail clearly rather than guess if that required row is
missing or inactive.

## Creation and Assignment

Commerce creation leaves `flavor_comunicacion_id` absent. The existing
assignment service is extended, rather than duplicated, to accept an explicit
clear operation. The route/schema represents either a positive flavor ID or
an explicit `null` assignment; it must not overload zero, an empty string, or
a magic flavor code. Clearing updates only the relation and retains existing
validation/authentication and caller-owned transaction behavior.

## Styling Boundary

`_resolve_flavor` already returns `None` for an absent relation. The usability
check becomes a normal active/nonempty-instruction check only. Consequently,
an absent flavor follows the existing `not_attempted` no-call branch. No
response type, prompt, wrapper validation, mapper, outbox, or diagnostic
shape changes.

## Compatibility and Observability

Commerce/configuration read projections must represent no selected flavor
without leaking instruction content. Existing selected non-neutral flavors
remain compatible. The closed diagnostic omits `flavor_code` when no style
attempt can occur, exactly as it already does for unusable configuration.

## Risks

The only material risk is a faulty migration that changes non-neutral
assignments or makes downgrade impossible. Focused migration tests and a
pre/post assignment count check are required. No runtime business action
depends on styling: absence safely degrades to deterministic text.
