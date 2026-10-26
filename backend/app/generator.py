"""Answer generation. `Generator` is the seam the API depends on; tests use a fake."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Protocol

import anthropic

from .config import Settings
from .knowledge import Chunk
from .prompts import ANSWER_SCHEMA, SYSTEM_PROMPT, build_user_turn
from .schemas import HistoryTurn


@dataclass(frozen=True)
class Generation:
    answer: str
    cited_ids: list[str]
    grounded: bool


class GenerationRefused(Exception):
    """The model (and any fallback) declined the request."""


class GenerationFailed(Exception):
    """The response couldn't be used (truncated, malformed)."""


class Generator(Protocol):
    async def generate(self, *, question: str, mode: str, chunks: list[Chunk], history: list[HistoryTurn]) -> Generation: ...


def build_messages(question: str, mode: str, chunks: list[Chunk], history: list[HistoryTurn]) -> list[dict]:
    """Prior turns as plain text, then the grounded question. First message must be a user turn."""
    messages: list[dict] = []
    for turn in history:
        role = "user" if turn.role == "user" else "assistant"
        if not messages and role == "assistant":
            continue
        messages.append({"role": role, "content": turn.content})
    messages.append({"role": "user", "content": build_user_turn(question, mode, chunks)})
    return messages


class LLMGenerator:
    """LLM answer generation via the provider's official SDK. Credentials come from the environment."""

    def __init__(self, settings: Settings, client: anthropic.AsyncAnthropic | None = None):
        self.settings = settings
        self.client = client or anthropic.AsyncAnthropic(timeout=45.0, max_retries=2)

    async def generate(self, *, question: str, mode: str, chunks: list[Chunk], history: list[HistoryTurn]) -> Generation:
        s = self.settings
        params = dict(
            model=s.model,
            max_tokens=s.max_tokens,
            # Static system prompt first so it can be served from the prompt cache once it's long enough.
            system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
            messages=build_messages(question, mode, chunks, history),
            output_config={"effort": s.effort, "format": {"type": "json_schema", "schema": ANSWER_SCHEMA}},
        )
        if s.use_fallbacks:
            # On a safety-classifier decline the API re-runs the request on the provider's recommended fallback model.
            response = await self.client.beta.messages.create(
                betas=["server-side-fallback-2026-07-01"], fallbacks="default", **params
            )
        else:
            response = await self.client.messages.create(**params)

        # Always check stop_reason before reading content.
        if response.stop_reason == "refusal":
            raise GenerationRefused()
        if response.stop_reason == "max_tokens":
            raise GenerationFailed("response truncated")

        text = next((b.text for b in response.content if b.type == "text"), None)
        if text is None:
            raise GenerationFailed("no text block")
        try:
            data = json.loads(text)
            return Generation(
                answer=str(data["answer"]).strip(),
                cited_ids=[str(i) for i in data.get("cited_ids", [])],
                grounded=bool(data["grounded"]),
            )
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            raise GenerationFailed(f"malformed output: {e}") from e
