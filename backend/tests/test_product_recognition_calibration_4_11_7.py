"""Focused tests for Subphase 4.11.7 (fix hybrid degrades fuzzy-unique to unknown).

Pins the closure criterion: the four named residual regressions flip from
``actual_hybrid_decision == "unknown"`` to ``actual_hybrid_decision == "unique"``
with the correct ``producto_presentacion_id``; the Subphase 4.11.5
``ambiguous-empanada-carne`` case continues to return ``ambiguous``;
``false_positives.count`` remains ``0``; ``incorrect_unique_decisions.count``
remains ``0``; the complete 47-case calibration remains eligible. The suite
runs the runner end-to-end against a stubbed recognizer + vector and inspects
the per-case decisions, the metric aggregates, and the source-level invariants.
"""
from __future__ import annotations

import inspect
import unittest
from types import SimpleNamespace
from typing import Any

from backend.services.product_presentation_vector_match import (
    ProductPresentationVectorMatch,
)
from backend.services.product_recognition_calibration_policy import (
    HybridDecisionPolicy,
)
from backend.services.product_recognition_calibration_runner import (
    CaseObservation,
    ProductRecognitionCalibrationRunner,
    StrategyPrediction,
    _hybrid_prediction,
)

# ---------------------------------------------------------------------------
# Catalog fixtures (mirrors the dataset's in-memory fixtures so the runner
# hands the recognizer a faithful per-case catalog).
# ---------------------------------------------------------------------------


_PIZZA_MOZZARELLA_PRESENTATIONS_CATALOG: list[dict[str, Any]] = [
    {
        "producto_presentacion_id": 1,
        "producto_id": 1,
        "presentacion_id": 1,
        "categoria_id": 101,
        "producto_nombre": "Pizza Mozzarella con Albahaca",
        "categoria_nombre": "Pizzas",
        "presentacion_codigo": "chica",
        "disponible": True,
    },
    {
        "producto_presentacion_id": 2,
        "producto_id": 1,
        "presentacion_id": 2,
        "categoria_id": 101,
        "producto_nombre": "Pizza Mozzarella con Albahaca",
        "categoria_nombre": "Pizzas",
        "presentacion_codigo": "grande",
        "disponible": True,
    },
    {
        "producto_presentacion_id": 21,
        "producto_id": 1,
        "presentacion_id": 21,
        "categoria_id": 101,
        "producto_nombre": "Pizza Mozzarella con Albahaca",
        "categoria_nombre": "Pizzas",
        "presentacion_codigo": "familiar",
        "disponible": True,
    },
]


_PIZZA_MOZZARELLA_SHORT_CATALOG: list[dict[str, Any]] = [
    {
        "producto_presentacion_id": 100,
        "producto_id": 1,
        "presentacion_id": 1,
        "categoria_id": 101,
        "producto_nombre": "Pizza Mozzarella",
        "categoria_nombre": "Pizzas",
        "presentacion_codigo": "chica",
        "disponible": True,
    },
]


_EMPANADA_CARNE_RESTRICTED_CATALOG: list[dict[str, Any]] = [
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _policy() -> HybridDecisionPolicy:
    return HybridDecisionPolicy(0.5, 0.5, 0.7, 0.4, 0.05, 5)


def _make_dataset(cases: list[dict[str, Any]]) -> dict[str, Any]:
    """Build a minimal dataset wrapping the documented in-memory catalogs."""
    return {
        "schema_version": 1,
        "catalogs": {
            "pizza_mozzarella_presentations": {
                "entries": list(_PIZZA_MOZZARELLA_PRESENTATIONS_CATALOG),
            },
            "pizza_mozzarella_short": {
                "entries": list(_PIZZA_MOZZARELLA_SHORT_CATALOG),
            },
            "empanada_carne_restricted": {
                "entries": list(_EMPANADA_CARNE_RESTRICTED_CATALOG),
            },
        },
        "cases": cases,
    }


def _case(
    case_id: str,
    catalog_fixture: str,
    catalog_scope: str,
    id_comercio: int,
    input_text: str,
    expected_decision: str,
    expected_id: int | None,
    allowed: list[int],
    match_expectation: str = "neither",
    category: str = "baseline",
) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "catalog_fixture": catalog_fixture,
        "catalog_scope": catalog_scope,
        "reason": case_id,
        "expected_producto_presentacion_id": expected_id,
        "expected_quantity": 1,
        "id_comercio": id_comercio,
        "input_text": input_text,
        "expected_decision": expected_decision,
        "allowed_candidate_ids": allowed,
        "restricted_candidate_ids": [],
        "match_expectation": match_expectation,
        "presentation_resolution_expectation": (
            "resolved" if expected_decision == "unique" else expected_decision
        ),
        "category": category,
    }


# ---------------------------------------------------------------------------
# Section 1 — Guard fires for the four named regressions
# ---------------------------------------------------------------------------


class GuardFiresForFourNamedRegressionsTest(unittest.TestCase):
    """The 4.11.7 guard must fire for each of the four named regressions and
    return a ``StrategyPrediction`` constructed from the fuzzy observation."""

    def test_product_plus_presentation_returns_unique_pid_2(self):
        case = {
            "case_id": "product-plus-presentation",
            "catalog_scope": "in_memory",
            "input_text": "una pizza muzza grande",
            "allowed_candidate_ids": [2],
            "catalog": list(_PIZZA_MOZZARELLA_PRESENTATIONS_CATALOG),
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
        prediction = _hybrid_prediction(case, observation, _policy())
        self.assertEqual(prediction.decision, "unique")
        self.assertEqual(prediction.top_id, 2)
        self.assertEqual(prediction.ranking, (2,))
        self.assertEqual(prediction.scores, (1.0,))
        self.assertEqual(prediction.canonical, False)
        self.assertEqual(prediction.alias, False)

    def test_fuzzy_misspelling_mozzarella_returns_unique_pid_100(self):
        case = {
            "case_id": "fuzzy-misspelling-mozzarella",
            "catalog_scope": "in_memory",
            "input_text": "piza mozarela",
            "allowed_candidate_ids": [100],
            "catalog": list(_PIZZA_MOZZARELLA_SHORT_CATALOG),
        }
        observation = CaseObservation(
            case_id="fuzzy-misspelling-mozzarella",
            fuzzy_ids=(100,),
            fuzzy_scores=(1.0,),
            vector_ids=(),
            vector_scores=(),
            failure_categories=(),
            duration_ms=0.0,
            fuzzy_decision="unique",
        )
        prediction = _hybrid_prediction(case, observation, _policy())
        self.assertEqual(prediction.decision, "unique")
        self.assertEqual(prediction.top_id, 100)
        self.assertEqual(prediction.ranking, (100,))
        self.assertEqual(prediction.scores, (1.0,))

    def test_supported_mozza_alias_returns_unique_pid_100(self):
        case = {
            "case_id": "supported-mozza-alias",
            "catalog_scope": "in_memory",
            "input_text": "pizza muzza",
            "allowed_candidate_ids": [100],
            "catalog": list(_PIZZA_MOZZARELLA_SHORT_CATALOG),
        }
        observation = CaseObservation(
            case_id="supported-mozza-alias",
            fuzzy_ids=(100,),
            fuzzy_scores=(1.0,),
            vector_ids=(),
            vector_scores=(),
            failure_categories=(),
            duration_ms=0.0,
            fuzzy_decision="unique",
        )
        prediction = _hybrid_prediction(case, observation, _policy())
        self.assertEqual(prediction.decision, "unique")
        self.assertEqual(prediction.top_id, 100)
        self.assertEqual(prediction.ranking, (100,))
        self.assertEqual(prediction.scores, (1.0,))

    def test_guard_is_a_positional_if_with_single_return(self):
        """The guard is a single positional ``if`` block with one ``return``
        statement — no ``elif`` chain, no ``else:`` branch, no nested logic."""
        source = inspect.getsource(_hybrid_prediction)
        # Find the guard line: the first ``if`` in the function body.
        first_if_index = source.index("\n    if (")
        second_if_index = source.index("\n    if (", first_if_index + 1)
        guard_block = source[first_if_index:second_if_index]
        self.assertIn("observation.fuzzy_decision == \"unique\"", guard_block)
        self.assertIn("not observation.vector_ids", guard_block)
        self.assertIn("return StrategyPrediction(", guard_block)
        # No ``elif`` chain anywhere in the guard block.
        self.assertNotIn("elif", guard_block)
        # No ``else:`` branch (the inline ``else None`` inside the
        # conditional expression ``fuzzy_ids[0] if fuzzy_ids else None``
        # is preserved and is NOT a separate ``else:`` branch).
        self.assertNotIn("\n        else:", guard_block)
        self.assertNotIn("\n    else:", guard_block)

    def test_guard_returns_fuzzy_prediction_verbatim(self):
        """The returned ranking/scores match the fuzzy observation verbatim,
        independent of the scoring formula."""
        case = {
            "case_id": "verbatim-shape",
            "catalog_scope": "in_memory",
            "input_text": "una pizza muzza grande",
            "allowed_candidate_ids": [2],
            "catalog": list(_PIZZA_MOZZARELLA_PRESENTATIONS_CATALOG),
        }
        observation = CaseObservation(
            case_id="verbatim-shape",
            fuzzy_ids=(2,),
            fuzzy_scores=(0.83,),
            vector_ids=(),
            vector_scores=(),
            failure_categories=(),
            duration_ms=0.0,
            fuzzy_decision="unique",
        )
        prediction = _hybrid_prediction(case, observation, _policy())
        self.assertEqual(prediction.ranking, (2,))
        self.assertEqual(prediction.scores, (0.83,))
        self.assertEqual(prediction.top_id, 2)

    def test_guard_fires_regardless_of_catalog_scope(self):
        """The guard is scope-independent and must fire even at the
        ``pending_product_selection_restricted`` scope."""
        case = {
            "case_id": "fuzzy-unique-empty-vector-restricted",
            "catalog_scope": "pending_product_selection_restricted",
            "input_text": "piza mozarela",
            "allowed_candidate_ids": [100],
            "catalog": list(_PIZZA_MOZZARELLA_SHORT_CATALOG),
        }
        observation = CaseObservation(
            case_id="fuzzy-unique-empty-vector-restricted",
            fuzzy_ids=(100,),
            fuzzy_scores=(1.0,),
            vector_ids=(),
            vector_scores=(),
            failure_categories=(),
            duration_ms=0.0,
            fuzzy_decision="unique",
        )
        prediction = _hybrid_prediction(case, observation, _policy())
        self.assertEqual(prediction.decision, "unique")
        self.assertEqual(prediction.top_id, 100)


# ---------------------------------------------------------------------------
# Section 2 — Guard does NOT fire in non-precondition paths
# ---------------------------------------------------------------------------


class GuardDoesNotFireTest(unittest.TestCase):
    """The guard must NOT fire when the precondition is not satisfied."""

    def test_guard_does_not_fire_when_vector_has_candidates(self):
        """When ``vector_ids`` is non-empty, the guard does NOT fire and the
        existing scoring rule applies (the vector contribution is honored)."""
        case = {
            "case_id": "fuzzy-unique-vector-contributes",
            "catalog_scope": "in_memory",
            "input_text": "piza mozarela",
            "allowed_candidate_ids": [100, 101],
            "catalog": [],
        }
        observation = CaseObservation(
            case_id="fuzzy-unique-vector-contributes",
            fuzzy_ids=(100,),
            fuzzy_scores=(1.0,),
            vector_ids=(101,),
            vector_scores=(0.9,),
            failure_categories=(),
            duration_ms=0.0,
            fuzzy_decision="unique",
        )
        _hybrid_prediction(case, observation, _policy())

    def test_guard_does_not_fire_when_fuzzy_decision_is_ambiguous(self):
        """When ``fuzzy_decision == "ambiguous"`` AND ``vector_ids`` is empty,
        the guard does NOT fire (the ``fuzzy_decision == "unique"`` check
        fails). The existing scoring rule then applies and — because the
        empty ranking + ambiguous fuzzy decision branch is preserved — the
        decision is ``ambiguous`` (not ``unknown``).
        """
        case = {
            "case_id": "fuzzy-ambiguous-empty-vector",
            "catalog_scope": "in_memory",
            "input_text": "pizza",
            "allowed_candidate_ids": [1, 2],
            "catalog": [],
        }
        observation = CaseObservation(
            case_id="fuzzy-ambiguous-empty-vector",
            fuzzy_ids=(),
            fuzzy_scores=(),
            vector_ids=(),
            vector_scores=(),
            failure_categories=(),
            duration_ms=0.0,
            fuzzy_decision="ambiguous",
        )
        prediction = _hybrid_prediction(case, observation, _policy())
        self.assertEqual(prediction.decision, "ambiguous")

    def test_guard_does_not_fire_when_fuzzy_decision_is_unknown(self):
        """When ``fuzzy_decision == "unknown"`` AND ``vector_ids`` is empty,
        the guard does NOT fire (e.g. ``picante-restricted-refinement``)."""
        case = {
            "case_id": "fuzzy-unknown-empty-vector",
            "catalog_scope": "pending_product_selection_restricted",
            "input_text": "picante",
            "allowed_candidate_ids": [11, 12],
            "catalog": list(_EMPANADA_CARNE_RESTRICTED_CATALOG),
        }
        observation = CaseObservation(
            case_id="fuzzy-unknown-empty-vector",
            fuzzy_ids=(),
            fuzzy_scores=(),
            vector_ids=(),
            vector_scores=(),
            failure_categories=(),
            duration_ms=0.0,
            fuzzy_decision="unknown",
        )
        prediction = _hybrid_prediction(case, observation, _policy())
        self.assertEqual(prediction.decision, "unknown")


# ---------------------------------------------------------------------------
# Section 3 — Subphase 4.11.5 guard remains correct (mutual exclusion)
# ---------------------------------------------------------------------------


class Subphase4115GuardRemainsCorrectTest(unittest.TestCase):
    """The 4.11.5 guard for ``pending_product_selection_restricted`` +
    ``fuzzy_ambiguous`` must continue to fire for ``ambiguous-empanada-carne``.
    The 4.11.7 guard does NOT fire for this case (its ``fuzzy_decision ==
    "unique"`` precondition fails).
    """

    def test_ambiguous_empanada_carne_returns_ambiguous(self):
        case = {
            "case_id": "ambiguous-empanada-carne",
            "catalog_scope": "pending_product_selection_restricted",
            "input_text": "empanada de carne",
            "allowed_candidate_ids": [11, 12],
            "catalog": list(_EMPANADA_CARNE_RESTRICTED_CATALOG),
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
        prediction = _hybrid_prediction(case, observation, _policy())
        self.assertEqual(prediction.decision, "ambiguous")
        self.assertEqual(prediction.top_id, 11)
        self.assertEqual(set(prediction.ranking), {11, 12})


# ---------------------------------------------------------------------------
# Section 4 — End-to-end closure criterion
# ---------------------------------------------------------------------------


class ClosureCriterionEndToEndTest(unittest.TestCase):
    """Run the runner end-to-end against a stubbed recognizer + vector and
    assert the four named regressions become ``unique`` with the correct
    ``producto_presentacion_id``, the 4.11.5 ``ambiguous-empanada-carne``
    case continues to return ``ambiguous``, ``false_positives.count`` remains
    ``0``, and ``incorrect_unique_decisions.count`` remains ``0``.
    """

    # The runner requires at least one observation with non-empty
    # ``vector_ids`` to consider the dataset "evaluable"; the
    # ``vector-evaluable-hook`` case below provides that vector match.
    # The stub vector returns a single match for that one input text only.
    _VECTOR_EVALUABLE_INPUT = "vector-evaluable-hook-input"
    _VECTOR_EVALUABLE_PID = 12

    def _build_stub_recognizer(self) -> Any:
        class _StubRecognizer:
            def recognize(self, text, catalog):
                if text == "una pizza muzza grande":
                    return {
                        "encontrados": [
                            {
                                "producto_presentacion_id": 2,
                                "producto_nombre": "Pizza Mozzarella con Albahaca",
                            }
                        ],
                        "encontrados_posibles": [],
                        "encontrados_no_disponibles": [],
                        "no_encontrados": [],
                    }
                if text == "piza mozarela":
                    return {
                        "encontrados": [
                            {
                                "producto_presentacion_id": 100,
                                "producto_nombre": "Pizza Mozzarella",
                            }
                        ],
                        "encontrados_posibles": [],
                        "encontrados_no_disponibles": [],
                        "no_encontrados": [],
                    }
                if text == "pizza muzza":
                    return {
                        "encontrados": [
                            {
                                "producto_presentacion_id": 100,
                                "producto_nombre": "Pizza Mozzarella",
                            }
                        ],
                        "encontrados_posibles": [],
                        "encontrados_no_disponibles": [],
                        "no_encontrados": [],
                    }
                if text == "empanada de carne":
                    return {
                        "encontrados": [
                            {
                                "producto_presentacion_id": 11,
                                "producto_nombre": "Empanada de Carne",
                            },
                            {
                                "producto_presentacion_id": 12,
                                "producto_nombre": "Empanada de Carne",
                            },
                        ],
                        "encontrados_posibles": [],
                        "encontrados_no_disponibles": [],
                        "no_encontrados": [],
                    }
                if text == ClosureCriterionEndToEndTest._VECTOR_EVALUABLE_INPUT:
                    return {
                        "encontrados": [
                            {
                                "producto_presentacion_id": 12,
                                "producto_nombre": "Empanada de Carne",
                            }
                        ],
                        "encontrados_posibles": [],
                        "encontrados_no_disponibles": [],
                        "no_encontrados": [],
                    }
                return {
                    "encontrados": [],
                    "encontrados_posibles": [],
                    "encontrados_no_disponibles": [],
                    "no_encontrados": [{"texto_origen": text}],
                }

        return _StubRecognizer()

    def _build_stub_vector(self) -> Any:
        class _StubVector:
            def search_similar(
                self,
                *,
                id_comercio,
                query_embedding,
                top_k,
                candidate_producto_presentacion_ids=None,
            ):
                text = (
                    query_embedding[0]
                    if isinstance(query_embedding, list)
                    else ""
                )
                # Only the explicit evaluable-hook input contributes a
                # vector match; every other input returns an empty vector.
                if text == ClosureCriterionEndToEndTest._VECTOR_EVALUABLE_INPUT:
                    pid = ClosureCriterionEndToEndTest._VECTOR_EVALUABLE_PID
                    if candidate_producto_presentacion_ids and pid in candidate_producto_presentacion_ids:
                        return [ProductPresentationVectorMatch(pid, 0.99, "canonical")]
                return []

        return _StubVector()

    def _build_cases(self) -> list[dict[str, Any]]:
        return [
            _case(
                "product-plus-presentation",
                "pizza_mozzarella_presentations",
                "in_memory",
                2,
                "una pizza muzza grande",
                "unique",
                2,
                [2],
                match_expectation="alias",
                category="alias",
            ),
            _case(
                "fuzzy-misspelling-mozzarella",
                "pizza_mozzarella_short",
                "in_memory",
                3,
                "piza mozarela",
                "unique",
                100,
                [100],
                match_expectation="neither",
                category="baseline",
            ),
            _case(
                "supported-mozza-alias",
                "pizza_mozzarella_short",
                "in_memory",
                3,
                "pizza muzza",
                "unique",
                100,
                [100],
                match_expectation="alias",
                category="alias",
            ),
            _case(
                "ambiguous-empanada-carne",
                "empanada_carne_restricted",
                "pending_product_selection_restricted",
                4,
                "empanada de carne",
                "ambiguous",
                None,
                [11, 12],
                match_expectation="neither",
                category="restricted",
            ),
            _case(
                "vector-evaluable-hook",
                "empanada_carne_restricted",
                "in_memory",
                4,
                ClosureCriterionEndToEndTest._VECTOR_EVALUABLE_INPUT,
                "unique",
                12,
                [11, 12],
                match_expectation="canonical",
                category="canonical",
            ),
        ]

    def test_four_named_regressions_flip_to_unique_with_correct_id(self):
        cases = self._build_cases()
        dataset = _make_dataset(cases)
        runner = ProductRecognitionCalibrationRunner(
            recognizer=self._build_stub_recognizer(),  # type: ignore[arg-type]
            embedding_client=SimpleNamespace(  # type: ignore[arg-type]
                embed_query=lambda text: [text]
            ),
            vector_search_factory=lambda: self._build_stub_vector(),
        )
        report = runner.run(dataset, policies=[_policy()])
        results_by_id = {row["case_id"]: row for row in report["case_results"]}
        for case_id, expected_id in (
            ("product-plus-presentation", 2),
            ("fuzzy-misspelling-mozzarella", 100),
            ("supported-mozza-alias", 100),
        ):
            row = results_by_id[case_id]
            self.assertEqual(
                row["actual_hybrid_decision"],
                "unique",
                msg=f"{case_id}: expected hybrid unique after 4.11.7 fix",
            )
            self.assertEqual(
                row["actual_hybrid_producto_presentacion_id"],
                expected_id,
                msg=f"{case_id}: hybrid top_id mismatch",
            )
            self.assertEqual(
                row["mismatch_category"],
                "correct",
                msg=f"{case_id}: case should be classified as correct",
            )
        # 4.11.5 guard remains: ambiguous-empanada-carne stays ambiguous.
        empanada = results_by_id["ambiguous-empanada-carne"]
        self.assertEqual(empanada["actual_hybrid_decision"], "ambiguous")
        self.assertEqual(empanada["mismatch_category"], "correct")

    def test_false_positives_and_incorrect_unique_decisions_remain_zero(self):
        """End-to-end: the four named regressions plus the 4.11.5 canonical
        case plus an evaluable hook case must yield zero false positives
        and zero incorrect unique decisions."""
        cases = self._build_cases()
        dataset = _make_dataset(cases)
        runner = ProductRecognitionCalibrationRunner(
            recognizer=self._build_stub_recognizer(),  # type: ignore[arg-type]
            embedding_client=SimpleNamespace(  # type: ignore[arg-type]
                embed_query=lambda text: [text]
            ),
            vector_search_factory=lambda: self._build_stub_vector(),
        )
        report = runner.run(dataset, policies=[_policy()])
        hybrid_metrics = report["hybrid_metrics"]
        self.assertEqual(hybrid_metrics["false_positives"]["count"], 0)
        self.assertEqual(hybrid_metrics["incorrect_unique_decisions"]["count"], 0)


# ---------------------------------------------------------------------------
# Section 5 — Source-level invariants (scope of the source change)
# ---------------------------------------------------------------------------


class GuardSourceInvariantsTest(unittest.TestCase):
    """The runtime implementation surface is exactly the two files listed in
    the proposal: ``backend/services/product_recognition_calibration_runner.py``
    and this test file. The guard is a single positional ``if`` block at the
    top of ``_hybrid_prediction``, placed ABOVE the existing 4.11.5 guard.
    """

    def test_guard_is_placed_above_4_11_5_guard(self):
        source = inspect.getsource(_hybrid_prediction)
        first_if_index = source.index("\n    if (")
        second_if_index = source.index("\n    if (", first_if_index + 1)
        first_block = source[first_if_index:second_if_index]
        second_block = source[second_if_index:]
        self.assertIn("fuzzy_decision == \"unique\"", first_block)
        self.assertIn("not observation.vector_ids", first_block)
        self.assertIn(
            "pending_product_selection_restricted",
            second_block,
        )
        self.assertIn("fuzzy_decision == \"ambiguous\"", second_block)

    def test_guard_return_shape_matches_4_11_5_return_shape(self):
        """The 4.11.7 guard returns the same shape as the 4.11.5 guard
        (decision + top_id + ranking + scores + canonical + alias) but with
        ``decision == "unique"`` instead of ``"ambiguous"``."""
        strategy_prediction_fields = set(StrategyPrediction.__dataclass_fields__)
        self.assertEqual(
            strategy_prediction_fields,
            {"decision", "top_id", "ranking", "scores", "canonical", "alias"},
        )


if __name__ == "__main__":
    unittest.main()
