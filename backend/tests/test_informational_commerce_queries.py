"""Focused tests for the informational commerce queries change.

The change introduces read-only deterministic responses for the six
approved informational intents emitted by the classifier when the
session has no pending context:

* ``ver_menu``
* ``consultar_producto``
* ``ver_metodos_de_pago``
* ``ver_metodos_de_entrega``
* ``consultar_domicilio_comercio``
* ``consultar_horarios_comercio``

These tests cover commerce isolation, pending-context priority,
active/available/sellable filtering and configured ordering, the
no-option / no-catalog business outcomes, the deterministic
one / no / multiple product matches, address formatting, the
hours-not-configured reply, technical failure propagation, response
ordering, local/outbox equivalence and the no-mutation/no-transaction
invariants.
"""
from __future__ import annotations

import importlib
import unittest
from unittest.mock import MagicMock, patch

from backend.intents.orchestration import informational_commerce_queries as info_module
from backend.intents.orchestration import initial_intent_dispatcher as dispatcher_module
from backend.intents.orchestration.informational_commerce_queries import (
    INFORMATIONAL_COMMERCE_HANDLER,
    is_informational_commerce_intent,
    process_initial_informational_commerce_query,
)
from backend.intents.orchestration.initial_intent_dispatcher import (
    dispatch_initial_message,
)
from backend.intents.responses import informational_commerce_queries as response_module
from backend.intents.responses.informational_commerce_queries import (
    build_informational_commerce_response,
)
from backend.intents.schemas.intent_classification import (
    ClassifiedIntent,
    IntentClassificationResult,
    IntentName,
)
from backend.intents.schemas.processed_intent import ProcessedIntent
from backend.services import outbound_response_mapper as mapper_module
from backend.services.exceptions import ComercioNotFound
from backend.services.outbound_response_mapper import (
    GENERIC_MESSAGE,
    build_customer_responses,
)


def _session(*, id_comercio: int | None = 7) -> MagicMock:
    session = MagicMock(name="ConversationSession")
    session.id_comercio = id_comercio
    session.context_type = None
    session.id_pedido = None
    session.pending_intents = None
    return session


def _db() -> MagicMock:
    return MagicMock(name="DatabaseSession")


def _classified(intent: IntentName, mensaje: str) -> ClassifiedIntent:
    return ClassifiedIntent(intent=intent, mensaje=mensaje)


def _build_result(*items: tuple[IntentName, str]) -> IntentClassificationResult:
    intents = [
        ClassifiedIntent(intent=name, mensaje=message) for name, message in items
    ]
    first_message = items[0][1] if items else "x"
    return IntentClassificationResult(intents=intents, mensaje=first_message)


def _categoria(descripcion: str, orden: int = 0):
    categoria = MagicMock(name=f"Categoria({descripcion})")
    categoria.descripcion = descripcion
    categoria.orden = orden
    return categoria


def _presentacion(codigo: str, descripcion: str, *, id_: int = 0):
    presentacion = MagicMock(name=f"Presentacion({codigo})")
    presentacion.codigo = codigo
    presentacion.descripcion = descripcion
    presentacion.id = id_
    presentacion.activo = True
    return presentacion


def _producto_presentacion(
    *,
    id_: int,
    presentacion,
    activo: bool = True,
    precios: list | None = None,
):
    pp = MagicMock(name=f"ProductoPresentacion({id_})")
    pp.id = id_
    pp.id_producto = 0
    pp.id_presentacion = presentacion.id
    pp.activo = activo
    pp.presentacion = presentacion
    pp.orden = 0
    pp.precios = precios if precios is not None else []
    return pp


def _precio(valor):
    precio = MagicMock(name=f"Precio({valor})")
    precio.precio = valor
    return precio


def _resolved(
    *,
    selected=None,
    token: str | None = None,
    nombre: str | None = None,
    categoria_id: int | None = None,
    candidate_count: int = 3,
):
    """Build a :class:`MenuCategoryResolution` for tests."""
    from backend.llm.menu_category_resolver import (
        MenuCategoryCandidate,
        MenuCategoryResolution,
    )

    if selected is None and token is not None and nombre is not None:
        candidate = MenuCategoryCandidate(
            categoria_id=int(categoria_id or 0),
            token=token,
            nombre=nombre,
        )
        return MenuCategoryResolution(
            selected=candidate,
            failure_class=None,
            attempted=True,
            candidate_count=candidate_count,
            latency_ms=1,
            template_version="menu-category-resolver/v1.0.0",
            template_fingerprint="test-fp",
            model=None,
        )
    return MenuCategoryResolution(
        selected=None,
        failure_class=None,
        attempted=True,
        candidate_count=candidate_count,
        latency_ms=1,
        template_version="menu-category-resolver/v1.0.0",
        template_fingerprint="test-fp",
        model=None,
    )


def _producto(
    *,
    id_: int,
    nombre: str,
    categoria,
    presentaciones,
    orden: int = 0,
    activo: bool = True,
    disponible: bool = True,
):
    producto = MagicMock(name=f"Producto({nombre})")
    producto.id = id_
    producto.nombre = nombre
    producto.activo = activo
    producto.disponible = disponible
    producto.orden = orden
    producto.categoria = categoria
    producto.presentaciones = presentaciones
    return producto


def _medio_pago(id_: int, codigo: str, descripcion: str, activo: bool = True):
    medio = MagicMock(name=f"MedioPago({codigo})")
    medio.id = id_
    medio.codigo = codigo
    medio.descripcion = descripcion
    medio.activo = activo
    return medio


def _metodo_entrega(id_: int, codigo: str, descripcion: str, orden: int = 0):
    metodo = MagicMock(name=f"MetodoEntrega({codigo})")
    metodo.id = id_
    metodo.codigo = codigo
    metodo.descripcion = descripcion
    metodo.orden = orden
    metodo.activo = True
    return metodo


def _comercio(
    *,
    id_: int = 7,
    calle: str = "Av. Siempre Viva",
    numero: str = "742",
    piso: str | None = None,
    localidad: str = "Springfield",
    provincia: str = "Buenos Aires",
    codigo_postal: str | None = "1000",
):
    comercio = MagicMock(name=f"Comercio({id_})")
    comercio.id = id_
    comercio.calle = calle
    comercio.numero = numero
    comercio.piso_departamento = piso
    comercio.localidad = localidad
    comercio.provincia = provincia
    comercio.codigo_postal = codigo_postal
    return comercio


class IsInformationalCommerceIntentTest(unittest.TestCase):
    def test_recognises_each_approved_intent(self) -> None:
        for name in (
            "ver_menu",
            "consultar_producto",
            "ver_metodos_de_pago",
            "ver_metodos_de_entrega",
            "consultar_domicilio_comercio",
            "consultar_horarios_comercio",
        ):
            with self.subTest(intent=name):
                self.assertTrue(is_informational_commerce_intent(name))

    def test_does_not_recognise_unrelated_intents(self) -> None:
        for name in (
            "agregar_producto",
            "consultar_resumen_pedido",
            "confirmar_pedido",
            "set_metodo_de_pago",
            "saludo",
            "desconocida",
            "",
        ):
            with self.subTest(intent=name):
                self.assertFalse(is_informational_commerce_intent(name))


class ProcessInitialMenuTest(unittest.TestCase):
    @patch.object(info_module, "_build_menu_category_resolver")
    @patch.object(info_module, "ProductoQueryService")
    def test_executed_lists_only_sellable_products_in_configured_order(
        self, svc_cls, resolver_factory
    ) -> None:
        cat_pizzas = _categoria("Pizzas", orden=1)
        cat_pizzas.id = 1
        cat_empanadas = _categoria("Empanadas", orden=2)
        cat_empanadas.id = 2
        pres_pizza_individual = _presentacion("PI", "Individual")
        pres_pizza_grande = _presentacion("PG", "Grande")
        pres_empanada_carne = _presentacion("EC", "Unidad")

        pizza = _producto(
            id_=1,
            nombre="Muzzarella",
            categoria=cat_pizzas,
            presentaciones=[
                _producto_presentacion(id_=10, presentacion=pres_pizza_individual),
                _producto_presentacion(id_=11, presentacion=pres_pizza_grande),
            ],
            orden=1,
        )
        empanada = _producto(
            id_=2,
            nombre="Empanada de Carne",
            categoria=cat_empanadas,
            presentaciones=[_producto_presentacion(id_=20, presentacion=pres_empanada_carne)],
            orden=1,
        )
        svc_cls.return_value.list_vendibles.return_value = [pizza, empanada]
        resolver_instance = resolver_factory.return_value
        resolver_instance.resolve.return_value = _resolved(selected=None)

        processed = process_initial_informational_commerce_query(
            _db(), _session(id_comercio=7), _classified(IntentName.VER_MENU, "menu")
        )

        self.assertEqual(processed.intent, "ver_menu")
        self.assertEqual(processed.status, "executed")
        self.assertEqual(processed.handler, INFORMATIONAL_COMMERCE_HANDLER)
        self.assertEqual(processed.recognizer, INFORMATIONAL_COMMERCE_HANDLER)
        items = processed.resolved_data["items"]
        self.assertEqual(
            [item["presentacion_codigo"] for item in items],
            ["PI", "PG", "EC"],
        )
        self.assertEqual(items[0]["categoria_nombre"], "Pizzas")
        self.assertEqual(items[-1]["categoria_nombre"], "Empanadas")
        svc_cls.return_value.list_vendibles.assert_called_once_with(7)
        resolver_instance.resolve.assert_called_once()

    @patch.object(info_module, "ProductoQueryService")
    def test_empty_catalog_returns_no_items_rejection(self, svc_cls) -> None:
        svc_cls.return_value.list_vendibles.return_value = []

        processed = process_initial_informational_commerce_query(
            _db(), _session(id_comercio=7), _classified(IntentName.VER_MENU, "menu")
        )

        self.assertEqual(processed.intent, "ver_menu")
        self.assertEqual(processed.status, "rejected")
        self.assertEqual(processed.resolved_data["reason"], "no_items")
        self.assertEqual(processed.handler, INFORMATIONAL_COMMERCE_HANDLER)

    @patch.object(info_module, "ProductoQueryService")
    def test_uses_only_session_comercio(self, svc_cls) -> None:
        svc_cls.return_value.list_vendibles.return_value = []
        session = _session(id_comercio=42)

        process_initial_informational_commerce_query(
            _db(),
            session,
            _classified(IntentName.VER_MENU, "menu"),
        )

        svc_cls.return_value.list_vendibles.assert_called_once_with(42)


class ProcessInitialMenuCategoryResolverTest(unittest.TestCase):
    """Focused tests for the bounded second LLM resolver inside
    ``_resolve_menu``. The informational orchestration must:

    * invoke the resolver exactly once for ``ver_menu`` with the
      bounded candidate projection;
    * preserve the full menu when the resolver selects nothing or
      fails;
    * honour the documented candidate bounds;
    * never query another commerce or accept a LLM-provided database
      ID;
    * keep the original ``list_vendibles`` call unique.
    """

    def _catalog(self) -> list:
        cat_pizzas = _categoria("Pizzas", orden=1)
        cat_empanadas = _categoria("Empanadas", orden=2)
        cat_bebidas = _categoria("Bebidas", orden=3)
        cat_pizzas.id = 1
        cat_empanadas.id = 2
        cat_bebidas.id = 3

        pres_pizza_individual = _presentacion("PI", "Individual")
        pres_pizza_grande = _presentacion("PG", "Grande")
        pres_empanada_carne = _presentacion("EC", "Unidad")
        pres_empanada_pollo = _presentacion("EP", "Unidad")
        pres_bebida_cola = _presentacion("BC", "Botella")

        pizza = _producto(
            id_=1,
            nombre="Muzzarella",
            categoria=cat_pizzas,
            presentaciones=[
                _producto_presentacion(id_=10, presentacion=pres_pizza_individual),
                _producto_presentacion(id_=11, presentacion=pres_pizza_grande),
            ],
            orden=1,
        )
        pizza2 = _producto(
            id_=2,
            nombre="Napolitana",
            categoria=cat_pizzas,
            presentaciones=[
                _producto_presentacion(id_=12, presentacion=pres_pizza_individual),
            ],
            orden=2,
        )
        empanada_carne = _producto(
            id_=3,
            nombre="Carne picante",
            categoria=cat_empanadas,
            presentaciones=[
                _producto_presentacion(id_=20, presentacion=pres_empanada_carne),
            ],
            orden=1,
        )
        empanada_pollo = _producto(
            id_=4,
            nombre="Pollo",
            categoria=cat_empanadas,
            presentaciones=[
                _producto_presentacion(id_=21, presentacion=pres_empanada_pollo),
            ],
            orden=2,
        )
        bebida_cola = _producto(
            id_=5,
            nombre="Coca-Cola",
            categoria=cat_bebidas,
            presentaciones=[
                _producto_presentacion(id_=30, presentacion=pres_bebida_cola),
            ],
            orden=1,
        )
        return [pizza, pizza2, empanada_carne, empanada_pollo, bebida_cola]

    @patch.object(info_module, "_build_menu_category_resolver")
    @patch.object(info_module, "ProductoQueryService")
    def test_empanadas_selection_filters_only_empanadas(
        self, svc_cls, resolver_cls
    ) -> None:
        svc_cls.return_value.list_vendibles.return_value = self._catalog()
        resolver_instance = resolver_cls.return_value
        resolver_instance.resolve.return_value = _resolved(
            token="c2", nombre="Empanadas", categoria_id=2
        )

        processed = process_initial_informational_commerce_query(
            _db(),
            _session(id_comercio=7),
            _classified(IntentName.VER_MENU, "qué gustos de empanadas tenés"),
        )

        self.assertEqual(processed.intent, "ver_menu")
        self.assertEqual(processed.status, "executed")
        self.assertEqual(processed.resolved_data["categoria_nombre"], "Empanadas")
        items = processed.resolved_data["items"]
        self.assertEqual(
            [(i["producto_nombre"], i["categoria_nombre"]) for i in items],
            [
                ("Carne picante", "Empanadas"),
                ("Pollo", "Empanadas"),
            ],
        )
        resolver_instance.resolve.assert_called_once()
        args, _ = resolver_instance.resolve.call_args
        self.assertEqual(args[0], "qué gustos de empanadas tenés")
        sent_candidates = args[1]
        self.assertEqual(
            [(c.token, c.nombre) for c in sent_candidates],
            [("c1", "Pizzas"), ("c2", "Empanadas"), ("c3", "Bebidas")],
        )
        for candidate in sent_candidates:
            self.assertNotEqual(candidate.categoria_id, 7)

    @patch.object(info_module, "_build_menu_category_resolver")
    @patch.object(info_module, "ProductoQueryService")
    def test_pizzas_selection_filters_only_pizzas(
        self, svc_cls, resolver_cls
    ) -> None:
        svc_cls.return_value.list_vendibles.return_value = self._catalog()
        resolver_instance = resolver_cls.return_value
        resolver_instance.resolve.return_value = _resolved(
            token="c1", nombre="Pizzas", categoria_id=1
        )

        processed = process_initial_informational_commerce_query(
            _db(),
            _session(id_comercio=7),
            _classified(IntentName.VER_MENU, "qué pizzas hay"),
        )

        items = processed.resolved_data["items"]
        self.assertEqual(
            [i["categoria_nombre"] for i in items],
            ["Pizzas", "Pizzas", "Pizzas"],
        )
        self.assertEqual(
            sorted({i["producto_nombre"] for i in items}),
            ["Muzzarella", "Napolitana"],
        )

    @patch.object(info_module, "_build_menu_category_resolver")
    @patch.object(info_module, "ProductoQueryService")
    def test_bebidas_selection_filters_only_bebidas(
        self, svc_cls, resolver_cls
    ) -> None:
        svc_cls.return_value.list_vendibles.return_value = self._catalog()
        resolver_instance = resolver_cls.return_value
        resolver_instance.resolve.return_value = _resolved(
            token="c3", nombre="Bebidas", categoria_id=3
        )

        processed = process_initial_informational_commerce_query(
            _db(),
            _session(id_comercio=7),
            _classified(IntentName.VER_MENU, "qué bebidas están disponibles"),
        )

        items = processed.resolved_data["items"]
        self.assertEqual([i["categoria_nombre"] for i in items], ["Bebidas"])
        self.assertEqual(items[0]["producto_nombre"], "Coca-Cola")

    @patch.object(info_module, "_build_menu_category_resolver")
    @patch.object(info_module, "ProductoQueryService")
    def test_no_selection_keeps_full_menu_byte_for_byte(
        self, svc_cls, resolver_cls
    ) -> None:
        svc_cls.return_value.list_vendibles.return_value = self._catalog()
        resolver_instance = resolver_cls.return_value
        resolver_instance.resolve.return_value = _resolved(selected=None)

        processed = process_initial_informational_commerce_query(
            _db(),
            _session(id_comercio=7),
            _classified(IntentName.VER_MENU, "qué pizzas hay"),
        )

        self.assertEqual(processed.status, "executed")
        self.assertNotIn("categoria_nombre", processed.resolved_data)
        self.assertEqual(len(processed.resolved_data["items"]), 6)

    @patch.object(info_module, "_build_menu_category_resolver")
    @patch.object(info_module, "ProductoQueryService")
    def test_transport_failure_keeps_full_menu(
        self, svc_cls, resolver_cls
    ) -> None:
        from backend.llm.menu_category_resolver import MenuCategoryResolution

        svc_cls.return_value.list_vendibles.return_value = self._catalog()
        resolver_instance = resolver_cls.return_value
        resolver_instance.resolve.return_value = MenuCategoryResolution(
            selected=None,
            failure_class="transport",
            attempted=True,
            candidate_count=3,
            latency_ms=10,
            template_version="menu-category-resolver/v1.0.0",
            template_fingerprint="fp",
            model=None,
        )

        processed = process_initial_informational_commerce_query(
            _db(),
            _session(id_comercio=7),
            _classified(IntentName.VER_MENU, "qué pizzas hay"),
        )

        self.assertEqual(processed.status, "executed")
        self.assertNotIn("categoria_nombre", processed.resolved_data)
        self.assertEqual(len(processed.resolved_data["items"]), 6)

    @patch.object(info_module, "_build_menu_category_resolver")
    @patch.object(info_module, "ProductoQueryService")
    def test_catalog_is_loaded_only_once(self, svc_cls, resolver_cls) -> None:
        svc_cls.return_value.list_vendibles.return_value = self._catalog()
        resolver_instance = resolver_cls.return_value
        resolver_instance.resolve.return_value = _resolved(selected=None)

        process_initial_informational_commerce_query(
            _db(),
            _session(id_comercio=7),
            _classified(IntentName.VER_MENU, "qué pizzas hay"),
        )

        svc_cls.return_value.list_vendibles.assert_called_once_with(7)

    @patch.object(info_module, "_build_menu_category_resolver")
    @patch.object(info_module, "ProductoQueryService")
    def test_isolation_between_comercios(self, svc_cls, resolver_cls) -> None:
        svc_cls.return_value.list_vendibles.return_value = self._catalog()
        resolver_instance = resolver_cls.return_value
        resolver_instance.resolve.return_value = _resolved(
            token="c1", nombre="Pizzas", categoria_id=1
        )

        process_initial_informational_commerce_query(
            _db(),
            _session(id_comercio=99),
            _classified(IntentName.VER_MENU, "qué pizzas hay"),
        )

        svc_cls.return_value.list_vendibles.assert_called_once_with(99)
        args, _ = resolver_instance.resolve.call_args
        sent_candidates = args[1]
        for candidate in sent_candidates:
            self.assertNotEqual(candidate.categoria_id, 99)

    @patch.object(info_module, "_build_menu_category_resolver")
    @patch.object(info_module, "ProductoQueryService")
    def test_token_name_mismatch_falls_back_to_full_menu(
        self, svc_cls, resolver_cls
    ) -> None:
        svc_cls.return_value.list_vendibles.return_value = self._catalog()
        resolver_instance = resolver_cls.return_value
        resolver_instance.resolve.return_value = _resolved(selected=None)

        processed = process_initial_informational_commerce_query(
            _db(),
            _session(id_comercio=7),
            _classified(IntentName.VER_MENU, "qué pizzas hay"),
        )

        self.assertEqual(processed.status, "executed")
        self.assertNotIn("categoria_nombre", processed.resolved_data)

    @patch.object(info_module, "_build_menu_category_resolver")
    @patch.object(info_module, "ProductoQueryService")
    def test_does_not_mutate_session_or_pending(self, svc_cls, resolver_cls) -> None:
        svc_cls.return_value.list_vendibles.return_value = self._catalog()
        resolver_instance = resolver_cls.return_value
        resolver_instance.resolve.return_value = _resolved(
            token="c1", nombre="Pizzas", categoria_id=1
        )

        session = _session(id_comercio=7)
        session.pending_intents = {"existing": "value"}
        snapshot_pending = dict(session.pending_intents)
        snapshot_context = session.context_type

        process_initial_informational_commerce_query(
            _db(),
            session,
            _classified(IntentName.VER_MENU, "qué pizzas hay"),
        )

        self.assertEqual(session.pending_intents, snapshot_pending)
        self.assertEqual(session.context_type, snapshot_context)

    @patch.object(info_module, "_build_menu_category_resolver")
    @patch.object(info_module, "ProductoQueryService")
    def test_oversized_candidate_count_skips_resolver(
        self, svc_cls, resolver_cls
    ) -> None:
        cats = []
        products = []
        for index in range(1, 25):
            cat = _categoria(f"Categoria {index}", orden=index)
            cat.id = index
            cats.append(cat)
            pres = _presentacion(f"C{index}", f"Pres {index}")
            products.append(
                _producto(
                    id_=index,
                    nombre=f"Prod {index}",
                    categoria=cat,
                    presentaciones=[
                        _producto_presentacion(
                            id_=index * 10, presentacion=pres
                        )
                    ],
                )
            )
        svc_cls.return_value.list_vendibles.return_value = products
        resolver_instance = resolver_cls.return_value

        processed = process_initial_informational_commerce_query(
            _db(),
            _session(id_comercio=7),
            _classified(IntentName.VER_MENU, "qué pizzas hay"),
        )

        resolver_instance.resolve.assert_not_called()
        self.assertEqual(processed.status, "executed")
        self.assertNotIn("categoria_nombre", processed.resolved_data)

    @patch.object(info_module, "_build_menu_category_resolver")
    @patch.object(info_module, "ProductoQueryService")
    def test_no_categories_skips_resolver(self, svc_cls, resolver_cls) -> None:
        products = []
        for index in range(1, 3):
            pres = _presentacion(f"C{index}", f"Pres {index}")
            product = _producto(
                id_=index,
                nombre=f"Prod {index}",
                categoria=None,
                presentaciones=[
                    _producto_presentacion(id_=index * 10, presentacion=pres)
                ],
            )
            products.append(product)
        svc_cls.return_value.list_vendibles.return_value = products
        resolver_instance = resolver_cls.return_value

        processed = process_initial_informational_commerce_query(
            _db(),
            _session(id_comercio=7),
            _classified(IntentName.VER_MENU, "qué pizzas hay"),
        )

        resolver_instance.resolve.assert_not_called()
        self.assertEqual(processed.status, "executed")

    def test_does_not_call_commit_or_rollback(self) -> None:
        db = _db()
        with patch.object(info_module, "ProductoQueryService") as svc_cls:
            svc_cls.return_value.list_vendibles.return_value = []
            process_initial_informational_commerce_query(
                db,
                _session(id_comercio=7),
                _classified(IntentName.VER_MENU, "menu"),
            )
        db.commit.assert_not_called()
        db.rollback.assert_not_called()
        db.flush.assert_not_called()
        db.begin.assert_not_called()


class ProcessInitialMenuCategoryIdentityTest(unittest.TestCase):
    """Focused tests for the backend category-identity contract.

    The orchestration must:

    * filter in-memory items by ``categoria_id`` from the revalidated
      candidate, never by ``categoria_nombre`` alone;
    * honour the exact ``(token, nombre)`` match — an unknown token
      or a token whose companion name does not belong to it falls
      back to the full menu;
    * keep ``categoria_id`` out of ``resolved_data``,
      :class:`ProcessedIntent` and the rendered customer response;
    * never include ``categoria_id`` in the LLM prompt.

    These tests do NOT mock the resolver's internal ``_match_selection``:
    they feed a controlled ``MenuCategoryResolution`` into the
    orchestration and observe the deterministic backend behaviour.
    """

    def _homonymous_catalog(self) -> list:
        """Catalog with two categories sharing the same ``nombre``
        (``"Promos"``) but distinct ``categoria_id`` values (10 and
        11). Each category owns its own sellable product so a
        name-based filter would mix them.
        """
        cat_promos_a = _categoria("Promos", orden=1)
        cat_promos_a.id = 10
        cat_promos_b = _categoria("Promos", orden=2)
        cat_promos_b.id = 11

        pres_a = _presentacion("PA", "Unidad")
        pres_b = _presentacion("PB", "Unidad")

        producto_a = _producto(
            id_=1,
            nombre="Combo A",
            categoria=cat_promos_a,
            presentaciones=[
                _producto_presentacion(id_=101, presentacion=pres_a),
            ],
        )
        producto_b = _producto(
            id_=2,
            nombre="Combo B",
            categoria=cat_promos_b,
            presentaciones=[
                _producto_presentacion(id_=102, presentacion=pres_b),
            ],
        )
        return [producto_a, producto_b]

    def _three_category_catalog(self) -> list:
        """Three distinct categories: Pizzas, Empanadas, Bebidas."""
        cat_pizzas = _categoria("Pizzas", orden=1)
        cat_pizzas.id = 1
        cat_empanadas = _categoria("Empanadas", orden=2)
        cat_empanadas.id = 2
        cat_bebidas = _categoria("Bebidas", orden=3)
        cat_bebidas.id = 3

        pres_pi = _presentacion("PI", "Individual")
        pres_ec = _presentacion("EC", "Unidad")
        pres_bc = _presentacion("BC", "Botella")

        pizza = _producto(
            id_=1,
            nombre="Muzzarella",
            categoria=cat_pizzas,
            presentaciones=[
                _producto_presentacion(id_=10, presentacion=pres_pi),
            ],
        )
        empanada = _producto(
            id_=2,
            nombre="Carne",
            categoria=cat_empanadas,
            presentaciones=[
                _producto_presentacion(id_=20, presentacion=pres_ec),
            ],
        )
        bebida = _producto(
            id_=3,
            nombre="Coca-Cola",
            categoria=cat_bebidas,
            presentaciones=[
                _producto_presentacion(id_=30, presentacion=pres_bc),
            ],
        )
        return [pizza, empanada, bebida]

    @patch.object(info_module, "_build_menu_category_resolver")
    @patch.object(info_module, "ProductoQueryService")
    def test_homonymous_categories_filter_by_categoria_id_not_name(
        self, svc_cls, resolver_factory
    ) -> None:
        svc_cls.return_value.list_vendibles.return_value = (
            self._homonymous_catalog()
        )
        resolver_instance = resolver_factory.return_value
        resolver_instance.resolve.return_value = _resolved(
            token="c1",
            nombre="Promos",
            categoria_id=10,
            candidate_count=2,
        )

        processed = process_initial_informational_commerce_query(
            _db(),
            _session(id_comercio=7),
            _classified(IntentName.VER_MENU, "qué promos hay"),
        )

        self.assertEqual(processed.intent, "ver_menu")
        self.assertEqual(processed.status, "executed")
        self.assertEqual(
            processed.resolved_data["categoria_nombre"], "Promos"
        )
        items = processed.resolved_data["items"]
        self.assertEqual(
            [(item["producto_nombre"], item["categoria_nombre"]) for item in items],
            [("Combo A", "Promos")],
        )
        self.assertNotIn("categoria_id", processed.resolved_data)
        self.assertNotIn("token", processed.resolved_data)
        for item in items:
            self.assertNotIn("categoria_id", item)
            self.assertNotIn("token", item)

        args, _ = resolver_instance.resolve.call_args
        sent_candidates = args[1]
        sent_tokens = {c.token: c.categoria_id for c in sent_candidates}
        self.assertEqual(sent_tokens, {"c1": 10, "c2": 11})
        for sent in sent_candidates:
            self.assertIn(sent.token, {"c1", "c2"})

    @patch.object(info_module, "_build_menu_category_resolver")
    @patch.object(info_module, "ProductoQueryService")
    def test_unknown_token_falls_back_to_full_menu(
        self, svc_cls, resolver_factory
    ) -> None:
        svc_cls.return_value.list_vendibles.return_value = (
            self._three_category_catalog()
        )
        resolver_instance = resolver_factory.return_value
        resolver_instance.resolve.return_value = _resolved(
            token="c99",
            nombre="Pizzas",
            categoria_id=1,
            candidate_count=3,
        )

        processed = process_initial_informational_commerce_query(
            _db(),
            _session(id_comercio=7),
            _classified(IntentName.VER_MENU, "qué pizzas hay"),
        )

        self.assertEqual(processed.status, "executed")
        self.assertNotIn("categoria_nombre", processed.resolved_data)
        self.assertNotIn("categoria_id", processed.resolved_data)
        nombres = [
            item["categoria_nombre"]
            for item in processed.resolved_data["items"]
        ]
        self.assertEqual(
            sorted({n for n in nombres if n}),
            ["Bebidas", "Empanadas", "Pizzas"],
        )

    @patch.object(info_module, "_build_menu_category_resolver")
    @patch.object(info_module, "ProductoQueryService")
    def test_inconsistent_token_nombre_falls_back_to_full_menu(
        self, svc_cls, resolver_factory
    ) -> None:
        svc_cls.return_value.list_vendibles.return_value = (
            self._three_category_catalog()
        )
        resolver_instance = resolver_factory.return_value
        resolver_instance.resolve.return_value = _resolved(
            token="c1",
            nombre="Empanadas",
            categoria_id=1,
            candidate_count=3,
        )

        processed = process_initial_informational_commerce_query(
            _db(),
            _session(id_comercio=7),
            _classified(IntentName.VER_MENU, "qué pizzas hay"),
        )

        self.assertEqual(processed.status, "executed")
        self.assertNotIn("categoria_nombre", processed.resolved_data)
        self.assertNotIn("categoria_id", processed.resolved_data)
        nombres = [
            item["categoria_nombre"]
            for item in processed.resolved_data["items"]
        ]
        self.assertEqual(
            sorted({n for n in nombres if n}),
            ["Bebidas", "Empanadas", "Pizzas"],
        )

    @patch.object(info_module, "_build_menu_category_resolver")
    @patch.object(info_module, "ProductoQueryService")
    def test_resolution_without_selected_falls_back_to_full_menu(
        self, svc_cls, resolver_factory
    ) -> None:
        svc_cls.return_value.list_vendibles.return_value = (
            self._three_category_catalog()
        )
        resolver_instance = resolver_factory.return_value
        resolver_instance.resolve.return_value = _resolved(selected=None)

        processed = process_initial_informational_commerce_query(
            _db(),
            _session(id_comercio=7),
            _classified(IntentName.VER_MENU, "qué pizzas hay"),
        )

        self.assertEqual(processed.status, "executed")
        self.assertNotIn("categoria_nombre", processed.resolved_data)
        self.assertNotIn("categoria_id", processed.resolved_data)

    @patch.object(info_module, "_build_menu_category_resolver")
    @patch.object(info_module, "ProductoQueryService")
    def test_resolution_with_forged_categoria_id_falls_back_to_full_menu(
        self, svc_cls, resolver_factory
    ) -> None:
        """The resolver's internal match already filters unknown
        combinations, but the orchestration must NOT trust a
        resolution whose ``selected.categoria_id`` disagrees with
        the in-memory candidate list either — this guards against a
        tampered or stubbed resolver that bypasses the internal
        match."""
        svc_cls.return_value.list_vendibles.return_value = (
            self._three_category_catalog()
        )
        resolver_instance = resolver_factory.return_value
        resolver_instance.resolve.return_value = _resolved(
            token="c1",
            nombre="Pizzas",
            categoria_id=999,
            candidate_count=3,
        )

        processed = process_initial_informational_commerce_query(
            _db(),
            _session(id_comercio=7),
            _classified(IntentName.VER_MENU, "qué pizzas hay"),
        )

        self.assertEqual(processed.status, "executed")
        self.assertNotIn("categoria_nombre", processed.resolved_data)
        self.assertNotIn("categoria_id", processed.resolved_data)
        nombres = [
            item["categoria_nombre"]
            for item in processed.resolved_data["items"]
        ]
        self.assertEqual(
            sorted({n for n in nombres if n}),
            ["Bebidas", "Empanadas", "Pizzas"],
        )

    @patch.object(info_module, "_build_menu_category_resolver")
    @patch.object(info_module, "ProductoQueryService")
    def test_resolved_data_and_response_never_expose_categoria_id(
        self, svc_cls, resolver_factory
    ) -> None:
        svc_cls.return_value.list_vendibles.return_value = (
            self._homonymous_catalog()
        )
        resolver_instance = resolver_factory.return_value
        resolver_instance.resolve.return_value = _resolved(
            token="c2",
            nombre="Promos",
            categoria_id=11,
            candidate_count=2,
        )

        processed = process_initial_informational_commerce_query(
            _db(),
            _session(id_comercio=7),
            _classified(IntentName.VER_MENU, "qué promos hay"),
        )

        resolved_serialized = repr(processed.resolved_data)
        self.assertNotIn("10", resolved_serialized)
        self.assertNotIn("11", resolved_serialized)
        self.assertNotIn("categoria_id", resolved_serialized)
        self.assertNotIn("token", resolved_serialized)
        for item in processed.resolved_data["items"]:
            self.assertNotIn("categoria_id", repr(item))
            self.assertNotIn("token", repr(item))

        rendered = build_informational_commerce_response(
            _db(), _session(), processed
        )
        self.assertNotIn("10", rendered.message)
        self.assertNotIn("11", rendered.message)
        self.assertNotIn("categoria_id", rendered.message)
        self.assertNotIn("token", rendered.message)
        self.assertIn("Promos disponibles:", rendered.message)

        args, _ = resolver_instance.resolve.call_args
        source_text = args[0]
        sent_candidates = args[1]
        from backend.diagnostics.menu_category_prompt_template import (
            build_menu_category_prompt,
        )

        rendered_prompt = build_menu_category_prompt(
            source_text,
            [{"token": c.token, "nombre": c.nombre} for c in sent_candidates],
        )
        self.assertNotIn("10", rendered_prompt)
        self.assertNotIn("11", rendered_prompt)
        self.assertNotIn("categoria_id", rendered_prompt)


class ProcessInitialConsultarProductoTest(unittest.TestCase):
    def _setup(self, svc_cls):
        cat = _categoria("Pizzas")
        pres_individual = _presentacion("PI", "Individual")
        pres_grande = _presentacion("PG", "Grande")
        muzzarella = _producto(
            id_=1,
            nombre="Pizza Muzzarella",
            categoria=cat,
            presentaciones=[
                _producto_presentacion(id_=10, presentacion=pres_individual),
                _producto_presentacion(id_=11, presentacion=pres_grande),
            ],
        )
        especial = _producto(
            id_=2,
            nombre="Pizza Especial",
            categoria=cat,
            presentaciones=[
                _producto_presentacion(id_=20, presentacion=pres_individual),
            ],
        )
        svc_cls.return_value.list_vendibles.return_value = [muzzarella, especial]

    @patch.object(info_module, "ProductoQueryService")
    def test_unique_match_returns_product_detail(self, svc_cls) -> None:
        self._setup(svc_cls)

        processed = process_initial_informational_commerce_query(
            _db(),
            _session(id_comercio=7),
            _classified(IntentName.CONSULTAR_PRODUCTO, "quiero la pizza muzzarella"),
        )

        self.assertEqual(processed.intent, "consultar_producto")
        self.assertEqual(processed.status, "executed")
        self.assertEqual(processed.resolved_data["producto_nombre"], "Pizza Muzzarella")
        self.assertEqual(
            [p["presentacion_codigo"] for p in processed.resolved_data["presentaciones"]],
            ["PI", "PG"],
        )

    @patch.object(info_module, "ProductoQueryService")
    def test_ambiguous_match_returns_clarification(self, svc_cls) -> None:
        self._setup(svc_cls)

        processed = process_initial_informational_commerce_query(
            _db(),
            _session(id_comercio=7),
            _classified(
                IntentName.CONSULTAR_PRODUCTO,
                "dame la pizza muzzarella o la pizza especial",
            ),
        )

        self.assertEqual(processed.intent, "consultar_producto")
        self.assertEqual(processed.status, "rejected")
        self.assertEqual(processed.resolved_data["reason"], "ambiguous")
        nombres = [op["producto_nombre"] for op in processed.resolved_data["opciones"]]
        self.assertIn("Pizza Muzzarella", nombres)
        self.assertIn("Pizza Especial", nombres)

    @patch.object(info_module, "ProductoQueryService")
    def test_no_match_returns_fixed_guidance(self, svc_cls) -> None:
        self._setup(svc_cls)

        processed = process_initial_informational_commerce_query(
            _db(),
            _session(id_comercio=7),
            _classified(IntentName.CONSULTAR_PRODUCTO, "quiero un sushi"),
        )

        self.assertEqual(processed.intent, "consultar_producto")
        self.assertEqual(processed.status, "rejected")
        self.assertEqual(processed.resolved_data["reason"], "no_match")
        self.assertTrue(processed.resolved_data["opciones"])

    @patch.object(info_module, "ProductoQueryService")
    def test_generic_single_token_does_not_select_any_product(
        self, svc_cls
    ) -> None:
        self._setup(svc_cls)

        processed = process_initial_informational_commerce_query(
            _db(),
            _session(id_comercio=7),
            _classified(IntentName.CONSULTAR_PRODUCTO, "de"),
        )

        self.assertEqual(processed.intent, "consultar_producto")
        self.assertEqual(processed.status, "rejected")
        self.assertEqual(processed.resolved_data["reason"], "no_match")
        nombres = [op["producto_nombre"] for op in processed.resolved_data["opciones"]]
        self.assertIn("Pizza Muzzarella", nombres)
        self.assertIn("Pizza Especial", nombres)

    @patch.object(info_module, "ProductoQueryService")
    def test_isolated_presentation_token_does_not_select_product(
        self, svc_cls
    ) -> None:
        cat = _categoria("Pizzas")
        pres_pizza_grande = _presentacion("PG", "Pizza Grande")
        muzzarella = _producto(
            id_=1,
            nombre="Pizza Muzzarella",
            categoria=cat,
            presentaciones=[
                _producto_presentacion(id_=11, presentacion=pres_pizza_grande),
            ],
        )
        svc_cls.return_value.list_vendibles.return_value = [muzzarella]

        processed = process_initial_informational_commerce_query(
            _db(),
            _session(id_comercio=7),
            _classified(IntentName.CONSULTAR_PRODUCTO, "grande"),
        )

        self.assertEqual(processed.intent, "consultar_producto")
        self.assertEqual(processed.status, "rejected")
        self.assertEqual(processed.resolved_data["reason"], "no_match")
        nombres = [op["producto_nombre"] for op in processed.resolved_data["opciones"]]
        self.assertEqual(nombres, ["Pizza Muzzarella"])

    @patch.object(info_module, "ProductoQueryService")
    def test_isolated_presentation_token_does_not_select_product_when_name_matches(
        self, svc_cls
    ) -> None:
        cat = _categoria("Pizzas")
        pres_pizza_grande = _presentacion("PG", "Pizza Grande")
        muzzarella = _producto(
            id_=1,
            nombre="Muzzarella",
            categoria=cat,
            presentaciones=[
                _producto_presentacion(id_=11, presentacion=pres_pizza_grande),
            ],
        )
        svc_cls.return_value.list_vendibles.return_value = [muzzarella]

        processed = process_initial_informational_commerce_query(
            _db(),
            _session(id_comercio=7),
            _classified(IntentName.CONSULTAR_PRODUCTO, "grande"),
        )

        self.assertEqual(processed.intent, "consultar_producto")
        self.assertEqual(processed.status, "rejected")
        self.assertEqual(processed.resolved_data["reason"], "no_match")

    @patch.object(info_module, "ProductoQueryService")
    def test_single_token_name_does_not_select_partial_match_product(
        self, svc_cls
    ) -> None:
        self._setup(svc_cls)

        processed = process_initial_informational_commerce_query(
            _db(),
            _session(id_comercio=7),
            _classified(IntentName.CONSULTAR_PRODUCTO, "muzzarella"),
        )

        self.assertEqual(processed.intent, "consultar_producto")
        self.assertEqual(processed.status, "rejected")
        self.assertEqual(processed.resolved_data["reason"], "no_match")

    @patch.object(info_module, "ProductoQueryService")
    def test_complete_product_name_returns_detail(self, svc_cls) -> None:
        self._setup(svc_cls)

        processed = process_initial_informational_commerce_query(
            _db(),
            _session(id_comercio=7),
            _classified(
                IntentName.CONSULTAR_PRODUCTO, "pizza muzzarella"
            ),
        )

        self.assertEqual(processed.status, "executed")
        self.assertEqual(
            processed.resolved_data["producto_nombre"], "Pizza Muzzarella"
        )
        self.assertEqual(
            [p["presentacion_codigo"] for p in processed.resolved_data["presentaciones"]],
            ["PI", "PG"],
        )

    @patch.object(info_module, "ProductoQueryService")
    def test_complete_presentation_description_returns_detail_when_unique(
        self, svc_cls
    ) -> None:
        self._setup(svc_cls)

        processed = process_initial_informational_commerce_query(
            _db(),
            _session(id_comercio=7),
            _classified(
                IntentName.CONSULTAR_PRODUCTO,
                "pizza muzzarella grande",
            ),
        )

        self.assertEqual(processed.status, "executed")
        self.assertEqual(
            processed.resolved_data["producto_nombre"], "Pizza Muzzarella"
        )

    @patch.object(info_module, "ProductoQueryService")
    def test_complete_presentation_code_returns_detail_when_unique(
        self, svc_cls
    ) -> None:
        cat = _categoria("Pizzas")
        pres_pi = _presentacion("PI", "Individual")
        pres_pg = _presentacion("PG", "Grande")
        muzzarella = _producto(
            id_=1,
            nombre="Pizza Muzzarella",
            categoria=cat,
            presentaciones=[
                _producto_presentacion(id_=10, presentacion=pres_pi),
                _producto_presentacion(id_=11, presentacion=pres_pg),
            ],
        )
        especial = _producto(
            id_=2,
            nombre="Pizza Especial",
            categoria=cat,
            presentaciones=[
                _producto_presentacion(id_=21, presentacion=pres_pi),
            ],
        )
        svc_cls.return_value.list_vendibles.return_value = [muzzarella, especial]

        processed_pi = process_initial_informational_commerce_query(
            _db(),
            _session(id_comercio=7),
            _classified(IntentName.CONSULTAR_PRODUCTO, "pg"),
        )
        self.assertEqual(processed_pi.status, "executed")
        self.assertEqual(
            processed_pi.resolved_data["producto_nombre"], "Pizza Muzzarella"
        )

        processed_pi_both = process_initial_informational_commerce_query(
            _db(),
            _session(id_comercio=7),
            _classified(IntentName.CONSULTAR_PRODUCTO, "pi"),
        )
        self.assertEqual(processed_pi_both.status, "rejected")
        self.assertEqual(processed_pi_both.resolved_data["reason"], "ambiguous")
        nombres = [
            op["producto_nombre"]
            for op in processed_pi_both.resolved_data["opciones"]
        ]
        self.assertIn("Pizza Muzzarella", nombres)
        self.assertIn("Pizza Especial", nombres)

    @patch.object(info_module, "ProductoQueryService")
    def test_multiple_complete_matches_remain_ambiguous(self, svc_cls) -> None:
        self._setup(svc_cls)

        processed = process_initial_informational_commerce_query(
            _db(),
            _session(id_comercio=7),
            _classified(
                IntentName.CONSULTAR_PRODUCTO,
                "pizza muzzarella y pizza especial",
            ),
        )

        self.assertEqual(processed.intent, "consultar_producto")
        self.assertEqual(processed.status, "rejected")
        self.assertEqual(processed.resolved_data["reason"], "ambiguous")
        nombres = [op["producto_nombre"] for op in processed.resolved_data["opciones"]]
        self.assertIn("Pizza Muzzarella", nombres)
        self.assertIn("Pizza Especial", nombres)

    @patch.object(info_module, "ProductoQueryService")
    def test_complete_name_wins_over_shared_presentation_token(
        self, svc_cls
    ) -> None:
        """Production regression: shared ``lata`` presentation must not
        add candidates from other beverages when ``Cerveza rubia``
        already identifies a product by complete name."""
        cat_bebidas = _categoria("Bebidas")
        cat_cervezas = _categoria("Cervezas")
        pres_lata = _presentacion("LT", "Lata")
        pres_botella = _presentacion("BT", "Botella")
        cerveza_rubia = _producto(
            id_=1,
            nombre="Cerveza rubia",
            categoria=cat_cervezas,
            presentaciones=[
                _producto_presentacion(id_=11, presentacion=pres_lata),
                _producto_presentacion(id_=12, presentacion=pres_botella),
            ],
        )
        cerveza_negra = _producto(
            id_=2,
            nombre="Cerveza negra",
            categoria=cat_cervezas,
            presentaciones=[
                _producto_presentacion(id_=21, presentacion=pres_botella),
            ],
        )
        gaseosa_cola = _producto(
            id_=3,
            nombre="Gaseosa Cola",
            categoria=cat_bebidas,
            presentaciones=[
                _producto_presentacion(id_=31, presentacion=pres_lata),
                _producto_presentacion(id_=32, presentacion=pres_botella),
            ],
        )
        jugo_naranja = _producto(
            id_=4,
            nombre="Jugo de naranja",
            categoria=cat_bebidas,
            presentaciones=[
                _producto_presentacion(id_=41, presentacion=pres_lata),
            ],
        )
        svc_cls.return_value.list_vendibles.return_value = [
            cerveza_rubia,
            cerveza_negra,
            gaseosa_cola,
            jugo_naranja,
        ]

        processed = process_initial_informational_commerce_query(
            _db(),
            _session(id_comercio=7),
            _classified(
                IntentName.CONSULTAR_PRODUCTO,
                "Cuánto sale la cerveza rubia en lata?",
            ),
        )

        self.assertEqual(processed.intent, "consultar_producto")
        self.assertEqual(processed.status, "executed")
        self.assertNotEqual(processed.resolved_data.get("reason"), "ambiguous")
        self.assertEqual(
            processed.resolved_data["producto_nombre"], "Cerveza rubia"
        )
        self.assertEqual(
            processed.resolved_data["producto_id"], cerveza_rubia.id
        )
        self.assertEqual(
            [p["presentacion_codigo"] for p in processed.resolved_data["presentaciones"]],
            ["LT", "BT"],
        )

    @patch.object(info_module, "ProductoQueryService")
    def test_does_not_mutate_pending_or_session(self, svc_cls) -> None:
        self._setup(svc_cls)
        session = _session(id_comercio=7)
        session.pending_intents = {"k": "v"}
        snapshot_pending = dict(session.pending_intents)
        snapshot_context = session.context_type

        process_initial_informational_commerce_query(
            _db(),
            session,
            _classified(IntentName.CONSULTAR_PRODUCTO, "quiero la pizza muzzarella"),
        )

        self.assertEqual(session.pending_intents, snapshot_pending)
        self.assertEqual(session.context_type, snapshot_context)

    @patch.object(info_module, "ProductoQueryService")
    def test_unique_match_includes_precio_for_each_presentacion(
        self, svc_cls
    ) -> None:
        from decimal import Decimal

        cat = _categoria("Pizzas")
        pres_individual = _presentacion("PI", "Individual")
        pres_grande = _presentacion("PG", "Grande")
        muzzarella = _producto(
            id_=1,
            nombre="Pizza Muzzarella",
            categoria=cat,
            presentaciones=[
                _producto_presentacion(
                    id_=10,
                    presentacion=pres_individual,
                    precios=[_precio(Decimal("1500.00"))],
                ),
                _producto_presentacion(
                    id_=11,
                    presentacion=pres_grande,
                    precios=[_precio(Decimal("2800.50"))],
                ),
            ],
        )
        svc_cls.return_value.list_vendibles.return_value = [muzzarella]

        processed = process_initial_informational_commerce_query(
            _db(),
            _session(id_comercio=7),
            _classified(IntentName.CONSULTAR_PRODUCTO, "quiero la pizza muzzarella"),
        )

        self.assertEqual(processed.status, "executed")
        presentaciones = processed.resolved_data["presentaciones"]
        self.assertEqual(
            [(p["presentacion_codigo"], p.get("precio")) for p in presentaciones],
            [("PI", "1500.00"), ("PG", "2800.50")],
        )

    @patch.object(info_module, "ProductoQueryService")
    def test_unique_match_omits_precio_when_presentacion_has_no_valid_price(
        self, svc_cls
    ) -> None:
        cat = _categoria("Pizzas")
        pres_sin_precio = _presentacion("PI", "Individual")
        pres_con_precio = _presentacion("PG", "Grande")
        muzzarella = _producto(
            id_=1,
            nombre="Pizza Muzzarella",
            categoria=cat,
            presentaciones=[
                _producto_presentacion(id_=10, presentacion=pres_sin_precio, precios=[]),
                _producto_presentacion(
                    id_=11,
                    presentacion=pres_con_precio,
                    precios=[_precio(100)],
                ),
            ],
        )
        svc_cls.return_value.list_vendibles.return_value = [muzzarella]

        processed = process_initial_informational_commerce_query(
            _db(),
            _session(id_comercio=7),
            _classified(IntentName.CONSULTAR_PRODUCTO, "quiero la pizza muzzarella"),
        )

        presentaciones = processed.resolved_data["presentaciones"]
        self.assertNotIn("precio", presentaciones[0])
        self.assertEqual(presentaciones[1]["precio"], "100.00")

    @patch.object(info_module, "ProductoQueryService")
    def test_unique_match_ignores_negative_prices(self, svc_cls) -> None:
        from decimal import Decimal

        cat = _categoria("Pizzas")
        pres = _presentacion("PI", "Individual")
        muzzarella = _producto(
            id_=1,
            nombre="Pizza Muzzarella",
            categoria=cat,
            presentaciones=[
                _producto_presentacion(
                    id_=10,
                    presentacion=pres,
                    precios=[_precio(Decimal("-1.00")), _precio(Decimal("900.00"))],
                ),
            ],
        )
        svc_cls.return_value.list_vendibles.return_value = [muzzarella]

        processed = process_initial_informational_commerce_query(
            _db(),
            _session(id_comercio=7),
            _classified(IntentName.CONSULTAR_PRODUCTO, "quiero la pizza muzzarella"),
        )

        self.assertEqual(
            processed.resolved_data["presentaciones"][0]["precio"], "900.00"
        )


class ProcessInitialPaymentDeliveryTest(unittest.TestCase):
    @patch.object(info_module, "MetodoEntregaService")
    @patch.object(info_module, "MediosPagoService")
    def test_lists_only_active_payment_options_for_comercio(
        self, mp_svc_cls, me_svc_cls
    ) -> None:
        mp_svc_cls.return_value.list_active_for_comercio.return_value = [
            _medio_pago(1, "EF", "Efectivo"),
            _medio_pago(2, "MP", "Mercado Pago"),
        ]
        me_svc_cls.return_value.list_active_for_comercio.return_value = []

        processed = process_initial_informational_commerce_query(
            _db(),
            _session(id_comercio=7),
            _classified(IntentName.VER_METODOS_DE_PAGO, "medios de pago"),
        )

        self.assertEqual(processed.intent, "ver_metodos_de_pago")
        self.assertEqual(processed.status, "executed")
        opciones = processed.resolved_data["opciones"]
        self.assertEqual(
            opciones,
            [
                {"codigo": "EF", "descripcion": "Efectivo"},
                {"codigo": "MP", "descripcion": "Mercado Pago"},
            ],
        )
        mp_svc_cls.return_value.list_active_for_comercio.assert_called_once_with(7)

    @patch.object(info_module, "MetodoEntregaService")
    @patch.object(info_module, "MediosPagoService")
    def test_empty_payment_options_returns_rejection(
        self, mp_svc_cls, me_svc_cls
    ) -> None:
        mp_svc_cls.return_value.list_active_for_comercio.return_value = []
        me_svc_cls.return_value.list_active_for_comercio.return_value = []

        processed = process_initial_informational_commerce_query(
            _db(),
            _session(id_comercio=7),
            _classified(IntentName.VER_METODOS_DE_PAGO, "medios de pago"),
        )

        self.assertEqual(processed.status, "rejected")
        self.assertEqual(processed.resolved_data["reason"], "no_options")

    @patch.object(info_module, "MetodoEntregaService")
    @patch.object(info_module, "MediosPagoService")
    def test_lists_active_delivery_methods_in_configured_order(
        self, mp_svc_cls, me_svc_cls
    ) -> None:
        mp_svc_cls.return_value.list_active_for_comercio.return_value = []
        me_svc_cls.return_value.list_active_for_comercio.return_value = [
            _metodo_entrega(1, "DEL", "Delivery", orden=1),
            _metodo_entrega(2, "LOC", "Retiro en local", orden=2),
        ]

        processed = process_initial_informational_commerce_query(
            _db(),
            _session(id_comercio=7),
            _classified(IntentName.VER_METODOS_DE_ENTREGA, "entrega"),
        )

        self.assertEqual(processed.intent, "ver_metodos_de_entrega")
        self.assertEqual(processed.status, "executed")
        self.assertEqual(
            [op["codigo"] for op in processed.resolved_data["opciones"]],
            ["DEL", "LOC"],
        )
        me_svc_cls.return_value.list_active_for_comercio.assert_called_once_with(7)

    @patch.object(info_module, "MetodoEntregaService")
    @patch.object(info_module, "MediosPagoService")
    def test_empty_delivery_methods_returns_rejection(
        self, mp_svc_cls, me_svc_cls
    ) -> None:
        mp_svc_cls.return_value.list_active_for_comercio.return_value = []
        me_svc_cls.return_value.list_active_for_comercio.return_value = []

        processed = process_initial_informational_commerce_query(
            _db(),
            _session(id_comercio=7),
            _classified(IntentName.VER_METODOS_DE_ENTREGA, "entrega"),
        )

        self.assertEqual(processed.status, "rejected")
        self.assertEqual(processed.resolved_data["reason"], "no_options")


class ProcessInitialDomicilioTest(unittest.TestCase):
    @patch.object(info_module, "ConfiguracionComercioService")
    def test_renders_address_from_session_comercio(self, svc_cls) -> None:
        svc_cls.return_value.get_by_id.return_value = _comercio(
            id_=7,
            calle="Av. Siempre Viva",
            numero="742",
            piso="1B",
            localidad="Springfield",
            provincia="Buenos Aires",
            codigo_postal="1000",
        )

        processed = process_initial_informational_commerce_query(
            _db(),
            _session(id_comercio=7),
            _classified(IntentName.CONSULTAR_DOMICILIO_COMERCIO, "direccion"),
        )

        self.assertEqual(processed.intent, "consultar_domicilio_comercio")
        self.assertEqual(processed.status, "executed")
        svc_cls.return_value.get_by_id.assert_called_once_with(7)
        self.assertEqual(processed.resolved_data["calle"], "Av. Siempre Viva")
        self.assertEqual(processed.resolved_data["piso_departamento"], "1B")

    @patch.object(info_module, "ConfiguracionComercioService")
    def test_missing_comercio_propagates_as_technical_failure(self, svc_cls) -> None:
        svc_cls.return_value.get_by_id.side_effect = ComercioNotFound(7)

        with self.assertRaises(ComercioNotFound):
            process_initial_informational_commerce_query(
                _db(),
                _session(id_comercio=7),
                _classified(
                    IntentName.CONSULTAR_DOMICILIO_COMERCIO, "direccion"
                ),
            )


class ProcessInitialHorariosTest(unittest.TestCase):
    @patch.object(info_module, "ComercioService")
    def test_returns_fixed_hours_not_configured_response(self, svc_cls) -> None:
        svc_cls.return_value.get_by_id.return_value = MagicMock(name="Comercio")

        processed = process_initial_informational_commerce_query(
            _db(),
            _session(id_comercio=7),
            _classified(IntentName.CONSULTAR_HORARIOS_COMERCIO, "horarios"),
        )

        self.assertEqual(processed.intent, "consultar_horarios_comercio")
        self.assertEqual(processed.status, "executed")
        self.assertEqual(processed.resolved_data["reason"], "not_configured")
        svc_cls.return_value.get_by_id.assert_called_once_with(7)

    def test_missing_session_comercio_propagates_without_inventing_schedule(self) -> None:
        with self.assertRaises(ComercioNotFound):
            process_initial_informational_commerce_query(
                _db(),
                _session(id_comercio=None),
                _classified(
                    IntentName.CONSULTAR_HORARIOS_COMERCIO, "horarios"
                ),
            )

    @patch.object(info_module, "ComercioService")
    def test_nonexistent_comercio_propagates_technical_failure(
        self, svc_cls
    ) -> None:
        svc_cls.return_value.get_by_id.side_effect = ComercioNotFound(7)

        with self.assertRaises(ComercioNotFound):
            process_initial_informational_commerce_query(
                _db(),
                _session(id_comercio=7),
                _classified(
                    IntentName.CONSULTAR_HORARIOS_COMERCIO, "horarios"
                ),
            )


class ProcessInitialTechnicalFailureTest(unittest.TestCase):
    @patch.object(info_module, "ProductoQueryService")
    def test_repository_failure_propagates_unchanged(self, svc_cls) -> None:
        svc_cls.return_value.list_vendibles.side_effect = RuntimeError("db boom")

        with self.assertRaises(RuntimeError):
            process_initial_informational_commerce_query(
                _db(),
                _session(id_comercio=7),
                _classified(IntentName.VER_MENU, "menu"),
            )

    def test_processed_intent_does_not_own_transaction(self) -> None:
        db = _db()

        with patch.object(info_module, "ProductoQueryService") as svc_cls:
            svc_cls.return_value.list_vendibles.return_value = []

            process_initial_informational_commerce_query(
                db,
                _session(id_comercio=7),
                _classified(IntentName.VER_MENU, "menu"),
            )

        db.commit.assert_not_called()
        db.rollback.assert_not_called()
        db.flush.assert_not_called()
        db.begin.assert_not_called()


class DispatcherWiringTest(unittest.TestCase):
    @patch.object(dispatcher_module, "process_initial_informational_commerce_query")
    @patch.object(dispatcher_module, "IntentClassifier")
    def test_ver_menu_routes_to_informational_module(
        self, classifier_cls, info_proc
    ) -> None:
        classifier_instance = MagicMock()
        classifier_instance.query.return_value = _build_result(
            (IntentName.VER_MENU, "menu"),
        )
        classifier_cls.return_value = classifier_instance
        info_proc.return_value = ProcessedIntent(
            intent="ver_menu",
            source_text="menu",
            status="executed",
            handler=INFORMATIONAL_COMMERCE_HANDLER,
            recognizer=INFORMATIONAL_COMMERCE_HANDLER,
            resolved_data={"items": []},
        )

        db = _db()
        session = _session()
        result = dispatch_initial_message(db, session, "menu")

        info_proc.assert_called_once_with(
            db,
            session,
            classifier_instance.query.return_value.intents[0],
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].intent, "ver_menu")
        self.assertEqual(result[0].handler, INFORMATIONAL_COMMERCE_HANDLER)

    @patch.object(dispatcher_module, "process_initial_informational_commerce_query")
    @patch.object(dispatcher_module, "IntentClassifier")
    def test_all_six_intents_route_through_dispatcher(
        self, classifier_cls, info_proc
    ) -> None:
        classifier_instance = MagicMock()
        classifier_instance.query.return_value = _build_result(
            (IntentName.VER_MENU, "menu"),
            (IntentName.CONSULTAR_PRODUCTO, "x"),
            (IntentName.VER_METODOS_DE_PAGO, "x"),
            (IntentName.VER_METODOS_DE_ENTREGA, "x"),
            (IntentName.CONSULTAR_DOMICILIO_COMERCIO, "x"),
            (IntentName.CONSULTAR_HORARIOS_COMERCIO, "x"),
        )
        classifier_cls.return_value = classifier_instance
        info_proc.side_effect = [
            ProcessedIntent(
                intent=intent_name,
                source_text="x",
                status="executed",
                handler=INFORMATIONAL_COMMERCE_HANDLER,
                recognizer=INFORMATIONAL_COMMERCE_HANDLER,
                resolved_data={},
            )
            for intent_name in (
                "ver_menu",
                "consultar_producto",
                "ver_metodos_de_pago",
                "ver_metodos_de_entrega",
                "consultar_domicilio_comercio",
                "consultar_horarios_comercio",
            )
        ]

        db = _db()
        session = _session()
        result = dispatch_initial_message(db, session, "mix")

        self.assertEqual(len(result), 6)
        self.assertEqual(info_proc.call_count, 6)
        self.assertEqual(
            [intent.intent for intent in result],
            [
                "ver_menu",
                "consultar_producto",
                "ver_metodos_de_pago",
                "ver_metodos_de_entrega",
                "consultar_domicilio_comercio",
                "consultar_horarios_comercio",
            ],
        )


class BuildInformationalCommerceResponseTest(unittest.TestCase):
    def test_menu_renders_deterministic_message_with_categories(self) -> None:
        items = [
            {
                "categoria_nombre": "Pizzas",
                "producto_nombre": "Muzzarella",
                "presentacion_codigo": "PI",
                "presentacion_descripcion": "Individual",
            },
            {
                "categoria_nombre": "Pizzas",
                "producto_nombre": "Muzzarella",
                "presentacion_codigo": "PG",
                "presentacion_descripcion": "Grande",
            },
            {
                "categoria_nombre": "Empanadas",
                "producto_nombre": "Carne",
                "presentacion_codigo": "EC",
                "presentacion_descripcion": "Unidad",
            },
        ]
        rendered = build_informational_commerce_response(
            _db(),
            _session(),
            ProcessedIntent(
                intent="ver_menu",
                source_text="menu",
                status="executed",
                handler=INFORMATIONAL_COMMERCE_HANDLER,
                recognizer=INFORMATIONAL_COMMERCE_HANDLER,
                resolved_data={"items": items},
            ),
        )

        self.assertEqual(rendered.intent, "ver_menu")
        self.assertEqual(rendered.status, "executed")
        self.assertIn("Menú disponible:", rendered.message)
        self.assertIn("Pizzas:", rendered.message)
        self.assertIn("- Muzzarella (PI)", rendered.message)
        self.assertIn("- Muzzarella (PG)", rendered.message)
        self.assertIn("Empanadas:", rendered.message)
        self.assertIn("- Carne (EC)", rendered.message)

    def test_empty_menu_renders_no_products_guidance(self) -> None:
        rendered = build_informational_commerce_response(
            _db(),
            _session(),
            ProcessedIntent(
                intent="ver_menu",
                source_text="menu",
                status="rejected",
                handler=INFORMATIONAL_COMMERCE_HANDLER,
                recognizer=INFORMATIONAL_COMMERCE_HANDLER,
                resolved_data={"reason": "no_items"},
            ),
        )
        self.assertEqual(rendered.status, "rejected")
        self.assertIn("no tengo productos disponibles", rendered.message)

    def test_product_detail_renders_nombre_categoria_y_presentaciones(self) -> None:
        rendered = build_informational_commerce_response(
            _db(),
            _session(),
            ProcessedIntent(
                intent="consultar_producto",
                source_text="x",
                status="executed",
                handler=INFORMATIONAL_COMMERCE_HANDLER,
                recognizer=INFORMATIONAL_COMMERCE_HANDLER,
                resolved_data={
                    "producto_nombre": "Pizza Muzzarella",
                    "categoria_nombre": "Pizzas",
                    "presentaciones": [
                        {
                            "presentacion_codigo": "PI",
                            "presentacion_descripcion": "Individual",
                        },
                    ],
                },
            ),
        )
        self.assertIn("Pizza Muzzarella", rendered.message)
        self.assertIn("Categoría: Pizzas", rendered.message)
        self.assertIn("Presentaciones:", rendered.message)
        self.assertIn("- PI (Individual)", rendered.message)

    def test_product_detail_renders_precio_when_present(self) -> None:
        rendered = build_informational_commerce_response(
            _db(),
            _session(),
            ProcessedIntent(
                intent="consultar_producto",
                source_text="x",
                status="executed",
                handler=INFORMATIONAL_COMMERCE_HANDLER,
                recognizer=INFORMATIONAL_COMMERCE_HANDLER,
                resolved_data={
                    "producto_nombre": "Pizza Muzzarella",
                    "categoria_nombre": "Pizzas",
                    "presentaciones": [
                        {
                            "presentacion_codigo": "PI",
                            "presentacion_descripcion": "Individual",
                            "precio": "1500.00",
                        },
                        {
                            "presentacion_codigo": "PG",
                            "presentacion_descripcion": "Grande",
                            "precio": "2800.50",
                        },
                    ],
                },
            ),
        )
        self.assertIn("- PI (Individual) — $1500.00", rendered.message)
        self.assertIn("- PG (Grande) — $2800.50", rendered.message)

    def test_product_detail_omits_precio_when_not_present(self) -> None:
        rendered = build_informational_commerce_response(
            _db(),
            _session(),
            ProcessedIntent(
                intent="consultar_producto",
                source_text="x",
                status="executed",
                handler=INFORMATIONAL_COMMERCE_HANDLER,
                recognizer=INFORMATIONAL_COMMERCE_HANDLER,
                resolved_data={
                    "producto_nombre": "Pizza Muzzarella",
                    "categoria_nombre": "Pizzas",
                    "presentaciones": [
                        {
                            "presentacion_codigo": "PI",
                            "presentacion_descripcion": "Individual",
                        },
                    ],
                },
            ),
        )
        self.assertIn("- PI (Individual)", rendered.message)
        self.assertNotIn("$", rendered.message)

    def test_ambiguous_product_renders_options_prompt(self) -> None:
        rendered = build_informational_commerce_response(
            _db(),
            _session(),
            ProcessedIntent(
                intent="consultar_producto",
                source_text="x",
                status="rejected",
                handler=INFORMATIONAL_COMMERCE_HANDLER,
                recognizer=INFORMATIONAL_COMMERCE_HANDLER,
                resolved_data={
                    "reason": "ambiguous",
                    "opciones": [
                        {"producto_nombre": "Pizza Muzzarella"},
                        {"producto_nombre": "Pizza Especial"},
                    ],
                },
            ),
        )
        self.assertIn("varios productos", rendered.message)
        self.assertNotIn("producto_nombre", rendered.message)

    def test_payment_options_render_with_codigo_y_descripcion(self) -> None:
        rendered = build_informational_commerce_response(
            _db(),
            _session(),
            ProcessedIntent(
                intent="ver_metodos_de_pago",
                source_text="x",
                status="executed",
                handler=INFORMATIONAL_COMMERCE_HANDLER,
                recognizer=INFORMATIONAL_COMMERCE_HANDLER,
                resolved_data={
                    "opciones": [
                        {"codigo": "EF", "descripcion": "Efectivo"},
                        {"codigo": "MP", "descripcion": "Mercado Pago"},
                    ],
                },
            ),
        )
        self.assertIn("Medios de pago disponibles:", rendered.message)
        self.assertIn("EF (Efectivo)", rendered.message)
        self.assertIn("MP (Mercado Pago)", rendered.message)
        self.assertIn(" o ", rendered.message)

    def test_empty_payment_options_render_no_options_guidance(self) -> None:
        rendered = build_informational_commerce_response(
            _db(),
            _session(),
            ProcessedIntent(
                intent="ver_metodos_de_pago",
                source_text="x",
                status="rejected",
                handler=INFORMATIONAL_COMMERCE_HANDLER,
                recognizer=INFORMATIONAL_COMMERCE_HANDLER,
                resolved_data={"reason": "no_options"},
            ),
        )
        self.assertIn("no tengo medios de pago configurados", rendered.message)

    def test_delivery_options_render_with_orden(self) -> None:
        rendered = build_informational_commerce_response(
            _db(),
            _session(),
            ProcessedIntent(
                intent="ver_metodos_de_entrega",
                source_text="x",
                status="executed",
                handler=INFORMATIONAL_COMMERCE_HANDLER,
                recognizer=INFORMATIONAL_COMMERCE_HANDLER,
                resolved_data={
                    "opciones": [
                        {"codigo": "DEL", "descripcion": "Delivery"},
                    ],
                },
            ),
        )
        self.assertIn("Métodos de entrega disponibles:", rendered.message)
        self.assertIn("DEL (Delivery)", rendered.message)

    def test_domicilio_renders_full_address(self) -> None:
        rendered = build_informational_commerce_response(
            _db(),
            _session(),
            ProcessedIntent(
                intent="consultar_domicilio_comercio",
                source_text="x",
                status="executed",
                handler=INFORMATIONAL_COMMERCE_HANDLER,
                recognizer=INFORMATIONAL_COMMERCE_HANDLER,
                resolved_data={
                    "calle": "Av. Siempre Viva",
                    "numero": "742",
                    "piso_departamento": "1B",
                    "localidad": "Springfield",
                    "provincia": "Buenos Aires",
                    "codigo_postal": "1000",
                },
            ),
        )
        self.assertIn("Av. Siempre Viva 742, 1B", rendered.message)
        self.assertIn("Springfield, Buenos Aires", rendered.message)
        self.assertIn("CP 1000", rendered.message)

    def test_horarios_renders_fixed_not_configured_message(self) -> None:
        rendered = build_informational_commerce_response(
            _db(),
            _session(),
            ProcessedIntent(
                intent="consultar_horarios_comercio",
                source_text="x",
                status="executed",
                handler=INFORMATIONAL_COMMERCE_HANDLER,
                recognizer=INFORMATIONAL_COMMERCE_HANDLER,
                resolved_data={"reason": "not_configured"},
            ),
        )
        self.assertIn("no tenemos horarios", rendered.message)
        self.assertNotIn(":00", rendered.message)
        self.assertNotIn("Lunes", rendered.message)
        self.assertNotIn("martes", rendered.message)

    def test_failed_status_renders_generic_technical_message(self) -> None:
        rendered = build_informational_commerce_response(
            _db(),
            _session(),
            ProcessedIntent(
                intent="ver_menu",
                source_text="x",
                status="failed",
                handler=INFORMATIONAL_COMMERCE_HANDLER,
                recognizer=INFORMATIONAL_COMMERCE_HANDLER,
                resolved_data={},
            ),
        )
        self.assertIn("problema técnico", rendered.message)

    def test_ver_menu_selected_category_renders_category_heading(self) -> None:
        rendered = build_informational_commerce_response(
            _db(),
            _session(),
            ProcessedIntent(
                intent="ver_menu",
                source_text="qué pizzas hay",
                status="executed",
                handler=INFORMATIONAL_COMMERCE_HANDLER,
                recognizer=INFORMATIONAL_COMMERCE_HANDLER,
                resolved_data={
                    "categoria_nombre": "Empanadas",
                    "items": [
                        {
                            "categoria_nombre": "Empanadas",
                            "producto_nombre": "Carne picante",
                            "presentacion_codigo": "EC",
                            "presentacion_descripcion": "Unidad",
                        },
                        {
                            "categoria_nombre": "Empanadas",
                            "producto_nombre": "Carne suave",
                            "presentacion_codigo": "CS",
                            "presentacion_descripcion": "Unidad",
                        },
                    ],
                },
            ),
        )

        self.assertEqual(rendered.intent, "ver_menu")
        self.assertEqual(rendered.status, "executed")
        self.assertIn("Empanadas disponibles:", rendered.message)
        self.assertIn("- Carne picante (EC)", rendered.message)
        self.assertIn("- Carne suave (CS)", rendered.message)
        self.assertNotIn("Menú disponible:", rendered.message)
        self.assertNotIn("Pizzas:", rendered.message)
        self.assertNotIn("Bebidas:", rendered.message)

    def test_ver_menu_full_menu_fallback_preserves_existing_output(self) -> None:
        items = [
            {
                "categoria_nombre": "Pizzas",
                "producto_nombre": "Muzzarella",
                "presentacion_codigo": "PI",
                "presentacion_descripcion": "Individual",
            },
            {
                "categoria_nombre": "Empanadas",
                "producto_nombre": "Carne",
                "presentacion_codigo": "EC",
                "presentacion_descripcion": "Unidad",
            },
        ]
        rendered = build_informational_commerce_response(
            _db(),
            _session(),
            ProcessedIntent(
                intent="ver_menu",
                source_text="menu",
                status="executed",
                handler=INFORMATIONAL_COMMERCE_HANDLER,
                recognizer=INFORMATIONAL_COMMERCE_HANDLER,
                resolved_data={"items": items},
            ),
        )

        self.assertIn("Menú disponible:", rendered.message)
        self.assertIn("Pizzas:", rendered.message)
        self.assertIn("Empanadas:", rendered.message)
        self.assertNotIn("Empanadas disponibles:", rendered.message)


class BuildCustomerResponsesInformationalTest(unittest.TestCase):
    @patch.object(mapper_module, "build_informational_commerce_response")
    def test_ver_menu_is_routed_through_informational_builder(
        self, info_builder
    ) -> None:
        info_builder.return_value = MagicMock(
            message="MENU", intent="ver_menu", status="executed"
        )

        responses = build_customer_responses(
            _db(),
            _session(),
            [
                ProcessedIntent(
                    intent="ver_menu",
                    source_text="x",
                    status="executed",
                    handler=INFORMATIONAL_COMMERCE_HANDLER,
                    recognizer=INFORMATIONAL_COMMERCE_HANDLER,
                    resolved_data={},
                ),
            ],
        )

        self.assertEqual(len(responses), 1)
        self.assertIs(responses[0], info_builder.return_value)
        info_builder.assert_called_once()

    @patch.object(mapper_module, "build_informational_commerce_response")
    def test_each_informational_intent_dispatches_to_builder(
        self, info_builder
    ) -> None:
        info_builder.side_effect = [
            MagicMock(message="m", intent=name, status="executed")
            for name in (
                "ver_menu",
                "consultar_producto",
                "ver_metodos_de_pago",
                "ver_metodos_de_entrega",
                "consultar_domicilio_comercio",
                "consultar_horarios_comercio",
            )
        ]
        intents = [
            ProcessedIntent(
                intent=name,
                source_text="x",
                status="executed",
                handler=INFORMATIONAL_COMMERCE_HANDLER,
                recognizer=INFORMATIONAL_COMMERCE_HANDLER,
                resolved_data={},
            )
            for name in (
                "ver_menu",
                "consultar_producto",
                "ver_metodos_de_pago",
                "ver_metodos_de_entrega",
                "consultar_domicilio_comercio",
                "consultar_horarios_comercio",
            )
        ]
        responses = build_customer_responses(_db(), _session(), intents)

        self.assertEqual(len(responses), 6)
        self.assertEqual(info_builder.call_count, 6)

    def test_real_builder_renders_ver_menu_deterministically(self) -> None:
        importlib.reload(mapper_module)
        responses = build_customer_responses(
            _db(),
            _session(),
            [
                ProcessedIntent(
                    intent="ver_menu",
                    source_text="menu",
                    status="executed",
                    handler=INFORMATIONAL_COMMERCE_HANDLER,
                    recognizer=INFORMATIONAL_COMMERCE_HANDLER,
                    resolved_data={
                        "items": [
                            {
                                "categoria_nombre": "Pizzas",
                                "producto_nombre": "Muzzarella",
                                "presentacion_codigo": "PI",
                                "presentacion_descripcion": "Individual",
                            }
                        ]
                    },
                ),
            ],
        )
        self.assertEqual(len(responses), 1)
        rendered = responses[0]
        self.assertEqual(rendered.intent, "ver_menu")
        self.assertEqual(rendered.status, "executed")
        self.assertNotEqual(rendered.message, GENERIC_MESSAGE)
        self.assertIn("Menú disponible:", rendered.message)
        self.assertIn("Pizzas:", rendered.message)
        self.assertIn("- Muzzarella (PI)", rendered.message)

    def test_horarios_does_not_invoke_generic_message(self) -> None:
        importlib.reload(mapper_module)
        responses = build_customer_responses(
            _db(),
            _session(),
            [
                ProcessedIntent(
                    intent="consultar_horarios_comercio",
                    source_text="horarios",
                    status="executed",
                    handler=INFORMATIONAL_COMMERCE_HANDLER,
                    recognizer=INFORMATIONAL_COMMERCE_HANDLER,
                    resolved_data={"reason": "not_configured"},
                ),
            ],
        )
        self.assertEqual(len(responses), 1)
        self.assertNotEqual(responses[0].message, GENERIC_MESSAGE)
        self.assertIn("horarios", responses[0].message)


class OrderingAndLocalOutboxEquivalenceTest(unittest.TestCase):
    @patch.object(mapper_module, "build_agregar_producto_response")
    @patch.object(mapper_module, "build_informational_commerce_response")
    def test_informational_intent_preserves_position_in_mixed_intent_list(
        self, info_builder, agregar_builder
    ) -> None:
        agregar_builder.return_value = MagicMock(
            message="ADD", intent="agregar_producto", status="executed"
        )
        info_builder.return_value = MagicMock(
            message="MENU", intent="ver_menu", status="executed"
        )

        responses = build_customer_responses(
            _db(),
            _session(),
            [
                ProcessedIntent(
                    intent="agregar_producto",
                    source_text="x",
                    status="executed",
                    handler="agregar_producto",
                    recognizer="recognizer_productos",
                    resolved_data={},
                ),
                ProcessedIntent(
                    intent="ver_menu",
                    source_text="x",
                    status="executed",
                    handler=INFORMATIONAL_COMMERCE_HANDLER,
                    recognizer=INFORMATIONAL_COMMERCE_HANDLER,
                    resolved_data={},
                ),
            ],
        )

        self.assertEqual(len(responses), 2)
        self.assertEqual(responses[0].intent, "agregar_producto")
        self.assertEqual(responses[1].intent, "ver_menu")

    def test_local_and_outbox_render_identical_text_for_same_processed_intent(
        self,
    ) -> None:
        intent = ProcessedIntent(
            intent="ver_menu",
            source_text="x",
            status="executed",
            handler=INFORMATIONAL_COMMERCE_HANDLER,
            recognizer=INFORMATIONAL_COMMERCE_HANDLER,
            resolved_data={
                "items": [
                    {
                        "categoria_nombre": "Pizzas",
                        "producto_nombre": "Muzzarella",
                        "presentacion_codigo": "PI",
                        "presentacion_descripcion": "Individual",
                    }
                ]
            },
        )
        db = _db()
        session = _session()
        local = build_customer_responses(db, session, [intent])
        outbox = mapper_module.stage_outbound_rows(
            db,
            session,
            proveedor="wa",
            recepcion_mensaje_proveedor_id=1,
            destinatario_e164="+5491112345678",
            intents=[intent],
            outbox_repo=MagicMock(),
        )
        self.assertEqual(local[0].message, outbox[0].customer_response.message)
        self.assertEqual(local[0].intent, outbox[0].customer_response.intent)
        self.assertEqual(local[0].status, outbox[0].customer_response.status)


class BoundariesTest(unittest.TestCase):
    def test_orchestration_module_all_exports_limited(self) -> None:
        importlib.reload(info_module)
        self.assertEqual(
            set(info_module.__all__),
            {
                "INFORMATIONAL_COMMERCE_HANDLER",
                "is_informational_commerce_intent",
                "process_initial_informational_commerce_query",
            },
        )

    def test_response_module_all_exports_limited(self) -> None:
        importlib.reload(response_module)
        self.assertEqual(
            set(response_module.__all__),
            {
                "INFORMATIONAL_COMMERCE_HANDLER",
                "build_informational_commerce_response",
            },
        )

    def test_orchestration_module_does_not_log_raw_text(self) -> None:
        with open(info_module.__file__, encoding="utf-8") as fh:
            source = fh.read()
        for forbidden in (
            "logging.",
            "logger.",
            "print(",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)

    def test_response_module_does_not_log_raw_text(self) -> None:
        with open(response_module.__file__, encoding="utf-8") as fh:
            source = fh.read()
        for forbidden in (
            "logging.",
            "logger.",
            "print(",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)

    def test_orchestration_module_does_not_import_repositories(self) -> None:
        with open(info_module.__file__, encoding="utf-8") as fh:
            source = fh.read()
        for forbidden in (
            "from backend.repositories",
            "import backend.repositories",
            "MediosPagoRepository",
            "MetodoEntregaRepository",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)

    def test_orchestration_module_does_not_call_transaction_methods(self) -> None:
        with open(info_module.__file__, encoding="utf-8") as fh:
            source = fh.read()
        for forbidden in (
            "self._session.commit",
            "self._session.rollback",
            "self._session.flush",
            "self._session.begin",
            "db.commit(",
            "db.rollback(",
            "db.flush(",
            "db.begin(",
            "db.close(",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
