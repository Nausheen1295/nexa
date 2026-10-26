"""Retrieval quality on the real exported knowledge base."""
from __future__ import annotations

import pytest

from app.config import Settings
from app.knowledge import load_chunks
from app.retrieval import BM25Retriever

R = BM25Retriever(load_chunks(Settings().knowledge_path))


def top_projects(q, k=6, **kw):
    return [c.project_id for c, s in R.search(q, k=k, **kw) if s > 0]


@pytest.mark.parametrize("question,expected", [
    ("Explain SecureVault AI", "securevault-ai"),
    ("Why did you use AES-256-GCM?", "securevault-ai"),
    ("How does the blockchain key vault work?", "securevault-ai"),
    ("What is NEXA?", "nexa"),
    ("plant disease photo", "floramind-ai"),
    ("second brain notes", "mindscape-ai"),
    ("csv data profiling charts", "insightforge"),
    ("packet sniffer scapy", "packet-sniffer"),
    ("climate geospatial maps", "earthpulse"),
])
def test_expected_project_ranks_first(question, expected):
    assert top_projects(question)[0] == expected


def test_profile_questions_find_profile():
    ids = [c.id for c, _ in R.search("Where did Nausheen study?", k=3)]
    assert "profile:education" in ids


def test_undocumented_chunk_attached_for_project_questions():
    ids = [c.id for c, _ in R.search("What was the biggest challenge in SecureVault AI?", k=4)]
    assert "securevault-ai:undocumented" in ids


def test_every_chunk_states_its_project_status():
    # The status line stops the model presenting plans as built work (and vice versa).
    for c, _ in R.search("NEXA architecture", k=5):
        if c.project_id == "nexa":
            assert c.text.startswith("Project: NEXA") and "Status: Live" in c.text


def test_gibberish_finds_nothing():
    assert R.search("zxqv plorbt", k=5) == []


def test_live_knowledge_falls_back_to_bundled_file(monkeypatch):
    import urllib.request
    from app.knowledge import load_knowledge

    def boom(*a, **k):
        raise OSError("offline")

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    chunks = load_knowledge(Settings().knowledge_path, "https://example.invalid/portfolio.json")
    assert len(chunks) == len(load_chunks(Settings().knowledge_path))


def test_live_knowledge_ignores_non_https_urls():
    from app.knowledge import load_knowledge
    assert load_knowledge(Settings().knowledge_path, "http://insecure.example/k.json")
