"""Knowledge base: chunks exported by the portfolio's tools/export-knowledge.mjs.

The portfolio publishes the file at /knowledge/portfolio.json. When NEXA_KNOWLEDGE_URL
is set the service loads that live copy at startup, and falls back to the bundled file
if the download fails, so a portfolio update reaches NEXA with a restart, not a redeploy.
"""
from __future__ import annotations

import json
import logging
import urllib.request
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("nexa")


@dataclass(frozen=True)
class Chunk:
    id: str
    title: str
    section: str
    url: str
    text: str
    project_id: str | None = None


def load_chunks(path: Path) -> list[Chunk]:
    return _parse(json.loads(Path(path).read_text(encoding="utf-8")))


def load_knowledge(path: Path, url: str = "", *, timeout: float = 10.0) -> list[Chunk]:
    """Live copy from `url` when given and valid, otherwise the bundled file at `path`."""
    if url.startswith("https://"):
        try:
            with urllib.request.urlopen(url, timeout=timeout) as res:  # noqa: S310 (https only)
                chunks = _parse(json.loads(res.read().decode("utf-8")))
            if chunks:
                log.info("knowledge: %d chunks from %s", len(chunks), url)
                return chunks
        except Exception as e:  # network, JSON or schema problems all fall back
            log.warning("knowledge: live copy unavailable (%s), using bundled file", type(e).__name__)
    return load_chunks(path)


def _parse(data: dict) -> list[Chunk]:
    if data.get("version") != 1:
        raise ValueError(f"Unsupported knowledge file version: {data.get('version')}")
    return [
        Chunk(id=c["id"], title=c["title"], section=c["section"], url=c["url"], text=c["text"], project_id=c.get("projectId"))
        for c in data["chunks"]
    ]
