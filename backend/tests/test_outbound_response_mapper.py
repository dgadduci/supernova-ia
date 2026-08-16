"""Focused tests for `backend.services.outbound_response_mapper`.

These tests cover the narrow social-conversation response mapping
introduced for the ``add-social-conversation-responses`` OpenSpec
change, plus the guided-closure branches (observation and delivery
address) that share the same private-response contract: the rendered
``CustomerResponse.message`` must not echo the captured free text, and
the mapper must keep the deterministic fixed message for the local
endpoint and the staged provider outbox.

The mapper is the shared translation boundary between the initial
dispatcher and the staged provider outbox, so the tests focus on:

* the deterministic fixed response selected for each of the six
  approved social intents (``saludo``, ``agradecimiento``,
  ``despedida``, ``respuesta_afirmativa``, ``respuesta_negativa``,
  ``desconocida``);
* preservation of the ``intent`` and ``status`` from the source
  ``ProcessedIntent`` on the rendered ``CustomerResponse``;
* response ordering when a social intent is mixed with another
  intent;
* preservation of the existing ``GENERIC_MESSAGE`` fallback for
  classifier intents outside the approved social set (for example
  the deferred ``ver_menu``);
* the dedicated ``set_observacion_pedido`` branch carries the
  observation success/rejection message but never the observation
  text;
* the dedicated ``set_direccion_entrega`` branch carries the
  delivery-address success/rejection message but never the address
  text.
"""
from __future__ import annotations

import importlib
import unittest
from unittest.mock import MagicMock, patch

from backend.intents.responses.draft_order_closure import (
    build_set_direccion_entrega_response,
    build_set_fecha_hora_entrega_response,
)
from backend.intents.responses.social_conversation_response import (
    SOCIAL_CONVERSATION_HANDLER,
    build_social_conversation_response,
    is_social_conversation_intent,
)
from backend.intents.schemas.customer_response import CustomerResponse
from backend.intents.schemas.processed_intent import (
    IntentStatus,
    ProcessedIntent,
)
from backend.services import outbound_response_mapper as mapper_module
from backend.services.outbound_response_mapper import (
    GENERIC_MESSAGE,
    build_customer_responses,
    stage_outbound_rows,
)


def _db() -> MagicMock:
    return MagicMock(name="DatabaseSession")


def _session() -> MagicMock:
    return MagicMock(name="ConversationSession")


def _processed(
    intent: str,
    status: IntentStatus = "executed",
) -> ProcessedIntent:
    return ProcessedIntent(
        intent=intent,
        source_text="irrelevant",
        status=status,
        recognizer="intent_classifier",
        handler=SOCIAL_CONVERSATION_HANDLER,
    )


class IsSocialConversationIntentTest(unittest.TestCase):
    def test_recognises_each_approved_social_intent(self) -> None:
        for name in (
            "saludo",
            "agradecimiento",
            "despedida",
            "respuesta_afirmativa",
            "respuesta_negativa",
            "desconocida",
        ):
            with self.subTest(intent=name):
                self.assertTrue(is_social_conversation_intent(name))

    def test_does_not_recognise_deferred_or_unrelated_intents(self) -> None:
        for name in (
            "agregar_producto",
            "ver_menu",
            "consultar_producto",
            "consultar_estado_pedido",
            "",
        ):
            with self.subTest(intent=name):
                self.assertFalse(is_social_conversation_intent(name))


class BuildSocialConversationResponseTest(unittest.TestCase):
    def test_each_social_intent_renders_deterministic_fixed_message(self) -> None:
        expected = {
            "saludo": "¡Hola! Puedo ayudarte a armar tu pedido. Decime qué querés.",
            "agradecimiento": "¡De nada! Decime si necesitás algo más.",
            "despedida": "¡Gracias por escribirnos! Hasta pronto.",
            "respuesta_afirmativa": (
                "Por ahora no tengo una pregunta activa para confirmar. "
                "Decime qué producto querés agregar o qué necesitás."
            ),
            "respuesta_negativa": (
                "Entendido. Si querés algo, decime qué necesitás."
            ),
            "desconocida": (
                "Disculpá, no entendí tu mensaje. "
                "Podés pedirme el menú o decirme qué producto querés agregar."
            ),
        }
        for name, message in expected.items():
            with self.subTest(intent=name):
                rendered = build_social_conversation_response(
                    _processed(name, status="executed")
                )
                self.assertEqual(rendered.message, message)
                self.assertEqual(rendered.intent, name)
                self.assertEqual(rendered.status, "executed")

    def test_preserves_source_status_on_rendered_response(self) -> None:
        rendered = build_social_conversation_response(
            _processed("agradecimiento", status="executed")
        )
        self.assertEqual(rendered.status, "executed")

    def test_unknown_intent_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            build_social_conversation_response(_processed("ver_menu"))

    def test_builder_does_not_touch_database_or_session(self) -> None:
        db = _db()
        build_social_conversation_response(_processed("saludo"))
        db.commit.assert_not_called()
        db.rollback.assert_not_called()
        db.flush.assert_not_called()
        db.refresh.assert_not_called()
        db.begin.assert_not_called()


class BuildCustomerResponsesSocialIntentsTest(unittest.TestCase):
    @patch.object(mapper_module, "build_social_conversation_response")
    def test_saludo_is_routed_through_social_builder(
        self, social_builder
    ) -> None:
        social_builder.return_value = MagicMock(
            message="social", intent="saludo", status="executed"
        )

        responses = build_customer_responses(
            _db(), _session(), [_processed("saludo")]
        )

        self.assertEqual(len(responses), 1)
        self.assertIs(responses[0], social_builder.return_value)
        social_builder.assert_called_once()

    @patch.object(mapper_module, "build_social_conversation_response")
    def test_each_social_intent_dispatches_to_builder(
        self, social_builder
    ) -> None:
        social_builder.side_effect = [
            MagicMock(message="s", intent=name, status="executed")
            for name in (
                "saludo",
                "agradecimiento",
                "despedida",
                "respuesta_afirmativa",
                "respuesta_negativa",
                "desconocida",
            )
        ]

        intents = [_processed(name) for name in (
            "saludo",
            "agradecimiento",
            "despedida",
            "respuesta_afirmativa",
            "respuesta_negativa",
            "desconocida",
        )]
        responses = build_customer_responses(_db(), _session(), intents)

        self.assertEqual(len(responses), 6)
        self.assertEqual(social_builder.call_count, 6)

    def test_real_builder_renders_deterministic_desconocida_message(self) -> None:
        importlib.reload(mapper_module)
        responses = build_customer_responses(
            _db(),
            _session(),
            [_processed("desconocida", status="executed")],
        )

        self.assertEqual(len(responses), 1)
        rendered = responses[0]
        self.assertEqual(rendered.intent, "desconocida")
        self.assertEqual(rendered.status, "executed")
        self.assertIn("Disculpá", rendered.message)


class BuildCustomerResponsesOrderingTest(unittest.TestCase):
    def test_social_intent_preserves_position_in_mixed_intent_list(self) -> None:
        first = ProcessedIntent(
            intent="agregar_producto",
            source_text="x",
            status="ready",
            handler="agregar_producto",
            recognizer="recognizer_productos",
        )
        middle = _processed("saludo")
        last = ProcessedIntent(
            intent="consultar_estado_pedido",
            source_text="y",
            status="rejected",
            handler="consultar_estado_pedido",
            recognizer="intent_classifier",
        )

        responses = build_customer_responses(_db(), _session(), [first, middle, last])

        self.assertEqual(len(responses), 3)
        self.assertEqual(responses[0].intent, "agregar_producto")
        self.assertEqual(responses[1].intent, "saludo")
        self.assertEqual(responses[1].status, "executed")
        self.assertEqual(responses[2].intent, "consultar_estado_pedido")
        self.assertEqual(
            responses[2].message,
            "No tenés un pedido activo para consultar.",
        )
        self.assertEqual(responses[2].status, "rejected")


class BuildCustomerResponsesGenericFallbackTest(unittest.TestCase):
    def test_deferred_intent_keeps_generic_message(self) -> None:
        responses = build_customer_responses(
            _db(),
            _session(),
            [
                ProcessedIntent(
                    intent="__futuro_deferred_intent__",
                    source_text="x",
                    status="rejected",
                    handler="__futuro_deferred_intent__",
                    recognizer="intent_classifier",
                ),
            ],
        )

        self.assertEqual(len(responses), 1)
        self.assertEqual(responses[0].message, GENERIC_MESSAGE)
        self.assertEqual(responses[0].intent, "__futuro_deferred_intent__")
        self.assertEqual(responses[0].status, "rejected")

    def test_consultar_estado_pedido_routes_to_dedicated_builder(self) -> None:
        responses = build_customer_responses(
            _db(),
            _session(),
            [
                ProcessedIntent(
                    intent="consultar_estado_pedido",
                    source_text="estado de mi pedido",
                    status="rejected",
                    handler="consultar_estado_pedido",
                    recognizer="intent_classifier",
                ),
            ],
        )

        self.assertEqual(len(responses), 1)
        self.assertEqual(
            responses[0].message,
            "No tenés un pedido activo para consultar.",
        )
        self.assertEqual(responses[0].intent, "consultar_estado_pedido")
        self.assertEqual(responses[0].status, "rejected")

    def test_generic_message_is_single_fixed_string(self) -> None:
        self.assertEqual(
            GENERIC_MESSAGE,
            "Disculpá, no pude procesar tu mensaje. ¿Podrías reformularlo?",
        )


class OutboundMapperBoundariesTest(unittest.TestCase):
    def test_module_all_exports_documented_symbols(self) -> None:
        importlib.reload(mapper_module)
        self.assertEqual(
            set(mapper_module.__all__),
            {
                "GENERIC_MESSAGE",
                "StagedOutboundRow",
                "build_customer_responses",
                "stage_outbound_rows",
            },
        )


class OutboundMapperStylerIntegrationTest(unittest.TestCase):
    """The mapper integrates the bounded styler as the shared
    presentation-only post-processor. The local endpoint and the
    staged outbox both consume the styled ``CustomerResponse``
    list produced by :func:`build_customer_responses`; the
    styler is therefore invoked once per turn inside the mapper
    and never from ``stage_outbound_rows``.

    These tests patch the styler entry point exposed by the
    mapper module so the assertions stay at the mapper boundary
    and the styler's own focused tests cover the contract in
    depth.
    """

    _SALUDO_INTENT = "saludo"
    _SALUDO_STATUS = "executed"
    _SALUDO_MESSAGE = (
        "¡Hola! Puedo ayudarte a armar tu pedido. Decime qué querés."
    )

    def _saludo_intent(self) -> ProcessedIntent:
        return ProcessedIntent(
            intent=self._SALUDO_INTENT,
            source_text="hola",
            status=self._SALUDO_STATUS,
            recognizer="intent_classifier",
            handler=SOCIAL_CONVERSATION_HANDLER,
        )

    def test_neutral_flavor_does_not_invoke_styler(self) -> None:
        from backend.services import outbound_response_styler

        with patch.object(
            outbound_response_styler, "QueryLlm"
        ) as query_llm_cls:
            query_llm_cls.return_value.request.side_effect = AssertionError(
                "QueryLlm must not be called for neutro"
            )
            db = MagicMock()
            session = MagicMock(id_comercio=1)
            db.get.side_effect = [
                MagicMock(flavor_comunicacion_id=1),
                MagicMock(activo=True, codigo="neutro", instruccion_llm="neutro"),
            ]
            responses = build_customer_responses(
                db, session, [self._saludo_intent()]
            )
            self.assertEqual(responses[0].message, self._SALUDO_MESSAGE)
            self.assertEqual(query_llm_cls.return_value.request.call_count, 0)

    def test_absent_session_id_comercio_does_not_invoke_styler_with_real_commerce(self) -> None:
        with patch.object(
            mapper_module, "style_responses"
        ) as styler:
            captured: dict = {}

            def _capture(*args, **kwargs):
                captured["comercio_id"] = args[1] if len(args) > 1 else kwargs.get("comercio_id")
                return args[2] if len(args) > 2 else kwargs.get("responses")

            styler.side_effect = _capture
            db = MagicMock()
            session = MagicMock(spec=[])
            build_customer_responses(db, session, [self._saludo_intent()])
            self.assertIsNone(captured.get("comercio_id"))

    def test_stage_outbound_rows_reuses_styler_output_and_does_not_re_invoke_styler(self) -> None:
        with patch.object(mapper_module, "style_responses") as styler:
            def _style(*args, **kwargs):
                responses = (
                    args[2] if len(args) > 2 else kwargs.get("responses")
                ) or []
                styled = []
                for r in responses:
                    styled.append(
                        CustomerResponse(
                            message=f"[X] {r.message}",
                            intent=r.intent,
                            status=r.status,
                        )
                    )
                return styled

            styler.side_effect = _style
            db = MagicMock()
            session = MagicMock(id_comercio=42)
            intent = self._saludo_intent()
            outbox_repo = MagicMock()
            staged_row = MagicMock()
            staged_row.id = 7
            outbox_repo.stage.return_value = staged_row

            result = stage_outbound_rows(
                db,
                session,
                proveedor="twilio",
                recepcion_mensaje_proveedor_id=1,
                destinatario_e164="+5491100000000",
                intents=[intent],
                outbox_repo=outbox_repo,
            )

            self.assertEqual(styler.call_count, 1)
            self.assertEqual(len(result), 1)
            self.assertEqual(
                result[0].customer_response.message, f"[X] {self._SALUDO_MESSAGE}"
            )
            self.assertEqual(
                outbox_repo.stage.call_args.kwargs["cuerpo"],
                f"[X] {self._SALUDO_MESSAGE}",
            )

    def test_mapper_invokes_styler_with_session_id_comercio(self) -> None:
        with patch.object(
            mapper_module, "style_responses"
        ) as styler:
            styler.side_effect = lambda *_args, **_kwargs: (
                _args[2] if len(_args) > 2 else _kwargs.get("responses")
            )
            db = MagicMock()
            session = MagicMock(id_comercio=99)
            build_customer_responses(
                db, session, [self._saludo_intent()]
            )
            self.assertEqual(styler.call_count, 1)
            self.assertEqual(styler.call_args.args[1], 99)

    def test_mapper_preserves_order_intent_status_when_styler_returns_baseline(self) -> None:
        with patch.object(mapper_module, "style_responses") as styler:
            styler.side_effect = lambda *_args, **_kwargs: (
                _args[2] if len(_args) > 2 else _kwargs.get("responses")
            )
            intents = [
                ProcessedIntent(
                    intent="agregar_producto",
                    source_text="x",
                    status="ready",
                    handler="agregar_producto",
                    recognizer="recognizer_productos",
                ),
                self._saludo_intent(),
                ProcessedIntent(
                    intent="set_direccion_entrega",
                    source_text="y",
                    status="executed",
                    handler="set_direccion_entrega",
                    recognizer="draft_order_closure",
                    resolved_data={"accepted_length": 12},
                ),
            ]
            db = MagicMock()
            session = MagicMock(id_comercio=1)
            responses = build_customer_responses(db, session, intents)
            self.assertEqual(len(responses), 3)
            self.assertEqual(responses[0].intent, "agregar_producto")
            self.assertEqual(responses[1].intent, "saludo")
            self.assertEqual(responses[2].intent, "set_direccion_entrega")
            self.assertNotIn("Tilcara", responses[2].message)

    def test_mapper_does_not_control_database_transactions(self) -> None:
        with patch.object(mapper_module, "style_responses") as styler:
            styler.side_effect = lambda *_args, **_kwargs: (
                _args[2] if len(_args) > 2 else _kwargs.get("responses")
            )
            db = MagicMock()
            session = MagicMock(id_comercio=1)
            build_customer_responses(db, session, [self._saludo_intent()])
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


class SetObservacionProductoMapperTest(unittest.TestCase):
    """``set_observacion_producto`` is no longer an active capability.

    The dispatcher produces a single ``rejected`` outcome with the
    ``direct_observation_disabled`` reason for the direct intent
    outside the bounded confirmation context. The mapper renders the
    documented fixed guidance for that shape. Any other payload
    (legacy executed state, unexpected rejection reasons, technical
    failure) reaches the safe fallback with no fake success message
    and no customer content leakage.
    """

    _DIRECT_GUIDANCE = (
        "Por favor, confirmá el pedido para poder agregar una observación."
    )

    def _intent(
        self,
        *,
        status: IntentStatus,
        observation_action: str | None = "set",
        producto_nombre: str | None = "Pizza Mozzarella",
        presentacion_codigo: str | None = "grande",
        observation_text: str | None = "obs-secret",
        reason: str | None = None,
    ) -> ProcessedIntent:
        resolved: dict = {
            "observation_action": observation_action,
        }
        if observation_text is not None:
            resolved["observation_text"] = observation_text
        if producto_nombre is not None:
            resolved["producto_nombre"] = producto_nombre
        if presentacion_codigo is not None:
            resolved["presentacion_codigo"] = presentacion_codigo
        if reason is not None:
            resolved["reason"] = reason
        return ProcessedIntent(
            intent="set_observacion_producto",
            source_text="La pizza es sin aceitunas",
            status=status,
            recognizer="recognizer_set_observacion_producto",
            handler="set_observacion_producto",
            resolved_data=resolved,
        )

    def test_direct_rejection_renders_fixed_guidance(self) -> None:
        intent = self._intent(
            status="rejected",
            reason="direct_observation_disabled",
        )
        mapped = build_customer_responses(
            MagicMock(), MagicMock(), [intent]
        )[0]
        self.assertEqual(mapped.message, self._DIRECT_GUIDANCE)
        self.assertEqual(mapped.intent, "set_observacion_producto")
        self.assertEqual(mapped.status, "rejected")
        self.assertNotIn("obs-secret", mapped.message)
        self.assertNotIn("Pizza Mozzarella", mapped.message)

    def test_outbox_stages_fixed_guidance(self) -> None:
        intent = self._intent(
            status="rejected",
            reason="direct_observation_disabled",
        )
        db = MagicMock()
        session = MagicMock()
        expected = build_customer_responses(db, session, [intent])[0]
        outbox_repo = MagicMock()
        staged_row = MagicMock()
        staged_row.id = 500
        outbox_repo.stage.return_value = staged_row

        result = stage_outbound_rows(
            db,
            session,
            proveedor="twilio",
            recepcion_mensaje_proveedor_id=1,
            destinatario_e164="+5491112345678",
            intents=[intent],
            outbox_repo=outbox_repo,
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].customer_response, expected)
        outbox_repo.stage.assert_called_once()
        self.assertEqual(
            outbox_repo.stage.call_args.kwargs["cuerpo"], expected.message
        )
        self.assertEqual(expected.message, self._DIRECT_GUIDANCE)

    def test_unexpected_payloads_fall_back_without_fake_success(self) -> None:
        for status in ("executed", "rejected", "failed"):
            with self.subTest(status=status):
                intent = self._intent(status=status)
                mapped = build_customer_responses(
                    MagicMock(), MagicMock(), [intent]
                )[0]
                self.assertEqual(mapped.intent, "set_observacion_producto")
                self.assertEqual(mapped.status, status)
                self.assertNotEqual(mapped.message, self._DIRECT_GUIDANCE)
                self.assertNotIn("obs-secret", mapped.message)
                self.assertNotEqual(
                    mapped.message,
                    "Listo, guardé tu observación.",
                )


class SetDireccionEntregaMapperTest(unittest.TestCase):
    """The mapper must route ``set_direccion_entrega`` to the dedicated
    builder so the local endpoint and the staged outbox share the same
    private deterministic message."""

    def _intent(
        self,
        *,
        status: IntentStatus,
        reason: str | None = None,
        length: int | None = None,
    ) -> ProcessedIntent:
        resolved: dict = {}
        if reason is not None:
            resolved["reason"] = reason
        if length is not None:
            resolved["accepted_length"] = length
        return ProcessedIntent(
            intent="set_direccion_entrega",
            source_text="Tilcara 2020",
            status=status,
            recognizer="draft_order_closure",
            handler="set_direccion_entrega",
            resolved_data=resolved,
        )

    def test_mapper_local_and_shared_builder_are_equivalent(self) -> None:
        intent = self._intent(status="executed", length=12)
        db = MagicMock()
        session = MagicMock()
        local = build_set_direccion_entrega_response(db, session, intent)
        mapped = build_customer_responses(db, session, [intent])[0]
        self.assertEqual(mapped, local)
        self.assertNotIn("Tilcara", mapped.message)
        self.assertNotIn("2020", mapped.message)

    def test_executed_renders_fixed_confirmation(self) -> None:
        intent = self._intent(status="executed", length=12)
        mapped = build_customer_responses(MagicMock(), MagicMock(), [intent])[0]
        self.assertEqual(mapped.status, "executed")
        self.assertEqual(mapped.intent, "set_direccion_entrega")
        self.assertIn("dirección", mapped.message.lower())
        self.assertNotIn("Tilcara", mapped.message)
        self.assertNotIn("2020", mapped.message)

    def test_rejected_renders_safe_message(self) -> None:
        for reason in (
            "text_empty",
            "text_too_long",
            "no_draft",
            "session_mismatch",
            "session_not_active",
            "pedido_not_borrador",
        ):
            with self.subTest(reason=reason):
                intent = self._intent(status="rejected", reason=reason)
                mapped = build_customer_responses(
                    MagicMock(), MagicMock(), [intent]
                )[0]
                self.assertEqual(mapped.status, "rejected")
                self.assertEqual(mapped.intent, "set_direccion_entrega")
                self.assertNotIn(reason, mapped.message)
                self.assertNotIn("Tilcara", mapped.message)

    def test_failed_renders_generic_message(self) -> None:
        intent = self._intent(status="failed")
        mapped = build_customer_responses(MagicMock(), MagicMock(), [intent])[0]
        self.assertEqual(mapped.status, "failed")
        self.assertIn("técnico", mapped.message.lower())
        self.assertNotIn("Tilcara", mapped.message)

    def test_outbox_staging_uses_the_same_message(self) -> None:
        intent = self._intent(status="executed", length=12)
        db = MagicMock()
        session = MagicMock()
        expected = build_customer_responses(db, session, [intent])[0]
        outbox_repo = MagicMock()
        staged_row = MagicMock()
        staged_row.id = 200
        outbox_repo.stage.return_value = staged_row

        result = stage_outbound_rows(
            db,
            session,
            proveedor="twilio",
            recepcion_mensaje_proveedor_id=1,
            destinatario_e164="+5491112345678",
            intents=[intent],
            outbox_repo=outbox_repo,
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].customer_response, expected)
        outbox_repo.stage.assert_called_once()
        self.assertEqual(
            outbox_repo.stage.call_args.kwargs["cuerpo"], expected.message
        )
        self.assertNotIn("Tilcara", expected.message)
        self.assertEqual(result[0].sequence, 0)


class SetFechaHoraEntregaMapperTest(unittest.TestCase):
    @staticmethod
    def _intent(
        *,
        status: IntentStatus,
        reason: str | None = None,
        accepted_format: str | None = None,
    ) -> ProcessedIntent:
        resolved: dict = {}
        if reason is not None:
            resolved["reason"] = reason
        if accepted_format is not None:
            resolved["accepted_format"] = accepted_format
        return ProcessedIntent(
            intent="set_fecha_hora_entrega",
            source_text="15/08/2026 19:30",
            status=status,
            recognizer="draft_order_closure",
            handler="set_fecha_hora_entrega",
            resolved_data=resolved,
        )

    def test_mapper_and_shared_builder_are_equivalent(self) -> None:
        intent = self._intent(
            status="executed",
            accepted_format="dd/mm/yyyy_hh:mm",
        )
        db = MagicMock()
        session = MagicMock()
        local = build_set_fecha_hora_entrega_response(db, session, intent)
        mapped = build_customer_responses(db, session, [intent])[0]
        self.assertEqual(mapped, local)
        self.assertNotIn("15/08/2026 19:30", mapped.message)
        self.assertNotIn("Buenos Aires", mapped.message)

    def test_executed_renders_fixed_confirmation(self) -> None:
        intent = self._intent(
            status="executed",
            accepted_format="yyyy-mm-dd_hh:mm",
        )
        mapped = build_customer_responses(MagicMock(), MagicMock(), [intent])[0]
        self.assertEqual(mapped.status, "executed")
        self.assertEqual(mapped.intent, "set_fecha_hora_entrega")
        self.assertEqual(
            mapped.message,
            "Listo, guardé la fecha y hora de entrega.",
        )
        self.assertNotIn("2026-08-15 19:30", mapped.message)
        self.assertNotIn("America/Argentina/Buenos_Aires", mapped.message)

    def test_all_rejections_render_safe_message(self) -> None:
        for reason in (
            "invalid_format",
            "past_datetime",
            "no_draft",
            "session_mismatch",
            "session_not_active",
            "pedido_not_borrador",
        ):
            with self.subTest(reason=reason):
                intent = self._intent(status="rejected", reason=reason)
                mapped = build_customer_responses(
                    MagicMock(), MagicMock(), [intent]
                )[0]
                self.assertEqual(mapped.status, "rejected")
                self.assertEqual(mapped.intent, "set_fecha_hora_entrega")
                self.assertNotIn(reason, mapped.message)
                self.assertNotIn("15/08/2026", mapped.message)
                self.assertNotIn("19:30", mapped.message)
                self.assertNotIn("Buenos Aires", mapped.message)

    def test_failed_renders_generic_message(self) -> None:
        intent = self._intent(status="failed")
        mapped = build_customer_responses(MagicMock(), MagicMock(), [intent])[0]
        self.assertEqual(mapped.status, "failed")
        self.assertIn("técnico", mapped.message.lower())
        self.assertNotIn("15/08/2026 19:30", mapped.message)

    def test_outbox_staging_uses_same_message(self) -> None:
        intent = self._intent(
            status="executed",
            accepted_format="dd/mm/yyyy_hh:mm",
        )
        db = MagicMock()
        session = MagicMock()
        expected = build_customer_responses(db, session, [intent])[0]
        outbox_repo = MagicMock()
        staged_row = MagicMock()
        staged_row.id = 300
        outbox_repo.stage.return_value = staged_row

        result = stage_outbound_rows(
            db,
            session,
            proveedor="twilio",
            recepcion_mensaje_proveedor_id=1,
            destinatario_e164="+5491112345678",
            intents=[intent],
            outbox_repo=outbox_repo,
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].customer_response, expected)
        self.assertEqual(
            outbox_repo.stage.call_args.kwargs["cuerpo"],
            expected.message,
        )
        self.assertNotIn("15/08/2026 19:30", expected.message)
        self.assertNotIn("dd/mm/yyyy_hh:mm", expected.message)

    def test_spanish_executed_renders_fixed_confirmation(self) -> None:
        intent = self._intent(
            status="executed",
            accepted_format="spanish_relative",
        )
        db = MagicMock()
        session = MagicMock()
        local = build_set_fecha_hora_entrega_response(db, session, intent)
        mapped = build_customer_responses(db, session, [intent])[0]
        self.assertEqual(mapped, local)
        self.assertEqual(
            mapped.message,
            "Listo, guardé la fecha y hora de entrega.",
        )
        self.assertNotIn("spanish_relative", mapped.message)
        self.assertNotIn("hoy a las 22 horas", mapped.message)

    def test_needs_date_rejection_renders_distinct_message(self) -> None:
        intent = self._intent(status="rejected", reason="needs_date")
        mapped = build_customer_responses(MagicMock(), MagicMock(), [intent])[0]
        self.assertEqual(mapped.status, "rejected")
        self.assertEqual(mapped.intent, "set_fecha_hora_entrega")
        self.assertNotIn("needs_date", mapped.message)
        self.assertNotIn("a las 11 de la noche", mapped.message)
        self.assertNotIn("15/08/2026", mapped.message)
        self.assertNotIn("America/Argentina", mapped.message)

    def test_past_datetime_rejection_renders_distinct_message(self) -> None:
        intent = self._intent(status="rejected", reason="past_datetime")
        mapped = build_customer_responses(MagicMock(), MagicMock(), [intent])[0]
        self.assertEqual(mapped.status, "rejected")
        self.assertEqual(mapped.intent, "set_fecha_hora_entrega")
        self.assertNotIn("past_datetime", mapped.message)
        self.assertNotIn("hoy a las 22", mapped.message)
        self.assertNotIn("ya pasó", "")
        self.assertIn("ya pasó", mapped.message)

    def test_invalid_format_rejection_renders_distinct_message(self) -> None:
        intent = self._intent(status="rejected", reason="invalid_format")
        mapped = build_customer_responses(MagicMock(), MagicMock(), [intent])[0]
        self.assertEqual(mapped.status, "rejected")
        self.assertEqual(mapped.intent, "set_fecha_hora_entrega")
        self.assertNotIn("invalid_format", mapped.message)
        self.assertNotIn("En dos horas", mapped.message)
        self.assertIn("'hoy'", mapped.message)

    def test_spanish_outbox_staging_uses_the_same_message(self) -> None:
        intent = self._intent(
            status="executed",
            accepted_format="spanish_relative",
        )
        db = MagicMock()
        session = MagicMock()
        expected = build_customer_responses(db, session, [intent])[0]
        outbox_repo = MagicMock()
        staged_row = MagicMock()
        staged_row.id = 400
        outbox_repo.stage.return_value = staged_row

        result = stage_outbound_rows(
            db,
            session,
            proveedor="twilio",
            recepcion_mensaje_proveedor_id=1,
            destinatario_e164="+5491112345678",
            intents=[intent],
            outbox_repo=outbox_repo,
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].customer_response, expected)
        self.assertEqual(
            outbox_repo.stage.call_args.kwargs["cuerpo"],
            expected.message,
        )
        self.assertNotIn("spanish_relative", expected.message)


if __name__ == "__main__":
    unittest.main(verbosity=2)
