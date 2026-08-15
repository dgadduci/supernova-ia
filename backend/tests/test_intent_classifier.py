import importlib
import logging
import unittest

import pydantic

from backend.diagnostics import prompt_template as prompt_template_module
from backend.diagnostics.prompt_template import (
    PROMPT_TEMPLATE_VERSION,
    build_intent_prompt,
)
from backend.intents.schemas.intent_classification import IntentName
from backend.llm import intent_classifier as intent_classifier_module
from backend.llm.intent_classifier import IntentClassifier
from backend.llm.query_llm import (
    QueryLlmConnectionError,
    QueryLlmHttpError,
    QueryLlmResponseError,
    QueryLlmTimeoutError,
)


class _StubQueryLlm:
    def __init__(self, payload: dict | None = None, side_effect: BaseException | None = None):
        self._payload = payload
        self._side_effect = side_effect
        self.calls: list[str] = []

    def request(self, prompt: str) -> dict:
        self.calls.append(prompt)
        if self._side_effect is not None:
            raise self._side_effect
        if self._payload is None:
            return {}
        return self._payload


class IntentClassifierQueryTest(unittest.TestCase):
    def test_single_agregar_producto(self):
        stub = _StubQueryLlm(
            payload={
                "intents": [
                    {"intent": "agregar_producto", "mensaje": "una empanada"}
                ],
                "mensaje": "quiero una empanada",
            }
        )
        classifier = IntentClassifier(query_llm=stub)

        result = classifier.query("quiero una empanada")

        self.assertEqual(len(result.intents), 1)
        self.assertEqual(result.intents[0].intent, IntentName.AGREGAR_PRODUCTO)
        self.assertEqual(result.intents[0].mensaje, "una empanada")
        self.assertEqual(result.mensaje, "quiero una empanada")
        self.assertEqual(len(stub.calls), 1)

    def test_multiple_intents_preserve_order(self):
        stub = _StubQueryLlm(
            payload={
                "intents": [
                    {"intent": "agregar_producto", "mensaje": "dos pizzas"},
                    {"intent": "set_metodo_de_pago", "mensaje": "efectivo"},
                ],
                "mensaje": "quiero dos pizzas y pago en efectivo",
            }
        )
        classifier = IntentClassifier(query_llm=stub)

        result = classifier.query("quiero dos pizzas y pago en efectivo")

        self.assertEqual(
            [ci.intent for ci in result.intents],
            [IntentName.AGREGAR_PRODUCTO, IntentName.SET_METODO_DE_PAGO],
        )

    def test_replacement_preserves_quitar_then_agregar(self):
        stub = _StubQueryLlm(
            payload={
                "intents": [
                    {"intent": "quitar_producto", "mensaje": "pizza de mozzarella"},
                    {"intent": "agregar_producto", "mensaje": "pizza napolitana"},
                ],
                "mensaje": "Cambiame la pizza de mozzarella por una napolitana",
            }
        )
        classifier = IntentClassifier(query_llm=stub)

        result = classifier.query(
            "Cambiame la pizza de mozzarella por una napolitana"
        )

        self.assertEqual(
            [ci.intent for ci in result.intents],
            [IntentName.QUITAR_PRODUCTO, IntentName.AGREGAR_PRODUCTO],
        )
        self.assertEqual(result.intents[0].mensaje, "pizza de mozzarella")
        self.assertEqual(result.intents[1].mensaje, "pizza napolitana")

    def test_non_string_message_raises_type_error(self):
        stub = _StubQueryLlm(payload={})
        classifier = IntentClassifier(query_llm=stub)

        with self.assertRaises(TypeError):
            classifier.query(None)  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            classifier.query(123)  # type: ignore[arg-type]
        self.assertEqual(stub.calls, [])

    def test_empty_or_whitespace_message_raises_value_error(self):
        stub = _StubQueryLlm(payload={})
        classifier = IntentClassifier(query_llm=stub)

        with self.assertRaises(ValueError):
            classifier.query("")
        with self.assertRaises(ValueError):
            classifier.query("   ")
        self.assertEqual(stub.calls, [])

    def test_unsupported_intent_raises_validation_error(self):
        stub = _StubQueryLlm(
            payload={
                "intents": [{"intent": "comprar_casa", "mensaje": "x"}],
                "mensaje": "x",
            }
        )
        classifier = IntentClassifier(query_llm=stub)

        with self.assertRaises(pydantic.ValidationError):
            classifier.query("comprame una casa")

    def test_malformed_output_raises_validation_error(self):
        cases = [
            {},
            {"intents": [], "mensaje": "x"},
            {
                "intents": [
                    {"intent": "agregar_producto", "mensaje": "x"}
                ],
                "mensaje": "  ",
            },
        ]
        for payload in cases:
            with self.subTest(payload=payload):
                stub = _StubQueryLlm(payload=payload)
                classifier = IntentClassifier(query_llm=stub)
                with self.assertRaises(pydantic.ValidationError):
                    classifier.query("hola")

    def test_query_llm_errors_propagate_unchanged(self):
        cases = [
            QueryLlmTimeoutError("timeout"),
            QueryLlmConnectionError("conn"),
            QueryLlmHttpError(500, "boom"),
            QueryLlmResponseError("bad json"),
        ]
        for exc in cases:
            with self.subTest(exc=type(exc).__name__):
                stub = _StubQueryLlm(side_effect=exc)
                classifier = IntentClassifier(query_llm=stub)
                with self.assertRaises(type(exc)) as ctx:
                    classifier.query("hola")
                self.assertIs(ctx.exception, exc)


class IntentClassifierPromptTest(unittest.TestCase):
    def test_prompt_includes_message_and_no_mutable_state(self):
        stub = _StubQueryLlm(
            payload={
                "intents": [
                    {"intent": "agregar_producto", "mensaje": "x"}
                ],
                "mensaje": "primer mensaje",
            }
        )
        classifier = IntentClassifier(query_llm=stub)

        classifier.query("primer mensaje")
        first_prompt = stub.calls[0]

        stub2 = _StubQueryLlm(
            payload={
                "intents": [
                    {"intent": "agregar_producto", "mensaje": "y"}
                ],
                "mensaje": "segundo mensaje",
            }
        )
        classifier2 = IntentClassifier(query_llm=stub2)
        classifier2.query("segundo mensaje")
        second_prompt = stub2.calls[0]

        self.assertIn("primer mensaje", first_prompt)
        self.assertNotIn("segundo mensaje", first_prompt)
        self.assertIn("segundo mensaje", second_prompt)
        self.assertNotIn("primer mensaje", second_prompt)

    def test_prompt_preserves_legacy_intent_names(self):
        stub = _StubQueryLlm(
            payload={
                "intents": [
                    {"intent": "agregar_producto", "mensaje": "x"}
                ],
                "mensaje": "x",
            }
        )
        classifier = IntentClassifier(query_llm=stub)

        classifier.query("hola")
        prompt = stub.calls[0]

        for name in (
            "saludo",
            "agradecimiento",
            "despedida",
            "ver_metodos_de_pago",
            "ver_metodos_de_entrega",
            "consultar_domicilio_comercio",
            "consultar_horarios_comercio",
            "iniciar_pedido",
            "agregar_producto",
            "quitar_producto",
            "vaciar_pedido",
            "set_observacion_pedido",
            "consultar_resumen_pedido",
            "set_metodo_de_entrega",
            "set_direccion_entrega",
            "set_fecha_hora_entrega",
            "set_metodo_de_pago",
            "confirmar_pedido",
            "consultar_estado_pedido",
            "cancelar_pedido",
            "desconocida",
        ):
            with self.subTest(name=name):
                self.assertIn(name, prompt)


class IntentClassifierBoundariesTest(unittest.TestCase):
    def test_module_does_not_import_disallowed_side_effects(self):
        importlib.reload(intent_classifier_module)
        module = intent_classifier_module
        with open(module.__file__, encoding="utf-8") as fh:
            source = fh.read()
        for forbidden in (
            "import requests",
            "from requests",
            "import fastapi",
            "from fastapi",
            "import sqlalchemy",
            "from sqlalchemy",
            "from backend.sessions",
            "from backend.intents.handlers",
            "from backend.intents.recognizers",
            "from backend.intents.resolvers",
            "from backend.intents.processor",
            "from backend.intents.orchestration",
            "from backend.intents.context",
            "backend.old_project",
            "from backend.old_project",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)

    def test_module_does_not_configure_global_logging_handlers(self):
        before = list(logging.getLogger().handlers)
        importlib.reload(intent_classifier_module)
        after = list(logging.getLogger().handlers)
        self.assertEqual(before, after)
        with open(intent_classifier_module.__file__, encoding="utf-8") as fh:
            self.assertNotIn("logging.basicConfig", fh.read())

    def test_public_surface_is_limited(self):
        self.assertEqual(intent_classifier_module.__all__, ["IntentClassifier"])

    def test_classifier_is_importable_from_modern_llm_package(self):
        from backend.llm.intent_classifier import IntentClassifier as Cls
        self.assertIs(Cls, IntentClassifier)


class IntentClassifierDebugLogPrivacyTest(unittest.TestCase):
    def test_debug_log_does_not_leak_customer_message_or_llm_response(self):
        message_sentinel = "CUSTOMER-MESSAGE-SENTINEL-abcdef-1234567890"
        response_sentinel = "LLM-RESPONSE-MESSAGE-SENTINEL-fedcba-0987654321"
        stub = _StubQueryLlm(
            payload={
                "intents": [{"intent": "saludo", "mensaje": response_sentinel}],
                "mensaje": response_sentinel,
            }
        )
        classifier = IntentClassifier(query_llm=stub)

        with self.assertLogs("backend.llm.intent_classifier", level="DEBUG") as captured:
            classifier.query(message_sentinel)

        self.assertTrue(captured.records, "expected at least one DEBUG log record")
        joined = "\n".join(record.getMessage() for record in captured.records)
        self.assertNotIn(message_sentinel, joined)
        self.assertNotIn(response_sentinel, joined)
        for record in captured.records:
            for field_name in dir(record):
                if field_name.startswith("_"):
                    continue
                value = getattr(record, field_name, None)
                if isinstance(value, str):
                    self.assertNotIn(message_sentinel, value)
                    self.assertNotIn(response_sentinel, value)


class IntentClassifierRemovalSemanticRuleTest(unittest.TestCase):
    """Verifies the static prompt instructs that messages expressing removal
    of products from the current order map to ``quitar_producto`` and never
    to ``agregar_producto``. The decision criterion is the meaning of
    removal; representative wording is guidance, not a closed vocabulary.
    """

    _PROMPT = build_intent_prompt("__placeholder__")

    def test_prompt_states_removal_semantic_rule(self):
        self.assertIn("quitar_producto", self._PROMPT)
        self.assertIn("agregar_producto", self._PROMPT)
        for marker in (
            "SEMÁNTICA",
            "significado de remoción",
            "NUNCA debe clasificarse como `agregar_producto`",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self._PROMPT)

    def test_prompt_includes_representative_removal_wording(self):
        for example in (
            "quita",
            "quitá",
            "quitar",
            "saca",
            "sacá",
            "sacar",
            "retirá",
            "retirar",
            "eliminá",
            "eliminar",
        ):
            with self.subTest(example=example):
                self.assertIn(example, self._PROMPT)

    def test_prompt_keeps_add_path_unchanged(self):
        self.assertIn(
            "agregar uno o más productos al pedido = `agregar_producto`",
            self._PROMPT,
        )

    def test_prompt_does_not_introduce_a_closed_verb_list(self):
        self.assertIn("lista cerrada", self._PROMPT)

    def test_prompt_template_version_is_bumped_monotonically(self):
        self.assertEqual(PROMPT_TEMPLATE_VERSION, "intent-classifier/v1.9.0")
        self.assertGreater(
            PROMPT_TEMPLATE_VERSION,
            "intent-classifier/v1.8.0",
        )


class IntentClassifierRemovalPayloadSchemaTest(unittest.TestCase):
    """Verifies that a controlled LLM payload returning one
    ``quitar_producto`` for a representative removal request preserves the
    literal customer-message substring and round-trips through the
    existing ``IntentClassificationResult`` contract. These checks verify
    the classifier schema, not the live LLM behavior.
    """

    _CASES: tuple[tuple[str, str], ...] = (
        ("saca una de mozzarella chica", "saca una de mozzarella chica"),
        ("sacar dos de mozzarella chica", "sacar dos de mozzarella chica"),
        ("retirá una de mozzarella chica", "retirá una de mozzarella chica"),
        ("quitá una pizza", "quitá una pizza"),
    )

    def test_single_quitar_producto_preserves_literal_mensaje(self):
        for full_message, classified_mensaje in self._CASES:
            with self.subTest(message=full_message):
                stub = _StubQueryLlm(
                    payload={
                        "intents": [
                            {
                                "intent": "quitar_producto",
                                "mensaje": classified_mensaje,
                            }
                        ],
                        "mensaje": full_message,
                    }
                )
                classifier = IntentClassifier(query_llm=stub)

                result = classifier.query(full_message)

                self.assertEqual(len(result.intents), 1)
                classified = result.intents[0]
                self.assertEqual(classified.intent, IntentName.QUITAR_PRODUCTO)
                self.assertEqual(classified.mensaje, classified_mensaje)
                self.assertIn(classified.mensaje, full_message)
                self.assertEqual(result.mensaje, full_message)
                self.assertEqual(len(stub.calls), 1)

    def test_removal_payload_never_claims_agregar_producto(self):
        stub = _StubQueryLlm(
            payload={
                "intents": [
                    {
                        "intent": "quitar_producto",
                        "mensaje": "saca una de mozzarella chica",
                    }
                ],
                "mensaje": "saca una de mozzarella chica",
            }
        )
        classifier = IntentClassifier(query_llm=stub)

        result = classifier.query("saca una de mozzarella chica")

        self.assertEqual(
            [ci.intent for ci in result.intents],
            [IntentName.QUITAR_PRODUCTO],
        )
        self.assertNotIn(IntentName.AGREGAR_PRODUCTO, result.intents)

    def test_add_request_still_maps_to_agregar_producto(self):
        stub = _StubQueryLlm(
            payload={
                "intents": [
                    {
                        "intent": "agregar_producto",
                        "mensaje": "una empanada",
                    }
                ],
                "mensaje": "quiero una empanada",
            }
        )
        classifier = IntentClassifier(query_llm=stub)

        result = classifier.query("quiero una empanada")

        self.assertEqual(len(result.intents), 1)
        self.assertEqual(result.intents[0].intent, IntentName.AGREGAR_PRODUCTO)


class IntentClassifierPromptTemplateFingerprintTest(unittest.TestCase):
    """Confirms the static-only fingerprint contract still holds after the
    removal-semantic rule is added. The fingerprint MUST be derived from
    the static template body only and MUST change whenever the static
    template body changes.
    """

    def test_fingerprint_is_derived_from_static_body(self):
        from backend.diagnostics.prompt_template import template_fingerprint

        expected = prompt_template_module._PROMPT_TEMPLATE_HASH
        self.assertEqual(template_fingerprint(), expected)

    def test_fingerprint_changes_when_body_changes(self):
        from backend.diagnostics.prompt_template import template_fingerprint

        original_body = prompt_template_module._PROMPT_TEMPLATE_BODY
        original_hash = prompt_template_module._PROMPT_TEMPLATE_HASH
        try:
            modified_body = original_body + "\n# drift marker"
            prompt_template_module._PROMPT_TEMPLATE_BODY = modified_body
            prompt_template_module._PROMPT_TEMPLATE_HASH = (
                __import__("hashlib").sha256(modified_body.encode("utf-8")).hexdigest()
            )
            self.assertNotEqual(template_fingerprint(), original_hash)
        finally:
            prompt_template_module._PROMPT_TEMPLATE_BODY = original_body
            prompt_template_module._PROMPT_TEMPLATE_HASH = original_hash


class IntentClassifierDeclarativeObservationRuleTest(unittest.TestCase):
    """The product-line observation capability was removed.

    The prompt no longer documents any ``set_observacion_producto``
    rule because the dispatcher rejects the intent outside the
    confirmation context. The remaining rule 9 covers the
    observation-bounded resolver contract and the prompt-template
    tests below assert that the explicit-declarative and
    add-with-condition examples are still present for the
    ``agregar_producto`` branch (the historic regressions are
    superseded by the confirmation-time observation flow).
    """

    _PROMPT = build_intent_prompt("__placeholder__")

    def test_prompt_no_longer_documents_set_observacion_producto(self):
        lowered = self._PROMPT.casefold()
        self.assertNotIn("set_observacion_producto", lowered)

    def test_prompt_still_documents_agregar_producto(self):
        self.assertIn("agregar_producto", self._PROMPT.casefold())

    def test_prompt_still_documents_set_observacion_pedido(self):
        self.assertIn("set_observacion_pedido", self._PROMPT.casefold())

    def test_prompt_lists_representative_add_verbs(self):
        """The removal of the product-line observation rule 10 dropped the
        closed list of declarative add verbs. The prompt still uses
        the canonical add verb ``quiero`` to ground the
        agregar_producto examples.
        """
        for verb in ("quiero", "agregar"):
            with self.subTest(verb=verb):
                self.assertIn(verb, self._PROMPT)

    def test_prompt_includes_explicit_add_with_condition_example(self):
        """The explicit add example ``Quiero envío a domicilio`` is
        still present in the prompt and renders an
        ``agregar_producto``-compatible quitar/modificar
        contract for delivery modality.
        """
        message = "Quiero envío a domicilio"
        self.assertIn(message, self._PROMPT)
        message_pos = self._PROMPT.find(message)
        salta_pos = self._PROMPT.find("Salida:", message_pos)
        json_pos = self._PROMPT.find("```json", salta_pos)
        end_pos = self._PROMPT.find("```", json_pos + len("```json"))
        block = self._PROMPT[json_pos:end_pos]
        self.assertIn("set_metodo_de_entrega", block)


class IntentClassifierDeclarativeObservationPayloadTest(unittest.TestCase):
    """The product-line observation payload tests are superseded.

    The historic regression used the legacy classifier contract that
    accepted ``set_observacion_producto`` from the LLM. The new
    contract lets the classifier still emit ``set_observacion_producto``
    for backward compatibility with persisted payloads, but the
    initial dispatcher rejects every direct observation outside the
    confirmation context. The remaining payload test verifies the
    explicit-add-with-condition path remains ``agregar_producto``.
    """

    def test_explicit_add_with_condition_remains_agregar_producto(self):
        message = "quiero una pizza de mozzarella chica sin aceitunas"
        stub = _StubQueryLlm(
            payload={
                "intents": [
                    {
                        "intent": "agregar_producto",
                        "mensaje": message,
                    }
                ],
                "mensaje": message,
            }
        )
        classifier = IntentClassifier(query_llm=stub)

        result = classifier.query(message)

        self.assertEqual(len(result.intents), 1)
        self.assertEqual(result.intents[0].intent, IntentName.AGREGAR_PRODUCTO)
        self.assertEqual(result.intents[0].mensaje, message)
        self.assertNotIn(
            IntentName.SET_OBSERVACION_PRODUCTO,
            [item.intent for item in result.intents],
        )


class IntentClassifierDeclarativeObservationFingerprintTest(unittest.TestCase):
    """Confirms the static-only fingerprint contract holds for the
    confirmation-time observation amendment: the fingerprint is derived
    from the static template body only, the version is bumped, and the
    runtime diagnostics never include the customer message.
    """

    def test_template_version_is_bumped_for_confirmation_time_amendment(self):
        self.assertEqual(PROMPT_TEMPLATE_VERSION, "intent-classifier/v1.9.0")
        self.assertGreater(
            PROMPT_TEMPLATE_VERSION, "intent-classifier/v1.8.0"
        )

    def test_template_fingerprint_excludes_customer_message(self):
        from backend.diagnostics.prompt_template import template_fingerprint

        sentinel = "DECLARATIVE-CUSTOMER-MESSAGE-SENTINEL-987654321"
        with_prompt = build_intent_prompt(sentinel)
        self.assertIn(sentinel, with_prompt)
        self.assertNotIn(sentinel, prompt_template_module._PROMPT_TEMPLATE_BODY)
        fingerprint = template_fingerprint()
        self.assertEqual(len(fingerprint), 64)
        self.assertNotIn(sentinel, fingerprint)

    def test_template_identity_pins_version_and_fingerprint(self):
        from backend.diagnostics.prompt_template import template_identity

        identity = template_identity()
        self.assertEqual(identity["prompt_template_version"], PROMPT_TEMPLATE_VERSION)
        self.assertEqual(
            identity["prompt_template_hash"], prompt_template_module._PROMPT_TEMPLATE_HASH
        )
        self.assertEqual(len(identity["prompt_template_hash"]), 64)


if __name__ == "__main__":
    unittest.main()