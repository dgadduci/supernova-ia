from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_serializer

from backend.intents.schemas.customer_response import CustomerResponse


class IncomingMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str


class IncomingMessageResponse(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
    )

    responses: list[CustomerResponse]
    diagnostics: list[dict[str, Any]] | None = Field(default=None)

    @model_serializer
    def _serialize(self) -> dict[str, Any]:
        data: dict[str, Any] = {"responses": [r.model_dump() for r in self.responses]}
        if self.diagnostics is not None:
            data["diagnostics"] = [dict(item) for item in self.diagnostics]
        return data


__all__ = ["IncomingMessageRequest", "IncomingMessageResponse"]
