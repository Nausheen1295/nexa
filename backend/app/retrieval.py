"""Retrieval over the knowledge base.

`Retriever` is the seam: today a dependency-free BM25 index; later an
embeddings + vector-DB retriever can implement the same `search()` method
without touching the API or prompt code.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from typing import Protocol

from .knowledge import Chunk

_TOKEN = re.compile(r"[a-z0-9][a-z0-9+#.-]*")
_STOP = frozenset(
    "the a an and or of to in on for with is are was were be been what which how why did does do you your she her "
    "nausheen nausheen's me show tell about explain use used using project projects like i'm im this that it its "
    "can could would should will from by as at".split()
)
_SYNONYMS = {
    "ai": ["artificial", "intelligence", "llm", "rag", "ml"],
    "cybersecurity": ["security", "encryption", "cryptography", "threat"],
    "security": ["cybersecurity", "encryption"],
    "db": ["database"],
    "challenge": ["challenges"],
    "decision": ["decisions"],
    "stack": ["technologies"],
    "tech": ["technologies"],
    # profile questions in everyday words
    "study": ["education", "degree", "university"], "studied": ["education", "degree", "university"],
    "studying": ["education", "degree", "university"], "university": ["education", "degree"],
    "college": ["education", "university"], "degree": ["education"], "qualification": ["education", "degree"],
    "work": ["experience", "intern"], "worked": ["experience", "intern"], "job": ["experience"],
    "internship": ["intern", "experience"], "reach": ["contact", "email"], "contact": ["email", "linkedin"],
    "hire": ["contact", "opportunities"], "based": ["location"], "live": ["based", "location"],
    "skills": ["skills"], "languages": ["languages", "python", "java"],
}


def tokenize(text: str) -> list[str]:
    toks = [t.strip(".-") for t in _TOKEN.findall(text.lower())]
    return [t for t in toks if len(t) > 1 and t not in _STOP]


class Retriever(Protocol):
    def search(self, query: str, *, k: int, project_id: str | None = None) -> list[tuple[Chunk, float]]: ...


class BM25Retriever:
    """Okapi BM25 with title boosting, synonym expansion and project focus."""

    def __init__(self, chunks: list[Chunk], *, k1: float = 1.4, b: float = 0.75, min_score: float = 1.0):
        self.chunks = chunks
        self.k1, self.b, self.min_score = k1, b, min_score
        self._docs = [Counter(tokenize(f"{c.title} {c.title} {c.text}")) for c in chunks]  # title counted twice = boost
        self._lens = [sum(d.values()) for d in self._docs]
        self._avg = sum(self._lens) / max(len(self._lens), 1)
        df: Counter[str] = Counter()
        for d in self._docs:
            df.update(d.keys())
        n = len(chunks)
        self._idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}
        self._by_id = {c.id: c for c in chunks}
        self._names = {c.project_id: c.title.split(" — ")[0].lower() for c in chunks if c.project_id}

    def _score(self, i: int, terms: list[str]) -> float:
        doc, length, s = self._docs[i], self._lens[i], 0.0
        for t in terms:
            tf = doc.get(t)
            if tf:
                s += self._idf[t] * tf * (self.k1 + 1) / (tf + self.k1 * (1 - self.b + self.b * length / self._avg))
        return s

    def search(self, query: str, *, k: int = 6, project_id: str | None = None) -> list[tuple[Chunk, float]]:
        base = tokenize(query)
        terms = base + [s for t in base for s in _SYNONYMS.get(t, [])]
        if not terms:
            return []

        # A project named in the question (or chosen in the UI) focuses retrieval on it.
        q = query.lower()
        focus = project_id or next((pid for pid, name in self._names.items() if name and name in q), None)

        scored = []
        for i, chunk in enumerate(self.chunks):
            if project_id and chunk.project_id not in (project_id, None):
                continue
            s = self._score(i, terms)
            if focus and chunk.project_id == focus:
                s *= 1.6
            if s >= self.min_score:
                scored.append((chunk, s))
        scored.sort(key=lambda x: x[1], reverse=True)
        top = scored[:k]

        # Whenever a project is in play, include its "not yet documented" chunk so the
        # model can say "that isn't documented" with a citation instead of guessing.
        for pid in {c.project_id for c, _ in top if c.project_id} | ({focus} if focus else set()):
            gap = self._by_id.get(f"{pid}:undocumented")
            if gap and all(c.id != gap.id for c, _ in top):
                top.append((gap, 0.0))
        return top
