"""Pre-migration characterization tests for hardcoded product aliases.

Records the current fuzzy-recognition behavior of every active entry in
``ALIASES_PALABRAS`` (the spelling/abbreviation substitution map at
``backend/recognizers/product_recognizer.py``) so Subphase 4.2 can confirm
that moving these aliases to PostgreSQL preserves observable behavior.

These tests run against the existing in-process recognizer with handcrafted
catalogs. They are not affected by the persistence migration and must
continue to pass before and after the seeder runs.
"""
from __future__ import annotations

import unittest

from backend.recognizers.product_recognizer import (
    ALIASES_PALABRAS,
    detectar_productos,
)

ProductRecognizerResult = dict


MOZZARELLA_ALIASES: tuple[str, ...] = (
    "muza",
    "muzza",
    "muzarela",
    "muzarella",
    "mozarela",
    "mozarella",
    "muzzarela",
    "muzzarella",
    "musarela",
    "musarella",
)
FUGAZZETA_ALIASES: tuple[str, ...] = ("fugazeta", "fugazetta")
NAPOLITANA_ALIASES: tuple[str, ...] = ("napoli",)
CALABRESA_ALIASES: tuple[str, ...] = ("calabreza",)


MOZZARELLA_CATALOG: list[dict] = [
    {
        "producto_presentacion_id": 1,
        "producto_id": 10,
        "presentacion_id": 100,
        "categoria_id": 1,
        "producto_nombre": "Pizza de Muzzarella",
        "categoria_nombre": "Pizzas",
        "presentacion_codigo": "unidad",
        "presentacion_descripcion": "Unidad",
        "activo": True,
        "disponible": True,
        "aliases": {
            "general_aliases": ["mozzarella"],
            "specific_aliases": [],
        },
    },
    {
        "producto_presentacion_id": 2,
        "producto_id": 10,
        "presentacion_id": 101,
        "categoria_id": 1,
        "producto_nombre": "Pizza de Muzzarella",
        "categoria_nombre": "Pizzas",
        "presentacion_codigo": "grande",
        "presentacion_descripcion": "Pizza grande de muzzarella",
        "activo": True,
        "disponible": True,
        "aliases": {
            "general_aliases": ["mozzarella"],
            "specific_aliases": [],
        },
    },
]


MOZZARELLA_UNIQUE_CATALOG: list[dict] = [
    {
        "producto_presentacion_id": 1,
        "producto_id": 10,
        "presentacion_id": 100,
        "categoria_id": 1,
        "producto_nombre": "Pizza de Muzzarella",
        "categoria_nombre": "Pizzas",
        "presentacion_codigo": "unidad",
        "presentacion_descripcion": "Unidad",
        "activo": True,
        "disponible": True,
        "aliases": {
            "general_aliases": ["mozzarella"],
            "specific_aliases": [],
        },
    }
]


MOZZARELLA_DUAL_PRESENTATION_CATALOG: list[dict] = [
    {
        "producto_presentacion_id": 1,
        "producto_id": 10,
        "presentacion_id": 100,
        "categoria_id": 1,
        "producto_nombre": "Pizza de Muzzarella",
        "categoria_nombre": "Pizzas",
        "presentacion_codigo": "chica",
        "presentacion_descripcion": "Chica",
        "activo": True,
        "disponible": True,
        "aliases": {
            "general_aliases": ["mozzarella"],
            "specific_aliases": [],
        },
    },
    {
        "producto_presentacion_id": 2,
        "producto_id": 10,
        "presentacion_id": 101,
        "categoria_id": 1,
        "producto_nombre": "Pizza de Muzzarella",
        "categoria_nombre": "Pizzas",
        "presentacion_codigo": "grande",
        "presentacion_descripcion": "Grande",
        "activo": True,
        "disponible": True,
        "aliases": {
            "general_aliases": ["mozzarella"],
            "specific_aliases": [],
        },
    },
]


FUGAZZETA_CATALOG: list[dict] = [
    {
        "producto_presentacion_id": 3,
        "producto_id": 20,
        "presentacion_id": 200,
        "categoria_id": 1,
        "producto_nombre": "Pizza Fugazzeta",
        "categoria_nombre": "Pizzas",
        "presentacion_codigo": "unidad",
        "presentacion_descripcion": "Unidad",
        "activo": True,
        "disponible": True,
        "aliases": {
            "general_aliases": ["fugazzeta"],
            "specific_aliases": [],
        },
    },
]


NAPOLITANA_CATALOG: list[dict] = [
    {
        "producto_presentacion_id": 4,
        "producto_id": 30,
        "presentacion_id": 300,
        "categoria_id": 1,
        "producto_nombre": "Pizza Napolitana",
        "categoria_nombre": "Pizzas",
        "presentacion_codigo": "unidad",
        "presentacion_descripcion": "Unidad",
        "activo": True,
        "disponible": True,
        "aliases": {
            "general_aliases": ["napolitana"],
            "specific_aliases": [],
        },
    },
]


CALABRESA_CATALOG: list[dict] = [
    {
        "producto_presentacion_id": 5,
        "producto_id": 40,
        "presentacion_id": 400,
        "categoria_id": 1,
        "producto_nombre": "Pizza Calabresa",
        "categoria_nombre": "Pizzas",
        "presentacion_codigo": "unidad",
        "presentacion_descripcion": "Unidad",
        "activo": True,
        "disponible": True,
        "aliases": {
            "general_aliases": ["calabresa"],
            "specific_aliases": [],
        },
    },
]


def _ids(result: ProductRecognizerResult) -> list[int]:
    found = [entry["producto_presentacion_id"] for entry in result["encontrados"]]
    possible = [
        entry["producto_presentacion_id"]
        for group in result["encontrados_posibles"]
        for entry in group["productos"]
    ]
    return found + possible


def _assert_unique_match(
    testcase: unittest.TestCase,
    text: str,
    catalog: list[dict],
    expected_id: int,
    expected_quantity: int,
) -> None:
    result = detectar_productos(text, catalog)
    ids = _ids(result)
    testcase.assertEqual(
        ids,
        [expected_id],
        f"text={text!r} expected unique id {expected_id}, got {ids}",
    )
    product: dict | None = result["encontrados"][0] if result["encontrados"] else None
    if product is None:
        for group in result["encontrados_posibles"]:
            for candidate in group["productos"]:
                if candidate["producto_presentacion_id"] == expected_id:
                    product = candidate
                    break
    testcase.assertIsNotNone(product)
    assert product is not None
    testcase.assertEqual(product["cantidad"], expected_quantity)


class AliasesInventoryTest(unittest.TestCase):
    def test_every_active_alias_entry_is_product_wide(self):
        expected = {
            *MOZZARELLA_ALIASES,
            *FUGAZZETA_ALIASES,
            *NAPOLITANA_ALIASES,
            *CALABRESA_ALIASES,
        }
        self.assertEqual(set(ALIASES_PALABRAS), expected)
        for raw, canonical in ALIASES_PALABRAS.items():
            with self.subTest(alias=raw):
                self.assertNotIn(" ", raw)
                self.assertNotIn(" ", canonical)
                self.assertIn(canonical, {"mozzarella", "fugazzeta", "napolitana", "calabresa"})


class MozzarellaAliasCharacterizationTest(unittest.TestCase):
    def test_each_mozzarella_alias_unique_against_canonical_muzzarella(self):
        for alias in MOZZARELLA_ALIASES:
            with self.subTest(alias=alias):
                _assert_unique_match(
                    self,
                    f"pizza {alias}",
                    MOZZARELLA_UNIQUE_CATALOG,
                    expected_id=1,
                    expected_quantity=1,
                )

    def test_quantity_word_preserved_with_alias(self):
        for alias in MOZZARELLA_ALIASES:
            with self.subTest(alias=alias):
                _assert_unique_match(
                    self,
                    f"dos pizza {alias}",
                    MOZZARELLA_UNIQUE_CATALOG,
                    expected_id=1,
                    expected_quantity=2,
                )

    def test_alias_with_unknown_phrase_returns_match(self):
        for alias in MOZZARELLA_ALIASES:
            with self.subTest(alias=alias):
                result = detectar_productos(
                    f"quiero una {alias} por favor", MOZZARELLA_UNIQUE_CATALOG
                )
                ids = _ids(result)
                self.assertIn(1, ids)

    def test_dual_presentation_filtered_by_codigo(self):
        for alias in MOZZARELLA_ALIASES:
            with self.subTest(alias=alias):
                _assert_unique_match(
                    self,
                    f"pizza {alias} grande",
                    MOZZARELLA_DUAL_PRESENTATION_CATALOG,
                    expected_id=2,
                    expected_quantity=1,
                )


class FugazzetaAliasCharacterizationTest(unittest.TestCase):
    def test_each_fugazzeta_alias_unique(self):
        for alias in FUGAZZETA_ALIASES:
            with self.subTest(alias=alias):
                _assert_unique_match(
                    self,
                    f"pizza {alias}",
                    FUGAZZETA_CATALOG,
                    expected_id=3,
                    expected_quantity=1,
                )


class NapolitanaAliasCharacterizationTest(unittest.TestCase):
    def test_napoli_alias_unique(self):
        for alias in NAPOLITANA_ALIASES:
            with self.subTest(alias=alias):
                _assert_unique_match(
                    self,
                    f"pizza {alias}",
                    NAPOLITANA_CATALOG,
                    expected_id=4,
                    expected_quantity=1,
                )


class CalabresaAliasCharacterizationTest(unittest.TestCase):
    def test_calabreza_alias_unique(self):
        for alias in CALABRESA_ALIASES:
            with self.subTest(alias=alias):
                _assert_unique_match(
                    self,
                    f"pizza {alias}",
                    CALABRESA_CATALOG,
                    expected_id=5,
                    expected_quantity=1,
                )


class PresentationValuesNotInAliasMapTest(unittest.TestCase):
    def test_structured_presentation_values_are_not_in_product_alias_map(self):
        from backend.recognizers.product_recognizer import PRESENTACION_ALIASES

        presentation_values = set(PRESENTACION_ALIASES.values())
        product_aliases = set(ALIASES_PALABRAS)
        self.assertTrue(
            product_aliases.isdisjoint(presentation_values),
            f"product aliases intersect presentation values: "
            f"{product_aliases & presentation_values}",
        )

    def test_structured_presentation_values_resolve_through_codigo(self):
        catalog: list[dict] = [
            {
                "producto_presentacion_id": 1,
                "producto_id": 1,
                "presentacion_id": 1,
                "categoria_id": 1,
                "producto_nombre": "Pizza de Muzzarella",
                "categoria_nombre": "Pizzas",
                "presentacion_codigo": "chica",
                "presentacion_descripcion": "Chica",
                "activo": True,
                "disponible": True,
            },
            {
                "producto_presentacion_id": 2,
                "producto_id": 1,
                "presentacion_id": 2,
                "categoria_id": 1,
                "producto_nombre": "Pizza de Muzzarella",
                "categoria_nombre": "Pizzas",
                "presentacion_codigo": "grande",
                "presentacion_descripcion": "Grande",
                "activo": True,
                "disponible": True,
            },
        ]
        for token, expected_id in (("chica", 1), ("grande", 2)):
            with self.subTest(token=token):
                result = detectar_productos(
                    f"pizza muzza {token}", catalog
                )
                ids = _ids(result)
                self.assertEqual(
                    ids,
                    [expected_id],
                    f"token {token!r} should resolve to id {expected_id}, got {ids}",
                )


class SharedAmbiguousAliasTest(unittest.TestCase):
    def test_shared_alias_preserves_ambiguity_across_presentations(self):
        for alias in MOZZARELLA_ALIASES:
            with self.subTest(alias=alias):
                result = detectar_productos(
                    f"quiero una pizza {alias}", MOZZARELLA_DUAL_PRESENTATION_CATALOG
                )
                self.assertEqual(result["encontrados"], [])
                self.assertEqual(len(result["encontrados_posibles"]), 1)
                possible_ids = [
                    entry["producto_presentacion_id"]
                    for group in result["encontrados_posibles"]
                    for entry in group["productos"]
                ]
                self.assertEqual(sorted(possible_ids), [1, 2])


__all__ = [
    "ALIASES_PALABRAS",
    "CALABRESA_ALIASES",
    "CALABRESA_CATALOG",
    "FUGAZZETA_ALIASES",
    "FUGAZZETA_CATALOG",
    "MOZZARELLA_ALIASES",
    "MOZZARELLA_CATALOG",
    "MOZZARELLA_DUAL_PRESENTATION_CATALOG",
    "MOZZARELLA_UNIQUE_CATALOG",
    "NAPOLITANA_ALIASES",
    "NAPOLITANA_CATALOG",
]


if __name__ == "__main__":
    unittest.main()
