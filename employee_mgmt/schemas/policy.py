from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field


class PolicyCreate(BaseModel):
    title: str = Field(..., min_length=2, max_length=255)
    category: str | None = Field(default=None, max_length=100)
    content: str = Field(..., min_length=1)


class PolicyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    category: str | None = None
    created_at: datetime


class PolicyQueryRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=1000)
    top_k: int = Field(default=5, ge=1, le=20)
    category: str | None = Field(default=None, max_length=100)


class PolicyChunkMatch(BaseModel):
    policy_id: int
    title: str
    chunk_text: str
    score: float


class PolicyQueryResponse(BaseModel):
    query: str
    matches: list[PolicyChunkMatch]
    answer: str | None = None