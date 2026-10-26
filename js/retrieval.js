/* ==========================================================================
   NEXA — BM25 retrieval, a line-for-line port of backend/app/retrieval.py so
   the website's documentation search ranks exactly like the API does.
   Pure functions, no DOM (tested in tests/).
   ========================================================================== */

const TOKEN = /[a-z0-9][a-z0-9+#.-]*/g;
const STOP = new Set(("the a an and or of to in on for with is are was were be been what which how why did does do you your she her " +
  "nausheen nausheen's me show tell about explain use used using project projects like i'm im this that it its " +
  "can could would should will from by as at").split(" "));
const SYNONYMS = {
  ai: ["artificial", "intelligence", "llm", "rag", "ml"],
  cybersecurity: ["security", "encryption", "cryptography", "threat"],
  security: ["cybersecurity", "encryption"],
  db: ["database"],
  challenge: ["challenges"],
  decision: ["decisions"],
  stack: ["technologies"],
  tech: ["technologies"],
  study: ["education", "degree", "university"], studied: ["education", "degree", "university"],
  studying: ["education", "degree", "university"], university: ["education", "degree"],
  college: ["education", "university"], degree: ["education"], qualification: ["education", "degree"],
  work: ["experience", "intern"], worked: ["experience", "intern"], job: ["experience"],
  internship: ["intern", "experience"], reach: ["contact", "email"], contact: ["email", "linkedin"],
  hire: ["contact", "opportunities"], based: ["location"], live: ["based", "location"],
  skills: ["skills"], languages: ["languages", "python", "java"],
};

export function tokenize(text) {
  return (String(text).toLowerCase().match(TOKEN) || [])
    .map((t) => t.replace(/^[.-]+|[.-]+$/g, ""))
    .filter((t) => t.length > 1 && !STOP.has(t));
}

const counter = (tokens) => { const m = new Map(); tokens.forEach((t) => m.set(t, (m.get(t) || 0) + 1)); return m; };

/** Okapi BM25 with title boosting, synonym expansion and project focus. */
export class BM25 {
  constructor(chunks, { k1 = 1.4, b = 0.75, minScore = 1.0 } = {}) {
    this.chunks = chunks;
    Object.assign(this, { k1, b, minScore });
    this.docs = chunks.map((c) => counter(tokenize(`${c.title} ${c.title} ${c.text}`))); // title counted twice = boost
    this.lens = this.docs.map((d) => [...d.values()].reduce((a, v) => a + v, 0));
    this.avg = this.lens.reduce((a, v) => a + v, 0) / Math.max(this.lens.length, 1);
    const df = new Map();
    this.docs.forEach((d) => d.forEach((_, t) => df.set(t, (df.get(t) || 0) + 1)));
    const n = chunks.length;
    this.idf = new Map([...df].map(([t, f]) => [t, Math.log(1 + (n - f + 0.5) / (f + 0.5))]));
    this.byId = new Map(chunks.map((c) => [c.id, c]));
    this.names = new Map(chunks.filter((c) => c.projectId).map((c) => [c.projectId, c.title.split(" — ")[0].toLowerCase()]));
  }

  score(i, terms) {
    const doc = this.docs[i], len = this.lens[i];
    let s = 0;
    for (const t of terms) {
      const tf = doc.get(t);
      if (tf) s += this.idf.get(t) * tf * (this.k1 + 1) / (tf + this.k1 * (1 - this.b + this.b * len / this.avg));
    }
    return s;
  }

  /** Returns [{chunk, score}] best first. */
  search(query, { k = 6, projectId = null } = {}) {
    const base = tokenize(query);
    const terms = [...base, ...base.flatMap((t) => SYNONYMS[t] || [])];
    if (!terms.length) return [];
    const q = query.toLowerCase();
    let focus = projectId;
    if (!focus) for (const [pid, name] of this.names) if (name && q.includes(name)) { focus = pid; break; }

    const scored = [];
    this.chunks.forEach((chunk, i) => {
      if (projectId && chunk.projectId !== projectId && chunk.projectId != null) return;
      let s = this.score(i, terms);
      if (focus && chunk.projectId === focus) s *= 1.6;
      if (s >= this.minScore) scored.push({ chunk, score: s });
    });
    scored.sort((a, b) => b.score - a.score);
    const top = scored.slice(0, k);

    // Whenever a project is in play, include its "not yet documented" chunk.
    const pids = new Set(top.map((h) => h.chunk.projectId).filter(Boolean));
    if (focus) pids.add(focus);
    for (const pid of pids) {
      const gap = this.byId.get(`${pid}:undocumented`);
      if (gap && !top.some((h) => h.chunk.id === gap.id)) top.push({ chunk: gap, score: 0 });
    }
    return top;
  }
}

/** Picks the sentences of a passage that best match the question (for compact offline answers). */
export function bestSentences(text, query, max = 3) {
  const q = new Set(tokenize(query).flatMap((t) => [t, ...(SYNONYMS[t] || [])]));
  const sentences = String(text).split(/(?<=[.!?])\s+|\n+/).map((s) => s.trim()).filter((s) => s.length > 3);
  const scored = sentences.map((s, i) => ({ s, i, n: tokenize(s).filter((t) => q.has(t)).length }));
  const keep = scored.filter((x) => x.n > 0).sort((a, b) => b.n - a.n || a.i - b.i).slice(0, max).sort((a, b) => a.i - b.i);
  return (keep.length ? keep : scored.slice(0, max)).map((x) => x.s);
}
