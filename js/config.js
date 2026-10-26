/* ==========================================================================
   NEXA — site configuration. NEVER put API keys here: this file is public.
   Set `endpoint` to the deployed API (https://…onrender.com) to switch NEXA
   from documentation search to AI answers.
   ========================================================================== */
export const NEXA_CONFIG = {
  endpoint: null,
  // The portfolio publishes the knowledge base; the bundled copy is the fallback.
  knowledgeUrl: "https://nausheen1295.github.io/portfolio/knowledge/portfolio.json",
  bundledKnowledge: "knowledge/portfolio.json",
  portfolioUrl: "https://nausheen1295.github.io/portfolio/",
  timeoutMs: 25000,
  // Free hosting sleeps when idle; the first health check may need to wake it.
  wakeTimeoutMs: 70000,
  maxQuestionLength: 500,
  maxHistory: 8,
};
