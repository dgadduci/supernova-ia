"""Shared, pure response-only coalescing helper.

The local HTTP/CLI orchestrator and the provider outbox mapper both translate
an ordered list of :class:`ProcessedIntent` items into rendered customer
responses. When the transactional processor returns a consecutive group of
executed ``agregar_producto`` results for the same product presentation, all
domain mutations are already correct, and only the terminal item's
``cantidad_final`` is authoritative for the confirmation. Emitting one
response per processed item would therefore surface an intermediate quantity
to the customer before the final confirmation.

This module owns the single decision of which items to render. It is a pure
read-only function over the supplied sequence and never mutates the input
items, the resolved data, or any external state.

Eligibility rules (all must hold):

* ``intent == "agregar_producto"``.
* ``status == "executed"``.
* ``resolved_data["producto_presentacion_id"]`` is a positive integer (and
  not a ``bool``).

A group is a maximal run of consecutive eligible items sharing the same
identifier. The function returns a list preserving the original order where
each eligible group is reduced to its terminal item. Non-eligible items and
eligible runs separated by anything other than another eligible same-id item
keep their existing one-item-per-response behavior.
"""
from __future__ import annotations

from collections.abc import Sequence as SequenceABC

from backend.intents.schemas.processed_intent import ProcessedIntent

_INTENT = "agregar_producto"
_STATUS = "executed"
_ID_KEY = "producto_presentacion_id"


def _eligible_identifier(item: ProcessedIntent) -> int | None:
    if item.intent != _INTENT:
        return None
    if item.status != _STATUS:
        return None
    raw = item.resolved_data.get(_ID_KEY)
    if type(raw) is not int or isinstance(raw, bool) or raw <= 0:
        return None
    return raw


def coalesce_consecutive_add_product_intents(
    intents: SequenceABC[ProcessedIntent],
) -> list[ProcessedIntent]:
    """Return the rendered set of intents for the caller to translate.

    The returned list preserves the original order. For each eligible run of
    consecutive same-presentation executed additions, only the terminal item
    is yielded; every non-eligible item is yielded unchanged. The input
    sequence and its items are not mutated.
    """
    rendered: list[ProcessedIntent] = []
    group_open = False
    group_id: int | None = None
    terminal: ProcessedIntent | None = None

    for item in intents:
        identifier = _eligible_identifier(item)
        if identifier is not None and group_open and identifier == group_id:
            terminal = item
            continue
        if group_open and terminal is not None:
            rendered.append(terminal)
        if identifier is not None:
            group_open = True
            group_id = identifier
            terminal = item
        else:
            group_open = False
            group_id = None
            terminal = None
            rendered.append(item)

    if group_open and terminal is not None:
        rendered.append(terminal)

    return rendered


__all__ = ["coalesce_consecutive_add_product_intents"]
