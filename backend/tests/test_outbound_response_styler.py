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

import hashlib
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
    style_responses_with_diagnostic,
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


class ExpressiveWrapperCalibrationTest(unittest.TestCase):
    """Subphase 6 — expressive wrapper calibration.

    The wrapper expands from ``<=24`` characters per field to
    ``<=96`` characters per field with a combined length bound of
    ``<=140`` characters. The LLM still receives only the
    ``response_type`` token and the persisted ``instruccion_llm``;
    the backend composes ``prefix + exact factual message +
    suffix``. The validator keeps rejecting digits, question
    marks, newlines and control characters. Empty wrappers remain
    an ``empty_wrapper`` per-item fallback.

    The tests below lock down the expanded expressive envelope
    while preserving the factual, privacy, one-call and
    transaction-boundary contracts of the restored wrapper.
    """

    _SALUDO = (
        "¡Hola! Puedo ayudarte a armar tu pedido. Decime qué querés."
    )
    _AGG_SUCCESS = "Listo, agregué 1 Pizza Mozzarella (grande)."

    def test_accepts_expressive_multi_word_prefix_within_ninety_six(self) -> None:
        flavor = _flavor()
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(
                message=self._SALUDO, intent="saludo", status="executed"
            )
        ]
        phrase = "¡Hola, qué gusto verte por acá otra vez! "
        self.assertLessEqual(len(phrase), 96)
        client = _llm(
            {"items": [{"index": 0, "prefix": phrase, "suffix": ""}]}
        )
        stream = io.StringIO()
        styled = style_responses(
            db, 1, responses, query_llm=client, stream=stream
        )
        self.assertEqual(styled[0].message, f"{phrase}{self._SALUDO}")
        self.assertEqual(styled[0].intent, "saludo")
        self.assertEqual(styled[0].status, "executed")
        last_event = _last_event(stream)
        self.assertEqual(last_event["outcome"], OUTCOME_APPLIED)
        self.assertEqual(last_event["applied_count"], 1)

    def test_accepts_expressive_multi_word_suffix_within_ninety_six(self) -> None:
        flavor = _flavor()
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(
                message=self._AGG_SUCCESS,
                intent="agregar_producto",
                status="executed",
            )
        ]
        phrase = " ¡Listo, pedí tranquilo y avisame si querés algo más!"
        self.assertLessEqual(len(phrase), 96)
        client = _llm(
            {"items": [{"index": 0, "prefix": "", "suffix": phrase}]}
        )
        stream = io.StringIO()
        styled = style_responses(
            db, 1, responses, query_llm=client, stream=stream
        )
        self.assertEqual(styled[0].message, f"{self._AGG_SUCCESS}{phrase}")
        self.assertEqual(styled[0].intent, "agregar_producto")
        self.assertEqual(styled[0].status, "executed")
        last_event = _last_event(stream)
        self.assertEqual(last_event["outcome"], OUTCOME_APPLIED)

    def test_accepts_unicode_emoji_within_per_field_bound(self) -> None:
        flavor = _flavor()
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(
                message=self._AGG_SUCCESS,
                intent="agregar_producto",
                status="executed",
            )
        ]
        prefix = "¡Excelente! 🍕🍕🍕 "
        suffix = " 🥳🎉"
        self.assertLessEqual(len(prefix), 96)
        self.assertLessEqual(len(suffix), 96)
        self.assertLessEqual(len(prefix) + len(suffix), 140)
        client = _llm(
            {"items": [{"index": 0, "prefix": prefix, "suffix": suffix}]}
        )
        stream = io.StringIO()
        styled = style_responses(
            db, 1, responses, query_llm=client, stream=stream
        )
        self.assertEqual(
            styled[0].message, f"{prefix}{self._AGG_SUCCESS}{suffix}"
        )
        last_event = _last_event(stream)
        self.assertEqual(last_event["outcome"], OUTCOME_APPLIED)

    def test_rejects_field_exactly_ninety_seven_characters(self) -> None:
        flavor = _flavor()
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(
                message=self._SALUDO, intent="saludo", status="executed"
            )
        ]
        long_prefix = "a" * 97
        client = _llm(
            {"items": [{"index": 0, "prefix": long_prefix, "suffix": ""}]}
        )
        stream = io.StringIO()
        styled = style_responses(
            db, 1, responses, query_llm=client, stream=stream
        )
        self.assertEqual(styled[0].message, self._SALUDO)
        self.assertEqual(styled[0].intent, "saludo")
        self.assertEqual(styled[0].status, "executed")
        last_event = _last_event(stream)
        self.assertEqual(
            last_event["failure_category"], FALLBACK_WRAPPER_INVALID
        )
        self.assertNotIn("outcome", last_event)

    def test_accepts_field_exactly_ninety_six_characters(self) -> None:
        flavor = _flavor()
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(
                message=self._SALUDO, intent="saludo", status="executed"
            )
        ]
        long_prefix = "a" * 96
        client = _llm(
            {"items": [{"index": 0, "prefix": long_prefix, "suffix": ""}]}
        )
        stream = io.StringIO()
        styled = style_responses(
            db, 1, responses, query_llm=client, stream=stream
        )
        self.assertEqual(styled[0].message, f"{long_prefix}{self._SALUDO}")
        last_event = _last_event(stream)
        self.assertEqual(last_event["outcome"], OUTCOME_APPLIED)

    def test_rejects_combined_length_one_forty_one(self) -> None:
        flavor = _flavor()
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(
                message=self._SALUDO, intent="saludo", status="executed"
            )
        ]
        prefix = "a" * 96
        suffix = "b" * 45
        self.assertEqual(len(prefix), 96)
        self.assertEqual(len(suffix), 45)
        self.assertEqual(len(prefix) + len(suffix), 141)
        client = _llm(
            {"items": [{"index": 0, "prefix": prefix, "suffix": suffix}]}
        )
        stream = io.StringIO()
        styled = style_responses(
            db, 1, responses, query_llm=client, stream=stream
        )
        self.assertEqual(styled[0].message, self._SALUDO)
        self.assertEqual(styled[0].intent, "saludo")
        self.assertEqual(styled[0].status, "executed")
        last_event = _last_event(stream)
        self.assertEqual(
            last_event["failure_category"], FALLBACK_WRAPPER_INVALID
        )
        self.assertNotIn("outcome", last_event)

    def test_accepts_combined_length_exactly_one_forty(self) -> None:
        flavor = _flavor()
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(
                message=self._SALUDO, intent="saludo", status="executed"
            )
        ]
        prefix = "a" * 96
        suffix = "b" * 44
        self.assertEqual(len(prefix) + len(suffix), 140)
        client = _llm(
            {"items": [{"index": 0, "prefix": prefix, "suffix": suffix}]}
        )
        stream = io.StringIO()
        styled = style_responses(
            db, 1, responses, query_llm=client, stream=stream
        )
        self.assertEqual(
            styled[0].message, f"{prefix}{self._SALUDO}{suffix}"
        )
        last_event = _last_event(stream)
        self.assertEqual(last_event["outcome"], OUTCOME_APPLIED)

    def test_digit_still_rejected_under_expressive_bounds(self) -> None:
        flavor = _flavor()
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(
                message=self._SALUDO, intent="saludo", status="executed"
            )
        ]
        client = _llm(
            {"items": [{"index": 0, "prefix": "Hola 1 vez más", "suffix": ""}]}
        )
        stream = io.StringIO()
        styled = style_responses(
            db, 1, responses, query_llm=client, stream=stream
        )
        self.assertEqual(styled[0].message, self._SALUDO)
        last_event = _last_event(stream)
        self.assertEqual(
            last_event["failure_category"], FALLBACK_WRAPPER_INVALID
        )

    def test_question_mark_still_rejected_under_expressive_bounds(self) -> None:
        flavor = _flavor()
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(
                message=self._SALUDO, intent="saludo", status="executed"
            )
        ]
        client = _llm(
            {
                "items": [
                    {
                        "index": 0,
                        "prefix": "¡Buenas, cómo andás hoy?",
                        "suffix": "",
                    }
                ]
            }
        )
        stream = io.StringIO()
        styled = style_responses(
            db, 1, responses, query_llm=client, stream=stream
        )
        self.assertEqual(styled[0].message, self._SALUDO)
        last_event = _last_event(stream)
        self.assertEqual(
            last_event["failure_category"], FALLBACK_WRAPPER_INVALID
        )

    def test_newline_still_rejected_under_expressive_bounds(self) -> None:
        flavor = _flavor()
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(
                message=self._SALUDO, intent="saludo", status="executed"
            )
        ]
        client = _llm(
            {"items": [{"index": 0, "prefix": "Hola\namigo", "suffix": ""}]}
        )
        stream = io.StringIO()
        styled = style_responses(
            db, 1, responses, query_llm=client, stream=stream
        )
        self.assertEqual(styled[0].message, self._SALUDO)
        last_event = _last_event(stream)
        self.assertEqual(
            last_event["failure_category"], FALLBACK_WRAPPER_INVALID
        )

    def test_control_character_still_rejected_under_expressive_bounds(self) -> None:
        flavor = _flavor()
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(
                message=self._SALUDO, intent="saludo", status="executed"
            )
        ]
        client = _llm(
            {
                "items": [
                    {"index": 0, "prefix": "Hola\x07amigo", "suffix": ""}
                ]
            }
        )
        stream = io.StringIO()
        styled = style_responses(
            db, 1, responses, query_llm=client, stream=stream
        )
        self.assertEqual(styled[0].message, self._SALUDO)
        last_event = _last_event(stream)
        self.assertEqual(
            last_event["failure_category"], FALLBACK_WRAPPER_INVALID
        )

    def test_factual_message_remains_intact_substring_with_expressive_wrapper(
        self,
    ) -> None:
        flavor = _flavor()
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(
                message=self._AGG_SUCCESS,
                intent="agregar_producto",
                status="executed",
            )
        ]
        prefix = "¡Sumá y seguí eligiendo! "
        suffix = " 🍕🥳"
        client = _llm(
            {"items": [{"index": 0, "prefix": prefix, "suffix": suffix}]}
        )
        stream = io.StringIO()
        styled = style_responses(
            db, 1, responses, query_llm=client, stream=stream
        )
        composed = styled[0].message
        self.assertTrue(composed.startswith(prefix))
        self.assertTrue(composed.endswith(suffix))
        self.assertIn(self._AGG_SUCCESS, composed)
        # The factual sentence is a contiguous substring; the order
        # of the prefix, original message and suffix is preserved.
        self.assertEqual(
            composed, f"{prefix}{self._AGG_SUCCESS}{suffix}"
        )
        self.assertEqual(styled[0].intent, "agregar_producto")
        self.assertEqual(styled[0].status, "executed")
        last_event = _last_event(stream)
        self.assertEqual(last_event["outcome"], OUTCOME_APPLIED)

    def test_mixed_batch_keeps_invalid_item_factual_and_applies_valid_item(
        self,
    ) -> None:
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
        valid_prefix = "¡Qué bueno tenerte de vuelta! "
        client = _llm(
            {
                "items": [
                    # Exceeds the combined length bound: invalid item.
                    {
                        "index": 0,
                        "prefix": "a" * 96,
                        "suffix": "b" * 45,
                    },
                    # Valid expressive wrapper with emojis.
                    {
                        "index": 1,
                        "prefix": valid_prefix,
                        "suffix": " 🍕✨",
                    },
                ]
            }
        )
        stream = io.StringIO()
        styled = style_responses(
            db, 1, responses, query_llm=client, stream=stream
        )
        self.assertEqual(styled[0].message, self._SALUDO)
        self.assertEqual(
            styled[1].message,
            f"{valid_prefix}{self._AGG_SUCCESS} 🍕✨",
        )
        self.assertEqual(styled[0].intent, "saludo")
        self.assertEqual(styled[1].intent, "agregar_producto")
        # Only one batch LLM call was made.
        self.assertEqual(client.request.call_count, 1)
        last_event = _last_event(stream)
        self.assertEqual(last_event["outcome"], OUTCOME_APPLIED)
        self.assertEqual(last_event["eligible_count"], 2)
        self.assertEqual(last_event["applied_count"], 1)

    def test_runtime_prompt_carries_no_factual_or_business_data(self) -> None:
        flavor = _flavor(
            codigo="joven",
            instruccion="Tono joven. Usá emojis cuando aporten calidez.",
        )
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(
                message="Pizza Mozzarella grande",
                intent="agregar_producto",
                status="executed",
            ),
            CustomerResponse(
                message="Tu pedido está en preparación.",
                intent="consultar_estado_pedido",
                status="executed",
            ),
            CustomerResponse(
                message="Av. Secreta 1234",
                intent="set_direccion_entrega",
                status="executed",
            ),
        ]
        client = _llm(
            {
                "items": [
                    {"index": 0, "prefix": "¡Buena!", "suffix": ""},
                    {"index": 1, "prefix": "", "suffix": " 🚀"},
                ]
            }
        )
        style_responses(db, 1, responses, query_llm=client)
        self.assertEqual(client.request.call_count, 1)
        prompt = client.request.call_args.args[0]
        for forbidden in (
            "Pizza Mozzarella",
            "Mozzarella",
            "grande",
            "Av. Secreta 1234",
            "session-7",
            "pedido-9",
            "comercio-42",
            "+5491100000000",
            "secret-customer-message",
            # Inbound raw text is never sent to the LLM.
            "agregar",
            "hola",
            # Ineligible free-text intents stay out of the batch.
            "response_type: set_direccion_entrega",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, prompt)
        # Only the bounded internal directive and the allowlisted
        # response_type tokens for eligible responses are present.
        self.assertIn("Tono joven. Usá emojis cuando aporten calidez.", prompt)
        self.assertIn("response_type: product_add_success", prompt)
        self.assertIn("response_type: order_status", prompt)

    def test_expressive_prompt_does_not_hardcode_joven_specific_emoji_or_phrase(
        self,
    ) -> None:
        # The static prompt is flavor-agnostic. The persisted
        # `instruccion_llm` is the sole source of tone/emoji; the
        # prompt body must not assert a flavor-specific word list.
        prompt = build_outbound_style_prompt(
            instruccion_llm="Tono serio. Sin emojis.",
            items=[{"index": 0, "response_type": "social_greeting"}],
        )
        for hardcoded in (
            "¡Hola",
            "¡Buenas",
            "🍕",
            "🥳",
            "genial",
        ):
            with self.subTest(hardcoded=hardcoded):
                self.assertNotIn(hardcoded, prompt)

    def test_one_call_batch_with_expressive_wrappers_across_eligible_only(
        self,
    ) -> None:
        flavor = _flavor()
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(
                message=self._SALUDO, intent="saludo", status="executed"
            ),
            CustomerResponse(
                message="rejection-text",
                intent="agregar_producto",
                status="rejected",
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
                    {
                        "index": 0,
                        "prefix": "¡Hola, bienvenido de nuevo! ",
                        "suffix": " 👋",
                    },
                    {
                        "index": 1,
                        "prefix": "¡Listo, pedido en marcha! ",
                        "suffix": " 🍕✨",
                    },
                ]
            }
        )
        stream = io.StringIO()
        styled = style_responses(
            db, 1, responses, query_llm=client, stream=stream
        )
        # The rejection is never sent to the LLM and stays intact.
        self.assertEqual(styled[0].message, "¡Hola, bienvenido de nuevo! " + self._SALUDO + " 👋")
        self.assertEqual(styled[1].message, "rejection-text")
        self.assertEqual(styled[2].message, "¡Listo, pedido en marcha! " + self._AGG_SUCCESS + " 🍕✨")
        # Single batch call for the two eligible items.
        self.assertEqual(client.request.call_count, 1)
        last_event = _last_event(stream)
        self.assertEqual(last_event["outcome"], OUTCOME_APPLIED)
        self.assertEqual(last_event["eligible_count"], 2)
        self.assertEqual(last_event["applied_count"], 2)

    def test_neutro_flavor_makes_zero_llm_calls_even_with_expressive_prompt(
        self,
    ) -> None:
        db = _db_with_flavor(1, flavor=_flavor(NEUTRO_FLAVOR_CODE))
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
                    {"index": 0, "prefix": "¡Buenas!", "suffix": ""},
                    {"index": 1, "prefix": "¡Listo!", "suffix": ""},
                ]
            }
        )
        stream = io.StringIO()
        styled = style_responses(
            db, 1, responses, query_llm=client, stream=stream
        )
        self.assertEqual(client.request.call_count, 0)
        self.assertEqual(styled[0].message, self._SALUDO)
        self.assertEqual(styled[1].message, self._AGG_SUCCESS)
        last_event = _last_event(stream)
        self.assertEqual(last_event["outcome"], OUTCOME_NOT_ATTEMPTED)

    def test_ineligible_responses_make_zero_llm_calls_under_expressive_envelope(
        self,
    ) -> None:
        flavor = _flavor()
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(
                message="rejection",
                intent="agregar_producto",
                status="rejected",
            ),
            CustomerResponse(
                message="Av. Secreta 1234",
                intent="set_direccion_entrega",
                status="executed",
            ),
            CustomerResponse(
                message="observacion-confidencial",
                intent="set_observacion_pedido",
                status="executed",
            ),
        ]
        client = _llm({"items": []})
        stream = io.StringIO()
        styled = style_responses(
            db, 1, responses, query_llm=client, stream=stream
        )
        self.assertEqual(client.request.call_count, 0)
        self.assertEqual(styled[0].message, "rejection")
        self.assertEqual(styled[1].message, "Av. Secreta 1234")
        self.assertEqual(styled[2].message, "observacion-confidencial")
        last_event = _last_event(stream)
        self.assertEqual(last_event["outcome"], OUTCOME_NOT_ATTEMPTED)
        self.assertEqual(last_event["eligible_count"], 0)

    def test_no_database_transaction_control_for_expressive_wrapper(self) -> None:
        flavor = _flavor()
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(
                message=self._SALUDO, intent="saludo", status="executed"
            )
        ]
        client = _llm(
            {
                "items": [
                    {
                        "index": 0,
                        "prefix": "¡Qué bueno verte por acá! ",
                        "suffix": " 👋",
                    }
                ]
            }
        )
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

    def test_template_version_reflects_expressive_calibration(self) -> None:
        self.assertEqual(
            OUTBOUND_STYLE_PROMPT_TEMPLATE_VERSION,
            "outbound-response-styler/v1.4.0",
        )
        self.assertEqual(styler_version(), "outbound-response-styler/v1.4.0")

    def test_template_fingerprint_changes_with_static_body_only(self) -> None:
        # The fingerprint must depend only on the static template
        # body and never on the rendered prompt, the flavor
        # instruction or any customer/pedido/session data.
        identity = outbound_style_template_identity()
        self.assertEqual(len(identity["outbound_style_prompt_template_hash"]), 64)
        first = identity["outbound_style_prompt_template_hash"]
        # Different flavor instruction must NOT change the
        # fingerprint.
        prompt_a = build_outbound_style_prompt(
            instruccion_llm="Tono serio.",
            items=[{"index": 0, "response_type": "social_greeting"}],
        )
        prompt_b = build_outbound_style_prompt(
            instruccion_llm="Tono joven, súper cálido y con emojis.",
            items=[
                {"index": 0, "response_type": "social_greeting"},
                {"index": 1, "response_type": "product_add_success"},
            ],
        )
        # Fingerprint stays stable across rendered prompts.
        self.assertEqual(
            outbound_style_template_fingerprint(),
            first,
        )
        # The rendered prompts differ when the items change, but
        # the static fingerprint does not.
        self.assertNotEqual(prompt_a, prompt_b)
        # Fingerprint must NOT embed any runtime data.
        for forbidden in (
            "Tono joven",
            "Tono serio",
            "social_greeting",
            "product_add_success",
            "Pizza Mozzarella",
            "Av. Secreta 1234",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, first)


class MenuWrapperCalibrationTest(unittest.TestCase):
    """Subphase 8 — menu wrapper calibration.

    Pilot evidence under a usable selected ``joven`` flavor showed
    that ``menu_full`` reached the styler but received the safe
    ``wrapper_invalid`` fallback: the LLM tried to reproduce,
    summarize, list, title, format or describe menu content while
    the static prompt only restated generic wrapper rules. This
    amendment revises and versions the static prompt so the
    ``menu_full`` boundary is explicit:

    * the LLM receives only the opaque ``menu_full`` token and the
      selected persisted flavor instruction;
    * the wrapper must be a generic one-line framing phrase;
    * it must not reproduce, summarize, enumerate, list, title,
      format or describe any menu content;
    * it must not introduce products, presentations, categories,
      prices, quantities, discounts or order/customer facts;
    * it must not use Markdown, bullets, line breaks, questions or
      instructions to the customer;
    * tone and emoji choices stay governed exclusively by the
      selected persisted ``instruccion_llm`` (no hardcoded flavor
      phrase or emoji);
    * an invalid menu wrapper preserves the exact deterministic
      menu through the existing ``wrapper_invalid`` fallback.

    The static validator, JSON schema, 96 / 140 character bounds,
    one-request maximum, exact factual-substring composition,
    neutral no-op and privacy / no-transaction contracts are
    unchanged. Only the static prompt template, its version and
    its fingerprint are bumped.
    """

    _MENU_MESSAGE = (
        "Menú disponible:\n"
        " - Pizzas: Margarita, Mozzarella, Especial\n"
        " - Bebidas: Agua, Gaseosa\n"
        " - Postres: Flan, Helado"
    )

    def test_template_version_reflects_menu_calibration(self) -> None:
        self.assertEqual(
            OUTBOUND_STYLE_PROMPT_TEMPLATE_VERSION,
            "outbound-response-styler/v1.4.0",
        )
        self.assertEqual(styler_version(), "outbound-response-styler/v1.4.0")
        identity = outbound_style_template_identity()
        self.assertEqual(
            identity["outbound_style_prompt_template_version"],
            "outbound-response-styler/v1.4.0",
        )

    def test_static_prompt_documents_explicit_menu_full_rule(self) -> None:
        """The static prompt body MUST make the ``menu_full``
        boundary explicit: one-line wrapper, never menu content,
        no Markdown / bullets / questions, no flavor-hardcoded
        phrase or emoji. The rule must be present in the body the
        LLM receives so the calibration is auditable.
        """
        prompt = build_outbound_style_prompt(
            instruccion_llm="Tono joven.",
            items=[{"index": 0, "response_type": "menu_full"}],
        )
        # Section header for the menu-specific rule.
        self.assertIn("Regla específica para `menu_full`", prompt)
        # Bounded one-line wrapper reminder.
        self.assertIn("una sola línea", prompt)
        # Prohibited behaviors (the LLM must be told what NOT to do).
        for forbidden_behavior in (
            "reproducir",
            "resumir",
            "enumerar",
            "listar",
            "titular",
            "formatear",
            "describir",
        ):
            with self.subTest(behavior=forbidden_behavior):
                self.assertIn(forbidden_behavior, prompt)
        # No Markdown / bullets / line breaks / questions / instructions.
        for forbidden_format in (
            "Markdown",
            "bullets",
            "saltos de línea",
            "preguntas",
            "instrucciones al cliente",
        ):
            with self.subTest(format=forbidden_format):
                self.assertIn(forbidden_format, prompt)
        # No products / categories / prices / quantities / discounts / facts.
        for forbidden_facts in (
            "productos",
            "presentaciones",
            "categorías",
            "precios",
            "cantidades",
            "descuentos",
            "hechos del pedido",
        ):
            with self.subTest(facts=forbidden_facts):
                self.assertIn(forbidden_facts, prompt)
        # Tone / emoji stay governed by the selected flavor instruction,
        # never hardcoded in the static prompt.
        self.assertIn("directriz interna de tono", prompt)
        self.assertIn("no hardcodees", prompt)

    def test_static_prompt_does_not_prescribe_a_flavor_specific_phrase(self) -> None:
        """The menu-specific rule must NOT hardcode a customer-facing
        phrase or emoji for ``menu_full`` or any flavor. Tone and
        emoji choices stay in the persisted ``instruccion_llm`` row.
        """
        prompt = build_outbound_style_prompt(
            instruccion_llm="Tono joven, súper cálido y con emojis.",
            items=[{"index": 0, "response_type": "menu_full"}],
        )
        for forbidden_phrase in (
            "¡Menú",
            "Aquí va el menú",
            "te paso el menú",
            "menú completo",
            "menú del día",
        ):
            with self.subTest(phrase=forbidden_phrase):
                self.assertNotIn(forbidden_phrase, prompt)
        # Emojis MUST NOT be hardcoded into the static prompt body.
        for forbidden_emoji in ("🍕", "🍔", "🥗", "🍰", "🥤"):
            with self.subTest(emoji=forbidden_emoji):
                self.assertNotIn(forbidden_emoji, prompt)

    def test_template_fingerprint_changes_with_menu_full_rule(self) -> None:
        """The static fingerprint MUST change when the menu-specific
        static rule is added. The fingerprint is the contract that
        detects prompt drift without ever leaking runtime data.
        """
        identity = outbound_style_template_identity()
        self.assertEqual(len(identity["outbound_style_prompt_template_hash"]), 64)
        # The fingerprint MUST NOT embed any flavor instruction,
        # customer or menu content.
        serialized = identity["outbound_style_prompt_template_hash"]
        for forbidden in (
            "Tono joven",
            "Tono serio",
            "menu_full",
            "Pizza",
            "Mozzarella",
            "Av. Secreta 1234",
            "INSTRUCCION-SECRETA",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, serialized)
        # The fingerprint is derived only from the static body, so
        # it MUST stay stable across identical template versions and
        # MUST change only when the static body itself changes.
        self.assertEqual(
            identity["outbound_style_prompt_template_hash"],
            outbound_style_template_fingerprint(),
        )
        # The hash MUST be a 64-char lowercase hex string (SHA-256).
        self.assertTrue(
            all(c in "0123456789abcdef" for c in serialized)
        )
        # Recomputing the hash of any rendered prompt with
        # arbitrary, deterministic runtime inputs MUST yield the
        # same hash: this proves the hash is a pure function of the
        # static body and never of runtime data. We use the empty
        # ``items`` case to match the no-items path.
        re_rendered_no_items = build_outbound_style_prompt(
            instruccion_llm="placeholder-instruccion-llm",
            items=[],
        ).replace("placeholder-instruccion-llm", "{instruccion_llm}")
        # Restore the empty-items placeholder that ``build_outbound_style_prompt``
        # replaced with ``(sin elementos)``.
        re_rendered_with_placeholder = re_rendered_no_items.replace(
            "(sin elementos)", "{items}"
        )
        self.assertEqual(
            hashlib.sha256(re_rendered_with_placeholder.encode("utf-8")).hexdigest(),
            identity["outbound_style_prompt_template_hash"],
        )

    def test_prompt_never_carries_menu_content_for_menu_full(self) -> None:
        flavor = _flavor(
            codigo="joven",
            instruccion="Tono joven. Usá emojis cuando aporten calidez.",
        )
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(
                message=self._MENU_MESSAGE,
                intent="ver_menu",
                status="executed",
            )
        ]
        client = _llm(
            {"items": [{"index": 0, "prefix": "¡Buenas! ", "suffix": " 🍕"}]}
        )
        style_responses(db, 1, responses, query_llm=client)
        prompt = client.request.call_args.args[0]
        # The deterministic menu MUST NOT be sent to the LLM.
        for menu_token in (
            "Pizzas",
            "Margarita",
            "Mozzarella",
            "Especial",
            "Bebidas",
            "Agua",
            "Gaseosa",
            "Postres",
            "Flan",
            "Helado",
            "Menú disponible",
        ):
            with self.subTest(menu_token=menu_token):
                self.assertNotIn(menu_token, prompt)
        # Only the opaque token and the persisted directive are
        # present in the prompt.
        self.assertIn("response_type: menu_full", prompt)
        self.assertIn("Tono joven. Usá emojis cuando aporten calidez.", prompt)

    def test_valid_generic_one_line_wrapper_with_emoji_is_applied(self) -> None:
        flavor = _flavor(codigo="joven")
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(
                message=self._MENU_MESSAGE,
                intent="ver_menu",
                status="executed",
            )
        ]
        prefix = "¡Acá va el menú del local! "
        suffix = " 🍕"
        client = _llm(
            {"items": [{"index": 0, "prefix": prefix, "suffix": suffix}]}
        )
        stream = io.StringIO()
        styled = style_responses(
            db, 1, responses, query_llm=client, stream=stream
        )
        # The deterministic menu remains an intact contiguous substring.
        composed = styled[0].message
        self.assertTrue(composed.startswith(prefix))
        self.assertTrue(composed.endswith(suffix))
        self.assertIn(self._MENU_MESSAGE, composed)
        self.assertEqual(composed, f"{prefix}{self._MENU_MESSAGE}{suffix}")
        self.assertEqual(styled[0].intent, "ver_menu")
        self.assertEqual(styled[0].status, "executed")
        last_event = _last_event(stream)
        self.assertEqual(last_event["outcome"], OUTCOME_APPLIED)
        self.assertEqual(last_event["applied_count"], 1)
        self.assertEqual(last_event["eligible_count"], 1)
        self.assertEqual(last_event["flavor_code"], "joven")

    def test_menu_full_falls_back_when_wrapper_uses_digits(self) -> None:
        """A wrapper that smuggles in digits (a typical menu
        reproduction attempt) MUST be rejected as ``wrapper_invalid``
        and the exact deterministic menu MUST be preserved."""
        flavor = _flavor(codigo="joven")
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(
                message=self._MENU_MESSAGE,
                intent="ver_menu",
                status="executed",
            )
        ]
        client = _llm(
            {
                "items": [
                    {
                        "index": 0,
                        "prefix": "Menú 1: pizzas",
                        "suffix": "",
                    }
                ]
            }
        )
        stream = io.StringIO()
        styled = style_responses(
            db, 1, responses, query_llm=client, stream=stream
        )
        self.assertEqual(styled[0].message, self._MENU_MESSAGE)
        last_event = _last_event(stream)
        self.assertEqual(last_event["failure_category"], FALLBACK_WRAPPER_INVALID)
        self.assertNotIn("outcome", last_event)
        self.assertEqual(last_event["flavor_code"], "joven")

    def test_menu_full_falls_back_when_wrapper_introduces_line_break(self) -> None:
        """Multi-line wrappers (an attempt to reproduce the menu)
        MUST be rejected and the exact deterministic menu preserved."""
        flavor = _flavor(codigo="joven")
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(
                message=self._MENU_MESSAGE,
                intent="ver_menu",
                status="executed",
            )
        ]
        client = _llm(
            {
                "items": [
                    {
                        "index": 0,
                        "prefix": "Acá va el menú:\n- pizzas\n- bebidas",
                        "suffix": "",
                    }
                ]
            }
        )
        stream = io.StringIO()
        styled = style_responses(
            db, 1, responses, query_llm=client, stream=stream
        )
        self.assertEqual(styled[0].message, self._MENU_MESSAGE)
        last_event = _last_event(stream)
        self.assertEqual(last_event["failure_category"], FALLBACK_WRAPPER_INVALID)
        self.assertNotIn("outcome", last_event)

    def test_menu_full_falls_back_when_wrapper_contains_question(self) -> None:
        """A wrapper that asks the customer a question (typical menu
        presentation attempt) MUST be rejected and the exact
        deterministic menu preserved."""
        flavor = _flavor(codigo="joven")
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(
                message=self._MENU_MESSAGE,
                intent="ver_menu",
                status="executed",
            )
        ]
        client = _llm(
            {
                "items": [
                    {
                        "index": 0,
                        "prefix": "¿Qué vas a pedir hoy?",
                        "suffix": "",
                    }
                ]
            }
        )
        stream = io.StringIO()
        styled = style_responses(
            db, 1, responses, query_llm=client, stream=stream
        )
        self.assertEqual(styled[0].message, self._MENU_MESSAGE)
        last_event = _last_event(stream)
        self.assertEqual(last_event["failure_category"], FALLBACK_WRAPPER_INVALID)

    def test_menu_full_wrapper_with_asterisks_passes_validator(self) -> None:
        """The runtime validator rejects digits, line breaks,
        question marks and ASCII control characters. A wrapper that
        smuggles in asterisks (``**``) or other Markdown markers
        without those characters is structurally safe per the
        existing wrapper contract; the static prompt reminds the
        LLM that Markdown is forbidden but the runtime cannot
        detect it. The deterministic menu MUST still remain an
        intact contiguous substring either way.
        """
        flavor = _flavor(codigo="joven")
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(
                message=self._MENU_MESSAGE,
                intent="ver_menu",
                status="executed",
            )
        ]
        client = _llm(
            {
                "items": [
                    {
                        "index": 0,
                        "prefix": "**Pizzas** disponibles",
                        "suffix": "",
                    }
                ]
            }
        )
        stream = io.StringIO()
        styled = style_responses(
            db, 1, responses, query_llm=client, stream=stream
        )
        composed = styled[0].message
        # Even when the wrapper passes the structural validator,
        # the deterministic menu MUST remain an intact contiguous
        # substring because the backend composes prefix + exact
        # factual message + suffix.
        self.assertTrue(composed.startswith("**Pizzas** disponibles"))
        self.assertIn(self._MENU_MESSAGE, composed)

    def test_menu_full_keeps_one_llm_call_per_turn(self) -> None:
        """A batch with a ``menu_full`` eligible response MUST still
        produce exactly one LLM call per turn."""
        flavor = _flavor(codigo="joven")
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(
                message="¡Hola! Decime qué querés.",
                intent="saludo",
                status="executed",
            ),
            CustomerResponse(
                message=self._MENU_MESSAGE,
                intent="ver_menu",
                status="executed",
            ),
        ]
        client = _llm(
            {
                "items": [
                    {"index": 0, "prefix": "¡Hey! ", "suffix": ""},
                    {"index": 1, "prefix": "Acá va el menú ", "suffix": " 🍕"},
                ]
            }
        )
        style_responses(db, 1, responses, query_llm=client)
        self.assertEqual(client.request.call_count, 1)

    def test_menu_full_ineligible_under_neutro_flavor(self) -> None:
        """Under ``neutro`` the menu response MUST remain byte-for-byte
        deterministic and the styler MUST NOT make any LLM call."""
        db = _db_with_flavor(1, flavor=_flavor(NEUTRO_FLAVOR_CODE))
        responses = [
            CustomerResponse(
                message=self._MENU_MESSAGE,
                intent="ver_menu",
                status="executed",
            )
        ]
        client = _llm(
            {
                "items": [
                    {"index": 0, "prefix": "Cualquier cosa", "suffix": ""},
                ]
            }
        )
        stream = io.StringIO()
        styled = style_responses(
            db, 1, responses, query_llm=client, stream=stream
        )
        self.assertEqual(client.request.call_count, 0)
        self.assertEqual(styled[0].message, self._MENU_MESSAGE)
        last_event = _last_event(stream)
        self.assertEqual(last_event["outcome"], OUTCOME_NOT_ATTEMPTED)

    def test_menu_full_preserves_existing_eligibility_token(self) -> None:
        """The eligibility surface for ``ver_menu`` MUST still map to
        the ``menu_full`` token. The calibration only refines the
        static prompt; it MUST NOT widen or shift the eligible set.
        """
        self.assertEqual(
            response_type_for("ver_menu", EXECUTED_STATUS),
            RESPONSE_TYPE_MENU_FULL,
        )


class FactualClaimGuardTest(unittest.TestCase):
    """Subphase 9 — factual-claim guard.

    Pilot evidence under ``joven`` confirms that the backend
    preserves the exact deterministic ``product_add_success``
    sentence, but also shows a valid-shaped wrapper claiming
    that the order is already in transit. That is an unsupported
    commercial / logistics fact and violates the wrapper-only
    safety boundary even though it is outside the deterministic
    substring.

    The amendment adds a bounded normalized lexical guard in the
    existing wrapper validator. A wrapper that asserts, promises,
    or infers order state, preparation, confirmation, shipment,
    delivery, payment, availability, timing, or execution is
    rejected through the existing ``wrapper_invalid`` fallback;
    the exact deterministic message is preserved, the diagnostic
    carries the bounded fallback category, no second LLM call is
    made, and no transaction control is invoked.

    The static prompt also restates the prohibition
    explicitly. The guard is a bounded lexical safety net, not a
    general semantic classifier; ``neutro`` remains an exact
    no-op and the existing 96 / 140 bounds, JSON schema, one
    call maximum, exact factual-substring composition, privacy
    and no-transaction contracts are unchanged.
    """

    _AGG_SUCCESS = "Listo, agregué 1 Pizza Mozzarella (grande)."
    _STATUS_MESSAGE = "Tú pedido está en preparación."
    _IN_TRANSIT_PREFIX = "¡Tu pedido está en camino! "

    def test_in_transit_claim_on_product_add_success_falls_back(self) -> None:
        """A wrapper that claims the order is already in transit
        on a successful product addition MUST be rejected as
        ``wrapper_invalid`` and the exact deterministic message
        MUST be preserved byte-for-byte."""
        flavor = _flavor(codigo="joven")
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(
                message=self._AGG_SUCCESS,
                intent="agregar_producto",
                status="executed",
            )
        ]
        client = _llm(
            {
                "items": [
                    {
                        "index": 0,
                        "prefix": self._IN_TRANSIT_PREFIX,
                        "suffix": "",
                    }
                ]
            }
        )
        stream = io.StringIO()
        styled = style_responses(
            db, 1, responses, query_llm=client, stream=stream
        )
        self.assertEqual(styled[0].message, self._AGG_SUCCESS)
        self.assertEqual(styled[0].intent, "agregar_producto")
        self.assertEqual(styled[0].status, "executed")
        last_event = _last_event(stream)
        self.assertEqual(
            last_event["failure_category"], FALLBACK_WRAPPER_INVALID
        )
        self.assertNotIn("outcome", last_event)
        self.assertEqual(last_event["flavor_code"], "joven")
        self.assertEqual(last_event["eligible_count"], 1)
        self.assertEqual(last_event["applied_count"], 0)

    def test_in_transit_claim_in_suffix_also_falls_back(self) -> None:
        """The guard MUST check both ``prefix`` and ``suffix``."""
        flavor = _flavor(codigo="joven")
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(
                message=self._AGG_SUCCESS,
                intent="agregar_producto",
                status="executed",
            )
        ]
        client = _llm(
            {
                "items": [
                    {
                        "index": 0,
                        "prefix": "¡Genial! ",
                        "suffix": " Ya está en camino.",
                    }
                ]
            }
        )
        stream = io.StringIO()
        styled = style_responses(
            db, 1, responses, query_llm=client, stream=stream
        )
        self.assertEqual(styled[0].message, self._AGG_SUCCESS)
        last_event = _last_event(stream)
        self.assertEqual(
            last_event["failure_category"], FALLBACK_WRAPPER_INVALID
        )

    def test_preparation_claim_falls_back(self) -> None:
        flavor = _flavor(codigo="joven")
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(
                message=self._AGG_SUCCESS,
                intent="agregar_producto",
                status="executed",
            )
        ]
        client = _llm(
            {
                "items": [
                    {
                        "index": 0,
                        "prefix": "¡Genial! ",
                        "suffix": " Ya estamos preparando tu pedido.",
                    }
                ]
            }
        )
        stream = io.StringIO()
        styled = style_responses(
            db, 1, responses, query_llm=client, stream=stream
        )
        self.assertEqual(styled[0].message, self._AGG_SUCCESS)
        last_event = _last_event(stream)
        self.assertEqual(
            last_event["failure_category"], FALLBACK_WRAPPER_INVALID
        )

    def test_delivery_claim_falls_back(self) -> None:
        flavor = _flavor(codigo="joven")
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(
                message=self._AGG_SUCCESS,
                intent="agregar_producto",
                status="executed",
            )
        ]
        client = _llm(
            {
                "items": [
                    {
                        "index": 0,
                        "prefix": "¡Genial! ",
                        "suffix": " Ya entregado.",
                    }
                ]
            }
        )
        stream = io.StringIO()
        styled = style_responses(
            db, 1, responses, query_llm=client, stream=stream
        )
        self.assertEqual(styled[0].message, self._AGG_SUCCESS)
        last_event = _last_event(stream)
        self.assertEqual(
            last_event["failure_category"], FALLBACK_WRAPPER_INVALID
        )

    def test_payment_claim_falls_back(self) -> None:
        flavor = _flavor(codigo="joven")
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(
                message=self._AGG_SUCCESS,
                intent="agregar_producto",
                status="executed",
            )
        ]
        client = _llm(
            {
                "items": [
                    {
                        "index": 0,
                        "prefix": "¡Genial! ",
                        "suffix": " Pago confirmado.",
                    }
                ]
            }
        )
        stream = io.StringIO()
        styled = style_responses(
            db, 1, responses, query_llm=client, stream=stream
        )
        self.assertEqual(styled[0].message, self._AGG_SUCCESS)
        last_event = _last_event(stream)
        self.assertEqual(
            last_event["failure_category"], FALLBACK_WRAPPER_INVALID
        )

    def test_availability_claim_falls_back(self) -> None:
        flavor = _flavor(codigo="joven")
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(
                message=self._AGG_SUCCESS,
                intent="agregar_producto",
                status="executed",
            )
        ]
        client = _llm(
            {
                "items": [
                    {
                        "index": 0,
                        "prefix": "¡Genial! ",
                        "suffix": " En stock.",
                    }
                ]
            }
        )
        stream = io.StringIO()
        styled = style_responses(
            db, 1, responses, query_llm=client, stream=stream
        )
        self.assertEqual(styled[0].message, self._AGG_SUCCESS)
        last_event = _last_event(stream)
        self.assertEqual(
            last_event["failure_category"], FALLBACK_WRAPPER_INVALID
        )

    def test_timing_claim_falls_back(self) -> None:
        flavor = _flavor(codigo="joven")
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(
                message=self._AGG_SUCCESS,
                intent="agregar_producto",
                status="executed",
            )
        ]
        client = _llm(
            {
                "items": [
                    {
                        "index": 0,
                        "prefix": "¡Genial! ",
                        "suffix": " Llega en 30 minutos.",
                    }
                ]
            }
        )
        stream = io.StringIO()
        styled = style_responses(
            db, 1, responses, query_llm=client, stream=stream
        )
        self.assertEqual(styled[0].message, self._AGG_SUCCESS)
        last_event = _last_event(stream)
        self.assertEqual(
            last_event["failure_category"], FALLBACK_WRAPPER_INVALID
        )

    def test_confirmation_claim_falls_back(self) -> None:
        flavor = _flavor(codigo="joven")
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(
                message=self._AGG_SUCCESS,
                intent="agregar_producto",
                status="executed",
            )
        ]
        client = _llm(
            {
                "items": [
                    {
                        "index": 0,
                        "prefix": "¡Genial! ",
                        "suffix": " Hemos confirmado tu pedido.",
                    }
                ]
            }
        )
        stream = io.StringIO()
        styled = style_responses(
            db, 1, responses, query_llm=client, stream=stream
        )
        self.assertEqual(styled[0].message, self._AGG_SUCCESS)
        last_event = _last_event(stream)
        self.assertEqual(
            last_event["failure_category"], FALLBACK_WRAPPER_INVALID
        )

    def test_shipment_claim_falls_back(self) -> None:
        flavor = _flavor(codigo="joven")
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(
                message=self._AGG_SUCCESS,
                intent="agregar_producto",
                status="executed",
            )
        ]
        client = _llm(
            {
                "items": [
                    {
                        "index": 0,
                        "prefix": "¡Genial! ",
                        "suffix": " Ya enviado.",
                    }
                ]
            }
        )
        stream = io.StringIO()
        styled = style_responses(
            db, 1, responses, query_llm=client, stream=stream
        )
        self.assertEqual(styled[0].message, self._AGG_SUCCESS)
        last_event = _last_event(stream)
        self.assertEqual(
            last_event["failure_category"], FALLBACK_WRAPPER_INVALID
        )

    def test_execution_claim_falls_back(self) -> None:
        flavor = _flavor(codigo="joven")
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(
                message=self._AGG_SUCCESS,
                intent="agregar_producto",
                status="executed",
            )
        ]
        client = _llm(
            {
                "items": [
                    {
                        "index": 0,
                        "prefix": "¡Genial! ",
                        "suffix": " Procesado.",
                    }
                ]
            }
        )
        stream = io.StringIO()
        styled = style_responses(
            db, 1, responses, query_llm=client, stream=stream
        )
        self.assertEqual(styled[0].message, self._AGG_SUCCESS)
        last_event = _last_event(stream)
        self.assertEqual(
            last_event["failure_category"], FALLBACK_WRAPPER_INVALID
        )

    def test_generic_expressive_wrapper_still_accepted(self) -> None:
        """A generic expressive wrapper with no guarded claim term
        MUST still be accepted and composed around the exact
        deterministic message."""
        flavor = _flavor(codigo="joven")
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(
                message=self._AGG_SUCCESS,
                intent="agregar_producto",
                status="executed",
            )
        ]
        prefix = "¡Qué bueno que sumaste algo! "
        suffix = " 🍕🥳"
        client = _llm(
            {"items": [{"index": 0, "prefix": prefix, "suffix": suffix}]}
        )
        stream = io.StringIO()
        styled = style_responses(
            db, 1, responses, query_llm=client, stream=stream
        )
        self.assertEqual(
            styled[0].message, f"{prefix}{self._AGG_SUCCESS}{suffix}"
        )
        last_event = _last_event(stream)
        self.assertEqual(last_event["outcome"], OUTCOME_APPLIED)
        self.assertEqual(last_event["applied_count"], 1)

    def test_mixed_batch_keeps_claim_item_factual_and_valid_applied(self) -> None:
        """In a mixed batch, the guarded item MUST fall back to the
        exact deterministic message while the other valid item
        MUST still be styled. Only one LLM call is made."""
        flavor = _flavor(codigo="joven")
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(
                message=self._AGG_SUCCESS,
                intent="agregar_producto",
                status="executed",
            ),
            CustomerResponse(
                message=self._STATUS_MESSAGE,
                intent="consultar_estado_pedido",
                status="executed",
            ),
        ]
        client = _llm(
            {
                "items": [
                    {
                        "index": 0,
                        "prefix": self._IN_TRANSIT_PREFIX,
                        "suffix": "",
                    },
                    {
                        "index": 1,
                        "prefix": "¡Acá estamos! ",
                        "suffix": "",
                    },
                ]
            }
        )
        stream = io.StringIO()
        styled = style_responses(
            db, 1, responses, query_llm=client, stream=stream
        )
        self.assertEqual(styled[0].message, self._AGG_SUCCESS)
        self.assertEqual(
            styled[1].message, f"¡Acá estamos! {self._STATUS_MESSAGE}"
        )
        self.assertEqual(client.request.call_count, 1)
        last_event = _last_event(stream)
        self.assertEqual(last_event["outcome"], OUTCOME_APPLIED)
        self.assertEqual(last_event["eligible_count"], 2)
        self.assertEqual(last_event["applied_count"], 1)

    def test_claim_guard_diagnostic_does_not_leak_wrapper_or_message_or_prompt(
        self,
    ) -> None:
        """The diagnostic MUST record the bounded ``wrapper_invalid``
        fallback category without exposing the rejected wrapper,
        the factual message, the prompt or the flavor instruction."""
        flavor = _flavor(
            codigo="joven",
            instruccion="INSTRUCCION-SECRETA-DEFENSA",
        )
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(
                message=self._AGG_SUCCESS,
                intent="agregar_producto",
                status="executed",
            )
        ]
        client = _llm(
            {
                "items": [
                    {
                        "index": 0,
                        "prefix": self._IN_TRANSIT_PREFIX,
                        "suffix": "",
                    }
                ]
            }
        )
        stream = io.StringIO()
        style_responses(
            db, 1, responses, query_llm=client, stream=stream
        )
        last_event = _last_event(stream)
        self.assertEqual(
            last_event["failure_category"], FALLBACK_WRAPPER_INVALID
        )
        serialized = json.dumps(last_event, sort_keys=True)
        for forbidden in (
            # The rejected wrapper content MUST NOT leak.
            "en camino",
            "Tu pedido está en camino",
            # The factual message MUST NOT leak.
            "Pizza Mozzarella",
            "Mozzarella",
            # The prompt and flavor instruction MUST NOT leak.
            "INSTRUCCION-SECRETA-DEFENSA",
            "Directriz interna",
            "Directriz",
            "response_type",
            # No business identifiers MUST leak.
            "session-7",
            "pedido-9",
            "comercio-42",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, serialized)
        # The bounded fallback category itself is allowed.
        self.assertEqual(last_event["failure_category"], "wrapper_invalid")
        self.assertEqual(last_event["applied_count"], 0)
        self.assertEqual(last_event["eligible_count"], 1)

    def test_one_llm_call_per_turn_preserved_under_claim_guard(self) -> None:
        """The guard MUST NOT trigger a second LLM call. The
        existing one-call maximum is preserved."""
        flavor = _flavor(codigo="joven")
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(
                message=self._AGG_SUCCESS,
                intent="agregar_producto",
                status="executed",
            )
        ]
        client = _llm(
            {
                "items": [
                    {
                        "index": 0,
                        "prefix": self._IN_TRANSIT_PREFIX,
                        "suffix": "",
                    }
                ]
            }
        )
        style_responses(db, 1, responses, query_llm=client)
        self.assertEqual(client.request.call_count, 1)

    def test_neutro_flavor_remain_exact_no_op_under_claim_guard(self) -> None:
        """``neutro`` MUST remain an exact no-op: no LLM call, the
        original message is preserved, the event reports
        ``not_attempted``. The guard is irrelevant for ``neutro``
        because the LLM is never invoked."""
        db = _db_with_flavor(1, flavor=_flavor(NEUTRO_FLAVOR_CODE))
        responses = [
            CustomerResponse(
                message=self._AGG_SUCCESS,
                intent="agregar_producto",
                status="executed",
            )
        ]
        client = _llm(
            {
                "items": [
                    {
                        "index": 0,
                        "prefix": self._IN_TRANSIT_PREFIX,
                        "suffix": "",
                    }
                ]
            }
        )
        stream = io.StringIO()
        styled = style_responses(
            db, 1, responses, query_llm=client, stream=stream
        )
        self.assertEqual(client.request.call_count, 0)
        self.assertEqual(styled[0].message, self._AGG_SUCCESS)
        last_event = _last_event(stream)
        self.assertEqual(last_event["outcome"], OUTCOME_NOT_ATTEMPTED)
        self.assertEqual(last_event["eligible_count"], 1)
        self.assertEqual(last_event["applied_count"], 0)

    def test_no_database_transaction_control_under_claim_guard(self) -> None:
        """The guard is a pure lexical check; it MUST NOT invoke
        any database transaction control method."""
        flavor = _flavor(codigo="joven")
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(
                message=self._AGG_SUCCESS,
                intent="agregar_producto",
                status="executed",
            )
        ]
        client = _llm(
            {
                "items": [
                    {
                        "index": 0,
                        "prefix": self._IN_TRANSIT_PREFIX,
                        "suffix": "",
                    }
                ]
            }
        )
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

    def test_static_prompt_documents_explicit_factual_claim_rule(self) -> None:
        """The static prompt body MUST restate the explicit
        prohibition of order state, preparation, confirmation,
        shipment, delivery, payment, availability, timing, and
        execution claims in ``prefix`` and ``suffix``."""
        prompt = build_outbound_style_prompt(
            instruccion_llm="Tono joven.",
            items=[{"index": 0, "response_type": "product_add_success"}],
        )
        # The amendment introduces a dedicated rule in the
        # sections the LLM receives.
        self.assertIn("NO afirmes, prometas ni infieras", prompt)
        # All bounded high-risk categories are listed explicitly.
        for category in (
            "estado del pedido",
            "preparación",
            "confirmación",
            "envío",
            "entrega",
            "pago",
            "disponibilidad",
            "tiempos",
            "ejecución",
        ):
            with self.subTest(category=category):
                self.assertIn(category, prompt)
        # The fallback category is named explicitly.
        self.assertIn("wrapper_invalid", prompt)

    def test_template_version_reflects_factual_claim_guard(self) -> None:
        """The static template version MUST be bumped to
        ``v1.4.0`` when the factual-claim guard rule is added."""
        self.assertEqual(
            OUTBOUND_STYLE_PROMPT_TEMPLATE_VERSION,
            "outbound-response-styler/v1.4.0",
        )
        self.assertEqual(styler_version(), "outbound-response-styler/v1.4.0")
        identity = outbound_style_template_identity()
        self.assertEqual(
            identity["outbound_style_prompt_template_version"],
            "outbound-response-styler/v1.4.0",
        )

    def test_template_fingerprint_changes_with_factual_claim_rule(self) -> None:
        """The static fingerprint MUST change when the
        factual-claim guard rule is added. The fingerprint is
        derived only from the static body and never embeds
        runtime data."""
        identity = outbound_style_template_identity()
        serialized = identity["outbound_style_prompt_template_hash"]
        self.assertEqual(len(serialized), 64)
        for forbidden in (
            "Tono joven",
            "Tono serio",
            "product_add_success",
            "Pizza Mozzarella",
            "Av. Secreta 1234",
            "INSTRUCCION-SECRETA",
            "en camino",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, serialized)
        self.assertTrue(
            all(c in "0123456789abcdef" for c in serialized)
        )

    def test_prompt_carries_no_in_transit_phrase_from_template(self) -> None:
        """The static template body MUST NOT hardcode a
        customer-facing phrase or emoji. The guard is a lexical
        safety net; the prompt body only describes the
        prohibition."""
        prompt = build_outbound_style_prompt(
            instruccion_llm="Tono joven.",
            items=[{"index": 0, "response_type": "product_add_success"}],
        )
        for forbidden_phrase in (
            "¡Tu pedido está en camino!",
            "Tu pedido está en camino",
            "Ya está en camino",
            "Llega en",
        ):
            with self.subTest(phrase=forbidden_phrase):
                self.assertNotIn(forbidden_phrase, prompt)


class FactualClaimGuardNormalizationTest(unittest.TestCase):
    """Subphase 9 — accent-insensitive, case-insensitive guard.

    The bounded lexical guard MUST compare fragments in a
    case-insensitive AND accent-insensitive way. Variants like
    "Confirmación recibida" / "Confirmacion recibida" and
    "Entrega confirmada" MUST fall back as ``wrapper_invalid``
    exactly like the already-covered "en camino" claim. The
    customer-facing text is never mutated by the comparison:
    the deterministic message is preserved byte-for-byte.

    The guard remains a finite lexical list. This amendment
    only adds the minimal morphological variants needed within
    the already-approved categories (notably ``confirmada``)
    and the Unicode normalization helper used for the
    comparison. No additional LLM call, open semantic regex,
    intent classification, flavor change, DB migration, prompt
    rewrite, mapper change, outbox change, transaction control
    or endpoint change is introduced.
    """

    _AGG_SUCCESS = "Listo, agregué 1 Pizza Mozzarella (grande)."

    def test_accented_confirmacion_recibida_falls_back(self) -> None:
        """A wrapper that says "Confirmación recibida" (with the
        canonical accent) MUST fall back as ``wrapper_invalid``."""
        flavor = _flavor(codigo="joven")
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(
                message=self._AGG_SUCCESS,
                intent="agregar_producto",
                status="executed",
            )
        ]
        client = _llm(
            {
                "items": [
                    {
                        "index": 0,
                        "prefix": "¡Genial! ",
                        "suffix": " Confirmación recibida.",
                    }
                ]
            }
        )
        stream = io.StringIO()
        styled = style_responses(
            db, 1, responses, query_llm=client, stream=stream
        )
        self.assertEqual(styled[0].message, self._AGG_SUCCESS)
        last_event = _last_event(stream)
        self.assertEqual(
            last_event["failure_category"], FALLBACK_WRAPPER_INVALID
        )
        self.assertNotIn("outcome", last_event)

    def test_unaccented_confirmacion_recibida_falls_back(self) -> None:
        """A wrapper that says "Confirmacion recibida" (without
        the accent) MUST also fall back as ``wrapper_invalid``.
        This is the variant that previously evaded the
        ``lower()``-only normalization."""
        flavor = _flavor(codigo="joven")
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(
                message=self._AGG_SUCCESS,
                intent="agregar_producto",
                status="executed",
            )
        ]
        client = _llm(
            {
                "items": [
                    {
                        "index": 0,
                        "prefix": "¡Genial! ",
                        "suffix": " Confirmacion recibida.",
                    }
                ]
            }
        )
        stream = io.StringIO()
        styled = style_responses(
            db, 1, responses, query_llm=client, stream=stream
        )
        self.assertEqual(styled[0].message, self._AGG_SUCCESS)
        last_event = _last_event(stream)
        self.assertEqual(
            last_event["failure_category"], FALLBACK_WRAPPER_INVALID
        )
        self.assertNotIn("outcome", last_event)

    def test_entrega_confirmada_falls_back(self) -> None:
        """The feminine past participle "confirmada" MUST be
        covered. A wrapper that says "Entrega confirmada" MUST
        fall back as ``wrapper_invalid``."""
        flavor = _flavor(codigo="joven")
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(
                message=self._AGG_SUCCESS,
                intent="agregar_producto",
                status="executed",
            )
        ]
        client = _llm(
            {
                "items": [
                    {
                        "index": 0,
                        "prefix": "¡Genial! ",
                        "suffix": " Entrega confirmada.",
                    }
                ]
            }
        )
        stream = io.StringIO()
        styled = style_responses(
            db, 1, responses, query_llm=client, stream=stream
        )
        self.assertEqual(styled[0].message, self._AGG_SUCCESS)
        last_event = _last_event(stream)
        self.assertEqual(
            last_event["failure_category"], FALLBACK_WRAPPER_INVALID
        )
        self.assertNotIn("outcome", last_event)

    def test_in_transit_claim_still_falls_back(self) -> None:
        """The previously-covered "en camino" claim MUST still
        fall back as ``wrapper_invalid`` after the normalization
        change."""
        flavor = _flavor(codigo="joven")
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(
                message=self._AGG_SUCCESS,
                intent="agregar_producto",
                status="executed",
            )
        ]
        client = _llm(
            {
                "items": [
                    {
                        "index": 0,
                        "prefix": "¡Tu pedido está en camino! ",
                        "suffix": "",
                    }
                ]
            }
        )
        stream = io.StringIO()
        styled = style_responses(
            db, 1, responses, query_llm=client, stream=stream
        )
        self.assertEqual(styled[0].message, self._AGG_SUCCESS)
        last_event = _last_event(stream)
        self.assertEqual(
            last_event["failure_category"], FALLBACK_WRAPPER_INVALID
        )
        self.assertNotIn("outcome", last_event)

    def test_uppercase_accented_confirmacion_falls_back(self) -> None:
        """Case + accent variation: "CONFIRMACIÓN RECIBIDA" MUST
        also fall back as ``wrapper_invalid``."""
        flavor = _flavor(codigo="joven")
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(
                message=self._AGG_SUCCESS,
                intent="agregar_producto",
                status="executed",
            )
        ]
        client = _llm(
            {
                "items": [
                    {
                        "index": 0,
                        "prefix": "",
                        "suffix": " CONFIRMACIÓN RECIBIDA.",
                    }
                ]
            }
        )
        stream = io.StringIO()
        styled = style_responses(
            db, 1, responses, query_llm=client, stream=stream
        )
        self.assertEqual(styled[0].message, self._AGG_SUCCESS)
        last_event = _last_event(stream)
        self.assertEqual(
            last_event["failure_category"], FALLBACK_WRAPPER_INVALID
        )

    def test_generic_safe_wrapper_still_applied(self) -> None:
        """A safe generic wrapper with no guarded claim term
        MUST still be applied. The normalization MUST NOT
        produce false positives on ordinary greetings."""
        flavor = _flavor(codigo="joven")
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(
                message=self._AGG_SUCCESS,
                intent="agregar_producto",
                status="executed",
            )
        ]
        prefix = "¡Qué bueno que sumaste algo! "
        suffix = " 🍕🥳"
        client = _llm(
            {"items": [{"index": 0, "prefix": prefix, "suffix": suffix}]}
        )
        stream = io.StringIO()
        styled = style_responses(
            db, 1, responses, query_llm=client, stream=stream
        )
        self.assertEqual(
            styled[0].message, f"{prefix}{self._AGG_SUCCESS}{suffix}"
        )
        last_event = _last_event(stream)
        self.assertEqual(last_event["outcome"], OUTCOME_APPLIED)
        self.assertEqual(last_event["applied_count"], 1)

    def test_customer_facing_text_is_not_mutated_by_guard(self) -> None:
        """The Unicode normalization MUST be confined to the
        guard comparison. The composed customer-facing text
        preserves the original characters of the wrapper and
        the deterministic message byte-for-byte."""
        flavor = _flavor(codigo="joven")
        db = _db_with_flavor(1, flavor=flavor)
        original = "¡Confirmación recibida!"
        responses = [
            CustomerResponse(
                message=self._AGG_SUCCESS,
                intent="agregar_producto",
                status="executed",
            )
        ]
        client = _llm(
            {
                "items": [
                    {
                        "index": 0,
                        "prefix": original,
                        "suffix": "",
                    }
                ]
            }
        )
        stream = io.StringIO()
        styled = style_responses(
            db, 1, responses, query_llm=client, stream=stream
        )
        # The guard rejected the wrapper, so the deterministic
        # message is preserved unchanged. The rejected wrapper
        # itself is never mutated nor surfaced.
        self.assertEqual(styled[0].message, self._AGG_SUCCESS)
        # The original characters survive untouched in the
        # LLM client argument (the wrapper is sent verbatim);
        # the guard only inspects a normalized copy.
        self.assertEqual(
            client.request.call_args.args[0].count(original),
            0,
            "Rejected wrapper must not be embedded in the prompt",
        )

    def test_neutro_skips_guard_entirely(self) -> None:
        """``neutro`` MUST remain an exact no-op: no LLM call,
        the original message is preserved, and the guard
        normalization is irrelevant because the LLM is never
        invoked."""
        db = _db_with_flavor(1, flavor=_flavor(NEUTRO_FLAVOR_CODE))
        responses = [
            CustomerResponse(
                message=self._AGG_SUCCESS,
                intent="agregar_producto",
                status="executed",
            )
        ]
        client = _llm(
            {
                "items": [
                    {
                        "index": 0,
                        "prefix": "¡Genial! ",
                        "suffix": " Confirmación recibida.",
                    }
                ]
            }
        )
        stream = io.StringIO()
        styled = style_responses(
            db, 1, responses, query_llm=client, stream=stream
        )
        self.assertEqual(client.request.call_count, 0)
        self.assertEqual(styled[0].message, self._AGG_SUCCESS)
        last_event = _last_event(stream)
        self.assertEqual(last_event["outcome"], OUTCOME_NOT_ATTEMPTED)
        self.assertEqual(last_event["eligible_count"], 1)
        self.assertEqual(last_event["applied_count"], 0)

    def test_one_llm_call_per_turn_preserved_under_normalized_guard(
        self,
    ) -> None:
        """The normalization MUST NOT trigger a second LLM
        call. The existing one-call maximum is preserved."""
        flavor = _flavor(codigo="joven")
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(
                message=self._AGG_SUCCESS,
                intent="agregar_producto",
                status="executed",
            )
        ]
        client = _llm(
            {
                "items": [
                    {
                        "index": 0,
                        "prefix": "¡Genial! ",
                        "suffix": " Confirmacion recibida.",
                    }
                ]
            }
        )
        style_responses(db, 1, responses, query_llm=client)
        self.assertEqual(client.request.call_count, 1)

    def test_bounded_diagnostic_under_normalized_guard(self) -> None:
        """Under the normalized guard, the diagnostic MUST
        record the bounded ``wrapper_invalid`` fallback
        category without exposing the rejected wrapper, the
        factual message, the prompt or the flavor instruction."""
        flavor = _flavor(
            codigo="joven",
            instruccion="INSTRUCCION-SECRETA-NORMALIZACION",
        )
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(
                message=self._AGG_SUCCESS,
                intent="agregar_producto",
                status="executed",
            )
        ]
        client = _llm(
            {
                "items": [
                    {
                        "index": 0,
                        "prefix": "¡Genial! ",
                        "suffix": " Confirmacion recibida.",
                    }
                ]
            }
        )
        stream = io.StringIO()
        style_responses(
            db, 1, responses, query_llm=client, stream=stream
        )
        last_event = _last_event(stream)
        self.assertEqual(
            last_event["failure_category"], FALLBACK_WRAPPER_INVALID
        )
        serialized = json.dumps(last_event, sort_keys=True)
        for forbidden in (
            "Confirmacion recibida",
            "Confirmación recibida",
            "Pizza Mozzarella",
            "Mozzarella",
            "INSTRUCCION-SECRETA-NORMALIZACION",
            "Directriz",
            "response_type",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, serialized)

    def test_no_database_transaction_control_under_normalized_guard(
        self,
    ) -> None:
        """The normalized guard is a pure lexical check; it
        MUST NOT invoke any database transaction control method."""
        flavor = _flavor(codigo="joven")
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(
                message=self._AGG_SUCCESS,
                intent="agregar_producto",
                status="executed",
            )
        ]
        client = _llm(
            {
                "items": [
                    {
                        "index": 0,
                        "prefix": "¡Genial! ",
                        "suffix": " Confirmacion recibida.",
                    }
                ]
            }
        )
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


class StyleResponsesWithDiagnosticTest(unittest.TestCase):
    """Subphase 7 — local pilot styling diagnostic handoff.

    The opt-in companion :func:`style_responses_with_diagnostic`
    returns the same styled list as the list-only API plus a
    closed, request-scoped :class:`StyleDiagnostic` companion.
    The companion is built from the same single styling pass so
    the responses and the diagnostic are produced together
    without invoking the styler twice.

    The companion is request-scoped and ephemeral; it never
    carries raw customer text, the rendered messages, prefix /
    suffix, the prompt, the flavor instruction, IDs, timing,
    exception detail, model output or arbitrary event payloads.
    """

    _VER_MENU_FULL = "Menú disponible:"
    _STATUS_MESSAGE = "Tú pedido está en preparación."
    _SALUDO = "¡Hola! Puedo ayudarte a armar tu pedido. Decime qué querés."
    _AGG_SUCCESS = "Listo, agregué 1 Pizza Mozzarella (grande)."

    def test_zero_eligible_returns_not_attempted_with_empty_response_types(self) -> None:
        db = _db_with_flavor(1, flavor=_flavor())
        responses = [
            CustomerResponse(
                message="rejection",
                intent="agregar_producto",
                status="rejected",
            )
        ]
        client = _llm({"items": [{"index": 0, "prefix": "", "suffix": ""}]})
        stream = io.StringIO()
        styled, diagnostic = style_responses_with_diagnostic(
            db, 1, responses, query_llm=client, stream=stream
        )
        self.assertEqual(client.request.call_count, 0)
        self.assertEqual(styled, responses)
        self.assertEqual(diagnostic.outcome, "not_attempted")
        self.assertEqual(diagnostic.eligible_count, 0)
        self.assertEqual(diagnostic.applied_count, 0)
        self.assertEqual(diagnostic.response_types, ())
        self.assertIsNone(diagnostic.fallback_category)
        self.assertIsNone(diagnostic.flavor_code)
        self.assertEqual(diagnostic.template_version, OUTBOUND_STYLE_PROMPT_TEMPLATE_VERSION)

    def test_flavor_not_usable_returns_not_attempted_with_response_types(self) -> None:
        db = _db_with_flavor(1, flavor=_flavor(NEUTRO_FLAVOR_CODE))
        responses = [
            CustomerResponse(
                message=self._SALUDO, intent="saludo", status="executed"
            )
        ]
        client = _llm({"items": [{"index": 0, "prefix": "", "suffix": ""}]})
        stream = io.StringIO()
        styled, diagnostic = style_responses_with_diagnostic(
            db, 1, responses, query_llm=client, stream=stream
        )
        self.assertEqual(client.request.call_count, 0)
        self.assertEqual(styled, responses)
        self.assertEqual(diagnostic.outcome, "not_attempted")
        self.assertEqual(diagnostic.eligible_count, 1)
        self.assertEqual(diagnostic.applied_count, 0)
        self.assertEqual(diagnostic.response_types, (RESPONSE_TYPE_SOCIAL_GREETING,))
        self.assertIsNone(diagnostic.flavor_code)
        self.assertIsNone(diagnostic.fallback_category)

    def test_applied_outcome_carries_flavor_code_and_response_types(self) -> None:
        flavor = _flavor(codigo="joven")
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(
                message=self._VER_MENU_FULL,
                intent="ver_menu",
                status="executed",
            )
        ]
        client = _llm(
            {"items": [{"index": 0, "prefix": "¡Buenas!", "suffix": ""}]}
        )
        stream = io.StringIO()
        styled, diagnostic = style_responses_with_diagnostic(
            db, 1, responses, query_llm=client, stream=stream
        )
        self.assertEqual(diagnostic.outcome, "applied")
        self.assertEqual(diagnostic.flavor_code, "joven")
        self.assertEqual(diagnostic.response_types, (RESPONSE_TYPE_MENU_FULL,))
        self.assertEqual(diagnostic.eligible_count, 1)
        self.assertEqual(diagnostic.applied_count, 1)
        self.assertIsNone(diagnostic.fallback_category)
        self.assertEqual(diagnostic.template_version, OUTBOUND_STYLE_PROMPT_TEMPLATE_VERSION)
        self.assertEqual(styled[0].message, f"¡Buenas!{self._VER_MENU_FULL}")

    def test_status_eligible_under_usable_flavor_is_attempted_not_neutro(self) -> None:
        """The executed status response is an eligible normal
        response under a usable selected flavor. The diagnostic
        MUST carry ``applied`` or a bounded ``fallback``; it
        MUST NEVER masquerade as ``neutro`` by reporting
        ``not_attempted``.
        """
        flavor = _flavor(codigo="joven")
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(
                message=self._STATUS_MESSAGE,
                intent="consultar_estado_pedido",
                status="executed",
            )
        ]
        client = _llm({"items": [{"index": 0, "prefix": "¡Hey!", "suffix": ""}]})
        stream = io.StringIO()
        _styled, diagnostic = style_responses_with_diagnostic(
            db, 1, responses, query_llm=client, stream=stream
        )
        self.assertEqual(diagnostic.outcome, "applied")
        self.assertEqual(diagnostic.flavor_code, "joven")
        self.assertEqual(diagnostic.response_types, (RESPONSE_TYPE_ORDER_STATUS,))

    def test_fallback_outcome_preserves_flavor_and_keeps_factual_intact(self) -> None:
        flavor = _flavor(codigo="joven")
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(
                message=self._VER_MENU_FULL,
                intent="ver_menu",
                status="executed",
            )
        ]
        client = _llm({"items": [{"index": 0, "prefix": "Hello2", "suffix": ""}]})
        stream = io.StringIO()
        styled, diagnostic = style_responses_with_diagnostic(
            db, 1, responses, query_llm=client, stream=stream
        )
        self.assertEqual(diagnostic.outcome, "fallback")
        self.assertEqual(diagnostic.flavor_code, "joven")
        self.assertEqual(diagnostic.fallback_category, FALLBACK_WRAPPER_INVALID)
        self.assertEqual(diagnostic.response_types, (RESPONSE_TYPE_MENU_FULL,))
        self.assertEqual(diagnostic.eligible_count, 1)
        self.assertEqual(diagnostic.applied_count, 0)
        # The factual message is preserved byte-for-byte.
        self.assertEqual(styled[0].message, self._VER_MENU_FULL)

    def test_zero_eligible_hides_flavor_code(self) -> None:
        """``flavor_code`` must be hidden when the attempt never
        reached the prompt stage (zero eligible)."""
        flavor = _flavor(codigo="joven")
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(
                message="rejection",
                intent="agregar_producto",
                status="rejected",
            )
        ]
        client = _llm({"items": [{"index": 0, "prefix": "", "suffix": ""}]})
        _styled, diagnostic = style_responses_with_diagnostic(
            db, 1, responses, query_llm=client
        )
        self.assertEqual(diagnostic.outcome, "not_attempted")
        self.assertIsNone(diagnostic.flavor_code)

    def test_flavor_unusable_hides_flavor_code(self) -> None:
        """``flavor_code`` must be hidden when the flavor was
        ``neutro``, inactive or had no instruction."""
        db = _db_with_flavor(1, flavor=_flavor(NEUTRO_FLAVOR_CODE))
        responses = [
            CustomerResponse(
                message=self._SALUDO, intent="saludo", status="executed"
            )
        ]
        client = _llm({"items": [{"index": 0, "prefix": "", "suffix": ""}]})
        _styled, diagnostic = style_responses_with_diagnostic(
            db, 1, responses, query_llm=client
        )
        self.assertEqual(diagnostic.outcome, "not_attempted")
        self.assertIsNone(diagnostic.flavor_code)

    def test_diagnostic_serializes_without_pii(self) -> None:
        flavor = _flavor(
            codigo="joven",
            instruccion="INSTRUCCION-SECRETA",
        )
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(
                message="Pizza Mozzarella grande",
                intent="agregar_producto",
                status="executed",
            )
        ]
        client = _llm({"items": [{"index": 0, "prefix": "", "suffix": ""}]})
        stream = io.StringIO()
        _styled, diagnostic = style_responses_with_diagnostic(
            db, 1, responses, query_llm=client, stream=stream
        )
        payload = json.dumps(
            {
                "outcome": diagnostic.outcome,
                "eligible_count": diagnostic.eligible_count,
                "applied_count": diagnostic.applied_count,
                "fallback_category": diagnostic.fallback_category,
                "flavor_code": diagnostic.flavor_code,
                "response_types": list(diagnostic.response_types),
                "template_version": diagnostic.template_version,
            },
            sort_keys=True,
        )
        for forbidden in (
            "INSTRUCCION-SECRETA",
            "Pizza Mozzarella",
            "Mozzarella",
            "Ag + Pizza",
            "session-7",
            "pedido-9",
            "comercio-42",
            "+5491100000000",
            "secret-customer-message",
            "Av. Secreta 1234",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, payload)

    def test_diagnostic_mirrors_list_only_api_for_same_inputs(self) -> None:
        """The opt-in companion MUST produce the same response
        list as the list-only API when given the same inputs."""
        flavor = _flavor(codigo="joven")
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
        mock_payload = {
            "items": [
                {"index": 0, "prefix": "¡Hey!", "suffix": ""},
                {"index": 1, "prefix": "", "suffix": " 🎉"},
            ]
        }
        # Use a fresh db and fresh client per call so the assertions
        # stay independent of any cross-call state.
        client_a = MagicMock(name="QueryLlmStubA")
        client_a.request.return_value = mock_payload
        client_b = MagicMock(name="QueryLlmStubB")
        client_b.request.return_value = mock_payload
        styled_only = style_responses(
            _db_with_flavor(1, flavor=flavor),
            1,
            list(responses),
            query_llm=client_a,
        )
        styled_with, diagnostic = style_responses_with_diagnostic(
            _db_with_flavor(1, flavor=flavor),
            1,
            list(responses),
            query_llm=client_b,
        )
        self.assertEqual(styled_with, styled_only)
        self.assertEqual(diagnostic.outcome, "applied")
        self.assertEqual(diagnostic.flavor_code, "joven")
        self.assertEqual(
            diagnostic.response_types,
            (RESPONSE_TYPE_SOCIAL_GREETING, RESPONSE_TYPE_PRODUCT_ADD_SUCCESS),
        )

    def test_diagnostic_does_not_control_database_transactions(self) -> None:
        flavor = _flavor()
        db = _db_with_flavor(1, flavor=flavor)
        responses = [
            CustomerResponse(
                message=self._SALUDO, intent="saludo", status="executed"
            )
        ]
        client = _llm({"items": [{"index": 0, "prefix": "", "suffix": ""}]})
        style_responses_with_diagnostic(db, 1, responses, query_llm=client)
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


if __name__ == "__main__":
    unittest.main(verbosity=2)