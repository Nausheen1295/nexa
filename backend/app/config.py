"""NEXA backend configuration — read once from environment variables.

Secrets (the LLM provider API key) are read by the provider SDK from the environment
and never logged, returned, or written anywhere by this service.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _list(name: str, default: str) -> list[str]:
    return [v.strip() for v in os.getenv(name, default).split(",") if v.strip()]


@dataclass(frozen=True)
class Settings:
    # Model + generation
    model: str = field(default_factory=lambda: os.getenv("NEXA_MODEL", ""))  # set in the host environment
    effort: str = field(default_factory=lambda: os.getenv("NEXA_EFFORT", "low"))  # chat → low effort
    max_tokens: int = field(default_factory=lambda: int(os.getenv("NEXA_MAX_TOKENS", "2048")))
    use_fallbacks: bool = field(default_factory=lambda: os.getenv("NEXA_FALLBACKS", "true").lower() == "true")

    # Retrieval
    knowledge_path: Path = field(default_factory=lambda: Path(os.getenv("NEXA_KNOWLEDGE", ROOT / "knowledge" / "portfolio.json")))
    # Optional: the portfolio publishes the live knowledge file; the bundled copy is the fallback.
    knowledge_url: str = field(default_factory=lambda: os.getenv("NEXA_KNOWLEDGE_URL", ""))
    top_k: int = field(default_factory=lambda: int(os.getenv("NEXA_TOP_K", "6")))

    # Web / security
    allowed_origins: list[str] = field(default_factory=lambda: _list(
        "NEXA_ALLOWED_ORIGINS", "https://nausheen1295.github.io,http://localhost:8000"))
    rate_limit_per_minute: int = field(default_factory=lambda: int(os.getenv("NEXA_RATE_LIMIT", "10")))
    rate_limit_per_day: int = field(default_factory=lambda: int(os.getenv("NEXA_RATE_LIMIT_DAY", "200")))
    trust_proxy: bool = field(default_factory=lambda: os.getenv("NEXA_TRUST_PROXY", "false").lower() == "true")

    @property
    def llm_configured(self) -> bool:
        return bool(self.model and (os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN")))
