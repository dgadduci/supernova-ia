# Design: plural presentation product recognition

## Decision

Add a two-entry, presentation-specific normalization map in the existing
`_normalizar_palabras_pedido` path after quantity-word normalization and before
`_singularizar_simple`:

```text
grandes -> grande
chicas  -> chica
```

Then retain the current generic singularization and alias behavior unchanged.
This prevents `grandes` becoming `grand`, so it remains a known size and does
not participate as an unmatched product token.

```text
quiero dos napolitanas grandes
  -> quiero 2 napolitana grande
  -> significant product token: napolitana
  -> presentation filter: grande
  -> existing exact catalog candidate + quantity 2
  -> existing agregar_producto handler increments the line
```

## Boundary and fallback

The map is not an alias catalog, fuzzy rule or a generic `-es` grammar change.
It applies only to the two approved presentation plural literals. Other text
continues through the pre-existing normalization and recognition pipeline.
The recognized presentation must still be filtered against the commerce's
existing catalog, so normalization cannot introduce a missing product or a
candidate from another commerce.

No LLM is added or promoted. In hybrid-authoritative mode, the existing
recognizer boundary still decides according to its configured policy. No
fallback from a semantic result to fuzzy is introduced.

## Tests

- Normalization and recognition of `quiero dos napolitanas grandes` selects
  only Napolitana Grande and carries quantity `2`.
- The analogous `chicas` form selects only Chica when that presentation is in
  the supplied catalog.
- Singular `grande`/`chica`, absent products, ambiguity and existing quantity
  behavior stay unchanged.
- One focused add-product execution proof verifies quantity `2` reaches the
  existing caller-owned increment path with no new transaction control.
