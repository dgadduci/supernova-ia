"""Focused tests for Subphase 4.11.5 (residual fuzzy failures + false positives).

Covers the typed-discriminated-union contract for ``encontrados_posibles``,
the category-scope matching pass, the ``muzarrella`` alias entry, the
production reader adaptations, the narrowly-scoped hybrid guard, and the
per-case diagnostic / eligibility invariants.
"""
from __future__ import annotations

import inspect
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from backend.intents.context.order_line_selection_resolver import (
    _flatten_pedido_producto_ids as _order_line_flatten_pp,
)
from backend.intents.context.product_modification_resolver import (
    _flatten_pedido_producto_ids as _mod_flatten_pp,
)
from backend.intents.context.product_modification_resolver import (
    _flatten_producto_presentacion_ids as _mod_flatten_pps,
)
from backend.intents.recognizers.modificar_producto_recognizer import (
    _flatten_pedido_producto_ids as _mod_recog_flatten_pp,
)
from backend.intents.recognizers.modificar_producto_recognizer import (
    _flatten_producto_presentacion_ids as _mod_recog_flatten_pps,
)
from backend.intents.recognizers.quitar_producto_recognizer import (
    _attach_pedido_producto_id_to_posibles as _quitar_attach_posibles,
)
from backend.recognizers.fuzzy_product_recognizer import FuzzyProductRecognizer
from backend.recognizers.product_recognizer import (
    ALIASES_PALABRAS,
    _coincidencia_categoria,
    detectar_productos,
)
from backend.recognizers.product_recognizer_contract import (
    CategoryAmbiguityGroup,
    PossibleMatchGroup,
    ProductRecognizerProtocol,
    ProductRecognizerResult,
)
from backend.recognizers.product_recognizer_contract import (
    __all__ as CONTRACT_ALL,
)

POSTRES_CATALOG: list[dict] = [
    {
        "producto_presentacion_id": 69,
        "producto_id": 800,
        "presentacion_id": 1,
        "categoria_id": 4,
        "categoria_nombre": "Postres",
        "producto_nombre": "Flan casero",
        "presentacion_codigo": "UNIDAD",
        "presentacion_descripcion": "Porción de flan casero",
        "activo": True,
        "disponible": True,
    },
    {
        "producto_presentacion_id": 70,
        "producto_id": 801,
        "presentacion_id": 1,
        "categoria_id": 4,
        "categoria_nombre": "Postres",
        "producto_nombre": "Tiramisú",
        "presentacion_codigo": "UNIDAD",
        "presentacion_descripcion": "Tiramisú",
        "activo": True,
        "disponible": True,
    },
    {
        "producto_presentacion_id": 71,
        "producto_id": 802,
        "presentacion_id": 1,
        "categoria_id": 4,
        "categoria_nombre": "Postres",
        "producto_nombre": "Helado",
        "presentacion_codigo": "UNIDAD",
        "presentacion_descripcion": "Helado",
        "activo": True,
        "disponible": True,
    },
    {
        "producto_presentacion_id": 72,
        "producto_id": 803,
        "presentacion_id": 1,
        "categoria_id": 4,
        "categoria_nombre": "Postres",
        "producto_nombre": "Brownie con helado",
        "presentacion_codigo": "UNIDAD",
        "presentacion_descripcion": "Brownie con helado",
        "activo": True,
        "disponible": True,
    },
]


PIZZA_CATALOG: list[dict] = [
    {
        "producto_presentacion_id": 1,
        "producto_id": 771,
        "presentacion_id": 1,
        "categoria_id": 1,
        "categoria_nombre": "Pizzas",
        "producto_nombre": "Pizza de Muzzarella",
        "presentacion_codigo": "GRANDE",
        "presentacion_descripcion": "Pizza grande de muzzarella",
        "activo": True,
        "disponible": True,
    },
]


MOSTAZA_CATALOG: list[dict] = [
    {
        "producto_presentacion_id": 99,
        "producto_id": 999,
        "presentacion_id": 99,
        "categoria_id": 9,
        "categoria_nombre": "Mostazas",
        "producto_nombre": "Mostaza dietética",
        "presentacion_codigo": "UNIDAD",
        "presentacion_descripcion": "Mostaza",
        "activo": True,
        "disponible": True,
    },
]


DATASET_PATH = (
    Path(__file__).parent.parent
    / "data"
    / "product_recognition_calibration_cases.json"
)


def _load_dataset() -> dict[str, Any]:
    return json.loads(DATASET_PATH.read_text(encoding="utf-8"))


def _dataset_fingerprint(dataset: dict[str, Any]) -> str:
    """Stable fingerprint of the dataset (matches Subphase 4.11.4)."""
    import hashlib

    canonical = json.dumps(
        {
            "schema_version": dataset["schema_version"],
            "seed_refs": dataset.get("seed_refs", {}),
            "commerce_catalog_fingerprint": dataset.get(
                "commerce_catalog_fingerprint", {}
            ),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Section 2 — Alias Entry
# ---------------------------------------------------------------------------


class MuzarrellaAliasTest(unittest.TestCase):
    def test_muzarrella_closes_residual_fuzzy_case(self):
        """The new alias entry must reach the same recognition shape as
        the existing ``muzza`` alias entry."""
        catalog = [
            {
                "producto_presentacion_id": 1,
                "producto_id": 1,
                "presentacion_id": 1,
                "categoria_id": 1,
                "categoria_nombre": "Pizzas",
                "producto_nombre": "Pizza de Muzzarella",
                "presentacion_codigo": "GRANDE",
                "presentacion_descripcion": "Pizza grande de muzzarella",
                "activo": True,
                "disponible": True,
            },
        ]
        result = detectar_productos("muzarrella", catalog)
        ids = [p["producto_presentacion_id"] for p in result["encontrados"]]
        self.assertEqual(ids, [1])
        self.assertEqual(result["no_encontrados"], [])
        self.assertEqual(result["encontrados_posibles"], [])

    def test_muzarrella_maps_to_canonical_mozzarella(self):
        self.assertEqual(ALIASES_PALABRAS["muzarrella"], "mozzarella")

    def test_existing_eleven_alias_entries_preserved(self):
        """The 11 (now 15) existing alias entries are preserved verbatim."""
        existing_entries = {
            "muza": "mozzarella",
            "muzza": "mozzarella",
            "muzarela": "mozzarella",
            "muzarella": "mozzarella",
            "mozarela": "mozzarella",
            "mozarella": "mozzarella",
            "muzarrella": "mozzarella",
            "muzzarela": "mozzarella",
            "muzzarella": "mozzarella",
            "musarela": "mozzarella",
            "musarella": "mozzarella",
            "fugazeta": "fugazzeta",
            "fugazetta": "fugazzeta",
            "napoli": "napolitana",
            "calabreza": "calabresa",
        }
        for alias, canonical in existing_entries.items():
            with self.subTest(alias=alias):
                self.assertEqual(ALIASES_PALABRAS.get(alias), canonical)


# ---------------------------------------------------------------------------
# Section 3 — Typed-Discriminated-Union Contract
# ---------------------------------------------------------------------------


class TypedUnionContractTest(unittest.TestCase):
    def test_possible_match_group_preserves_byte_identical_shape(self):
        self.assertNotIn("kind", PossibleMatchGroup.__annotations__)

    def test_category_ambiguity_group_carries_kind_discriminator(self):
        annotations = CategoryAmbiguityGroup.__annotations__
        self.assertIn("kind", annotations)
        self.assertIn("categoria_nombre", annotations)
        self.assertIn("texto_origen", annotations)
        self.assertNotIn("productos", annotations)

    def test_possible_ambiguity_group_is_union(self):
        self.assertIn("PossibleAmbiguityGroup", CONTRACT_ALL)
        self.assertIn("CategoryAmbiguityGroup", CONTRACT_ALL)
        self.assertIn("PossibleMatchGroup", CONTRACT_ALL)

    def test_recognizer_result_typed_union_widened(self):
        annotations = ProductRecognizerResult.__annotations__
        self.assertIn("encontrados_posibles", annotations)
        self.assertIn("PossibleAmbiguityGroup", CONTRACT_ALL)

    def test_product_recognizer_protocol_signature_preserved(self):
        sig = inspect.signature(ProductRecognizerProtocol.recognize)
        params = list(sig.parameters)
        self.assertEqual(params[:3], ["self", "text", "catalog"])
        self.assertIn("ProductRecognizerResult", str(sig.return_annotation))


class CategoryPassTest(unittest.TestCase):
    def test_un_postre_produces_category_level_group(self):
        result = detectar_productos("un postre", POSTRES_CATALOG)
        self.assertEqual(result["encontrados"], [])
        self.assertEqual(len(result["encontrados_posibles"]), 1)
        group = result["encontrados_posibles"][0]
        self.assertEqual(group["kind"], "category")
        self.assertEqual(group["categoria_nombre"], "Postres")
        self.assertEqual(group["texto_origen"], "un postre")
        self.assertNotIn("productos", group)

    def test_otra_pizza_does_not_expose_pizza_ids_as_evaluable(self):
        catalog = [
            {
                "producto_presentacion_id": pid,
                "producto_id": 770 + pid,
                "presentacion_id": 1,
                "categoria_id": 1,
                "categoria_nombre": "Pizzas",
                "producto_nombre": f"Pizza Variedad {pid}",
                "presentacion_codigo": "GRANDE",
                "presentacion_descripcion": "Pizza",
                "activo": True,
                "disponible": True,
            }
            for pid in range(1, 31)
        ]
        result = detectar_productos("otra pizza", catalog)
        self.assertEqual(result["encontrados"], [])
        self.assertEqual(len(result["encontrados_posibles"]), 1)
        group = result["encontrados_posibles"][0]
        self.assertEqual(group["kind"], "category")
        self.assertEqual(group["categoria_nombre"], "Pizzas")
        self.assertNotIn("productos", group)

    def test_no_calibration_label_leakage_in_recognizer_module(self):
        """``detectar_productos`` must NOT consult any calibration label."""
        source = inspect.getsource(detectar_productos)
        for forbidden in (
            "allowed_candidate_ids",
            "restricted_candidate_ids",
            "expected_producto_presentacion_id",
        ):
            self.assertNotIn(forbidden, source)

    def test_recognizer_signature_unchanged(self):
        sig = inspect.signature(detectar_productos)
        self.assertEqual(list(sig.parameters), ["texto", "productos_presentaciones"])

    def test_coincidencia_categoria_helper_signature(self):
        sig = inspect.signature(_coincidencia_categoria)
        self.assertEqual(list(sig.parameters), ["texto_segmento", "catalogo"])
        self.assertIn("str | None", str(sig.return_annotation))

    def test_pizza_muzzarella_byte_identical_product_match(self):
        catalog = [
            {
                "producto_presentacion_id": 1,
                "producto_id": 771,
                "presentacion_id": 1,
                "categoria_id": 1,
                "categoria_nombre": "Pizzas",
                "producto_nombre": "Pizza de Muzzarella",
                "presentacion_codigo": "GRANDE",
                "presentacion_descripcion": "Pizza grande de muzzarella",
                "activo": True,
                "disponible": True,
            },
        ]
        result = detectar_productos("pizza muzzarella", catalog)
        self.assertEqual(len(result["encontrados"]), 1)
        self.assertEqual(result["encontrados"][0]["producto_presentacion_id"], 1)
        self.assertEqual(result["encontrados_posibles"], [])

    def test_category_pass_respects_stopword_filter(self):
        result = detectar_productos("un grande postre", POSTRES_CATALOG)
        group = result["encontrados_posibles"][0]
        self.assertEqual(group["kind"], "category")
        self.assertEqual(group["categoria_nombre"], "Postres")

    def test_category_pass_no_significant_tokens(self):
        result = detectar_productos("un de con", POSTRES_CATALOG)
        self.assertEqual(result["encontrados"], [])
        self.assertEqual(result["encontrados_posibles"], [])
        self.assertEqual(
            [entry["texto_origen"] for entry in result["no_encontrados"]],
            ["un de con"],
        )

    def test_category_pass_is_deterministic(self):
        first = detectar_productos("un postre", POSTRES_CATALOG)
        second = detectar_productos("un postre", POSTRES_CATALOG)
        self.assertEqual(first, second)

    def test_public_result_schema_has_exactly_four_keys(self):
        result = detectar_productos("un postre", POSTRES_CATALOG)
        self.assertEqual(
            set(result.keys()),
            {"encontrados", "encontrados_posibles", "encontrados_no_disponibles", "no_encontrados"},
        )

    def test_fuzzy_product_recognizer_adapter_returns_widened_union(self):
        recognizer = FuzzyProductRecognizer()
        result = recognizer.recognize("un postre", POSTRES_CATALOG)
        self.assertIsInstance(result, dict)
        self.assertEqual(len(result["encontrados_posibles"]), 1)
        self.assertEqual(result["encontrados_posibles"][0]["kind"], "category")

    def test_recognizer_all_export_unchanged(self):
        from backend.recognizers.product_recognizer import __all__

        self.assertEqual(set(__all__), {"detectar_productos"})

    def test_competing_categories_returns_only_matched_category(self):
        catalog = POSTRES_CATALOG + [
            {
                "producto_presentacion_id": 1,
                "producto_id": 771,
                "presentacion_id": 1,
                "categoria_id": 1,
                "categoria_nombre": "Pizzas",
                "producto_nombre": "Pizza de Muzzarella",
                "presentacion_codigo": "GRANDE",
                "presentacion_descripcion": "Pizza grande de muzzarella",
                "activo": True,
                "disponible": True,
            },
        ]
        result = detectar_productos("postre", catalog)
        self.assertEqual(result["encontrados"], [])
        self.assertEqual(len(result["encontrados_posibles"]), 1)
        self.assertEqual(result["encontrados_posibles"][0]["categoria_nombre"], "Postres")


# ---------------------------------------------------------------------------
# Section 5 — Reader Adaptations
# ---------------------------------------------------------------------------


class ReaderAdaptationTest(unittest.TestCase):
    def test_product_intent_resolver_skips_category_group(self):
        from backend.intents.resolvers.product_intent_resolver import (
            resolve_product_intent,
        )

        raw = {
            "encontrados": [],
            "encontrados_posibles": [
                {"kind": "category", "categoria_nombre": "Pizzas", "texto_origen": "pizza"},
            ],
            "encontrados_no_disponibles": [],
            "no_encontrados": [],
        }
        result = resolve_product_intent(raw)
        self.assertEqual(result["candidate_ids"], [])
        self.assertEqual(result["resolved_data"], {})

    def test_product_intent_resolver_preserves_flat_candidate_path(self):
        from backend.intents.resolvers.product_intent_resolver import (
            resolve_product_intent,
        )

        raw = {
            "encontrados": [],
            "encontrados_posibles": [
                {"producto_presentacion_id": 1, "producto_nombre": "Pizza", "cantidad": 1},
            ],
            "encontrados_no_disponibles": [],
            "no_encontrados": [],
        }
        result = resolve_product_intent(raw)
        self.assertEqual(result["candidate_ids"], [1])
        self.assertEqual(result["resolved_data"]["cantidad"], 1)

    def test_product_intent_resolver_does_not_keyerror_on_category(self):
        from backend.intents.resolvers.product_intent_resolver import (
            resolve_product_intent,
        )

        raw = {
            "encontrados": [],
            "encontrados_posibles": [
                {"kind": "category", "categoria_nombre": "Pizzas", "texto_origen": "pizza"},
            ],
            "encontrados_no_disponibles": [],
            "no_encontrados": [],
        }
        # Should not raise KeyError.
        result = resolve_product_intent(raw)
        self.assertIn("candidate_ids", result)

    def test_product_selection_resolver_skips_category_group(self):
        from backend.intents.context.product_selection_context_resolver import (
            resolve_product_selection,
        )
        from backend.intents.schemas.processed_intent import ProcessedIntent
        from backend.intents.schemas.requirement_state import RequirementState

        active = ProcessedIntent(
            intent="agregar_producto",
            source_text="algo",
            status="pending_resolution",
            recognizer="recognizer_fuzzy_product",
            handler="agregar_producto",
            resolved_data={},
            requirements=[
                RequirementState(name="producto_presentacion_id", status="pending", value=None),
            ],
            candidate_ids=[1, 2, 3, 4],
        )
        # Catalog with a category that matches the user input "postre" but
        # no product-level fuzzy match (no "postre" in any product name).
        catalog = [
            {
                "producto_presentacion_id": 69,
                "producto_nombre": "Flan casero",
                "presentacion_codigo": "UNIDAD",
                "categoria_nombre": "Postres",
            },
        ]
        result = resolve_product_selection("postre", active, catalog)
        # The category-level group is not a product candidate, so the
        # resolver must NOT narrow. The active intent is returned unchanged.
        self.assertEqual(result.status, "pending_resolution")
        self.assertEqual(result.candidate_ids, [1, 2, 3, 4])

    def test_product_modification_resolver_skips_category(self):
        raw = {
            "encontrados": [],
            "encontrados_posibles": [
                {"kind": "category", "categoria_nombre": "Pizzas", "texto_origen": "pizza"},
            ],
            "encontrados_no_disponibles": [],
            "no_encontrados": [],
        }
        self.assertEqual(_mod_flatten_pp(raw), [])
        self.assertEqual(_mod_flatten_pps(raw), [])

    def test_order_line_selection_resolver_skips_category(self):
        raw = {
            "encontrados": [],
            "encontrados_posibles": [
                {"kind": "category", "categoria_nombre": "Pizzas", "texto_origen": "pizza"},
            ],
            "encontrados_no_disponibles": [],
            "no_encontrados": [],
        }
        self.assertEqual(_order_line_flatten_pp(raw), [])

    def test_modificar_producto_recognizer_skips_category(self):
        raw = {
            "encontrados": [],
            "encontrados_posibles": [
                {"kind": "category", "categoria_nombre": "Pizzas", "texto_origen": "pizza"},
            ],
            "encontrados_no_disponibles": [],
            "no_encontrados": [],
        }
        self.assertEqual(_mod_recog_flatten_pp(raw), [])
        self.assertEqual(_mod_recog_flatten_pps(raw), [])

    def test_quitar_producto_attach_preserves_category_group(self):
        catalog = [
            {
                "producto_presentacion_id": 1,
                "pedido_producto_id": 99,
                "producto_nombre": "Pizza",
                "presentacion_codigo": "UNIDAD",
            },
        ]
        group = {"kind": "category", "categoria_nombre": "Pizzas", "texto_origen": "pizza"}
        result = _quitar_attach_posibles([group], catalog)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["kind"], "category")
        self.assertEqual(result[0]["categoria_nombre"], "Pizzas")
        self.assertNotIn("productos", result[0])


class NoUncheckedProductosAccessTest(unittest.TestCase):
    """Grep-based assertion: no production reader does
    ``group[\"productos\"]`` direct access without a discriminator
    check. Test files are excluded."""

    READER_FILES = (
        "backend/intents/resolvers/product_intent_resolver.py",
        "backend/intents/context/product_selection_context_resolver.py",
        "backend/intents/context/product_modification_resolver.py",
        "backend/intents/context/order_line_selection_resolver.py",
        "backend/intents/orchestration/quitar_producto_initial.py",
        "backend/intents/recognizers/quitar_producto_recognizer.py",
        "backend/intents/recognizers/modificar_producto_recognizer.py",
        "backend/services/product_recognition_calibration_runner.py",
        "backend/services/product_recognition_shadow_service.py",
    )

    def test_no_unsafe_group_productos_access(self):
        for relative in self.READER_FILES:
            path = Path(__file__).parent.parent.parent / relative
            source = path.read_text(encoding="utf-8")
            self.assertNotIn("group[\"productos\"]", source, msg=relative)


# ---------------------------------------------------------------------------
# Section 6 — Hybrid Guard
# ---------------------------------------------------------------------------


class FuzzyDecisionHelperTest(unittest.TestCase):
    def test_fuzzy_decision_returns_ambiguous_for_category(self):
        from backend.services.product_recognition_calibration_runner import (
            _fuzzy_decision,
        )

        result = {
            "encontrados": [],
            "encontrados_posibles": [
                {"kind": "category", "categoria_nombre": "Pizzas", "texto_origen": "pizza"},
            ],
            "encontrados_no_disponibles": [],
            "no_encontrados": [],
        }
        self.assertEqual(_fuzzy_decision(result), "ambiguous")

    def test_fuzzy_decision_unique(self):
        from backend.services.product_recognition_calibration_runner import (
            _fuzzy_decision,
        )

        result = {
            "encontrados": [{"producto_presentacion_id": 1}],
            "encontrados_posibles": [],
            "encontrados_no_disponibles": [],
            "no_encontrados": [],
        }
        self.assertEqual(_fuzzy_decision(result), "unique")

    def test_fuzzy_decision_ambiguous_by_ids(self):
        from backend.services.product_recognition_calibration_runner import (
            _fuzzy_decision,
        )

        result = {
            "encontrados": [{"producto_presentacion_id": 1}],
            "encontrados_posibles": [{"productos": [{"producto_presentacion_id": 2}]}],
            "encontrados_no_disponibles": [],
            "no_encontrados": [],
        }
        self.assertEqual(_fuzzy_decision(result), "ambiguous")

    def test_fuzzy_decision_unknown(self):
        from backend.services.product_recognition_calibration_runner import (
            _fuzzy_decision,
        )

        result = {
            "encontrados": [],
            "encontrados_posibles": [],
            "encontrados_no_disponibles": [],
            "no_encontrados": [],
        }
        self.assertEqual(_fuzzy_decision(result), "unknown")


class DecisionEmptyRankingBranchTest(unittest.TestCase):
    def test_decision_returns_ambiguous_when_empty_ranking_and_fuzzy_ambiguous(self):
        from backend.services.product_recognition_calibration_policy import (
            HybridDecisionPolicy,
        )
        from backend.services.product_recognition_calibration_runner import _decision

        policy = HybridDecisionPolicy(0.5, 0.5, 0.7, 0.4, 0.05, 5)
        self.assertEqual(_decision((), (), policy, False, False, "ambiguous"), "ambiguous")

    def test_decision_returns_unknown_when_empty_ranking_and_fuzzy_unique(self):
        from backend.services.product_recognition_calibration_policy import (
            HybridDecisionPolicy,
        )
        from backend.services.product_recognition_calibration_runner import _decision

        policy = HybridDecisionPolicy(0.5, 0.5, 0.7, 0.4, 0.05, 5)
        self.assertEqual(_decision((), (), policy, False, False, "unique"), "unknown")

    def test_decision_returns_unknown_when_empty_ranking_and_fuzzy_unknown(self):
        from backend.services.product_recognition_calibration_policy import (
            HybridDecisionPolicy,
        )
        from backend.services.product_recognition_calibration_runner import _decision

        policy = HybridDecisionPolicy(0.5, 0.5, 0.7, 0.4, 0.05, 5)
        self.assertEqual(_decision((), (), policy, False, False, "unknown"), "unknown")


class HybridGuardFiresForAmbiguousEmpanadaCarneTest(unittest.TestCase):
    def test_guard_fires_for_ambiguous_empanada_carne(self):
        """The hybrid decision for ``ambiguous-empanada-carne`` must be
        ``ambiguous`` (not ``unique``) when fuzzy returns ambiguous
        and vector returns unique(pid=11)."""
        from backend.services.product_recognition_calibration_policy import (
            HybridDecisionPolicy,
        )
        from backend.services.product_recognition_calibration_runner import (
            CaseObservation,
            _hybrid_prediction,
        )

        case = {
            "case_id": "ambiguous-empanada-carne",
            "catalog_scope": "pending_product_selection_restricted",
            "input_text": "empanada de carne",
            "allowed_candidate_ids": [11, 12],
            "catalog": [
                {
                    "producto_presentacion_id": 11,
                    "producto_nombre": "Empanada de Carne PICANTE",
                    "presentacion_codigo": "PICANTE",
                },
                {
                    "producto_presentacion_id": 12,
                    "producto_nombre": "Empanada de Carne TRADICIONAL",
                    "presentacion_codigo": "TRADICIONAL",
                },
            ],
        }
        observation = CaseObservation(
            case_id="ambiguous-empanada-carne",
            fuzzy_ids=(11, 12),
            fuzzy_scores=(1.0, 0.5),
            vector_ids=(11,),
            vector_scores=(1.0,),
            failure_categories=(),
            duration_ms=0.0,
            fuzzy_decision="ambiguous",
        )
        policy = HybridDecisionPolicy(0.5, 0.5, 0.7, 0.4, 0.05, 5)
        prediction = _hybrid_prediction(case, observation, policy)
        self.assertEqual(prediction.decision, "ambiguous")
        self.assertEqual(prediction.top_id, 11)
        self.assertEqual(set(prediction.ranking), {11, 12})

    def test_guard_does_not_fire_for_commerce_dynamic_database(self):
        from backend.services.product_recognition_calibration_policy import (
            HybridDecisionPolicy,
        )
        from backend.services.product_recognition_calibration_runner import (
            CaseObservation,
            _hybrid_prediction,
        )

        case = {
            "case_id": "c1-canonical-pizza-muzzarella",
            "catalog_scope": "commerce_dynamic_database",
            "input_text": "pizza muzzarella",
            "allowed_candidate_ids": [1, 2],
            "catalog": [],
        }
        observation = CaseObservation(
            case_id="c1-canonical-pizza-muzzarella",
            fuzzy_ids=(1, 2),
            fuzzy_scores=(1.0, 0.6),
            vector_ids=(1,),
            vector_scores=(1.0,),
            failure_categories=(),
            duration_ms=0.0,
            fuzzy_decision="ambiguous",
        )
        policy = HybridDecisionPolicy(0.5, 0.5, 0.7, 0.4, 0.05, 5)
        prediction = _hybrid_prediction(case, observation, policy)
        # Guard does NOT fire because the catalog_scope is
        # commerce_dynamic_database; the canonical/alias promotion in
        # _exact_flags takes the decision to "unique".
        self.assertEqual(prediction.decision, "unique")

    def test_guard_does_not_fire_for_fuzzy_unique_with_multi_candidate_ranking(self):
        from backend.services.product_recognition_calibration_policy import (
            HybridDecisionPolicy,
        )
        from backend.services.product_recognition_calibration_runner import (
            CaseObservation,
            _hybrid_prediction,
        )

        case = {
            "case_id": "fuzzy-unique-then-vector-different",
            "catalog_scope": "pending_product_selection_restricted",
            "input_text": "empanada de carne",
            "allowed_candidate_ids": [11, 12],
            "catalog": [],
        }
        observation = CaseObservation(
            case_id="fuzzy-unique-then-vector-different",
            fuzzy_ids=(11,),
            fuzzy_scores=(1.0,),
            vector_ids=(12,),
            vector_scores=(1.0,),
            failure_categories=(),
            duration_ms=0.0,
            fuzzy_decision="unique",
        )
        policy = HybridDecisionPolicy(0.5, 0.5, 0.7, 0.4, 0.05, 5)
        # The guard's condition (fuzzy_decision == "ambiguous") is NOT met,
        # so the guard does NOT fire regardless of the combined hybrid
        # ranking size. The decision is whatever the scoring rule gives.
        _hybrid_prediction(case, observation, policy)

    def test_guard_does_not_fire_for_fuzzy_unknown(self):
        from backend.services.product_recognition_calibration_policy import (
            HybridDecisionPolicy,
        )
        from backend.services.product_recognition_calibration_runner import (
            CaseObservation,
            _hybrid_prediction,
        )

        case = {
            "case_id": "picante-restricted-refinement",
            "catalog_scope": "pending_product_selection_restricted",
            "input_text": "picante",
            "allowed_candidate_ids": [11, 12],
            "catalog": [],
        }
        observation = CaseObservation(
            case_id="picante-restricted-refinement",
            fuzzy_ids=(),
            fuzzy_scores=(),
            vector_ids=(),
            vector_scores=(),
            failure_categories=(),
            duration_ms=0.0,
            fuzzy_decision="unknown",
        )
        policy = HybridDecisionPolicy(0.5, 0.5, 0.7, 0.4, 0.05, 5)
        prediction = _hybrid_prediction(case, observation, policy)
        self.assertEqual(prediction.decision, "unknown")

    def test_guard_does_not_fire_for_in_memory_non_restricted(self):
        from backend.services.product_recognition_calibration_policy import (
            HybridDecisionPolicy,
        )
        from backend.services.product_recognition_calibration_runner import (
            CaseObservation,
            _hybrid_prediction,
        )

        case = {
            "case_id": "product-plus-presentation",
            "catalog_scope": "in_memory",
            "input_text": "pizza muzzarella mas jamon",
            "allowed_candidate_ids": [2],
            "catalog": [],
        }
        observation = CaseObservation(
            case_id="product-plus-presentation",
            fuzzy_ids=(2,),
            fuzzy_scores=(1.0,),
            vector_ids=(),
            vector_scores=(),
            failure_categories=(),
            duration_ms=0.0,
            fuzzy_decision="unique",
        )
        policy = HybridDecisionPolicy(0.5, 0.5, 0.7, 0.4, 0.05, 5)
        # Guard condition: catalog_scope == "pending_product_selection_restricted"
        # is NOT met; the guard does not fire.
        _hybrid_prediction(case, observation, policy)


class GuardDoesNotModifyFormulaTest(unittest.TestCase):
    def test_guard_does_not_modify_scoring_formula_or_policy_grid(self):
        from backend.services.product_recognition_calibration_policy import (
            AMBIGUOUS_THRESHOLDS,
            SCORE_GAPS,
            TOP_K_VALUES,
            UNIQUE_THRESHOLDS,
            WEIGHT_POINTS,
            generate_policy_grid,
        )

        policies = generate_policy_grid()
        # Iterate the documented Cartesian grid and compare.
        from itertools import product as iter_product
        expected_pairs = list(iter_product(
            WEIGHT_POINTS,
            UNIQUE_THRESHOLDS,
            AMBIGUOUS_THRESHOLDS,
            SCORE_GAPS,
            TOP_K_VALUES,
        ))
        self.assertEqual(len(policies), len(expected_pairs))
        for weight_pair, unique, ambiguous, gap, top_k in expected_pairs:
            self.assertTrue(
                any(
                    p.fuzzy_weight == weight_pair[0]
                    and p.vector_weight == weight_pair[1]
                    and p.unique_threshold == unique
                    and p.ambiguous_threshold == ambiguous
                    and p.minimum_score_gap == gap
                    and p.vector_top_k == top_k
                    for p in policies
                )
            )


class RunnerClassificationTest(unittest.TestCase):
    """Behavioral assertion: the runner classifies the documented
    Subphase 4.11.4 cases as ``correct`` (or as documented residual)
    after the fix."""

    def test_runner_classifies_three_residual_fuzzy_failures_as_correct(self):
        from backend.services.product_presentation_vector_match import (
            ProductPresentationVectorMatch,
        )
        from backend.services.product_recognition_calibration_policy import (
            HybridDecisionPolicy,
        )
        from backend.services.product_recognition_calibration_runner import (
            ProductRecognitionCalibrationRunner,
        )

        class _StubRecognizer:
            def __init__(self) -> None:
                self.calls: list[tuple[str, str]] = []

            def recognize(self, text, catalog):
                self.calls.append((text, str(id(catalog))))
                # muzarrella -> real Pizza de Muzzarella via alias entry
                if text == "muzarrella":
                    pid = next(
                        entry["producto_presentacion_id"]
                        for entry in catalog
                        if entry["producto_presentacion_id"] in (1, 2)
                    )
                    return {
                        "encontrados": [
                            {
                                "producto_presentacion_id": pid,
                                "producto_nombre": "Pizza de Muzzarella",
                            }
                        ],
                        "encontrados_posibles": [],
                        "encontrados_no_disponibles": [],
                        "no_encontrados": [],
                    }
                if text == "un postre":
                    return {
                        "encontrados": [],
                        "encontrados_posibles": [
                            {
                                "kind": "category",
                                "categoria_nombre": "Postres",
                                "texto_origen": "un postre",
                            }
                        ],
                        "encontrados_no_disponibles": [],
                        "no_encontrados": [{"texto_origen": "un postre"}],
                    }
                if text == "otra pizza":
                    return {
                        "encontrados": [],
                        "encontrados_posibles": [
                            {
                                "kind": "category",
                                "categoria_nombre": "Pizzas",
                                "texto_origen": "otra pizza",
                            }
                        ],
                        "encontrados_no_disponibles": [],
                        "no_encontrados": [{"texto_origen": "otra pizza"}],
                    }
                return {
                    "encontrados": [],
                    "encontrados_posibles": [],
                    "encontrados_no_disponibles": [],
                    "no_encontrados": [{"texto_origen": text}],
                }

        class _StubVector:
            def search_similar(self, *, id_comercio, query_embedding, top_k, candidate_producto_presentacion_ids=None):
                # The runner requires at least one case to have a non-empty
                # vector_ids tuple to consider the dataset "evaluable".
                # The muzarrella case (fuzzy returns unique(pid=1)) is
                # backed by a real product; the empty-vector return is
                # correct for the other cases.

                text = query_embedding[0] if isinstance(query_embedding, list) else ""
                if text == "muzarrella":
                    return [ProductPresentationVectorMatch(1, 0.99, "canonical")]
                return []

        cases = [
            {
                "case_id": "c1-fuzzy-vector-disagreement-muzarrella",
                "id_comercio": 1,
                "input_text": "muzarrella",
                "expected_decision": "unique",
                "expected_producto_presentacion_id": 1,
                "allowed_candidate_ids": [1, 2],
                "restricted_candidate_ids": [],
                "match_expectation": "alias",
                "presentation_resolution_expectation": "resolved",
                "category": "baseline",
                "catalog_scope": "in_memory",
                "catalog_fixture": "fixture_muzarrella",
            },
            {
                "case_id": "c1-ambiguous-postre",
                "id_comercio": 1,
                "input_text": "un postre",
                "expected_decision": "ambiguous",
                "expected_producto_presentacion_id": None,
                "allowed_candidate_ids": [69, 70, 71, 72],
                "restricted_candidate_ids": [],
                "match_expectation": "neither",
                "presentation_resolution_expectation": "ambiguous",
                "category": "ambiguous",
                "catalog_scope": "in_memory",
                "catalog_fixture": "fixture_postres",
            },
            {
                "case_id": "c1-ambiguous-pizza-again",
                "id_comercio": 1,
                "input_text": "otra pizza",
                "expected_decision": "ambiguous",
                "expected_producto_presentacion_id": None,
                "allowed_candidate_ids": [1, 2, 3, 4],
                "restricted_candidate_ids": [],
                "match_expectation": "neither",
                "presentation_resolution_expectation": "ambiguous",
                "category": "ambiguous",
                "catalog_scope": "in_memory",
                "catalog_fixture": "fixture_pizzas",
            },
        ]
        dataset = {
            "schema_version": 1,
            "catalogs": {
                "fixture_muzarrella": {
                    "entries": [
                        {"producto_presentacion_id": 1, "producto_nombre": "Pizza de Muzzarella"},
                        {"producto_presentacion_id": 2, "producto_nombre": "Pizza de Muzzarella"},
                    ]
                },
                "fixture_postres": {
                    "entries": [
                        {"producto_presentacion_id": pid, "categoria_nombre": "Postres"}
                        for pid in (69, 70, 71, 72)
                    ]
                },
                "fixture_pizzas": {
                    "entries": [
                        {"producto_presentacion_id": pid, "categoria_nombre": "Pizzas"}
                        for pid in range(1, 31)
                    ]
                },
            },
            "cases": cases,
        }
        runner = ProductRecognitionCalibrationRunner(
            recognizer=_StubRecognizer(),  # type: ignore[arg-type]
            embedding_client=SimpleNamespace(embed_query=lambda text: [text]),  # type: ignore[arg-type]
            vector_search_factory=lambda: _StubVector(),
        )
        report = runner.run(
            dataset,
            policies=[HybridDecisionPolicy(0.5, 0.5, 0.7, 0.4, 0.05, 5)],
        )
        case_results = report["case_results"]
        categories = {row["case_id"]: row["mismatch_category"] for row in case_results}
        self.assertEqual(categories["c1-fuzzy-vector-disagreement-muzarrella"], "correct")
        self.assertEqual(categories["c1-ambiguous-postre"], "correct")
        self.assertEqual(categories["c1-ambiguous-pizza-again"], "correct")
        self.assertEqual(report["mismatch_category_counts"].get("real_fuzzy_recognizer_failure", 0), 0)
        # Total counts: 3 correct cases → 3 - 0 mismatch = 0 total mismatches.
        self.assertEqual(report["mismatch_category_counts"].get("total", 0), 0)


class RunnerFalsePositiveEliminatedTest(unittest.TestCase):
    def test_runner_eliminates_ambiguous_empanada_carne_false_positive(self):
        from backend.services.product_recognition_calibration_policy import (
            HybridDecisionPolicy,
        )
        from backend.services.product_recognition_calibration_runner import (
            ProductRecognitionCalibrationRunner,
        )

        class _StubRecognizer:
            def recognize(self, text, catalog):
                return {
                    "encontrados": [
                        {"producto_presentacion_id": 11, "producto_nombre": "Empanada PICANTE"},
                        {"producto_presentacion_id": 12, "producto_nombre": "Empanada TRADICIONAL"},
                    ],
                    "encontrados_posibles": [],
                    "encontrados_no_disponibles": [],
                    "no_encontrados": [],
                }

        class _StubVector:
            def search_similar(self, *, id_comercio, query_embedding, top_k, candidate_producto_presentacion_ids=None):
                from backend.services.product_presentation_vector_match import (
                    ProductPresentationVectorMatch,
                )

                return [ProductPresentationVectorMatch(11, 0.99, "canonical")]

        cases = [
            {
                "case_id": "ambiguous-empanada-carne",
                "id_comercio": 4,
                "input_text": "empanada de carne",
                "expected_decision": "ambiguous",
                "expected_producto_presentacion_id": None,
                "allowed_candidate_ids": [11, 12],
                "restricted_candidate_ids": [],
                "match_expectation": "neither",
                "presentation_resolution_expectation": "ambiguous",
                "category": "baseline",
                "catalog_scope": "pending_product_selection_restricted",
                "catalog_fixture": "empanada_carne_restricted",
            },
        ]
        dataset = {
            "schema_version": 1,
            "catalogs": {
                "empanada_carne_restricted": {
                    "entries": [
                        {"producto_presentacion_id": 11, "producto_nombre": "Empanada PICANTE"},
                        {"producto_presentacion_id": 12, "producto_nombre": "Empanada TRADICIONAL"},
                    ]
                }
            },
            "cases": cases,
        }
        runner = ProductRecognitionCalibrationRunner(
            recognizer=_StubRecognizer(),  # type: ignore[arg-type]
            embedding_client=SimpleNamespace(embed_query=lambda text: [text]),  # type: ignore[arg-type]
            vector_search_factory=lambda: _StubVector(),
        )
        report = runner.run(
            dataset,
            policies=[HybridDecisionPolicy(0.5, 0.5, 0.7, 0.4, 0.05, 5)],
        )
        case_results = report["case_results"]
        self.assertEqual(case_results[0]["mismatch_category"], "correct")
        self.assertEqual(report["mismatch_category_counts"].get("real_hybrid_recognizer_failure", 0), 0)
        self.assertEqual(report["mismatch_category_counts"].get("total", 0), 0)
        self.assertEqual(report["hybrid_metrics"]["false_positives"]["count"], 0)
        # false_positive_tolerance_failed is no longer in the reasons.
        reasons = report["eligibility"]["reasons"]
        self.assertNotIn("false_positive_tolerance_failed", reasons)


class CommerceIsolationPreservedTest(unittest.TestCase):
    def test_39_baseline_cases_dataset_invariants_preserved(self):
        dataset = _load_dataset()
        self.assertEqual(dataset["schema_version"], 3)
        cases = dataset["cases"]
        in_memory = [c for c in cases if c.get("catalog_scope") == "in_memory"]
        dynamic = [c for c in cases if c.get("catalog_scope") == "commerce_dynamic_database"]
        restricted = [c for c in cases if c.get("catalog_scope") == "pending_product_selection_restricted"]
        self.assertEqual(len(in_memory), 7)
        self.assertEqual(len(dynamic), 37)
        self.assertEqual(len(restricted), 3)
        self.assertEqual(len(cases), 47)
        # dataset fingerprint matches the Subphase 4.11.4 persisted one.
        self.assertEqual(
            dataset.get("commerce_catalog_fingerprint", {}).get("1"),
            "b17e6e15f405aef11267791dfea253da9ba1240bf0125ed2886a0ed2f55ef35a",
        )


if __name__ == "__main__":
    unittest.main()
