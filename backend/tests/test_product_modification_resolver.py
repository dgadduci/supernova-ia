import importlib
import unittest
from unittest.mock import MagicMock, patch

from sqlalchemy.orm import Session as DatabaseSession

from backend.intents.context import (
    product_modification_resolver as resolver_module,
)
from backend.intents.context.product_modification_resolver import (
    resolve_product_modification,
)
from backend.intents.schemas.processed_intent import ProcessedIntent
from backend.models.session import Session as ConversationSession


def _pending_intent(
    stage: str,
    source_candidate_ids: list[int],
    destination_candidate_ids: list[int],
    *,
    cantidad: int | None = None,
    cantidad_destino: int | None = None,
) -> ProcessedIntent:
    resolved_data: dict = {
        "source_candidate_ids": list(source_candidate_ids),
        "destination_candidate_ids": list(destination_candidate_ids),
    }
    if cantidad is not None:
        resolved_data["cantidad"] = cantidad
    if cantidad_destino is not None:
        resolved_data["cantidad_destino"] = cantidad_destino
    return ProcessedIntent(
        intent="modificar_producto",
        source_text="x",
        status="pending_resolution",
        recognizer="modificar_producto_recognizer",
        handler="modificar_producto",
        stage=stage,  # type: ignore[arg-type]
        resolved_data=resolved_data,
        candidate_ids=[],
    )


class ResolveProductModificationSourceSelectionTest(unittest.TestCase):
    @patch.object(resolver_module, "recognize_quitar_producto")
    def test_source_refinement_narrows_to_one(self, recognizer):
        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        active = _pending_intent(
            "source_selection", [11, 12], [200, 201], cantidad=2
        )

        recognizer.return_value = {
            "encontrados": [{"pedido_producto_id": 11}],
            "encontrados_posibles": [],
            "encontrados_no_disponibles": [],
            "no_encontrados": [],
            "cantidad": None,
        }

        result = resolve_product_modification(db, session, "la chica", active)

        self.assertEqual(result.status, "pending_resolution")
        self.assertEqual(result.stage, "destination_selection")
        self.assertEqual(result.resolved_data["source_candidate_ids"], [11])
        self.assertEqual(
            result.resolved_data["destination_candidate_ids"], [200, 201]
        )
        self.assertEqual(result.resolved_data["cantidad"], 2)

    @patch.object(resolver_module, "recognize_quitar_producto")
    def test_source_refinement_to_unique_with_unique_dest_returns_ready(
        self, recognizer
    ):
        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        active = _pending_intent("source_selection", [11, 12], [200])

        recognizer.return_value = {
            "encontrados": [{"pedido_producto_id": 11}],
            "encontrados_posibles": [],
            "encontrados_no_disponibles": [],
            "no_encontrados": [],
            "cantidad": None,
        }

        result = resolve_product_modification(db, session, "la chica", active)

        self.assertEqual(result.status, "ready")
        self.assertEqual(
            result.resolved_data["pedido_producto_origen_id"], 11
        )
        self.assertEqual(
            result.resolved_data["producto_presentacion_destino_id"], 200
        )

    @patch.object(resolver_module, "recognize_quitar_producto")
    def test_invalid_source_id_returns_rejected(self, recognizer):
        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        active = _pending_intent("source_selection", [11, 12], [200])

        recognizer.return_value = {
            "encontrados": [{"pedido_producto_id": 99}],
            "encontrados_posibles": [],
            "encontrados_no_disponibles": [],
            "no_encontrados": [],
            "cantidad": None,
        }

        result = resolve_product_modification(db, session, "otra cosa", active)

        self.assertEqual(result.status, "rejected")

    @patch.object(resolver_module, "recognize_quitar_producto")
    def test_source_keeps_ambiguous_after_refinement(self, recognizer):
        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        active = _pending_intent("source_selection", [11, 12], [200, 201])

        recognizer.return_value = {
            "encontrados": [],
            "encontrados_posibles": [
                {"productos": [{"pedido_producto_id": 11}, {"pedido_producto_id": 12}]}
            ],
            "encontrados_no_disponibles": [],
            "no_encontrados": [],
            "cantidad": None,
        }

        result = resolve_product_modification(db, session, "pizza", active)

        self.assertEqual(result.status, "pending_resolution")
        self.assertEqual(result.stage, "source_selection")
        self.assertEqual(result.resolved_data["source_candidate_ids"], [11, 12])


class ResolveProductModificationDestinationSelectionTest(unittest.TestCase):
    @patch.object(resolver_module, "ProductoQueryService")
    @patch.object(resolver_module, "detectar_productos")
    def test_destination_refinement_narrows_to_one(
        self, detector, catalog_cls
    ):
        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        active = _pending_intent(
            "destination_selection", [11], [200, 201, 202], cantidad=3
        )

        catalog_service = MagicMock()
        catalog_service.list_presentaciones_by_ids.return_value = [
            {"producto_presentacion_id": 200, "producto_nombre": "A", "presentacion_codigo": "g"},
            {"producto_presentacion_id": 201, "producto_nombre": "B", "presentacion_codigo": "g"},
            {"producto_presentacion_id": 202, "producto_nombre": "C", "presentacion_codigo": "g"},
        ]
        catalog_cls.return_value = catalog_service

        detector.return_value = {
            "encontrados": [{"producto_presentacion_id": 201}],
            "encontrados_posibles": [],
            "encontrados_no_disponibles": [],
            "no_encontrados": [],
        }

        result = resolve_product_modification(db, session, "la B", active)

        self.assertEqual(result.status, "ready")
        self.assertEqual(
            result.resolved_data["pedido_producto_origen_id"], 11
        )
        self.assertEqual(
            result.resolved_data["producto_presentacion_destino_id"], 201
        )
        self.assertEqual(result.resolved_data["cantidad"], 3)

    @patch.object(resolver_module, "ProductoQueryService")
    @patch.object(resolver_module, "detectar_productos")
    def test_invalid_destination_returns_rejected(self, detector, catalog_cls):
        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        active = _pending_intent("destination_selection", [11], [200, 201])

        catalog_service = MagicMock()
        catalog_service.list_presentaciones_by_ids.return_value = [
            {"producto_presentacion_id": 200, "producto_nombre": "A", "presentacion_codigo": "g"},
            {"producto_presentacion_id": 201, "producto_nombre": "B", "presentacion_codigo": "g"},
        ]
        catalog_cls.return_value = catalog_service

        detector.return_value = {
            "encontrados": [{"producto_presentacion_id": 999}],
            "encontrados_posibles": [],
            "encontrados_no_disponibles": [],
            "no_encontrados": [],
        }

        result = resolve_product_modification(db, session, "x", active)

        self.assertEqual(result.status, "rejected")


class ResolveProductModificationPreservationTest(unittest.TestCase):
    @patch.object(resolver_module, "recognize_quitar_producto")
    def test_cantidad_preserved_across_turns(self, recognizer):
        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        active = _pending_intent("source_selection", [11, 12], [200], cantidad=3)

        recognizer.return_value = {
            "encontrados": [{"pedido_producto_id": 11}],
            "encontrados_posibles": [],
            "encontrados_no_disponibles": [],
            "no_encontrados": [],
            "cantidad": None,
        }

        result = resolve_product_modification(db, session, "la chica", active)

        self.assertEqual(result.resolved_data["cantidad"], 3)

    @patch.object(resolver_module, "recognize_quitar_producto")
    def test_cantidad_destino_preserved_across_source_turns(self, recognizer):
        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        active = _pending_intent(
            "source_selection", [11, 12], [200], cantidad=2
        )
        active.resolved_data["cantidad_destino"] = 1

        recognizer.return_value = {
            "encontrados": [{"pedido_producto_id": 11}],
            "encontrados_posibles": [],
            "encontrados_no_disponibles": [],
            "no_encontrados": [],
            "cantidad": None,
        }

        result = resolve_product_modification(db, session, "la chica", active)

        self.assertEqual(result.resolved_data["cantidad"], 2)
        self.assertEqual(result.resolved_data["cantidad_destino"], 1)

    @patch.object(resolver_module, "ProductoQueryService")
    @patch.object(resolver_module, "detectar_productos")
    def test_cantidad_destino_preserved_across_destination_turns(
        self, detector, catalog_cls
    ):
        db = MagicMock(spec=DatabaseSession)
        session = MagicMock(spec=ConversationSession)
        active = _pending_intent(
            "destination_selection", [11], [200, 201], cantidad=2
        )
        active.resolved_data["cantidad_destino"] = 1

        catalog_service = MagicMock()
        catalog_service.list_presentaciones_by_ids.return_value = [
            {"producto_presentacion_id": 200, "producto_nombre": "A", "presentacion_codigo": "g"},
            {"producto_presentacion_id": 201, "producto_nombre": "B", "presentacion_codigo": "g"},
        ]
        catalog_cls.return_value = catalog_service

        detector.return_value = {
            "encontrados": [{"producto_presentacion_id": 200}],
            "encontrados_posibles": [],
            "encontrados_no_disponibles": [],
            "no_encontrados": [],
        }

        result = resolve_product_modification(db, session, "la A", active)

        self.assertEqual(result.status, "ready")
        self.assertEqual(result.resolved_data["cantidad"], 2)
        self.assertEqual(result.resolved_data["cantidad_destino"], 1)

    @patch.object(resolver_module, "ProductoQueryService")
    @patch.object(resolver_module, "detectar_productos")
    def test_bare_destination_keeps_paired_cantidad_destino(
        self, detector, catalog_cls
    ):
        db = MagicMock(spec=DatabaseSession)
        catalog_service = MagicMock()
        catalog_service.list_presentaciones_by_ids.return_value = [
            {"producto_presentacion_id": 101, "producto_nombre": "Mozzarella", "presentacion_codigo": "grande"},
            {"producto_presentacion_id": 102, "producto_nombre": "Mozzarella", "presentacion_codigo": "chica"},
        ]
        catalog_cls.return_value = catalog_service

        active = _pending_intent(
            "destination_selection", [41], [101, 102], cantidad=2
        )
        active.resolved_data["cantidad_destino"] = 1

        result = resolve_product_modification(
            db, MagicMock(spec=ConversationSession), "chica", active
        )

        self.assertEqual(result.status, "ready")
        self.assertEqual(result.resolved_data["cantidad"], 2)
        self.assertEqual(result.resolved_data["cantidad_destino"], 1)
        self.assertEqual(
            result.resolved_data["producto_presentacion_destino_id"], 102
        )
        detector.assert_not_called()


class ResolveProductModificationBoundariesTest(unittest.TestCase):
    def test_module_does_not_commit_or_rollback(self):
        importlib.reload(resolver_module)
        with open(resolver_module.__file__, encoding="utf-8") as fh:
            source = fh.read()
        for forbidden in (
            "db.commit",
            "db.rollback",
            "from backend.llm",
            "from backend.routers",
            "from backend.intents.responses",
            "from backend.old_project",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)

    def test_public_surface_is_limited(self):
        self.assertEqual(
            resolver_module.__all__,
            ["resolve_product_modification"],
        )


class _TwoDestinationCatalogFixture:
    def __init__(self) -> None:
        self.rows = [
            {
                "producto_presentacion_id": 101,
                "producto_nombre": "Mozzarella",
                "presentacion_codigo": "grande",
            },
            {
                "producto_presentacion_id": 102,
                "producto_nombre": "Mozzarella",
                "presentacion_codigo": "chica",
            },
        ]

    def install(self, catalog_cls: MagicMock) -> None:
        catalog_service = MagicMock()
        catalog_service.list_presentaciones_by_ids.return_value = list(self.rows)
        catalog_cls.return_value = catalog_service


class ResolveProductModificationBareDestinationSelectionTest(
    unittest.TestCase
):
    """Bare presentation refinement for ``destination_selection``."""

    def _session(self) -> MagicMock:
        return MagicMock(spec=ConversationSession)

    def _active(self, *, cantidad: int | None = None) -> ProcessedIntent:
        return _pending_intent(
            "destination_selection",
            [41],
            [101, 102],
            cantidad=cantidad,
        )

    def _catalog(
        self,
        *,
        chica_id: int = 102,
        codes: tuple[tuple[int, str], ...] = (
            (101, "grande"),
            (102, "chica"),
        ),
    ) -> list[dict]:
        rows: list[dict] = []
        for pp_id, code in codes:
            rows.append(
                {
                    "producto_presentacion_id": pp_id,
                    "producto_nombre": "Mozzarella",
                    "presentacion_codigo": code,
                }
            )
        return rows

    @patch.object(resolver_module, "ProductoQueryService")
    @patch.object(resolver_module, "detectar_productos")
    def test_chica_bare_match_returns_ready_with_unique_destination(
        self, detector, catalog_cls
    ):
        db = MagicMock(spec=DatabaseSession)
        catalog_service = MagicMock()
        catalog_service.list_presentaciones_by_ids.return_value = self._catalog()
        catalog_cls.return_value = catalog_service

        result = resolve_product_modification(
            db, self._session(), "chica", self._active()
        )

        self.assertEqual(result.status, "ready")
        self.assertEqual(result.stage, None)
        self.assertEqual(
            result.resolved_data["pedido_producto_origen_id"], 41
        )
        self.assertEqual(
            result.resolved_data["producto_presentacion_destino_id"], 102
        )
        self.assertEqual(
            result.resolved_data["source_candidate_ids"], [41]
        )
        self.assertEqual(
            result.resolved_data["destination_candidate_ids"], [102]
        )
        detector.assert_not_called()

    @patch.object(resolver_module, "ProductoQueryService")
    @patch.object(resolver_module, "detectar_productos")
    def test_case_variation_uppercase_still_matches(
        self, detector, catalog_cls
    ):
        db = MagicMock(spec=DatabaseSession)
        catalog_service = MagicMock()
        catalog_service.list_presentaciones_by_ids.return_value = self._catalog()
        catalog_cls.return_value = catalog_service

        result = resolve_product_modification(
            db, self._session(), "CHICA", self._active()
        )

        self.assertEqual(result.status, "ready")
        self.assertEqual(
            result.resolved_data["producto_presentacion_destino_id"], 102
        )
        detector.assert_not_called()

    @patch.object(resolver_module, "ProductoQueryService")
    @patch.object(resolver_module, "detectar_productos")
    def test_article_la_chica_returns_unique_match(
        self, detector, catalog_cls
    ):
        db = MagicMock(spec=DatabaseSession)
        catalog_service = MagicMock()
        catalog_service.list_presentaciones_by_ids.return_value = self._catalog()
        catalog_cls.return_value = catalog_service

        result = resolve_product_modification(
            db, self._session(), "la chica", self._active()
        )

        self.assertEqual(result.status, "ready")
        self.assertEqual(
            result.resolved_data["producto_presentacion_destino_id"], 102
        )
        detector.assert_not_called()

    @patch.object(resolver_module, "ProductoQueryService")
    @patch.object(resolver_module, "detectar_productos")
    def test_article_un_grande_returns_unique_match(
        self, detector, catalog_cls
    ):
        db = MagicMock(spec=DatabaseSession)
        catalog_service = MagicMock()
        catalog_service.list_presentaciones_by_ids.return_value = self._catalog()
        catalog_cls.return_value = catalog_service

        result = resolve_product_modification(
            db, self._session(), "un grande", self._active()
        )

        self.assertEqual(result.status, "ready")
        self.assertEqual(
            result.resolved_data["producto_presentacion_destino_id"], 101
        )
        detector.assert_not_called()

    @patch.object(resolver_module, "ProductoQueryService")
    @patch.object(resolver_module, "detectar_productos")
    def test_source_candidate_and_cantidad_preserved(
        self, detector, catalog_cls
    ):
        db = MagicMock(spec=DatabaseSession)
        catalog_service = MagicMock()
        catalog_service.list_presentaciones_by_ids.return_value = self._catalog()
        catalog_cls.return_value = catalog_service

        active = self._active(cantidad=2)
        active.resolved_data["pedido_producto_origen_id"] = 41
        active.resolved_data["legacy_marker"] = "kept"

        result = resolve_product_modification(
            db, self._session(), "chica", active
        )

        self.assertEqual(result.status, "ready")
        self.assertEqual(
            result.resolved_data["pedido_producto_origen_id"], 41
        )
        self.assertEqual(result.resolved_data["cantidad"], 2)
        self.assertEqual(
            result.resolved_data["legacy_marker"], "kept"
        )
        detector.assert_not_called()

    @patch.object(resolver_module, "ProductoQueryService")
    @patch.object(resolver_module, "detectar_productos")
    def test_zero_match_falls_through_to_recognizer(
        self, detector, catalog_cls
    ):
        db = MagicMock(spec=DatabaseSession)
        catalog_service = MagicMock()
        catalog_service.list_presentaciones_by_ids.return_value = self._catalog()
        catalog_cls.return_value = catalog_service

        detector.return_value = {
            "encontrados": [],
            "encontrados_posibles": [],
            "encontrados_no_disponibles": [],
            "no_encontrados": [],
        }

        result = resolve_product_modification(
            db, self._session(), "mediana", self._active()
        )

        detector.assert_called_once()
        self.assertEqual(result.status, "pending_resolution")
        self.assertEqual(
            result.resolved_data["destination_candidate_ids"], [101, 102]
        )

    @patch.object(resolver_module, "ProductoQueryService")
    @patch.object(resolver_module, "detectar_productos")
    def test_multiple_match_falls_through_to_recognizer(
        self, detector, catalog_cls
    ):
        db = MagicMock(spec=DatabaseSession)
        active = _pending_intent(
            "destination_selection", [41], [101, 200], cantidad=1
        )
        catalog_service = MagicMock()
        catalog_service.list_presentaciones_by_ids.return_value = [
            {
                "producto_presentacion_id": 101,
                "producto_nombre": "A",
                "presentacion_codigo": "chica",
            },
            {
                "producto_presentacion_id": 200,
                "producto_nombre": "B",
                "presentacion_codigo": "chica",
            },
        ]
        catalog_cls.return_value = catalog_service

        detector.return_value = {
            "encontrados": [{"producto_presentacion_id": 101}],
            "encontrados_posibles": [],
            "encontrados_no_disponibles": [],
            "no_encontrados": [],
        }

        result = resolve_product_modification(
            db, self._session(), "chica", active
        )

        detector.assert_called_once()
        self.assertEqual(result.status, "ready")
        self.assertEqual(
            result.resolved_data["producto_presentacion_destino_id"], 101
        )
        self.assertNotEqual(
            result.resolved_data["producto_presentacion_destino_id"], 200
        )

    @patch.object(resolver_module, "ProductoQueryService")
    @patch.object(resolver_module, "detectar_productos")
    def test_multi_token_reply_falls_through_to_recognizer(
        self, detector, catalog_cls
    ):
        db = MagicMock(spec=DatabaseSession)
        catalog_service = MagicMock()
        catalog_service.list_presentaciones_by_ids.return_value = self._catalog()
        catalog_cls.return_value = catalog_service

        detector.return_value = {
            "encontrados": [{"producto_presentacion_id": 102}],
            "encontrados_posibles": [],
            "encontrados_no_disponibles": [],
            "no_encontrados": [],
        }

        result = resolve_product_modification(
            db, self._session(), "la pizza chica", self._active()
        )

        detector.assert_called_once()
        self.assertEqual(result.status, "ready")
        self.assertEqual(
            result.resolved_data["producto_presentacion_destino_id"], 102
        )

    @patch.object(resolver_module, "ProductoQueryService")
    @patch.object(resolver_module, "detectar_productos")
    def test_full_mozzarella_chica_falls_through_to_recognizer(
        self, detector, catalog_cls
    ):
        db = MagicMock(spec=DatabaseSession)
        catalog_service = MagicMock()
        catalog_service.list_presentaciones_by_ids.return_value = self._catalog()
        catalog_cls.return_value = catalog_service

        detector.return_value = {
            "encontrados": [{"producto_presentacion_id": 102}],
            "encontrados_posibles": [],
            "encontrados_no_disponibles": [],
            "no_encontrados": [],
        }

        result = resolve_product_modification(
            db, self._session(), "mozzarella chica", self._active()
        )

        detector.assert_called_once()
        self.assertEqual(result.status, "ready")
        self.assertEqual(
            result.resolved_data["producto_presentacion_destino_id"], 102
        )

    @patch.object(resolver_module, "ProductoQueryService")
    @patch.object(resolver_module, "detectar_productos")
    def test_bare_match_does_not_widen_destination_candidates(
        self, detector, catalog_cls
    ):
        db = MagicMock(spec=DatabaseSession)
        catalog_service = MagicMock()
        catalog_service.list_presentaciones_by_ids.return_value = self._catalog()
        catalog_cls.return_value = catalog_service

        result = resolve_product_modification(
            db, self._session(), "chica", self._active()
        )

        self.assertEqual(
            result.resolved_data["destination_candidate_ids"], [102]
        )
        self.assertNotIn(999, result.resolved_data["destination_candidate_ids"])

    @patch.object(resolver_module, "ProductoQueryService")
    @patch.object(resolver_module, "detectar_productos")
    def test_bare_match_does_not_invoke_transaction_controls(
        self, detector, catalog_cls
    ):
        db = MagicMock(spec=DatabaseSession)
        catalog_service = MagicMock()
        catalog_service.list_presentaciones_by_ids.return_value = self._catalog()
        catalog_cls.return_value = catalog_service

        for forbidden in (
            "commit",
            "rollback",
            "flush",
            "refresh",
            "begin",
            "begin_nested",
            "close",
        ):
            setattr(db, forbidden, MagicMock())

        result = resolve_product_modification(
            db, self._session(), "la chica", self._active(cantidad=2)
        )

        self.assertEqual(result.status, "ready")
        db.commit.assert_not_called()
        db.rollback.assert_not_called()
        db.flush.assert_not_called()
        db.refresh.assert_not_called()
        db.begin.assert_not_called()
        db.begin_nested.assert_not_called()
        db.close.assert_not_called()
        detector.assert_not_called()


if __name__ == "__main__":
    unittest.main()
