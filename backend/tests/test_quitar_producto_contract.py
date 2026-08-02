import importlib
import unittest

from backend.intents.contracts import quitar_producto as contract_module
from backend.intents.contracts.quitar_producto import QUITAR_PRODUCTO_CONTRACT


class QuitarProductoContractShapeTest(unittest.TestCase):
    def test_contract_is_a_dict(self):
        self.assertIsInstance(QUITAR_PRODUCTO_CONTRACT, dict)

    def test_top_level_keys_are_exactly_documented(self):
        self.assertEqual(
            set(QUITAR_PRODUCTO_CONTRACT.keys()),
            {"intent", "recognizer", "handler", "requirements"},
        )

    def test_top_level_field_values(self):
        self.assertEqual(QUITAR_PRODUCTO_CONTRACT["intent"], "quitar_producto")
        self.assertEqual(
            QUITAR_PRODUCTO_CONTRACT["recognizer"], "recognizer_quitar_producto"
        )
        self.assertEqual(QUITAR_PRODUCTO_CONTRACT["handler"], "quitar_producto")

    def test_requirements_have_documented_shape(self):
        requirements = QUITAR_PRODUCTO_CONTRACT["requirements"]
        self.assertIn("pedido_producto_id", requirements)
        self.assertIn("cantidad", requirements)
        self.assertEqual(requirements["pedido_producto_id"]["required"], True)
        self.assertIsNone(requirements["pedido_producto_id"]["default"])
        self.assertEqual(requirements["cantidad"]["required"], False)
        self.assertIsNone(requirements["cantidad"]["default"])

    def test_no_forbidden_requirement_names(self):
        requirements = QUITAR_PRODUCTO_CONTRACT["requirements"]
        forbidden = {"precio", "subtotal", "cantidad_actual", "producto_presentacion_id"}
        self.assertFalse(forbidden.intersection(requirements.keys()))


class QuitarProductoContractPublicSurfaceTest(unittest.TestCase):
    def test_module_all_is_limited_to_contract(self):
        importlib.reload(contract_module)
        self.assertEqual(contract_module.__all__, ["QUITAR_PRODUCTO_CONTRACT"])


if __name__ == "__main__":
    unittest.main()