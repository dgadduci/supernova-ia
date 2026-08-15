"""Versioned controlled corpus for the IntentClassifier audit runner.

The corpus enumerates one canonical fixture per registered intent name plus
the three production regressions called out by the proposal
(set_metodo_de_pago, set_direccion_entrega, set_observacion_pedido). Each
fixture pins the expected ordered intent sequence and the expected source
fragments so the audit can produce an evidence-only pass/fail report.

Corpus inputs are controlled. They are intentionally safe to render in the
prompt and serialized verbatim in the audit report, so fixtures MUST NOT
contain real customer PII or secrets.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from backend.intents.schemas.intent_classification import IntentName

CORPUS_VERSION = "intent-corpus/v1.7.0"


@dataclass(frozen=True, slots=True)
class IntentFixture:
    fixture_id: str
    description: str
    message: str
    expected_intents: tuple[IntentName, ...]
    expected_source_fragments: tuple[str, ...]


def _fixture(
    fixture_id: str,
    description: str,
    message: str,
    expected: tuple[IntentName, ...],
    fragments: tuple[str, ...] = (),
) -> IntentFixture:
    return IntentFixture(
        fixture_id=fixture_id,
        description=description,
        message=message,
        expected_intents=expected,
        expected_source_fragments=fragments,
    )


CONTROLLED_INTENT_CORPUS: tuple[IntentFixture, ...] = (
    _fixture(
        "F-SALUDO",
        "Greeting",
        "Hola, buenas tardes",
        (IntentName.SALUDO,),
    ),
    _fixture(
        "F-AGRADECIMIENTO",
        "Customer thanks the shop",
        "Muchas gracias",
        (IntentName.AGRADECIMIENTO,),
    ),
    _fixture(
        "F-DESPEDIDA",
        "Customer says goodbye",
        "Hasta luego, nos vemos",
        (IntentName.DESPEDIDA,),
    ),
    _fixture(
        "F-RESPUESTA_AFIRMATIVA",
        "Affirmative reply",
        "Sí, por favor",
        (IntentName.RESPUESTA_AFIRMATIVA,),
    ),
    _fixture(
        "F-RESPUESTA_NEGATIVA",
        "Negative reply",
        "No, gracias",
        (IntentName.RESPUESTA_NEGATIVA,),
    ),
    _fixture(
        "F-VER_MENU",
        "Wants to see the menu",
        "Quiero ver la carta",
        (IntentName.VER_MENU,),
    ),
    _fixture(
        "F-VER_MENU-CATEGORIA_PIZZAS",
        "Category browse: asks which pizzas are available (must remain "
        "ver_menu, not consultar_producto)",
        "qué pizzas hay",
        (IntentName.VER_MENU,),
    ),
    _fixture(
        "F-VER_MENU-CATEGORIA_EMPANADAS",
        "Category browse: asks which empanada flavors are available "
        "(must remain ver_menu, not consultar_producto)",
        "qué gustos de empanadas tenés",
        (IntentName.VER_MENU,),
    ),
    _fixture(
        "F-VER_MENU-CATEGORIA_BEBIDAS",
        "Category browse: asks which beverages are available (must "
        "remain ver_menu, not consultar_producto)",
        "qué bebidas están disponibles",
        (IntentName.VER_MENU,),
    ),
    _fixture(
        "F-VER_MENU-CATEGORIA_EMPANADAS_TENES",
        "Pilot regression: 'qué gustos de empanadas tenés' must remain "
        "ver_menu and must NOT be classified as consultar_producto",
        "qué gustos de empanadas tenés",
        (IntentName.VER_MENU,),
    ),
    _fixture(
        "F-VER_MENU-CATEGORIA_EMPANADAS_HAY",
        "Pilot regression: 'qué gustos de empanadas hay' must remain "
        "ver_menu and must NOT be classified as consultar_producto",
        "qué gustos de empanadas hay",
        (IntentName.VER_MENU,),
    ),
    _fixture(
        "F-VER_MENU-CATEGORIA_BEBIDAS_TENES",
        "Pilot regression: 'qué bebidas tenés' must remain ver_menu "
        "and must NOT be classified as consultar_producto",
        "qué bebidas tenés",
        (IntentName.VER_MENU,),
    ),
    _fixture(
        "F-CONSULTAR_PRODUCTO",
        "Asks about a specific product",
        "Tienen empanadas de jamón y queso?",
        (IntentName.CONSULTAR_PRODUCTO,),
        ("empanadas de jamón y queso",),
    ),
    _fixture(
        "F-CONSULTAR_PRODUCTO-PRECIO_NAPOLITANA",
        "Concrete product detail: asks the price of a specific "
        "presentation (must remain consultar_producto and must NOT "
        "be classified as ver_menu)",
        "cuánto sale la napolitana grande",
        (IntentName.CONSULTAR_PRODUCTO,),
        ("cuánto sale la napolitana grande",),
    ),
    _fixture(
        "F-VER_METODOS_DE_PAGO",
        "Asks about accepted payment methods",
        "Qué medios de pago aceptan?",
        (IntentName.VER_METODOS_DE_PAGO,),
    ),
    _fixture(
        "F-VER_METODOS_DE_ENTREGA",
        "Asks about delivery methods",
        "Cómo puedo recibir el pedido?",
        (IntentName.VER_METODOS_DE_ENTREGA,),
    ),
    _fixture(
        "F-CONSULTAR_DOMICILIO_COMERCIO",
        "Asks for the shop address",
        "Dónde queda el local?",
        (IntentName.CONSULTAR_DOMICILIO_COMERCIO,),
    ),
    _fixture(
        "F-CONSULTAR_HORARIOS_COMERCIO",
        "Asks about opening hours",
        "Hasta qué hora atienden?",
        (IntentName.CONSULTAR_HORARIOS_COMERCIO,),
    ),
    _fixture(
        "F-INICIAR_PEDIDO",
        "Wants to start an order without products yet",
        "Quiero hacer un pedido",
        (IntentName.INICIAR_PEDIDO,),
    ),
    _fixture(
        "F-AGREGAR_PRODUCTO",
        "Adds a product",
        "Quiero una empanada de carne",
        (IntentName.AGREGAR_PRODUCTO,),
        ("una empanada de carne",),
    ),
    _fixture(
        "F-AGREGAR_PRODUCTO_DOS",
        "Adds two products in one message (order preserved)",
        "Quiero dos pizzas de mozzarella y una empanada de carne",
        (
            IntentName.AGREGAR_PRODUCTO,
            IntentName.AGREGAR_PRODUCTO,
        ),
        ("dos pizzas de mozzarella", "una empanada de carne"),
    ),
    _fixture(
        "F-QUITAR_PRODUCTO",
        "Removes a product",
        "Quítame la pizza napolitana",
        (IntentName.QUITAR_PRODUCTO,),
        ("la pizza napolitana",),
    ),
    _fixture(
        "F-MODIFICAR_PRODUCTO",
        "Atomic product swap (single intent)",
        "Cambiame la pizza de mozzarella por una napolitana",
        (IntentName.MODIFICAR_PRODUCTO,),
        ("Cambiame la pizza de mozzarella por una napolitana",),
    ),
    _fixture(
        "F-VACIAR_PEDIDO",
        "Empty the cart",
        "Quiero vaciar el pedido",
        (IntentName.VACIAR_PEDIDO,),
    ),
    _fixture(
        "F-SET_OBSERVACION_PEDIDO",
        "Adds a general observation",
        "Por favor que la entrega sea sin demorarse mucho",
        (IntentName.SET_OBSERVACION_PEDIDO,),
        ("que la entrega sea sin demorarse mucho",),
    ),
    _fixture(
        "F-REG-OBSERVACION_PEDIDO",
        "Regression: general order observation must remain a single "
        "set_observacion_pedido intent",
        "Por favor que la entrega sea sin demorarse mucho",
        (IntentName.SET_OBSERVACION_PEDIDO,),
        ("que la entrega sea sin demorarse mucho",),
    ),
    _fixture(
        "F-CONSULTAR_RESUMEN_PEDIDO",
        "Wants the order summary",
        "Pasame el resumen del pedido",
        (IntentName.CONSULTAR_RESUMEN_PEDIDO,),
    ),
    _fixture(
        "F-SET_METODO_DE_ENTREGA",
        "Sets delivery method",
        "Lo paso a retirar por el local",
        (IntentName.SET_METODO_DE_ENTREGA,),
    ),
    _fixture(
        "F-REG-OBSERVACION_PEDIDO-PORTON_LATERAL",
        "Regression: access/route instruction that mentions 'entrega' "
        "must remain a single set_observacion_pedido intent",
        "La entrega es por el portón lateral",
        (IntentName.SET_OBSERVACION_PEDIDO,),
    ),
    _fixture(
        "F-REG-OBSERVACION_PEDIDO-MASCOTAS",
        "Regression: care/pets instruction must remain a single "
        "set_observacion_pedido intent",
        "Cuidado con el perro",
        (IntentName.SET_OBSERVACION_PEDIDO,),
    ),
    _fixture(
        "F-REG-METODO_DE_ENTREGA-ENVIO_DOMICILIO",
        "Regression: explicit delivery modality must remain a single "
        "set_metodo_de_entrega intent",
        "Quiero envío a domicilio",
        (IntentName.SET_METODO_DE_ENTREGA,),
    ),
    _fixture(
        "F-REG-METODO_DE_ENTREGA-RETIRO_LOCAL",
        "Regression: explicit pickup modality must remain a single "
        "set_metodo_de_entrega intent",
        "Lo retiro por el local",
        (IntentName.SET_METODO_DE_ENTREGA,),
    ),
    _fixture(
        "F-SET_DIRECCION_ENTREGA",
        "Sets the delivery address",
        "Me lo envias a Tilcara 2020",
        (IntentName.SET_DIRECCION_ENTREGA,),
    ),
    _fixture(
        "F-REG-DIRECCION_ENTREGA-TILCARA_2020",
        "Regression: explicit concrete address must remain a single "
        "set_direccion_entrega intent and must NOT become "
        "set_observacion_pedido despite the word 'entrega'",
        "Me lo envias a Tilcara 2020",
        (IntentName.SET_DIRECCION_ENTREGA,),
    ),
    _fixture(
        "F-SET_FECHA_HORA_ENTREGA",
        "Sets scheduled delivery date/time",
        "Lo quiero recibir mañana a las 20",
        (IntentName.SET_FECHA_HORA_ENTREGA,),
    ),
    _fixture(
        "F-REG-PAGO-EFECTIVO",
        "Regression: Pago en Efectivo (prueba cierre) must be a single "
        "set_metodo_de_pago intent",
        "Pago en Efectivo (prueba cierre)",
        (IntentName.SET_METODO_DE_PAGO,),
        ("Pago en Efectivo (prueba cierre)",),
    ),
    _fixture(
        "F-SET_METODO_DE_PAGO",
        "Sets payment method (canonical)",
        "Pago en efectivo",
        (IntentName.SET_METODO_DE_PAGO,),
    ),
    _fixture(
        "F-CONFIRMAR_PEDIDO",
        "Confirms the order",
        "Sí, confirmo el pedido",
        (IntentName.CONFIRMAR_PEDIDO,),
    ),
    _fixture(
        "F-CONSULTAR_ESTADO_PEDIDO",
        "Asks about the status of an existing order",
        "Cómo va mi pedido?",
        (IntentName.CONSULTAR_ESTADO_PEDIDO,),
    ),
    _fixture(
        "F-CONSULTAR_ESTADO_PEDIDO-CUAL_ES",
        "Asks about the order status using the explicit 'cual es el "
        "estado de mi pedido' phrasing (covers the closed draft / "
        "confirmed phrasing used by the pending-context interruption)",
        "Cuál es el estado de mi pedido",
        (IntentName.CONSULTAR_ESTADO_PEDIDO,),
    ),
    _fixture(
        "F-CANCELAR_PEDIDO",
        "Cancels a confirmed order",
        "Quiero cancelar el pedido",
        (IntentName.CANCELAR_PEDIDO,),
    ),
    _fixture(
        "F-DESCONOCIDA",
        "Unparseable message",
        "asdf qwerty lorem ipsum",
        (IntentName.DESCONOCIDA,),
    ),
)


def iter_fixtures() -> Iterable[IntentFixture]:
    """Iterate over the controlled corpus in declaration order."""
    return iter(CONTROLLED_INTENT_CORPUS)


def get_fixture(fixture_id: str) -> IntentFixture | None:
    for fixture in CONTROLLED_INTENT_CORPUS:
        if fixture.fixture_id == fixture_id:
            return fixture
    return None


def unique_intents_covered() -> tuple[IntentName, ...]:
    """Return the tuple of unique intent names covered by the corpus."""
    seen: list[IntentName] = []
    for fixture in CONTROLLED_INTENT_CORPUS:
        for intent in fixture.expected_intents:
            if intent not in seen:
                seen.append(intent)
    return tuple(seen)


__all__ = [
    "CONTROLLED_INTENT_CORPUS",
    "CORPUS_VERSION",
    "IntentFixture",
    "get_fixture",
    "iter_fixtures",
    "unique_intents_covered",
]
