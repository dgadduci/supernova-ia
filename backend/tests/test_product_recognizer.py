import unittest

from backend.recognizers.product_recognizer import (
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


if __name__ == "__main__":
    unittest.main()
