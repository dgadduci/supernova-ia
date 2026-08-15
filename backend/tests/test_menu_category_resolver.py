"""Focused tests for the dedicated menu category resolver.

The resolver is the bounded second LLM interpreter that decides which
single ``ver_menu`` category, if any, a customer menu browse request
refers to. These tests cover:

* happy-path selection (Pizzas / Empanadas / Bebidas);
* strict no-selection return (``null`` ``null``);
* mismatched or unknown ``(token, nombre)``;
* extra-field / malformed payload containment;
* documented transport failures (timeout / connection / HTTP /
  response / schema) translated to typed ``no_selection`` without
  leaking exception text or IDs;
* candidate bounds (count, name length, serialized context length);
* prompt privacy — the rendered prompt contains only the classified
  source text and the opaque ``(token, nombre)`` pairs;
* diagnostic identity that never carries raw message text or
  category names;
* one prompt per call, no mutation/transaction controls, no DB IDs in
  the projection.
"""
from __future__ import annotations

import unittest

from backend.diagnostics.menu_category_prompt_template import (
    MENU_CATEGORY_PROMPT_TEMPLATE_VERSION,
    build_menu_category_prompt,
    menu_category_template_fingerprint,
    menu_category_template_identity,
)
from backend.llm import menu_category_resolver as resolver_module
from backend.llm.menu_category_resolver import (
    MAX_CANDIDATE_CONTEXT_CHARS,
    MAX_CANDIDATE_COUNT,
    MAX_CANDIDATE_NAME_LENGTH,
    MenuCategoryCandidate,
    MenuCategoryResolution,
    MenuCategoryResolver,
)
from backend.llm.query_llm import (
    QueryLlmConnectionError,
    QueryLlmHttpError,
    QueryLlmResponseError,
    QueryLlmTimeoutError,
)


def _candidate(token: str, nombre: str, categoria_id: int) -> MenuCategoryCandidate:
    return MenuCategoryCandidate(
        categoria_id=categoria_id,
        token=token,
        nombre=nombre,
    )


class _StubQueryLlm:
    def __init__(self, payload=None, side_effect: BaseException | None = None):
        self._payload = payload
        self._side_effect = side_effect
        self.calls: list[str] = []

    def request(self, prompt: str) -> dict:
        self.calls.append(prompt)
        if self._side_effect is not None:
            raise self._side_effect
        return self._payload or {}


class ResolverPromptTemplateTest(unittest.TestCase):
    def test_prompt_includes_only_query_and_opaque_candidate_pairs(self) -> None:
        candidates = [
            {"token": "c1", "nombre": "Pizzas"},
            {"token": "c2", "nombre": "Empanadas"},
        ]
        prompt = build_menu_category_prompt("qué pizzas hay", candidates)

        self.assertIn("qué pizzas hay", prompt)
        self.assertIn("token: c1 | nombre: Pizzas", prompt)
        self.assertIn("token: c2 | nombre: Empanadas", prompt)

    def test_prompt_does_not_include_real_categoria_id_values(self) -> None:
        candidates = [
            {"token": "c1", "nombre": "Pizzas"},
            {"token": "c2", "nombre": "Empanadas"},
        ]
        prompt = build_menu_category_prompt("qué pizzas hay", candidates)
        for forbidden in (
            "12345",
            "99999",
            "categoria_id",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, prompt)

    def test_prompt_does_not_include_product_names_prices_or_aliases(self) -> None:
        candidates = [
            {"token": "c1", "nombre": "Pizzas"},
            {"token": "c2", "nombre": "Empanadas"},
        ]
        prompt = build_menu_category_prompt("qué pizzas hay", candidates)
        for forbidden in (
            "Muzzarella",
            "Coca-Cola",
            "$1500",
            "alias",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, prompt)

    def test_template_fingerprint_is_independent_of_message_or_candidates(self) -> None:
        base = menu_category_template_fingerprint()
        other = build_menu_category_prompt("otro mensaje", [{"token": "c9", "nombre": "Bebidas"}])
        self.assertEqual(menu_category_template_fingerprint(), base)
        self.assertNotEqual(other, "")

    def test_template_identity_pins_version_and_hash(self) -> None:
        identity = menu_category_template_identity()
        self.assertEqual(
            identity["menu_category_prompt_template_version"],
            MENU_CATEGORY_PROMPT_TEMPLATE_VERSION,
        )
        self.assertEqual(
            identity["menu_category_prompt_template_hash"],
            menu_category_template_fingerprint(),
        )


class MenuCategoryResolverSelectionTest(unittest.TestCase):
    def _candidates(self) -> list[MenuCategoryCandidate]:
        return [
            _candidate("c1", "Pizzas", 101),
            _candidate("c2", "Empanadas", 202),
            _candidate("c3", "Bebidas", 303),
        ]

    def test_returns_selected_pair_when_both_match(self) -> None:
        stub = _StubQueryLlm(payload={"token": "c2", "nombre": "Empanadas"})
        resolver = MenuCategoryResolver(query_llm=stub)

        resolution = resolver.resolve("qué gustos de empanadas tenés", self._candidates())

        self.assertIsInstance(resolution, MenuCategoryResolution)
        self.assertTrue(resolution.is_selected)
        self.assertIsNotNone(resolution.selected)
        assert resolution.selected is not None
        self.assertEqual(resolution.selected.token, "c2")
        self.assertEqual(resolution.selected.nombre, "Empanadas")
        self.assertEqual(resolution.selected.categoria_id, 202)
        self.assertEqual(resolution.candidate_count, 3)
        self.assertIsNone(resolution.failure_class)

    def test_returns_no_selection_when_both_null(self) -> None:
        stub = _StubQueryLlm(payload={"token": None, "nombre": None})
        resolver = MenuCategoryResolver(query_llm=stub)

        resolution = resolver.resolve("qué pizzas hay", self._candidates())

        self.assertFalse(resolution.is_selected)
        self.assertIsNone(resolution.selected)
        self.assertIsNone(resolution.failure_class)

    def test_returns_no_selection_on_token_name_mismatch(self) -> None:
        stub = _StubQueryLlm(payload={"token": "c1", "nombre": "Empanadas"})
        resolver = MenuCategoryResolver(query_llm=stub)

        resolution = resolver.resolve("qué pizzas hay", self._candidates())

        self.assertFalse(resolution.is_selected)
        self.assertIsNone(resolution.failure_class)

    def test_returns_no_selection_on_unknown_token(self) -> None:
        stub = _StubQueryLlm(payload={"token": "c99", "nombre": "Pizzas"})
        resolver = MenuCategoryResolver(query_llm=stub)

        resolution = resolver.resolve("qué pizzas hay", self._candidates())

        self.assertFalse(resolution.is_selected)

    def test_returns_no_selection_on_unknown_nombre(self) -> None:
        stub = _StubQueryLlm(payload={"token": "c1", "nombre": "Hamburguesas"})
        resolver = MenuCategoryResolver(query_llm=stub)

        resolution = resolver.resolve("qué pizzas hay", self._candidates())

        self.assertFalse(resolution.is_selected)

    def test_returns_no_selection_on_extra_field_payload(self) -> None:
        stub = _StubQueryLlm(
            payload={"token": "c1", "nombre": "Pizzas", "categoria_id": 101}
        )
        resolver = MenuCategoryResolver(query_llm=stub)

        resolution = resolver.resolve("qué pizzas hay", self._candidates())

        self.assertFalse(resolution.is_selected)
        self.assertEqual(resolution.failure_class, "schema")

    def test_returns_no_selection_on_malformed_payload(self) -> None:
        stub = _StubQueryLlm(payload={"token": 42, "nombre": ["Pizzas"]})
        resolver = MenuCategoryResolver(query_llm=stub)

        resolution = resolver.resolve("qué pizzas hay", self._candidates())

        self.assertFalse(resolution.is_selected)
        self.assertEqual(resolution.failure_class, "schema")

    def test_returns_no_selection_when_only_token_present(self) -> None:
        stub = _StubQueryLlm(payload={"token": "c1", "nombre": None})
        resolver = MenuCategoryResolver(query_llm=stub)

        resolution = resolver.resolve("qué pizzas hay", self._candidates())

        self.assertFalse(resolution.is_selected)

    def test_returns_no_selection_when_only_nombre_present(self) -> None:
        stub = _StubQueryLlm(payload={"token": None, "nombre": "Pizzas"})
        resolver = MenuCategoryResolver(query_llm=stub)

        resolution = resolver.resolve("qué pizzas hay", self._candidates())

        self.assertFalse(resolution.is_selected)


class MenuCategoryResolverFailureContainmentTest(unittest.TestCase):
    def _candidates(self) -> list[MenuCategoryCandidate]:
        return [
            _candidate("c1", "Pizzas", 101),
            _candidate("c2", "Empanadas", 202),
        ]

    def _assert_typed_failure(self, exc: BaseException, expected_class: str) -> None:
        stub = _StubQueryLlm(side_effect=exc)
        resolver = MenuCategoryResolver(query_llm=stub)

        resolution = resolver.resolve("qué pizzas hay", self._candidates())

        self.assertFalse(resolution.is_selected)
        self.assertEqual(resolution.failure_class, expected_class)
        self.assertTrue(resolution.attempted)

    def test_timeout_translates_to_transport_failure(self) -> None:
        self._assert_typed_failure(QueryLlmTimeoutError("boom"), "transport")

    def test_connection_error_translates_to_transport_failure(self) -> None:
        self._assert_typed_failure(
            QueryLlmConnectionError("boom"), "transport"
        )

    def test_http_error_translates_to_transport_failure(self) -> None:
        self._assert_typed_failure(QueryLlmHttpError(500, "boom"), "transport")

    def test_response_error_translates_to_response_failure(self) -> None:
        self._assert_typed_failure(QueryLlmResponseError("boom"), "response")

    def test_schema_error_translates_to_schema_failure(self) -> None:
        stub = _StubQueryLlm(payload={"token": "c1"})
        resolver = MenuCategoryResolver(query_llm=stub)

        resolution = resolver.resolve("qué pizzas hay", self._candidates())

        self.assertFalse(resolution.is_selected)
        self.assertEqual(resolution.failure_class, "schema")

    def test_resolver_does_not_leak_exception_text_in_resolution(self) -> None:
        sentinel = "SECRET-EXCEPTION-CONTENT-9876543210"
        stub = _StubQueryLlm(
            side_effect=QueryLlmTimeoutError(sentinel)
        )
        resolver = MenuCategoryResolver(query_llm=stub)

        resolution = resolver.resolve("qué pizzas hay", self._candidates())

        self.assertNotIn(sentinel, repr(resolution))


class MenuCategoryResolverBoundsTest(unittest.TestCase):
    def test_candidate_count_overflow_drops_to_twenty(self) -> None:
        many = [
            _candidate(f"c{index}", f"Categoria {index}", index)
            for index in range(1, 30)
        ]
        bounded = resolver_module._enforce_candidate_bounds(many)
        self.assertEqual(len(bounded), MAX_CANDIDATE_COUNT)

    def test_candidate_name_too_long_is_filtered(self) -> None:
        long_name = "x" * (MAX_CANDIDATE_NAME_LENGTH + 1)
        candidates = [
            _candidate("c1", "Pizzas", 1),
            _candidate("c2", long_name, 2),
            _candidate("c3", "Bebidas", 3),
        ]
        bounded = resolver_module._enforce_candidate_bounds(candidates)
        tokens = [c.token for c in bounded]
        self.assertIn("c1", tokens)
        self.assertIn("c3", tokens)
        self.assertNotIn("c2", tokens)

    def test_serialization_constants_match_documented_values(self) -> None:
        self.assertEqual(MAX_CANDIDATE_COUNT, 20)
        self.assertEqual(MAX_CANDIDATE_NAME_LENGTH, 80)
        self.assertEqual(MAX_CANDIDATE_CONTEXT_CHARS, 2000)


class MenuCategoryResolverPrivacyTest(unittest.TestCase):
    def test_rendered_prompt_omits_real_categoria_id_and_product_metadata(self) -> None:
        candidates = [_candidate("c1", "Pizzas", 999)]
        prompt = build_menu_category_prompt(
            "qué pizzas hay",
            [{"token": c.token, "nombre": c.nombre} for c in candidates],
        )

        self.assertNotIn("999", prompt)
        self.assertNotIn("categoria_id", prompt)
        self.assertNotIn("Muzzarella", prompt)
        self.assertNotIn("$1500", prompt)

    def test_resolution_does_not_carry_raw_message_or_category_label(self) -> None:
        secret_message = "RAW-CUSTOMER-MESSAGE-SECRET-ABC123"
        secret_name = "Bebidas secretas"
        candidates = [_candidate("c1", secret_name, 123)]

        resolver = MenuCategoryResolver(
            query_llm=_StubQueryLlm(payload={"token": None, "nombre": None})
        )

        resolution = resolver.resolve(secret_message, candidates)

        self.assertNotIn(secret_message, repr(resolution))
        self.assertNotIn(secret_name, repr(resolution))

    def test_template_fingerprint_stable_across_messages_and_candidates(self) -> None:
        first = menu_category_template_fingerprint()
        build_menu_category_prompt(
            "otro mensaje distinto",
            [{"token": "c1", "nombre": "Otra"}],
        )
        self.assertEqual(menu_category_template_fingerprint(), first)


class MenuCategoryResolverSurfaceTest(unittest.TestCase):
    def test_public_all_is_minimal(self) -> None:
        self.assertEqual(
            set(resolver_module.__all__),
            {
                "MAX_CANDIDATE_CONTEXT_CHARS",
                "MAX_CANDIDATE_COUNT",
                "MAX_CANDIDATE_NAME_LENGTH",
                "MenuCategoryCandidate",
                "MenuCategoryResolution",
                "MenuCategoryResolver",
            },
        )


if __name__ == "__main__":
    unittest.main()