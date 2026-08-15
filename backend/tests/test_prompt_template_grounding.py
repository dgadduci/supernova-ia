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
        # The prompt must document the hardened contract from the second
        # correction: substring literal, no reuse from examples or catalog,
        # single action -> single intent, multi intent only for multi action.
        lowered = prompt.casefold()
        self.assertIn("substring", lowered)
        self.assertIn("literal", lowered)
        self.assertIn("no inventes", lowered)
        self.assertIn("no reutilices", lowered)
        self.assertIn("una única acción", lowered)
        self.assertIn("exactamente un intent", lowered)
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


class SecondPromptCorrectionStructureTest(unittest.TestCase):
    """Structural/contract checks for the second prompt correction.

    These tests do not simulate LLM results. They verify that the rendered
    prompt places the current message last, removes the multi-intent
    contaminant, and documents the hardened contract.
    """

    def _build_prompt(self, message: str = "dummy current message") -> str:
        classifier = IntentClassifier(
            query_llm=_StubQueryLlm({"intents": [], "mensaje": ""})
        )
        return classifier._build_prompt(message)

    def test_intro_instructs_to_classify_only_this_message(self):
        prompt = self._build_prompt()
        self.assertIn("clasificá únicamente este mensaje", prompt.casefold())

    def test_catalog_appears_before_examples_section(self):
        prompt = self._build_prompt()
        catalog_pos = prompt.find("Catálogo de posibles intents")
        examples_pos = prompt.find("Ejemplos de referencia")
        self.assertGreater(catalog_pos, -1)
        self.assertGreater(examples_pos, -1)
        self.assertLess(catalog_pos, examples_pos)

    def test_examples_appear_before_current_message(self):
        prompt = self._build_prompt()
        examples_pos = prompt.find("Ejemplos de referencia")
        message_marker = prompt.find("Mensaje actual del cliente")
        current_message_pos = prompt.find("dummy current message")
        self.assertGreater(examples_pos, -1)
        self.assertGreater(message_marker, -1)
        self.assertGreater(current_message_pos, -1)
        self.assertLess(examples_pos, message_marker)
        self.assertLess(message_marker, current_message_pos)

    def test_current_message_is_last_section(self):
        prompt = self._build_prompt("zzzz-sentinel-current-message")
        current_pos = prompt.rfind("zzzz-sentinel-current-message")
        tail = prompt[current_pos + len("zzzz-sentinel-current-message"):]
        self.assertEqual(tail.strip(), "")

    def test_multi_intent_contaminant_is_removed(self):
        prompt = self._build_prompt()
        lowered = prompt.casefold()
        for forbidden in (
            "una empanada de carne y dos pizzas de mozzarella",
            "dos pizzas de mozzarella",
            "me la envies a tilcara 2020",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, lowered)

    def test_short_examples_for_each_failure_case_are_present(self):
        prompt = self._build_prompt()
        cases = [
            ("Cómo puedo recibir el pedido?", "ver_metodos_de_entrega"),
            (
                "Por favor que la entrega sea sin demorarse mucho",
                "set_observacion_pedido",
            ),
            ("Me lo envias a Tilcara 2020", "set_direccion_entrega"),
            ("Pago en Efectivo (prueba cierre)", "set_metodo_de_pago"),
        ]
        for message, intent in cases:
            with self.subTest(intent=intent):
                self.assertIn(message, prompt)
                self.assertIn(intent, prompt)

    def test_examples_section_explicitly_disclaims_content_reuse(self):
        prompt = self._build_prompt()
        self.assertIn(
            "no los uses como contenido", prompt.casefold()
        )

    def test_substring_literal_contract_is_documented(self):
        prompt = self._build_prompt()
        lowered = prompt.casefold()
        self.assertIn("substring literal", lowered)
        self.assertIn("no reutilices", lowered)
        self.assertIn("no inventes", lowered)

    def test_single_action_single_intent_contract_is_documented(self):
        prompt = self._build_prompt()
        lowered = prompt.casefold()
        self.assertIn("una única acción", lowered)
        self.assertIn("exactamente un intent", lowered)
        self.assertIn("varias acciones distintas", lowered)

    def test_modificar_producto_atomicity_rule_is_documented(self):
        prompt = self._build_prompt()
        self.assertIn("modificar_producto", prompt)
        self.assertIn("atómica", prompt.casefold())

    def test_output_structure_lists_intent_and_mensaje_fields(self):
        prompt = self._build_prompt()
        self.assertIn('"intent": "<', prompt)
        self.assertIn('"mensaje": "<', prompt)

    def test_template_version_bumped_for_declarative_amendment(self):
        from backend.diagnostics import PROMPT_TEMPLATE_VERSION

        self.assertEqual(PROMPT_TEMPLATE_VERSION, "intent-classifier/v1.8.0")


class CategoryBrowseGuidanceStructureTest(unittest.TestCase):
    """Structural/contract checks for the category-browse guidance
    pinned by the ``add-llm-assisted-category-menu-resolution`` change.

    These tests do not simulate LLM results. They verify that the
    rendered prompt documents the new category-browse rule and keeps
    ``consultar_producto`` reserved for concrete product detail.
    """

    def _build_prompt(self, message: str = "dummy current message") -> str:
        classifier = IntentClassifier(
            query_llm=_StubQueryLlm({"intents": [], "mensaje": ""})
        )
        return classifier._build_prompt(message)

    def test_catalog_entry_for_ver_menu_documents_category_browse(self):
        prompt = self._build_prompt()
        self.assertIn("categoría del comercio", prompt.casefold())
        self.assertIn("pizzas", prompt.casefold())
        self.assertIn("empanadas", prompt.casefold())
        self.assertIn("bebidas", prompt.casefold())

    def test_catalog_entry_for_consultar_producto_keeps_concrete_product(self):
        prompt = self._build_prompt()
        self.assertIn(
            "producto concreto", prompt.casefold()
        )

    def test_rule_10_distinguishes_category_browse_from_product_detail(self):
        prompt = self._build_prompt()
        lowered = prompt.casefold()
        self.assertIn("10.", prompt)
        self.assertIn("ver_menu", lowered)
        self.assertIn("consultar_producto", lowered)
        self.assertIn("qué pizzas hay", lowered)
        self.assertIn("qué gustos de empanadas tenés", lowered)
        self.assertIn("qué bebidas están disponibles", lowered)
        self.assertIn("nunca debe clasificarse como", lowered)

    def test_template_version_bumped_for_category_browse_guidance(self):
        self.assertEqual(PROMPT_TEMPLATE_VERSION, "intent-classifier/v1.8.0")


class BoundaryCalibrationStructureTest(unittest.TestCase):
    """Structural/contract checks for the boundary-calibration prompt.

    These tests do not simulate LLM results. They verify that the
    rendered prompt documents the new numbered rule 8 (boundary between
    `set_metodo_de_entrega` and `set_observacion_pedido`) and the four
    contrastive `Mensaje:` / `Salida:` examples pinned by the change.
    """

    def _build_prompt(self, message: str = "dummy current message") -> str:
        classifier = IntentClassifier(
            query_llm=_StubQueryLlm({"intents": [], "mensaje": ""})
        )
        return classifier._build_prompt(message)

    def test_rule_8_is_present(self):
        prompt = self._build_prompt()
        self.assertIn("8.", prompt)

    def test_rule_8_documents_modality_boundary(self):
        prompt = self._build_prompt()
        lowered = prompt.casefold()
        self.assertIn("set_metodo_de_entrega", lowered)
        self.assertIn("set_observacion_pedido", lowered)
        self.assertIn("set_direccion_entrega", lowered)
        self.assertIn("modalidad", lowered)
        self.assertIn("operativas", lowered)
        self.assertIn("direccionales", lowered)

    def test_rule_8_gives_priority_to_set_direccion_entrega(self):
        prompt = self._build_prompt()
        lowered = prompt.casefold()
        self.assertIn("set_direccion_entrega", lowered)
        self.assertIn("domicilio", lowered)
        self.assertIn("dirección", lowered)
        self.assertIn("siempre", lowered)
        self.assertIn("nunca", lowered)

    def test_rule_8_scopes_observation_to_non_directional_operations(self):
        prompt = self._build_prompt()
        lowered = prompt.casefold()
        self.assertIn("set_observacion_pedido", lowered)
        for term in ("portón", "timbre", "mascotas", "cuidado", "edificio"):
            with self.subTest(term=term):
                self.assertIn(term, lowered)

    def test_rule_8_keeps_substring_literal_contract(self):
        prompt = self._build_prompt()
        lowered = prompt.casefold()
        self.assertIn("substring literal", lowered)
        self.assertIn("no reutilices", lowered)
        self.assertIn("no inventes", lowered)
        self.assertIn("una única acción", lowered)
        self.assertIn("exactamente un intent", lowered)

    def test_rule_8_orders_observation_example_before_modality_example(self):
        prompt = self._build_prompt()
        observation_pos = prompt.find("La entrega es por el portón lateral")
        modality_pos = prompt.find("Quiero envío a domicilio")
        self.assertGreater(observation_pos, -1)
        self.assertGreater(modality_pos, -1)
        self.assertLess(observation_pos, modality_pos)

    def test_boundary_examples_route_observation_messages_to_set_observacion_pedido(self):
        prompt = self._build_prompt()
        cases = [
            "La entrega es por el portón lateral",
            "Cuidado con el perro",
        ]
        for message in cases:
            with self.subTest(message=message):
                message_pos = prompt.find(message)
                self.assertGreater(message_pos, -1)
                salta_pos = prompt.find("Salida:", message_pos)
                self.assertGreater(salta_pos, message_pos)
                json_pos = prompt.find("```json", salta_pos)
                self.assertGreater(json_pos, salta_pos)
                end_pos = prompt.find("```", json_pos + len("```json"))
                self.assertGreater(end_pos, json_pos)
                block = prompt[json_pos:end_pos]
                self.assertIn("set_observacion_pedido", block)
                self.assertNotIn("set_metodo_de_entrega", block)

    def test_boundary_examples_route_modality_messages_to_set_metodo_de_entrega(self):
        prompt = self._build_prompt()
        cases = [
            "Quiero envío a domicilio",
            "Lo retiro por el local",
        ]
        for message in cases:
            with self.subTest(message=message):
                message_pos = prompt.find(message)
                self.assertGreater(message_pos, -1)
                salta_pos = prompt.find("Salida:", message_pos)
                self.assertGreater(salta_pos, message_pos)
                json_pos = prompt.find("```json", salta_pos)
                self.assertGreater(json_pos, salta_pos)
                end_pos = prompt.find("```", json_pos + len("```json"))
                self.assertGreater(end_pos, json_pos)
                block = prompt[json_pos:end_pos]
                self.assertIn("set_metodo_de_entrega", block)
                self.assertNotIn("set_observacion_pedido", block)

    def test_boundary_messages_are_substring_literals(self):
        prompt = self._build_prompt()
        for message in (
            "La entrega es por el portón lateral",
            "Cuidado con el perro",
            "Quiero envío a domicilio",
            "Lo retiro por el local",
        ):
            with self.subTest(message=message):
                self.assertIn(message, prompt)

    def test_template_version_bumped_to_v1_8_0(self):
        self.assertEqual(PROMPT_TEMPLATE_VERSION, "intent-classifier/v1.8.0")


if __name__ == "__main__":
    unittest.main()
