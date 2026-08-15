"""Focused tests for ``set_observacion_producto`` identity recovery.

The bounded identity-evidence recovery runs only after the existing
order-line fuzzy recognizer returns zero candidates. The tests cover:

- qualified ``Mozzarella Chica`` recovers only the Chica line when
  Mozzarella Grande and Mozzarella Chica are both owned;
- a second product/condition (Napolitana Chica + Napolitana Grande)
  proves the recovery is not a literal mozzarella/pizza special case;
- a reference without sufficient presentation across two compatible
  lines stays in the pending order-line selection path;
- missing identity evidence stays rejected (no catalog, foreign line,
  most-recent-line or LLM-derived fallback);
- lines from a different pedido and the commerce catalog are never
  widened into the candidate set;
- when the fuzzy recognizer already produces candidates, the recovery
  is not executed;
- the full literal message survives into the ready/executed intent;
- the recognizer never invokes transaction-control methods on the
  database session.
"""
from __future__ import annotations

import importlib
import unittest
from unittest.mock import MagicMock, patch

from sqlalchemy.orm import Session as DatabaseSession

from backend.intents.recognizers import (
    set_observacion_producto_recognizer as recognizer_module,
)
from backend.intents.recognizers.set_observacion_producto_recognizer import (
    _recover_candidates_by_identity,
    is_clear_observation_message,
    recognize_set_observacion_producto,
)
from backend.models.session import Session as ConversationSession


def _make_pp_line(
    *,
    pp_id: int,
    producto_nombre: str,
    presentacion_codigo: str,
    presentacion_descripcion: str,
    categoria_descripcion: str,
    cantidad: int = 1,
) -> MagicMock:
    """Build a ``MagicMock`` standing in for a ``PedidoProducto`` row
    with the eager-loaded fields the recovery compares against."""
    presentacion = MagicMock(
        codigo=presentacion_codigo,
        descripcion=presentacion_descripcion,
        activo=True,
    )
    categoria = MagicMock(descripcion=categoria_descripcion, activo=True)
    producto = MagicMock(
        nombre=producto_nombre,
        id_categoria_producto=1,
        activo=True,
        disponible=True,
    )
    producto.categoria = categoria
    producto_presentacion = MagicMock(
        id_producto=1,
        id_presentacion=1,
        activo=True,
    )
    producto_presentacion.producto = producto
    producto_presentacion.presentacion = presentacion
    pp = MagicMock(
        id=pp_id,
        id_producto_presentacion=100 + pp_id,
        cantidad=cantidad,
    )
    pp.producto_presentacion = producto_presentacion
    return pp


def _conversation_session(
    *,
    pedido_id: int | None,
    session_id: int = 1,
) -> MagicMock:
    sess = MagicMock(spec=ConversationSession)
    sess.id = session_id
    sess.id_pedido = pedido_id
    sess.estado_session = "ACTIVA"
    return sess


class IdentityRecoveryQualifiedMozzarellaChicaTest(unittest.TestCase):
    """The original pilot bug: own pedido has Mozzarella Grande + Chica
    and ``La pizza de mozzarella chica es sin aceitunas`` must recover
    only the Chica line once the fuzzy path returns zero candidates.
    """

    _MESSAGE = "La pizza de mozzarella chica es sin aceitunas"

    def _lines(self) -> list[MagicMock]:
        return [
            _make_pp_line(
                pp_id=101,
                producto_nombre="Mozzarella",
                presentacion_codigo="grande",
                presentacion_descripcion="Grande",
                categoria_descripcion="Pizzas",
            ),
            _make_pp_line(
                pp_id=102,
                producto_nombre="Mozzarella",
                presentacion_codigo="chica",
                presentacion_descripcion="Chica",
                categoria_descripcion="Pizzas",
            ),
        ]

    def test_recovery_yields_only_chica_line(self) -> None:
        recovered = _recover_candidates_by_identity(self._lines(), self._MESSAGE)
        self.assertEqual(recovered, [102])

    @patch.object(recognizer_module, "PedidoProductoService")
    @patch.object(recognizer_module, "recognize_quitar_producto")
    def test_recognizer_uses_recovery_when_fuzzy_returns_zero(
        self, recognize_quitar, service_cls
    ) -> None:
        recognize_quitar.return_value = {
            "encontrados": [],
            "encontrados_posibles": [],
            "encontrados_no_disponibles": [],
            "no_encontrados": [{"texto_origen": self._MESSAGE}],
            "cantidad": None,
        }
        service = MagicMock()
        service.list_by_pedido.return_value = self._lines()
        service_cls.return_value = service

        db = MagicMock(spec=DatabaseSession)
        session = _conversation_session(pedido_id=7)

        result = recognize_set_observacion_producto(db, session, self._MESSAGE)

        self.assertEqual(result["candidate_ids"], [102])
        self.assertEqual(result["observation_action"], "set")
        self.assertEqual(result["observation_text"], self._MESSAGE)
        self.assertFalse(result["no_pedido"])
        service.list_by_pedido.assert_called_once_with(7)

    @patch.object(recognizer_module, "PedidoProductoService")
    @patch.object(recognizer_module, "recognize_quitar_producto")
    def test_recovery_preserves_full_literal_message_for_orchestrator(
        self, recognize_quitar, service_cls
    ) -> None:
        recognize_quitar.return_value = {
            "encontrados": [],
            "encontrados_posibles": [],
            "encontrados_no_disponibles": [],
            "no_encontrados": [],
            "cantidad": None,
        }
        service = MagicMock()
        service.list_by_pedido.return_value = self._lines()
        service_cls.return_value = service

        db = MagicMock(spec=DatabaseSession)
        session = _conversation_session(pedido_id=7)

        result = recognize_set_observacion_producto(db, session, self._MESSAGE)

        self.assertEqual(
            result["observation_text"],
            "La pizza de mozzarella chica es sin aceitunas",
        )
        self.assertNotIn("es sin", "_".join(result.keys()))
        self.assertEqual(result["observation_action"], "set")


class IdentityRecoverySecondProductTest(unittest.TestCase):
    """The recovery is not a literal ``mozzarella/pizza`` exception:
    a different product and condition must follow the same rule.
    """

    def test_napolitana_chica_recovers_only_chica(self) -> None:
        lines = [
            _make_pp_line(
                pp_id=201,
                producto_nombre="Napolitana",
                presentacion_codigo="grande",
                presentacion_descripcion="Grande",
                categoria_descripcion="Pizzas",
            ),
            _make_pp_line(
                pp_id=202,
                producto_nombre="Napolitana",
                presentacion_codigo="chica",
                presentacion_descripcion="Chica",
                categoria_descripcion="Pizzas",
            ),
            _make_pp_line(
                pp_id=203,
                producto_nombre="Mozzarella",
                presentacion_codigo="chica",
                presentacion_descripcion="Chica",
                categoria_descripcion="Pizzas",
            ),
        ]
        message = "La napolitana chica es sin aceitunas"
        recovered = _recover_candidates_by_identity(lines, message)
        self.assertEqual(recovered, [202])

    def test_empanada_with_sin_picante_recovers_unique_line(self) -> None:
        lines = [
            _make_pp_line(
                pp_id=301,
                producto_nombre="Empanada",
                presentacion_codigo="unidad",
                presentacion_descripcion="Unidad",
                categoria_descripcion="Empanadas",
            ),
            _make_pp_line(
                pp_id=302,
                producto_nombre="Mozzarella",
                presentacion_codigo="chica",
                presentacion_descripcion="Chica",
                categoria_descripcion="Pizzas",
            ),
        ]
        message = "La empanada es sin picante"
        recovered = _recover_candidates_by_identity(lines, message)
        self.assertEqual(recovered, [301])


class IdentityRecoveryPendingForTwoCompatibleTest(unittest.TestCase):
    """When the reference has insufficient presentation disambiguation
    and two own lines share the same product, the recognizer returns
    both ids so the existing pending order-line selection path is used
    instead of silently picking a line.
    """

    def test_two_mozzarella_lines_without_presentation_remains_pending(
        self,
    ) -> None:
        lines = [
            _make_pp_line(
                pp_id=101,
                producto_nombre="Mozzarella",
                presentacion_codigo="grande",
                presentacion_descripcion="Grande",
                categoria_descripcion="Pizzas",
            ),
            _make_pp_line(
                pp_id=102,
                producto_nombre="Mozzarella",
                presentacion_codigo="chica",
                presentacion_descripcion="Chica",
                categoria_descripcion="Pizzas",
            ),
        ]
        message = "La pizza de mozzarella es sin aceitunas"
        recovered = _recover_candidates_by_identity(lines, message)
        self.assertEqual(recovered, [101, 102])

    @patch.object(recognizer_module, "PedidoProductoService")
    @patch.object(recognizer_module, "recognize_quitar_producto")
    def test_recognizer_returns_pending_candidate_set_for_two_lines(
        self, recognize_quitar, service_cls
    ) -> None:
        lines = [
            _make_pp_line(
                pp_id=101,
                producto_nombre="Mozzarella",
                presentacion_codigo="grande",
                presentacion_descripcion="Grande",
                categoria_descripcion="Pizzas",
            ),
            _make_pp_line(
                pp_id=102,
                producto_nombre="Mozzarella",
                presentacion_codigo="chica",
                presentacion_descripcion="Chica",
                categoria_descripcion="Pizzas",
            ),
        ]
        recognize_quitar.return_value = {
            "encontrados": [],
            "encontrados_posibles": [],
            "encontrados_no_disponibles": [],
            "no_encontrados": [],
            "cantidad": None,
        }
        service = MagicMock()
        service.list_by_pedido.return_value = lines
        service_cls.return_value = service

        db = MagicMock(spec=DatabaseSession)
        session = _conversation_session(pedido_id=7)

        result = recognize_set_observacion_producto(
            db, session, "La pizza de mozzarella es sin aceitunas"
        )

        self.assertEqual(result["candidate_ids"], [101, 102])
        self.assertEqual(result["observation_action"], "set")
        self.assertEqual(
            result["observation_text"],
            "La pizza de mozzarella es sin aceitunas",
        )


class IdentityRecoveryRejectsWithoutEvidenceTest(unittest.TestCase):
    """Without enough product/identity evidence the recognizer must
    reject without mutating anything and without falling back to the
    commerce catalog, another pedido, a most-recent-line heuristic or
    an LLM guess.
    """

    def test_only_category_word_does_not_match(self) -> None:
        lines = [
            _make_pp_line(
                pp_id=101,
                producto_nombre="Mozzarella",
                presentacion_codigo="chica",
                presentacion_descripcion="Chica",
                categoria_descripcion="Pizzas",
            ),
        ]
        recovered = _recover_candidates_by_identity(
            lines, "La pizza es sin aceitunas"
        )
        self.assertEqual(recovered, [])

    def test_only_presentation_word_does_not_match(self) -> None:
        lines = [
            _make_pp_line(
                pp_id=101,
                producto_nombre="Mozzarella",
                presentacion_codigo="chica",
                presentacion_descripcion="Chica",
                categoria_descripcion="Pizzas",
            ),
        ]
        recovered = _recover_candidates_by_identity(
            lines, "La chica es sin aceitunas"
        )
        self.assertEqual(recovered, [])

    def test_empty_message_returns_empty(self) -> None:
        lines = [
            _make_pp_line(
                pp_id=101,
                producto_nombre="Mozzarella",
                presentacion_codigo="chica",
                presentacion_descripcion="Chica",
                categoria_descripcion="Pizzas",
            ),
        ]
        self.assertEqual(_recover_candidates_by_identity(lines, ""), [])
        self.assertEqual(_recover_candidates_by_identity(lines, "   "), [])

    @patch.object(recognizer_module, "PedidoProductoService")
    @patch.object(recognizer_module, "recognize_quitar_producto")
    def test_no_evidence_returns_empty_candidate_set_without_mutation(
        self, recognize_quitar, service_cls
    ) -> None:
        recognize_quitar.return_value = {
            "encontrados": [],
            "encontrados_posibles": [],
            "encontrados_no_disponibles": [],
            "no_encontrados": [],
            "cantidad": None,
        }
        lines = [
            _make_pp_line(
                pp_id=101,
                producto_nombre="Mozzarella",
                presentacion_codigo="chica",
                presentacion_descripcion="Chica",
                categoria_descripcion="Pizzas",
            ),
        ]
        service = MagicMock()
        service.list_by_pedido.return_value = lines
        service_cls.return_value = service

        db = MagicMock(spec=DatabaseSession)
        session = _conversation_session(pedido_id=7)

        result = recognize_set_observacion_producto(
            db, session, "La pizza es sin aceitunas"
        )

        self.assertEqual(result["candidate_ids"], [])
        self.assertEqual(result["observation_action"], "set")
        self.assertEqual(
            result["observation_text"], "La pizza es sin aceitunas"
        )
        db.commit.assert_not_called()
        db.rollback.assert_not_called()
        db.flush.assert_not_called()


class IdentityRecoveryNoForeignOrCommerceWideningTest(unittest.TestCase):
    """The recovery only reads the SAME active draft line rows. It
    must never include lines from another pedido, the commerce
    catalog, or a most-recent-line heuristic."""

    def test_only_lines_from_list_by_pedido_are_considered(self) -> None:
        own_lines = [
            _make_pp_line(
                pp_id=101,
                producto_nombre="Mozzarella",
                presentacion_codigo="chica",
                presentacion_descripcion="Chica",
                categoria_descripcion="Pizzas",
            ),
        ]
        foreign_lines = [
            _make_pp_line(
                pp_id=999,
                producto_nombre="Mozzarella",
                presentacion_codigo="chica",
                presentacion_descripcion="Chica",
                categoria_descripcion="Pizzas",
            ),
        ]
        message = "La pizza de mozzarella chica es sin aceitunas"
        recovered_own = _recover_candidates_by_identity(own_lines, message)
        recovered_foreign = _recover_candidates_by_identity(
            foreign_lines, message
        )
        self.assertEqual(recovered_own, [101])
        self.assertEqual(recovered_foreign, [999])
        self.assertNotIn(
            999,
            recovered_own,
            "a foreign pedido line must never be widened into the set",
        )

    def test_no_aliases_are_consulted(self) -> None:
        """The recovery must use only the already-projected fields and
        must not introduce any new alias source."""

        importlib.reload(recognizer_module)
        with open(recognizer_module.__file__, encoding="utf-8") as fh:
            source = fh.read()
        for forbidden in (
            "ProductoAlias",
            "producto_alias",
            "alias_normalizado",
            "from backend.services.producto_alias",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)


class FuzzyAlreadyProducesCandidatesTest(unittest.TestCase):
    """If the bounded fuzzy path already produces at least one
    candidate, the identity recovery must not be invoked.
    """

    @patch.object(recognizer_module, "PedidoProductoService")
    @patch.object(recognizer_module, "recognize_quitar_producto")
    def test_fuzzy_match_short_circuits_recovery(
        self, recognize_quitar, service_cls
    ) -> None:
        recognize_quitar.return_value = {
            "encontrados": [
                {
                    "pedido_producto_id": 42,
                    "producto_presentacion_id": 1,
                    "producto_nombre": "Mozzarella",
                }
            ],
            "encontrados_posibles": [],
            "encontrados_no_disponibles": [],
            "no_encontrados": [],
            "cantidad": None,
        }
        service = MagicMock()
        service_cls.return_value = service

        db = MagicMock(spec=DatabaseSession)
        session = _conversation_session(pedido_id=7)

        result = recognize_set_observacion_producto(
            db, session, "La pizza de mozzarella chica es sin aceitunas"
        )

        self.assertEqual(result["candidate_ids"], [42])
        service.list_by_pedido.assert_not_called()


class RecognizerNoTransactionControlTest(unittest.TestCase):
    """The recognizer is read-only: it never commits, rolls back,
    flushes, refreshes, expires, begins, or closes the database
    session.
    """

    def test_source_does_not_call_transaction_methods(self) -> None:
        importlib.reload(recognizer_module)
        with open(recognizer_module.__file__, encoding="utf-8") as fh:
            source = fh.read()
        for forbidden in (
            "db.commit",
            "db.rollback",
            "db.flush",
            "db.refresh",
            "db.expire",
            "db.begin",
            "db.close",
            "session.commit",
            "session.rollback",
            "session.flush",
            "session.refresh",
            "session.expire",
            "session.begin",
            "session.close",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)

    def test_module_does_not_import_disallowed_side_effects(self) -> None:
        importlib.reload(recognizer_module)
        with open(recognizer_module.__file__, encoding="utf-8") as fh:
            source = fh.read()
        for forbidden in (
            "from backend.repositories",
            "from backend.routers",
            "from backend.llm",
            "from backend.dependencies",
            "import requests",
            "from requests",
            "import fastapi",
            "from fastapi",
            "HTTPException",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)

    def test_public_surface_is_limited(self) -> None:
        self.assertEqual(
            set(recognizer_module.__all__),
            {"is_clear_observation_message", "recognize_set_observacion_producto"},
        )


class RecognizerClearGrammarUnchangedTest(unittest.TestCase):
    """The existing clear grammar must remain unchanged by the
    identity-recovery amendment."""

    def test_clear_phrase_still_detected(self) -> None:
        self.assertTrue(
            is_clear_observation_message("Quitar la aclaracion de la pizza")
        )

    def test_declarative_set_phrase_still_not_clear(self) -> None:
        self.assertFalse(
            is_clear_observation_message(
                "La pizza de mozzarella chica es sin aceitunas"
            )
        )


class IdentityRecoveryConditionWordDoesNotDesambiguateTest(unittest.TestCase):
    """A condition word that appears later in the message must not be
    treated as a presentation disambiguator. Only the contiguous run
    ``<producto> <presentación>`` counts as identity evidence.
    """

    def _lines(self) -> list[MagicMock]:
        return [
            _make_pp_line(
                pp_id=101,
                producto_nombre="Mozzarella",
                presentacion_codigo="grande",
                presentacion_descripcion="Grande",
                categoria_descripcion="Pizzas",
            ),
            _make_pp_line(
                pp_id=102,
                producto_nombre="Mozzarella",
                presentacion_codigo="chica",
                presentacion_descripcion="Chica",
                categoria_descripcion="Pizzas",
            ),
        ]

    def test_condition_grande_word_does_not_select_grande_line(self) -> None:
        recovered = _recover_candidates_by_identity(
            self._lines(),
            "La pizza de mozzarella es con salsa grande",
        )
        self.assertEqual(recovered, [101, 102])

    def test_condition_chica_word_does_not_select_chica_line(self) -> None:
        recovered = _recover_candidates_by_identity(
            self._lines(),
            "La pizza de mozzarella es con salsa chica",
        )
        self.assertEqual(recovered, [101, 102])

    def test_real_pilot_message_still_selects_only_chica(self) -> None:
        recovered = _recover_candidates_by_identity(
            self._lines(),
            "La pizza de mozzarella chica es sin aceitunas",
        )
        self.assertEqual(recovered, [102])

    @patch.object(recognizer_module, "PedidoProductoService")
    @patch.object(recognizer_module, "recognize_quitar_producto")
    def test_recognizer_returns_pending_for_condition_word_message(
        self, recognize_quitar, service_cls
    ) -> None:
        recognize_quitar.return_value = {
            "encontrados": [],
            "encontrados_posibles": [],
            "encontrados_no_disponibles": [],
            "no_encontrados": [],
            "cantidad": None,
        }
        service = MagicMock()
        service.list_by_pedido.return_value = self._lines()
        service_cls.return_value = service

        db = MagicMock(spec=DatabaseSession)
        session = _conversation_session(pedido_id=7)

        result = recognize_set_observacion_producto(
            db,
            session,
            "La pizza de mozzarella es con salsa grande",
        )

        self.assertEqual(result["candidate_ids"], [101, 102])
        self.assertEqual(result["observation_action"], "set")
        self.assertEqual(
            result["observation_text"],
            "La pizza de mozzarella es con salsa grande",
        )
        db.commit.assert_not_called()
        db.rollback.assert_not_called()


class IdentityRecoveryCompoundProductTest(unittest.TestCase):
    """A condition word must not artificially complete a compound
    product name. The recovery requires the full normalized product
    name to appear as a contiguous subsequence of the message tokens.
    """

    def test_condition_word_does_not_complete_compound_product(self) -> None:
        lines = [
            _make_pp_line(
                pp_id=201,
                producto_nombre="Pizza Mozzarella",
                presentacion_codigo="chica",
                presentacion_descripcion="Chica",
                categoria_descripcion="Pizzas",
            ),
            _make_pp_line(
                pp_id=202,
                producto_nombre="Pizza Mozzarella",
                presentacion_codigo="grande",
                presentacion_descripcion="Grande",
                categoria_descripcion="Pizzas",
            ),
            _make_pp_line(
                pp_id=203,
                producto_nombre="Mozzarella",
                presentacion_codigo="chica",
                presentacion_descripcion="Chica",
                categoria_descripcion="Pizzas",
            ),
        ]
        recovered = _recover_candidates_by_identity(
            lines, "La pizza grande es sin aceitunas"
        )
        self.assertEqual(recovered, [])

    def test_contiguous_compound_product_strict_match(self) -> None:
        lines = [
            _make_pp_line(
                pp_id=201,
                producto_nombre="Pizza Mozzarella",
                presentacion_codigo="chica",
                presentacion_descripcion="Chica",
                categoria_descripcion="Pizzas",
            ),
            _make_pp_line(
                pp_id=202,
                producto_nombre="Pizza Mozzarella",
                presentacion_codigo="grande",
                presentacion_descripcion="Grande",
                categoria_descripcion="Pizzas",
            ),
        ]
        recovered = _recover_candidates_by_identity(
            lines,
            "La pizza mozzarella chica es sin aceitunas",
        )
        self.assertEqual(recovered, [201])

    def test_compound_product_split_by_preposition_does_not_match(self) -> None:
        lines = [
            _make_pp_line(
                pp_id=201,
                producto_nombre="Pizza Mozzarella",
                presentacion_codigo="chica",
                presentacion_descripcion="Chica",
                categoria_descripcion="Pizzas",
            ),
        ]
        recovered = _recover_candidates_by_identity(
            lines,
            "La pizza de mozzarella chica es sin aceitunas",
        )
        self.assertEqual(recovered, [])

    def test_strict_match_requires_adjacent_presentation_after_product(
        self,
    ) -> None:
        lines = [
            _make_pp_line(
                pp_id=301,
                producto_nombre="Mozzarella",
                presentacion_codigo="chica",
                presentacion_descripcion="Chica",
                categoria_descripcion="Pizzas",
            ),
            _make_pp_line(
                pp_id=302,
                producto_nombre="Mozzarella",
                presentacion_codigo="grande",
                presentacion_descripcion="Grande",
                categoria_descripcion="Pizzas",
            ),
        ]
        recovered = _recover_candidates_by_identity(
            lines,
            "Mozzarella con salsa grande",
        )
        self.assertEqual(recovered, [301, 302])


if __name__ == "__main__":
    unittest.main()