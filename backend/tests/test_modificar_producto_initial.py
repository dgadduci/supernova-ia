import importlib
import unittest
from unittest.mock import MagicMock, patch

from sqlalchemy.orm import Session as DatabaseSession

from backend.intents.orchestration import (
    modificar_producto_initial as initial_module,
)
from backend.intents.orchestration.modificar_producto_initial import (
    process_initial_modificar_producto,
)
from backend.intents.recognizers import (
    modificar_producto_recognizer as recognizer_module,
)
from backend.models.session import Session as ConversationSession
from backend.recognizers.fuzzy_product_recognizer import FuzzyProductRecognizer


def _hijack_real_fuzzy():
    """Replace ``recognizer_module._product_recognizer`` with a real
    ``FuzzyProductRecognizer`` so the production
    ``recognize_modificar_producto`` (and hence the initial
    orchestrator under test) executes the real fuzzy against the
    catalog carrying eager-loaded ``categoria_nombre``.

    Returns a tuple of ``(original, restore)`` so the test can
    restore the factory-recognized module-level symbol after the
    assertions complete.
    """
    original = recognizer_module._product_recognizer
    recognizer_module._product_recognizer = FuzzyProductRecognizer()

    def _restore() -> None:
        recognizer_module._product_recognizer = original

    return original, _restore


def _build_pedido_producto(
    *,
    pedido_producto_id: int,
    presentacion_id: int,
    producto_id: int,
    presentacion_codigo: str,
    presentacion_descripcion: str,
    producto_nombre: str,
    categoria_id: int,
    categoria_descripcion: str,
    cantidad: int,
) -> MagicMock:
    """Create a MagicMock ``PedidoProducto`` with eager-loaded
    presentation/product/category so the real fuzzy sees
    ``categoria_nombre`` from the same owned row.
    """
    presentacion = MagicMock(
        codigo=presentacion_codigo,
        descripcion=presentacion_descripcion,
        activo=True,
    )
    producto = MagicMock(
        nombre=producto_nombre,
        id_categoria_producto=categoria_id,
        activo=True,
        disponible=True,
    )
    producto.categoria = MagicMock(descripcion=categoria_descripcion)
    producto_presentacion = MagicMock(
        id_producto=producto_id,
        id_presentacion=presentacion_id,
        activo=True,
    )
    producto_presentacion.producto = producto
    producto_presentacion.presentacion = presentacion
    pp = MagicMock(
        id=pedido_producto_id,
        id_producto_presentacion=100 + pedido_producto_id,
        cantidad=cantidad,
    )
    pp.producto_presentacion = producto_presentacion
    return pp


def _build_destination_catalog_entry(
    *,
    producto_presentacion_id: int,
    producto_id: int,
    presentacion_id: int,
    categoria_id: int,
    producto_nombre: str,
    categoria_nombre: str,
    presentacion_codigo: str,
    presentacion_descripcion: str,
) -> dict:
    """Build a single destination catalog dict using the same keys
    ``_build_catalog_dict`` in ``ProductoQueryService`` produces.
    """
    return {
        "producto_presentacion_id": producto_presentacion_id,
        "producto_id": producto_id,
        "presentacion_id": presentacion_id,
        "categoria_id": categoria_id,
        "producto_nombre": producto_nombre,
        "categoria_nombre": categoria_nombre,
        "presentacion_codigo": presentacion_codigo,
        "presentacion_descripcion": presentacion_descripcion,
        "producto_activo": True,
        "presentacion_activo": True,
        "activo": True,
        "disponible": True,
    }


class ProcessInitialModificarProductoMissingPedidoTest(unittest.TestCase):
    def test_missing_pedido_returns_rejected(self):
        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        session.id_pedido = None

        result = process_initial_modificar_producto(db, session, "cambiá algo")

        self.assertEqual(result.status, "rejected")
        self.assertEqual(result.intent, "modificar_producto")


class ProcessInitialModificarProductoReadyTest(unittest.TestCase):
    @patch.object(initial_module, "execute_modificar_producto")
    @patch.object(initial_module, "set_pending_intent")
    @patch.object(initial_module, "recognize_modificar_producto")
    def test_unique_domains_return_ready(
        self, recognizer, set_pending, execute_handler
    ):
        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        session.id_pedido = 7
        session.id_comercio = 1

        recognizer.return_value = {
            "source_candidate_ids": [11],
            "destination_candidate_ids": [200],
            "source_pp_id": 11,
            "destination_pp_id": 200,
            "cantidad": None,
        }

        from backend.intents.schemas.processed_intent import ProcessedIntent

        execute_handler.return_value = ProcessedIntent(
            intent="modificar_producto",
            source_text="x",
            status="ready",
            recognizer="modificar_producto_recognizer",
            handler="modificar_producto",
            resolved_data={},
            requirements=[],
            candidate_ids=[],
        )

        result = process_initial_modificar_producto(
            db, session, "cambiá la pizza chica por una grande"
        )

        self.assertEqual(result.status, "ready")
        self.assertEqual(result.intent, "modificar_producto")
        execute_handler.assert_called_once()
        set_pending.assert_not_called()

    @patch.object(initial_module, "execute_modificar_producto")
    @patch.object(initial_module, "set_pending_intent")
    @patch.object(initial_module, "recognize_modificar_producto")
    def test_unique_with_cantidad_preserves_it(
        self, recognizer, set_pending, execute_handler
    ):
        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        session.id_pedido = 7
        session.id_comercio = 1

        recognizer.return_value = {
            "source_candidate_ids": [11],
            "destination_candidate_ids": [200],
            "source_pp_id": 11,
            "destination_pp_id": 200,
            "cantidad": 2,
        }

        from backend.intents.schemas.processed_intent import ProcessedIntent

        execute_handler.return_value = ProcessedIntent(
            intent="modificar_producto",
            source_text="x",
            status="ready",
            recognizer="modificar_producto_recognizer",
            handler="modificar_producto",
            resolved_data={"cantidad": 2},
            requirements=[],
            candidate_ids=[],
        )

        result = process_initial_modificar_producto(
            db, session, "cambiá 2 chicas por 2 grandes"
        )

        self.assertEqual(result.status, "ready")
        self.assertEqual(result.resolved_data.get("cantidad"), 2)

    @patch.object(initial_module, "execute_modificar_producto")
    @patch.object(initial_module, "set_pending_intent")
    @patch.object(initial_module, "recognize_modificar_producto")
    def test_unique_with_paired_cantidad_destino(
        self, recognizer, set_pending, execute_handler
    ):
        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        session.id_pedido = 7
        session.id_comercio = 1

        recognizer.return_value = {
            "source_candidate_ids": [11],
            "destination_candidate_ids": [200],
            "source_pp_id": 11,
            "destination_pp_id": 200,
            "cantidad": 2,
            "cantidad_destino": 1,
        }

        from backend.intents.schemas.processed_intent import ProcessedIntent

        execute_handler.return_value = ProcessedIntent(
            intent="modificar_producto",
            source_text="x",
            status="ready",
            recognizer="modificar_producto_recognizer",
            handler="modificar_producto",
            resolved_data={"cantidad": 2, "cantidad_destino": 1},
            requirements=[],
            candidate_ids=[],
        )

        process_initial_modificar_producto(
            db, session, "cambiar 2 napolitanas por una muzza"
        )

        args, _ = execute_handler.call_args
        ready_intent = args[2]
        self.assertEqual(ready_intent.resolved_data["cantidad"], 2)
        self.assertEqual(ready_intent.resolved_data["cantidad_destino"], 1)


class ProcessInitialModificarProductoPendingTest(unittest.TestCase):
    @patch.object(initial_module, "set_pending_intent")
    @patch.object(initial_module, "recognize_modificar_producto")
    def test_ambiguous_source_returns_pending_source_selection(
        self, recognizer, set_pending
    ):
        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        session.id_pedido = 7
        session.id_comercio = 1

        recognizer.return_value = {
            "source_candidate_ids": [11, 12],
            "destination_candidate_ids": [200],
            "source_pp_id": None,
            "destination_pp_id": 200,
            "cantidad": None,
        }

        result = process_initial_modificar_producto(
            db, session, "cambiá la pizza por una grande"
        )

        self.assertEqual(result.status, "pending_resolution")
        self.assertEqual(result.stage, "source_selection")
        self.assertEqual(
            result.resolved_data["source_candidate_ids"], [11, 12]
        )
        self.assertEqual(
            result.resolved_data["destination_candidate_ids"], [200]
        )
        set_pending.assert_called_once()

    @patch.object(initial_module, "set_pending_intent")
    @patch.object(initial_module, "recognize_modificar_producto")
    def test_ambiguous_destination_returns_pending_destination_selection(
        self, recognizer, set_pending
    ):
        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        session.id_pedido = 7
        session.id_comercio = 1

        recognizer.return_value = {
            "source_candidate_ids": [11],
            "destination_candidate_ids": [200, 201],
            "source_pp_id": 11,
            "destination_pp_id": None,
            "cantidad": None,
        }

        result = process_initial_modificar_producto(
            db, session, "cambiá la pizza chica por grande"
        )

        self.assertEqual(result.status, "pending_resolution")
        self.assertEqual(result.stage, "destination_selection")
        self.assertEqual(result.resolved_data["source_candidate_ids"], [11])
        self.assertEqual(
            result.resolved_data["destination_candidate_ids"], [200, 201]
        )


class ProcessInitialModificarProductoRejectedTest(unittest.TestCase):
    @patch.object(initial_module, "set_pending_intent")
    @patch.object(initial_module, "recognize_modificar_producto")
    def test_invalid_destination_quantity_returns_rejected(
        self, recognizer, set_pending
    ):
        """The orchestrator MUST reject an explicit invalid destination
        quantity BEFORE creating pending, resolving candidates or
        invoking the handler/service. This is the deterministic fix for
        the blocker `cambiar 2 ... por 0 ...`.
        """
        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        session.id_pedido = 7
        session.id_comercio = 1

        recognizer.return_value = {
            "source_candidate_ids": [11],
            "destination_candidate_ids": [200],
            "source_pp_id": 11,
            "destination_pp_id": 200,
            "cantidad": 2,
            "cantidad_destino": None,
            "cantidad_destino_invalid": True,
        }

        result = process_initial_modificar_producto(
            db, session, "cambiar 2 napolitanas por 0 muzza"
        )

        self.assertEqual(result.status, "rejected")
        self.assertEqual(
            result.resolved_data["reason"], "invalid_destination_quantity"
        )
        set_pending.assert_not_called()

    @patch.object(initial_module, "set_pending_intent")
    @patch.object(initial_module, "recognize_modificar_producto")
    def test_no_source_candidates_returns_rejected(
        self, recognizer, set_pending
    ):
        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        session.id_pedido = 7
        session.id_comercio = 1

        recognizer.return_value = {
            "source_candidate_ids": [],
            "destination_candidate_ids": [200],
            "source_pp_id": None,
            "destination_pp_id": 200,
            "cantidad": None,
        }

        result = process_initial_modificar_producto(db, session, "algo")

        self.assertEqual(result.status, "rejected")
        set_pending.assert_not_called()

    @patch.object(initial_module, "set_pending_intent")
    @patch.object(initial_module, "recognize_modificar_producto")
    def test_no_destination_candidates_returns_rejected(
        self, recognizer, set_pending
    ):
        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        session.id_pedido = 7
        session.id_comercio = 1

        recognizer.return_value = {
            "source_candidate_ids": [11],
            "destination_candidate_ids": [],
            "source_pp_id": 11,
            "destination_pp_id": None,
            "cantidad": None,
        }

        result = process_initial_modificar_producto(db, session, "algo")

        self.assertEqual(result.status, "rejected")
        set_pending.assert_not_called()

    @patch.object(initial_module, "set_pending_intent")
    @patch.object(initial_module, "recognize_modificar_producto")
    def test_equivalent_source_destination_returns_rejected(
        self, recognizer, set_pending
    ):
        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        session.id_pedido = 7
        session.id_comercio = 1

        recognizer.return_value = {
            "source_candidate_ids": [11],
            "destination_candidate_ids": [11],
            "source_pp_id": 11,
            "destination_pp_id": 11,
            "cantidad": None,
        }

        result = process_initial_modificar_producto(db, session, "algo")

        self.assertEqual(result.status, "rejected")


class ProcessInitialModificarProductoBoundariesTest(unittest.TestCase):
    def test_module_does_not_commit_or_rollback(self):
        importlib.reload(initial_module)
        with open(initial_module.__file__, encoding="utf-8") as fh:
            source = fh.read()
        for forbidden in (
            "db.commit",
            "db.rollback",
            "db.flush",
            "from backend.llm",
            "from backend.routers",
            "from backend.old_project",
            "build_modificar_producto_response",
            "from backend.intents.responses",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)

    def test_public_surface_is_limited(self):
        self.assertEqual(
            initial_module.__all__,
            ["process_initial_modificar_producto"],
        )


class ProcessInitialModificarProductoCategoryQualifiedSourceTest(unittest.TestCase):
    """Exercise the initial orchestrator with the real shared fuzzy
    recognizer configured via the module wrapper.

    The orchestrator's ``recognize_modificar_producto`` is NOT mocked:
    the real fuzzy is invoked through the production wrapper against
    the owned ``PedidoProducto`` catalog. Only the external
    collaborators that cannot run in-process are isolated
    (``PedidoProductoService`` for the Pedido lines,
    ``ProductoQueryService`` for the destination catalog,
    ``set_pending_intent`` and ``execute_modificar_producto`` on the
    orchestrator side).
    """

    def _owned_lines(self) -> list[MagicMock]:
        return [
            _build_pedido_producto(
                pedido_producto_id=101,
                presentacion_id=1,
                producto_id=201,
                presentacion_codigo="grande",
                presentacion_descripcion="Grande",
                producto_nombre="Mozzarella",
                categoria_id=301,
                categoria_descripcion="Pizzas",
                cantidad=1,
            ),
            _build_pedido_producto(
                pedido_producto_id=102,
                presentacion_id=2,
                producto_id=201,
                presentacion_codigo="chica",
                presentacion_descripcion="Chica",
                producto_nombre="Mozzarella",
                categoria_id=301,
                categoria_descripcion="Pizzas",
                cantidad=1,
            ),
            _build_pedido_producto(
                pedido_producto_id=103,
                presentacion_id=3,
                producto_id=202,
                presentacion_codigo="chica",
                presentacion_descripcion="Chica",
                producto_nombre="Napolitana",
                categoria_id=301,
                categoria_descripcion="Pizzas",
                cantidad=1,
            ),
        ]

    def _destination_catalog(self) -> list[dict]:
        return [
            _build_destination_catalog_entry(
                producto_presentacion_id=200,
                producto_id=301,
                presentacion_id=10,
                categoria_id=401,
                producto_nombre="Verdura",
                categoria_nombre="Empanadas",
                presentacion_codigo="unidad",
                presentacion_descripcion="Unidad",
            )
        ]

    @patch.object(initial_module, "execute_modificar_producto")
    @patch.object(initial_module, "set_pending_intent")
    @patch.object(recognizer_module, "PedidoProductoService")
    @patch.object(recognizer_module, "ProductoQueryService")
    def test_ambiguous_category_qualified_source_returns_pending_source_selection(
        self, catalog_cls, pp_service_cls, set_pending, execute_handler
    ):
        """``pizza de mozzarella`` MUST surface exactly the two own
        Mozzarella line IDs (Grande and Chica), the Napolitana line
        that is foreign to the source product MUST NOT appear, and the
        initial orchestrator MUST produce ``pending_resolution`` with
        stage ``source_selection`` without invoking the handler.
        """
        _original, restore = _hijack_real_fuzzy()

        try:
            db = MagicMock(spec=DatabaseSession)
            session = MagicMock(spec=ConversationSession)
            session.id_pedido = 7
            session.id_comercio = 1

            pp_service = MagicMock()
            pp_service.list_by_pedido.return_value = self._owned_lines()
            pp_service_cls.return_value = pp_service

            catalog_service = MagicMock()
            catalog_service.list_recognizer_catalog.return_value = (
                self._destination_catalog()
            )
            catalog_cls.return_value = catalog_service

            result = process_initial_modificar_producto(
                db,
                session,
                "cambia una pizza de mozzarella por una empanada de verdura",
            )

            self.assertEqual(result.status, "pending_resolution")
            self.assertEqual(result.stage, "source_selection")
            self.assertEqual(
                result.resolved_data["source_candidate_ids"], [101, 102]
            )
            self.assertNotIn(103, result.resolved_data["source_candidate_ids"])
            self.assertEqual(
                result.resolved_data["destination_candidate_ids"], [200]
            )
            set_pending.assert_called_once()
            execute_handler.assert_not_called()
        finally:
            restore()

    @patch.object(initial_module, "execute_modificar_producto")
    @patch.object(initial_module, "set_pending_intent")
    @patch.object(recognizer_module, "PedidoProductoService")
    @patch.object(recognizer_module, "ProductoQueryService")
    def test_source_outside_draft_returns_rejected_without_pending_or_mutation(
        self, catalog_cls, pp_service_cls, set_pending, execute_handler
    ):
        """``empanada de carne`` is a category-qualified source that
        is absent from the active draft. The real fuzzy must surface
        no source candidate and the initial orchestrator MUST reject
        before creating pending, resolving candidates or invoking
        the handler/service.
        """
        _original, restore = _hijack_real_fuzzy()

        try:
            db = MagicMock(spec=DatabaseSession)
            session = MagicMock(spec=ConversationSession)
            session.id_pedido = 7
            session.id_comercio = 1

            pp_service = MagicMock()
            pp_service.list_by_pedido.return_value = self._owned_lines()
            pp_service_cls.return_value = pp_service

            catalog_service = MagicMock()
            catalog_service.list_recognizer_catalog.return_value = (
                self._destination_catalog()
            )
            catalog_cls.return_value = catalog_service

            result = process_initial_modificar_producto(
                db,
                session,
                "cambia una empanada de carne por una empanada de verdura",
            )

            self.assertEqual(result.status, "rejected")
            self.assertEqual(result.resolved_data["reason"], "source_absent")
            set_pending.assert_not_called()
            execute_handler.assert_not_called()
        finally:
            restore()


if __name__ == "__main__":
    unittest.main()
