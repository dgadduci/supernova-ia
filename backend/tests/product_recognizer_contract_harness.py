import unittest
from typing import cast

from backend.recognizers.product_recognizer_contract import ProductRecognizerProtocol

RESULT_KEYS = [
    "encontrados",
    "encontrados_posibles",
    "encontrados_no_disponibles",
    "no_encontrados",
]


def assert_product_recognizer_contract(
    testcase: unittest.TestCase,
    recognizer: ProductRecognizerProtocol,
) -> None:
    exact_catalog = [
        {
            "producto_presentacion_id": 1,
            "producto_id": 10,
            "presentacion_id": 100,
            "categoria_id": 1000,
            "producto_nombre": "Empanada de Pollo",
            "categoria_nombre": "Empanadas",
            "presentacion_codigo": "UNIDAD",
            "presentacion_descripcion": "Unidad",
            "producto_activo": True,
            "presentacion_activo": True,
            "activo": True,
            "disponible": True,
            "fixture_marker": "preserved",
        }
    ]
    exact = recognizer.recognize("empanada de pollo", exact_catalog)
    testcase.assertIs(type(exact), dict)
    testcase.assertEqual(list(exact), RESULT_KEYS)
    testcase.assertTrue(
        all(type(cast(dict, exact)[key]) is list for key in RESULT_KEYS)
    )
    testcase.assertEqual(len(exact["encontrados"]), 1)
    found = exact["encontrados"][0]
    testcase.assertEqual(found["producto_presentacion_id"], 1)
    testcase.assertEqual(found["cantidad"], 1)
    testcase.assertEqual(found["texto_origen"], "empanada de pollo")
    testcase.assertEqual(cast(dict, found)["fixture_marker"], "preserved")
    testcase.assertTrue(set(exact_catalog[0]).issubset(found))

    quantity = recognizer.recognize("tres empanadas de pollo", exact_catalog)
    testcase.assertEqual(quantity["encontrados"][0]["cantidad"], 3)

    ambiguous_catalog = [
        {
            "producto_presentacion_id": 1,
            "producto_nombre": "Pizza Mozzarella con Albahaca",
            "presentacion_codigo": "CHICA",
        },
        {
            "producto_presentacion_id": 2,
            "producto_nombre": "Pizza Mozzarella con Albahaca",
            "presentacion_codigo": "GRANDE",
        },
        {
            "producto_presentacion_id": 21,
            "producto_nombre": "Pizza Mozzarella con Albahaca",
            "presentacion_codigo": "FAMILIAR",
        },
    ]
    ambiguous = recognizer.recognize("quiero una pizza", ambiguous_catalog)
    testcase.assertEqual(len(ambiguous["encontrados_posibles"]), 1)
    group = ambiguous["encontrados_posibles"][0]
    testcase.assertEqual(list(group), ["texto_origen", "productos"])
    testcase.assertEqual(group["texto_origen"], "quiero una pizza")
    testcase.assertEqual(
        [entry["producto_presentacion_id"] for entry in group["productos"]],
        [1, 2, 21],
    )

    unavailable_catalog = [
        {
            "producto_presentacion_id": 50,
            "producto_nombre": "Coca Cola",
            "presentacion_codigo": "LATA",
            "producto_activo": True,
            "presentacion_activo": True,
            "activo": True,
            "disponible": False,
        },
        {
            "producto_presentacion_id": 51,
            "producto_nombre": "Coca Cola",
            "presentacion_codigo": "LATA",
            "producto_activo": False,
            "presentacion_activo": True,
            "activo": True,
            "disponible": True,
        },
    ]
    unavailable = recognizer.recognize("coca lata", unavailable_catalog)
    testcase.assertEqual(unavailable["encontrados"], [])
    testcase.assertEqual(
        [entry["producto_presentacion_id"] for entry in unavailable["encontrados_no_disponibles"]],
        [50],
    )

    duplicate_catalog = [
        {
            "producto_presentacion_id": 70,
            "producto_nombre": "Pizza Mozzarella",
            "presentacion_codigo": "UNIDAD",
            "source": "weaker",
        },
        {
            "producto_presentacion_id": 70,
            "producto_nombre": "Pizza Napolitana",
            "presentacion_codigo": "UNIDAD",
            "source": "stronger",
        },
    ]
    duplicate = recognizer.recognize("pizza napolitana", duplicate_catalog)
    testcase.assertEqual(len(duplicate["encontrados"]), 1)
    testcase.assertEqual(cast(dict, duplicate["encontrados"][0])["source"], "stronger")

    unknown = recognizer.recognize("caramelo mas alfajor", exact_catalog)
    testcase.assertEqual(
        unknown["no_encontrados"],
        [{"texto_origen": "caramelo"}, {"texto_origen": "alfajor"}],
    )

    empty = recognizer.recognize("", [])
    testcase.assertEqual(list(empty), RESULT_KEYS)
    testcase.assertEqual(empty["encontrados"], [])
    testcase.assertEqual(empty["encontrados_posibles"], [])
    testcase.assertEqual(empty["encontrados_no_disponibles"], [])
    testcase.assertEqual(empty["no_encontrados"], [{"texto_origen": ""}])


__all__ = ["RESULT_KEYS", "assert_product_recognizer_contract"]
