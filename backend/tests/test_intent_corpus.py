import unittest

from backend.diagnostics import (
    CONTROLLED_INTENT_CORPUS,
    CORPUS_VERSION,
    PROMPT_TEMPLATE_VERSION,
    iter_fixtures,
    unique_intents_covered,
)
from backend.intents.schemas.intent_classification import IntentName


class ControlledCorpusShapeTest(unittest.TestCase):
    def test_corpus_is_non_empty(self):
        self.assertGreater(len(CONTROLLED_INTENT_CORPUS), 0)

    def test_corpus_version_is_pinned(self):
        self.assertTrue(CORPUS_VERSION.startswith("intent-corpus/"))

    def test_every_intent_name_has_at_least_one_canonical_fixture(self):
        seen = set(unique_intents_covered())
        for intent in IntentName:
            with self.subTest(intent=intent):
                self.assertIn(intent, seen)

    def test_payment_regression_fixture_pins_single_intent(self):
        regression = next(
            fixture
            for fixture in CONTROLLED_INTENT_CORPUS
            if fixture.fixture_id == "F-REG-PAGO-EFECTIVO"
        )
        self.assertEqual(
            regression.expected_intents,
            (IntentName.SET_METODO_DE_PAGO,),
        )
        self.assertIn("Pago en Efectivo (prueba cierre)", regression.message)

    def test_product_observation_fixture_pins_single_intent(self):
        regression = next(
            fixture
            for fixture in CONTROLLED_INTENT_CORPUS
            if fixture.fixture_id == "F-SET_OBSERVACION_PRODUCTO"
        )
        self.assertEqual(
            regression.expected_intents,
            (IntentName.SET_OBSERVACION_PRODUCTO,),
        )

    def test_order_observation_fixture_pins_single_intent(self):
        regression = next(
            fixture
            for fixture in CONTROLLED_INTENT_CORPUS
            if fixture.fixture_id == "F-SET_OBSERVACION_PEDIDO"
        )
        self.assertEqual(
            regression.expected_intents,
            (IntentName.SET_OBSERVACION_PEDIDO,),
        )

    def test_boundary_porton_lateral_fixture_pins_single_observacion_pedido(self):
        fixture = next(
            f for f in CONTROLLED_INTENT_CORPUS
            if f.fixture_id == "F-REG-OBSERVACION_PEDIDO-PORTON_LATERAL"
        )
        self.assertEqual(
            fixture.expected_intents,
            (IntentName.SET_OBSERVACION_PEDIDO,),
        )
        self.assertEqual(fixture.message, "La entrega es por el portón lateral")

    def test_boundary_mascotas_fixture_pins_single_observacion_pedido(self):
        fixture = next(
            f for f in CONTROLLED_INTENT_CORPUS
            if f.fixture_id == "F-REG-OBSERVACION_PEDIDO-MASCOTAS"
        )
        self.assertEqual(
            fixture.expected_intents,
            (IntentName.SET_OBSERVACION_PEDIDO,),
        )
        self.assertEqual(fixture.message, "Cuidado con el perro")

    def test_boundary_envio_domicilio_fixture_pins_single_metodo_de_entrega(self):
        fixture = next(
            f for f in CONTROLLED_INTENT_CORPUS
            if f.fixture_id == "F-REG-METODO_DE_ENTREGA-ENVIO_DOMICILIO"
        )
        self.assertEqual(
            fixture.expected_intents,
            (IntentName.SET_METODO_DE_ENTREGA,),
        )
        self.assertEqual(fixture.message, "Quiero envío a domicilio")

    def test_boundary_retiro_local_fixture_pins_single_metodo_de_entrega(self):
        fixture = next(
            f for f in CONTROLLED_INTENT_CORPUS
            if f.fixture_id == "F-REG-METODO_DE_ENTREGA-RETIRO_LOCAL"
        )
        self.assertEqual(
            fixture.expected_intents,
            (IntentName.SET_METODO_DE_ENTREGA,),
        )
        self.assertEqual(fixture.message, "Lo retiro por el local")

    def test_category_pizzas_fixture_pins_single_ver_menu_intent(self):
        fixture = next(
            f for f in CONTROLLED_INTENT_CORPUS
            if f.fixture_id == "F-VER_MENU-CATEGORIA_PIZZAS"
        )
        self.assertEqual(fixture.expected_intents, (IntentName.VER_MENU,))
        self.assertEqual(fixture.message, "qué pizzas hay")
        self.assertNotIn(IntentName.CONSULTAR_PRODUCTO, fixture.expected_intents)

    def test_category_empanadas_fixture_pins_single_ver_menu_intent(self):
        fixture = next(
            f for f in CONTROLLED_INTENT_CORPUS
            if f.fixture_id == "F-VER_MENU-CATEGORIA_EMPANADAS"
        )
        self.assertEqual(fixture.expected_intents, (IntentName.VER_MENU,))
        self.assertEqual(fixture.message, "qué gustos de empanadas tenés")
        self.assertNotIn(IntentName.CONSULTAR_PRODUCTO, fixture.expected_intents)

    def test_category_bebidas_fixture_pins_single_ver_menu_intent(self):
        fixture = next(
            f for f in CONTROLLED_INTENT_CORPUS
            if f.fixture_id == "F-VER_MENU-CATEGORIA_BEBIDAS"
        )
        self.assertEqual(fixture.expected_intents, (IntentName.VER_MENU,))
        self.assertEqual(fixture.message, "qué bebidas están disponibles")
        self.assertNotIn(IntentName.CONSULTAR_PRODUCTO, fixture.expected_intents)

    def test_concrete_product_detail_fixture_remains_consultar_producto(self):
        fixture = next(
            f for f in CONTROLLED_INTENT_CORPUS
            if f.fixture_id == "F-CONSULTAR_PRODUCTO-PRECIO_NAPOLITANA"
        )
        self.assertEqual(
            fixture.expected_intents, (IntentName.CONSULTAR_PRODUCTO,)
        )
        self.assertEqual(fixture.message, "cuánto sale la napolitana grande")
        self.assertNotIn(IntentName.VER_MENU, fixture.expected_intents)

    def test_corpus_version_bumped_for_category_browse_fixtures(self):
        self.assertTrue(CORPUS_VERSION.startswith("intent-corpus/v"))
        self.assertGreaterEqual(CORPUS_VERSION, "intent-corpus/v1.6.0")

    def test_direccion_entrega_tilcara_fixture_pins_single_set_direccion_entrega(self):
        fixture = next(
            f for f in CONTROLLED_INTENT_CORPUS
            if f.fixture_id == "F-REG-DIRECCION_ENTREGA-TILCARA_2020"
        )
        self.assertEqual(
            fixture.expected_intents,
            (IntentName.SET_DIRECCION_ENTREGA,),
        )
        self.assertEqual(fixture.message, "Me lo envias a Tilcara 2020")
        self.assertNotIn(
            IntentName.SET_OBSERVACION_PEDIDO,
            fixture.expected_intents,
        )
        self.assertNotIn(
            IntentName.SET_METODO_DE_ENTREGA,
            fixture.expected_intents,
        )

    def test_fixture_ids_are_unique(self):
        ids = [fixture.fixture_id for fixture in CONTROLLED_INTENT_CORPUS]
        self.assertEqual(len(ids), len(set(ids)))

    def test_messages_are_non_empty_strings(self):
        for fixture in iter_fixtures():
            with self.subTest(fixture_id=fixture.fixture_id):
                self.assertIsInstance(fixture.message, str)
                self.assertTrue(fixture.message.strip())


class ControlledCorpusPromptFingerprintTest(unittest.TestCase):
    def test_every_fixture_message_is_present_in_its_rendered_prompt(self):
        from backend.llm.intent_classifier import IntentClassifier

        classifier = IntentClassifier()
        for fixture in CONTROLLED_INTENT_CORPUS:
            with self.subTest(fixture_id=fixture.fixture_id):
                prompt = classifier._build_prompt(fixture.message)
                self.assertIn(fixture.message, prompt)


class PromptTemplateVersionTest(unittest.TestCase):
    def test_version_is_a_versioned_string(self):
        self.assertTrue(PROMPT_TEMPLATE_VERSION.startswith("intent-classifier/"))


if __name__ == "__main__":
    unittest.main()
