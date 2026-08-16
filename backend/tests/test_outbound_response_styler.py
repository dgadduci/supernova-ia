"""Focused tests for the safe outbound response styler.

The styler is the shared, optional presentation-only layer invoked
once per turn by :mod:`backend.services.outbound_response_mapper`.
The tests cover the privacy, eligibility, one-call batching,
fallback, observability and transaction-boundary contracts from
the approved OpenSpec change.

The tests intentionally avoid hitting the real LLM transport.
Every ``QueryLlm`` interaction is faked through a ``MagicMock``
that captures the rendered prompt and returns a controlled JSON
payload. The real ``Comercio`` and ``FlavorComunicacion`` ORM rows
are replaced by ``MagicMock`` instances so the tests stay fast and
isolated.
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
from backend.intents.responses.social_conversation_response import (
    SOCIAL_CONVERSATION_HANDLER,
)

# NOTE: `outbound_style_template_fingerprint` is used by the
# focused test below and is re-exported from
# `backend.services.outbound_response_styler` for the module-level
# `__all__` boundary; the test imports the canonical definition.
from backend.intents.schemas.customer_response import CustomerResponse
from backend.intents.schemas.processed_intent import ProcessedIntent
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
    FALLBACK_EMPTY_WRAPPER,
    FALLBACK_HTTP,
    FALLBACK_MALFORMED_BATCH,
    FALLBACK_RESPONSE,
    FALLBACK_TIMEOUT,
    FALLBACK_UNEXPECTED,
    FALLBACK_WRAPPER_INVALID,
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

_FACTUAL_SENTINELS = (
    "secret-customer-message",
    "Pizza Mozzarella",
    "Av. Secreta 1234",
    "Medio de pago X",
    "+5491100000000",
    "session-id-leak",
    "pedido-id-leak",
)


def _forbidden_in_prompt(rendered: str) -> list[str]:
    leaks: list[str] = []
    for sentinel in _FACTUAL_SENTINELS:
        if sentinel in rendered:
            leaks.append(sentinel)
    return leaks


def _flavor(codigo: str = "serio", *, activo: bool = True, instruccion: str = "Tono serio.") -> MagicMock:
    flavor = MagicMock()
    flavor.activo = activo
    flavor.codigo = codigo
    flavor.instruccion_llm = instruccion
    return flavor


def _db_with_flavor(comercio_id: int = 1, *, flavor: MagicMock | None = None) -> MagicMock:
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


def _capture_event(line: str) -> dict | None:
    try:
        return json.loads(line.strip())
    except json.JSONDecodeError:
        return None


def _last_event(stream: io.StringIO) -> dict:
    last_line = stream.getvalue().splitlines()[-1]
    event = _capture_event(last_line)
    assert event is not None
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
            ("ver_metodos_de_pago", EXECUTED_STATUS): RESPONSE_TYPE_INFO_PAYMENT_METHODS,
            (
                "ver_metodos_de_entrega",
                EXECUTED_STATUS,
            ): RESPONSE_TYPE_INFO_DELIVERY_METHODS,
            ("consultar_domicilio_comercio", EXECUTED_STATUS): RESPONSE_TYPE_INFO_ADDRESS,
            ("consultar_horarios_comercio", EXECUTED_STATUS): RESPONSE_TYPE_INFO_HOURS,
            ("agregar_producto", EXECUTED_STATUS): RESPONSE_TYPE_PRODUCT_ADD_SUCCESS,
            ("quitar_producto", EXECUTED_STATUS): RESPONSE_TYPE_PRODUCT_REMOVE_SUCCESS,
            ("modificar_producto", EXECUTED_STATUS): RESPONSE_TYPE_PRODUCT_MODIFY_SUCCESS,
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
        """`desconocida` is a generic recovery / ambiguity response and
        MUST stay byte-for-byte deterministic regardless of the
        selected flavor.
        """
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
        self.assertIsNone(response_type_for("__futuro_deferred_intent__", EXECUTED_STATUS))

    def test_response_type_for_rejects_non_string_inputs(self) -> None:
        self.assertIsNone(response_type_for(None, EXECUTED_STATUS))  # type: ignore[arg-type]
        self.assertIsNone(response_type_for("saludo", None))  # type: ignore[arg-type]


class SelectEligibleTest(unittest.TestCase):
    def test_preserves_index_and_response_for_eligible_only(self) -> None:
        responses = [
            CustomerResponse(message="A", intent="saludo", status="executed"),
            CustomerResponse(message="B", intent="desconocida", status="rejected"),
            CustomerResponse(message="C", intent="agregar_producto", status="executed"),
            CustomerResponse(message="D", intent="set_direccion_entrega", status="executed"),
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
            {"items": [{"index": 0, "prefix": "¡Hey!", "suffix": ""}]}
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
            {"items": [{"index": 0, "prefix": "¡Hey!", "suffix": ""}]}
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
            {"items": [{"index": 0, "prefix": "¡Hey!", "suffix": ""}]}
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
            {"items": [{"index": 0, "prefix": "¡Hey!", "suffix": ""}]}
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
        client = _llm({"items": [{"index": 0, "prefix": "x", "suffix": ""}]})
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
        client = _llm({"items": [{"index": 0, "prefix": "x", "suffix": ""}]})
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
        client = _llm({"items": [{"index": 0, "prefix": "x", "suffix": ""}]})
        styled = style_responses(
            db, "not-an-int", responses, query_llm=client  # type: ignore[arg-type]
        )
        self.assertEqual(styled[0].message, "Hola")
        self.assertEqual(client.request.call_count, 0)


class StyleResponsesHappyPathTest(unittest.TestCase):
    def test_one_eligible_response_uses_one_llm_call_and_wraps_factual(self) -> None:
        flavor = _flavor()
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(
                message="Hola, decime qué querés.",
                intent="saludo",
                status="executed",
            )
        ]
        client = _llm(
            {"items": [{"index": 0, "prefix": "¡Buenas!", "suffix": " 👋"}]}
        )
        styled = style_responses(db, 1, responses, query_llm=client)
        self.assertEqual(client.request.call_count, 1)
        self.assertEqual(styled[0].message, "¡Buenas!Hola, decime qué querés. 👋")
        self.assertEqual(styled[0].intent, "saludo")
        self.assertEqual(styled[0].status, "executed")
        self.assertIn("Hola, decime qué querés.", styled[0].message)

    def test_multiple_eligible_responses_share_a_single_call(self) -> None:
        flavor = _flavor()
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(message="Mensaje 1", intent="saludo", status="executed"),
            CustomerResponse(message="Mensaje 2", intent="agradecimiento", status="executed"),
            CustomerResponse(message="Mensaje 3", intent="iniciar_pedido", status="executed"),
        ]
        client = _llm(
            {
                "items": [
                    {"index": 0, "prefix": "[A] ", "suffix": ""},
                    {"index": 1, "prefix": "[B] ", "suffix": ""},
                    {"index": 2, "prefix": "[C] ", "suffix": " ✨"},
                ]
            }
        )
        styled = style_responses(db, 1, responses, query_llm=client)
        self.assertEqual(client.request.call_count, 1)
        self.assertEqual(styled[0].message, "[A] Mensaje 1")
        self.assertEqual(styled[1].message, "[B] Mensaje 2")
        self.assertEqual(styled[2].message, "[C] Mensaje 3 ✨")

    def test_preserves_intent_and_status_after_wrapping(self) -> None:
        flavor = _flavor()
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(
                message="Hola",
                intent="saludo",
                status="executed",
            )
        ]
        client = _llm({"items": [{"index": 0, "prefix": "⚡", "suffix": ""}]})
        styled = style_responses(db, 1, responses, query_llm=client)
        self.assertEqual(styled[0].intent, "saludo")
        self.assertEqual(styled[0].status, "executed")

    def test_desconocida_is_byte_for_byte_baseline_under_active_flavor(self) -> None:
        """`desconocida` is a generic recovery message that MUST
        stay byte-for-byte deterministic regardless of the
        selected flavor. Under an active non-neutral flavor it
        must NOT be sent to the LLM, the rendered message must
        not change and the styler must emit a `not_attempted`
        event with zero eligible count.
        """
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
                    {
                        "index": 0,
                        "prefix": "⚡",
                        "suffix": " ALTERED",
                    }
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
        """Defensive contract: the eligibility surface MUST NOT
        advertise any token for `desconocida`, regardless of
        status.
        """
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

    def test_mixed_eligible_and_ineligible_responses_only_style_eligible(self) -> None:
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
                    {"index": 0, "prefix": "[S] ", "suffix": ""},
                    {"index": 1, "prefix": "[I] ", "suffix": ""},
                ]
            }
        )
        styled = style_responses(db, 1, responses, query_llm=client)
        self.assertEqual(styled[0].message, "[S] Mensaje A")
        self.assertEqual(styled[1].message, "Mensaje B (rejection)")
        self.assertEqual(styled[2].message, "[I] Mensaje C")
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
            CustomerResponse(message="E", intent="agregar_producto", status="executed"),
        ]
        client = _llm(
            {
                "items": [
                    {"index": 0, "prefix": "[S] ", "suffix": ""},
                    {"index": 4, "prefix": "[A] ", "suffix": ""},
                ]
            }
        )
        style_responses(db, 1, responses, query_llm=client)
        prompt = client.request.call_args.args[0]
        self.assertIn("response_type: social_greeting", prompt)
        self.assertIn("response_type: product_add_success", prompt)
        self.assertNotIn("response_type: set_observacion_pedido", prompt)
        self.assertNotIn("response_type: set_direccion_entrega", prompt)
        self.assertNotIn("response_type: set_metodo_de_pago", prompt)


class StyleResponsesPrivacyTest(unittest.TestCase):
    def test_prompt_never_contains_factual_message_or_customer_text(self) -> None:
        flavor = _flavor(instruccion="Tono serio. Cero jerga.")
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(
                message="Pizza Mozzarella grande",
                intent="agregar_producto",
                status="executed",
            ),
            CustomerResponse(
                message="Tú pedido está en preparación.",
                intent="consultar_estado_pedido",
                status="executed",
            ),
        ]
        client = _llm(
            {
                "items": [
                    {"index": 0, "prefix": "", "suffix": ""},
                    {"index": 1, "prefix": "", "suffix": ""},
                ]
            }
        )
        style_responses(
            db,
            1,
            responses,
            query_llm=client,
        )
        prompt = client.request.call_args.args[0]
        leaks = _forbidden_in_prompt(prompt)
        self.assertEqual(
            leaks,
            [],
            f"factual/customer data leaked in prompt: {leaks}",
        )

    def test_prompt_carries_only_static_template_and_internal_instruction(self) -> None:
        flavor = _flavor(instruccion="Tono serio. Cero jerga.")
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(message="X", intent="saludo", status="executed"),
        ]
        client = _llm({"items": [{"index": 0, "prefix": "", "suffix": ""}]})
        style_responses(db, 1, responses, query_llm=client)
        prompt = client.request.call_args.args[0]
        self.assertIn("Tono serio. Cero jerga.", prompt)
        self.assertIn("response_type: social_greeting", prompt)
        for sentinel in (
            "session-id-leak",
            "pedido-id-leak",
            "session-7",
            "pedido-9",
            "comercio-42",
            "+5491100000000",
            "secret-customer-message",
            "Pizza Mozzarella",
            "Av. Secreta 1234",
        ):
            with self.subTest(sentinel=sentinel):
                self.assertNotIn(sentinel, prompt)

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

    def test_rendering_is_pure_function_of_inputs(self) -> None:
        items = [{"index": 0, "response_type": "social_greeting"}]
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
            items=[{"index": 0, "response_type": "social_greeting"}],
        )
        second = build_outbound_style_prompt(
            instruccion_llm=instruction,
            items=[
                {"index": 0, "response_type": "social_greeting"},
                {"index": 1, "response_type": "product_add_success"},
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
            db,
            1,
            responses,
            query_llm=client,
            stream=stream,
        )
        self.assertEqual(styled[0].message, "OK")
        last_event = _last_event(stream)
        self.assertIsNotNone(last_event)
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
        self.assertEqual(last_event["exception_type"], "QueryLlmConnectionError")

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
        self.assertEqual(last_event["exception_type"], "QueryLlmResponseError")

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

    def test_malformed_batch_structure_falls_back_for_all_items(self) -> None:
        flavor = _flavor()
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(message="A", intent="saludo", status="executed"),
            CustomerResponse(
                message="B", intent="agregar_producto", status="executed"
            ),
        ]
        client = _llm({"items": [{"index": 0, "prefix": "", "suffix": ""}]})
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
                        "prefix": "",
                        "suffix": "",
                        "message": "ALLO",
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
                    {"index": 1, "prefix": "", "suffix": ""},
                    {"index": 0, "prefix": "", "suffix": ""},
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

    def test_wrapper_with_digit_falls_back(self) -> None:
        flavor = _flavor()
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(message="A", intent="saludo", status="executed"),
        ]
        client = _llm({"items": [{"index": 0, "prefix": "Hello2", "suffix": ""}]})
        stream = io.StringIO()
        styled = style_responses(
            db, 1, responses, query_llm=client, stream=stream
        )
        self.assertEqual(styled[0].message, "A")
        last_event = _last_event(stream)
        self.assertEqual(last_event["failure_category"], FALLBACK_WRAPPER_INVALID)
        self.assertNotIn("outcome", last_event)

    def test_wrapper_with_question_mark_falls_back(self) -> None:
        flavor = _flavor()
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(message="A", intent="saludo", status="executed"),
        ]
        client = _llm({"items": [{"index": 0, "prefix": "¿Listo?", "suffix": ""}]})
        stream = io.StringIO()
        styled = style_responses(
            db, 1, responses, query_llm=client, stream=stream
        )
        self.assertEqual(styled[0].message, "A")
        last_event = _last_event(stream)
        self.assertEqual(last_event["failure_category"], FALLBACK_WRAPPER_INVALID)
        self.assertNotIn("outcome", last_event)

    def test_wrapper_with_newline_falls_back(self) -> None:
        flavor = _flavor()
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(message="A", intent="saludo", status="executed"),
        ]
        client = _llm({"items": [{"index": 0, "prefix": "Hi\n", "suffix": ""}]})
        stream = io.StringIO()
        styled = style_responses(
            db, 1, responses, query_llm=client, stream=stream
        )
        self.assertEqual(styled[0].message, "A")
        last_event = _last_event(stream)
        self.assertEqual(last_event["failure_category"], FALLBACK_WRAPPER_INVALID)
        self.assertNotIn("outcome", last_event)

    def test_per_item_wrapper_invalid_falls_back_for_that_item_only(self) -> None:
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
                    {"index": 0, "prefix": "[G] ", "suffix": ""},
                    {"index": 1, "prefix": "[B?", "suffix": ""},
                ]
            }
        )
        stream = io.StringIO()
        styled = style_responses(
            db, 1, responses, query_llm=client, stream=stream
        )
        self.assertEqual(styled[0].message, "[G] A")
        self.assertEqual(styled[1].message, "B")
        last_event = _last_event(stream)
        self.assertEqual(last_event.get("outcome"), OUTCOME_APPLIED)
        self.assertEqual(last_event.get("applied_count"), 1)
        self.assertEqual(last_event.get("eligible_count"), 2)

    def test_event_emitted_when_there_are_zero_eligible(self) -> None:
        db = _db_with_flavor(1, flavor=_flavor())
        responses = [
            CustomerResponse(
                message="rejection",
                intent="agregar_producto",
                status="rejected",
            ),
        ]
        client = _llm({"items": [{"index": 0, "prefix": "", "suffix": ""}]})
        stream = io.StringIO()
        style_responses(
            db, 1, responses, query_llm=client, stream=stream
        )
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
        client = _llm({"items": [{"index": 0, "prefix": "", "suffix": ""}]})
        stream = io.StringIO()
        style_responses(
            db, 1, responses, query_llm=client, stream=stream
        )
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
        client = _llm({"items": [{"index": 0, "prefix": "¡Hey!", "suffix": ""}]})
        stream = io.StringIO()
        style_responses(
            db, 1, responses, query_llm=client, stream=stream
        )
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
        # Sanity: the hash is a 64-char lowercase hex (SHA-256).
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
        style_responses(
            db, 1, responses, query_llm=client, stream=stream
        )
        last_event = _last_event(stream)
        self.assertNotIn("outcome", last_event)
        self.assertEqual(
            last_event.get("failure_category"), FALLBACK_TIMEOUT
        )
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

    def test_event_carries_static_template_identity_when_not_attempted(self) -> None:
        # Zero-eligible responses still emit a `not_attempted` event
        # carrying the static template identity for diagnostics.
        db = _db_with_flavor(1, flavor=_flavor())
        client = _llm({"items": [{"index": 0, "prefix": "", "suffix": ""}]})
        stream = io.StringIO()
        style_responses(
            db, 1, [], query_llm=client, stream=stream
        )
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

    def test_template_identity_never_carries_sensitive_content(self) -> None:
        """Static template identity is sourced from the static
        template body. It MUST NOT contain the rendered prompt,
        the flavor instruction, the customer text, the factual
        response text, the LLM output or any business identifier.
        """
        flavor = _flavor(instruccion="INSTRUCCION-SECRETA")
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(
                message="Pizza Mozzarella grande",
                intent="agregar_producto",
                status="executed",
            ),
        ]
        client = _llm(
            {
                "items": [
                    {"index": 0, "prefix": "", "suffix": ""},
                ]
            }
        )
        stream = io.StringIO()
        style_responses(
            db, 1, responses, query_llm=client, stream=stream
        )
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
            "secret-customer-message",
            "Av. Secreta 1234",
        ):
            with self.subTest(forbidden=forbidden):
                # Observability events MUST NOT carry the prompt,
                # the flavor instruction, customer text, factual
                # response text or any business identifier.
                self.assertNotIn(forbidden, serialized)
        # The prompt legitimately carries the bounded internal
        # `instruccion_llm` (the selected flavor directive) but it
        # MUST NOT carry customer text, factual response text,
        # business identifiers or LLM output.
        for forbidden in (
            "Pizza Mozzarella",
            "session-7",
            "pedido-9",
            "comercio-42",
            "+5491100000000",
            "secret-customer-message",
            "Av. Secreta 1234",
        ):
            with self.subTest(prompt_forbidden=forbidden):
                self.assertNotIn(forbidden, prompt)
        self.assertIn("INSTRUCCION-SECRETA", prompt)
        self.assertIn("response_type: product_add_success", prompt)


class StyleResponsesSecurityTest(unittest.TestCase):
    def test_no_database_transaction_control_is_invoked(self) -> None:
        flavor = _flavor()
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(message="A", intent="saludo", status="executed"),
        ]
        client = _llm(
            {
                "items": [
                    {"index": 0, "prefix": "[G] ", "suffix": ""},
                ]
            }
        )
        stream = io.StringIO()
        style_responses(
            db, 1, responses, query_llm=client, stream=stream
        )
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
        style_responses(
            db, 1, responses, query_llm=client, stream=stream
        )
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
        client = _llm({"items": [{"index": 0, "prefix": "", "suffix": ""}]})
        styled = style_responses(db, 1, [], query_llm=client)
        self.assertEqual(styled, [])
        self.assertEqual(client.request.call_count, 0)


class EmptyWrapperContractTest(unittest.TestCase):
    """Empty wrappers are explicitly invalid per eligible item.

    The pilot revealed that the LLM may return ``{"prefix": "",
    "suffix": ""}`` for every eligible item, which was previously
    accepted as a successful apply and produced no visible style
    change. The corrected contract:

    * at least one of ``prefix`` or ``suffix`` MUST be non-empty
      for every eligible item;
    * empty wrappers fall back to the original factual message;
    * the diagnostic event records the bounded ``empty_wrapper``
      category when ALL wrappers are empty/invalid;
    * the prompt template documents the visibility mandate
      explicitly.
    """

    _SALUDO = (
        "¡Hola! Puedo ayudarte a armar tu pedido. Decime qué querés."
    )
    _AGG_SUCCESS = "Listo, agregué 1 Pizza Mozzarella (grande)."
    _MENU_HEADER = "Menú disponible:"

    def _saludo_intent(self) -> ProcessedIntent:
        return ProcessedIntent(
            intent="saludo",
            source_text="hola",
            status="executed",
            recognizer="intent_classifier",
            handler=SOCIAL_CONVERSATION_HANDLER,
        )

    def _menu_intent(self) -> ProcessedIntent:
        return ProcessedIntent(
            intent="ver_menu",
            source_text="menu",
            status="executed",
            recognizer="menu_category_resolver",
            handler="informational_commerce_response",
            resolved_data={"items": []},
        )

    def _add_intent(self) -> ProcessedIntent:
        return ProcessedIntent(
            intent="agregar_producto",
            source_text="agregar",
            status="executed",
            recognizer="recognizer_productos",
            handler="agregar_producto",
        )

    def test_prompt_requires_visible_wrapper_per_eligible_item(self) -> None:
        flavor = _flavor()
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(
                message=self._SALUDO, intent="saludo", status="executed"
            )
        ]
        client = _llm({"items": [{"index": 0, "prefix": "", "suffix": ""}]})
        style_responses(db, 1, responses, query_llm=client)
        prompt = client.request.call_args.args[0]
        self.assertIn("Visibilidad obligatoria", prompt)
        self.assertIn("al menos uno de", prompt)
        self.assertIn("NO vacía", prompt)

    def test_single_empty_wrapper_keeps_factual_intact(self) -> None:
        flavor = _flavor()
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(
                message=self._SALUDO, intent="saludo", status="executed"
            )
        ]
        client = _llm({"items": [{"index": 0, "prefix": "", "suffix": ""}]})
        stream = io.StringIO()
        styled = style_responses(
            db, 1, responses, query_llm=client, stream=stream
        )
        self.assertEqual(styled[0].message, self._SALUDO)
        self.assertEqual(styled[0].intent, "saludo")
        self.assertEqual(styled[0].status, "executed")
        last_event = _last_event(stream)
        self.assertEqual(last_event["eligible_count"], 1)
        self.assertEqual(last_event["applied_count"], 0)
        self.assertEqual(
            last_event["failure_category"], FALLBACK_EMPTY_WRAPPER
        )

    def test_mixed_batch_only_applies_non_empty_wrappers(self) -> None:
        flavor = _flavor()
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(
                message=self._SALUDO, intent="saludo", status="executed"
            ),
            CustomerResponse(
                message=self._AGG_SUCCESS,
                intent="agregar_producto",
                status="executed",
            ),
        ]
        client = _llm(
            {
                "items": [
                    {"index": 0, "prefix": "", "suffix": ""},
                    {"index": 1, "prefix": "¡Listo! ", "suffix": ""},
                ]
            }
        )
        stream = io.StringIO()
        styled = style_responses(
            db, 1, responses, query_llm=client, stream=stream
        )
        self.assertEqual(styled[0].message, self._SALUDO)
        self.assertEqual(styled[1].message, f"¡Listo! {self._AGG_SUCCESS}")
        self.assertEqual(styled[0].intent, "saludo")
        self.assertEqual(styled[1].intent, "agregar_producto")
        self.assertEqual(client.request.call_count, 1)
        last_event = _last_event(stream)
        self.assertEqual(last_event["outcome"], OUTCOME_APPLIED)
        self.assertEqual(last_event["eligible_count"], 2)
        self.assertEqual(last_event["applied_count"], 1)

    def test_all_empty_wrappers_emit_empty_wrapper_fallback(self) -> None:
        flavor = _flavor()
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(
                message=self._SALUDO, intent="saludo", status="executed"
            ),
            CustomerResponse(
                message=self._AGG_SUCCESS,
                intent="agregar_producto",
                status="executed",
            ),
        ]
        client = _llm(
            {
                "items": [
                    {"index": 0, "prefix": "", "suffix": ""},
                    {"index": 1, "prefix": "", "suffix": ""},
                ]
            }
        )
        stream = io.StringIO()
        styled = style_responses(
            db, 1, responses, query_llm=client, stream=stream
        )
        self.assertEqual(styled[0].message, self._SALUDO)
        self.assertEqual(styled[1].message, self._AGG_SUCCESS)
        last_event = _last_event(stream)
        self.assertNotIn("outcome", last_event)
        self.assertEqual(
            last_event["failure_category"], FALLBACK_EMPTY_WRAPPER
        )
        self.assertEqual(last_event["eligible_count"], 2)
        self.assertEqual(last_event["applied_count"], 0)

    def test_joven_flavor_applies_visible_style_to_saludo(self) -> None:
        flavor = _flavor(codigo="joven")
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(
                message=self._SALUDO, intent="saludo", status="executed"
            )
        ]
        client = _llm({"items": [{"index": 0, "prefix": "¡Buenas! ", "suffix": ""}]})
        stream = io.StringIO()
        styled = style_responses(
            db, 1, responses, query_llm=client, stream=stream
        )
        self.assertEqual(styled[0].message, f"¡Buenas! {self._SALUDO}")
        last_event = _last_event(stream)
        self.assertEqual(last_event["flavor_code"], "joven")
        self.assertEqual(last_event["outcome"], OUTCOME_APPLIED)

    def test_joven_flavor_applies_visible_style_to_menu(self) -> None:
        flavor = _flavor(codigo="joven")
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(
                message=self._MENU_HEADER,
                intent="ver_menu",
                status="executed",
            )
        ]
        client = _llm({"items": [{"index": 0, "prefix": "", "suffix": " 🍕"}]})
        stream = io.StringIO()
        styled = style_responses(
            db, 1, responses, query_llm=client, stream=stream
        )
        self.assertEqual(styled[0].message, f"{self._MENU_HEADER} 🍕")
        last_event = _last_event(stream)
        self.assertEqual(last_event["flavor_code"], "joven")
        self.assertEqual(last_event["outcome"], OUTCOME_APPLIED)

    def test_joven_flavor_applies_visible_style_to_add_success(self) -> None:
        flavor = _flavor(codigo="joven")
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(
                message=self._AGG_SUCCESS,
                intent="agregar_producto",
                status="executed",
            )
        ]
        client = _llm({"items": [{"index": 0, "prefix": "¡Genial! ", "suffix": ""}]})
        stream = io.StringIO()
        styled = style_responses(
            db, 1, responses, query_llm=client, stream=stream
        )
        self.assertEqual(
            styled[0].message, f"¡Genial! {self._AGG_SUCCESS}"
        )
        last_event = _last_event(stream)
        self.assertEqual(last_event["flavor_code"], "joven")
        self.assertEqual(last_event["outcome"], OUTCOME_APPLIED)

    def test_prompt_never_carries_factual_or_inbound_text(self) -> None:
        flavor = _flavor(
            codigo="joven",
            instruccion="Tono joven. Cero formalidad.",
        )
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(
                message="Pizza Mozzarella grande",
                intent="agregar_producto",
                status="executed",
            )
        ]
        client = _llm({"items": [{"index": 0, "prefix": "¡Hey! ", "suffix": ""}]})
        style_responses(db, 1, responses, query_llm=client)
        prompt = client.request.call_args.args[0]
        for forbidden in (
            "Pizza Mozzarella",
            "Pizza",
            "Mozzarella",
            "grande",
            "Av. Secreta 1234",
            "session-7",
            "pedido-9",
            "comercio-42",
            "+5491100000000",
            "secret-customer-message",
            "hola",
            "agregar",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, prompt)
        # The prompt carries the bounded internal directive only.
        self.assertIn("Tono joven. Cero formalidad.", prompt)

    def test_neutro_flavor_skips_styling_for_saludo(self) -> None:
        db = _db_with_flavor(1, flavor=_flavor(NEUTRO_FLAVOR_CODE))
        responses = [
            CustomerResponse(
                message=self._SALUDO, intent="saludo", status="executed"
            )
        ]
        client = _llm({"items": [{"index": 0, "prefix": "", "suffix": ""}]})
        stream = io.StringIO()
        style_responses(db, 1, responses, query_llm=client, stream=stream)
        self.assertEqual(client.request.call_count, 0)
        last_event = _last_event(stream)
        self.assertEqual(last_event["outcome"], OUTCOME_NOT_ATTEMPTED)

    def test_desconocida_skips_styling_for_saludo_baseline(self) -> None:
        flavor = _flavor()
        db = _db_with_flavor(1, flavor=flavor)
        baseline = (
            "Disculpá, no entendí tu mensaje. "
            "Podés pedirme el menú o decirme qué producto querés agregar."
        )
        responses = [
            CustomerResponse(
                message=baseline,
                intent="desconocida",
                status="executed",
            )
        ]
        client = _llm({"items": [{"index": 0, "prefix": "¡Hey! ", "suffix": ""}]})
        stream = io.StringIO()
        styled = style_responses(
            db, 1, responses, query_llm=client, stream=stream
        )
        self.assertEqual(styled[0].message, baseline)
        self.assertEqual(client.request.call_count, 0)
        last_event = _last_event(stream)
        self.assertEqual(last_event["outcome"], OUTCOME_NOT_ATTEMPTED)
        self.assertEqual(last_event["eligible_count"], 0)

    def test_no_database_transaction_control_on_empty_wrapper(self) -> None:
        flavor = _flavor()
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(
                message=self._SALUDO, intent="saludo", status="executed"
            )
        ]
        client = _llm({"items": [{"index": 0, "prefix": "", "suffix": ""}]})
        stream = io.StringIO()
        style_responses(
            db, 1, responses, query_llm=client, stream=stream
        )
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

    def test_single_llm_call_for_mixed_batch(self) -> None:
        flavor = _flavor()
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(
                message=self._SALUDO, intent="saludo", status="executed"
            ),
            CustomerResponse(
                message=self._AGG_SUCCESS,
                intent="agregar_producto",
                status="executed",
            ),
        ]
        client = _llm(
            {
                "items": [
                    {"index": 0, "prefix": "", "suffix": ""},
                    {"index": 1, "prefix": "¡Genial! ", "suffix": ""},
                ]
            }
        )
        style_responses(db, 1, responses, query_llm=client)
        self.assertEqual(client.request.call_count, 1)

    def test_all_empty_failure_event_carries_static_identity(self) -> None:
        flavor = _flavor()
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(
                message=self._SALUDO, intent="saludo", status="executed"
            )
        ]
        client = _llm({"items": [{"index": 0, "prefix": "", "suffix": ""}]})
        stream = io.StringIO()
        style_responses(
            db, 1, responses, query_llm=client, stream=stream
        )
        last_event = _last_event(stream)
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


if __name__ == "__main__":
    unittest.main(verbosity=2)