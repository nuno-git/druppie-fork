/**
 * Integration test for the LLM proxy's retry/back-off/keepalive behaviour.
 *
 * Drives the REAL setupLlmProxy() handler end-to-end against a chaos
 * upstream that fails on a configurable schedule. Uses short back-off
 * delays (via LLM_RETRY_DELAYS_MS / LLM_RETRY_KEEPALIVE_MS) so the
 * suite finishes in ~10s instead of ~3min.
 *
 * Run:
 *   LLM_RETRY_DELAYS_MS=200,400,800 \
 *   LLM_RETRY_KEEPALIVE_MS=100 \
 *   LLM_RETRY_BUDGET_MS=10000 \
 *   npx tsx tests/proxy/retry-integration.test.ts
 *
 * Cases:
 *   1. Eventual success — chaos 429s N times, proxy retries, request
 *      succeeds. Asserts: retry count, elapsed ≥ sum of back-offs,
 *      exactly one upstream success at the end.
 *   2. Keepalive during back-off — streaming client must see SSE comment
 *      lines before the real data chunks. Proves opencode won't idle-out.
 *   3. Client disconnects mid-retry — chaos fails forever; after a few
 *      retries the client closes its socket. Asserts the upstream stops
 *      receiving further requests (we abandoned the retry loop).
 *   4. Per-call counter partitioning — two concurrent requests with
 *      different `id` tokens don't interfere with each other.
 */

import http from "node:http";
import { spawn, type ChildProcess } from "node:child_process";
import { setTimeout as delay } from "node:timers/promises";
import express from "express";
import { CredentialStore } from "../../src/credentials/credential-store.js";
import { setupLlmProxy } from "../../src/proxy/llm-proxy.js";

const CHAOS_PORT = 9970;
const PROXY_PORT = 9971;
const SESSION_ID = "test-session";
const PROVIDER = "openai"; // Reuse OpenAI-compat auth injection
const CHAOS_URL = `http://127.0.0.1:${CHAOS_PORT}`;

// ────────────────────────────────────────────────────────────────────────
// Minimal test harness (no vitest) — total failures = nonzero exit.
// ────────────────────────────────────────────────────────────────────────

let passed = 0;
let failed = 0;
const failures: string[] = [];

async function test(name: string, fn: () => Promise<void>): Promise<void> {
  process.stdout.write(`• ${name} ... `);
  const started = Date.now();
  try {
    await fn();
    const ms = Date.now() - started;
    console.log(`OK (${ms}ms)`);
    passed++;
  } catch (err) {
    const ms = Date.now() - started;
    const msg = err instanceof Error ? err.stack || err.message : String(err);
    console.log(`FAIL (${ms}ms)\n  ${msg}`);
    failed++;
    failures.push(`${name}: ${msg}`);
  }
}

function assert(cond: unknown, msg: string): asserts cond {
  if (!cond) throw new Error(`Assertion failed: ${msg}`);
}

// ────────────────────────────────────────────────────────────────────────
// Chaos server process management
// ────────────────────────────────────────────────────────────────────────

let chaos: ChildProcess | null = null;

async function startChaos(): Promise<void> {
  chaos = spawn(
    "npx",
    ["tsx", new URL("./chaos-upstream.ts", import.meta.url).pathname, "--port", String(CHAOS_PORT)],
    { stdio: ["ignore", "inherit", "inherit"] }
  );
  // Poll until it's up
  for (let i = 0; i < 50; i++) {
    try {
      await fetchJson(`${CHAOS_URL}/_counters/ping`);
      return;
    } catch {
      await delay(100);
    }
  }
  throw new Error("chaos server did not start");
}

async function stopChaos(): Promise<void> {
  if (chaos) {
    chaos.kill("SIGTERM");
    await new Promise<void>((r) => chaos!.once("exit", () => r()));
    chaos = null;
  }
}

async function fetchJson(url: string, init?: RequestInit): Promise<any> {
  const res = await fetch(url, init);
  if (!res.ok) throw new Error(`${url} → ${res.status}`);
  return res.json();
}

async function resetChaos(): Promise<void> {
  await fetch(`${CHAOS_URL}/_reset`);
}

async function getChaosCounter(id: string): Promise<{ requests: number; failures: number }> {
  return fetchJson(`${CHAOS_URL}/_counters/${id}`);
}

// ────────────────────────────────────────────────────────────────────────
// Proxy setup
// ────────────────────────────────────────────────────────────────────────

let proxyServer: http.Server | null = null;
let proxyKey = "";

function startProxy(): Promise<void> {
  const app = express();
  const store = new CredentialStore();
  const keys = store.store(SESSION_ID, {
    llm: [{ provider: PROVIDER, apiKey: "test-key", baseUrl: CHAOS_URL }],
  });
  proxyKey = keys.llmProxyKey!;
  setupLlmProxy(app, store);
  return new Promise((resolve) => {
    proxyServer = app.listen(PROXY_PORT, () => resolve());
  });
}

async function stopProxy(): Promise<void> {
  if (proxyServer) {
    await new Promise<void>((r) => proxyServer!.close(() => r()));
    proxyServer = null;
  }
}

function proxyUrl(): string {
  return `http://127.0.0.1:${PROXY_PORT}/llm-proxy/${proxyKey}/${PROVIDER}/chat/completions`;
}

interface ChaosOpts {
  id: string;
  fail?: number;
  status?: number;
  hang?: number;
  drop?: number;
}

/** Build an OpenAI-shaped request body with a top-level `chaos` object.
 *  The proxy forwards the body as-is (modulo provider-prefix model rewrite),
 *  so chaos-upstream can read the schedule from the body even though the
 *  querystring is stripped by the proxy. */
function openaiBody(stream: boolean, chaos: ChaosOpts): string {
  return JSON.stringify({
    model: "chaos-model",
    messages: [{ role: "user", content: "hi" }],
    stream,
    chaos,
  });
}

// ────────────────────────────────────────────────────────────────────────
// Tests
// ────────────────────────────────────────────────────────────────────────

async function main() {
  await startChaos();
  await startProxy();
  try {
    await test("eventual success after N 429s (buffered)", async () => {
      await resetChaos();
      const id = "t1";
      const started = Date.now();
      const res = await fetch(proxyUrl(), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: openaiBody(false, { id, fail: 3, status: 429 }),
      });
      const elapsed = Date.now() - started;
      assert(res.status === 200, `expected 200, got ${res.status}`);
      const body = await res.json();
      assert(body.choices?.[0]?.message?.content === "ok", "expected OK response body");
      const counter = await getChaosCounter(id);
      assert(counter.requests === 4, `expected 4 upstream requests, got ${counter.requests}`);
      assert(counter.failures === 3, `expected 3 failures, got ${counter.failures}`);
      // With LLM_RETRY_DELAYS_MS=200,400,800 the first 3 retries sleep
      // 200+400+800 = 1400ms total. Allow ±300ms slack.
      assert(elapsed >= 1400, `elapsed ${elapsed}ms < 1400ms — back-off not respected`);
      assert(elapsed < 5000, `elapsed ${elapsed}ms > 5000ms — took too long`);
    });

    await test("eventual success after N 429s (streaming, with keepalives)", async () => {
      await resetChaos();
      const id = "t2";
      // Use a longer sleep window so the keepalive path definitely fires
      const res = await fetch(proxyUrl(), {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Accept: "text/event-stream",
        },
        body: openaiBody(true, { id, fail: 2, status: 429 }),
      });
      assert(res.status === 200, `expected 200, got ${res.status}`);
      assert(res.body, "expected response body stream");
      const reader = res.body!.getReader();
      const decoder = new TextDecoder();
      let text = "";
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        text += decoder.decode(value, { stream: true });
      }
      // Keepalive comments are lines starting with ':'
      assert(/^:\s*keepalive/m.test(text), `expected SSE keepalive comments in stream, got:\n${text.slice(0, 500)}`);
      // Real SSE data arrived after the keepalives
      assert(/"content":"ok"/.test(text), "expected OK delta in stream");
      assert(/data: \[DONE\]/.test(text), "expected stream terminator");
      const counter = await getChaosCounter(id);
      assert(counter.requests === 3, `expected 3 upstream requests, got ${counter.requests}`);
    });

    await test("client disconnect during retry abandons upstream", async () => {
      await resetChaos();
      const id = "t3";
      const ctrl = new AbortController();
      // fail=20 means the proxy will keep retrying; we'll abort mid-loop
      const req = fetch(proxyUrl(), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: openaiBody(false, { id, fail: 20, status: 429 }),
        signal: ctrl.signal,
      }).catch(() => undefined);
      // Let it make a couple of attempts, then abort
      await delay(500);
      ctrl.abort();
      await req;
      const before = await getChaosCounter(id);
      // Wait long enough for any in-flight retries to complete
      await delay(2000);
      const after = await getChaosCounter(id);
      assert(
        after.requests === before.requests,
        `upstream saw ${after.requests - before.requests} extra requests after client disconnect — should be 0`
      );
    });

    await test("parallel requests don't corrupt counters", async () => {
      await resetChaos();
      const [r1, r2] = await Promise.all([
        fetch(proxyUrl(), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: openaiBody(false, { id: "pA", fail: 1, status: 429 }),
        }),
        fetch(proxyUrl(), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: openaiBody(false, { id: "pB", fail: 2, status: 429 }),
        }),
      ]);
      assert(r1.status === 200 && r2.status === 200, "both should succeed");
      await r1.json();
      await r2.json();
      const cA = await getChaosCounter("pA");
      const cB = await getChaosCounter("pB");
      assert(cA.requests === 2, `A expected 2 requests, got ${cA.requests}`);
      assert(cB.requests === 3, `B expected 3 requests, got ${cB.requests}`);
    });
  } finally {
    await stopProxy();
    await stopChaos();
  }

  console.log();
  console.log(`${passed} passed, ${failed} failed`);
  if (failed > 0) {
    console.log("\nFailures:");
    for (const f of failures) console.log("  - " + f);
    process.exit(1);
  }
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
