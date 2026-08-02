import importlib
import unittest

from backend.intents.contracts import modificar_producto as contract_module
from backend.intents.contracts.modificar_producto import MODIFICAR_PRODUCTO_CONTRACT
from backend.intents.contracts.registry import CONTRACT_REGISTRY


class ModificarProductoContractShapeTest(unittest.TestCase):
    def test_contract_is_a_dict(self):
        self.assertIsInstance(MODIFICAR_PRODUCTO_CONTRACT, dict)

    def test_top_level_keys_are_exactly_documented(self):
        self.assertEqual(
            set(MODIFICAR_PRODUCTO_CONTRACT.keys()),
            {"intent", "recognizer", "handler", "requirements"},
        )

    def test_top_level_field_values(self):
        self.assertEqual(MODIFICAR_PRODUCTO_CONTRACT["intent"], "modificar_producto")
        self.assertEqual(
            MODIFICAR_PRODUCTO_CONTRACT["recognizer"],
            "modificar_producto_recognizer",
        )
        self.assertEqual(
            MODIFICAR_PRODUCTO_CONTRACT["handler"], "modificar_producto"
        )

    def test_requirements_have_documented_shape(self):
        requirements = MODIFICAR_PRODUCTO_CONTRACT["requirements"]
        self.assertIn("pedido_producto_origen_id", requirements)
        self.assertIn("producto_presentacion_destino_id", requirements)
        self.assertIn("cantidad", requirements)
        self.assertEqual(requirements["pedido_producto_origen_id"]["required"], True)
        self.assertIsNone(requirements["pedido_producto_origen_id"]["default"])
        self.assertEqual(
            requirements["producto_presentacion_destino_id"]["required"], True
        )
        self.assertIsNone(
            requirements["producto_presentacion_destino_id"]["default"]
        )
        self.assertEqual(requirements["cantidad"]["required"], False)
        self.assertIsNone(requirements["cantidad"]["default"])

    def test_no_forbidden_requirement_names(self):
        requirements = MODIFICAR_PRODUCTO_CONTRACT["requirements"]
        forbidden = {
            "precio",
            "subtotal",
            "cantidad_actual",
            "id",
            "pedido_id",
            "id_pedido",
            "producto_presentacion_id",
        }
        self.assertFalse(forbidden.intersection(requirements.keys()))


class ModificarProductoContractRegistryTest(unittest.TestCase):
    def test_registry_lists_modificar_producto(self):
        self.assertIn("modificar_producto", CONTRACT_REGISTRY)
        self.assertEqual(
            CONTRACT_REGISTRY["modificar_producto"]["intent"],
            "modificar_producto",
        )

    def test_registry_includes_agregar_and_quitar(self):
        self.assertIn("agregar_producto", CONTRACT_REGISTRY)
        self.assertIn("quitar_producto", CONTRACT_REGISTRY)


class ModificarProductoContractPublicSurfaceTest(unittest.TestCase):
    def test_module_all_is_limited_to_contract(self):
        importlib.reload(contract_module)
        self.assertEqual(
            contract_module.__all__, ["MODIFICAR_PRODUCTO_CONTRACT"]
        )


if __name__ == "__main__":
    unittest.main()
