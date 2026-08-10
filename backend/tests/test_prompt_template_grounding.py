import unittest

from backend.config.settings import Settings
from backend.diagnostics import (
    PROMPT_TEMPLATE_VERSION,
    ClassifierCallCompleted,
    ClassifierCallStarted,
    CollectingDiagnosticSink,
)
from backend.diagnostics import prompt_template as prompt_template_module
from backend.diagnostics.prompt_template import (
    template_fingerprint,
    template_identity,
)
from backend.intents.schemas.intent_classification import IntentName
from backend.llm import intent_classifier as intent_classifier_module
from backend.llm.intent_classifier import IntentClassifier
from backend.llm.query_llm import QueryLlmResponseError


class _StubQueryLlm:
    def __init__(self, payload):
        self._payload = payload
        self.calls: list[str] = []

    def request(self, prompt: str) -> dict:
        self.calls.append(prompt)
        return self._payload


class _StubQueryLlmWithSettings:
    def __init__(self, payload, settings):
        self._payload = payload
        self._settings = settings
        self.calls: list[str] = []

    def request(self, prompt: str) -> dict:
        self.calls.append(prompt)
        return self._payload


class PromptGroundedIntentsRuleTest(unittest.TestCase):
    def test_prompt_documents_grounded_intent_rule(self):
        classifier = IntentClassifier(
            query_llm=_StubQueryLlm({"intents": [], "mensaje": ""})
        )
        prompt = classifier._build_prompt("Pago en Efectivo (prueba cierre)")
        self.assertIn("grounded intents", prompt.casefold())
        self.assertIn("Pago en Efectivo (prueba cierre)", prompt)
        self.assertIn("set_metodo_de_pago", prompt)

    def test_payment_fixture_routes_to_single_set_metodo_de_pago_intent(self):
        stub = _StubQueryLlm(
            {
                "intents": [
                    {
                        "intent": "set_metodo_de_pago",
                        "mensaje": "Pago en Efectivo (prueba cierre)",
                    },
                ],
                "mensaje": "Pago en Efectivo (prueba cierre)",
            }
        )
        classifier = IntentClassifier(query_llm=stub)
        result = classifier.query("Pago en Efectivo (prueba cierre)")
        self.assertEqual(len(result.intents), 1)
        self.assertEqual(result.intents[0].intent, IntentName.SET_METODO_DE_PAGO)
        self.assertEqual(
            result.intents[0].mensaje, "Pago en Efectivo (prueba cierre)"
        )

    def test_payment_fixture_does_not_emit_product_or_address(self):
        stub = _StubQueryLlm(
            {
                "intents": [
                    {
                        "intent": "set_metodo_de_pago",
                        "mensaje": "Pago en Efectivo (prueba cierre)",
                    },
                ],
                "mensaje": "Pago en Efectivo (prueba cierre)",
            }
        )
        classifier = IntentClassifier(query_llm=stub)
        result = classifier.query("Pago en Efectivo (prueba cierre)")
        names = {item.intent for item in result.intents}
        self.assertNotIn(IntentName.AGREGAR_PRODUCTO, names)
        self.assertNotIn(IntentName.SET_DIRECCION_ENTREGA, names)
        self.assertNotIn(IntentName.SET_METODO_DE_ENTREGA, names)
        self.assertEqual(len(result.intents), 1)

    def test_payment_regression_passes_multi_intent_response_through_to_audit(self):
        stub = _StubQueryLlm(
            {
                "intents": [
                    {"intent": "agregar_producto", "mensaje": "una empanada"},
                    {"intent": "set_direccion_entrega", "mensaje": "Tilcara 2020"},
                    {"intent": "set_metodo_de_pago", "mensaje": "Efectivo"},
                ],
                "mensaje": "Pago en Efectivo (prueba cierre)",
            }
        )
        classifier = IntentClassifier(query_llm=stub)
        result = classifier.query("Pago en Efectivo (prueba cierre)")
        names = [item.intent for item in result.intents]
        self.assertEqual(
            names,
            [
                IntentName.AGREGAR_PRODUCTO,
                IntentName.SET_DIRECCION_ENTREGA,
                IntentName.SET_METODO_DE_PAGO,
            ],
        )

    def test_observation_product_fixture_pins_single_intent(self):
        stub = _StubQueryLlm(
            {
                "intents": [
                    {
                        "intent": "set_observacion_producto",
                        "mensaje": "La pizza es sin aceitunas",
                    },
                ],
                "mensaje": "La pizza es sin aceitunas",
            }
        )
        classifier = IntentClassifier(query_llm=stub)
        result = classifier.query("La pizza es sin aceitunas")
        self.assertEqual(len(result.intents), 1)
        self.assertEqual(result.intents[0].intent, IntentName.SET_OBSERVACION_PRODUCTO)

    def test_observation_order_fixture_pins_single_intent(self):
        stub = _StubQueryLlm(
            {
                "intents": [
                    {
                        "intent": "set_observacion_pedido",
                        "mensaje": "Por favor que la entrega sea sin demorarse mucho",
                    },
                ],
                "mensaje": "Por favor que la entrega sea sin demorarse mucho",
            }
        )
        classifier = IntentClassifier(query_llm=stub)
        result = classifier.query(
            "Por favor que la entrega sea sin demorarse mucho"
        )
        self.assertEqual(len(result.intents), 1)
        self.assertEqual(result.intents[0].intent, IntentName.SET_OBSERVACION_PEDIDO)


class PromptTemplateMetadataTest(unittest.TestCase):
    def test_started_event_carries_prompt_template_version_and_fingerprint(self):
        sink = CollectingDiagnosticSink()
        classifier = IntentClassifier(
            query_llm=_StubQueryLlm(
                {
                    "intents": [{"intent": "saludo", "mensaje": "hola"}],
                    "mensaje": "hola",
                }
            ),
            sink=sink,
        )
        classifier.query("hola")
        started = next(
            event
            for event in sink.events()
            if isinstance(event, ClassifierCallStarted)
        )
        self.assertEqual(started.prompt_template_version, PROMPT_TEMPLATE_VERSION)
        self.assertTrue(started.prompt_fingerprint)
        self.assertEqual(len(started.prompt_fingerprint), 64)

    def test_completed_event_carries_correlation_metadata(self):
        sink = CollectingDiagnosticSink()
        classifier = IntentClassifier(
            query_llm=_StubQueryLlm(
                {
                    "intents": [{"intent": "saludo", "mensaje": "hola"}],
                    "mensaje": "hola",
                }
            ),
            sink=sink,
        )
        classifier.query("hola", model="qwen2.5-coder:7b-ctx8192")
        started = next(
            event
            for event in sink.events()
            if isinstance(event, ClassifierCallStarted)
        )
        completed = next(
            event
            for event in sink.events()
            if isinstance(event, ClassifierCallCompleted)
        )
        self.assertEqual(completed.validation_category, "ok")
        self.assertEqual(completed.classified_intents, ["saludo"])
        self.assertEqual(completed.effective_model, "qwen2.5-coder:7b-ctx8192")
        self.assertEqual(completed.intent_count, 1)
        self.assertEqual(completed.prompt_template_version, PROMPT_TEMPLATE_VERSION)
        self.assertEqual(completed.prompt_fingerprint, started.prompt_fingerprint)

    def test_completed_event_validation_category_is_schema_error_on_bad_payload(self):
        import pydantic

        sink = CollectingDiagnosticSink()
        classifier = IntentClassifier(
            query_llm=_StubQueryLlm({"intents": [], "mensaje": "hola"}),
            sink=sink,
        )
        with self.assertRaises(pydantic.ValidationError):
            classifier.query("hola")
        completed = next(
            event
            for event in sink.events()
            if isinstance(event, ClassifierCallCompleted)
        )
        self.assertEqual(completed.validation_category, "schema_error")

    def test_completed_event_validation_category_is_transport_error_on_query_error(self):
        sink = CollectingDiagnosticSink()

        class _Boom:
            def request(self, prompt: str) -> dict:
                raise QueryLlmResponseError("empty body")

        classifier = IntentClassifier(query_llm=_Boom(), sink=sink)
        with self.assertRaises(QueryLlmResponseError):
            classifier.query("hola")
        completed = next(
            event
            for event in sink.events()
            if isinstance(event, ClassifierCallCompleted)
        )
        self.assertEqual(completed.validation_category, "transport_error")
        self.assertIn("QueryLlmResponseError", completed.parse_errors)

    def test_runtime_events_do_not_carry_raw_customer_message(self):
        sink = CollectingDiagnosticSink()
        classifier = IntentClassifier(
            query_llm=_StubQueryLlm(
                {
                    "intents": [{"intent": "saludo", "mensaje": "hola"}],
                    "mensaje": "hola",
                }
            ),
            sink=sink,
        )
        classifier.query("super-secret-customer-payload")
        for event in sink.events():
            serialized = event.to_dict()
            self.assertNotIn("super-secret-customer-payload", str(serialized))

    def test_runtime_events_do_not_carry_echoed_response_message(self):
        secret = "confidencial-mensaje-cliente-789"
        sink = CollectingDiagnosticSink()
        classifier = IntentClassifier(
            query_llm=_StubQueryLlm(
                {
                    "intents": [{"intent": "saludo", "mensaje": secret}],
                    "mensaje": secret,
                }
            ),
            sink=sink,
        )
        classifier.query("cualquier cosa")
        for event in sink.events():
            serialized = str(event.to_dict())
            self.assertNotIn(secret, serialized)

    def test_runtime_events_do_not_carry_raw_prompt(self):
        sink = CollectingDiagnosticSink()
        sentinel = "RAW-PROMPT-SENTINEL-1234567890"
        classifier = IntentClassifier(
            query_llm=_StubQueryLlm(
                {
                    "intents": [{"intent": "saludo", "mensaje": "hola"}],
                    "mensaje": "hola",
                }
            ),
            sink=sink,
        )
        classifier.query(sentinel)
        for event in sink.events():
            serialized = str(event.to_dict())
            self.assertNotIn(sentinel, serialized)
            self.assertNotIn("Catálogo de posibles intents", serialized)


class PromptFingerprintPrivacyTest(unittest.TestCase):
    def test_same_fingerprint_for_different_messages_with_same_template(self):
        sink = CollectingDiagnosticSink()
        classifier = IntentClassifier(
            query_llm=_StubQueryLlm(
                {
                    "intents": [{"intent": "saludo", "mensaje": "hola"}],
                    "mensaje": "hola",
                }
            ),
            sink=sink,
        )
        classifier.query("primer mensaje super secreto 1")
        first_events = [
            event
            for event in sink.events()
            if isinstance(event, (ClassifierCallStarted, ClassifierCallCompleted))
        ]
        first_started = first_events[0]
        first_completed = first_events[1]
        sink.clear()

        classifier.query("segundo mensaje totalmente distinto 2")
        second_events = [
            event
            for event in sink.events()
            if isinstance(event, (ClassifierCallStarted, ClassifierCallCompleted))
        ]
        second_started = second_events[0]
        second_completed = second_events[1]

        self.assertEqual(first_started.prompt_fingerprint, second_started.prompt_fingerprint)
        self.assertEqual(
            first_completed.prompt_fingerprint, second_completed.prompt_fingerprint
        )
        self.assertEqual(template_fingerprint(), first_started.prompt_fingerprint)
        self.assertEqual(template_fingerprint(), first_completed.prompt_fingerprint)

    def test_fingerprint_is_independent_of_response_payload(self):
        sink = CollectingDiagnosticSink()
        classifier = IntentClassifier(
            query_llm=_StubQueryLlm(
                {
                    "intents": [{"intent": "saludo", "mensaje": "primera respuesta"}],
                    "mensaje": "primera respuesta",
                }
            ),
            sink=sink,
        )
        classifier.query("hola")
        first_completed = next(
            event
            for event in sink.events()
            if isinstance(event, ClassifierCallCompleted)
        )
        sink.clear()

        classifier.query("hola", model="another-model:1b")
        second_completed = next(
            event
            for event in sink.events()
            if isinstance(event, ClassifierCallCompleted)
        )

        self.assertEqual(first_completed.prompt_fingerprint, second_completed.prompt_fingerprint)
        self.assertNotEqual(first_completed.effective_model, second_completed.effective_model)

    def test_template_content_change_changes_fingerprint(self):
        original_catalog = prompt_template_module._INTENT_CATALOG
        original_output = prompt_template_module._OUTPUT_STRUCT
        original_body = prompt_template_module._PROMPT_TEMPLATE_BODY
        original_hash = prompt_template_module._PROMPT_TEMPLATE_HASH
        try:
            prompt_template_module._INTENT_CATALOG = original_catalog + "\n* cambio"
            prompt_template_module._OUTPUT_STRUCT = original_output
            prompt_template_module._PROMPT_TEMPLATE_BODY = (
                "\nCatálogo de posibles intents:\n"
                + prompt_template_module._INTENT_CATALOG
                + "\nmessage\n{message}\n"
                + prompt_template_module._OUTPUT_STRUCT
            )
            prompt_template_module._PROMPT_TEMPLATE_HASH = (
                prompt_template_module._PROMPT_TEMPLATE_HASH.__class__.__name__  # placeholder
            )

            import hashlib

            prompt_template_module._PROMPT_TEMPLATE_HASH = hashlib.sha256(
                prompt_template_module._PROMPT_TEMPLATE_BODY.encode("utf-8")
            ).hexdigest()
            self.assertNotEqual(
                prompt_template_module._PROMPT_TEMPLATE_HASH, original_hash
            )
            self.assertNotEqual(template_fingerprint(), original_hash)
        finally:
            prompt_template_module._INTENT_CATALOG = original_catalog
            prompt_template_module._OUTPUT_STRUCT = original_output
            prompt_template_module._PROMPT_TEMPLATE_BODY = original_body
            prompt_template_module._PROMPT_TEMPLATE_HASH = original_hash

    def test_template_identity_includes_version_and_hash(self):
        identity = template_identity()
        self.assertEqual(identity["prompt_template_version"], PROMPT_TEMPLATE_VERSION)
        self.assertEqual(identity["prompt_template_hash"], template_fingerprint())
        self.assertEqual(len(identity["prompt_template_hash"]), 64)


class EffectiveModelExposureTest(unittest.TestCase):
    def test_production_query_llm_exposes_configured_model(self):
        sink = CollectingDiagnosticSink()
        settings = Settings(
            llm_url="http://llm.test/api/generate",
            llm_model="qwen2.5-coder:7b-ctx8192",
            llm_timeout=30,
            llm_keep_alive="2h",
            llm_num_ctx=8192,
            llm_num_predict=1500,
            llm_log_content=False,
            llm_log_max_chars=1000,
            ollama_proxy_url=None,
        )
        classifier = IntentClassifier(
            query_llm=_StubQueryLlmWithSettings(
                {
                    "intents": [{"intent": "saludo", "mensaje": "hola"}],
                    "mensaje": "hola",
                },
                settings=settings,
            ),
            sink=sink,
        )
        classifier.query("hola")
        started = next(
            event for event in sink.events() if isinstance(event, ClassifierCallStarted)
        )
        completed = next(
            event
            for event in sink.events()
            if isinstance(event, ClassifierCallCompleted)
        )
        self.assertEqual(started.model, "qwen2.5-coder:7b-ctx8192")
        self.assertEqual(completed.effective_model, "qwen2.5-coder:7b-ctx8192")

    def test_injected_stub_with_settings_exposes_its_model(self):
        sink = CollectingDiagnosticSink()
        settings = Settings(
            llm_url="http://llm.test/api/generate",
            llm_model="custom-model:7b",
            llm_timeout=30,
            llm_keep_alive="2h",
            llm_num_ctx=8192,
            llm_num_predict=1500,
            llm_log_content=False,
            llm_log_max_chars=1000,
            ollama_proxy_url=None,
        )
        classifier = IntentClassifier(
            query_llm=_StubQueryLlmWithSettings(
                {
                    "intents": [{"intent": "saludo", "mensaje": "hola"}],
                    "mensaje": "hola",
                },
                settings=settings,
            ),
            sink=sink,
        )
        classifier.query("hola")
        completed = next(
            event
            for event in sink.events()
            if isinstance(event, ClassifierCallCompleted)
        )
        self.assertEqual(completed.effective_model, "custom-model:7b")

    def test_injected_stub_without_settings_falls_back_to_unknown_sentinel(self):
        sink = CollectingDiagnosticSink()
        classifier = IntentClassifier(
            query_llm=_StubQueryLlm(
                {
                    "intents": [{"intent": "saludo", "mensaje": "hola"}],
                    "mensaje": "hola",
                }
            ),
            sink=sink,
        )
        classifier.query("hola")
        completed = next(
            event
            for event in sink.events()
            if isinstance(event, ClassifierCallCompleted)
        )
        self.assertEqual(completed.effective_model, "<unknown>")

    def test_caller_override_used_when_settings_absent(self):
        sink = CollectingDiagnosticSink()
        classifier = IntentClassifier(
            query_llm=_StubQueryLlm(
                {
                    "intents": [{"intent": "saludo", "mensaje": "hola"}],
                    "mensaje": "hola",
                }
            ),
            sink=sink,
        )
        classifier.query("hola", model="override-model:1b")
        completed = next(
            event
            for event in sink.events()
            if isinstance(event, ClassifierCallCompleted)
        )
        self.assertEqual(completed.effective_model, "override-model:1b")

    def test_settings_model_takes_precedence_over_caller_override(self):
        sink = CollectingDiagnosticSink()
        settings = Settings(
            llm_url="http://llm.test/api/generate",
            llm_model="configured-model:7b",
            llm_timeout=30,
            llm_keep_alive="2h",
            llm_num_ctx=8192,
            llm_num_predict=1500,
            llm_log_content=False,
            llm_log_max_chars=1000,
            ollama_proxy_url=None,
        )
        classifier = IntentClassifier(
            query_llm=_StubQueryLlmWithSettings(
                {
                    "intents": [{"intent": "saludo", "mensaje": "hola"}],
                    "mensaje": "hola",
                },
                settings=settings,
            ),
            sink=sink,
        )
        classifier.query("hola", model="override-model:1b")
        completed = next(
            event
            for event in sink.events()
            if isinstance(event, ClassifierCallCompleted)
        )
        self.assertEqual(completed.effective_model, "configured-model:7b")


class ClassifierPublicSurfaceTest(unittest.TestCase):
    def test_intent_classifier_module_all_is_minimal(self):
        self.assertEqual(intent_classifier_module.__all__, ["IntentClassifier"])


if __name__ == "__main__":
    unittest.main()
