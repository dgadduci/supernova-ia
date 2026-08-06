import unittest

from backend.recognizers.product_recognizer import (
    PRESENTACION_ALIASES,
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


if __name__ == "__main__":
    unittest.main()
