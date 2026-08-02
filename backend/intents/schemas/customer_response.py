from pydantic import BaseModel


class CustomerResponse(BaseModel):
    message: str
    intent: str
    status: str


__all__ = ["CustomerResponse"]
