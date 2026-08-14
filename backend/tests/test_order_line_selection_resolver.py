import importlib
import unittest
from unittest.mock import MagicMock, patch

from sqlalchemy.orm import Session as DatabaseSession

from backend.intents.context import (
    order_line_selection_resolver as resolver_module,
)
from backend.intents.context.order_line_selection_resolver import (
    resolve_order_line_selection,
)
from backend.intents.orchestration.pending_context_dispatcher import (
    dispatch_pending_context,
)
from backend.intents.schemas.processed_intent import ProcessedIntent
from backend.intents.schemas.requirement_state import RequirementState
from backend.models.session import Session as ConversationSession


def _active_intent(candidate_ids: list[int]) -> ProcessedIntent:
    return ProcessedIntent(
        intent="quitar_producto",
        source_text="quitá una pizza",
        status="pending_resolution",
        recognizer="recognizer_quitar_producto",
        handler="quitar_producto",
        resolved_data={},
        requirements=[
            RequirementState(name="pedido_producto_id", status="pending", value=None),
            RequirementState(name="cantidad", status="pending", value=None),
        ],
        candidate_ids=list(candidate_ids),
    )


class ResolveOrderLineSelectionNarrowingTest(unittest.TestCase):
    @patch.object(resolver_module, "recognize_quitar_producto")
    def test_refinement_to_single_returns_ready(self, recognize):
        recognize.return_value = {
            "encontrados": [{"pedido_producto_id": 102}],
            "encontrados_posibles": [],
            "encontrados_no_disponibles": [],
            "no_encontrados": [],
            "cantidad": None,
        }
        active = _active_intent(candidate_ids=[101, 102, 103])

        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        result = resolve_order_line_selection(db, session, "la de muzzarella", active)

        self.assertEqual(result.status, "ready")
        self.assertEqual(result.candidate_ids, [])
        self.assertEqual(result.resolved_data["pedido_producto_id"], 102)
        req_names = {r.name: r.status for r in result.requirements}
        self.assertEqual(req_names.get("pedido_producto_id"), "completed")

    @patch.object(resolver_module, "recognize_quitar_producto")
    def test_refinement_to_subset_keeps_pending(self, recognize):
        recognize.return_value = {
            "encontrados": [],
            "encontrados_posibles": [
                {
                    "texto_origen": "la grande",
                    "productos": [
                        {"pedido_producto_id": 102},
                        {"pedido_producto_id": 104},
                    ],
                }
            ],
            "encontrados_no_disponibles": [],
            "no_encontrados": [],
            "cantidad": None,
        }
        active = _active_intent(candidate_ids=[101, 102, 103, 104, 105])

        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        result = resolve_order_line_selection(db, session, "la grande", active)

        self.assertEqual(result.status, "pending_resolution")
        self.assertEqual(set(result.candidate_ids), {102, 104})
        self.assertNotIn(101, result.candidate_ids)
        self.assertNotIn(103, result.candidate_ids)
        self.assertNotIn(105, result.candidate_ids)


class ResolveOrderLineSelectionRejectionTest(unittest.TestCase):
    @patch.object(resolver_module, "recognize_quitar_producto")
    def test_invalid_candidate_returns_rejected_without_mutation(
        self, recognize
    ):
        recognize.return_value = {
            "encontrados": [{"pedido_producto_id": 999}],
            "encontrados_posibles": [],
            "encontrados_no_disponibles": [],
            "no_encontrados": [],
            "cantidad": None,
        }
        active = _active_intent(candidate_ids=[101, 102])

        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        result = resolve_order_line_selection(db, session, "x", active)

        self.assertEqual(result.status, "rejected")
        self.assertEqual(result.candidate_ids, [101, 102])

    @patch.object(resolver_module, "recognize_quitar_producto")
    def test_no_match_keeps_active_unchanged(self, recognize):
        recognize.return_value = {
            "encontrados": [],
            "encontrados_posibles": [],
            "encontrados_no_disponibles": [],
            "no_encontrados": [{"texto_origen": "x"}],
            "cantidad": None,
        }
        active = _active_intent(candidate_ids=[101, 102])

        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        result = resolve_order_line_selection(db, session, "gibberish", active)

        self.assertEqual(result.status, "pending_resolution")
        self.assertEqual(result.candidate_ids, [101, 102])


class ResolveOrderLineSelectionBoundariesTest(unittest.TestCase):
    def test_module_does_not_broaden_to_commerce_catalog(self):
        with open(resolver_module.__file__, encoding="utf-8") as fh:
            source = fh.read()
        self.assertNotIn("list_recognizer_catalog", source)
        self.assertNotIn("from backend.services.producto_query_service", source)

    def test_module_does_not_import_disallowed_side_effects(self):
        importlib.reload(resolver_module)
        with open(resolver_module.__file__, encoding="utf-8") as fh:
            source = fh.read()
        for forbidden in (
            "db.commit",
            "db.rollback",
            "db.flush",
            "from sqlalchemy import select",
            "from backend.repositories",
            "from backend.routers",
            "from backend.llm",
            "backend.old_project",
            "import requests",
            "from requests",
            "import fastapi",
            "from fastapi",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)

    def test_public_surface_is_limited(self):
        self.assertEqual(
            resolver_module.__all__,
            ["resolve_order_line_selection"],
        )


class ResolveOrderLineSelectionSetObservacionTest(unittest.TestCase):
    """The same resolver narrows `set_observacion_producto` pending
    intents without rewriting the original action or text."""

    def _active(self, candidate_ids: list[int]) -> ProcessedIntent:
        return ProcessedIntent(
            intent="set_observacion_producto",
            source_text="La pizza es sin aceitunas",
            status="pending_resolution",
            recognizer="recognizer_set_observacion_producto",
            handler="set_observacion_producto",
            resolved_data={
                "observation_action": "set",
                "observation_text": "La pizza es sin aceitunas",
            },
            requirements=[
                RequirementState(
                    name="pedido_producto_id", status="pending", value=None
                ),
                RequirementState(
                    name="observacion",
                    status="completed",
                    value="set",
                ),
            ],
            candidate_ids=list(candidate_ids),
        )

    @patch.object(resolver_module, "recognize_quitar_producto")
    def test_clarification_preserves_set_action_and_text(self, recognize):
        recognize.return_value = {
            "encontrados": [{"pedido_producto_id": 11}],
            "encontrados_posibles": [],
            "encontrados_no_disponibles": [],
            "no_encontrados": [],
            "cantidad": None,
        }
        active = self._active(candidate_ids=[10, 11])

        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        result = resolve_order_line_selection(db, session, "la grande", active)

        self.assertEqual(result.status, "ready")
        self.assertEqual(result.intent, "set_observacion_producto")
        self.assertEqual(result.handler, "set_observacion_producto")
        self.assertEqual(result.candidate_ids, [])
        self.assertEqual(result.resolved_data["pedido_producto_id"], 11)
        self.assertEqual(result.resolved_data["observation_action"], "set")
        self.assertEqual(
            result.resolved_data["observation_text"],
            "La pizza es sin aceitunas",
        )
        req_names = {r.name: r.status for r in result.requirements}
        self.assertEqual(req_names.get("pedido_producto_id"), "completed")
        self.assertEqual(req_names.get("observacion"), "completed")

    @patch.object(resolver_module, "recognize_quitar_producto")
    def test_clarification_preserves_clear_action(self, recognize):
        recognize.return_value = {
            "encontrados": [{"pedido_producto_id": 11}],
            "encontrados_posibles": [],
            "encontrados_no_disponibles": [],
            "no_encontrados": [],
            "cantidad": None,
        }
        active = ProcessedIntent(
            intent="set_observacion_producto",
            source_text="Quitar la aclaración de la pizza",
            status="pending_resolution",
            recognizer="recognizer_set_observacion_producto",
            handler="set_observacion_producto",
            resolved_data={"observation_action": "clear"},
            requirements=[
                RequirementState(
                    name="pedido_producto_id", status="pending", value=None
                ),
                RequirementState(
                    name="observacion",
                    status="completed",
                    value="clear",
                ),
            ],
            candidate_ids=[10, 11],
        )

        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        result = resolve_order_line_selection(db, session, "la grande", active)

        self.assertEqual(result.status, "ready")
        self.assertEqual(result.resolved_data["observation_action"], "clear")
        self.assertNotIn(
            "Quitar la aclaración de la pizza",
            result.resolved_data.get("observation_text", ""),
        )

    @patch.object(resolver_module, "recognize_quitar_producto")
    def test_clarification_outside_set_keeps_rejected(self, recognize):
        recognize.return_value = {
            "encontrados": [{"pedido_producto_id": 99}],
            "encontrados_posibles": [],
            "encontrados_no_disponibles": [],
            "no_encontrados": [],
            "cantidad": None,
        }
        active = self._active(candidate_ids=[10, 11])

        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        result = resolve_order_line_selection(db, session, "x", active)

        self.assertEqual(result.status, "rejected")
        self.assertEqual(result.candidate_ids, [10, 11])


class ResolveOrderLineSelectionBarePresentationTest(unittest.TestCase):
    """Deterministic ``chica`` / ``grande`` clarification for the
    pending ``quitar_producto`` order-line selection.

    These tests pin the contract introduced for the
    ``fix-order-line-size-only-pending-selection`` change: a bare
    normalized presentation code (``chica``, ``grande``) or the same
    code with a single leading Spanish article selects the unique
    matching active ``pedido_producto_id``. Anything else falls
    through to the existing restricted recognizer/intersection path
    without widening the candidate set.
    """

    def _pp(self, pp_id: int, codigo: str) -> MagicMock:
        pp = MagicMock(id=pp_id)
        pp.producto_presentacion.presentacion.codigo = codigo
        return pp

    def _service_rows(self, rows: list[MagicMock]) -> MagicMock:
        service = MagicMock()
        service.list_by_pedido.return_value = rows
        return service

    @patch.object(resolver_module, "PedidoProductoService")
    @patch.object(resolver_module, "recognize_quitar_producto")
    def test_chica_resolves_only_chica_line(self, recognize, service_cls):
        service = self._service_rows(
            [self._pp(201, "chica"), self._pp(202, "grande")],
        )
        service_cls.return_value = service
        active = _active_intent(candidate_ids=[201, 202])

        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        session.id_pedido = 7

        result = resolve_order_line_selection(db, session, "Chica", active)

        self.assertEqual(result.status, "ready")
        self.assertEqual(result.candidate_ids, [])
        self.assertEqual(result.resolved_data["pedido_producto_id"], 201)
        self.assertEqual(result.intent, "quitar_producto")
        self.assertEqual(result.handler, "quitar_producto")
        recognize.assert_not_called()
        service_cls.assert_called_once_with(db)
        service.list_by_pedido.assert_called_once_with(7)
        for forbidden in (
            "commit", "rollback", "flush", "refresh", "begin", "close",
        ):
            self.assertFalse(
                getattr(db, forbidden).called,
                f"resolver must not call db.{forbidden}()",
            )

    @patch.object(resolver_module, "PedidoProductoService")
    @patch.object(resolver_module, "recognize_quitar_producto")
    def test_chica_lowercase_resolves_only_chica_line(
        self, recognize, service_cls
    ):
        service_cls.return_value = self._service_rows(
            [self._pp(201, "chica"), self._pp(202, "grande")],
        )
        active = _active_intent(candidate_ids=[201, 202])

        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        session.id_pedido = 7

        result = resolve_order_line_selection(db, session, "chica", active)

        self.assertEqual(result.status, "ready")
        self.assertEqual(result.resolved_data["pedido_producto_id"], 201)
        recognize.assert_not_called()

    @patch.object(resolver_module, "PedidoProductoService")
    @patch.object(resolver_module, "recognize_quitar_producto")
    def test_la_chica_resolves_only_chica_line(self, recognize, service_cls):
        service_cls.return_value = self._service_rows(
            [self._pp(201, "chica"), self._pp(202, "grande")],
        )
        active = _active_intent(candidate_ids=[201, 202])

        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        session.id_pedido = 7

        result = resolve_order_line_selection(db, session, "la chica", active)

        self.assertEqual(result.status, "ready")
        self.assertEqual(result.resolved_data["pedido_producto_id"], 201)
        recognize.assert_not_called()

    @patch.object(resolver_module, "PedidoProductoService")
    @patch.object(resolver_module, "recognize_quitar_producto")
    def test_grande_resolves_only_grande_line(self, recognize, service_cls):
        service_cls.return_value = self._service_rows(
            [self._pp(201, "chica"), self._pp(202, "grande")],
        )
        active = _active_intent(candidate_ids=[201, 202])

        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        session.id_pedido = 7

        result = resolve_order_line_selection(db, session, "Grande", active)

        self.assertEqual(result.status, "ready")
        self.assertEqual(result.resolved_data["pedido_producto_id"], 202)
        recognize.assert_not_called()

    @patch.object(resolver_module, "PedidoProductoService")
    @patch.object(resolver_module, "recognize_quitar_producto")
    def test_una_grande_resolves_only_grande_line(
        self, recognize, service_cls
    ):
        service_cls.return_value = self._service_rows(
            [self._pp(201, "chica"), self._pp(202, "grande")],
        )
        active = _active_intent(candidate_ids=[201, 202])

        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        session.id_pedido = 7

        result = resolve_order_line_selection(
            db, session, "una grande", active,
        )

        self.assertEqual(result.status, "ready")
        self.assertEqual(result.resolved_data["pedido_producto_id"], 202)
        recognize.assert_not_called()

    @patch.object(resolver_module, "PedidoProductoService")
    @patch.object(resolver_module, "recognize_quitar_producto")
    def test_deterministic_match_preserves_resolved_data_and_requirements(
        self, recognize, service_cls
    ):
        """Original ``resolved_data`` (cantidad, etc.) and the
        original requirements other than ``pedido_producto_id`` are
        preserved verbatim by the deterministic pre-check.
        """
        service_cls.return_value = self._service_rows(
            [self._pp(201, "chica"), self._pp(202, "grande")],
        )
        active = ProcessedIntent(
            intent="quitar_producto",
            source_text="quitá una pizza",
            status="pending_resolution",
            recognizer="recognizer_quitar_producto",
            handler="quitar_producto",
            resolved_data={"cantidad": 2, "nota": "sin aceitunas"},
            requirements=[
                RequirementState(
                    name="pedido_producto_id", status="pending", value=None,
                ),
                RequirementState(
                    name="cantidad", status="completed", value=2,
                ),
                RequirementState(
                    name="observacion", status="pending", value=None,
                ),
            ],
            candidate_ids=[201, 202],
        )

        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        session.id_pedido = 7

        result = resolve_order_line_selection(db, session, "Chica", active)

        self.assertEqual(result.status, "ready")
        self.assertEqual(result.candidate_ids, [])
        self.assertEqual(result.resolved_data["pedido_producto_id"], 201)
        self.assertEqual(result.resolved_data["cantidad"], 2)
        self.assertEqual(result.resolved_data["nota"], "sin aceitunas")
        req_by_name = {r.name: r for r in result.requirements}
        self.assertEqual(
            req_by_name["pedido_producto_id"].status, "completed",
        )
        self.assertEqual(
            req_by_name["pedido_producto_id"].value, 201,
        )
        self.assertEqual(req_by_name["cantidad"].status, "completed")
        self.assertEqual(req_by_name["cantidad"].value, 2)
        self.assertEqual(req_by_name["observacion"].status, "pending")
        self.assertEqual(req_by_name["observacion"].value, None)
        recognize.assert_not_called()

    @patch.object(resolver_module, "PedidoProductoService")
    @patch.object(resolver_module, "recognize_quitar_producto")
    def test_foreign_pedido_producto_with_matching_codigo_is_not_selected(
        self, recognize, service_cls
    ):
        """A line outside ``candidate_ids`` (e.g. another pedido or
        commerce) is never selected, even when its
        ``presentacion.codigo`` matches the reply. Only the persisted
        ``candidate_ids`` participate in the deterministic match.
        """
        service_cls.return_value = self._service_rows(
            [
                self._pp(201, "docena"),
                self._pp(202, "familiar"),
                self._pp(999, "chica"),
            ],
        )
        active = _active_intent(candidate_ids=[201, 202])

        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        session.id_pedido = 7

        result = resolve_order_line_selection(db, session, "Chica", active)

        self.assertNotEqual(result.resolved_data.get("pedido_producto_id"), 999)
        self.assertNotIn(999, result.candidate_ids)
        if result.status == "ready":
            self.assertNotEqual(
                result.resolved_data.get("pedido_producto_id"), 999,
            )

    @patch.object(resolver_module, "PedidoProductoService")
    @patch.object(resolver_module, "recognize_quitar_producto")
    def test_napolitana_chica_does_not_select_mozzarella_chica(
        self, recognize, service_cls
    ):
        """``Napolitana chica`` must NOT select ``Mozzarella Chica``
        by suffix. The deterministic pre-check returns ``None`` and
        the existing restricted recognizer/intersection path runs
        without widening the candidate set.
        """
        recognize.return_value = {
            "encontrados": [],
            "encontrados_posibles": [],
            "encontrados_no_disponibles": [],
            "no_encontrados": [{"texto_origen": "Napolitana chica"}],
            "cantidad": None,
        }
        service_cls.return_value = self._service_rows(
            [self._pp(201, "chica"), self._pp(202, "grande")],
        )
        active = _active_intent(candidate_ids=[201, 202])

        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        session.id_pedido = 7

        result = resolve_order_line_selection(
            db, session, "Napolitana chica", active,
        )

        self.assertEqual(result.status, "pending_resolution")
        self.assertEqual(result.candidate_ids, [201, 202])
        self.assertNotIn("pedido_producto_id", result.resolved_data)
        recognize.assert_called_once_with(db, session, "Napolitana chica")

    @patch.object(resolver_module, "PedidoProductoService")
    @patch.object(resolver_module, "recognize_quitar_producto")
    def test_empty_text_falls_through_to_recognizer(
        self, recognize, service_cls
    ):
        recognize.return_value = {
            "encontrados": [],
            "encontrados_posibles": [],
            "encontrados_no_disponibles": [],
            "no_encontrados": [{"texto_origen": ""}],
            "cantidad": None,
        }
        service_cls.return_value = self._service_rows(
            [self._pp(201, "chica"), self._pp(202, "grande")],
        )
        active = _active_intent(candidate_ids=[201, 202])

        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        session.id_pedido = 7

        result = resolve_order_line_selection(db, session, "", active)

        self.assertEqual(result.status, "pending_resolution")
        self.assertEqual(result.candidate_ids, [201, 202])
        recognize.assert_called_once_with(db, session, "")

    @patch.object(resolver_module, "PedidoProductoService")
    @patch.object(resolver_module, "recognize_quitar_producto")
    def test_no_match_falls_through_without_widening(
        self, recognize, service_cls
    ):
        """A bare code that no candidate uses falls through to the
        recognizer and never widens the candidate set."""
        recognize.return_value = {
            "encontrados": [],
            "encontrados_posibles": [],
            "encontrados_no_disponibles": [],
            "no_encontrados": [{"texto_origen": "docena"}],
            "cantidad": None,
        }
        service_cls.return_value = self._service_rows(
            [self._pp(201, "chica"), self._pp(202, "grande")],
        )
        active = _active_intent(candidate_ids=[201, 202])

        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        session.id_pedido = 7

        result = resolve_order_line_selection(db, session, "docena", active)

        self.assertEqual(result.status, "pending_resolution")
        self.assertEqual(result.candidate_ids, [201, 202])
        self.assertNotIn(999, result.candidate_ids)
        recognize.assert_called_once_with(db, session, "docena")

    @patch.object(resolver_module, "PedidoProductoService")
    @patch.object(resolver_module, "recognize_quitar_producto")
    def test_unsupported_intent_skips_bare_presentation_match(
        self, recognize, service_cls
    ):
        """The deterministic pre-check is only for
        ``quitar_producto``; ``set_observacion_producto`` follows
        the existing restricted recognizer path even for bare
        presentation codes.
        """
        recognize.return_value = {
            "encontrados": [{"pedido_producto_id": 11}],
            "encontrados_posibles": [],
            "encontrados_no_disponibles": [],
            "no_encontrados": [],
            "cantidad": None,
        }
        service_cls.return_value = self._service_rows(
            [self._pp(10, "chica"), self._pp(11, "chica")],
        )
        active = ProcessedIntent(
            intent="set_observacion_producto",
            source_text="La pizza es sin aceitunas",
            status="pending_resolution",
            recognizer="recognizer_set_observacion_producto",
            handler="set_observacion_producto",
            resolved_data={
                "observation_action": "set",
                "observation_text": "La pizza es sin aceitunas",
            },
            requirements=[
                RequirementState(
                    name="pedido_producto_id", status="pending", value=None,
                ),
                RequirementState(
                    name="observacion", status="completed", value="set",
                ),
            ],
            candidate_ids=[10, 11],
        )

        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        session.id_pedido = 7

        result = resolve_order_line_selection(db, session, "Chica", active)

        self.assertEqual(result.status, "ready")
        self.assertEqual(result.intent, "set_observacion_producto")
        self.assertEqual(result.handler, "set_observacion_producto")
        self.assertEqual(result.resolved_data["pedido_producto_id"], 11)
        self.assertEqual(
            result.resolved_data["observation_action"], "set",
        )
        self.assertEqual(
            result.resolved_data["observation_text"],
            "La pizza es sin aceitunas",
        )
        recognize.assert_called_once_with(db, session, "Chica")

    @patch.object(resolver_module, "PedidoProductoService")
    @patch.object(resolver_module, "recognize_quitar_producto")
    def test_duplicate_code_falls_through_to_recognizer(
        self, recognize, service_cls
    ):
        """When two active candidates share the same presentation
        code the pre-check is inconclusive; the resolver falls
        through to the existing recognizer/intersection path.
        """
        recognize.return_value = {
            "encontrados": [],
            "encontrados_posibles": [],
            "encontrados_no_disponibles": [],
            "no_encontrados": [{"texto_origen": "Chica"}],
            "cantidad": None,
        }
        service_cls.return_value = self._service_rows(
            [
                self._pp(201, "chica"),
                self._pp(202, "chica"),
                self._pp(203, "grande"),
            ],
        )
        active = _active_intent(candidate_ids=[201, 202, 203])

        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        session.id_pedido = 7

        result = resolve_order_line_selection(db, session, "Chica", active)

        self.assertEqual(result.status, "pending_resolution")
        self.assertEqual(set(result.candidate_ids), {201, 202, 203})
        recognize.assert_called_once_with(db, session, "Chica")

    @patch.object(resolver_module, "PedidoProductoService")
    @patch.object(resolver_module, "recognize_quitar_producto")
    def test_missing_pedido_falls_through_to_recognizer(
        self, recognize, service_cls
    ):
        recognize.return_value = {
            "encontrados": [],
            "encontrados_posibles": [],
            "encontrados_no_disponibles": [],
            "no_encontrados": [{"texto_origen": "Chica"}],
            "cantidad": None,
        }
        service_cls.return_value = self._service_rows(
            [self._pp(201, "chica"), self._pp(202, "grande")],
        )
        active = _active_intent(candidate_ids=[201, 202])

        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        session.id_pedido = None

        result = resolve_order_line_selection(db, session, "Chica", active)

        self.assertEqual(result.status, "pending_resolution")
        self.assertEqual(result.candidate_ids, [201, 202])
        recognize.assert_called_once_with(db, session, "Chica")
        service_cls.assert_not_called()

    @patch.object(resolver_module, "PedidoProductoService")
    @patch.object(resolver_module, "recognize_quitar_producto")
    def test_operational_error_propagates_without_invoking_recognizer(
        self, recognize, service_cls
    ):
        """A transient ``OperationalError`` on the pedido line read
        MUST propagate out of the resolver unchanged. Hiding it as a
        fallback to ``recognize_quitar_producto`` would silently
        retry the same read and could end in a selection/mutation on
        a transient failure.
        """
        from sqlalchemy.exc import OperationalError

        service = MagicMock()
        service.list_by_pedido.side_effect = OperationalError(
            "stmt", {}, Exception("db boom"),
        )
        service_cls.return_value = service
        active = _active_intent(candidate_ids=[201, 202])

        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        session.id_pedido = 7

        with self.assertRaises(OperationalError):
            resolve_order_line_selection(db, session, "Chica", active)

        recognize.assert_not_called()
        service.list_by_pedido.assert_called_once_with(7)
        for forbidden in (
            "commit", "rollback", "flush", "refresh", "begin", "close",
        ):
            self.assertFalse(
                getattr(db, forbidden).called,
                f"resolver must not call db.{forbidden}() on error",
            )

    @patch.object(resolver_module, "PedidoProductoService")
    @patch.object(resolver_module, "recognize_quitar_producto")
    def test_pedido_not_found_propagates_without_invoking_recognizer(
        self, recognize, service_cls
    ):
        """``PedidoNotFound`` MUST propagate. The existing
        ``recognize_quitar_producto`` would also raise on a missing
        pedido, so converting it into a fallback only hides the
        technical condition without changing the outcome.
        """
        from backend.services.exceptions import PedidoNotFound

        service = MagicMock()
        service.list_by_pedido.side_effect = PedidoNotFound(7)
        service_cls.return_value = service
        active = _active_intent(candidate_ids=[201, 202])

        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        session.id_pedido = 7

        with self.assertRaises(PedidoNotFound):
            resolve_order_line_selection(db, session, "Chica", active)

        recognize.assert_not_called()
        service.list_by_pedido.assert_called_once_with(7)
        for forbidden in (
            "commit", "rollback", "flush", "refresh", "begin", "close",
        ):
            self.assertFalse(
                getattr(db, forbidden).called,
                f"resolver must not call db.{forbidden}() on error",
            )


class ResolveOrderLineSelectionDispatcherIntegrationTest(unittest.TestCase):
    """Real ``dispatch_pending_context`` flow:

    pending ``quitar_producto`` ``order_line_selection`` →
    ``resolve_order_line_selection`` deterministic pre-check →
    ``set_active`` → ``execute_ready_pending_context`` →
    ``execute_quitar_producto`` → clear pending/context.

    Each test patches only the persistence-adjacent seams
    (``PedidoProductoService.list_by_pedido`` and
    ``execute_quitar_producto``); the dispatcher, resolver,
    ``set_active``, ``load_pending_state`` and
    ``clear_pending_context`` are the real production code paths.
    """

    def _pp(self, pp_id: int, codigo: str) -> MagicMock:
        pp = MagicMock(id=pp_id, cantidad=1)
        pp.producto_presentacion.presentacion.codigo = codigo
        pp.producto_presentacion.presentacion.descripcion = codigo
        pp.producto_presentacion.producto.nombre = (
            "Mozzarella" if codigo in {"chica", "grande"} else "Pizza"
        )
        return pp

    def _make_session(self) -> MagicMock:
        from backend.intents.schemas.pending_intents import PendingIntents
        from backend.sessions.enums.context_type import ContextType

        session = MagicMock(spec=ConversationSession)
        session.id_pedido = 7
        session.context_type = ContextType.ORDER_LINE_SELECTION.value
        active = _active_intent(candidate_ids=[201, 202])
        state = PendingIntents(active=active, queue=[])
        session.pending_intents = state.model_dump(mode="json")
        return session

    def _run_dispatch(self, message: str, expected_pp_id: int):
        from backend.intents.orchestration import (
            pending_context_dispatcher as dispatcher_module,
        )
        from backend.intents.orchestration import (
            pending_context_execution as execution_module,
        )

        chica = self._pp(201, "chica")
        grande = self._pp(202, "grande")

        db = MagicMock(spec=DatabaseSession)
        session = self._make_session()

        captured_handler_intent: dict = {}
        handler_call_count = {"n": 0}

        def _fake_handler(_db, _session, intent):
            handler_call_count["n"] += 1
            captured_handler_intent["intent"] = intent
            return intent.model_copy(update={"status": "executed"})

        with patch.object(resolver_module, "PedidoProductoService") as resolver_service_cls, \
             patch.object(resolver_module, "recognize_quitar_producto") as recognize, \
             patch.object(
                 execution_module, "execute_quitar_producto",
                 side_effect=_fake_handler,
             ) as handler, \
             patch.object(dispatcher_module, "emit_event"):
            resolver_service = MagicMock()
            resolver_service.list_by_pedido.return_value = [chica, grande]
            resolver_service_cls.return_value = resolver_service

            result = dispatch_pending_context(db, session, message)

        return {
            "result": result,
            "session": session,
            "db": db,
            "captured_handler_intent": captured_handler_intent.get("intent"),
            "recognize": recognize,
            "resolver_service": resolver_service,
            "handler": handler,
            "handler_call_count": handler_call_count["n"],
        }

    def test_chica_clarification_runs_full_dispatcher_flow(self):
        outcome = self._run_dispatch("Chica", expected_pp_id=201)

        result = outcome["result"]
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].status, "executed")
        self.assertEqual(
            result[0].resolved_data["pedido_producto_id"], 201,
        )

        captured = outcome["captured_handler_intent"]
        self.assertIsNotNone(captured)
        self.assertEqual(captured.status, "ready")
        self.assertEqual(captured.intent, "quitar_producto")
        self.assertEqual(captured.handler, "quitar_producto")
        self.assertEqual(
            captured.resolved_data["pedido_producto_id"], 201,
        )
        self.assertEqual(captured.candidate_ids, [])

        session = outcome["session"]
        self.assertIsNone(session.context_type)
        cleared = session.pending_intents
        self.assertIsNotNone(cleared)
        self.assertIsNone(cleared.get("active"))
        self.assertEqual(cleared.get("queue"), [])

        outcome["recognize"].assert_not_called()
        outcome["resolver_service"].list_by_pedido.assert_called_once_with(7)

        self.assertEqual(outcome["handler_call_count"], 1)
        outcome["handler"].assert_called_once()
        handler_db, handler_session, handler_intent = (
            outcome["handler"].call_args.args
        )
        self.assertIs(handler_db, outcome["db"])
        self.assertIs(handler_session, session)
        self.assertEqual(
            handler_intent.resolved_data["pedido_producto_id"], 201,
        )

        for forbidden in (
            "commit", "rollback", "flush", "refresh", "begin", "close",
        ):
            self.assertFalse(
                getattr(outcome["db"], forbidden).called,
                f"dispatcher/handler must not call db.{forbidden}()",
            )

    def test_grande_clarification_runs_full_dispatcher_flow(self):
        outcome = self._run_dispatch("Grande", expected_pp_id=202)

        result = outcome["result"]
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].status, "executed")
        self.assertEqual(
            result[0].resolved_data["pedido_producto_id"], 202,
        )

        captured = outcome["captured_handler_intent"]
        self.assertIsNotNone(captured)
        self.assertEqual(captured.status, "ready")
        self.assertEqual(
            captured.resolved_data["pedido_producto_id"], 202,
        )

        session = outcome["session"]
        self.assertIsNone(session.context_type)
        cleared = session.pending_intents
        self.assertIsNotNone(cleared)
        self.assertIsNone(cleared.get("active"))

        outcome["recognize"].assert_not_called()
        outcome["resolver_service"].list_by_pedido.assert_called_once_with(7)

        self.assertEqual(outcome["handler_call_count"], 1)
        outcome["handler"].assert_called_once()
        handler_intent = outcome["handler"].call_args.args[2]
        self.assertEqual(
            handler_intent.resolved_data["pedido_producto_id"], 202,
        )

        for forbidden in (
            "commit", "rollback", "flush", "refresh", "begin", "close",
        ):
            self.assertFalse(
                getattr(outcome["db"], forbidden).called,
                f"dispatcher/handler must not call db.{forbidden}()",
            )

    def test_la_chica_clarification_runs_full_dispatcher_flow(self):
        """Single article prefix also routes through the full
        dispatcher flow.
        """
        outcome = self._run_dispatch("la chica", expected_pp_id=201)

        result = outcome["result"]
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].status, "executed")
        self.assertEqual(
            result[0].resolved_data["pedido_producto_id"], 201,
        )
        self.assertEqual(outcome["handler_call_count"], 1)
        self.assertIsNone(outcome["session"].context_type)
        outcome["recognize"].assert_not_called()


if __name__ == "__main__":
    unittest.main()