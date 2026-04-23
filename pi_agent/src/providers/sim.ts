/**
 * Sim LLM provider — a failure-injecting reverse proxy in front of the real
 * Z.AI endpoint. It does NOT fabricate responses; it forwards them.
 *
 * For each incoming request, it rolls the dice:
 *   - With `failureRate` probability, it returns a fake error (429 with
 *     Retry-After / 500 / 502 / 503) WITHOUT contacting upstream.
 *   - Otherwise, it streams the request through to the real Z.AI API and
 *     pipes the response back verbatim (SSE and all).
 *
 * So you get real model output on the good path, and authentic-looking
 * transient failures on the bad path — perfect for watching pi's retry
 * machinery cope with a flaky upstream while the agent still makes real
 * progress once retries succeed.
 *
 * Enable with ONESHOT_SIM_FAILURES=1. Tune with ONESHOT_SIM_FAILURE_RATE
 * (default 0.5). Upstream URL defaults to the real Z.AI coding endpoint.
 */
import { createServer, type Server, type IncomingHttpHeaders } from "node:http";
import { Readable } from "node:stream";
import { fetch as undiciFetch, Agent } from "undici";

export interface SimStats {
  total: number;
  failed: number;
  succeeded: number;
  byStatus: Record<number, number>;
}

export interface SimServer {
  port: number;
  baseUrl: string;
  stats: () => SimStats;
  stop: () => Promise<void>;
}

export interface SimOptions {
  /** 0-1. Default 0.5. */
  failureRate?: number;
  /** Which status codes to pick from. Default [429, 500, 502, 503]. */
  errorStatuses?: number[];
  /** Seconds to ask client to wait on 429. Default random 2-6. */
  retryAfterSec?: () => number;
  /** Upstream base URL. Default: real Z.AI coding endpoint. */
  upstreamBaseUrl?: string;
  /** Emit a log line per request? Default true. */
  verbose?: boolean;
}

const DEFAULT_UPSTREAM = "https://api.z.ai/api/coding/paas/v4";

export async function startSimServer(options: SimOptions = {}): Promise<SimServer> {
  const failureRate = options.failureRate ?? 0.5;
  const errorStatuses = options.errorStatuses ?? [429, 500, 502, 503];
  const retryAfterSec = options.retryAfterSec ?? (() => 2 + Math.floor(Math.random() * 5));
  const upstreamBaseUrl = (options.upstreamBaseUrl ?? DEFAULT_UPSTREAM).replace(/\/$/, "");
  const verbose = options.verbose ?? true;

  const agent = new Agent({ connectTimeout: 30_000 });
  const stats: SimStats = { total: 0, failed: 0, succeeded: 0, byStatus: {} };

  const server: Server = createServer((req, res) => {
    stats.total++;

    if (req.method !== "POST") {
      // Health / probe requests — just say OK.
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ ok: true }));
      return;
    }

    let bodyBuf = Buffer.alloc(0);
    req.on("data", (chunk: Buffer) => {
      bodyBuf = Buffer.concat([bodyBuf, chunk]);
    });
    req.on("end", async () => {
      const fail = Math.random() < failureRate;

      if (fail) {
        stats.failed++;
        const status = errorStatuses[Math.floor(Math.random() * errorStatuses.length)];
        stats.byStatus[status] = (stats.byStatus[status] ?? 0) + 1;
        const headers: Record<string, string> = { "Content-Type": "application/json" };
        if (status === 429) headers["Retry-After"] = String(retryAfterSec());
        res.writeHead(status, headers);
        res.end(JSON.stringify({
          error: {
            message: `sim: injected ${status}`,
            type: status === 429 ? "rate_limit_exceeded" : "server_error",
            code: `sim_${status}`,
          },
        }));
        if (verbose) console.log(`[sim] INJECT ${status}  (total=${stats.total} fail=${stats.failed} ok=${stats.succeeded})`);
        return;
      }

      // Forward to real upstream. Preserve path, method, and headers (including Authorization).
      const upstreamUrl = upstreamBaseUrl + (req.url ?? "");
      const forwardHeaders = cloneHeaders(req.headers);
      // Node's http lowercases all headers; undici will re-normalise. Strip hop-by-hop.
      delete forwardHeaders["host"];
      delete forwardHeaders["content-length"];
      delete forwardHeaders["connection"];

      try {
        const upstream = await undiciFetch(upstreamUrl, {
          method: "POST",
          headers: forwardHeaders,
          body: bodyBuf,
          dispatcher: agent,
        });
        stats.succeeded++;
        const upstreamStatus = upstream.status;
        stats.byStatus[upstreamStatus] = (stats.byStatus[upstreamStatus] ?? 0) + 1;
        const outHeaders: Record<string, string> = {};
        upstream.headers.forEach((v, k) => { outHeaders[k] = v; });
        res.writeHead(upstreamStatus, outHeaders);
        if (upstream.body) {
          Readable.fromWeb(upstream.body as any).pipe(res);
        } else {
          res.end();
        }
        if (verbose) console.log(`[sim] PROXY  ${upstreamStatus} → upstream  (total=${stats.total} fail=${stats.failed} ok=${stats.succeeded})`);
      } catch (err) {
        stats.failed++;
        stats.byStatus[599] = (stats.byStatus[599] ?? 0) + 1;
        res.writeHead(599, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ error: { message: `sim: upstream fetch failed: ${(err as Error).message}` } }));
        if (verbose) console.log(`[sim] UPSTREAM FAIL  ${(err as Error).message}`);
      }
    });
  });

  return new Promise((resolve, reject) => {
    server.on("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const addr = server.address();
      const port = typeof addr === "object" && addr ? addr.port : 0;
      if (!port) {
        reject(new Error("sim server failed to bind"));
        return;
      }
      resolve({
        port,
        baseUrl: `http://127.0.0.1:${port}`,
        stats: () => ({ ...stats, byStatus: { ...stats.byStatus } }),
        stop: () => new Promise((r) => server.close(() => r())),
      });
    });
  });
}

function cloneHeaders(h: IncomingHttpHeaders): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [k, v] of Object.entries(h)) {
    if (v === undefined) continue;
    out[k] = Array.isArray(v) ? v.join(", ") : v;
  }
  return out;
}
