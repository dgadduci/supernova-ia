# Design: natural commerce choice matching

The matcher works only with `list_active_for_comercio` candidates already loaded by the existing orchestrator.

1. Normalize input and candidate code/description as today.
2. Return unique exact code/description match; preserve current ambiguity.
3. Otherwise tokenize normalized input and each normalized candidate description on whitespace. A candidate qualifies only when every non-empty description token is present as a whole input token.
4. One qualifying candidate is `unique`; multiple are `ambiguous`; none are `not_active`.

For example, `pago en efectivo prueba cierre` contains all description tokens of `efectivo prueba cierre`; it therefore selects that one commerce-enabled option. `efectivo` with both `Efectivo` and `Efectivo con descuento` remains uniquely the first only if the latter's extra tokens are absent; text satisfying two descriptions returns `ambiguous`.

This is containment, not fuzzy matching: no substring (`efect`), code fragments, typo distance, aliases or global candidate lookup. The matcher returns only a candidate/reason and does not mutate DB state; the existing orchestrator remains transaction owner.
