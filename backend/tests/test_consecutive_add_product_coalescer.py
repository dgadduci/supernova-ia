"""Focused unit tests for the shared, pure coalescing helper.

The helper is the single decision boundary that decides which processed
items are rendered as customer confirmations. These tests pin its
eligibility, ordering, immutability, and terminal-only semantics for both
consumers: the local response orchestrator and the provider outbox mapper.
"""
from __future__ import annotations

import unittest

from backend.intents.responses.consecutive_add_product_coalescer import (
    coalesce_consecutive_add_product_intents,
)
from backend.intents.schemas.processed_intent import ProcessedIntent


def _add(
    *,
    ppid: int | None,
    status: str = "executed",
    intent: str = "agregar_producto",
    cantidad: int | None = 1,
) -> ProcessedIntent:
    resolved: dict[str, object] = {}
    if cantidad is not None:
        resolved["cantidad"] = cantidad
    if ppid is not None:
        resolved["producto_presentacion_id"] = ppid
    return ProcessedIntent(
        intent=intent,
        source_text="hola",
        status=status,  # type: ignore[arg-type]
        handler="agregar_producto",
        recognizer="recognizer_productos",
        resolved_data=resolved,
    )


class EmptyAndTrivialInputTest(unittest.TestCase):
    def test_empty_input_returns_empty_list(self):
        self.assertEqual(coalesce_consecutive_add_product_intents([]), [])

    def test_single_eligible_returns_unchanged(self):
        item = _add(ppid=1, cantidad=2)
        result = coalesce_consecutive_add_product_intents([item])
        self.assertEqual(result, [item])

    def test_single_non_eligible_returns_unchanged(self):
        pending = _add(ppid=1, status="pending_resolution")
        rejected = ProcessedIntent(
            intent="agregar_producto",
            source_text="x",
            status="rejected",
            handler="agregar_producto",
        )
        unknown = ProcessedIntent(
            intent="desconocida",
            source_text="x",
            status="rejected",
            handler="desconocida",
        )
        for item in (pending, rejected, unknown):
            with self.subTest(status=item.status, intent=item.intent):
                result = coalesce_consecutive_add_product_intents([item])
                self.assertEqual(result, [item])


class EligibleGroupCoalescingTest(unittest.TestCase):
    def test_two_consecutive_same_id_yields_only_terminal(self):
        first = _add(ppid=1, cantidad=1)
        terminal = _add(ppid=1, cantidad=3)
        result = coalesce_consecutive_add_product_intents([first, terminal])
        self.assertEqual(result, [terminal])

    def test_three_consecutive_same_id_yields_only_terminal(self):
        first = _add(ppid=1, cantidad=1)
        middle = _add(ppid=1, cantidad=2)
        terminal = _add(ppid=1, cantidad=5)
        result = coalesce_consecutive_add_product_intents(
            [first, middle, terminal]
        )
        self.assertEqual(result, [terminal])

    def test_terminal_carries_authoritative_cantidad_final(self):
        intermediate = _add(ppid=1, cantidad=1)
        terminal = _add(ppid=1, cantidad=4)
        terminal.resolved_data["cantidad_final"] = 7
        result = coalesce_consecutive_add_product_intents(
            [intermediate, terminal]
        )
        self.assertEqual(len(result), 1)
        self.assertIs(result[0], terminal)
        self.assertEqual(result[0].resolved_data.get("cantidad_final"), 7)


class IneligibleSeparationTest(unittest.TestCase):
    def test_different_presentations_are_not_coalesced(self):
        a = _add(ppid=1, cantidad=1)
        b = _add(ppid=2, cantidad=2)
        result = coalesce_consecutive_add_product_intents([a, b])
        self.assertEqual(result, [a, b])

    def test_non_consecutive_same_id_is_not_coalesced(self):
        first = _add(ppid=1, cantidad=1)
        separator = ProcessedIntent(
            intent="agregar_producto",
            source_text="x",
            status="pending_resolution",
            handler="agregar_producto",
        )
        later = _add(ppid=1, cantidad=4)
        result = coalesce_consecutive_add_product_intents(
            [first, separator, later]
        )
        self.assertEqual(result, [first, separator, later])

    def test_separator_between_two_groups_keeps_three_items(self):
        a1 = _add(ppid=1, cantidad=1)
        a2 = _add(ppid=1, cantidad=2)
        separator = ProcessedIntent(
            intent="agregar_producto",
            source_text="x",
            status="rejected",
            handler="agregar_producto",
        )
        b = _add(ppid=2, cantidad=3)
        result = coalesce_consecutive_add_product_intents(
            [a1, a2, separator, b]
        )
        self.assertEqual(result, [a2, separator, b])

    def test_trailing_separator_keeps_only_terminal(self):
        a1 = _add(ppid=1, cantidad=1)
        a2 = _add(ppid=1, cantidad=3)
        separator = ProcessedIntent(
            intent="agregar_producto",
            source_text="x",
            status="pending_resolution",
            handler="agregar_producto",
        )
        result = coalesce_consecutive_add_product_intents(
            [a1, a2, separator]
        )
        self.assertEqual(result, [a2, separator])

    def test_different_intents_are_not_coalesced(self):
        agregar = _add(ppid=1, cantidad=1)
        quitar = ProcessedIntent(
            intent="quitar_producto",
            source_text="x",
            status="executed",
            handler="quitar_producto",
            resolved_data={"producto_presentacion_id": 1, "cantidad": 1},
        )
        result = coalesce_consecutive_add_product_intents([agregar, quitar])
        self.assertEqual(result, [agregar, quitar])


class StatusAndIdentifierEligibilityTest(unittest.TestCase):
    def test_pending_add_is_not_eligible(self):
        a1 = _add(ppid=1, status="executed", cantidad=1)
        pending = _add(ppid=1, status="pending_resolution")
        a2 = _add(ppid=1, status="executed", cantidad=4)
        result = coalesce_consecutive_add_product_intents([a1, pending, a2])
        self.assertEqual(result, [a1, pending, a2])

    def test_rejected_add_is_not_eligible(self):
        a1 = _add(ppid=1, cantidad=1)
        rejected = _add(ppid=1, status="rejected")
        result = coalesce_consecutive_add_product_intents([a1, rejected])
        self.assertEqual(result, [a1, rejected])

    def test_failed_add_is_not_eligible(self):
        a1 = _add(ppid=1, cantidad=1)
        failed = _add(ppid=1, status="failed")
        result = coalesce_consecutive_add_product_intents([a1, failed])
        self.assertEqual(result, [a1, failed])

    def test_missing_presentation_id_is_not_eligible(self):
        a1 = _add(ppid=1, cantidad=1)
        missing = _add(ppid=None, cantidad=2)
        a2 = _add(ppid=1, cantidad=4)
        result = coalesce_consecutive_add_product_intents([a1, missing, a2])
        self.assertEqual(result, [a1, missing, a2])

    def test_zero_presentation_id_is_not_eligible(self):
        a1 = _add(ppid=1, cantidad=1)
        zero = _add(ppid=0, cantidad=2)
        result = coalesce_consecutive_add_product_intents([a1, zero])
        self.assertEqual(result, [a1, zero])

    def test_negative_presentation_id_is_not_eligible(self):
        a1 = _add(ppid=1, cantidad=1)
        negative = _add(ppid=-1, cantidad=2)
        result = coalesce_consecutive_add_product_intents([a1, negative])
        self.assertEqual(result, [a1, negative])

    def test_non_integer_presentation_id_is_not_eligible(self):
        a1 = _add(ppid=1, cantidad=1)
        string_id = ProcessedIntent(
            intent="agregar_producto",
            source_text="x",
            status="executed",
            handler="agregar_producto",
            resolved_data={
                "producto_presentacion_id": "1",
                "cantidad": 2,
            },
        )
        result = coalesce_consecutive_add_product_intents([a1, string_id])
        self.assertEqual(result, [a1, string_id])

    def test_boolean_presentation_id_is_not_eligible(self):
        a1 = _add(ppid=1, cantidad=1)
        bool_id = ProcessedIntent(
            intent="agregar_producto",
            source_text="x",
            status="executed",
            handler="agregar_producto",
            resolved_data={
                "producto_presentacion_id": True,
                "cantidad": 2,
            },
        )
        result = coalesce_consecutive_add_product_intents([a1, bool_id])
        self.assertEqual(result, [a1, bool_id])


class ImmutabilityTest(unittest.TestCase):
    def test_input_items_are_not_mutated(self):
        first = _add(ppid=1, cantidad=1)
        terminal = _add(ppid=1, cantidad=3)
        first_snapshot = first.model_dump()
        terminal_snapshot = terminal.model_dump()
        coalesce_consecutive_add_product_intents([first, terminal])
        self.assertEqual(first.model_dump(), first_snapshot)
        self.assertEqual(terminal.model_dump(), terminal_snapshot)

    def test_returned_items_are_the_input_objects(self):
        first = _add(ppid=1, cantidad=1)
        terminal = _add(ppid=1, cantidad=3)
        result = coalesce_consecutive_add_product_intents([first, terminal])
        self.assertIs(result[0], terminal)


if __name__ == "__main__":
    unittest.main(verbosity=2)
