/**
 * Chaos upstream — a fake LLM provider that fails on a configurable schedule.
 *
 * Used by the proxy retry integration tests to exercise the real LLM-proxy
 * retry loop without calling a real provider. Each inbound request picks
 * its fault schedule from query params:
 *
 *   ?fail=N&status=429        First N requests respond with `status` (default 429).
 *                             Request N+1 succeeds.
 *   ?hang=ms                  Hold the connection open for `ms` before responding
 *                             (exercises connect/read timeouts).
 *   ?drop=N                   First N requests accept the connection then reset
 *                             it (socket destroy) — exercises ECONNRESET retries.
 *   ?id=<token>               Partition counters by token so parallel tests
 *                             don't interfere. Required.
 *
 * Admin endpoints:
 *   GET  /_counters/<id>      Returns { requests, failures } as JSON.
 *   POST /_reset              Clears all counters.
 *
 * Successful responses stream a minimal OpenAI-compatible SSE completion.
 *
 * Run:
 *   npx tsx tests/proxy/chaos-upstream.ts --port 9999
 */

import http from "node:http";
import { URL } from "node:url";

interface Counters {
  requests: number;
  failures: number;
}

const counters = new Map<string, Counters>();

function getCounter(id: string): Counters {
  let c = counters.get(id);
  if (!c) {
    c = { requests: 0, failures: 0 };
    counters.set(id, c);
  }
  return c;
}

function writeSseChunk(res: http.ServerResponse, data: unknown): void {
  res.write(`data: ${JSON.stringify(data)}\n\n`);
}

function respondStreaming(res: http.ServerResponse, id: string): void {
  res.writeHead(200, {
    "Content-Type": "text/event-stream",
    "Cache-Control": "no-cache",
    Connection: "keep-alive",
  });
  writeSseChunk(res, {
    id: `chatcmpl-chaos-${id}`,
    object: "chat.completion.chunk",
    created: Math.floor(Date.now() / 1000),
    model: "chaos-model",
    choices: [
      { index: 0, delta: { role: "assistant", content: "ok" }, finish_reason: null },
    ],
  });
  writeSseChunk(res, {
    id: `chatcmpl-chaos-${id}`,
    object: "chat.completion.chunk",
    created: Math.floor(Date.now() / 1000),
    model: "chaos-model",
    choices: [{ index: 0, delta: {}, finish_reason: "stop" }],
  });
  res.write("data: [DONE]\n\n");
  res.end();
}

function respondBuffered(res: http.ServerResponse, id: string): void {
  res.writeHead(200, { "Content-Type": "application/json" });
  res.end(
    JSON.stringify({
      id: `chatcmpl-chaos-${id}`,
      object: "chat.completion",
      created: Math.floor(Date.now() / 1000),
      model: "chaos-model",
      choices: [
        {
          index: 0,
          message: { role: "assistant", content: "ok" },
          finish_reason: "stop",
        },
      ],
    })
  );
}

const portArg = process.argv.indexOf("--port");
const port = portArg >= 0 ? parseInt(process.argv[portArg + 1], 10) : 9999;

const server = http.createServer((req, res) => {
  const url = new URL(req.url || "/", `http://localhost:${port}`);

  // Admin routes
  if (url.pathname.startsWith("/_counters/")) {
    const id = url.pathname.replace("/_counters/", "");
    const c = counters.get(id) || { requests: 0, failures: 0 };
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify(c));
    return;
  }
  if (url.pathname === "/_reset") {
    counters.clear();
    res.writeHead(200, { "Content-Type": "text/plain" });
    res.end("reset");
    return;
  }

  // Fault config can come from (a) query params — useful for direct
  // curl testing of the chaos server — or (b) a top-level `chaos` object
  // in the JSON request body, which the LLM proxy forwards unchanged.
  // The body form is what end-to-end tests use because the proxy drops
  // the querystring when forwarding to the upstream.
  const qsId = url.searchParams.get("id");
  const qsFail = parseInt(url.searchParams.get("fail") || "0", 10);
  const qsStatus = parseInt(url.searchParams.get("status") || "429", 10);
  const qsHang = parseInt(url.searchParams.get("hang") || "0", 10);
  const qsDrop = parseInt(url.searchParams.get("drop") || "0", 10);

  const bodyChunks: Buffer[] = [];
  req.on("data", (chunk: Buffer) => bodyChunks.push(chunk));
  req.on("end", async () => {
    const body = Buffer.concat(bodyChunks).toString("utf8");
    let parsedBody: any = null;
    try {
      parsedBody = body ? JSON.parse(body) : null;
    } catch {
      // ignore — body form is optional
    }
    const chaos = (parsedBody && typeof parsedBody === "object" && parsedBody.chaos) || {};
    const id = chaos.id ?? qsId ?? "default";
    const failCount = chaos.fail ?? qsFail;
    const failStatus = chaos.status ?? qsStatus;
    const hangMs = chaos.hang ?? qsHang;
    const dropCount = chaos.drop ?? qsDrop;

    const counter = getCounter(id);
    counter.requests += 1;
    const prevFailures = counter.failures;

    if (hangMs > 0) {
      await new Promise((r) => setTimeout(r, hangMs));
    }

    if (prevFailures < dropCount) {
      counter.failures += 1;
      // Destroy the socket without responding — client sees ECONNRESET.
      req.socket.destroy();
      return;
    }

    if (prevFailures < failCount) {
      counter.failures += 1;
      res.writeHead(failStatus, { "Content-Type": "application/json" });
      res.end(
        JSON.stringify({
          error: {
            message: `Chaos: planned failure ${prevFailures + 1}/${failCount}`,
            type: "rate_limit_error",
            code: String(failStatus),
          },
        })
      );
      return;
    }

    const isStream = /"stream"\s*:\s*true/.test(body);
    if (isStream) respondStreaming(res, id);
    else respondBuffered(res, id);
  });
});

server.listen(port, () => {
  console.log(`[chaos-upstream] listening on :${port}`);
});

process.on("SIGTERM", () => {
  server.close(() => process.exit(0));
});
process.on("SIGINT", () => {
  server.close(() => process.exit(0));
});
