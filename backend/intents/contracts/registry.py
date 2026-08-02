"""Contract registry for the modern intent pipeline.

Aggregates the static contract literals so consumers can enumerate every
supported intent through a single source. The contract registry is
deliberately read-only and free of side effects.
"""

from backend.intents.contracts.agregar_producto import AGREGAR_PRODUCTO_CONTRACT
from backend.intents.contracts.modificar_producto import MODIFICAR_PRODUCTO_CONTRACT
from backend.intents.contracts.quitar_producto import QUITAR_PRODUCTO_CONTRACT


CONTRACT_REGISTRY: dict[str, dict] = {
    AGREGAR_PRODUCTO_CONTRACT["intent"]: AGREGAR_PRODUCTO_CONTRACT,
    QUITAR_PRODUCTO_CONTRACT["intent"]: QUITAR_PRODUCTO_CONTRACT,
    MODIFICAR_PRODUCTO_CONTRACT["intent"]: MODIFICAR_PRODUCTO_CONTRACT,
}


def list_intents() -> list[str]:
    return list(CONTRACT_REGISTRY.keys())


def get_contract(intent_name: str) -> dict | None:
    return CONTRACT_REGISTRY.get(intent_name)


__all__ = ["CONTRACT_REGISTRY", "list_intents", "get_contract"]
