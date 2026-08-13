"""Focused coverage for the ``agregar_producto`` contract default quantity.

The processor treats the already-declared ``cantidad`` default ``1`` as an
authoritative deterministic business value when recognition omits quantity
entirely. Explicit recognized quantities are preserved unchanged and the
normalized recognizer result is never mutated.
"""
from __future__ import annotations

import unittest

from backend.intents.contracts.agregar_producto import AGREGAR_PRODUCTO_CONTRACT
from backend.intents.processor import process_agregar_producto


def _normalized(resolved_data: dict, candidate_ids: list[int] | None = None) -> dict:
    return {
        "resolved_data": resolved_data,
        "candidate_ids": list(candidate_ids or []),
        "unavailable_items": [],
        "not_found_items": [],
    }


class OmittedQuantityUsesContractDefaultTest(unittest.TestCase):
    def test_contract_declares_default_one(self):
        self.assertEqual(
            AGREGAR_PRODUCTO_CONTRACT["requirements"]["cantidad"]["default"], 1
        )

    def test_omitted_quantity_is_completed_with_default_one(self):
        processed = process_agregar_producto(
            "quiero una pizza", _normalized({"producto_presentacion_id": 42})
        )

        self.assertEqual(processed.status, "ready")
        self.assertEqual(
            processed.resolved_data, {"producto_presentacion_id": 42, "cantidad": 1}
        )
        cantidad = next(r for r in processed.requirements if r.name == "cantidad")
        self.assertEqual(cantidad.status, "completed")
        self.assertEqual(cantidad.value, 1)

    def test_two_candidates_without_quantity_pend_only_on_presentation(self):
        processed = process_agregar_producto(
            "quiero mozzarella", _normalized({}, [101, 102])
        )

        self.assertEqual(processed.status, "pending_resolution")
        self.assertEqual(processed.candidate_ids, [101, 102])
        self.assertEqual(processed.resolved_data, {"cantidad": 1})
        cantidad = next(r for r in processed.requirements if r.name == "cantidad")
        self.assertEqual(cantidad.status, "completed")
        self.assertEqual(cantidad.value, 1)
        presentacion = next(
            r for r in processed.requirements if r.name == "producto_presentacion_id"
        )
        self.assertEqual(presentacion.status, "pending")
        self.assertIsNone(presentacion.value)
        pending_names = {
            r.name for r in processed.requirements if r.status == "pending"
        }
        self.assertEqual(pending_names, {"producto_presentacion_id"})


class ExplicitQuantityIsPreservedTest(unittest.TestCase):
    def test_explicit_positive_quantity_is_not_replaced_by_default(self):
        processed = process_agregar_producto(
            "quiero 3 pizzas",
            _normalized({"producto_presentacion_id": 42, "cantidad": 3}),
        )

        self.assertEqual(processed.status, "ready")
        self.assertEqual(processed.resolved_data["cantidad"], 3)
        cantidad = next(r for r in processed.requirements if r.name == "cantidad")
        self.assertEqual(cantidad.status, "completed")
        self.assertEqual(cantidad.value, 3)

    def test_explicit_quantity_with_pending_presentation_is_preserved(self):
        processed = process_agregar_producto(
            "quiero 2 mozzarellas", _normalized({"cantidad": 2}, [101, 102])
        )

        self.assertEqual(processed.status, "pending_resolution")
        self.assertEqual(processed.resolved_data["cantidad"], 2)


class NormalizedInputIsNotMutatedTest(unittest.TestCase):
    def test_default_completion_does_not_mutate_normalized_input(self):
        resolved_data: dict = {"producto_presentacion_id": 42}
        normalized = _normalized(resolved_data)

        processed = process_agregar_producto("quiero una pizza", normalized)

        self.assertEqual(resolved_data, {"producto_presentacion_id": 42})
        self.assertEqual(normalized["resolved_data"], {"producto_presentacion_id": 42})
        self.assertIsNot(processed.resolved_data, resolved_data)
        self.assertIsNot(processed.resolved_data, normalized["resolved_data"])

    def test_missing_resolved_data_key_still_yields_default(self):
        normalized: dict = {"candidate_ids": [101, 102]}

        processed = process_agregar_producto("quiero mozzarella", normalized)

        self.assertEqual(processed.resolved_data, {"cantidad": 1})
        self.assertNotIn("resolved_data", normalized)


if __name__ == "__main__":
    unittest.main()
