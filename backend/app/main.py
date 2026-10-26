"""NEXA API — grounded Q&A over Nausheen's portfolio.

    GET  /healthz  → 200 while the process is running (host health checks)
    GET  /health   → 200 {"status": "ok"} when ready to answer, 503 otherwise
    POST /chat     → {answer, sources, grounded}   (contract: the portfolio's js/nexa/client.js)

Run locally:  uvicorn app.main:app --reload --port 8787
"""
from __future__ import annotations

import logging
import time

import anthropic
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import Settings
from .generator import LLMGenerator, GenerationFailed, GenerationRefused, Generator
from .knowledge import load_knowledge
from .ratelimit import RateLimiter
from .retrieval import BM25Retriever, Retriever
from .schemas import ChatRequest, ChatResponse, Source

log = logging.getLogger("nexa")

NOT_DOCUMENTED = ("That isn't covered in Nausheen's documented projects yet, so I won't guess. "
                  "Try asking about a specific project, technology or lab — or get in touch with her directly.")
MAX_BODY_BYTES = 32_000


def create_app(settings: Settings | None = None, *, retriever: Retriever | None = None,
               generator: Generator | None = None) -> FastAPI:
    settings = settings or Settings()
    chunks = load_knowledge(settings.knowledge_path, settings.knowledge_url) if retriever is None else []
    retriever = retriever or BM25Retriever(chunks)
    if generator is None and settings.llm_configured:
        generator = LLMGenerator(settings)
    limiter = RateLimiter(settings.rate_limit_per_minute, settings.rate_limit_per_day)

    app = FastAPI(title="NEXA API", version="1.0.0", docs_url=None, redoc_url=None)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "Accept"],
        max_age=600,
    )

    @app.middleware("http")
    async def guard(request: Request, call_next):
        length = request.headers.get("content-length")
        if length and length.isdigit() and int(length) > MAX_BODY_BYTES:
            return JSONResponse({"error": "Request too large."}, status_code=413)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        return response

    def client_key(request: Request) -> str:
        if settings.trust_proxy and (fwd := request.headers.get("x-forwarded-for")):
            return fwd.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    @app.get("/healthz")
    async def alive():
        # Liveness for the host's health check: the process is up, even before a key is set.
        return {"status": "alive"}

    @app.get("/health")
    async def health():
        if generator is None:
            return JSONResponse({"status": "unavailable"}, status_code=503)
        return {"status": "ok"}

    @app.post("/chat", response_model=ChatResponse)
    async def chat(body: ChatRequest, request: Request):
        retry = limiter.check(client_key(request))
        if retry is not None:
            return JSONResponse({"error": "Too many questions — please slow down.", "retryAfter": retry},
                                status_code=429, headers={"Retry-After": str(retry)})
        if generator is None:
            return JSONResponse({"error": "NEXA is not configured."}, status_code=503)

        question = " ".join(body.question.split())
        started = time.perf_counter()
        hits = retriever.search(question, k=settings.top_k, project_id=body.projectId)

        # Nothing relevant retrieved → answer honestly without calling the model at all.
        if not any(score > 0 for _, score in hits):
            return ChatResponse(answer=NOT_DOCUMENTED, sources=[], grounded=False)

        retrieved = [c for c, _ in hits]
        try:
            gen = await generator.generate(question=question, mode=body.mode, chunks=retrieved, history=body.history)
        except GenerationRefused:
            return ChatResponse(answer="I can't help with that one. Ask me about Nausheen's projects, skills or experience.",
                                sources=[], grounded=False)
        except GenerationFailed:
            log.warning("generation failed")
            return JSONResponse({"error": "NEXA couldn't answer right now."}, status_code=502)
        except anthropic.RateLimitError:
            return JSONResponse({"error": "NEXA is busy — please try again shortly.", "retryAfter": 30}, status_code=429,
                                headers={"Retry-After": "30"})
        except (anthropic.APIStatusError, anthropic.APIConnectionError) as e:
            log.warning("upstream error: %s", type(e).__name__)
            return JSONResponse({"error": "NEXA couldn't answer right now."}, status_code=502)

        # Only cite documents that were actually retrieved — the model can't invent a source.
        by_id = {c.id: c for c in retrieved}
        sources, seen = [], set()
        for cid in gen.cited_ids:
            c = by_id.get(cid)
            if c and c.url not in seen:
                seen.add(c.url)
                sources.append(Source(title=c.title, url=c.url))

        log.info("chat mode=%s project=%s docs=%d cited=%d grounded=%s %.0fms", body.mode, body.projectId,
                 len(retrieved), len(sources), gen.grounded, (time.perf_counter() - started) * 1000)
        return ChatResponse(answer=gen.answer, sources=sources, grounded=gen.grounded and bool(sources))

    return app


app = create_app()  # uvicorn entry point
