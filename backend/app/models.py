from typing import Literal

from pydantic import BaseModel, Field


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=12000)


class ChatRequest(BaseModel):
    messages: list[ChatTurn] = Field(min_length=1)
    model: str | None = None


class ResetRequest(BaseModel):
    model: str | None = None
