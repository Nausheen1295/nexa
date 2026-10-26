/* ==========================================================================
   NEXA — chat app.
   Online:  questions go to the NEXA API (RAG + LLM) and come back grounded,
            with sources verified server-side.
   Offline: a clearly labelled documentation search (the same BM25 ranking the
            API uses) shows the matching passages. It never imitates AI.
   ========================================================================== */
import { initTheme, esc } from "./theme.js";
import { NEXA_CONFIG as CFG } from "./config.js";
import { BM25, bestSentences } from "./retrieval.js";

const $ = (id) => document.getElementById(id);

const MODES = [
  { id: "recruiter", label: "Recruiter", hint: "Impact, skills and role, without jargon." },
  { id: "developer", label: "Developer", hint: "Stack, implementation and trade-offs." },
  { id: "simple", label: "Simple", hint: "Explained like you're new to tech." },
  { id: "architecture", label: "Architecture", hint: "Components, data flow and design." },
  { id: "interview", label: "Interview", hint: "Ask interview questions; NEXA answers from the documented work, in Nausheen's voice." },
];
const SUGGESTIONS = {
  recruiter: ["What has Nausheen built?", "Which projects use AI?", "Tell me about her internships", "What is she studying?"],
  developer: ["What technologies does SecureVault AI use?", "How does MindScape AI find related notes?", "How does FloraMind run models in the browser?", "What data sources does EarthPulse use?"],
  simple: ["Explain SecureVault AI simply", "What does InsightForge do?", "What is NEXA?", "What does FloraMind AI do?"],
  architecture: ["Explain the architecture of SecureVault AI", "How is NEXA's RAG pipeline built?", "How does EarthPulse fetch live data?", "Where does encryption happen in SecureVault AI?"],
  interview: ["Tell me about a technical challenge you solved.", "What security mechanisms did you implement?", "How did you test your projects?", "How would you scale NEXA?"],
};
// Questions about things that may be undocumented → the gap they map to.
const INTENTS = [
  [/challeng|difficult|hardest|problem you (faced|solved)/i, "technical challenges"],
  [/database|\bdb\b|storage engine|\bsql\b/i, "database choice"],
  [/\brole\b|did you (do|build)|team|solo/i, "Nausheen's role"],
  [/why .*(choose|chose|use|pick)|decision|trade-?off/i, "engineering decisions"],
  [/result|impact|metric|users/i, "results or metrics"],
];

let mode = "recruiter";
let projectId = "";
let online = false;
let busy = false;
let index = null;
let chunks = [];
const history = [];

initTheme($("themeToggle"));

/* ------------------------------------------------------------ knowledge */
async function loadKnowledge() {
  for (const url of [CFG.knowledgeUrl, CFG.bundledKnowledge]) {
    try {
      const res = await fetch(url, { cache: "no-cache" });
      if (!res.ok) continue;
      const data = await res.json();
      if (data.version !== 1 || !Array.isArray(data.chunks)) continue;
      chunks = data.chunks;
      index = new BM25(chunks);
      const projects = new Map(chunks.filter((c) => c.projectId).map((c) => [c.projectId, c.title.split(" — ")[0]]));
      $("project").innerHTML = '<option value="">All projects</option>' +
        [...projects].sort((a, b) => a[1].localeCompare(b[1])).map(([id, name]) => `<option value="${esc(id)}">${esc(name)}</option>`).join("");
      return;
    } catch { /* try the next source */ }
  }
  addNexa('<p class="note error">The knowledge base couldn\'t be loaded. Check your connection and reload.</p>');
}

/* --------------------------------------------------------------- status */
function setStatus(state, text) {
  const el = $("status");
  el.dataset.state = state;
  el.querySelector("span").textContent = text;
  el.title = text;
  $("modeNote").textContent = state === "online"
    ? "AI answers: generated only from the retrieved documentation, with verified sources."
    : "Documentation search: answers are passages from the portfolio's project documentation.";
}

async function timedFetch(url, opts = {}, ms = CFG.timeoutMs) {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), ms);
  try { return await fetch(url, { ...opts, signal: ctrl.signal }); } finally { clearTimeout(t); }
}

async function checkBackend() {
  // HTTPS in production; plain http only for a backend on this machine.
  const ok = typeof CFG.endpoint === "string" && (/^https:\/\//.test(CFG.endpoint) || /^http:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/.test(CFG.endpoint));
  if (!ok) {
    setStatus("offline", "Documentation search");
    return;
  }
  setStatus("waking", "Connecting to AI…");
  try {
    const res = await timedFetch(`${CFG.endpoint}/health`, { headers: { Accept: "application/json" } }, CFG.wakeTimeoutMs);
    online = res.ok;
  } catch { online = false; }
  setStatus(online ? "online" : "offline", online ? "AI online" : "Documentation search (AI offline)");
}

/* ----------------------------------------------------------------- modes */
function renderModes() {
  $("modes").innerHTML = MODES.map((m) => `<button type="button" role="radio" data-mode="${m.id}" aria-checked="${m.id === mode}">${m.label}</button>`).join("");
  $("modeHint").textContent = MODES.find((m) => m.id === mode).hint;
  $("suggestions").innerHTML = SUGGESTIONS[mode].map((q) => `<button class="chip" type="button" data-q="${esc(q)}">${esc(q)}</button>`).join("");
}
$("modes").addEventListener("click", (e) => {
  const b = e.target.closest("[data-mode]");
  if (!b) return;
  mode = b.dataset.mode;
  renderModes();
});
$("modes").addEventListener("keydown", (e) => {
  const d = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
  if (!d) return;
  const i = (MODES.findIndex((m) => m.id === mode) + d + MODES.length) % MODES.length;
  mode = MODES[i].id;
  renderModes();
  $("modes").querySelector(`[data-mode="${mode}"]`).focus();
});
$("project").addEventListener("change", (e) => { projectId = e.target.value; });
$("suggestions").addEventListener("click", (e) => { const b = e.target.closest("[data-q]"); if (b) ask(b.dataset.q); });

/* ---------------------------------------------------------------- thread */
function addUser(text) {
  $("welcome").classList.add("compact");
  $("thread").insertAdjacentHTML("beforeend", `<li class="msg user"><div class="bubble">${esc(text)}</div></li>`);
}
function addNexa(html) {
  $("thread").insertAdjacentHTML("beforeend", `<li class="msg nexa"><span class="avatar" aria-hidden="true"></span><div class="bubble">${html}</div></li>`);
  const last = $("thread").lastElementChild;
  last.scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "nearest" });
  return last;
}
/** Light markdown: paragraphs, bullet lists and **bold** on escaped text. */
function md(text) {
  return esc(text).split(/\n{2,}/).map((block) => {
    const lines = block.split("\n");
    if (lines.every((l) => /^\s*[-•*] /.test(l))) return `<ul>${lines.map((l) => `<li>${l.replace(/^\s*[-•*] /, "")}</li>`).join("")}</ul>`;
    return `<p>${lines.join("<br>")}</p>`;
  }).join("").replace(/\*\*(.+?)\*\*/g, "<b>$1</b>");
}
const sourceLinks = (list) => list.length
  ? `<div class="sources">${list.map((s) => `<a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.title)}</a>`).join("")}</div>` : "";

/* ------------------------------------------------------------------ ask */
async function ask(raw) {
  const question = raw.trim().slice(0, CFG.maxQuestionLength);
  if (!question || busy) return;
  busy = true;
  $("question").value = "";
  autosize();
  addUser(question);
  const typing = addNexa('<span class="typing" aria-label="NEXA is answering"><span></span><span></span><span></span></span>');
  let html;
  if (online) html = await askBackend(question);
  if (!html) html = answerFromDocs(question);
  typing.querySelector(".bubble").innerHTML = html;
  history.push({ role: "user", content: question });
  history.push({ role: "nexa", content: typing.querySelector(".bubble").textContent.slice(0, 1500) });
  while (history.length > CFG.maxHistory) history.shift();
  busy = false;
}

async function askBackend(question) {
  try {
    const res = await timedFetch(`${CFG.endpoint}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ question, mode, projectId: projectId || null, history: history.slice(-CFG.maxHistory) }),
    });
    const data = await res.json().catch(() => ({}));
    if (res.status === 429) return `<p class="note warn">${esc(data.error || "Too many questions — please wait a moment.")}</p>`;
    if (!res.ok || typeof data.answer !== "string") throw new Error(data.error || res.status);
    return `<span class="kind ai">AI answer${data.grounded ? " · from documentation" : ""}</span>${md(data.answer)}${sourceLinks(data.sources || [])}`;
  } catch {
    // Fall back to documentation search for this question, and say so.
    online = false;
    setStatus("offline", "Documentation search (AI offline)");
    return null;
  }
}

/** Chunk text as prose: drops the status line and folds "Label:" + bullets into one sentence. */
function readable(text) {
  const out = [];
  let label = null, items = [];
  const flush = () => {
    if (items.length) out.push(`${label ? `${label}: ` : ""}${items.join("; ")}.`);
    else if (label) out.push(`${label}.`);
    label = null; items = [];
  };
  for (const line of text.split("\n")) {
    if (/^Project: .+ Status: /.test(line) || /^(Source code|Live demo|Live site): https?:/.test(line)) continue;
    if (/^\s*[-•*] /.test(line)) { items.push(line.replace(/^\s*[-•*] /, "").replace(/\.$/, "")); continue; }
    flush();
    if (/:\s*$/.test(line)) label = line.replace(/:\s*$/, "");
    else if (line.trim()) out.push(line.trim());
  }
  flush();
  return out.join("\n");
}

function answerFromDocs(question) {
  if (!index) return '<p class="note error">The knowledge base isn\'t loaded yet.</p>';
  const hits = index.search(question, { k: 6, projectId: projectId || null });
  // When a project is named (or chosen), only its own passages are shown.
  const lower = question.toLowerCase();
  const focus = projectId || [...index.names].find(([, name]) => name && lower.includes(name))?.[0] || null;
  let real = hits.filter((h) => h.score > 0 && !h.chunk.id.endsWith(":undocumented") && (!focus || h.chunk.projectId === focus));
  if (focus && /^(what is|what's|explain|tell me about|describe)\b/i.test(question.trim())) {
    const overview = chunks.find((c) => c.id === `${focus}:overview`);
    if (overview) real = [{ chunk: overview, score: 1 }, ...real.filter((h) => h.chunk.id !== overview.id)];
  }
  const gaps = hits.filter((h) => h.chunk.id.endsWith(":undocumented"));
  const intent = INTENTS.find(([re]) => re.test(question));
  // A gap only matters when the question asks for exactly that missing detail.
  const gapNotes = intent ? gaps.filter((g) => g.chunk.text.includes(intent[1])).map((g) => {
    const name = g.chunk.title.split(" — ")[0];
    return `<p class="gap"><b>Not documented yet:</b> ${esc(intent[1])} for ${esc(name)}. I won't guess. <a href="${esc(g.chunk.url)}" target="_blank" rel="noopener">See the case study</a> or ask Nausheen directly.</p>`;
  }) : [];
  // Asked for a detail the named project hasn't documented: say so, and don't pad with loosely related passages.
  if (focus && gapNotes.length) real = [];
  if (!real.length && !gapNotes.length) {
    return `<span class="kind">Documentation search</span><p>That isn't covered in Nausheen's documented projects, so I won't guess. Try asking about a specific project, technology or skill, or <a href="${esc(CFG.portfolioUrl)}#contact" target="_blank" rel="noopener">contact her directly</a>.</p>`;
  }
  const seen = new Set();
  const passages = real.filter((h) => !seen.has(h.chunk.url + h.chunk.section) && seen.add(h.chunk.url + h.chunk.section)).slice(0, 3).map(({ chunk }) => {
    const lines = bestSentences(readable(chunk.text), question, 3);
    return `<div class="passage"><h3><a href="${esc(chunk.url)}" target="_blank" rel="noopener">${esc(chunk.title)}</a></h3><p>${lines.map(esc).join(" ")}</p></div>`;
  });
  return `<span class="kind">Documentation search · best matches</span>${passages.join("")}${gapNotes.join("")}`;
}

/* -------------------------------------------------------------- composer */
const q = $("question");
function autosize() { q.style.height = "auto"; q.style.height = `${Math.min(q.scrollHeight, 160)}px`; }
q.addEventListener("input", autosize);
q.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); ask(q.value); } });
$("composer").addEventListener("submit", (e) => { e.preventDefault(); ask(q.value); });
$("clearBtn").addEventListener("click", () => {
  $("thread").innerHTML = "";
  history.length = 0;
  $("welcome").classList.remove("compact");
  q.focus();
});

/* ----------------------------------------------------------------- start */
renderModes();
const initial = new URLSearchParams(location.search).get("q");
loadKnowledge().then(() => { if (initial) ask(initial); });
checkBackend();
