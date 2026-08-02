from pydantic import BaseModel, Field

from backend.intents.schemas.processed_intent import ProcessedIntent


class PendingIntents(BaseModel):
    version: int = 1
    active: ProcessedIntent | None = None
    queue: list[ProcessedIntent] = Field(default_factory=list)


__all__ = ["PendingIntents"]