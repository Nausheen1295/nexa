"""API contract + safety tests. No network, no API key: a fake generator stands in for the LLM."""
from __future__ import annotations

import json
from dataclasses import replace
from types import SimpleNamespace

import anthropic
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.generator import LLMGenerator, Generation, GenerationFailed, GenerationRefused, build_messages
from app.knowledge import load_chunks
from app.main import NOT_DOCUMENTED, create_app
from app.ratelimit import RateLimiter
from app.retrieval import BM25Retriever
from app.schemas import HistoryTurn

SETTINGS = Settings(model="test-model")
CHUNKS = load_chunks(SETTINGS.knowledge_path)


class FakeGenerator:
    def __init__(self, result=None, exc=None):
        self.result, self.exc, self.calls = result, exc, []

    async def generate(self, **kw):
        self.calls.append(kw)
        if self.exc:
            raise self.exc
        ids = [c.id for c in kw["chunks"]]
        return self.result or Generation(answer="SecureVault AI encrypts files locally.", cited_ids=ids[:2] + ["made-up:id"], grounded=True)


def client_with(gen=None, **overrides):
    settings = replace(SETTINGS, **overrides) if overrides else SETTINGS
    return TestClient(create_app(settings, retriever=BM25Retriever(CHUNKS), generator=gen))


# ---------------------------------------------------------------- health
def test_health_ok_when_generator_present():
    assert client_with(FakeGenerator()).get("/health").json() == {"status": "ok"}


def test_liveness_ok_even_without_llm():
    with TestClient(create_app(replace(SETTINGS, model=""), retriever=BM25Retriever(CHUNKS))) as c:
        r = c.get("/healthz")
    assert r.status_code == 200 and r.json() == {"status": "alive"}


def test_health_503_without_llm():
    app = create_app(SETTINGS, retriever=BM25Retriever(CHUNKS), generator=None)
    if SETTINGS.llm_configured:
        pytest.skip("an API key is set in this environment")
    assert TestClient(app).get("/health").status_code == 503


# ---------------------------------------------------------------- happy path
def test_chat_returns_grounded_answer_with_only_real_sources():
    gen = FakeGenerator()
    r = client_with(gen).post("/chat", json={"question": "Explain SecureVault AI", "mode": "developer"})
    assert r.status_code == 200
    body = r.json()
    assert body["grounded"] is True
    assert body["sources"] and all(s["url"].startswith("https://") for s in body["sources"])
    assert all("made-up" not in s["title"] for s in body["sources"])          # fabricated id dropped
    assert gen.calls[0]["mode"] == "developer"
    assert any(c.project_id == "securevault-ai" for c in gen.calls[0]["chunks"])


def test_no_relevant_documents_skips_the_model():
    gen = FakeGenerator()
    r = client_with(gen).post("/chat", json={"question": "zxqv plorbt"})
    assert r.json() == {"answer": NOT_DOCUMENTED, "sources": [], "grounded": False}
    assert gen.calls == []


def test_grounded_false_when_model_cites_nothing():
    gen = FakeGenerator(Generation(answer="Not documented.", cited_ids=[], grounded=True))
    body = client_with(gen).post("/chat", json={"question": "SecureVault AI database"}).json()
    assert body["grounded"] is False and body["sources"] == []


def test_project_context_restricts_retrieval():
    gen = FakeGenerator()
    client_with(gen).post("/chat", json={"question": "what technologies", "projectId": "nexa"})
    assert {c.project_id for c in gen.calls[0]["chunks"]} <= {"nexa", None}


# ---------------------------------------------------------------- validation
@pytest.mark.parametrize("payload", [
    {"question": ""},
    {"question": "x" * 501},
    {"question": "hi", "mode": "jailbreak"},
    {"question": "hi", "projectId": "../etc/passwd"},
    {"question": "hi", "history": [{"role": "user", "content": "x"}] * 9},
    {"question": "hi", "history": [{"role": "system", "content": "x"}]},
])
def test_invalid_requests_rejected(payload):
    assert client_with(FakeGenerator()).post("/chat", json=payload).status_code == 422


def test_oversized_body_rejected():
    r = client_with(FakeGenerator()).post("/chat", content=b"x" * 40_000, headers={"Content-Type": "application/json"})
    assert r.status_code == 413


# ---------------------------------------------------------------- failure modes
def test_refusal_returns_polite_ungrounded_answer():
    body = client_with(FakeGenerator(exc=GenerationRefused())).post("/chat", json={"question": "SecureVault AI"}).json()
    assert body["grounded"] is False and body["sources"] == []


def test_generation_failure_is_502():
    assert client_with(FakeGenerator(exc=GenerationFailed("x"))).post("/chat", json={"question": "SecureVault AI"}).status_code == 502


def test_rate_limit_429_with_retry_after():
    c = client_with(FakeGenerator(), rate_limit_per_minute=2)
    codes = [c.post("/chat", json={"question": "SecureVault AI"}).status_code for _ in range(3)]
    assert codes == [200, 200, 429]
    r = c.post("/chat", json={"question": "SecureVault AI"})
    assert int(r.headers["Retry-After"]) >= 1 and r.json()["retryAfter"] >= 1


def test_cors_allows_only_configured_origins():
    c = client_with(FakeGenerator())
    ok = c.options("/chat", headers={"Origin": "https://nausheen1295.github.io", "Access-Control-Request-Method": "POST"})
    bad = c.options("/chat", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"})
    assert ok.headers.get("access-control-allow-origin") == "https://nausheen1295.github.io"
    assert "access-control-allow-origin" not in bad.headers


def test_rate_limiter_window_resets():
    t = [0.0]
    rl = RateLimiter(per_minute=1, per_day=100, clock=lambda: t[0])
    assert rl.check("a") is None and rl.check("a") is not None
    t[0] = 61
    assert rl.check("a") is None


# ---------------------------------------------------------------- LLM request shape (fake SDK client)
class FakeLLMClient:
    def __init__(self, response):
        self.sent = None
        outer = self

        class Msgs:
            async def create(self, **kw):
                outer.sent = kw
                return response
        self.beta = SimpleNamespace(messages=Msgs())
        self.messages = Msgs()


def _resp(stop="end_turn", payload=None):
    text = json.dumps(payload or {"answer": "A", "cited_ids": ["x"], "grounded": True})
    return SimpleNamespace(stop_reason=stop, content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=text)])


@pytest.mark.anyio
async def test_llm_request_uses_model_effort_schema_and_fallbacks():
    fake = FakeLLMClient(_resp())
    gen = LLMGenerator(SETTINGS, client=fake)
    out = await gen.generate(question="q", mode="recruiter", chunks=CHUNKS[:2], history=[])
    assert out == Generation(answer="A", cited_ids=["x"], grounded=True)
    sent = fake.sent
    assert sent["model"] == SETTINGS.model
    assert sent["output_config"]["effort"] == "low"
    assert sent["output_config"]["format"]["type"] == "json_schema"
    assert sent["betas"] == ["server-side-fallback-2026-07-01"] and sent["fallbacks"] == "default"
    assert "thinking" not in sent and "temperature" not in sent
    assert sent["messages"][-1]["role"] == "user" and "<documents>" in sent["messages"][-1]["content"]


@pytest.mark.anyio
@pytest.mark.parametrize("stop,exc", [("refusal", GenerationRefused), ("max_tokens", GenerationFailed)])
async def test_llm_stop_reasons(stop, exc):
    with pytest.raises(exc):
        await LLMGenerator(SETTINGS, client=FakeLLMClient(_resp(stop))).generate(question="q", mode="simple", chunks=CHUNKS[:1], history=[])


def test_history_never_starts_with_assistant():
    msgs = build_messages("q", "simple", CHUNKS[:1], [HistoryTurn(role="nexa", content="hi"), HistoryTurn(role="user", content="u")])
    assert [m["role"] for m in msgs] == ["user", "user"]


def test_no_secrets_in_source():
    import pathlib
    for f in pathlib.Path(__file__).resolve().parent.parent.joinpath("app").glob("*.py"):
        assert "sk-ant-" not in f.read_text(encoding="utf-8")
