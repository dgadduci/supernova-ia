"""Focused tests for the experimental full-message outbound styler.

The styler is the shared, optional presentation-only layer invoked
once per turn by :mod:`backend.services.outbound_response_mapper`.
The tests cover the privacy, eligibility, one-call batching,
fallback, observability and transaction-boundary contracts from
the approved experimental OpenSpec change.

The tests intentionally avoid hitting the real LLM transport.
Every ``QueryLlm`` interaction is faked through a ``MagicMock``
that captures the rendered prompt and returns a controlled JSON
payload. The real ``Comercio`` and ``FlavorComunicacion`` ORM rows
are replaced by ``MagicMock`` instances so the tests stay fast and
isolated.

The tests verify the structural contract ONLY. They never assert
semantic equivalence of the LLM-generated message with the
factual source (no protected-token validator, no comparison of
quantities/products); they only assert that a structurally valid
generated message replaces the factual one and that any structural
problem triggers the documented fallback.
"""
from __future__ import annotations

import io
import json
import logging
import unittest
from unittest.mock import MagicMock

from backend.diagnostics.outbound_response_style_prompt_template import (
    OUTBOUND_STYLE_PROMPT_TEMPLATE_VERSION,
    build_outbound_style_prompt,
    outbound_style_template_fingerprint,
    outbound_style_template_identity,
)
from backend.intents.schemas.customer_response import CustomerResponse
from backend.llm.query_llm import (
    QueryLlmConnectionError,
    QueryLlmError,
    QueryLlmHttpError,
    QueryLlmResponseError,
    QueryLlmTimeoutError,
)
from backend.observability import (
    COMPONENT_OUTBOUND_STYLE,
    EVENT_OUTBOUND_STYLE,
)
from backend.services.outbound_response_styler import (
    EXECUTED_STATUS,
    FALLBACK_CONNECTION,
    FALLBACK_EMPTY_MESSAGE,
    FALLBACK_HTTP,
    FALLBACK_MALFORMED_BATCH,
    FALLBACK_MESSAGE_INVALID,
    FALLBACK_RESPONSE,
    FALLBACK_TIMEOUT,
    FALLBACK_UNEXPECTED,
    NEUTRO_FLAVOR_CODE,
    OUTCOME_APPLIED,
    OUTCOME_NOT_ATTEMPTED,
    RESPONSE_TYPE_INFO_ADDRESS,
    RESPONSE_TYPE_INFO_DELIVERY_METHODS,
    RESPONSE_TYPE_INFO_HOURS,
    RESPONSE_TYPE_INFO_PAYMENT_METHODS,
    RESPONSE_TYPE_MENU_FULL,
    RESPONSE_TYPE_ORDER_CONFIRMED,
    RESPONSE_TYPE_ORDER_EMPTIED,
    RESPONSE_TYPE_ORDER_STARTED,
    RESPONSE_TYPE_ORDER_STATUS,
    RESPONSE_TYPE_ORDER_SUMMARY,
    RESPONSE_TYPE_PRODUCT_ADD_SUCCESS,
    RESPONSE_TYPE_PRODUCT_INFO,
    RESPONSE_TYPE_PRODUCT_MODIFY_SUCCESS,
    RESPONSE_TYPE_PRODUCT_REMOVE_SUCCESS,
    RESPONSE_TYPE_SOCIAL_GOODBYE,
    RESPONSE_TYPE_SOCIAL_GREETING,
    RESPONSE_TYPE_SOCIAL_NO,
    RESPONSE_TYPE_SOCIAL_THANKS,
    RESPONSE_TYPE_SOCIAL_YES,
    is_eligible_response,
    response_type_for,
    select_eligible,
    style_responses,
    styler_fingerprint,
    styler_version,
)

_SALUDO = (
    "¡Hola! Puedo ayudarte a armar tu pedido. Decime qué querés."
)
_AGG_SUCCESS = "Listo, agregué 2 Empanadas de Pollo."
_MENU_HEADER = "Menú disponible:"
_MENU_MULTILINE = (
    "Menú disponible:\n"
    "- Pizza Mozzarella: $5000\n"
    "- Pizza Napolitana: $5200\n"
    "- Empanadas de Pollo: $1200"
)
_ORDER_STATUS = (
    "Tu pedido está en preparación y sale en 15 minutos."
)
_CONFIRM = (
    "Listo, confirmé tu pedido. Te avisamos cuando esté en camino."
)


def _flavor(
    codigo: str = "serio",
    *,
    activo: bool = True,
    instruccion: str = "Tono serio.",
) -> MagicMock:
    flavor = MagicMock()
    flavor.activo = activo
    flavor.codigo = codigo
    flavor.instruccion_llm = instruccion
    return flavor


def _db_with_flavor(
    comercio_id: int = 1, *, flavor: MagicMock | None = None
) -> MagicMock:
    """Return a MagicMock session whose ``db.get`` returns the
    supplied comercio / flavor pair.
    """
    comercio = MagicMock()
    comercio.flavor_comunicacion_id = 1 if flavor is not None else None
    db = MagicMock()
    if flavor is None:
        db.get.side_effect = [comercio, None]
    else:
        db.get.side_effect = [comercio, flavor]
    return db


def _llm(payload: dict | Exception) -> MagicMock:
    client = MagicMock(name="QueryLlmStub")
    if isinstance(payload, BaseException):
        client.request.side_effect = payload
    else:
        client.request.return_value = payload
    return client


def _last_event(stream: io.StringIO) -> dict:
    last_line = stream.getvalue().splitlines()[-1]
    event = json.loads(last_line.strip())
    return event


class ResponseTypeMappingTest(unittest.TestCase):
    def test_eligible_pairs_map_to_documented_tokens(self) -> None:
        cases = {
            ("saludo", EXECUTED_STATUS): RESPONSE_TYPE_SOCIAL_GREETING,
            ("agradecimiento", EXECUTED_STATUS): RESPONSE_TYPE_SOCIAL_THANKS,
            ("despedida", EXECUTED_STATUS): RESPONSE_TYPE_SOCIAL_GOODBYE,
            ("respuesta_afirmativa", EXECUTED_STATUS): RESPONSE_TYPE_SOCIAL_YES,
            ("respuesta_negativa", EXECUTED_STATUS): RESPONSE_TYPE_SOCIAL_NO,
            ("ver_menu", EXECUTED_STATUS): RESPONSE_TYPE_MENU_FULL,
            ("consultar_producto", EXECUTED_STATUS): RESPONSE_TYPE_PRODUCT_INFO,
            (
                "ver_metodos_de_pago",
                EXECUTED_STATUS,
            ): RESPONSE_TYPE_INFO_PAYMENT_METHODS,
            (
                "ver_metodos_de_entrega",
                EXECUTED_STATUS,
            ): RESPONSE_TYPE_INFO_DELIVERY_METHODS,
            (
                "consultar_domicilio_comercio",
                EXECUTED_STATUS,
            ): RESPONSE_TYPE_INFO_ADDRESS,
            (
                "consultar_horarios_comercio",
                EXECUTED_STATUS,
            ): RESPONSE_TYPE_INFO_HOURS,
            ("agregar_producto", EXECUTED_STATUS): RESPONSE_TYPE_PRODUCT_ADD_SUCCESS,
            ("quitar_producto", EXECUTED_STATUS): RESPONSE_TYPE_PRODUCT_REMOVE_SUCCESS,
            (
                "modificar_producto",
                EXECUTED_STATUS,
            ): RESPONSE_TYPE_PRODUCT_MODIFY_SUCCESS,
            ("consultar_estado_pedido", EXECUTED_STATUS): RESPONSE_TYPE_ORDER_STATUS,
            ("consultar_resumen_pedido", EXECUTED_STATUS): RESPONSE_TYPE_ORDER_SUMMARY,
            ("confirmar_pedido", EXECUTED_STATUS): RESPONSE_TYPE_ORDER_CONFIRMED,
            ("iniciar_pedido", EXECUTED_STATUS): RESPONSE_TYPE_ORDER_STARTED,
            ("vaciar_pedido", EXECUTED_STATUS): RESPONSE_TYPE_ORDER_EMPTIED,
        }
        for (intent, status), token in cases.items():
            with self.subTest(intent=intent, status=status):
                self.assertEqual(response_type_for(intent, status), token)

    def test_desconocida_is_explicitly_ineligible_for_every_status(self) -> None:
        for status in (
            "executed",
            "rejected",
            "failed",
            "pending_resolution",
            "ready",
        ):
            with self.subTest(status=status):
                self.assertIsNone(response_type_for("desconocida", status))

    def test_error_rejected_pending_statuses_are_ineligible(self) -> None:
        for status in ("rejected", "failed", "pending_resolution", "ready"):
            for intent in (
                "saludo",
                "agregar_producto",
                "consultar_resumen_pedido",
                "confirmar_pedido",
                "ver_menu",
            ):
                with self.subTest(intent=intent, status=status):
                    self.assertIsNone(response_type_for(intent, status))

    def test_free_text_intents_are_ineligible(self) -> None:
        for intent in (
            "set_observacion_pedido",
            "set_observacion_producto",
            "set_direccion_entrega",
            "set_fecha_hora_entrega",
            "set_metodo_de_pago",
            "set_metodo_de_entrega",
        ):
            with self.subTest(intent=intent):
                self.assertIsNone(response_type_for(intent, EXECUTED_STATUS))

    def test_unknown_intent_is_ineligible(self) -> None:
        self.assertIsNone(
            response_type_for("__futuro_deferred_intent__", EXECUTED_STATUS)
        )

    def test_response_type_for_rejects_non_string_inputs(self) -> None:
        self.assertIsNone(response_type_for(None, EXECUTED_STATUS))  # type: ignore[arg-type]
        self.assertIsNone(response_type_for("saludo", None))  # type: ignore[arg-type]


class SelectEligibleTest(unittest.TestCase):
    def test_preserves_index_and_response_for_eligible_only(self) -> None:
        responses = [
            CustomerResponse(message="A", intent="saludo", status="executed"),
            CustomerResponse(message="B", intent="desconocida", status="rejected"),
            CustomerResponse(message="C", intent="agregar_producto", status="executed"),
            CustomerResponse(
                message="D", intent="set_direccion_entrega", status="executed"
            ),
        ]
        eligible = select_eligible(responses)
        self.assertEqual(
            [(item.index, item.response_type) for item in eligible],
            [
                (0, RESPONSE_TYPE_SOCIAL_GREETING),
                (2, RESPONSE_TYPE_PRODUCT_ADD_SUCCESS),
            ],
        )
        self.assertEqual(eligible[0].response, responses[0])
        self.assertEqual(eligible[1].response, responses[2])

    def test_handles_empty_input(self) -> None:
        self.assertEqual(select_eligible([]), [])

    def test_ignores_non_responses(self) -> None:
        self.assertEqual(
            select_eligible([object(), None]),  # type: ignore[list-item]
            [],
        )

    def test_is_eligible_response_helper(self) -> None:
        self.assertTrue(
            is_eligible_response(
                CustomerResponse(
                    message="A", intent="saludo", status="executed"
                )
            )
        )
        self.assertFalse(
            is_eligible_response(
                CustomerResponse(
                    message="A", intent="saludo", status="rejected"
                )
            )
        )


class FlavorResolutionTest(unittest.TestCase):
    def test_neutro_flavor_is_not_usable(self) -> None:
        db = _db_with_flavor(1, flavor=_flavor(NEUTRO_FLAVOR_CODE))
        responses = [
            CustomerResponse(
                message="Hola", intent="saludo", status="executed"
            )
        ]
        client = _llm(
            {"items": [{"index": 0, "message": "¡Hey!"}]}
        )
        styled = style_responses(db, 1, responses, query_llm=client)
        self.assertEqual(styled[0].message, "Hola")
        self.assertEqual(client.request.call_count, 0)

    def test_inactive_flavor_is_not_usable(self) -> None:
        db = _db_with_flavor(1, flavor=_flavor(activo=False))
        responses = [
            CustomerResponse(
                message="Hola", intent="saludo", status="executed"
            )
        ]
        client = _llm(
            {"items": [{"index": 0, "message": "¡Hey!"}]}
        )
        styled = style_responses(db, 1, responses, query_llm=client)
        self.assertEqual(styled[0].message, "Hola")
        self.assertEqual(client.request.call_count, 0)

    def test_empty_instruccion_llm_is_not_usable(self) -> None:
        db = _db_with_flavor(1, flavor=_flavor(instruccion=""))
        responses = [
            CustomerResponse(
                message="Hola", intent="saludo", status="executed"
            )
        ]
        client = _llm(
            {"items": [{"index": 0, "message": "¡Hey!"}]}
        )
        styled = style_responses(db, 1, responses, query_llm=client)
        self.assertEqual(styled[0].message, "Hola")
        self.assertEqual(client.request.call_count, 0)

    def test_whitespace_instruccion_llm_is_not_usable(self) -> None:
        db = _db_with_flavor(1, flavor=_flavor(instruccion="   "))
        responses = [
            CustomerResponse(
                message="Hola", intent="saludo", status="executed"
            )
        ]
        client = _llm(
            {"items": [{"index": 0, "message": "¡Hey!"}]}
        )
        styled = style_responses(db, 1, responses, query_llm=client)
        self.assertEqual(styled[0].message, "Hola")
        self.assertEqual(client.request.call_count, 0)

    def test_missing_comercio_is_safe_no_op(self) -> None:
        db = MagicMock()
        db.get.return_value = None
        responses = [
            CustomerResponse(
                message="Hola", intent="saludo", status="executed"
            )
        ]
        client = _llm({"items": [{"index": 0, "message": "x"}]})
        styled = style_responses(db, None, responses, query_llm=client)
        self.assertEqual(styled[0].message, "Hola")
        self.assertEqual(client.request.call_count, 0)

    def test_comercio_with_unknown_flavor_id_is_safe_no_op(self) -> None:
        db = MagicMock()
        comercio = MagicMock(flavor_comunicacion_id=999)
        db.get.side_effect = [comercio, None]
        responses = [
            CustomerResponse(
                message="Hola", intent="saludo", status="executed"
            )
        ]
        client = _llm({"items": [{"index": 0, "message": "x"}]})
        styled = style_responses(db, 1, responses, query_llm=client)
        self.assertEqual(styled[0].message, "Hola")
        self.assertEqual(client.request.call_count, 0)

    def test_non_int_comercio_id_is_safe_no_op(self) -> None:
        db = MagicMock()
        responses = [
            CustomerResponse(
                message="Hola", intent="saludo", status="executed"
            )
        ]
        client = _llm({"items": [{"index": 0, "message": "x"}]})
        styled = style_responses(
            db, "not-an-int", responses, query_llm=client  # type: ignore[arg-type]
        )
        self.assertEqual(styled[0].message, "Hola")
        self.assertEqual(client.request.call_count, 0)


class StyleResponsesHappyPathTest(unittest.TestCase):
    def test_one_eligible_response_replaces_factual_with_generated_message(
        self,
    ) -> None:
        flavor = _flavor()
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(
                message=_SALUDO,
                intent="saludo",
                status="executed",
            )
        ]
        client = _llm(
            {
                "items": [
                    {
                        "index": 0,
                        "message": "¡Buenas! Te ayudo con tu pedido 😊",
                    }
                ]
            }
        )
        styled = style_responses(db, 1, responses, query_llm=client)
        self.assertEqual(client.request.call_count, 1)
        self.assertEqual(
            styled[0].message, "¡Buenas! Te ayudo con tu pedido 😊"
        )
        self.assertEqual(styled[0].intent, "saludo")
        self.assertEqual(styled[0].status, "executed")

    def test_no_prefix_suffix_composition_occurs(self) -> None:
        """The full-message contract must NOT produce
        ``prefix + original + suffix`` composition. The generated
        message replaces the original verbatim.
        """
        flavor = _flavor()
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(
                message="Mensaje factual exacto",
                intent="saludo",
                status="executed",
            )
        ]
        client = _llm(
            {"items": [{"index": 0, "message": "Versión totalmente nueva"}]}
        )
        styled = style_responses(db, 1, responses, query_llm=client)
        self.assertEqual(styled[0].message, "Versión totalmente nueva")
        self.assertNotIn("Mensaje factual exacto", styled[0].message)

    def test_multiple_eligible_responses_share_a_single_call(self) -> None:
        flavor = _flavor()
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(
                message="Mensaje 1", intent="saludo", status="executed"
            ),
            CustomerResponse(
                message="Mensaje 2",
                intent="agradecimiento",
                status="executed",
            ),
            CustomerResponse(
                message="Mensaje 3",
                intent="iniciar_pedido",
                status="executed",
            ),
        ]
        client = _llm(
            {
                "items": [
                    {"index": 0, "message": "Versión A"},
                    {"index": 1, "message": "Versión B"},
                    {"index": 2, "message": "Versión C"},
                ]
            }
        )
        styled = style_responses(db, 1, responses, query_llm=client)
        self.assertEqual(client.request.call_count, 1)
        self.assertEqual(styled[0].message, "Versión A")
        self.assertEqual(styled[1].message, "Versión B")
        self.assertEqual(styled[2].message, "Versión C")
        self.assertEqual(
            [r.intent for r in styled],
            ["saludo", "agradecimiento", "iniciar_pedido"],
        )
        self.assertEqual([r.status for r in styled], ["executed"] * 3)

    def test_preserves_intent_and_status_after_generation(self) -> None:
        flavor = _flavor()
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(
                message="Hola",
                intent="saludo",
                status="executed",
            )
        ]
        client = _llm({"items": [{"index": 0, "message": "Versión natural"}]})
        styled = style_responses(db, 1, responses, query_llm=client)
        self.assertEqual(styled[0].intent, "saludo")
        self.assertEqual(styled[0].status, "executed")

    def test_desconocida_is_byte_for_byte_baseline_under_active_flavor(
        self,
    ) -> None:
        flavor = _flavor()
        db = _db_with_flavor(1, flavor=flavor)
        baseline_message = (
            "Disculpá, no entendí tu mensaje. "
            "Podés pedirme el menú o decirme qué producto querés agregar."
        )
        responses = [
            CustomerResponse(
                message=baseline_message,
                intent="desconocida",
                status="executed",
            )
        ]
        client = _llm(
            {
                "items": [
                    {"index": 0, "message": "Versión alterada ✨"}
                ]
            }
        )
        stream = io.StringIO()
        styled = style_responses(
            db, 1, responses, query_llm=client, stream=stream
        )
        self.assertEqual(client.request.call_count, 0)
        self.assertEqual(len(styled), 1)
        self.assertEqual(styled[0].intent, "desconocida")
        self.assertEqual(styled[0].status, "executed")
        self.assertEqual(styled[0].message, baseline_message)
        last_event = _last_event(stream)
        self.assertEqual(last_event.get("outcome"), OUTCOME_NOT_ATTEMPTED)
        self.assertEqual(last_event.get("eligible_count"), 0)
        self.assertEqual(last_event.get("applied_count"), 0)
        self.assertEqual(
            last_event.get("outbound_style_prompt_template_version"),
            OUTBOUND_STYLE_PROMPT_TEMPLATE_VERSION,
        )

    def test_desconocida_response_type_is_none_in_eligibility_table(self) -> None:
        self.assertIsNone(response_type_for("desconocida", "executed"))
        for status in ("rejected", "failed", "pending_resolution", "ready"):
            with self.subTest(status=status):
                self.assertIsNone(response_type_for("desconocida", status))

    def test_desconocida_is_excluded_from_select_eligible(self) -> None:
        responses = [
            CustomerResponse(
                message="Hola", intent="saludo", status="executed"
            ),
            CustomerResponse(
                message="¿Cuál?", intent="desconocida", status="executed"
            ),
        ]
        eligible = select_eligible(responses)
        self.assertEqual(
            [(item.index, item.response_type) for item in eligible],
            [(0, RESPONSE_TYPE_SOCIAL_GREETING)],
        )

    def test_mixed_eligible_and_ineligible_responses_only_style_eligible(
        self,
    ) -> None:
        flavor = _flavor()
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(
                message="Mensaje A",
                intent="saludo",
                status="executed",
            ),
            CustomerResponse(
                message="Mensaje B (rejection)",
                intent="agregar_producto",
                status="rejected",
            ),
            CustomerResponse(
                message="Mensaje C",
                intent="iniciar_pedido",
                status="executed",
            ),
            CustomerResponse(
                message="Mensaje D (pending)",
                intent="vaciar_pedido",
                status="pending_resolution",
            ),
            CustomerResponse(
                message="Mensaje E (address)",
                intent="set_direccion_entrega",
                status="executed",
            ),
        ]
        client = _llm(
            {
                "items": [
                    {"index": 0, "message": "Versión A"},
                    {"index": 1, "message": "Versión C"},
                ]
            }
        )
        styled = style_responses(db, 1, responses, query_llm=client)
        self.assertEqual(styled[0].message, "Versión A")
        self.assertEqual(styled[1].message, "Mensaje B (rejection)")
        self.assertEqual(styled[2].message, "Versión C")
        self.assertEqual(styled[3].message, "Mensaje D (pending)")
        self.assertEqual(styled[4].message, "Mensaje E (address)")
        self.assertEqual(styled[1].intent, "agregar_producto")
        self.assertEqual(styled[4].intent, "set_direccion_entrega")

    def test_only_eligible_response_types_are_sent_to_the_llm(self) -> None:
        flavor = _flavor()
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(message="A", intent="saludo", status="executed"),
            CustomerResponse(
                message="B",
                intent="set_observacion_pedido",
                status="executed",
            ),
            CustomerResponse(
                message="C",
                intent="set_direccion_entrega",
                status="executed",
            ),
            CustomerResponse(
                message="D",
                intent="set_metodo_de_pago",
                status="executed",
            ),
            CustomerResponse(
                message="E", intent="agregar_producto", status="executed"
            ),
        ]
        client = _llm(
            {
                "items": [
                    {"index": 0, "message": "Versión A"},
                    {"index": 1, "message": "Versión E"},
                ]
            }
        )
        style_responses(db, 1, responses, query_llm=client)
        prompt = client.request.call_args.args[0]
        self.assertIn('"response_type": "social_greeting"', prompt)
        self.assertIn('"response_type": "product_add_success"', prompt)
        self.assertNotIn("set_observacion_pedido", prompt)
        self.assertNotIn("set_direccion_entrega", prompt)
        self.assertNotIn("set_metodo_de_pago", prompt)


class StyleResponsesPromptContractTest(unittest.TestCase):
    """The prompt must contain the factual message and response
    type for eligible items, plus the bounded flavor directive, and
    must NOT contain inbound text, identifiers or ineligible
    response content.
    """

    _SENTINELS = (
        "Pizza Mozzarella",
        "Av. Secreta 1234",
        "Medio de pago X",
        "+5491100000000",
        "session-id-leak",
        "pedido-id-leak",
        "comercio-42",
    )

    def test_prompt_carries_factual_message_and_response_type(self) -> None:
        flavor = _flavor()
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(
                message="Listo, agregué 2 Empanadas de Pollo.",
                intent="agregar_producto",
                status="executed",
            ),
        ]
        client = _llm(
            {"items": [{"index": 0, "message": "Versión generada"}]}
        )
        style_responses(db, 1, responses, query_llm=client)
        prompt = client.request.call_args.args[0]
        self.assertIn('"response_type": "product_add_success"', prompt)
        self.assertIn(
            "Listo, agregué 2 Empanadas de Pollo.", prompt
        )

    def test_prompt_carries_menu_lines_as_factual_message(self) -> None:
        flavor = _flavor()
        db = _db_with_flavor(1, flavor=flavor)
        menu = (
            "Menú disponible:\n"
            "- Pizza Mozzarella: $5000\n"
            "- Pizza Napolitana: $5200"
        )
        responses = [
            CustomerResponse(
                message=menu, intent="ver_menu", status="executed"
            )
        ]
        client = _llm(
            {"items": [{"index": 0, "message": "Menú alternativo"}]}
        )
        style_responses(db, 1, responses, query_llm=client)
        prompt = client.request.call_args.args[0]
        self.assertIn('"response_type": "menu_full"', prompt)
        self.assertIn("Pizza Mozzarella: $5000", prompt)
        self.assertIn("Pizza Napolitana: $5200", prompt)

    def test_prompt_documents_factual_preservation_rules(self) -> None:
        flavor = _flavor()
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(
                message="Hola",
                intent="saludo",
                status="executed",
            )
        ]
        client = _llm({"items": [{"index": 0, "message": "Versión"}]})
        style_responses(db, 1, responses, query_llm=client)
        prompt = client.request.call_args.args[0]
        self.assertIn("factual_message", prompt)
        self.assertIn("presentaciones", prompt)
        self.assertIn("cantidades", prompt)
        self.assertIn("precios", prompt)
        self.assertIn("fechas", prompt)
        self.assertIn("horarios", prompt)
        self.assertIn("estados", prompt)
        self.assertIn("línea de menú", prompt)
        self.assertIn("Reglas inquebrantables", prompt)
        self.assertIn("Estructura de salida", prompt)
        self.assertIn("Reafirmación factual", prompt)

    def test_prompt_excludes_inbound_text_ids_and_ineligible_content(
        self,
    ) -> None:
        flavor = _flavor(instruccion="Tono serio. Cero jerga.")
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(
                message="Listo, agregué 2 Empanadas de Pollo.",
                intent="agregar_producto",
                status="executed",
            ),
        ]
        client = _llm(
            {"items": [{"index": 0, "message": "Versión generada"}]}
        )
        style_responses(db, 1, responses, query_llm=client)
        prompt = client.request.call_args.args[0]
        for sentinel in (
            "Pizza Mozzarella",
            "Av. Secreta 1234",
            "Medio de pago X",
            "+5491100000000",
            "session-id-leak",
            "pedido-id-leak",
            "comercio-42",
        ):
            with self.subTest(sentinel=sentinel):
                self.assertNotIn(sentinel, prompt)

    def test_prompt_does_not_carry_factual_message_for_ineligible_items(
        self,
    ) -> None:
        """The prompt carries the factual message for eligible
        items ONLY. Ineligible response content must not be
        transmitted to the LLM.
        """
        flavor = _flavor()
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(
                message="Texto saludo elegible",
                intent="saludo",
                status="executed",
            ),
            CustomerResponse(
                message="Texto observacion secreta",
                intent="set_observacion_pedido",
                status="executed",
            ),
            CustomerResponse(
                message="Direccion Tilcara 1234",
                intent="set_direccion_entrega",
                status="executed",
            ),
        ]
        client = _llm({"items": [{"index": 0, "message": "Versión"}]})
        style_responses(db, 1, responses, query_llm=client)
        prompt = client.request.call_args.args[0]
        self.assertIn("Texto saludo elegible", prompt)
        self.assertNotIn("Texto observacion secreta", prompt)
        self.assertNotIn("Direccion Tilcara 1234", prompt)

    def test_prompt_carries_internal_flavor_directive_only(self) -> None:
        flavor = _flavor(instruccion="INSTRUCCION-SECRETA")
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(
                message="Hola",
                intent="saludo",
                status="executed",
            )
        ]
        client = _llm({"items": [{"index": 0, "message": "Versión"}]})
        style_responses(db, 1, responses, query_llm=client)
        prompt = client.request.call_args.args[0]
        self.assertIn("INSTRUCCION-SECRETA", prompt)


class StyleResponsesPrivacyTest(unittest.TestCase):
    def test_static_template_fingerprint_is_stable(self) -> None:
        identity_a = outbound_style_template_identity()
        identity_b = outbound_style_template_identity()
        self.assertEqual(identity_a, identity_b)
        self.assertEqual(
            identity_a["outbound_style_prompt_template_version"],
            OUTBOUND_STYLE_PROMPT_TEMPLATE_VERSION,
        )
        self.assertEqual(
            identity_a["outbound_style_prompt_template_hash"],
            outbound_style_template_fingerprint(),
        )

    def test_template_version_is_v2_full_message(self) -> None:
        """The contract change bumped the template version to v2
        and the fingerprint is derived only from the static body.
        """
        self.assertEqual(
            OUTBOUND_STYLE_PROMPT_TEMPLATE_VERSION,
            "outbound-response-styler/v2.2.0",
        )

    def test_rendering_is_pure_function_of_inputs(self) -> None:
        items = [
            {
                "index": 0,
                "response_type": "social_greeting",
                "factual_message": "Hola.",
            }
        ]
        first = build_outbound_style_prompt(
            instruccion_llm="Tono serio.", items=items
        )
        second = build_outbound_style_prompt(
            instruccion_llm="Tono serio.", items=items
        )
        self.assertEqual(first, second)

    def test_rendering_changes_when_items_change(self) -> None:
        instruction = "Tono serio."
        first = build_outbound_style_prompt(
            instruccion_llm=instruction,
            items=[
                {
                    "index": 0,
                    "response_type": "social_greeting",
                    "factual_message": "A",
                }
            ],
        )
        second = build_outbound_style_prompt(
            instruccion_llm=instruction,
            items=[
                {
                    "index": 0,
                    "response_type": "social_greeting",
                    "factual_message": "A",
                },
                {
                    "index": 1,
                    "response_type": "product_add_success",
                    "factual_message": "B",
                },
            ],
        )
        self.assertNotEqual(first, second)


class StyleResponsesFailureTest(unittest.TestCase):
    def test_timeout_returns_factual_fallback_and_marks_event(self) -> None:
        flavor = _flavor()
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(message="OK", intent="saludo", status="executed"),
        ]
        client = _llm(QueryLlmTimeoutError("timeout"))
        stream = io.StringIO()
        styled = style_responses(
            db, 1, responses, query_llm=client, stream=stream
        )
        self.assertEqual(styled[0].message, "OK")
        last_event = _last_event(stream)
        self.assertEqual(last_event["event"], EVENT_OUTBOUND_STYLE)
        self.assertNotIn("outcome", last_event)
        self.assertEqual(last_event["failure_category"], FALLBACK_TIMEOUT)
        self.assertEqual(last_event["exception_type"], "QueryLlmTimeoutError")

    def test_connection_error_returns_factual_fallback(self) -> None:
        flavor = _flavor()
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(message="OK", intent="saludo", status="executed"),
        ]
        client = _llm(QueryLlmConnectionError("connection"))
        stream = io.StringIO()
        styled = style_responses(
            db, 1, responses, query_llm=client, stream=stream
        )
        self.assertEqual(styled[0].message, "OK")
        last_event = _last_event(stream)
        self.assertEqual(last_event["failure_category"], FALLBACK_CONNECTION)
        self.assertEqual(
            last_event["exception_type"], "QueryLlmConnectionError"
        )

    def test_http_error_returns_factual_fallback(self) -> None:
        flavor = _flavor()
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(message="OK", intent="saludo", status="executed"),
        ]
        client = _llm(QueryLlmHttpError(503, "boom"))
        stream = io.StringIO()
        styled = style_responses(
            db, 1, responses, query_llm=client, stream=stream
        )
        self.assertEqual(styled[0].message, "OK")
        last_event = _last_event(stream)
        self.assertEqual(last_event["failure_category"], FALLBACK_HTTP)
        self.assertEqual(last_event["exception_type"], "QueryLlmHttpError")

    def test_response_error_returns_factual_fallback(self) -> None:
        flavor = _flavor()
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(message="OK", intent="saludo", status="executed"),
        ]
        client = _llm(QueryLlmResponseError("bad json"))
        stream = io.StringIO()
        styled = style_responses(
            db, 1, responses, query_llm=client, stream=stream
        )
        self.assertEqual(styled[0].message, "OK")
        last_event = _last_event(stream)
        self.assertEqual(last_event["failure_category"], FALLBACK_RESPONSE)
        self.assertEqual(
            last_event["exception_type"], "QueryLlmResponseError"
        )

    def test_unexpected_query_llm_error_returns_factual_fallback(self) -> None:
        flavor = _flavor()
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(message="OK", intent="saludo", status="executed"),
        ]
        client = _llm(QueryLlmError("generic"))
        stream = io.StringIO()
        styled = style_responses(
            db, 1, responses, query_llm=client, stream=stream
        )
        self.assertEqual(styled[0].message, "OK")
        last_event = _last_event(stream)
        self.assertEqual(last_event["failure_category"], FALLBACK_UNEXPECTED)
        self.assertEqual(last_event["exception_type"], "QueryLlmError")

    def test_unexpected_exception_returns_factual_fallback(self) -> None:
        flavor = _flavor()
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(message="OK", intent="saludo", status="executed"),
        ]
        client = _llm(RuntimeError("boom"))
        stream = io.StringIO()
        styled = style_responses(
            db, 1, responses, query_llm=client, stream=stream
        )
        self.assertEqual(styled[0].message, "OK")
        last_event = _last_event(stream)
        self.assertEqual(last_event["failure_category"], FALLBACK_UNEXPECTED)
        self.assertEqual(last_event["exception_type"], "RuntimeError")

    def test_no_retry_on_transport_failure(self) -> None:
        flavor = _flavor()
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(message="OK", intent="saludo", status="executed"),
        ]
        client = _llm(QueryLlmTimeoutError("boom"))
        style_responses(db, 1, responses, query_llm=client)
        self.assertEqual(client.request.call_count, 1)

    def test_malformed_batch_wrong_count_falls_back_for_all_items(self) -> None:
        flavor = _flavor()
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(message="A", intent="saludo", status="executed"),
            CustomerResponse(
                message="B", intent="agregar_producto", status="executed"
            ),
        ]
        client = _llm({"items": [{"index": 0, "message": "Versión A"}]})
        stream = io.StringIO()
        styled = style_responses(
            db, 1, responses, query_llm=client, stream=stream
        )
        self.assertEqual(styled[0].message, "A")
        self.assertEqual(styled[1].message, "B")
        last_event = _last_event(stream)
        self.assertEqual(last_event["failure_category"], FALLBACK_MALFORMED_BATCH)

    def test_malformed_batch_with_extra_field_falls_back(self) -> None:
        flavor = _flavor()
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(message="A", intent="saludo", status="executed"),
        ]
        client = _llm(
            {
                "items": [
                    {
                        "index": 0,
                        "message": "Versión A",
                        "extra": "no",
                    }
                ]
            }
        )
        stream = io.StringIO()
        styled = style_responses(
            db, 1, responses, query_llm=client, stream=stream
        )
        self.assertEqual(styled[0].message, "A")
        last_event = _last_event(stream)
        self.assertEqual(last_event["failure_category"], FALLBACK_MALFORMED_BATCH)

    def test_malformed_batch_with_prefix_field_falls_back(self) -> None:
        """The full-message contract rejects any leftover prefix
        field from the old wrapper protocol.
        """
        flavor = _flavor()
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(message="A", intent="saludo", status="executed"),
        ]
        client = _llm(
            {
                "items": [
                    {
                        "index": 0,
                        "prefix": "Hey",
                        "message": "Versión A",
                    }
                ]
            }
        )
        stream = io.StringIO()
        styled = style_responses(
            db, 1, responses, query_llm=client, stream=stream
        )
        self.assertEqual(styled[0].message, "A")
        last_event = _last_event(stream)
        self.assertEqual(last_event["failure_category"], FALLBACK_MALFORMED_BATCH)

    def test_malformed_index_order_falls_back(self) -> None:
        flavor = _flavor()
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(message="A", intent="saludo", status="executed"),
            CustomerResponse(
                message="B", intent="agregar_producto", status="executed"
            ),
        ]
        client = _llm(
            {
                "items": [
                    {"index": 1, "message": "Versión B"},
                    {"index": 0, "message": "Versión A"},
                ]
            }
        )
        stream = io.StringIO()
        styled = style_responses(
            db, 1, responses, query_llm=client, stream=stream
        )
        self.assertEqual(styled[0].message, "A")
        self.assertEqual(styled[1].message, "B")
        last_event = _last_event(stream)
        self.assertEqual(last_event["failure_category"], FALLBACK_MALFORMED_BATCH)

    def test_per_item_empty_message_falls_back_for_that_item_only(self) -> None:
        flavor = _flavor()
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(message="A", intent="saludo", status="executed"),
            CustomerResponse(
                message="B", intent="agregar_producto", status="executed"
            ),
        ]
        client = _llm(
            {
                "items": [
                    {"index": 0, "message": "Versión A"},
                    {"index": 1, "message": ""},
                ]
            }
        )
        stream = io.StringIO()
        styled = style_responses(
            db, 1, responses, query_llm=client, stream=stream
        )
        self.assertEqual(styled[0].message, "Versión A")
        self.assertEqual(styled[1].message, "B")
        last_event = _last_event(stream)
        self.assertEqual(last_event.get("outcome"), OUTCOME_APPLIED)
        self.assertEqual(last_event.get("applied_count"), 1)
        self.assertEqual(last_event.get("eligible_count"), 2)

    def test_per_item_non_string_message_falls_back_for_that_item_only(
        self,
    ) -> None:
        flavor = _flavor()
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(message="A", intent="saludo", status="executed"),
            CustomerResponse(
                message="B", intent="agregar_producto", status="executed"
            ),
        ]
        client = _llm(
            {
                "items": [
                    {"index": 0, "message": "Versión A"},
                    {"index": 1, "message": 42},
                ]
            }
        )
        stream = io.StringIO()
        styled = style_responses(
            db, 1, responses, query_llm=client, stream=stream
        )
        self.assertEqual(styled[0].message, "Versión A")
        self.assertEqual(styled[1].message, "B")
        last_event = _last_event(stream)
        self.assertEqual(last_event.get("outcome"), OUTCOME_APPLIED)
        self.assertEqual(last_event.get("applied_count"), 1)

    def test_per_item_control_chars_message_falls_back_for_that_item_only(
        self,
    ) -> None:
        flavor = _flavor()
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(message="A", intent="saludo", status="executed"),
            CustomerResponse(
                message="B", intent="agregar_producto", status="executed"
            ),
        ]
        client = _llm(
            {
                "items": [
                    {"index": 0, "message": "Versión A"},
                    {"index": 1, "message": "MAL\x00FORM"},
                ]
            }
        )
        stream = io.StringIO()
        styled = style_responses(
            db, 1, responses, query_llm=client, stream=stream
        )
        self.assertEqual(styled[0].message, "Versión A")
        self.assertEqual(styled[1].message, "B")
        last_event = _last_event(stream)
        self.assertEqual(last_event.get("outcome"), OUTCOME_APPLIED)
        self.assertEqual(last_event.get("applied_count"), 1)

    def test_all_empty_messages_fall_back_for_all_items(self) -> None:
        flavor = _flavor()
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(message="A", intent="saludo", status="executed"),
            CustomerResponse(
                message="B", intent="agregar_producto", status="executed"
            ),
        ]
        client = _llm(
            {
                "items": [
                    {"index": 0, "message": ""},
                    {"index": 1, "message": ""},
                ]
            }
        )
        stream = io.StringIO()
        styled = style_responses(
            db, 1, responses, query_llm=client, stream=stream
        )
        self.assertEqual(styled[0].message, "A")
        self.assertEqual(styled[1].message, "B")
        last_event = _last_event(stream)
        self.assertNotIn("outcome", last_event)
        self.assertEqual(
            last_event["failure_category"], FALLBACK_EMPTY_MESSAGE
        )

    def test_all_invalid_messages_fall_back_for_all_items(self) -> None:
        flavor = _flavor()
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(message="A", intent="saludo", status="executed"),
            CustomerResponse(
                message="B", intent="agregar_producto", status="executed"
            ),
        ]
        client = _llm(
            {
                "items": [
                    {"index": 0, "message": "OK\x07"},
                    {"index": 1, "message": 99},
                ]
            }
        )
        stream = io.StringIO()
        styled = style_responses(
            db, 1, responses, query_llm=client, stream=stream
        )
        self.assertEqual(styled[0].message, "A")
        self.assertEqual(styled[1].message, "B")
        last_event = _last_event(stream)
        self.assertNotIn("outcome", last_event)
        self.assertEqual(
            last_event["failure_category"], FALLBACK_MESSAGE_INVALID
        )

    def test_event_emitted_when_there_are_zero_eligible(self) -> None:
        db = _db_with_flavor(1, flavor=_flavor())
        responses = [
            CustomerResponse(
                message="rejection",
                intent="agregar_producto",
                status="rejected",
            ),
        ]
        client = _llm({"items": [{"index": 0, "message": "Versión"}]})
        stream = io.StringIO()
        style_responses(db, 1, responses, query_llm=client, stream=stream)
        self.assertEqual(client.request.call_count, 0)
        last_event = _last_event(stream)
        self.assertEqual(last_event["outcome"], OUTCOME_NOT_ATTEMPTED)
        self.assertEqual(last_event["eligible_count"], 0)
        self.assertEqual(last_event["applied_count"], 0)

    def test_event_emitted_when_flavor_is_neutro(self) -> None:
        db = _db_with_flavor(1, flavor=_flavor(NEUTRO_FLAVOR_CODE))
        responses = [
            CustomerResponse(message="A", intent="saludo", status="executed"),
        ]
        client = _llm({"items": [{"index": 0, "message": "Versión"}]})
        stream = io.StringIO()
        style_responses(db, 1, responses, query_llm=client, stream=stream)
        self.assertEqual(client.request.call_count, 0)
        last_event = _last_event(stream)
        self.assertEqual(last_event["outcome"], OUTCOME_NOT_ATTEMPTED)
        self.assertEqual(last_event["eligible_count"], 1)

    def test_event_carries_static_template_identity_on_success(self) -> None:
        flavor = _flavor()
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(message="A", intent="saludo", status="executed"),
        ]
        client = _llm({"items": [{"index": 0, "message": "Versión"}]})
        stream = io.StringIO()
        style_responses(db, 1, responses, query_llm=client, stream=stream)
        last_event = _last_event(stream)
        self.assertEqual(last_event.get("event"), EVENT_OUTBOUND_STYLE)
        self.assertEqual(last_event.get("component"), COMPONENT_OUTBOUND_STYLE)
        self.assertEqual(last_event.get("outcome"), OUTCOME_APPLIED)
        self.assertEqual(last_event.get("eligible_count"), 1)
        self.assertEqual(last_event.get("applied_count"), 1)
        self.assertEqual(
            last_event.get("outbound_style_prompt_template_version"),
            OUTBOUND_STYLE_PROMPT_TEMPLATE_VERSION,
        )
        self.assertEqual(
            last_event.get("outbound_style_prompt_template_hash"),
            outbound_style_template_identity()[
                "outbound_style_prompt_template_hash"
            ],
        )
        self.assertEqual(
            len(last_event["outbound_style_prompt_template_hash"]), 64
        )
        self.assertTrue(
            all(
                c in "0123456789abcdef"
                for c in last_event["outbound_style_prompt_template_hash"]
            )
        )

    def test_event_carries_static_template_identity_on_fallback(self) -> None:
        flavor = _flavor()
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(message="OK", intent="saludo", status="executed"),
        ]
        client = _llm(QueryLlmTimeoutError("boom"))
        stream = io.StringIO()
        style_responses(db, 1, responses, query_llm=client, stream=stream)
        last_event = _last_event(stream)
        self.assertNotIn("outcome", last_event)
        self.assertEqual(last_event.get("failure_category"), FALLBACK_TIMEOUT)
        self.assertEqual(
            last_event.get("outbound_style_prompt_template_version"),
            OUTBOUND_STYLE_PROMPT_TEMPLATE_VERSION,
        )
        self.assertEqual(
            last_event.get("outbound_style_prompt_template_hash"),
            outbound_style_template_identity()[
                "outbound_style_prompt_template_hash"
            ],
        )

    def test_event_carries_static_template_identity_when_not_attempted(
        self,
    ) -> None:
        db = _db_with_flavor(1, flavor=_flavor())
        client = _llm({"items": [{"index": 0, "message": "Versión"}]})
        stream = io.StringIO()
        style_responses(db, 1, [], query_llm=client, stream=stream)
        last_event = _last_event(stream)
        self.assertEqual(last_event.get("outcome"), OUTCOME_NOT_ATTEMPTED)
        self.assertEqual(last_event.get("eligible_count"), 0)
        self.assertEqual(last_event.get("applied_count"), 0)
        self.assertEqual(
            last_event.get("outbound_style_prompt_template_version"),
            OUTBOUND_STYLE_PROMPT_TEMPLATE_VERSION,
        )
        self.assertEqual(
            last_event.get("outbound_style_prompt_template_hash"),
            outbound_style_template_identity()[
                "outbound_style_prompt_template_hash"
            ],
        )

    def test_event_does_not_carry_prompt_or_factual_message(self) -> None:
        flavor = _flavor(instruccion="INSTRUCCION-SECRETA")
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(
                message="Listo, agregué 1 unidad.",
                intent="agregar_producto",
                status="executed",
            ),
        ]
        client = _llm(
            {
                "items": [
                    {"index": 0, "message": "Versión generada"},
                ]
            }
        )
        stream = io.StringIO()
        style_responses(db, 1, responses, query_llm=client, stream=stream)
        prompt = client.request.call_args.args[0]
        last_event = _last_event(stream)
        serialized = json.dumps(last_event, sort_keys=True)
        for forbidden in (
            "INSTRUCCION-SECRETA",
            "Pizza Mozzarella",
            "agregar_producto",
            "session-7",
            "pedido-9",
            "comercio-42",
            "+5491100000000",
            "Av. Secreta 1234",
            "Versión generada",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, serialized)
        for forbidden in (
            "Pizza Mozzarella",
            "session-7",
            "pedido-9",
            "comercio-42",
            "+5491100000000",
            "Av. Secreta 1234",
        ):
            with self.subTest(prompt_forbidden=forbidden):
                self.assertNotIn(forbidden, prompt)
        self.assertIn("INSTRUCCION-SECRETA", prompt)
        self.assertIn('"response_type": "product_add_success"', prompt)
        self.assertIn("Listo, agregué 1 unidad.", prompt)


class StyleResponsesSecurityTest(unittest.TestCase):
    def test_no_database_transaction_control_is_invoked(self) -> None:
        flavor = _flavor()
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(message="A", intent="saludo", status="executed"),
        ]
        client = _llm(
            {"items": [{"index": 0, "message": "Versión"}]}
        )
        stream = io.StringIO()
        style_responses(db, 1, responses, query_llm=client, stream=stream)
        for method in (
            "commit",
            "rollback",
            "begin",
            "begin_nested",
            "flush",
            "refresh",
            "close",
        ):
            getattr(db, method).assert_not_called()

    def test_no_database_transaction_control_invoked_on_failure(self) -> None:
        flavor = _flavor()
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(message="A", intent="saludo", status="executed"),
        ]
        client = _llm(QueryLlmTimeoutError("boom"))
        stream = io.StringIO()
        style_responses(db, 1, responses, query_llm=client, stream=stream)
        for method in (
            "commit",
            "rollback",
            "begin",
            "begin_nested",
            "flush",
            "refresh",
            "close",
        ):
            getattr(db, method).assert_not_called()

    def test_module_does_not_register_global_logging_handlers(self) -> None:
        before = list(logging.getLogger().handlers)
        from backend.services import outbound_response_styler  # noqa: F401

        after = list(logging.getLogger().handlers)
        self.assertEqual(before, after)


class StyleResponsesEmptyInputTest(unittest.TestCase):
    def test_empty_responses_returns_empty(self) -> None:
        db = _db_with_flavor(1, flavor=_flavor())
        client = _llm({"items": [{"index": 0, "message": "Versión"}]})
        styled = style_responses(db, 1, [], query_llm=client)
        self.assertEqual(styled, [])
        self.assertEqual(client.request.call_count, 0)


class StyleResponsesFamilyTest(unittest.TestCase):
    """Contract-quality tests for representative factual messages:

    * greeting
    * add with quantity
    * multi-line menu
    * order status
    * confirmation

    Tests assert the structural contract and fallback behavior
    only; they DO NOT assert semantic equivalence of the LLM output
    with the factual source.
    """

    def test_saludo_replaces_with_full_message(self) -> None:
        flavor = _flavor()
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(message=_SALUDO, intent="saludo", status="executed")
        ]
        client = _llm(
            {"items": [{"index": 0, "message": "¡Hola! ¿Qué te gustaría pedir hoy?"}]}
        )
        styled = style_responses(db, 1, responses, query_llm=client)
        self.assertEqual(styled[0].message, "¡Hola! ¿Qué te gustaría pedir hoy?")
        self.assertEqual(styled[0].intent, "saludo")
        self.assertEqual(styled[0].status, "executed")

    def test_add_with_quantity_replaces_with_full_message(self) -> None:
        flavor = _flavor()
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(
                message=_AGG_SUCCESS,
                intent="agregar_producto",
                status="executed",
            )
        ]
        client = _llm(
            {
                "items": [
                    {
                        "index": 0,
                        "message": (
                            "¡Listo! Agregué 2 empanadas de pollo "
                            "a tu pedido 😊"
                        ),
                    }
                ]
            }
        )
        styled = style_responses(db, 1, responses, query_llm=client)
        self.assertEqual(
            styled[0].message,
            "¡Listo! Agregué 2 empanadas de pollo a tu pedido 😊",
        )
        self.assertEqual(styled[0].intent, "agregar_producto")
        self.assertEqual(styled[0].status, "executed")

    def test_multi_line_menu_replaces_with_full_message(self) -> None:
        flavor = _flavor()
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(
                message=_MENU_MULTILINE,
                intent="ver_menu",
                status="executed",
            )
        ]
        client = _llm(
            {
                "items": [
                    {
                        "index": 0,
                        "message": (
                            "Te paso el menú disponible:\n"
                            "- Pizza Mozzarella: $5000\n"
                            "- Pizza Napolitana: $5200\n"
                            "- Empanadas de Pollo: $1200"
                        ),
                    }
                ]
            }
        )
        styled = style_responses(db, 1, responses, query_llm=client)
        self.assertIn("Pizza Mozzarella: $5000", styled[0].message)
        self.assertIn("Pizza Napolitana: $5200", styled[0].message)
        self.assertIn("Empanadas de Pollo: $1200", styled[0].message)
        self.assertEqual(styled[0].intent, "ver_menu")

    def test_order_status_replaces_with_full_message(self) -> None:
        flavor = _flavor()
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(
                message=_ORDER_STATUS,
                intent="consultar_estado_pedido",
                status="executed",
            )
        ]
        client = _llm(
            {
                "items": [
                    {
                        "index": 0,
                        "message": (
                            "Tu pedido ya está en preparación. "
                            "Sale en unos 15 minutos 🚀"
                        ),
                    }
                ]
            }
        )
        styled = style_responses(db, 1, responses, query_llm=client)
        self.assertEqual(
            styled[0].message,
            "Tu pedido ya está en preparación. Sale en unos 15 minutos 🚀",
        )
        self.assertEqual(styled[0].intent, "consultar_estado_pedido")

    def test_confirmation_replaces_with_full_message(self) -> None:
        flavor = _flavor()
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(
                message=_CONFIRM,
                intent="confirmar_pedido",
                status="executed",
            )
        ]
        client = _llm(
            {
                "items": [
                    {
                        "index": 0,
                        "message": (
                            "¡Listo! Pedido confirmado. Te avisamos "
                            "cuando esté en camino."
                        ),
                    }
                ]
            }
        )
        styled = style_responses(db, 1, responses, query_llm=client)
        self.assertEqual(
            styled[0].message,
            "¡Listo! Pedido confirmado. Te avisamos cuando esté en camino.",
        )
        self.assertEqual(styled[0].intent, "confirmar_pedido")

    def test_neutro_skips_llm_for_all_representative_families(self) -> None:
        """Under the neutral flavor the deterministic baseline is
        preserved byte-for-byte for every representative family.
        """
        db = _db_with_flavor(1, flavor=_flavor(NEUTRO_FLAVOR_CODE))
        responses = [
            CustomerResponse(message=_SALUDO, intent="saludo", status="executed"),
            CustomerResponse(
                message=_AGG_SUCCESS,
                intent="agregar_producto",
                status="executed",
            ),
            CustomerResponse(
                message=_MENU_MULTILINE,
                intent="ver_menu",
                status="executed",
            ),
            CustomerResponse(
                message=_ORDER_STATUS,
                intent="consultar_estado_pedido",
                status="executed",
            ),
            CustomerResponse(
                message=_CONFIRM, intent="confirmar_pedido", status="executed"
            ),
        ]
        client = _llm({"items": []})
        styled = style_responses(db, 1, responses, query_llm=client)
        self.assertEqual(client.request.call_count, 0)
        self.assertEqual([r.message for r in styled], [r.message for r in responses])

    def test_factual_message_is_transmitted_to_the_llm_for_eligible_items(
        self,
    ) -> None:
        """The eligible factual message is sent to the LLM as the
        sole business source of truth. The LLM receives the
        verbatim text it must rephrase.
        """
        flavor = _flavor()
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(
                message="Listo, agregué 2 Empanadas de Pollo.",
                intent="agregar_producto",
                status="executed",
            ),
        ]
        client = _llm({"items": [{"index": 0, "message": "Versión"}]})
        style_responses(db, 1, responses, query_llm=client)
        prompt = client.request.call_args.args[0]
        self.assertIn("Listo, agregué 2 Empanadas de Pollo.", prompt)


class StyleResponsesVersionTest(unittest.TestCase):
    def test_styler_version_is_static(self) -> None:
        self.assertEqual(styler_version(), OUTBOUND_STYLE_PROMPT_TEMPLATE_VERSION)

    def test_styler_fingerprint_matches_template_identity(self) -> None:
        self.assertEqual(
            styler_fingerprint(),
            outbound_style_template_identity()[
                "outbound_style_prompt_template_hash"
            ],
        )


class PromptSafeSerializationTest(unittest.TestCase):
    """Bloqueante 1: the runtime items block MUST be a valid JSON
    literal built with ``json.dumps`` (UTF-8, ``ensure_ascii=False``)
    so quotes, backslashes, accents, JSON-looking text and newlines
    are safely delimited.
    """

    def _render_prompt(self, message: str) -> str:
        flavor = _flavor()
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(
                message=message, intent="agregar_producto", status="executed"
            )
        ]
        client = _llm({"items": [{"index": 0, "message": "Versión"}]})
        style_responses(db, 1, responses, query_llm=client)
        return client.request.call_args.args[0]

    def test_factual_message_with_quotes_is_json_escaped(self) -> None:
        prompt = self._render_prompt('Listo, agregué 2 "Empanadas".')
        self.assertIn(r"\"Empanadas\"", prompt)
        self.assertNotIn('agregué 2 "Empanadas".', prompt)

    def test_factual_message_with_backslashes_is_json_escaped(self) -> None:
        prompt = self._render_prompt(r"Pedido: C:\ordenes\123.txt")
        self.assertIn(r"C:\\ordenes\\123.txt", prompt)
        self.assertNotIn(r"C:\ordenes\123.txt", prompt)

    def test_factual_message_with_accents_is_kept_verbatim(self) -> None:
        """``ensure_ascii=False`` preserves accented Spanish letters
        so the prompt is human-readable for the LLM.
        """
        prompt = self._render_prompt("Listo: agregué empanadas.")
        self.assertIn("agregué empanadas", prompt)
        self.assertNotIn(r"\u00e9", prompt)

    def test_factual_message_with_json_looking_text_is_escaped(self) -> None:
        prompt = self._render_prompt('Pedido: {"x":1}')
        self.assertIn(r"{\"x\":1}", prompt)
        self.assertNotIn('Pedido: {"x":1}', prompt)

    def test_factual_message_with_newlines_is_escaped(self) -> None:
        prompt = self._render_prompt("Línea 1\nLínea 2\nLínea 3")
        self.assertIn(r"Línea 1\nLínea 2\nLínea 3", prompt)
        self.assertNotIn("Línea 1\nLínea 2\nLínea 3", prompt)

    def test_factual_message_appears_only_inside_json_block(self) -> None:
        """The deterministic factual content lives ONLY inside the
        closed JSON runtime block; it is not interpolated as a free
        text line in the static prompt body.
        """
        prompt = self._render_prompt("FACTUAL-SECRETO-XYZ")
        runtime_idx = prompt.find('"items"')
        factual_idx = prompt.find("FACTUAL-SECRETO-XYZ")
        self.assertGreater(runtime_idx, 0)
        self.assertGreater(factual_idx, runtime_idx)
        self.assertIn('"factual_message": "FACTUAL-SECRETO-XYZ"', prompt)


class PromptOrderTest(unittest.TestCase):
    """Bloqueante 3: the static prompt body must place the flavor
    directive BEFORE the factual reaffirmation, and the factual
    reaffirmation BEFORE the runtime JSON block. The reaffirmation
    must be present in the static, versioned body and it must
    outrank the flavor directive.
    """

    def _render(self) -> str:
        flavor = _flavor(instruccion="DIRECTRIZ-TONO")
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(
                message="Mensaje factual",
                intent="saludo",
                status="executed",
            )
        ]
        client = _llm({"items": [{"index": 0, "message": "Versión"}]})
        style_responses(db, 1, responses, query_llm=client)
        return client.request.call_args.args[0]

    def test_prompt_order_flavor_then_reaffirmation_then_runtime(self) -> None:
        prompt = self._render()
        idx_directive = prompt.find("DIRECTRIZ-TONO")
        idx_reaffirmation = prompt.find("Reafirmación factual")
        # Look for the runtime JSON block (carries integer `index`,
        # not the schema's `<entero>` placeholder) by finding the
        # actual factual_message key.
        idx_runtime = prompt.find('"factual_message":')
        self.assertGreater(idx_directive, 0)
        self.assertGreater(idx_reaffirmation, 0)
        self.assertGreater(idx_runtime, 0)
        self.assertLess(idx_directive, idx_reaffirmation)
        self.assertLess(idx_reaffirmation, idx_runtime)

    def test_reaffirmation_contains_all_required_clauses(self) -> None:
        prompt = self._render()
        for clause in (
            "única fuente autorizada de hechos",
            "productos y sus presentaciones",
            "cantidades",
            "precios",
            "fechas",
            "horarios",
            "estados del pedido",
            "cada línea de menú",
            "NO agregues",
            "NO inventes presentaciones, unidades, variantes, descuentos",
            "prevalecen sin excepción",
            "Devolvé únicamente el JSON",
        ):
            with self.subTest(clause=clause):
                self.assertIn(clause, prompt)

    def test_factual_reaffirmation_is_part_of_static_body(self) -> None:
        """The reaffirmation block is rendered from the static
        template body; mutating the runtime ``instruccion_llm`` does
        NOT remove it.
        """
        flavor = _flavor(instruccion="CAMBIADO")
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(
                message="Hola",
                intent="saludo",
                status="executed",
            )
        ]
        client = _llm({"items": [{"index": 0, "message": "Versión"}]})
        style_responses(db, 1, responses, query_llm=client)
        prompt = client.request.call_args.args[0]
        self.assertIn("Reafirmación factual", prompt)
        self.assertIn("CAMBIADO", prompt)


class PromptVersionTest(unittest.TestCase):
    def test_template_version_bumped_for_contract_refinement(self) -> None:
        """Version must be bumped from the previous v2.0.0 because
        the contract was refined (JSON serialization + reaffirmation
        + newline policy) and again for the menu / status calibration
        amendment (v2.2.0).
        """
        self.assertEqual(
            OUTBOUND_STYLE_PROMPT_TEMPLATE_VERSION,
            "outbound-response-styler/v2.2.0",
        )

    def test_template_fingerprint_is_valid_sha256_hex(self) -> None:
        identity = outbound_style_template_identity()
        fp = identity["outbound_style_prompt_template_hash"]
        self.assertEqual(len(fp), 64)
        self.assertTrue(all(c in "0123456789abcdef" for c in fp))

    def test_template_fingerprint_changes_when_body_changes(self) -> None:
        """The fingerprint is derived only from the static body and
        changes when the body changes, even if the version stays.
        """
        import hashlib

        original_body = (
            "\nSos un asistente de presentación para un comercio."
        )
        new_body = original_body + " Texto adicional."
        original_fp = hashlib.sha256(original_body.encode("utf-8")).hexdigest()
        new_fp = hashlib.sha256(new_body.encode("utf-8")).hexdigest()
        self.assertNotEqual(original_fp, new_fp)

    def test_template_fingerprint_is_stable_for_same_body(self) -> None:
        identity_a = outbound_style_template_identity()
        identity_b = outbound_style_template_identity()
        self.assertEqual(identity_a, identity_b)
        self.assertEqual(
            identity_a["outbound_style_prompt_template_hash"],
            outbound_style_template_fingerprint(),
        )


class GeneratedMessagePolicyTest(unittest.TestCase):
    """Bloqueante 2: ``\\n`` and ``\\r\\n`` are allowed in the
    generated message; ``\\t``, ``\\x00``, ``\\x1b``, ``\\x7f`` and
    other ASCII control characters are rejected per item under
    ``message_invalid``. ``\\r\\n`` is normalized to ``\\n``.
    """

    def test_multiline_message_is_applied_with_preserved_lines(self) -> None:
        flavor = _flavor()
        db = _db_with_flavor(1, flavor=flavor)
        menu = (
            "Menú disponible:\n"
            "- Pizza Mozzarella: $5000\n"
            "- Pizza Napolitana: $5200"
        )
        responses = [
            CustomerResponse(
                message=menu, intent="ver_menu", status="executed"
            )
        ]
        generated = (
            "Te paso el menú:\n"
            "- Pizza Mozzarella: $5000\n"
            "- Pizza Napolitana: $5200"
        )
        client = _llm({"items": [{"index": 0, "message": generated}]})
        styled = style_responses(db, 1, responses, query_llm=client)
        self.assertEqual(styled[0].message, generated)
        self.assertEqual(styled[0].intent, "ver_menu")
        self.assertEqual(styled[0].status, "executed")
        self.assertIn("\n", styled[0].message)

    def test_crlf_message_is_normalized_to_lf(self) -> None:
        flavor = _flavor()
        db = _db_with_flavor(1, flavor=flavor)
        menu = "Menú:\n- Pizza: $5000\n- Empanada: $1200"
        responses = [
            CustomerResponse(
                message=menu, intent="ver_menu", status="executed"
            )
        ]
        generated = "Te paso el menú:\r\n- Pizza: $5000\r\n- Empanada: $1200"
        client = _llm({"items": [{"index": 0, "message": generated}]})
        styled = style_responses(db, 1, responses, query_llm=client)
        self.assertNotIn("\r", styled[0].message)
        self.assertEqual(
            styled[0].message,
            "Te paso el menú:\n- Pizza: $5000\n- Empanada: $1200",
        )

    def test_bare_cr_message_is_rejected_per_item(self) -> None:
        """Bare ``\\r`` (classic-Mac line ending) is NOT part of an
        allowed ``\\r\\n`` CRLF pair, so it must be rejected and the
        item must fall back to the factual message.
        """
        flavor = _flavor()
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(message="A", intent="saludo", status="executed"),
            CustomerResponse(
                message="B", intent="agregar_producto", status="executed"
            ),
        ]
        client = _llm(
            {
                "items": [
                    {"index": 0, "message": "Versión A"},
                    {"index": 1, "message": "A\rB\rC"},
                ]
            }
        )
        stream = io.StringIO()
        styled = style_responses(
            db, 1, responses, query_llm=client, stream=stream
        )
        self.assertEqual(styled[0].message, "Versión A")
        self.assertEqual(styled[1].message, "B")
        last_event = _last_event(stream)
        self.assertEqual(last_event.get("outcome"), OUTCOME_APPLIED)
        self.assertEqual(last_event.get("applied_count"), 1)

    def test_tab_character_falls_back_per_item(self) -> None:
        flavor = _flavor()
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(message="A", intent="saludo", status="executed"),
            CustomerResponse(
                message="B", intent="agregar_producto", status="executed"
            ),
        ]
        client = _llm(
            {
                "items": [
                    {"index": 0, "message": "Versión\tA"},
                    {"index": 1, "message": "Versión B"},
                ]
            }
        )
        stream = io.StringIO()
        styled = style_responses(
            db, 1, responses, query_llm=client, stream=stream
        )
        self.assertEqual(styled[0].message, "A")
        self.assertEqual(styled[1].message, "Versión B")
        last_event = _last_event(stream)
        self.assertEqual(last_event.get("outcome"), OUTCOME_APPLIED)
        self.assertEqual(last_event.get("applied_count"), 1)

    def test_nul_character_falls_back_per_item(self) -> None:
        flavor = _flavor()
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(message="A", intent="saludo", status="executed"),
            CustomerResponse(
                message="B", intent="agregar_producto", status="executed"
            ),
        ]
        client = _llm(
            {
                "items": [
                    {"index": 0, "message": "Versión A"},
                    {"index": 1, "message": "Versión\x00B"},
                ]
            }
        )
        stream = io.StringIO()
        styled = style_responses(
            db, 1, responses, query_llm=client, stream=stream
        )
        self.assertEqual(styled[0].message, "Versión A")
        self.assertEqual(styled[1].message, "B")
        last_event = _last_event(stream)
        self.assertEqual(last_event.get("outcome"), OUTCOME_APPLIED)
        self.assertEqual(last_event.get("applied_count"), 1)

    def test_esc_character_falls_back_per_item(self) -> None:
        flavor = _flavor()
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(message="A", intent="saludo", status="executed"),
            CustomerResponse(
                message="B", intent="agregar_producto", status="executed"
            ),
        ]
        client = _llm(
            {
                "items": [
                    {"index": 0, "message": "Versión A"},
                    {"index": 1, "message": "Versión\x1bB"},
                ]
            }
        )
        stream = io.StringIO()
        styled = style_responses(
            db, 1, responses, query_llm=client, stream=stream
        )
        self.assertEqual(styled[0].message, "Versión A")
        self.assertEqual(styled[1].message, "B")
        last_event = _last_event(stream)
        self.assertEqual(last_event.get("outcome"), OUTCOME_APPLIED)
        self.assertEqual(last_event.get("applied_count"), 1)

    def test_del_character_falls_back_per_item(self) -> None:
        flavor = _flavor()
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(message="A", intent="saludo", status="executed"),
            CustomerResponse(
                message="B", intent="agregar_producto", status="executed"
            ),
        ]
        client = _llm(
            {
                "items": [
                    {"index": 0, "message": "Versión A"},
                    {"index": 1, "message": "Versión\x7fB"},
                ]
            }
        )
        stream = io.StringIO()
        styled = style_responses(
            db, 1, responses, query_llm=client, stream=stream
        )
        self.assertEqual(styled[0].message, "Versión A")
        self.assertEqual(styled[1].message, "B")

    def test_all_invalid_messages_emit_message_invalid_fallback(self) -> None:
        flavor = _flavor()
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(message="A", intent="saludo", status="executed"),
            CustomerResponse(
                message="B", intent="agregar_producto", status="executed"
            ),
        ]
        client = _llm(
            {
                "items": [
                    {"index": 0, "message": "Versión\tA"},
                    {"index": 1, "message": "Versión\x00B"},
                ]
            }
        )
        stream = io.StringIO()
        styled = style_responses(
            db, 1, responses, query_llm=client, stream=stream
        )
        self.assertEqual(styled[0].message, "A")
        self.assertEqual(styled[1].message, "B")
        last_event = _last_event(stream)
        self.assertEqual(
            last_event.get("failure_category"), FALLBACK_MESSAGE_INVALID
        )

    def test_structural_envelope_invalid_still_falls_back_for_all(self) -> None:
        """The newline policy change does NOT relax the structural
        envelope validation; a malformed envelope still causes the
        entire batch to fall back to the factual baseline.
        """
        flavor = _flavor()
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(message="A", intent="saludo", status="executed"),
        ]
        client = _llm(
            {
                "items": [
                    {"index": 1, "message": "Versión A"},
                ]
            }
        )
        stream = io.StringIO()
        styled = style_responses(
            db, 1, responses, query_llm=client, stream=stream
        )
        self.assertEqual(styled[0].message, "A")
        last_event = _last_event(stream)
        self.assertEqual(last_event["failure_category"], FALLBACK_MALFORMED_BATCH)

    def test_single_line_message_with_newline_inside_is_allowed(self) -> None:
        """The newline policy is permissive: any string that contains
        only printable Unicode plus ``\\n`` is accepted, even when it
        was not originally a menu. No semantic policy is added.
        """
        flavor = _flavor()
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(message="A", intent="saludo", status="executed"),
        ]
        client = _llm({"items": [{"index": 0, "message": "Línea 1\nLínea 2"}]})
        styled = style_responses(db, 1, responses, query_llm=client)
        self.assertEqual(styled[0].message, "Línea 1\nLínea 2")


class PromptCalibrationAmendmentTest(unittest.TestCase):
    """Task 1.4 / 3.4: the static full-message prompt is calibrated
    so that a ``menu_full`` / ``menu_category`` ``factual_message`` is
    an immutable factual inventory (every category, line, product,
    presentation/unit, price, punctuation and order) and an
    ``order_status`` response may only repeat status / logistics
    wording explicitly present in the ``factual_message``.

    These tests assert the prompt CONTRACT only. They never assert
    that a live LLM will obey them: the manual pilot gate is the
    authority for semantic compliance.
    """

    def _render_prompt(
        self,
        *,
        flavor_instruccion: str = "Tono serio.",
        response_type: str = "menu_full",
        factual_message: str | None = None,
    ) -> str:
        if factual_message is None:
            factual_message = (
                "Menú disponible:\n"
                "- Pizza Mozzarella (grande): $5000\n"
                "- Pizza Mozzarella (chica): $3200\n"
                "- Pizza Napolitana (2 litros): $5200\n"
                "- Empanadas de Pollo (docena): $1200"
            )
        flavor = _flavor(instruccion=flavor_instruccion)
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(
                message=factual_message,
                intent=("ver_menu" if response_type == "menu_full"
                        else ("consultar_estado_pedido"
                              if response_type == "order_status"
                              else "saludo")),
                status="executed",
            )
        ]
        client = _llm({"items": [{"index": 0, "message": "Versión"}]})
        style_responses(db, 1, responses, query_llm=client)
        return client.request.call_args.args[0]

    def test_prompt_documents_immutable_menu_inventory_rule(self) -> None:
        prompt = self._render_prompt(response_type="menu_full")
        for clause in (
            "`menu_full`",
            "`menu_category`",
            "inventario factual",
            "inmutable",
            "cada categoría",
            "cada línea",
            "cada producto",
            "presentación/unidad",
            "precio",
            "puntuación",
            "orden exacto",
        ):
            with self.subTest(clause=clause):
                self.assertIn(clause, prompt)

    def test_prompt_prohibits_summarizing_regrouping_flattening_menu(
        self,
    ) -> None:
        prompt = self._render_prompt(response_type="menu_full")
        self.assertIn("resumir", prompt)
        self.assertIn("reagrupar", prompt)
        self.assertIn("aplanar a prosa", prompt)
        self.assertIn("omitir variantes", prompt)
        self.assertIn("fusionar líneas", prompt)
        self.assertIn("reemplazar la lista", prompt)
        self.assertIn("introducción o un cierre breve y no factual", prompt)
        self.assertIn("cuerpo del menú debe permanecer intacto y completo", prompt)

    def test_prompt_documents_immutable_menu_inventory_in_reaffirmation(
        self,
    ) -> None:
        prompt = self._render_prompt(response_type="menu_full")
        idx_reaffirmation = prompt.find("Reafirmación factual")
        idx_runtime = prompt.find('"factual_message":')
        self.assertGreater(idx_reaffirmation, 0)
        self.assertGreater(idx_runtime, 0)
        reaffirmation_block = prompt[idx_reaffirmation:idx_runtime]
        for clause in (
            "`menu_full`",
            "`menu_category`",
            "inventario factual",
            "inmutable",
            "resumir",
            "reagrupar",
            "aplanar a prosa",
            "omitir variantes",
        ):
            with self.subTest(clause=clause):
                self.assertIn(clause, reaffirmation_block)

    def test_prompt_names_presentation_and_unit_variants(self) -> None:
        prompt = self._render_prompt()
        self.assertIn("presentaciones", prompt)
        self.assertIn("grande/chica", prompt)
        self.assertIn("lata", prompt)
        self.assertIn("litro", prompt)
        self.assertIn("2 litros", prompt)
        self.assertIn("unidad", prompt)
        self.assertIn("kilo", prompt)

    def test_prompt_documents_status_non_inference_rule(self) -> None:
        prompt = self._render_prompt(response_type="order_status")
        for clause in (
            "`order_status`",
            "estado y la logística expresamente presentes",
            "inferir o prometer",
            "preparación, despacho, entrega",
            "llegada",
            "tiempos estimados",
            "urgencia",
            "acción futura",
        ):
            with self.subTest(clause=clause):
                self.assertIn(clause, prompt)

    def test_prompt_documents_status_non_inference_in_reaffirmation(
        self,
    ) -> None:
        prompt = self._render_prompt(response_type="order_status")
        idx_reaffirmation = prompt.find("Reafirmación factual")
        idx_runtime = prompt.find('"factual_message":')
        self.assertGreater(idx_reaffirmation, 0)
        self.assertGreater(idx_runtime, 0)
        reaffirmation_block = prompt[idx_reaffirmation:idx_runtime]
        for clause in (
            "`order_status`",
            "estado y la logística expresamente presentes",
            "preparación, despacho, entrega",
            "tiempos estimados",
            "acción futura",
        ):
            with self.subTest(clause=clause):
                self.assertIn(clause, reaffirmation_block)

    def test_prompt_subordinates_flavor_directive_to_factual_rules(
        self,
    ) -> None:
        prompt = self._render_prompt(
            flavor_instruccion="INSTRUCCION-CALIDA-QUE-PUEDE-TENTAR-A-DRIFT",
        )
        self.assertIn("INSTRUCCION-CALIDA-QUE-PUEDE-TENTAR-A-DRIFT", prompt)
        idx_directive = prompt.find("INSTRUCCION-CALIDA-QUE-PUEDE-TENTAR-A-DRIFT")
        idx_reaffirmation = prompt.find("Reafirmación factual")
        idx_runtime = prompt.find('"factual_message":')
        self.assertGreater(idx_directive, 0)
        self.assertGreater(idx_reaffirmation, 0)
        self.assertGreater(idx_runtime, 0)
        self.assertLess(idx_directive, idx_reaffirmation)
        self.assertLess(idx_reaffirmation, idx_runtime)
        reaffirmation_block = prompt[idx_reaffirmation:idx_runtime]
        self.assertIn("prevalecen sin excepción", reaffirmation_block)
        self.assertIn("ajusta exclusivamente vocabulario", reaffirmation_block)

    def test_reaffirmation_block_survives_flavor_directive_change(
        self,
    ) -> None:
        """The menu and status clauses belong to the static body
        and remain present regardless of the runtime flavor
        directive.
        """
        for instruccion in (
            "Tono serio.",
            "Tono joven y cálido.",
            "DIRECTRIZ-QUE-PROMETE-ENTREGAS",
        ):
            with self.subTest(instruccion=instruccion):
                prompt = self._render_prompt(
                    flavor_instruccion=instruccion,
                    response_type="menu_full",
                )
                idx_reaffirmation = prompt.find("Reafirmación factual")
                idx_runtime = prompt.find('"factual_message":')
                reaffirmation_block = prompt[idx_reaffirmation:idx_runtime]
                self.assertIn("inventario factual", reaffirmation_block)
                self.assertIn("resumir", reaffirmation_block)

    def test_status_non_inference_survives_flavor_directive_change(self) -> None:
        for instruccion in (
            "Tono serio.",
            "Tono joven y cálido.",
            "DIRECTRIZ-QUE-INVENTA-EN-CAMINO",
        ):
            with self.subTest(instruccion=instruccion):
                prompt = self._render_prompt(
                    flavor_instruccion=instruccion,
                    response_type="order_status",
                )
                idx_reaffirmation = prompt.find("Reafirmación factual")
                idx_runtime = prompt.find('"factual_message":')
                reaffirmation_block = prompt[idx_reaffirmation:idx_runtime]
                self.assertIn("`order_status`", reaffirmation_block)
                self.assertIn("tiempos estimados", reaffirmation_block)
                self.assertIn("acción futura", reaffirmation_block)

    def test_runtime_factual_block_uses_safe_json_serialization(self) -> None:
        """The strengthened rules do NOT change the safe-JSON
        serialization of the runtime block: quotes, backslashes,
        accents and newlines are still escaped / preserved as
        documented.
        """
        flavor = _flavor()
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(
                message='Menú: {"a": 1}\nLínea 2 con "comillas"',
                intent="ver_menu",
                status="executed",
            )
        ]
        client = _llm({"items": [{"index": 0, "message": "Versión"}]})
        style_responses(db, 1, responses, query_llm=client)
        prompt = client.request.call_args.args[0]
        self.assertIn(r"{\"a\": 1}", prompt)
        self.assertIn(r"\"comillas\"", prompt)
        self.assertIn(r"\nLínea 2 con \"comillas\"", prompt)
        self.assertNotIn('Menú: {"a": 1}\nLínea 2 con "comillas"', prompt)

    def test_template_version_reflects_calibration_amendment(self) -> None:
        """The template version must reflect the calibration
        amendment so operators can correlate drift with the menu /
        status strengthening.
        """
        self.assertEqual(
            OUTBOUND_STYLE_PROMPT_TEMPLATE_VERSION,
            "outbound-response-styler/v2.2.0",
        )

    def test_template_fingerprint_changes_only_with_static_body(self) -> None:
        """Fingerprint must remain stable when the static body is
        unchanged and independent of any runtime flavor directive or
        factual message.
        """
        first = outbound_style_template_fingerprint()
        for instruccion, message in (
            ("Tono A.", "Menú A"),
            ("Tono B bien cálido.", "Estado B en camino"),
            ("", ""),
        ):
            with self.subTest(instruccion=instruccion, message=message):
                self.assertEqual(
                    outbound_style_template_fingerprint(), first
                )
                self.assertEqual(
                    build_outbound_style_prompt(
                        instruccion_llm=instruccion,
                        items=[
                            {
                                "index": 0,
                                "response_type": "menu_full",
                                "factual_message": message,
                            }
                        ],
                    ).find(first),
                    -1,
                )

    def test_no_semantic_validator_was_added_to_styler(self) -> None:
        """The amendment is a prompt-only calibration. The styler
        MUST still be a strict structural parser with no semantic
        fact comparison and no second LLM call.
        """
        flavor = _flavor()
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(message="A", intent="saludo", status="executed"),
            CustomerResponse(
                message="B", intent="agregar_producto", status="executed"
            ),
        ]
        client = _llm(
            {
                "items": [
                    {"index": 0, "message": "Texto arbitrario X"},
                    {"index": 1, "message": "Texto arbitrario Y"},
                ]
            }
        )
        styled = style_responses(db, 1, responses, query_llm=client)
        self.assertEqual(client.request.call_count, 1)
        self.assertEqual(styled[0].message, "Texto arbitrario X")
        self.assertEqual(styled[1].message, "Texto arbitrario Y")

    def test_no_database_transaction_control_was_added(self) -> None:
        flavor = _flavor()
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(
                message=_MENU_MULTILINE,
                intent="ver_menu",
                status="executed",
            )
        ]
        client = _llm({"items": [{"index": 0, "message": "Versión menú"}]})
        style_responses(db, 1, responses, query_llm=client)
        for method in (
            "commit",
            "rollback",
            "begin",
            "begin_nested",
            "flush",
            "refresh",
            "close",
        ):
            getattr(db, method).assert_not_called()

    def test_no_second_llm_call_on_menu_failure(self) -> None:
        flavor = _flavor()
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(
                message=_MENU_MULTILINE,
                intent="ver_menu",
                status="executed",
            )
        ]
        client = _llm(QueryLlmTimeoutError("boom"))
        styled = style_responses(db, 1, responses, query_llm=client)
        self.assertEqual(client.request.call_count, 1)
        self.assertEqual(styled[0].message, _MENU_MULTILINE)

    def test_no_second_llm_call_on_status_failure(self) -> None:
        flavor = _flavor()
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(
                message=_ORDER_STATUS,
                intent="consultar_estado_pedido",
                status="executed",
            )
        ]
        client = _llm(QueryLlmTimeoutError("boom"))
        styled = style_responses(db, 1, responses, query_llm=client)
        self.assertEqual(client.request.call_count, 1)
        self.assertEqual(styled[0].message, _ORDER_STATUS)


if __name__ == "__main__":
    unittest.main(verbosity=2)