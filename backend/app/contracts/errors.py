from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class ErrorBody(ContractModel):
    code: str
    message: str
    requestId: str
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorEnvelope(ContractModel):
    error: ErrorBody
