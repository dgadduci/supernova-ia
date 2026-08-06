from typing import Any


def resolve_product_intent(raw: dict) -> dict:
    encontrados = raw.get("encontrados") or []
    encontrados_posibles = raw.get("encontrados_posibles") or []
    encontrados_no_disponibles = raw.get("encontrados_no_disponibles") or []
    no_encontrados = raw.get("no_encontrados") or []

    resolved_data: dict[str, Any] = {}
    candidate_ids: list[int] = []
    unavailable_items: list[str] = []
    not_found_items: list[str] = []

    if encontrados:
        first = encontrados[0]
        resolved_data["producto_presentacion_id"] = first["producto_presentacion_id"]
        resolved_data["cantidad"] = first["cantidad"]
    elif (
        encontrados_posibles
        and isinstance(encontrados_posibles[0], dict)
        and "productos" in encontrados_posibles[0]
    ):
        for group in encontrados_posibles:
            if group.get("kind") == "category":
                continue
            for candidate in group.get("productos") or []:
                candidate_ids.append(candidate["producto_presentacion_id"])
                if "cantidad" in candidate and "cantidad" not in resolved_data:
                    resolved_data["cantidad"] = candidate["cantidad"]
    elif encontrados_posibles and isinstance(encontrados_posibles[0], dict) and encontrados_posibles[0].get("kind") == "category":
        pass
    else:
        for candidate in encontrados_posibles:
            if isinstance(candidate, dict) and candidate.get("kind") == "category":
                continue
            candidate_ids.append(candidate["producto_presentacion_id"])
            if "cantidad" in candidate and "cantidad" not in resolved_data:
                resolved_data["cantidad"] = candidate["cantidad"]

    for item in encontrados_no_disponibles:
        unavailable_items.append(item["texto_origen"])

    for item in no_encontrados:
        not_found_items.append(item["texto_origen"])

    return {
        "resolved_data": resolved_data,
        "candidate_ids": candidate_ids,
        "unavailable_items": unavailable_items,
        "not_found_items": not_found_items,
    }


__all__ = ["resolve_product_intent"]
