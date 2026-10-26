# NEXA backend

The API behind **NEXA**, the assistant on the [NEXUS portfolio](https://nausheen1295.github.io/portfolio/) and the [NEXA site](https://nausheen1295.github.io/nexa/). It answers questions about Nausheen's projects
**only from documented sources**, and says so when something isn't documented.

GitHub Pages only serves static files, so this service is deployed separately. The websites call it through
their `config.js` endpoint.

```
Browser (GitHub Pages)                         NEXA backend (this folder)
──────────────────────                         ──────────────────────────────────────────────
js/nexa/ui.js ── js/nexa/client.js ──HTTPS──►  FastAPI  /health · /chat
                                               │  validation (pydantic) · CORS allow-list
                                               │  per-visitor rate limiting · body-size cap
                                               ▼
                                               Retriever (BM25 today → vector DB later)
                                               │  searches knowledge/portfolio.json
                                               ▼
                                               Generator → LLM (provider SDK)    
                                               │  grounded system prompt · JSON answer + cited ids
                                               ▼
                                               {answer, sources[], grounded}
```

## How an answer is produced
1. **Validate.** The question is 1–500 characters, `mode` is one of five values, `projectId` is a slug, and history holds at most 8 turns.
2. **Retrieve.** The service finds the most relevant knowledge chunks. A project named in the question, or picked as context, gets priority. That project's *"not yet documented"* chunk is always included, so NEXA can say "that isn't documented" and cite it.
3. **Short-circuit.** If nothing relevant is found, the service returns an honest "not documented" reply **without calling the model** (no cost, no hallucination).
4. **Generate.** The LLM gets the static system prompt (grounding rules) plus the retrieved documents and the question, then returns structured JSON with `answer`, `cited_ids` and `grounded`.
5. **Verify citations.** Only ids that were actually retrieved become sources, so the model can't invent a source. An answer with no valid sources is marked `grounded: false`.

### Model settings
| Setting | Default | Why |
|---|---|---|
| `NEXA_MODEL` | provider model id (see `.env.example`) | Most capable default model. |
| `NEXA_EFFORT` | `low` | Short, grounded chat answers don't need deep reasoning. Raise it if answers feel thin. |
| `NEXA_FALLBACKS` | `true` | Server-side refusal fallback (`fallbacks: "default"`). If a safety classifier declines, the API retries on the provider's recommended fallback model. |

`stop_reason` is checked before any content is read. A refusal returns a polite, ungrounded reply, and a truncated answer returns a 502.

## Knowledge base
The portfolio generates the knowledge file from its project data and READMEs (`tools/export-knowledge.mjs` in the
portfolio repo) and publishes it at `https://nausheen1295.github.io/portfolio/knowledge/portfolio.json`.

- **Live copy:** with `NEXA_KNOWLEDGE_URL` set, the service loads that file at startup, so portfolio updates reach NEXA with a restart.
- **Fallback:** `knowledge/portfolio.json` here is a bundled copy, used if the download fails.
- **Status line:** every chunk starts with its project's status, so the model can't present plans as finished work.

## Run locally
```bash
python -m venv .venv
.venv\Scripts\activate            # macOS/Linux: source .venv/bin/activate
pip install -r requirements-dev.txt
pytest                            # 34 tests, no API key or network needed
copy .env.example .env            # then set the API key in .env
uvicorn app.main:app --reload --port 8787
```
Without credentials, `/health` returns **503** and the website stays in its labelled documentation-search mode.

## Deploy on Render (free plan)
1. Open **https://render.com/deploy?repo=https://github.com/Nausheen1295/nexa** (or Render → *New* → *Blueprint* and pick this repo). `render.yaml` describes the service.
2. When Render asks, fill in the two secret values:
   - `ANTHROPIC_API_KEY`: your LLM provider API key. It only ever lives in Render.
   - `NEXA_MODEL`: the model id to use, from your provider's documentation.
3. Wait for the deploy, then open `https://<service>.onrender.com/health`; it should return `{"status":"ok"}`.
4. Put that `https://<service>.onrender.com` address in **`js/config.js`** in this repo and **`js/nexa/config.js`** in the portfolio repo (`endpoint`), and push. Both sites switch to AI answers automatically.

The free plan sleeps after 15 minutes idle; the first question after that can take up to a minute while it wakes. The sites wait for it and answer from documentation meanwhile.
Other hosts (Fly.io, Railway, Cloud Run) work too: deploy `backend/` with its `Dockerfile`, set the variables from `.env.example`, and use `/healthz` as the health check.

## Security checklist
- **API key:** stays server-side only. Nothing in `app/` or the website contains secrets (a test enforces this).
- **CORS:** only the portfolio's origin (plus localhost) may call the API from a browser.
- **Input limits:** strict validation, a 32 KB body cap and a 500-character question limit.
- **Rate limiting:** per visitor, per minute and per day. It's in-memory, so use Redis if you run more than one instance.
- **Prompt injection:** documents and questions are treated as data. The system prompt tells the model to ignore instructions inside them, and citations are verified server-side.
- **Exposure and logging:** the auto-generated `/docs` pages are disabled, and logs record mode, counts and latency, never the question text.
- **Cost control:** rate limits, a `NEXA_MAX_TOKENS` cap, low effort, and a no-match short-circuit that skips the model entirely.

## Files
```
app/config.py      settings from environment variables
app/schemas.py     request/response models (the API contract)
app/knowledge.py   loads knowledge/portfolio.json
app/retrieval.py   Retriever interface + BM25 implementation
app/prompts.py     system prompt, mode instructions, answer JSON schema
app/generator.py   LLM call (structured output, fallbacks, stop-reason handling)
app/ratelimit.py   sliding-window rate limiter
app/main.py        FastAPI app: /health, /chat
tests/             API, safety and retrieval tests
```
