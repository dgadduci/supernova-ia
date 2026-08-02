from typing import Any, Literal

from pydantic import BaseModel, Field

from backend.intents.schemas.requirement_state import RequirementState

IntentStatus = Literal["pending_resolution", "ready", "executed", "rejected", "failed"]
IntentStage = Literal["source_selection", "destination_selection"] | None


class ProcessedIntent(BaseModel):
    intent: str
    source_text: str
    status: IntentStatus
    recognizer: str | None = None
    handler: str
    stage: IntentStage = None
    resolved_data: dict[str, Any] = Field(default_factory=dict)
    requirements: list[RequirementState] = Field(default_factory=list)
    candidate_ids: list[int] = Field(default_factory=list)


__all__ = ["IntentStage", "IntentStatus", "ProcessedIntent"]