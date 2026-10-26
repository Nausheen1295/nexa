import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { BM25, tokenize, bestSentences } from "../js/retrieval.js";

const kb = JSON.parse(readFileSync(new URL("../knowledge/portfolio.json", import.meta.url), "utf8"));
// Expected rankings produced by backend/app/retrieval.py on the same knowledge file.
const parity = JSON.parse(readFileSync(new URL("./parity.json", import.meta.url), "utf8"));
const R = new BM25(kb.chunks);

test("tokenizer drops stop words and edge punctuation", () => {
  assert.deepEqual(tokenize("What is AES-256-GCM? Node.js."), ["aes-256-gcm", "node.js"]);
});

test("ranking matches the Python backend exactly", () => {
  for (const [q, expected] of Object.entries(parity)) {
    const got = q === "__focus" ? R.search("features", { k: 6, projectId: "earthpulse" }) : R.search(q, { k: 6 });
    assert.deepEqual(got.map((h) => h.chunk.id), expected.map(([id]) => id), q);
    got.forEach((h, i) => assert.ok(Math.abs(h.score - expected[i][1]) < 1e-4, `${q}: score ${h.chunk.id}`));
  }
});

test("gibberish finds nothing", () => {
  assert.deepEqual(R.search("zxqv plorbt"), []);
});

test("best sentences prefer matching ones", () => {
  assert.deepEqual(bestSentences("Cats sleep. Encryption uses AES. Dogs bark.", "encryption", 1), ["Encryption uses AES."]);
});
