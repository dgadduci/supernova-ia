from backend.intents.contracts.agregar_producto import AGREGAR_PRODUCTO_CONTRACT
from backend.intents.schemas.processed_intent import ProcessedIntent
from backend.intents.schemas.requirement_state import RequirementState


def process_agregar_producto(source_text: str, normalized_result: dict) -> ProcessedIntent:
    candidate_ids = list(normalized_result.get("candidate_ids") or [])

    contract_requirements = AGREGAR_PRODUCTO_CONTRACT["requirements"]

    resolved_data = dict(normalized_result.get("resolved_data") or {})
    if "cantidad" not in resolved_data:
        resolved_data["cantidad"] = contract_requirements["cantidad"]["default"]

    requirements: list[RequirementState] = []
    for name, config in contract_requirements.items():
        if name in resolved_data:
            requirements.append(
                RequirementState(name=name, status="completed", value=resolved_data[name])
            )
        else:
            requirements.append(
                RequirementState(name=name, status="pending", value=config["default"])
            )

    all_required_completed = all(
        req.status == "completed"
        for name, req in zip(contract_requirements.keys(), requirements)
        if contract_requirements[name].get("required") is True
    )
    status = "ready" if all_required_completed else "pending_resolution"

    return ProcessedIntent(
        intent=AGREGAR_PRODUCTO_CONTRACT["intent"],
        source_text=source_text,
        status=status,
        recognizer=AGREGAR_PRODUCTO_CONTRACT["recognizer"],
        handler=AGREGAR_PRODUCTO_CONTRACT["handler"],
        resolved_data=resolved_data,
        requirements=requirements,
        candidate_ids=candidate_ids,
    )


__all__ = ["process_agregar_producto"]