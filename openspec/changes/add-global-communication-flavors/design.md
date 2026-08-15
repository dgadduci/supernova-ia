# Design: global communication flavors without response rewriting

## Data model

Create `flavors_comunicacion` as a global catalog:

| Field | Meaning |
| --- | --- |
| `id` | Internal primary key |
| `codigo` | Unique immutable machine key, e.g. `neutro` |
| `nombre` | Administrator-visible label |
| `descripcion` | Administrator-facing explanation of the profile |
| `instruccion_llm` | Internal future style directive; never commerce input or API output |
| `activo` | Whether a commerce may select the flavor |
| `version` | Profile instruction revision identifier |
| timestamps | Existing project convention for auditability |

`comercios.flavor_comunicacion_id` references this catalog. A relationship
allows the existing configuration read path to expose safe metadata only.

## Migration and seed sequence

The migration must be safe for existing databases:

1. Create `flavors_comunicacion` and insert the six canonical global records,
   including one active row whose code is exactly `neutro`.
2. Add `flavor_comunicacion_id` to `comercios` as nullable temporarily.
3. Backfill every existing commerce by resolving the seeded `neutro` row by
   code, not by assumed numeric ID.
4. Add the FK and make the column non-null.

The seed is idempotent for the migration's own fresh-upgrade contract. It does
not expose an application API for arbitrary profile creation or mutation.

## Read and selection surfaces

- `GET` active flavors returns only safe metadata: `id`, `codigo`, `nombre`,
  `descripcion`, `version` and `activo`.
- Existing commerce/configuration reads include the selected flavor's same
  safe metadata.
- A focused authenticated administrator operation accepts only a flavor ID for
  one commerce. It resolves the global row, rejects unknown/inactive rows, and
  changes only `flavor_comunicacion_id`.

The selected profile is intentionally an explicit association, not copied
flavor text. `instruccion_llm` remains server-internal for the future
embellisher.

## Transaction and error handling

Repository/service collaborators remain transaction-free; the existing router
dependency/application transaction owner commits on success or rolls back on
failure. Unknown/inactive flavor selection uses existing style of explicit
domain error and mapped HTTP response. It must not leak profile instructions
or mutate the commerce.

## Compatibility

All old commerces and new commerces resolve to `neutro`. No current message
builder reads the association in this phase, so every outbound factual message
remains byte-for-byte unchanged. This is intentional and is covered by a
regression test around the response mapper/current response path.

## Deferred phase boundary

Phase 2 will introduce an outbound-only style interpreter after deterministic
response creation. It will use the selected profile's internal instruction,
never use flavor text as business authority, and retain deterministic fallback.
This change adds none of that code or LLM traffic.
