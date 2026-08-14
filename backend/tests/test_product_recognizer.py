import unittest

from backend.recognizers.product_recognizer import (
    PRESENTACION_ALIASES,
    PRESENTACION_PLURAL_NORMALIZATION,
    STOPWORDS,
    detectar_productos,
)

EMPANADA_CATALOG = [
    {
        "producto_presentacion_id": 1,
        "producto_id": 1,
        "presentacion_id": 1,
        "categoria_id": 1,
        "categoria_nombre": "Empanadas",
        "producto_nombre": "Empanada de Pollo",
        "presentacion_codigo": "unidad",
        "presentacion_descripcion": "Unidad",
        "activo": True,
        "disponible": True,
    }
]


PIZZA_CATALOG = [
    {
        "producto_presentacion_id": 2,
        "producto_id": 2,
        "presentacion_id": 2,
        "categoria_id": 2,
        "categoria_nombre": "Pizzas",
        "producto_nombre": "Pizza Mozzarella",
        "presentacion_codigo": "grande",
        "presentacion_descripcion": "Pizza grande de mozzarella",
        "activo": True,
        "disponible": True,
    }
]


CATEGORIA_PREFIJO_CATALOG = [
    {
        "producto_presentacion_id": 100,
        "producto_id": 10,
        "presentacion_id": 1,
        "categoria_id": 1,
        "categoria_nombre": "Pizzas",
        "producto_nombre": "Napolitana",
        "presentacion_codigo": "grande",
        "presentacion_descripcion": "Pizza grande napolitana",
        "activo": True,
        "disponible": True,
    },
    {
        "producto_presentacion_id": 101,
        "producto_id": 10,
        "presentacion_id": 2,
        "categoria_id": 1,
        "categoria_nombre": "Pizzas",
        "producto_nombre": "Napolitana",
        "presentacion_codigo": "chica",
        "presentacion_descripcion": "Pizza chica napolitana",
        "activo": True,
        "disponible": True,
    },
    {
        "producto_presentacion_id": 102,
        "producto_id": 11,
        "presentacion_id": 3,
        "categoria_id": 1,
        "categoria_nombre": "Pizzas",
        "producto_nombre": "Mozzarella",
        "presentacion_codigo": "unidad",
        "presentacion_descripcion": "Pizza mozzarella",
        "activo": True,
        "disponible": True,
    },
    {
        "producto_presentacion_id": 200,
        "producto_id": 20,
        "presentacion_id": 4,
        "categoria_id": 2,
        "categoria_nombre": "Empanadas",
        "producto_nombre": "Napolitana",
        "presentacion_codigo": "unidad",
        "presentacion_descripcion": "Empanada napolitana",
        "activo": True,
        "disponible": True,
    },
]


CATEGORIA_PREFIJO_PRODUCTO_NOMBRE_PREFIX = [
    {
        "producto_presentacion_id": 400,
        "producto_id": 40,
        "presentacion_id": 6,
        "categoria_id": 1,
        "categoria_nombre": "Pizzas",
        "producto_nombre": "Pizza Mozzarella",
        "presentacion_codigo": "unidad",
        "presentacion_descripcion": "Pizza mozzarella",
        "activo": True,
        "disponible": True,
    }
]


class DetectarProductosStopwordsTest(unittest.TestCase):
    def test_quita_sin_cantidad_resuelve_candidato(self):
        resultado = detectar_productos("quita las empanadas de pollo", EMPANADA_CATALOG)

        nombres_encontrados = [p["producto_nombre"] for p in resultado["encontrados"]]
        self.assertIn("Empanada de Pollo", nombres_encontrados)
        fragmentos_no_encontrados = [n["texto_origen"] for n in resultado["no_encontrados"]]
        self.assertNotIn("quita las empanadas de pollo", fragmentos_no_encontrados)

    def test_sacala_pronominal_resuelve_candidato(self):
        resultado = detectar_productos(
            "sacala empanadas de pollo", EMPANADA_CATALOG
        )

        nombres_encontrados = [p["producto_nombre"] for p in resultado["encontrados"]]
        self.assertIn("Empanada de Pollo", nombres_encontrados)

    def test_verbo_generico_elimina_resuelve_candidato(self):
        resultado = detectar_productos("elimina la pizza muzza", PIZZA_CATALOG)

        nombres_encontrados = [p["producto_nombre"] for p in resultado["encontrados"]]
        self.assertIn("Pizza Mozzarella", nombres_encontrados)

    def test_agregar_sin_cantidad_resuelve_candidato(self):
        resultado = detectar_productos(
            "agrega empanadas de pollo", EMPANADA_CATALOG
        )

        nombres_encontrados = [p["producto_nombre"] for p in resultado["encontrados"]]
        self.assertIn("Empanada de Pollo", nombres_encontrados)

    def test_stopwords_contiene_verbos_imperativos(self):
        verbos = [
            "quita", "quitar", "saca", "sacame", "sacala", "quitala",
            "quitalas", "quitale", "sacasela", "elimina", "eliminar",
            "remueve", "remover", "borra", "borrar", "suprime", "suprimir",
            "agrega", "agregar",
        ]
        for verbo in verbos:
            with self.subTest(verbo=verbo):
                self.assertIn(verbo, STOPWORDS)


class DetectarProductosPresentacionTest(unittest.TestCase):
    def test_picante_no_esta_en_presentacion_aliases(self):
        self.assertNotIn("picante", PRESENTACION_ALIASES)

    def test_descriptor_picante_no_filtra_candidato_unidad(self):
        catalog = [
            {
                "producto_presentacion_id": 10,
                "producto_id": 10,
                "presentacion_id": 10,
                "categoria_id": 1,
                "categoria_nombre": "Empanadas",
                "producto_nombre": "Empanada de Carne Picante",
                "presentacion_codigo": "unidad",
                "presentacion_descripcion": "Unidad",
                "activo": True,
                "disponible": True,
            },
            {
                "producto_presentacion_id": 11,
                "producto_id": 11,
                "presentacion_id": 11,
                "categoria_id": 1,
                "categoria_nombre": "Empanadas",
                "producto_nombre": "Empanada de Pollo",
                "presentacion_codigo": "unidad",
                "presentacion_descripcion": "Unidad",
                "activo": True,
                "disponible": True,
            },
        ]
        resultado = detectar_productos("empanadas carne picante", catalog)

        ids_encontrados = [p["producto_presentacion_id"] for p in resultado["encontrados"]]
        self.assertIn(10, ids_encontrados)
        nombres_encontrados = [p["producto_nombre"] for p in resultado["encontrados"]]
        self.assertIn("Empanada de Carne Picante", nombres_encontrados)
        self.assertNotIn(
            "empanadas carne picante",
            [n["texto_origen"] for n in resultado["no_encontrados"]],
        )

    def test_termino_legitimo_grande_filtra_candidato_correcto(self):
        catalog = [
            {
                "producto_presentacion_id": 20,
                "producto_id": 20,
                "presentacion_id": 20,
                "categoria_id": 2,
                "categoria_nombre": "Pizzas",
                "producto_nombre": "Pizza Mozzarella",
                "presentacion_codigo": "grande",
                "presentacion_descripcion": "Pizza grande de mozzarella",
                "activo": True,
                "disponible": True,
            },
            {
                "producto_presentacion_id": 21,
                "producto_id": 20,
                "presentacion_id": 21,
                "categoria_id": 2,
                "categoria_nombre": "Pizzas",
                "producto_nombre": "Pizza Mozzarella",
                "presentacion_codigo": "chica",
                "presentacion_descripcion": "Pizza chica de mozzarella",
                "activo": True,
                "disponible": True,
            },
        ]
        resultado = detectar_productos("pizza mozzarella grande", catalog)

        ids_encontrados = [p["producto_presentacion_id"] for p in resultado["encontrados"]]
        self.assertEqual(ids_encontrados, [20])

    def test_termino_legitimo_chica_filtra_candidato_correcto(self):
        catalog = [
            {
                "producto_presentacion_id": 30,
                "producto_id": 30,
                "presentacion_id": 30,
                "categoria_id": 2,
                "categoria_nombre": "Pizzas",
                "producto_nombre": "Pizza Mozzarella",
                "presentacion_codigo": "grande",
                "presentacion_descripcion": "Pizza grande de mozzarella",
                "activo": True,
                "disponible": True,
            },
            {
                "producto_presentacion_id": 31,
                "producto_id": 30,
                "presentacion_id": 31,
                "categoria_id": 2,
                "categoria_nombre": "Pizzas",
                "producto_nombre": "Pizza Mozzarella",
                "presentacion_codigo": "chica",
                "presentacion_descripcion": "Pizza chica de mozzarella",
                "activo": True,
                "disponible": True,
            },
        ]
        resultado = detectar_productos("pizza mozzarella chica", catalog)

        ids_encontrados = [p["producto_presentacion_id"] for p in resultado["encontrados"]]
        self.assertEqual(ids_encontrados, [31])

    def test_termino_legitimo_lata_filtra_candidato_correcto(self):
        catalog = [
            {
                "producto_presentacion_id": 40,
                "producto_id": 40,
                "presentacion_id": 40,
                "categoria_id": 3,
                "categoria_nombre": "Bebidas",
                "producto_nombre": "Coca Cola",
                "presentacion_codigo": "litro",
                "presentacion_descripcion": "Coca 1 litro",
                "activo": True,
                "disponible": True,
            },
            {
                "producto_presentacion_id": 41,
                "producto_id": 40,
                "presentacion_id": 41,
                "categoria_id": 3,
                "categoria_nombre": "Bebidas",
                "producto_nombre": "Coca Cola",
                "presentacion_codigo": "lata",
                "presentacion_descripcion": "Coca lata",
                "activo": True,
                "disponible": True,
            },
        ]
        resultado = detectar_productos("coca lata", catalog)

        ids_encontrados = [p["producto_presentacion_id"] for p in resultado["encontrados"]]
        self.assertIn(41, ids_encontrados)
        self.assertNotIn(40, ids_encontrados)

    def test_termino_presentacion_desconocido_no_filtra_unidad(self):
        catalog = [
            {
                "producto_presentacion_id": 50,
                "producto_id": 50,
                "presentacion_id": 50,
                "categoria_id": 1,
                "categoria_nombre": "Empanadas",
                "producto_nombre": "Empanada de Pollo",
                "presentacion_codigo": "unidad",
                "presentacion_descripcion": "Unidad",
                "activo": True,
                "disponible": True,
            },
        ]
        resultado = detectar_productos("empanadas de pollo", catalog)

        ids_encontrados = [p["producto_presentacion_id"] for p in resultado["encontrados"]]
        nombres_encontrados = [p["producto_nombre"] for p in resultado["encontrados"]]
        self.assertIn(50, ids_encontrados)
        self.assertIn("Empanada de Pollo", nombres_encontrados)

    def test_presentacion_aliases_incluye_terminos_legitimos(self):
        for term in ("chica", "chico", "chiqui", "pequena", "pequeno",
                     "grande", "gran", "grandi", "unidad", "individual",
                     "lata", "familiar", "fami"):
            with self.subTest(term=term):
                self.assertIn(term, PRESENTACION_ALIASES)


class DetectarProductosCategoriaPrefijoTest(unittest.TestCase):
    def test_categoria_explicita_resuelve_solo_productos_de_la_categoria(self):
        resultado = detectar_productos(
            "3 Pizza napolitana", CATEGORIA_PREFIJO_CATALOG
        )

        ids_encontrados = [
            p["producto_presentacion_id"]
            for p in resultado["encontrados"]
        ]
        ids_posibles = [
            p["producto_presentacion_id"]
            for grupo in resultado["encontrados_posibles"]
            if grupo.get("kind") is None
            for p in grupo.get("productos", [])
        ]
        self.assertEqual(sorted(ids_encontrados + ids_posibles), [100, 101])
        cantidades = [
            p["cantidad"]
            for p in resultado["encontrados"]
        ]
        cantidades += [
            p["cantidad"]
            for grupo in resultado["encontrados_posibles"]
            if grupo.get("kind") is None
            for p in grupo.get("productos", [])
        ]
        self.assertTrue(all(c == 3 for c in cantidades))
        self.assertEqual(resultado["no_encontrados"], [])
        categorias = [
            grupo for grupo in resultado["encontrados_posibles"]
            if grupo.get("kind") == "category"
        ]
        self.assertEqual(categorias, [])

    def test_categoria_sola_sigue_siendo_grupo_category_only(self):
        resultado = detectar_productos(
            "3 pizza", CATEGORIA_PREFIJO_CATALOG
        )

        self.assertEqual(resultado["encontrados"], [])
        ids_producto = [
            grupo["producto_presentacion_id"]
            for grupo in resultado["encontrados_posibles"]
            for p in grupo.get("productos", [])
        ]
        self.assertEqual(ids_producto, [])
        grupos_category = [
            grupo for grupo in resultado["encontrados_posibles"]
            if grupo.get("kind") == "category"
        ]
        self.assertEqual(len(grupos_category), 1)
        self.assertEqual(grupos_category[0]["categoria_nombre"], "Pizzas")
        self.assertEqual(
            [n["texto_origen"] for n in resultado["no_encontrados"]],
            ["3 pizza"],
        )

    def test_categoria_incompatible_no_promueve_candidato(self):
        resultado = detectar_productos(
            "empanada napolitana", CATEGORIA_PREFIJO_CATALOG
        )

        ids_encontrados = [
            p["producto_presentacion_id"] for p in resultado["encontrados"]
        ]
        self.assertEqual(ids_encontrados, [200])
        nombres = [p["producto_nombre"] for p in resultado["encontrados"]]
        self.assertEqual(nombres, ["Napolitana"])
        self.assertEqual(
            [p["categoria_nombre"] for p in resultado["encontrados"]],
            ["Empanadas"],
        )

    def test_nombre_producto_con_prefijo_categoria_conserva_resultado(self):
        resultado = detectar_productos(
            "pizza mozzarella", CATEGORIA_PREFIJO_PRODUCTO_NOMBRE_PREFIX
        )

        ids = [p["producto_presentacion_id"] for p in resultado["encontrados"]]
        self.assertEqual(ids, [400])
        nombres = [p["producto_nombre"] for p in resultado["encontrados"]]
        self.assertEqual(nombres, ["Pizza Mozzarella"])
        self.assertEqual(resultado["no_encontrados"], [])


NAPOLITANA_PIZZA_CATALOG = [
    {
        "producto_presentacion_id": 600,
        "producto_id": 60,
        "presentacion_id": 60,
        "categoria_id": 1,
        "categoria_nombre": "Pizzas",
        "producto_nombre": "Napolitana",
        "presentacion_codigo": "grande",
        "presentacion_descripcion": "Pizza grande napolitana",
        "activo": True,
        "disponible": True,
    },
    {
        "producto_presentacion_id": 601,
        "producto_id": 60,
        "presentacion_id": 61,
        "categoria_id": 1,
        "categoria_nombre": "Pizzas",
        "producto_nombre": "Napolitana",
        "presentacion_codigo": "chica",
        "presentacion_descripcion": "Pizza chica napolitana",
        "activo": True,
        "disponible": True,
    },
]


class DetectarProductosPresentacionPluralTest(unittest.TestCase):
    """Narrowly approved presentation plural normalization.

    ``grandes`` -> ``grande`` and ``chicas`` -> ``chica`` are mapped before
    generic singularization, after quantity words. This keeps both
    presentations recognized as sizes and prevents them from becoming
    unmatched product tokens.
    """

    def test_presentacion_plural_normalization_solo_grandes_y_chicas(self):
        self.assertEqual(
            PRESENTACION_PLURAL_NORMALIZATION,
            {"grandes": "grande", "chicas": "chica"},
        )

    def test_dos_napolitanas_grandes_solo_napolitana_grande_cantidad_dos(self):
        resultado = detectar_productos(
            "quiero dos napolitanas grandes", NAPOLITANA_PIZZA_CATALOG
        )

        ids = [p["producto_presentacion_id"] for p in resultado["encontrados"]]
        self.assertEqual(ids, [600])
        self.assertEqual(resultado["encontrados"][0]["cantidad"], 2)
        self.assertEqual(resultado["no_encontrados"], [])
        ids_posibles = [
            p["producto_presentacion_id"]
            for grupo in resultado["encontrados_posibles"]
            if grupo.get("kind") is None
            for p in grupo.get("productos", [])
        ]
        self.assertEqual(ids_posibles, [])

    def test_dos_napolitanas_chicas_solo_napolitana_chica_cantidad_dos(self):
        resultado = detectar_productos(
            "quiero dos napolitanas chicas", NAPOLITANA_PIZZA_CATALOG
        )

        ids = [p["producto_presentacion_id"] for p in resultado["encontrados"]]
        self.assertEqual(ids, [601])
        self.assertEqual(resultado["encontrados"][0]["cantidad"], 2)
        self.assertEqual(resultado["no_encontrados"], [])
        ids_posibles = [
            p["producto_presentacion_id"]
            for grupo in resultado["encontrados_posibles"]
            if grupo.get("kind") is None
            for p in grupo.get("productos", [])
        ]
        self.assertEqual(ids_posibles, [])

    def test_grande_singular_sigue_reconociendo_solo_napolitana_grande(self):
        resultado = detectar_productos(
            "una napolitana grande", NAPOLITANA_PIZZA_CATALOG
        )

        ids = [p["producto_presentacion_id"] for p in resultado["encontrados"]]
        self.assertEqual(ids, [600])
        self.assertEqual(resultado["encontrados"][0]["cantidad"], 1)

    def test_chica_singular_sigue_reconociendo_solo_napolitana_chica(self):
        resultado = detectar_productos(
            "una napolitana chica", NAPOLITANA_PIZZA_CATALOG
        )

        ids = [p["producto_presentacion_id"] for p in resultado["encontrados"]]
        self.assertEqual(ids, [601])
        self.assertEqual(resultado["encontrados"][0]["cantidad"], 1)

    def test_ausente_sigue_sin_encontrar(self):
        resultado = detectar_productos(
            "quiero dos calzoni grandes", NAPOLITANA_PIZZA_CATALOG
        )

        self.assertEqual(resultado["encontrados"], [])
        self.assertEqual(resultado["no_encontrados"], [{"texto_origen": "quiero dos calzoni grandes"}])

    def test_ambiguedad_pizza_sin_presentacion_se_mantiene(self):
        resultado = detectar_productos(
            "quiero una napolitana", NAPOLITANA_PIZZA_CATALOG
        )

        self.assertEqual(resultado["encontrados"], [])
        ids_posibles = sorted(
            [
                p["producto_presentacion_id"]
                for grupo in resultado["encontrados_posibles"]
                if grupo.get("kind") is None
                for p in grupo.get("productos", [])
            ]
        )
        self.assertEqual(ids_posibles, [600, 601])


class DetectarProductosAgregarSeamQuantityTwoTest(unittest.TestCase):
    """Smallest add-product execution proof: a plural ``Grande`` request
    reaches the existing quantity-two seam without introducing new
    transaction control.

    The recognizer output ``(producto_presentacion_id, cantidad)`` is the
    contract consumed by ``process_agregar_producto`` and
    ``execute_agregar_producto``. The processor and handler tests
    independently prove quantity ``2`` preservation and the
    create/increment outcomes; this test pins the recognizer side so the
    full seam closes without a new path.
    """

    def test_dos_napolitanas_grandes_alimenta_seam_con_pp_id_y_cantidad(self):
        resultado = detectar_productos(
            "quiero dos napolitanas grandes", NAPOLITANA_PIZZA_CATALOG
        )

        self.assertEqual(len(resultado["encontrados"]), 1)
        unico = resultado["encontrados"][0]
        self.assertEqual(unico["producto_presentacion_id"], 600)
        self.assertEqual(unico["cantidad"], 2)
        self.assertEqual(
            unico["presentacion_codigo"], "grande",
        )


if __name__ == "__main__":
    unittest.main()
