"""Request / response models — the API contract shared with js/nexa/client.js."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Mode = Literal["recruiter", "developer", "simple", "architecture", "interview"]


class HistoryTurn(BaseModel):
    role: Literal["user", "nexa"]
    content: str = Field(max_length=4000)


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    mode: Mode = "recruiter"
    projectId: str | None = Field(default=None, max_length=64, pattern=r"^[a-z0-9-]+$")
    history: list[HistoryTurn] = Field(default_factory=list, max_length=8)


class Source(BaseModel):
    title: str
    url: str


class ChatResponse(BaseModel):
    answer: str
    sources: list[Source]
    grounded: bool
