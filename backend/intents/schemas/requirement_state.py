from typing import Any, Literal

from pydantic import BaseModel

RequirementStatus = Literal["pending", "completed"]


class RequirementState(BaseModel):
    name: str
    status: RequirementStatus
    value: Any | None = None


__all__ = ["RequirementStatus", "RequirementState"]