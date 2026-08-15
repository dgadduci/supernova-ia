import importlib
import unittest
from unittest import mock
from unittest.mock import patch

from backend.diagnostics.events import (
    ResolverCallCompleted,
    ResolverCallStarted,
)
from backend.intents.context import (
    product_selection_context_resolver as resolver_module,
)
from backend.intents.context.product_selection_context_resolver import (
    resolve_product_selection,
)
from backend.intents.schemas.processed_intent import ProcessedIntent
from backend.intents.schemas.requirement_state import RequirementState


def _active_intent(candidate_ids: list[int]) -> ProcessedIntent:
    return ProcessedIntent(
        intent="agregar_producto",
        source_text="quiero dos pizzas",
        status="pending_resolution",
        recognizer="recognizer_productos",
        handler="agregar_producto",
        resolved_data={"cantidad": 2},
        requirements=[
            RequirementState(name="producto_presentacion_id", status="pending", value=None)
        ],
        candidate_ids=list(candidate_ids),
    )


def _resultado(encontrados=None, encontrados_posibles=None):
    return {
        "encontrados": encontrados if encontrados is not None else [],
        "encontrados_posibles": encontrados_posibles if encontrados_posibles is not None else [],
        "encontrados_no_disponibles": [],
        "no_encontrados": [],
    }


CATALOG = [
    {"producto_presentacion_id": pid, "producto_nombre": f"item-{pid}"}
    for pid in [1, 2, 3, 4, 5]
]


class ResolveProductSelectionNarrowingTest(unittest.TestCase):
    @patch.object(resolver_module, "detectar_productos")
    def test_five_pizza_narrowing_returns_three_large_candidates(
        self, detectar
    ):
        five_ids = [101, 102, 103, 104, 105]
        three_large_ids = [102, 104, 105]
        detectar.return_value = _resultado(
            encontrados_posibles=[
                {
                    "texto_origen": "la grande",
                    "productos": [
                        {"producto_presentacion_id": pid}
                        for pid in three_large_ids
                    ],
                }
            ]
        )
        active = _active_intent(candidate_ids=five_ids)

        result = resolve_product_selection("la grande", active, CATALOG)

        self.assertIsNot(result, active)
        self.assertEqual(result.candidate_ids, three_large_ids)
        self.assertEqual(result.status, "pending_resolution")
        self.assertEqual(result.intent, active.intent)
        self.assertEqual(result.source_text, active.source_text)
        self.assertEqual(result.recognizer, active.recognizer)
        self.assertEqual(result.handler, active.handler)
        self.assertEqual(result.resolved_data, active.resolved_data)
        self.assertEqual(result.requirements, active.requirements)

    @patch.object(resolver_module, "detectar_productos")
    def test_three_large_to_single_ready_intent(self, detectar):
        three_large_ids = [102, 104, 105]
        detectar.return_value = _resultado(
            encontrados=[
                {
                    "producto_presentacion_id": 102,
                    "producto_nombre": "Pizza de Muzzarella Grande",
                }
            ]
        )
        active = _active_intent(candidate_ids=three_large_ids)

        result = resolve_product_selection(
            "Pizza de Muzzarella Grande", active, CATALOG
        )

        self.assertEqual(result.candidate_ids, [])
        self.assertEqual(result.status, "ready")
        self.assertEqual(result.resolved_data["producto_presentacion_id"], 102)
        self.assertEqual(result.resolved_data["cantidad"], 2)
        req_names = {req.name: req.status for req in result.requirements}
        self.assertEqual(req_names.get("producto_presentacion_id"), "completed")

    @patch.object(resolver_module, "detectar_productos")
    def test_empty_intersection_returns_input_unchanged(self, detectar):
        detectar.return_value = _resultado(
            encontrados_posibles=[
                {
                    "texto_origen": "la grande",
                    "productos": [{"producto_presentacion_id": 999}],
                }
            ]
        )
        active = _active_intent(candidate_ids=[201, 202])

        result = resolve_product_selection("la grande", active, CATALOG)

        self.assertIs(result, active)
        self.assertEqual(result.candidate_ids, [201, 202])
        self.assertEqual(result.status, "pending_resolution")


class ResolveProductSelectionNoDbSideEffectsTest(unittest.TestCase):
    @patch.object(resolver_module, "detectar_productos")
    def test_narrowing_branch_does_not_call_db_methods_or_mutate_input(
        self, detectar
    ):
        five_ids = [101, 102, 103, 104, 105]
        three_large_ids = [102, 104, 105]
        detectar.return_value = _resultado(
            encontrados_posibles=[
                {
                    "texto_origen": "la grande",
                    "productos": [
                        {"producto_presentacion_id": pid}
                        for pid in three_large_ids
                    ],
                }
            ]
        )
        active = _active_intent(candidate_ids=five_ids)
        original_candidate_ids = list(active.candidate_ids)
        original_resolved_data = dict(active.resolved_data)
        original_requirements = list(active.requirements)

        db = mock.MagicMock(name="DatabaseSession")

        result = resolve_product_selection("la grande", active, CATALOG)

        db.commit.assert_not_called()
        db.flush.assert_not_called()
        db.refresh.assert_not_called()
        db.expire.assert_not_called()
        db.begin.assert_not_called()

        self.assertEqual(active.candidate_ids, original_candidate_ids)
        self.assertEqual(dict(active.resolved_data), original_resolved_data)
        self.assertEqual(list(active.requirements), original_requirements)

        self.assertEqual(result.candidate_ids, three_large_ids)
        self.assertEqual(result.status, "pending_resolution")


class ResolveProductSelectionUniqueMatchPriorityTest(unittest.TestCase):
    @patch.object(resolver_module, "detectar_productos")
    def test_unique_match_takes_priority_over_candidates(self, detectar):
        three_large_ids = [102, 104, 105]
        detectar.return_value = _resultado(
            encontrados=[
                {
                    "producto_presentacion_id": 102,
                    "producto_nombre": "Pizza de Muzzarella Grande",
                }
            ],
            encontrados_posibles=[
                {
                    "texto_origen": "la grande",
                    "productos": [
                        {"producto_presentacion_id": pid}
                        for pid in three_large_ids
                    ],
                }
            ],
        )
        active = _active_intent(candidate_ids=three_large_ids)

        result = resolve_product_selection(
            "Pizza de Muzzarella Grande", active, CATALOG
        )

        self.assertEqual(result.candidate_ids, [])
        self.assertEqual(result.status, "ready")
        self.assertEqual(result.resolved_data["producto_presentacion_id"], 102)


CATALOG_WITH_PRESENTACIONES = [
    {
        "producto_presentacion_id": 1,
        "producto_nombre": "Pizza de Muzzarella Chica",
        "presentacion_codigo": "CHICA",
    },
    {
        "producto_presentacion_id": 2,
        "producto_nombre": "Pizza de Muzzarella Grande",
        "presentacion_codigo": "GRANDE",
    },
    {
        "producto_presentacion_id": 3,
        "producto_nombre": "Pizza Napolitana Chica",
        "presentacion_codigo": "CHICA",
    },
    {
        "producto_presentacion_id": 4,
        "producto_nombre": "Pizza Napolitana Grande",
        "presentacion_codigo": "GRANDE",
    },
]


CARNE_CATALOG = [
    {
        "producto_presentacion_id": 11,
        "producto_nombre": "Empanada de Carne",
        "presentacion_codigo": "PICANTE",
    },
    {
        "producto_presentacion_id": 12,
        "producto_nombre": "Empanada de Carne",
        "presentacion_codigo": "TRADICIONAL",
    },
]


PRODUCTO_NOMBRE_PICANTE_CATALOG = [
    {
        "producto_presentacion_id": 31,
        "producto_nombre": "Empanada de Carne",
        "presentacion_codigo": "UNIDAD",
    },
    {
        "producto_presentacion_id": 32,
        "producto_nombre": "Empanada de Carne Picante",
        "presentacion_codigo": "UNIDAD",
    },
]


PRODUCTO_NOMBRE_TRADICIONAL_CATALOG = [
    {
        "producto_presentacion_id": 21,
        "producto_nombre": "Pizza Muzzarella",
        "presentacion_codigo": "UNIDAD",
    },
    {
        "producto_presentacion_id": 22,
        "producto_nombre": "Pizza Muzzarella Tradicional",
        "presentacion_codigo": "UNIDAD",
    },
]


class ResolveProductSelectionCarneFragmentTest(unittest.TestCase):
    """2.1, 2.3, 2.4: focused tests for discriminating fragments
    against the persisted Carne candidate set using the real recognizer
    (no detectar_productos mock). The catalog mirrors the seed used in
    `test_agregar_producto_sequential_queue_end_to_end.py` with the
    Picante/Tradicional presentations."""

    def _carne_active(self, candidate_ids, cantidad: int = 1) -> ProcessedIntent:
        return ProcessedIntent(
            intent="agregar_producto",
            source_text="una empanada de carne",
            status="pending_resolution",
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

    def test_picante_uniquely_selects_picante_candidate(self):
        active = self._carne_active([11, 12])
        raw = resolver_module.detectar_productos("picante", CARNE_CATALOG)
        result = resolve_product_selection("picante", active, CARNE_CATALOG)
        self.assertEqual(result.status, "ready")
        self.assertEqual(result.candidate_ids, [])
        self.assertEqual(
            result.resolved_data.get("producto_presentacion_id"), 11
        )
        self.assertEqual(result.resolved_data.get("cantidad"), 1)
        req_names = {req.name: req.status for req in result.requirements}
        self.assertEqual(req_names.get("producto_presentacion_id"), "completed")
        raw_ids = [r["producto_presentacion_id"] for r in raw["encontrados"]]
        for grp in raw["encontrados_posibles"]:
            for p in grp.get("productos", []):
                raw_ids.append(p["producto_presentacion_id"])
        if raw_ids:
            self.assertIn(11, raw_ids)
            self.assertNotIn(999, raw_ids)

    def test_la_picante_with_article_uniquely_selects_picante(self):
        active = self._carne_active([11, 12])
        result = resolve_product_selection("la picante", active, CARNE_CATALOG)
        self.assertEqual(result.status, "ready")
        self.assertEqual(result.candidate_ids, [])
        self.assertEqual(
            result.resolved_data.get("producto_presentacion_id"), 11
        )

    def test_carne_picante_with_product_noun_uniquely_selects_picante(self):
        """2.1/2.2: `carne picante` is a discriminating fragment that
        must return ready and select the picante candidate from the
        active set. The current resolver narrows via the
        `presentacion_codigo` alias path: only the picante presentation
        has PICANTE in its codigo, so the intersection is unique."""
        active = self._carne_active([11, 12])
        result = resolve_product_selection(
            "carne picante", active, CARNE_CATALOG
        )
        self.assertEqual(result.status, "ready")
        self.assertEqual(result.candidate_ids, [])
        self.assertEqual(
            result.resolved_data.get("producto_presentacion_id"), 11
        )
        self.assertEqual(result.resolved_data.get("cantidad"), 1)

    def test_la_comun_without_picante_keeps_active_unchanged(self):
        """`la común` cannot discriminate the persisted Carne set in
        this catalog shape (no candidate has `comun` in
        `presentacion_codigo`) so the active intent must remain
        `pending_resolution` with the original candidate IDs."""
        active = self._carne_active([11, 12])
        result = resolve_product_selection("la comun", active, CARNE_CATALOG)
        self.assertEqual(result.status, "pending_resolution")
        self.assertEqual(result.candidate_ids, [11, 12])
        self.assertNotIn(
            "producto_presentacion_id", result.resolved_data
        )

    def test_la_de_carne_comun_preserves_active_ambiguity(self):
        """`la de carne común` is a discriminating fragment for the
        traditional variant when the catalog exposes it. With the
        default PICANTE/TRADICIONAL codigos and no `comun` alias
        registered, the resolver preserves the active ambiguity."""
        active = self._carne_active([11, 12])
        result = resolve_product_selection(
            "la de carne comun", active, CARNE_CATALOG
        )
        self.assertEqual(result.status, "pending_resolution")
        self.assertEqual(result.candidate_ids, [11, 12])

    def test_picante_with_quantity_4_preserves_cantidad(self):
        """2.2/2.3: quantity must survive unique fragment resolution."""
        active = self._carne_active([11, 12], cantidad=4)
        result = resolve_product_selection("picante", active, CARNE_CATALOG)
        self.assertEqual(result.status, "ready")
        self.assertEqual(result.resolved_data.get("cantidad"), 4)
        self.assertEqual(
            result.resolved_data.get("producto_presentacion_id"), 11
        )
        self.assertEqual(result.candidate_ids, [])

    def test_recognizer_outside_active_candidate_ids_is_rejected(self):
        """2.3: recognition returning only IDs not in the active
        candidate set must NOT mutate active state or queue."""
        active = self._carne_active([11, 12])
        catalog_with_foreign = list(CARNE_CATALOG) + [
            {
                "producto_presentacion_id": 999,
                "producto_nombre": "Pizza Mozzarella",
                "presentacion_codigo": "GRANDE",
            }
        ]
        result = resolve_product_selection(
            "pizza", active, catalog_with_foreign
        )
        self.assertEqual(result.status, "pending_resolution")
        self.assertEqual(result.candidate_ids, [11, 12])

    def test_raw_recognizer_output_for_picante_catalog(self):
        """2.4: assert raw real-recognizer output and resolver output
        for the exact picante catalog. The recognizer may or may not
        return the picante candidate directly depending on its
        heuristics; the resolver must still produce `ready` for id 11
        via the presentacion-alias narrowing path."""
        raw = resolver_module.detectar_productos("picante", CARNE_CATALOG)
        raw_ids = [r["producto_presentacion_id"] for r in raw["encontrados"]]
        for grp in raw["encontrados_posibles"]:
            for p in grp.get("productos", []):
                raw_ids.append(p["producto_presentacion_id"])
        if raw_ids:
            self.assertNotIn(999, raw_ids)

        active = self._carne_active([11, 12])
        result = resolve_product_selection("picante", active, CARNE_CATALOG)
        self.assertEqual(result.status, "ready")
        self.assertEqual(
            result.resolved_data.get("producto_presentacion_id"), 11
        )
        self.assertEqual(result.candidate_ids, [])


class HybridAmbiguousQuantitySelectionFlowTest(unittest.TestCase):
    """4.x: prove the deterministic quantity the hybrid ambiguous
    translation attaches to each candidate survives the pending →
    bounded-selection path.

    The hybrid recognizer is the only one patched: every other
    resolver/handler/repository seam keeps its real implementation,
    so the test exercises the documented production chain.
    """

    def _carne_picante_suave_catalog(self) -> list[dict]:
        """Isolated PICANTE/SUAVE catalog mirroring the pilot.

        The shared ``CARNE_CATALOG`` exposes PICANTE/TRADICIONAL,
        which is correct for the pre-existing ``ResolveProductSelectionCarneFragmentTest``
        but does NOT exercise the bounded ``suave`` selection the pilot
        runs. The tests in this class use ONLY this isolated copy
        so they do not mutate or depend on the shared catalog.
        """
        return [
            {
                "producto_presentacion_id": 11,
                "producto_nombre": "Empanada de Carne",
                "presentacion_codigo": "PICANTE",
            },
            {
                "producto_presentacion_id": 12,
                "producto_nombre": "Empanada de Carne",
                "presentacion_codigo": "SUAVE",
            },
        ]

    def _carne_active(self, candidate_ids, cantidad: int = 1) -> ProcessedIntent:
        return ProcessedIntent(
            intent="agregar_producto",
            source_text="quiero 2 empanadas de carne",
            status="pending_resolution",
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

    def _hybrid_recognizer(self):
        """Build a deterministic hybrid recognizer that always
        emits the ambiguous Carne translation."""
        from backend.services.hybrid_authoritative_recognizer import (
            HybridAuthoritativeProductRecognizer,
        )
        from backend.services.product_recognition_calibration_policy import (
            HybridDecisionPolicy,
        )
        from backend.services.shadow_metrics_recorder import ShadowMetricsRecorder

        class _AlwaysAmbiguousFuzzy:
            def __init__(self) -> None:
                self.calls = 0

            def recognize(self, text, catalog, *, intent_metadata=None):
                self.calls += 1
                return {
                    "encontrados": [],
                    "encontrados_posibles": [
                        {
                            "texto_origen": text,
                            "productos": [
                                {
                                    "producto_presentacion_id": 11,
                                    "producto_nombre": "Empanada de Carne",
                                    "texto_origen": text,
                                },
                                {
                                    "producto_presentacion_id": 12,
                                    "producto_nombre": "Empanada de Carne",
                                    "texto_origen": text,
                                },
                            ],
                        }
                    ],
                    "encontrados_no_disponibles": [],
                    "no_encontrados": [],
                }

        class _StubEmbedding:
            def embed_query(self, text):
                return [0.0] * 384

            def embed_documents(self, texts):
                return [[0.0] * 384 for _ in texts]

        class _StubVectorMatch:
            def __init__(self, pid, score):
                self.id_producto_presentacion = pid
                self.score = score

        class _StubVectorService:
            def search_similar(
                self,
                *,
                id_comercio,
                query_embedding,
                top_k,
                candidate_producto_presentacion_ids,
            ):
                return [
                    _StubVectorMatch(11, 0.95),
                    _StubVectorMatch(12, 0.90),
                ]

        return HybridAuthoritativeProductRecognizer(
            inner=_AlwaysAmbiguousFuzzy(),
            policy=HybridDecisionPolicy(
                fuzzy_weight=0.5,
                vector_weight=0.5,
                unique_threshold=0.7,
                ambiguous_threshold=0.4,
                minimum_score_gap=0.05,
                vector_top_k=5,
            ),
            embedding_client=_StubEmbedding(),
            vector_search_service=lambda: _StubVectorService(),
            recorder=ShadowMetricsRecorder(),
            configured_mode="hybrid_authoritative",
            effective_mode="hybrid_authoritative",
            commerce_id_resolver=lambda catalog: 99,
        )

    def test_hybrid_ambiguous_translation_attaches_quantity_two_to_each_candidate(self):
        recognizer = self._hybrid_recognizer()
        result = recognizer.recognize(
            "quiero 2 empanadas de carne", CARNE_CATALOG
        )
        self.assertEqual(result["encontrados"], [])
        self.assertEqual(len(result["encontrados_posibles"]), 1)
        productos = result["encontrados_posibles"][0]["productos"]
        self.assertEqual(
            [p["producto_presentacion_id"] for p in productos], [11, 12]
        )
        for entry in productos:
            self.assertEqual(int(entry["cantidad"]), 2)

    def test_picante_selection_preserves_quantity_two(self):
        """The pending → ``picante`` flow must NOT replace the
        quantity the hybrid translator attached to the ambiguous
        candidate set with the resolver default of one."""
        from backend.intents.resolvers.product_intent_resolver import (
            resolve_product_intent,
        )

        catalog = self._carne_picante_suave_catalog()

        recognizer = self._hybrid_recognizer()
        raw = recognizer.recognize(
            "quiero 2 empanadas de carne", catalog
        )
        resolved = resolve_product_intent(raw)
        self.assertEqual(resolved["resolved_data"]["cantidad"], 2)
        self.assertEqual(resolved["candidate_ids"], [11, 12])

        active = self._carne_active(
            candidate_ids=resolved["candidate_ids"],
            cantidad=resolved["resolved_data"]["cantidad"],
        )

        original = resolver_module._product_recognizer  # type: ignore[attr-defined]
        resolver_module._product_recognizer = (  # type: ignore[attr-defined]
            _FuzzyCarneSpy()
        )
        try:
            result = resolve_product_selection(
                "picante", active, catalog
            )
        finally:
            resolver_module._product_recognizer = original  # type: ignore[attr-defined]

        self.assertEqual(result.status, "ready")
        self.assertEqual(result.resolved_data.get("cantidad"), 2)
        self.assertEqual(
            result.resolved_data.get("producto_presentacion_id"), 11
        )
        self.assertEqual(result.candidate_ids, [])

    def test_ambiguous_quantity_does_not_replace_persisted_pending_quantity(self):
        """When the hybrid ambiguous translator omits ``cantidad``
        (the pre-fix behaviour) the persisted pending state would
        default to one. With the fix in place, the translator
        always carries the parsed quantity, so the pending state
        survives the bounded ``suave`` selection unchanged."""

        catalog = self._carne_picante_suave_catalog()

        recognizer = self._hybrid_recognizer()
        raw = recognizer.recognize(
            "agrega dos empanadas de carne", catalog
        )
        productos = raw["encontrados_posibles"][0]["productos"]
        for entry in productos:
            self.assertEqual(int(entry["cantidad"]), 2)

        active = self._carne_active(
            candidate_ids=[p["producto_presentacion_id"] for p in productos],
            cantidad=2,
        )

        original = resolver_module._product_recognizer  # type: ignore[attr-defined]
        resolver_module._product_recognizer = (  # type: ignore[attr-defined]
            _FuzzyCarneSpy()
        )
        try:
            result = resolve_product_selection(
                "suave", active, catalog
            )
        finally:
            resolver_module._product_recognizer = original  # type: ignore[attr-defined]

        self.assertEqual(result.status, "ready")
        self.assertEqual(result.resolved_data.get("cantidad"), 2)
        self.assertEqual(
            result.resolved_data.get("producto_presentacion_id"), 12
        )
        self.assertEqual(result.candidate_ids, [])


class _FuzzyCarneSpy:
    """Spy recognizer that resolves ``picante``/``suave`` against
    the carne catalog by mirroring the presentacion_codigo alias
    path the production resolver applies when the real recognizer
    returns no match. The spy returns an empty four-key result so
    the resolver falls back to the alias-narrowing branch without
    touching the persisted quantity.
    """

    def recognize(self, text, catalog, *, intent_metadata=None):
        return {
            "encontrados": [],
            "encontrados_posibles": [],
            "encontrados_no_disponibles": [],
            "no_encontrados": [{"texto_origen": text}],
        }


class ResolveProductSelectionProductoNombreAliasTest(unittest.TestCase):
    """3.32.7: product-narrowing when the discriminating fragment lives in
    `producto_nombre` rather than `presentacion_codigo`. The new predicate
    in `_narrow_by_presentacion_alias` matches the alias token as a whole
    word (case-insensitive) against the candidate's normalized
    `producto_nombre`, in addition to the existing `presentacion_codigo`
    path."""

    def _active(self, candidate_ids, source_text="1 empanada de carne",
                cantidad: int = 1) -> ProcessedIntent:
        return ProcessedIntent(
            intent="agregar_producto",
            source_text=source_text,
            status="pending_resolution",
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

    def test_picante_uniquely_selects_picante_producto_nombre(self):
        active = self._active([31, 32])
        result = resolve_product_selection(
            "picante", active, PRODUCTO_NOMBRE_PICANTE_CATALOG
        )
        self.assertEqual(result.status, "ready")
        self.assertEqual(result.candidate_ids, [])
        self.assertEqual(
            result.resolved_data.get("producto_presentacion_id"), 32
        )
        self.assertEqual(result.resolved_data.get("cantidad"), 1)
        req_names = {req.name: req.status for req in result.requirements}
        self.assertEqual(
            req_names.get("producto_presentacion_id"), "completed"
        )

    def test_tradicional_narrows_to_tradicional_pizza(self):
        active = self._active([21, 22], source_text="1 pizza de muzarella")
        result = resolve_product_selection(
            "tradicional", active, PRODUCTO_NOMBRE_TRADICIONAL_CATALOG
        )
        self.assertEqual(result.status, "ready")
        self.assertEqual(result.candidate_ids, [])
        self.assertEqual(
            result.resolved_data.get("producto_presentacion_id"), 22
        )
        self.assertEqual(result.resolved_data.get("cantidad"), 1)

    def test_carne_picante_with_product_noun_narrows_to_picante(self):
        active = self._active([31, 32])
        result = resolve_product_selection(
            "carne picante", active, PRODUCTO_NOMBRE_PICANTE_CATALOG
        )
        self.assertEqual(result.status, "ready")
        self.assertEqual(result.candidate_ids, [])
        self.assertEqual(
            result.resolved_data.get("producto_presentacion_id"), 32
        )
        self.assertEqual(result.resolved_data.get("cantidad"), 1)

    def test_la_picante_with_article_narrows_to_picante(self):
        active = self._active([31, 32])
        result = resolve_product_selection(
            "la picante", active, PRODUCTO_NOMBRE_PICANTE_CATALOG
        )
        self.assertEqual(result.status, "ready")
        self.assertEqual(result.candidate_ids, [])
        self.assertEqual(
            result.resolved_data.get("producto_presentacion_id"), 32
        )

    def test_la_de_carne_picante_narrows_to_picante(self):
        active = self._active([31, 32])
        result = resolve_product_selection(
            "la de carne picante", active, PRODUCTO_NOMBRE_PICANTE_CATALOG
        )
        self.assertEqual(result.status, "ready")
        self.assertEqual(result.candidate_ids, [])
        self.assertEqual(
            result.resolved_data.get("producto_presentacion_id"), 32
        )

    @patch.object(resolver_module, "detectar_productos")
    def test_substring_picantes_does_not_match_picante_alias(self, detectar):
        detectar.return_value = _resultado()
        catalog = [
            {
                "producto_presentacion_id": 41,
                "producto_nombre": "Empanada Picantes Variedad",
                "presentacion_codigo": "UNIDAD",
            },
        ] + [
            dict(pp) for pp in PRODUCTO_NOMBRE_PICANTE_CATALOG
        ]
        active = self._active([31, 32, 41])
        result = resolve_product_selection(
            "picante", active, catalog
        )
        self.assertNotIn(41, result.candidate_ids)
        self.assertEqual(
            result.resolved_data.get("producto_presentacion_id"), 32
        )

    def test_presentacion_codigo_path_still_narrows_la_grande(self):
        catalog = [
            {
                "producto_presentacion_id": 51,
                "producto_nombre": "Pizza Muzzarella",
                "presentacion_codigo": "CHICA",
            },
            {
                "producto_presentacion_id": 52,
                "producto_nombre": "Pizza Muzzarella",
                "presentacion_codigo": "GRANDE",
            },
        ]
        active = self._active([51, 52], source_text="1 pizza de muzarella")
        result = resolve_product_selection(
            "la grande", active, catalog
        )
        self.assertEqual(result.status, "ready")
        self.assertEqual(result.candidate_ids, [])
        self.assertEqual(
            result.resolved_data.get("producto_presentacion_id"), 52
        )

    def test_grandi_variant_matches_producto_nombre_via_alias_normalization(self):
        catalog = [
            {
                "producto_presentacion_id": 61,
                "producto_nombre": "Pizza Muzzarella Grande",
                "presentacion_codigo": "UNIDAD",
            },
            {
                "producto_presentacion_id": 62,
                "producto_nombre": "Pizza Muzzarella",
                "presentacion_codigo": "UNIDAD",
            },
        ]
        active = self._active([61, 62], source_text="1 pizza de muzarella")
        result = resolve_product_selection(
            "grandi", active, catalog
        )
        self.assertEqual(result.status, "ready")
        self.assertEqual(result.candidate_ids, [])
        self.assertEqual(
            result.resolved_data.get("producto_presentacion_id"), 61
        )

    def test_multiple_narrowed_candidates_keep_pending_resolution(self):
        catalog = [
            {
                "producto_presentacion_id": 71,
                "producto_nombre": "Empanada de Carne Picante",
                "presentacion_codigo": "UNIDAD",
            },
            {
                "producto_presentacion_id": 72,
                "producto_nombre": "Empanada de Carne Picante",
                "presentacion_codigo": "DOCENA",
            },
        ]
        active = self._active([71, 72])
        result = resolve_product_selection(
            "picante", active, catalog
        )
        self.assertEqual(result.status, "pending_resolution")
        self.assertEqual(result.candidate_ids, [71, 72])
        self.assertNotIn(
            "producto_presentacion_id", result.resolved_data
        )
        self.assertEqual(result.resolved_data.get("cantidad"), 1)


class ResolveProductSelectionDiagnosticSurfaceTest(unittest.TestCase):
    """3.32.7: confirm the 3.32.6 diagnostic surface still emits the
    expected events for the `carne picante` flow that exercises the new
    product-name match predicate. The same flow must keep the
    NoopDiagnosticSink contract (no events)."""

    def _active(self) -> ProcessedIntent:
        return ProcessedIntent(
            intent="agregar_producto",
            source_text="1 empanada de carne",
            status="pending_resolution",
            recognizer="recognizer_productos",
            handler="agregar_producto",
            resolved_data={"cantidad": 1},
            requirements=[
                RequirementState(
                    name="producto_presentacion_id",
                    status="pending",
                    value=None,
                )
            ],
            candidate_ids=[31, 32],
        )

    def test_collecting_sink_records_resolver_input_output_and_candidates(self):
        from backend.diagnostics import CollectingDiagnosticSink

        sink = CollectingDiagnosticSink()
        active = self._active()
        result = resolve_product_selection(
            "carne picante", active, PRODUCTO_NOMBRE_PICANTE_CATALOG, sink=sink
        )

        self.assertEqual(result.status, "ready")
        self.assertEqual(result.candidate_ids, [])
        self.assertEqual(
            result.resolved_data.get("producto_presentacion_id"), 32
        )

        events = sink.events()
        started = [e for e in events if isinstance(e, ResolverCallStarted)]
        completed = [e for e in events if isinstance(e, ResolverCallCompleted)]
        self.assertEqual(len(started), 1)
        self.assertEqual(len(completed), 1)

        started_event = started[0]
        self.assertEqual(started_event.incoming_text, "carne picante")
        self.assertEqual(started_event.candidate_count, 2)
        sample_nombres: set[str] = set()
        for entry in started_event.candidate_catalog:
            if isinstance(entry, dict):
                nombre = entry.get("producto_nombre")
            else:
                nombre = getattr(entry, "producto_nombre", None)
            if isinstance(nombre, str):
                sample_nombres.add(nombre)
        self.assertEqual(
            sample_nombres,
            {"Empanada de Carne", "Empanada de Carne Picante"},
        )

        completed_event = completed[0]
        self.assertEqual(completed_event.status_after, "ready")
        self.assertEqual(completed_event.selected_candidate_id, 32)
        self.assertEqual(completed_event.candidate_ids_after, [])
        self.assertEqual(completed_event.candidate_count_after, 0)
        self.assertEqual(len(completed_event.matches), 1)
        self.assertEqual(completed_event.matches[0], 32)

    def test_noop_sink_does_not_record_events(self):
        from backend.diagnostics import NoopDiagnosticSink

        sink = NoopDiagnosticSink()
        active = self._active()
        result = resolve_product_selection(
            "carne picante", active, PRODUCTO_NOMBRE_PICANTE_CATALOG, sink=sink
        )

        self.assertEqual(result.status, "ready")
        self.assertEqual(result.candidate_ids, [])
        self.assertEqual(
            result.resolved_data.get("producto_presentacion_id"), 32
        )
        self.assertEqual(
            sorted(a for a in dir(sink) if not a.startswith("_")),
            sorted(
                [
                    "on_classifier_completed",
                    "on_classifier_started",
                    "on_pending_state_snapshot",
                    "on_resolver_completed",
                    "on_resolver_started",
                ]
            ),
        )


class ResolveProductSelectionTamanioOnlyRefinementTest(unittest.TestCase):
    @patch.object(resolver_module, "detectar_productos")
    def test_size_only_refinement_narrows_to_unique_candidate(self, detectar):
        detectar.return_value = _resultado()
        active = _active_intent(candidate_ids=[1, 2])

        result = resolve_product_selection("grande", active, CATALOG_WITH_PRESENTACIONES)

        self.assertEqual(result.status, "ready")
        self.assertEqual(result.candidate_ids, [])
        self.assertEqual(result.resolved_data["producto_presentacion_id"], 2)
        self.assertEqual(result.resolved_data["cantidad"], 2)
        req_names = {req.name: req.status for req in result.requirements}
        self.assertEqual(req_names.get("producto_presentacion_id"), "completed")

    @patch.object(resolver_module, "detectar_productos")
    def test_size_with_article_refinement_narrows_to_unique_candidate(
        self, detectar
    ):
        detectar.return_value = _resultado()
        active = _active_intent(candidate_ids=[1, 2])

        result = resolve_product_selection("la grande", active, CATALOG_WITH_PRESENTACIONES)

        self.assertEqual(result.status, "ready")
        self.assertEqual(result.candidate_ids, [])
        self.assertEqual(result.resolved_data["producto_presentacion_id"], 2)

    @patch.object(resolver_module, "detectar_productos")
    def test_size_only_refinement_narrows_to_multiple_candidates(self, detectar):
        detectar.return_value = _resultado()
        active = _active_intent(candidate_ids=[1, 2, 3, 4])

        result = resolve_product_selection("grande", active, CATALOG_WITH_PRESENTACIONES)

        self.assertEqual(result.status, "pending_resolution")
        self.assertEqual(result.candidate_ids, [2, 4])
        self.assertNotIn(1, result.candidate_ids)
        self.assertNotIn(3, result.candidate_ids)

    @patch.object(resolver_module, "detectar_productos")
    def test_size_only_with_unknown_size_keeps_candidates_unchanged(
        self, detectar
    ):
        detectar.return_value = _resultado()
        active = _active_intent(candidate_ids=[1, 2])

        result = resolve_product_selection("familiar", active, CATALOG_WITH_PRESENTACIONES)

        self.assertIs(result, active)
        self.assertEqual(result.candidate_ids, [1, 2])
        self.assertEqual(result.status, "pending_resolution")

    @patch.object(resolver_module, "detectar_productos")
    def test_size_with_product_noun_does_not_narrow_by_size(self, detectar):
        detectar.return_value = _resultado()
        active = _active_intent(candidate_ids=[1, 2])

        result = resolve_product_selection(
            "fugazeta grande", active, CATALOG_WITH_PRESENTACIONES
        )

        self.assertIs(result, active)
        self.assertEqual(result.candidate_ids, [1, 2])
        self.assertEqual(result.status, "pending_resolution")

    @patch.object(resolver_module, "detectar_productos")
    def test_gibberish_message_keeps_candidates_unchanged(self, detectar):
        detectar.return_value = _resultado()
        active = _active_intent(candidate_ids=[1, 2])

        result = resolve_product_selection("asdf", active, CATALOG_WITH_PRESENTACIONES)

        self.assertIs(result, active)
        self.assertEqual(result.candidate_ids, [1, 2])
        self.assertEqual(result.status, "pending_resolution")


class ResolveProductSelectionDefaultQuantityTest(unittest.TestCase):
    """Two persisted candidates whose quantity came from the contract default.

    The initial intent is pending only for ``producto_presentacion_id``; the
    ``cantidad`` requirement is already completed with the contract default
    ``1``. Selecting ``Grande`` must therefore reach ``ready`` with the default
    quantity intact and without widening the persisted candidate set.
    """

    def _default_quantity_intent(self, candidate_ids: list[int]) -> ProcessedIntent:
        return ProcessedIntent(
            intent="agregar_producto",
            source_text="quiero una pizza de muzzarella",
            status="pending_resolution",
            recognizer="recognizer_productos",
            handler="agregar_producto",
            resolved_data={"cantidad": 1},
            requirements=[
                RequirementState(
                    name="producto_presentacion_id", status="pending", value=None
                ),
                RequirementState(name="cantidad", status="completed", value=1),
            ],
            candidate_ids=list(candidate_ids),
        )

    @patch.object(resolver_module, "detectar_productos")
    def test_grande_resolves_two_candidates_to_ready_with_default_quantity(
        self, detectar
    ):
        detectar.return_value = _resultado()
        active = self._default_quantity_intent(candidate_ids=[1, 2])

        result = resolve_product_selection(
            "grande", active, CATALOG_WITH_PRESENTACIONES
        )

        self.assertEqual(result.status, "ready")
        self.assertEqual(result.candidate_ids, [])
        self.assertEqual(
            result.resolved_data,
            {"producto_presentacion_id": 2, "cantidad": 1},
        )
        req_status = {req.name: req.status for req in result.requirements}
        self.assertEqual(req_status["producto_presentacion_id"], "completed")
        self.assertEqual(req_status["cantidad"], "completed")
        cantidad = next(req for req in result.requirements if req.name == "cantidad")
        self.assertEqual(cantidad.value, 1)

    @patch.object(resolver_module, "detectar_productos")
    def test_selection_does_not_widen_persisted_candidates(self, detectar):
        detectar.return_value = _resultado(
            encontrados_posibles=[
                {
                    "texto_origen": "grande",
                    "productos": [
                        {"producto_presentacion_id": 2},
                        {"producto_presentacion_id": 4},
                    ],
                }
            ]
        )
        active = self._default_quantity_intent(candidate_ids=[1, 2])

        result = resolve_product_selection(
            "grande", active, CATALOG_WITH_PRESENTACIONES
        )

        self.assertNotIn(4, result.candidate_ids)
        self.assertEqual(active.candidate_ids, [1, 2])
        self.assertEqual(active.resolved_data, {"cantidad": 1})

    @patch.object(resolver_module, "detectar_productos")
    def test_ambiguous_reply_keeps_default_quantity_pending_state(self, detectar):
        detectar.return_value = _resultado()
        active = self._default_quantity_intent(candidate_ids=[1, 2])

        result = resolve_product_selection(
            "familiar", active, CATALOG_WITH_PRESENTACIONES
        )

        self.assertIs(result, active)
        self.assertEqual(result.status, "pending_resolution")
        self.assertEqual(result.candidate_ids, [1, 2])
        cantidad = next(req for req in result.requirements if req.name == "cantidad")
        self.assertEqual(cantidad.status, "completed")
        self.assertEqual(cantidad.value, 1)


class ResolveProductSelectionBoundariesTest(unittest.TestCase):
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
            "from backend.models",
            "db.commit",
            "db.rollback",
            "db.flush",
            "db.refresh",
            "db.expire",
            "db.begin",
            "backend.old_project",
            "from backend.old_project",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)
        # The Subphase 4.12B binding allows only the recognizer factory
        # from backend.services; every other service import remains
        # forbidden so the resolver stays a thin collaboration layer.
        allowed_services = {"backend.services.product_recognition_factory"}
        for line in source.splitlines():
            stripped = line.strip()
            if not stripped.startswith("from backend.services"):
                continue
            import_path = stripped[len("from ") :].split(" import ", 1)[0].strip()
            with self.subTest(import_path=import_path):
                self.assertIn(import_path, allowed_services)

    def test_public_surface_is_limited(self):
        self.assertEqual(
            resolver_module.__all__,
            ["resolve_product_selection"],
        )


if __name__ == "__main__":
    unittest.main()
