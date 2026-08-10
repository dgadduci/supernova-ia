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
