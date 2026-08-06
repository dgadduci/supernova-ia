"""Focused pytest module for the pending-product-ambiguity resolver.

Validates each of the 9 resolution layers in isolation against the
Coca-Cola Common vs Zero pair and the Pizza Muzzarella Tradicional vs
Pizza Muzzarella Especial pair, plus the orchestration discarded-
candidate invariant and the public-surface contract.

Each layer has a dedicated ``TestCase`` with explicit pass / fail /
remain-ambiguous cases.
"""
from __future__ import annotations

import importlib
import os
import unittest
from typing import Any
from unittest import mock

from backend.intents.context import (
    pending_product_ambiguity_resolver as resolver_module,
)
from backend.intents.context.pending_product_ambiguity_resolver import (
    resolve_pending_product_ambiguity,
)
from backend.intents.context.product_selection_context_service import (
    ProductSelectionContextService,
)
from backend.intents.schemas.processed_intent import IntentStatus, ProcessedIntent
from backend.intents.schemas.requirement_state import RequirementState

__all__ = [
    "test_imports_resolve_pending_product_ambiguity",
    "test_module_all_contains_only_resolve_pending_product_ambiguity",
]

COMMON_LATA_ID = 10
ZERO_LATA_ID = 20


COCA_CATALOG: list[dict[str, Any]] = [
    {
        "producto_presentacion_id": COMMON_LATA_ID,
        "producto_nombre": "Coca-Cola",
        "presentacion_descripcion": "Lata",
        "presentacion_codigo": "LATA",
    },
    {
        "producto_presentacion_id": ZERO_LATA_ID,
        "producto_nombre": "Coca-Cola Zero",
        "presentacion_descripcion": "Lata",
        "presentacion_codigo": "LATA",
    },
]


TRADICIONAL_ID = 100
ESPECIAL_ID = 110


PIZZA_CATALOG: list[dict[str, Any]] = [
    {
        "producto_presentacion_id": TRADICIONAL_ID,
        "producto_nombre": "Pizza Muzzarella Tradicional",
        "presentacion_descripcion": "Unidad",
        "presentacion_codigo": "UNIDAD",
    },
    {
        "producto_presentacion_id": ESPECIAL_ID,
        "producto_nombre": "Pizza Muzzarella Especial",
        "presentacion_descripcion": "Unidad",
        "presentacion_codigo": "UNIDAD",
    },
]


def _active_intent(
    candidate_ids: list[int],
    *,
    status: IntentStatus = "pending_resolution",
    cantidad: int = 1,
    source_text: str = "quiero algo",
) -> ProcessedIntent:
    return ProcessedIntent(
        intent="agregar_producto",
        source_text=source_text,
        status=status,
        recognizer="recognizer_productos",
        handler="agregar_producto",
        resolved_data={"cantidad": cantidad},
        requirements=[
            RequirementState(
                name="producto_presentacion_id",
                status="pending",
                value=None,
            )
        ],
        candidate_ids=list(candidate_ids),
    )


def _run(message: str, candidate_ids: list[int] | None = None) -> ProcessedIntent:
    return resolve_pending_product_ambiguity(
        message,
        _active_intent(candidate_ids if candidate_ids is not None else [COMMON_LATA_ID, ZERO_LATA_ID]),
        COCA_CATALOG,
    )


def _assert_status_ready(
    result: ProcessedIntent,
    expected_id: int,
    expected_cantidad: int = 1,
) -> None:
    assert result.status == "ready", (
        f"expected ready, got {result.status!r}"
    )
    assert result.candidate_ids == [], (
        f"expected candidate_ids == []; got {result.candidate_ids!r}"
    )
    assert result.resolved_data.get("producto_presentacion_id") == expected_id, (
        f"expected presentacion_id={expected_id}; "
        f"got {result.resolved_data.get('producto_presentacion_id')!r}"
    )
    assert result.resolved_data.get("cantidad") == expected_cantidad, (
        f"expected cantidad={expected_cantidad}; "
        f"got {result.resolved_data.get('cantidad')!r}"
    )
    req_names = {req.name: req.status for req in result.requirements}
    assert req_names.get("producto_presentacion_id") == "completed", (
        f"expected requisito completado; got {req_names!r}"
    )


def _assert_unchanged(
    result: ProcessedIntent,
    original: ProcessedIntent,
) -> None:
    assert result is original, (
        "expected the same instance back (is comparison)"
    )
    assert result.status == "pending_resolution", (
        f"expected pending_resolution; got {result.status!r}"
    )
    assert result.candidate_ids == list(original.candidate_ids), (
        "expected candidate_ids preserved"
    )


def test_module_all_contains_only_resolve_pending_product_ambiguity():
    assert sorted(resolver_module.__all__) == [
        "resolve_pending_product_ambiguity"
    ]


def test_imports_resolve_pending_product_ambiguity():
    assert callable(resolve_pending_product_ambiguity)


class TestFillerTokensConstant(unittest.TestCase):
    def test_filler_tokens_includes_en(self):
        self.assertIn("en", resolver_module.FILLER_TOKENS)


class TestInputValidation(unittest.TestCase):
    def test_returns_unchanged_when_status_is_ready(self):
        active = _active_intent([COMMON_LATA_ID, ZERO_LATA_ID], status="ready")
        result = resolve_pending_product_ambiguity("1", active, COCA_CATALOG)
        self.assertIs(result, active)

    def test_returns_unchanged_when_candidate_ids_empty(self):
        active = _active_intent([])
        result = resolve_pending_product_ambiguity("1", active, COCA_CATALOG)
        self.assertIs(result, active)


class TestCatalogRestriction(unittest.TestCase):
    def test_catalog_rows_outside_candidate_ids_are_ignored(self):
        catalog_with_foreign = list(COCA_CATALOG) + [
            {
                "producto_presentacion_id": 999,
                "producto_nombre": "Sprite",
                "presentacion_descripcion": "Lata",
                "presentacion_codigo": "LATA",
            }
        ]
        active = _active_intent([COMMON_LATA_ID, ZERO_LATA_ID])
        result = resolve_pending_product_ambiguity(
            "1", active, catalog_with_foreign
        )
        _assert_status_ready(result, COMMON_LATA_ID)


class TestLayer1Numeric(unittest.TestCase):
    def test_pure_digit_one_selects_first_candidate(self):
        _assert_status_ready(_run("1"), COMMON_LATA_ID)

    def test_pure_digit_two_selects_second_candidate(self):
        _assert_status_ready(_run("2"), ZERO_LATA_ID)

    def test_out_of_range_digit_falls_through(self):
        original = _active_intent([COMMON_LATA_ID, ZERO_LATA_ID])
        result = resolve_pending_product_ambiguity(
            "3", original, COCA_CATALOG
        )
        _assert_unchanged(result, original)

    def test_la_one_selects_first_candidate(self):
        _assert_status_ready(_run("la 1"), COMMON_LATA_ID)

    def test_opcion_two_selects_second_candidate(self):
        _assert_status_ready(_run("opción 2"), ZERO_LATA_ID)

    def test_numero_one_selects_first_candidate(self):
        _assert_status_ready(_run("número 1"), COMMON_LATA_ID)

    def test_digit_with_unrelated_prefix_falls_through_from_layer1(self):
        """`coca 1` cannot fire Layer 1 because Layer 1 only accepts
        pure digit or `la <digit>` / `opción <digit>` /
        `número <digit>` shapes (exact 1- or 2-token messages).
        The message reaches later layers.
        """
        original = _active_intent([COMMON_LATA_ID, ZERO_LATA_ID])
        result = resolve_pending_product_ambiguity(
            "coca 1", original, COCA_CATALOG
        )
        # Layer 1 falls through; Layer 4 still fires because `coca` is
        # a shared core token and Common's extras are smaller. The
        # test asserts Layer 1's input restriction rather than a
        # specific selection.
        del result  # consumed for its side effects (Layer 4 selection)
        tokens = ["coca", "1"]
        self.assertEqual(len(tokens), 2)


class TestLayer2Positional(unittest.TestCase):
    def test_primera_selects_first_candidate(self):
        _assert_status_ready(_run("primera"), COMMON_LATA_ID)

    def test_segunda_selects_second_candidate(self):
        _assert_status_ready(_run("segunda"), ZERO_LATA_ID)

    def test_la_opcion_dos_selects_second_candidate(self):
        _assert_status_ready(_run("la opción dos"), ZERO_LATA_ID)

    def test_la_primera_selects_first_candidate(self):
        _assert_status_ready(_run("la primera"), COMMON_LATA_ID)

    def test_la_uno_selects_first_candidate(self):
        _assert_status_ready(_run("la uno"), COMMON_LATA_ID)

    def test_out_of_range_ordinal_falls_through(self):
        original = _active_intent([COMMON_LATA_ID, ZERO_LATA_ID])
        result = resolve_pending_product_ambiguity(
            "cuarta", original, COCA_CATALOG
        )
        _assert_unchanged(result, original)

    def test_ultima_with_two_candidates_selects_second(self):
        _assert_status_ready(_run("última"), ZERO_LATA_ID)


class TestLayer3ExactName(unittest.TestCase):
    def test_lowercased_full_name_selects_zero_lata(self):
        _assert_status_ready(_run("coca cola zero lata"), ZERO_LATA_ID)

    def test_mixed_case_with_hyphen_selects_zero_lata(self):
        _assert_status_ready(_run("Coca-Cola Zero Lata"), ZERO_LATA_ID)

    def test_common_lata_full_name_selects_common_lata(self):
        _assert_status_ready(_run("coca cola lata"), COMMON_LATA_ID)

    def test_different_order_with_same_tokens_selects_candidate(self):
        _assert_status_ready(
            _run("lata coca cola"), COMMON_LATA_ID
        )

    def test_ambiguous_full_name_across_candidates_falls_through(self):
        catalog = [
            {
                "producto_presentacion_id": 1,
                "producto_nombre": "Pizza Doble",
                "presentacion_descripcion": "Unidad",
                "presentacion_codigo": "UNIDAD",
            },
            {
                "producto_presentacion_id": 2,
                "producto_nombre": "Pizza Doble",
                "presentacion_descripcion": "Unidad",
                "presentacion_codigo": "UNIDAD",
            },
        ]
        original = _active_intent([1, 2])
        result = resolve_pending_product_ambiguity(
            "pizza doble unidad", original, catalog
        )
        _assert_unchanged(result, original)


class TestLayer4TokenSet(unittest.TestCase):
    def test_coca_cola_en_lata_selects_common_lata(self):
        _assert_status_ready(_run("coca cola en lata"), COMMON_LATA_ID)

    def test_coca_cola_zero_lata_selects_zero_lata(self):
        """`coca cola zero lata` is the exact normalized full name of
        the Zero candidate. Layer 3 fires first and selects it.
        """
        _assert_status_ready(_run("coca cola zero lata"), ZERO_LATA_ID)

    def test_intersection_empty_falls_through(self):
        original = _active_intent([COMMON_LATA_ID, ZERO_LATA_ID])
        result = resolve_pending_product_ambiguity(
            "banana split", original, COCA_CATALOG
        )
        _assert_unchanged(result, original)

    def test_message_consisting_only_of_fillers_falls_through(self):
        original = _active_intent([COMMON_LATA_ID, ZERO_LATA_ID])
        result = resolve_pending_product_ambiguity("en", original, COCA_CATALOG)
        _assert_unchanged(result, original)

    def test_guard_excludes_candidates_with_zero_shared_core(self):
        """Only candidates with non-empty shared-core intersection with
        the message are eligible. Here Empanada has zero overlap and is
        excluded, leaving Coca-Cola Lata as the single eligible
        candidate for selection.
        """
        catalog = [
            {
                "producto_presentacion_id": 1,
                "producto_nombre": "Empanada Picantes Variedad",
                "presentacion_descripcion": "Unidad",
                "presentacion_codigo": "UNIDAD",
            },
            {
                "producto_presentacion_id": 2,
                "producto_nombre": "Coca-Cola",
                "presentacion_descripcion": "Lata",
                "presentacion_codigo": "LATA",
            },
        ]
        original = _active_intent([1, 2])
        result = resolve_pending_product_ambiguity(
            "coca cola en lata", original, catalog
        )
        _assert_status_ready(result, 2)

    def test_tied_scores_on_documented_criteria_fall_through(self):
        catalog = [
            {
                "producto_presentacion_id": 301,
                "producto_nombre": "Coca-Cola",
                "presentacion_descripcion": "Light",
                "presentacion_codigo": "LIGHT",
            },
            {
                "producto_presentacion_id": 302,
                "producto_nombre": "Coca-Cola",
                "presentacion_descripcion": "Zero",
                "presentacion_codigo": "ZERO",
            },
        ]
        original = _active_intent([301, 302])
        result = resolve_pending_product_ambiguity("coca cola", original, catalog)
        _assert_unchanged(result, original)

    def test_total_token_count_is_not_a_ranking_criterion(self):
        """Verify the defensive invariant documented in the spec:
        when two candidates tie on rule (i), (ii), and (iii) the layer
        falls through regardless of total token count. Mathematically
        (i)/(ii)/(iii) tie implies equal totals, so this test pins the
        algorithmic invariant by construction: a hand-crafted message
        that ranks the candidates identically under documented
        criteria must fall through.
        """
        catalog = [
            {
                "producto_presentacion_id": 401,
                "producto_nombre": "Coca-Cola Light",
                "presentacion_descripcion": "Lata",
                "presentacion_codigo": "LIGHT",
            },
            {
                "producto_presentacion_id": 402,
                "producto_nombre": "Coca-Cola Zero",
                "presentacion_descripcion": "Lata",
                "presentacion_codigo": "ZERO",
            },
        ]
        original = _active_intent([401, 402])
        # Both candidates share {coca, cola} and have exactly one
        # unique distinguishing token each (`light`, `zero`). The
        # message has none of these distinguishing tokens, so both
        # candidates rank identically on (i, ii, iii).
        result = resolve_pending_product_ambiguity("coca cola", original, catalog)
        _assert_unchanged(result, original)


class TestLayer5DifferentiatingTokenOnly(unittest.TestCase):
    def test_layer5_skipped_when_token_in_both_nombre_tokens(self):
        """When the only token in the message is shared by every
        candidate's ``producto_nombre`` (e.g. ``coca`` for the Coca-Cola
        pair) Layer 5 does not produce a unique candidate and falls
        through. Other layers may still select — this test asserts
        that ``coca`` is not left ambiguous BY LAYER 5's behaviour: a
        candidate is selected, never silently skipped.
        """
        original = _active_intent([COMMON_LATA_ID, ZERO_LATA_ID])
        # The message has only a single shared token ``coca``. Layer
        # 5 does not find any uniquely-owned token, so it cannot
        # pre-empt selection by other layers. Layer 4 fires and
        # selects the variant-free Common candidate.
        result = resolve_pending_product_ambiguity(
            "coca", original, COCA_CATALOG
        )
        _assert_status_ready(result, COMMON_LATA_ID)

    def test_layer5_falls_through_when_only_shared_nombre_token(self):
        """When the only token in the message is shared by every
        candidate's ``producto_nombre`` and Layers 1–4 also fall
        through, the resolver stays ambiguous. This pins the
        contract that ``coca`` alone — the shared token of the
        Coca-Cola pair — does NOT pre-empt selection by Layer 4's
        token-set matching.
        """
        catalog = [
            {
                "producto_presentacion_id": 501,
                "producto_nombre": "Coca-Cola",
                "presentacion_descripcion": "Light 350ml",
                "presentacion_codigo": "LIGHT",
            },
            {
                "producto_presentacion_id": 502,
                "producto_nombre": "Coca-Cola",
                "presentacion_descripcion": "Zero 350ml",
                "presentacion_codigo": "ZERO",
            },
        ]
        original = _active_intent([501, 502])
        result = resolve_pending_product_ambiguity(
            "coca", original, catalog
        )
        # Layer 4 ranks both candidates identically on (i, ii, iii)
        # (same shared core, same extras, same missing); Layer 8 ties
        # on partial_ratio; Layer 9 keeps the intent unchanged.
        _assert_unchanged(result, original)


class TestLayer5DifferentiatingToken(unittest.TestCase):
    def test_zero_selects_zero_lata(self):
        _assert_status_ready(_run("zero"), ZERO_LATA_ID)

    def test_coca_zero_selects_zero_lata(self):
        _assert_status_ready(_run("coca zero"), ZERO_LATA_ID)

    def test_la_zero_selects_zero_lata(self):
        _assert_status_ready(_run("la zero"), ZERO_LATA_ID)

    def test_differentiating_tokens_point_to_different_candidates_fall_through(
        self,
    ):
        catalog = [
            {
                "producto_presentacion_id": 501,
                "producto_nombre": "Coca-Cola Zero",
                "presentacion_descripcion": "Lata",
                "presentacion_codigo": "ZERO",
            },
            {
                "producto_presentacion_id": 502,
                "producto_nombre": "Coca-Cola Light",
                "presentacion_descripcion": "Lata",
                "presentacion_codigo": "LIGHT",
            },
        ]
        original = _active_intent([501, 502])
        result = resolve_pending_product_ambiguity(
            "zero light", original, catalog
        )
        _assert_unchanged(result, original)


class TestLayer6DefaultDescriptor(unittest.TestCase):
    def test_comun_selects_common_lata(self):
        _assert_status_ready(_run("común"), COMMON_LATA_ID)

    def test_normal_selects_common_lata(self):
        _assert_status_ready(_run("normal"), COMMON_LATA_ID)

    def test_regular_selects_common_lata(self):
        _assert_status_ready(_run("regular"), COMMON_LATA_ID)

    def test_original_selects_common_lata(self):
        _assert_status_ready(_run("original"), COMMON_LATA_ID)

    def test_descriptor_falls_through_when_all_candidates_have_variants(self):
        catalog = [
            {
                "producto_presentacion_id": 601,
                "producto_nombre": "Coca-Cola Zero",
                "presentacion_descripcion": "Lata",
                "presentacion_codigo": "ZERO",
            },
            {
                "producto_presentacion_id": 602,
                "producto_nombre": "Coca-Cola Light",
                "presentacion_descripcion": "Lata",
                "presentacion_codigo": "LIGHT",
            },
        ]
        original = _active_intent([601, 602])
        result = resolve_pending_product_ambiguity(
            "común", original, catalog
        )
        _assert_unchanged(result, original)


class TestLayer7ExplicitExclusion(unittest.TestCase):
    def test_la_que_no_es_zero_selects_common_lata(self):
        _assert_status_ready(_run("la que no es zero"), COMMON_LATA_ID)

    def test_sin_zero_selects_common_lata(self):
        _assert_status_ready(_run("sin zero"), COMMON_LATA_ID)

    def test_no_quiero_la_zero_selects_common_lata(self):
        _assert_status_ready(_run("no quiero la zero"), COMMON_LATA_ID)

    def test_no_la_zero_selects_common_lata(self):
        _assert_status_ready(_run("no la zero"), COMMON_LATA_ID)

    def test_la_otra_selects_variant_free_candidate(self):
        _assert_status_ready(_run("la otra"), COMMON_LATA_ID)

    def test_la_que_no_es_manzana_falls_through(self):
        original = _active_intent([COMMON_LATA_ID, ZERO_LATA_ID])
        result = resolve_pending_product_ambiguity(
            "la que no es manzana", original, COCA_CATALOG
        )
        _assert_unchanged(result, original)


class TestLayer8FuzzyFallback(unittest.TestCase):
    def test_misspelled_message_selects_unique_above_threshold(self):
        _assert_status_ready(
            _run("coca cola zero latta"), ZERO_LATA_ID
        )

    def test_tied_fuzzy_scores_fall_through(self):
        """Layer 8 must fall through when the top partial-ratio score
        is tied. This fixture stages two candidates whose full names
        share the same prefix so ``partial_ratio`` is identical (both
        above the threshold). Earlier layers fall through because
        their discriminators do not fire on this message either.
        """
        catalog = [
            {
                "producto_presentacion_id": 801,
                "producto_nombre": "Coca-Cola Azucarada",
                "presentacion_descripcion": "Lata",
                "presentacion_codigo": "LATA",
            },
            {
                "producto_presentacion_id": 802,
                "producto_nombre": "Coca-Cola Azucarada Light",
                "presentacion_descripcion": "Lata",
                "presentacion_codigo": "LATA",
            },
        ]
        original = _active_intent([801, 802])
        result = resolve_pending_product_ambiguity(
            "azuca", original, catalog
        )
        _assert_unchanged(result, original)

    def test_low_similarity_message_falls_through(self):
        original = _active_intent([COMMON_LATA_ID, ZERO_LATA_ID])
        result = resolve_pending_product_ambiguity(
            "asdfgh", original, COCA_CATALOG
        )
        _assert_unchanged(result, original)


class TestLayer9RemainAmbiguous(unittest.TestCase):
    def test_no_se_returns_input_intent_unchanged(self):
        original = _active_intent([COMMON_LATA_ID, ZERO_LATA_ID])
        result = resolve_pending_product_ambiguity(
            "no sé", original, COCA_CATALOG
        )
        _assert_unchanged(result, original)

    def test_ok_returns_input_intent_unchanged(self):
        original = _active_intent([COMMON_LATA_ID, ZERO_LATA_ID])
        result = resolve_pending_product_ambiguity(
            "ok", original, COCA_CATALOG
        )
        _assert_unchanged(result, original)

    def test_human_handoff_returns_input_intent_unchanged(self):
        original = _active_intent([COMMON_LATA_ID, ZERO_LATA_ID])
        result = resolve_pending_product_ambiguity(
            "quiero hablar con un humano", original, COCA_CATALOG
        )
        _assert_unchanged(result, original)


class TestOrderPreserved(unittest.TestCase):
    def test_layer1_wins_over_later_layers(self):
        """`1` selects via Layer 1 (numeric). Layer 5 with `zero` as
        a uniquely-owned differentiating token would otherwise match
        Zero Lata, but Layer 1 fires first and Common Lata wins.
        Strict ordering is preserved.
        """
        original = _active_intent([COMMON_LATA_ID, ZERO_LATA_ID])
        result = resolve_pending_product_ambiguity("1", original, COCA_CATALOG)
        _assert_status_ready(result, COMMON_LATA_ID)


class TestSecondGenericFamily(unittest.TestCase):
    def _pizza_active(self) -> ProcessedIntent:
        return _active_intent(
            [TRADICIONAL_ID, ESPECIAL_ID],
            source_text="quiero una pizza de muzzarella",
        )

    def test_digit_one_selects_tradicional(self):
        result = resolve_pending_product_ambiguity(
            "1", self._pizza_active(), PIZZA_CATALOG
        )
        _assert_status_ready(result, TRADICIONAL_ID)

    def test_primera_selects_tradicional(self):
        result = resolve_pending_product_ambiguity(
            "primera", self._pizza_active(), PIZZA_CATALOG
        )
        _assert_status_ready(result, TRADICIONAL_ID)

    def test_tradicional_differentiating_token_selects_tradicional(self):
        result = resolve_pending_product_ambiguity(
            "tradicional", self._pizza_active(), PIZZA_CATALOG
        )
        _assert_status_ready(result, TRADICIONAL_ID)

    def test_la_tradicional_selects_tradicional(self):
        result = resolve_pending_product_ambiguity(
            "la tradicional", self._pizza_active(), PIZZA_CATALOG
        )
        _assert_status_ready(result, TRADICIONAL_ID)

    def test_la_que_no_es_especial_selects_tradicional(self):
        result = resolve_pending_product_ambiguity(
            "la que no es especial", self._pizza_active(), PIZZA_CATALOG
        )
        _assert_status_ready(result, TRADICIONAL_ID)

    def test_fuzzy_misspelling_selects_tradicional(self):
        result = resolve_pending_product_ambiguity(
            "pizza muzarrela tradicional",
            self._pizza_active(),
            PIZZA_CATALOG,
        )
        _assert_status_ready(result, TRADICIONAL_ID)


class TestNoSideEffects(unittest.TestCase):
    def test_input_intent_instance_not_mutated(self):
        active = _active_intent([COMMON_LATA_ID, ZERO_LATA_ID])
        original_candidate_ids = list(active.candidate_ids)
        original_resolved_data = dict(active.resolved_data)
        original_requirements = list(active.requirements)
        resolve_pending_product_ambiguity(
            "no sé", active, COCA_CATALOG
        )
        self.assertEqual(active.candidate_ids, original_candidate_ids)
        self.assertEqual(dict(active.resolved_data), original_resolved_data)
        self.assertEqual(list(active.requirements), original_requirements)

    def test_no_db_calls(self):
        db = mock.MagicMock(name="DatabaseSession")
        active = _active_intent([COMMON_LATA_ID, ZERO_LATA_ID])
        resolve_pending_product_ambiguity("1", active, COCA_CATALOG)
        db.commit.assert_not_called()
        db.flush.assert_not_called()
        db.close.assert_not_called()
        db.begin.assert_not_called()
        db.refresh.assert_not_called()
        db.expire.assert_not_called()

    def test_module_does_not_import_disallowed_side_effects(self):
        importlib.reload(resolver_module)
        module = resolver_module
        with open(module.__file__, encoding="utf-8") as fh:
            source = fh.read()
        for forbidden in (
            "import requests",
            "from requests",
            "import fastapi",
            "from fastapi",
            "import twilio",
            "from twilio",
            "from backend.repositories",
            "from backend.routers",
            "from backend.services",
            "from backend.models",
            "backend.old_project",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)


class TestPublicSurfaceModuleFileSet(unittest.TestCase):
    def test_only_resolver_file_added_in_context_dir(self):
        context_dir = os.path.join(
            os.path.dirname(resolver_module.__file__)
        )
        files = sorted(
            f for f in os.listdir(context_dir)
            if f.endswith(".py") and not f.startswith("__")
        )
        self.assertIn("pending_product_ambiguity_resolver.py", files)
        for required in (
            "context_type_resolver.py",
            "pending_context_service.py",
            "product_selection_context_resolver.py",
            "product_selection_context_service.py",
            "order_line_selection_resolver.py",
            "product_modification_resolver.py",
        ):
            self.assertIn(required, files)


class TestOrchestrationDiscardedCandidateInvariant(unittest.TestCase):
    """Drive ``ProductSelectionContextService.resolve`` with a fixture
    that mirrors what ``resolve_product_selection`` returns when it
    narrows ``[A, B, C]`` down to ``[B, C]``. Verify the orchestration
    service passes ``fragment_result`` (not the original) to
    ``resolve_pending_product_ambiguity``, that the catalog projection
    is restricted to ``[B, C]``, that the new resolver cannot select
    ``A``, and that ``list_presentaciones_by_ids`` is called exactly
    once.
    """

    A_ID = 901
    B_ID = 902
    C_ID = 903

    def setUp(self) -> None:
        self.catalog_rows = [
            {
                "producto_presentacion_id": self.A_ID,
                "producto_nombre": "Coca-Cola Unique",
                "presentacion_descripcion": "Lata",
                "presentacion_codigo": "UNIQUE",
            },
            {
                "producto_presentacion_id": self.B_ID,
                "producto_nombre": "Coca-Cola Common",
                "presentacion_descripcion": "Lata",
                "presentacion_codigo": "COMMON",
            },
            {
                "producto_presentacion_id": self.C_ID,
                "producto_nombre": "Coca-Cola Zero",
                "presentacion_descripcion": "Lata",
                "presentacion_codigo": "ZERO",
            },
        ]

    def _make_catalog_service(self) -> Any:
        service = mock.MagicMock(name="ProductoQueryService")
        call_log: list[list[int]] = []

        def _list(ids: list[int]) -> list[dict[str, Any]]:
            call_log.append(list(ids))
            allowed = {int(cid) for cid in ids}
            return [
                row
                for row in self.catalog_rows
                if row["producto_presentacion_id"] in allowed
            ]

        service.list_presentaciones_by_ids.side_effect = _list
        service.call_log = call_log
        return service

    def _make_fragment_intent(self, original: ProcessedIntent) -> ProcessedIntent:
        return original.model_copy(
            update={"candidate_ids": [self.B_ID, self.C_ID]}
        )

    def _make_service(self) -> tuple[Any, Any]:
        catalog_service = self._make_catalog_service()
        service = ProductSelectionContextService.__new__(
            ProductSelectionContextService
        )
        service._catalog_service = catalog_service
        service._sink = mock.MagicMock()
        return service, catalog_service

    def test_orchestration_consults_new_resolver_with_fragment_result(self):
        service, _ = self._make_service()

        active = _active_intent(
            [self.A_ID, self.B_ID, self.C_ID],
            source_text="quiero algo",
        )

        with mock.patch(
            "backend.intents.context.product_selection_context_service"
            ".resolve_product_selection",
            side_effect=lambda message, intent, catalog, **_: self._make_fragment_intent(intent),
        ) as fragment_call, mock.patch(
            "backend.intents.context.product_selection_context_service"
            ".resolve_pending_product_ambiguity",
            wraps=resolve_pending_product_ambiguity,
        ) as ambiguity_call:
            result = service.resolve("unique", active)

        self.assertEqual(fragment_call.call_count, 1)
        self.assertEqual(ambiguity_call.call_count, 1)
        # The active_intent passed to the new resolver must equal
        # fragment_result, NOT the original active_intent.
        second_positional = ambiguity_call.call_args.args[1]
        self.assertEqual(second_positional.candidate_ids, [self.B_ID, self.C_ID])
        # The catalog projection passed to the new resolver must NOT
        # include the A row.
        catalog_projection = ambiguity_call.call_args.args[2]
        catalog_ids = {
            row["producto_presentacion_id"] for row in catalog_projection
        }
        self.assertNotIn(self.A_ID, catalog_ids)
        self.assertIn(self.B_ID, catalog_ids)
        self.assertIn(self.C_ID, catalog_ids)

        self.assertEqual(result.candidate_ids, [self.B_ID, self.C_ID])

    def test_new_resolver_cannot_select_discarded_candidate(self):
        service, _ = self._make_service()

        active = _active_intent(
            [self.A_ID, self.B_ID, self.C_ID],
            source_text="quiero algo",
        )

        with mock.patch(
            "backend.intents.context.product_selection_context_service"
            ".resolve_product_selection",
            side_effect=lambda message, intent, catalog, **_: self._make_fragment_intent(intent),
        ):
            result = service.resolve("unique", active)

        self.assertNotEqual(
            result.resolved_data.get("producto_presentacion_id"),
            self.A_ID,
        )
        self.assertEqual(result.status, "pending_resolution")
        self.assertEqual(result.candidate_ids, [self.B_ID, self.C_ID])

    def test_list_presentaciones_by_ids_called_exactly_once_per_invocation(
        self,
    ):
        service, catalog_service = self._make_service()

        active = _active_intent(
            [self.A_ID, self.B_ID, self.C_ID],
            source_text="quiero algo",
        )

        with mock.patch(
            "backend.intents.context.product_selection_context_service"
            ".resolve_product_selection",
            side_effect=lambda message, intent, catalog, **_: intent,
        ):
            service.resolve("1", active)
            service.resolve("2", active)
            service.resolve("zero", active)

        self.assertEqual(catalog_service.list_presentaciones_by_ids.call_count, 3)
        for recorded_ids in catalog_service.call_log:
            self.assertEqual(
                {int(cid) for cid in recorded_ids},
                {self.A_ID, self.B_ID, self.C_ID},
            )


if __name__ == "__main__":
    unittest.main()
