import unittest

from backend.recognizers.fuzzy_product_recognizer import FuzzyProductRecognizer
from backend.recognizers.product_recognizer import detectar_productos
from backend.recognizers.product_recognizer_contract import ProductRecognizerProtocol
from backend.tests.product_recognizer_contract_harness import (
    assert_product_recognizer_contract,
)


class ProductRecognizerContractTest(unittest.TestCase):
    def test_fuzzy_recognizer_satisfies_reusable_contract(self):
        recognizer: ProductRecognizerProtocol = FuzzyProductRecognizer()
        assert_product_recognizer_contract(self, recognizer)

    def test_adapter_and_legacy_function_are_equivalent(self):
        catalog = [
            {
                "producto_presentacion_id": 1,
                "producto_nombre": "Pizza Mozzarella",
                "presentacion_codigo": "GRANDE",
                "activo": True,
                "disponible": True,
                "fixture_marker": "preserved",
            },
            {
                "producto_presentacion_id": 2,
                "producto_nombre": "Coca Cola",
                "presentacion_codigo": "LATA",
                "activo": True,
                "disponible": False,
            },
        ]
        recognizer = FuzzyProductRecognizer()
        for text in (
            "dos pizzas muzza grande",
            "una coca lata",
            "caramelo",
            "pizza muzza, coca lata",
        ):
            with self.subTest(text=text):
                self.assertEqual(
                    recognizer.recognize(text, catalog),
                    detectar_productos(text, catalog),
                )


if __name__ == "__main__":
    unittest.main()
