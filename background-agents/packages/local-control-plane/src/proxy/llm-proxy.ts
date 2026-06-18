/**
 * LLM API proxy — injects stored API keys into LLM provider requests.
 *
 * Route: ALL /llm-proxy/:proxyKey/:provider/*
 *
 * Supports SSE streaming passthrough for streaming LLM responses.
 * Uses node:http/node:https for streaming to avoid Express buffering.
 *
 * Provider auth injection:
 * - Anthropic: x-api-key header + anthropic-version
 * - OpenAI-compatible (zai, openai, deepseek, deepinfra): Authorization: Bearer
 *
 * Resilience features:
 * - Per-session error tracking (C1) — consecutive 5xx trigger provider_unhealthy
 * - LLM result callbacks (C3) — feed session-level health tracking
 * - Transparent failover (A) — on 5xx or 429, try next provider in model chain
 */

import http from "node:http";
import https from "node:https";
import type { Express, Request, Response } from "express";
import type { CredentialStore, LlmCredentials } from "../credentials/credential-store.js";

const MAX_BODY_SIZE = 10 * 1024 * 1024; // 10 MB
const CONNECT_TIMEOUT_MS = 30_000;
const READ_TIMEOUT_MS = 300_000;

const CONSECUTIVE_ERROR_THRESHOLD = 3;

/**
 * Per-provider retry config. Retries against the SAME provider happen until
 * the wall-clock budget runs out, then we failover to the next provider in
 * the chain.
 *
 * Goal: an upstream outage (rate limit, 5xx, connection reset) should cause
 * the proxy to wait it out rather than bubble up a 502 to opencode within a
 * few minutes. The C3 watchdog in SessionInstance (LLM_FAILURE_TIMEOUT_MS,
 * default 24h) still decides when to give up and kill the sandbox.
 *
 * Back-off schedule grows then caps: 10s, 30s, 2min, 5min, 5min, 5min, ...
 * Override the budget per session via env LLM_RETRY_BUDGET_MS.
 */
const SAME_PROVIDER_RETRY_BUDGET_MS = parseInt(
  process.env.LLM_RETRY_BUDGET_MS || String(24 * 60 * 60 * 1000), // 24h
  10
);

/** Parse a CSV of millisecond values (e.g. "100,200,500") into a number array,
 *  or return null if the env var is unset / malformed. Used by the retry
 *  integration tests to shrink back-offs below 10s; prod defaults stand. */
function parseDelaysMs(raw: string | undefined): number[] | null {
  if (!raw) return null;
  const parts = raw.split(",").map((s) => parseInt(s.trim(), 10));
  if (parts.some((n) => !Number.isFinite(n) || n < 0)) return null;
  if (parts.length === 0) return null;
  return parts;
}
const SAME_PROVIDER_DELAYS_MS: number[] = parseDelaysMs(process.env.LLM_RETRY_DELAYS_MS) ?? [
  10_000, 30_000, 120_000, 300_000,
];

/** Keep-alive SSE comments sent to the client during back-off sleeps so its
 *  HTTP socket doesn't idle out while we're waiting on a flaky upstream.
 *  Env-overridable for tests (via LLM_RETRY_KEEPALIVE_MS). */
const STREAM_KEEPALIVE_INTERVAL_MS = parseInt(
  process.env.LLM_RETRY_KEEPALIVE_MS || "15000",
  10
);

function nextBackoffDelay(retryIdx: number): number {
  // retryIdx is 1-based (first retry = 1). Cap to the last entry when we
  // run past the end of the schedule.
  const i = Math.max(0, retryIdx - 1);
  return SAME_PROVIDER_DELAYS_MS[Math.min(i, SAME_PROVIDER_DELAYS_MS.length - 1)];
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/** Sleep in short slices so we can emit SSE keepalives to the client during
 *  the wait. If `writeKeepalive` is provided (streaming requests only), we
 *  call it every STREAM_KEEPALIVE_INTERVAL_MS to keep the downstream socket
 *  alive. Returns early and truthy if the client disconnected mid-sleep. */
async function sleepWithKeepalive(
  ms: number,
  writeKeepalive: (() => boolean) | null,
  isClientGone: () => boolean
): Promise<boolean> {
  const end = Date.now() + ms;
  while (Date.now() < end) {
    if (isClientGone()) return true;
    const remaining = end - Date.now();
    const slice = Math.min(remaining, STREAM_KEEPALIVE_INTERVAL_MS);
    await sleep(slice);
    if (writeKeepalive && !writeKeepalive()) return true; // socket write failed
  }
  return isClientGone();
}

/** Map of provider names to their base URLs (fallbacks if not stored). */
const PROVIDER_BASE_URLS: Record<string, string> = {
  anthropic: "https://api.anthropic.com",
  openai: "https://api.openai.com",
  zai: "https://open.bigmodel.cn/api/paas",
  deepseek: "https://api.deepseek.com",
  deepinfra: "https://api.deepinfra.com/v1",
};

/**
 * OpenCode/OpenAI SDK always prefixes paths with /v1/ (e.g. /v1/chat/completions).
 * Some providers use a different API version path. This map rewrites the version
 * prefix so the upstream URL is correct.
 *   - null  = strip /v1/ entirely (provider base URL already includes full path)
 *   - "vN"  = replace /v1/ with /vN/
 */
const API_VERSION_REWRITE: Record<string, string | null> = {
  zai: "v4", // zai uses /v4/chat/completions, not /v1/chat/completions
  deepinfra: null, // deepinfra base URL is .../v1, SDK sends openai/chat/completions — no rewrite needed
};

// ── Error tracking (C1) ─────────────────────────────────────────────────

/**
 * Per-session error tracking for provider health detection.
 * Key: proxyKey, Value: Map<provider, consecutiveErrorCount>
 */
const sessionErrors = new Map<string, Map<string, number>>();

/** Clean up error tracking when session is destroyed. */
export function clearSessionErrors(proxyKey: string): void {
  sessionErrors.delete(proxyKey);
}

// ── Callbacks type ──────────────────────────────────────────────────────

export interface LlmProxyCallbacks {
  onProviderUnhealthy?: (sessionId: string, provider: string, errorCount: number) => void;
  onLlmResult?: (sessionId: string, success: boolean) => void;
}

// ── Helpers ─────────────────────────────────────────────────────────────

function injectAuthHeaders(
  headers: Record<string, string>,
  provider: string,
  apiKey: string
): void {
  if (provider === "anthropic") {
    headers["x-api-key"] = apiKey;
    if (!headers["anthropic-version"]) {
      headers["anthropic-version"] = "2023-06-01";
    }
  } else {
    // OpenAI-compatible providers (zai, openai, deepseek, deepinfra)
    headers["Authorization"] = `Bearer ${apiKey}`;
  }
}

function isStreamingRequest(body: Buffer): boolean {
  try {
    const parsed = JSON.parse(body.toString());
    return parsed.stream === true;
  } catch {
    return false;
  }
}

function rewriteApiPath(apiPath: string, provider: string, baseUrl: string): string {
  let finalPath = apiPath;
  const versionRewrite = API_VERSION_REWRITE[provider];
  if (versionRewrite === undefined) return finalPath;

  const baseEndsWithVersion = baseUrl.replace(/\/$/, "").endsWith(`/${versionRewrite}`);

  if (finalPath.startsWith("v1/")) {
    if (versionRewrite === null) {
      // Strip v1/ entirely (e.g. deepinfra base URL already includes /v1)
      finalPath = finalPath.slice(3);
    } else if (baseEndsWithVersion) {
      // Base URL already ends with the version — just strip v1/
      finalPath = finalPath.slice(3);
    } else {
      // Replace v1/ with target version
      finalPath = `${versionRewrite}/${finalPath.slice(3)}`;
    }
  } else if (versionRewrite !== null && !baseEndsWithVersion) {
    // Path has no version prefix (e.g. "chat/completions") and base URL doesn't
    // include the version — prepend target version (e.g. "v4/chat/completions")
    finalPath = `${versionRewrite}/${finalPath}`;
  }

  return finalPath;
}

function extractModelFromBody(body: Buffer): string | null {
  try {
    const parsed = JSON.parse(body.toString());
    return parsed.model || null;
  } catch {
    return null;
  }
}

function rewriteModelInBody(body: Buffer, newModel: string): Buffer {
  try {
    const parsed = JSON.parse(body.toString());
    parsed.model = newModel;
    return Buffer.from(JSON.stringify(parsed));
  } catch {
    return body;
  }
}

function trackLlmResult(
  proxyKey: string,
  provider: string,
  success: boolean,
  credentialStore: CredentialStore,
  callbacks?: LlmProxyCallbacks
): void {
  // C1: Track consecutive errors
  if (!sessionErrors.has(proxyKey)) {
    sessionErrors.set(proxyKey, new Map());
  }
  const counts = sessionErrors.get(proxyKey)!;

  if (success) {
    counts.set(provider, 0);
  } else {
    const errorCount = (counts.get(provider) || 0) + 1;
    counts.set(provider, errorCount);

    if (errorCount >= CONSECUTIVE_ERROR_THRESHOLD) {
      console.warn(
        `[llm-proxy] Provider ${provider} has ${errorCount} consecutive errors for proxy key ${proxyKey.slice(0, 8)}...`
      );
      const sessionId = credentialStore.getSessionIdByLlmProxyKey(proxyKey);
      if (sessionId && callbacks?.onProviderUnhealthy) {
        callbacks.onProviderUnhealthy(sessionId, provider, errorCount);
      }
      counts.set(provider, 0); // Reset to avoid repeated notifications
    }
  }

  // C3: Report every result for session-level health tracking
  if (callbacks?.onLlmResult) {
    const sessionId = credentialStore.getSessionIdByLlmProxyKey(proxyKey);
    if (sessionId) {
      callbacks.onLlmResult(sessionId, success);
    }
  }
}

// ── Streaming with failover support ─────────────────────────────────────

type StreamResult = "success" | "headers_sent" | "failed_before_headers";

async function attemptStreamingRequest(
  url: string,
  method: string,
  headers: Record<string, string>,
  body: Buffer,
  res: Response,
  provider: string,
  /** Optional: called right before we start forwarding upstream bytes.
   *  Used by the retry loop to commit SSE headers early (for keepalives)
   *  so we don't try to writeHead() again here. */
  onBeforeForward?: () => void
): Promise<StreamResult> {
  const startTime = Date.now();
  return new Promise<StreamResult>((resolve) => {
    const parsed = new URL(url);
    const transport = parsed.protocol === "https:" ? https : http;

    const options: http.RequestOptions = {
      hostname: parsed.hostname,
      port: parsed.port || (parsed.protocol === "https:" ? 443 : 80),
      path: parsed.pathname + parsed.search,
      method,
      headers: {
        ...headers,
        "Content-Length": Buffer.byteLength(body).toString(),
      },
      timeout: CONNECT_TIMEOUT_MS,
    };

    let chunkCount = 0;
    let totalBytes = 0;

    const upstream = transport.request(options, (upstreamRes) => {
      const ttfb = Date.now() - startTime;
      console.log(
        `[llm-proxy] ${provider} upstream responded status=${upstreamRes.statusCode} ttfb=${ttfb}ms`
      );

      if (
        upstreamRes.statusCode &&
        (upstreamRes.statusCode < 200 || upstreamRes.statusCode >= 300)
      ) {
        // Any non-2xx — retry (same provider first, then failover).
        upstreamRes.resume();
        upstreamRes.on("end", () => resolve("failed_before_headers"));
        return;
      }

      // Success — forward response. If the outer retry loop already
      // committed SSE headers (for keepalive purposes), skip writeHead
      // and just start piping upstream chunks.
      if (onBeforeForward) onBeforeForward();
      if (!res.headersSent) {
        res.writeHead(upstreamRes.statusCode || 200, {
          "Content-Type": upstreamRes.headers["content-type"] || "text/event-stream",
          "Cache-Control": "no-cache",
          Connection: "keep-alive",
          ...(upstreamRes.headers["x-request-id"]
            ? { "x-request-id": upstreamRes.headers["x-request-id"] }
            : {}),
        });
      }

      upstreamRes.on("data", (chunk: Buffer) => {
        chunkCount++;
        totalBytes += chunk.length;
        res.write(chunk);
      });

      upstreamRes.on("end", () => {
        const elapsed = Date.now() - startTime;
        console.log(
          `[llm-proxy] ${provider} stream done chunks=${chunkCount} bytes=${totalBytes} elapsed=${elapsed}ms`
        );
        res.end();
        resolve("success");
      });

      upstreamRes.on("error", (err) => {
        const elapsed = Date.now() - startTime;
        console.error(
          `[llm-proxy] ${provider} upstream stream error after ${elapsed}ms: ${err.message}`
        );
        res.end();
        resolve("headers_sent");
      });

      // Read timeout
      upstreamRes.setTimeout(READ_TIMEOUT_MS, () => {
        const elapsed = Date.now() - startTime;
        console.warn(
          `[llm-proxy] ${provider} read timeout after ${elapsed}ms chunks=${chunkCount}`
        );
        upstreamRes.destroy();
        res.end();
        resolve("headers_sent");
      });
    });

    upstream.on("timeout", () => {
      const elapsed = Date.now() - startTime;
      console.warn(`[llm-proxy] ${provider} connect timeout after ${elapsed}ms`);
      upstream.destroy();
      resolve("failed_before_headers");
    });

    upstream.on("error", (err) => {
      const elapsed = Date.now() - startTime;
      console.error(`[llm-proxy] ${provider} request error after ${elapsed}ms: ${err.message}`);
      resolve("failed_before_headers");
    });

    upstream.write(body);
    upstream.end();
  });
}

// ── Buffered request with failover support ──────────────────────────────

interface BufferedResult {
  status: number;
  contentType: string | null;
  body: Buffer;
}

async function attemptBufferedRequest(
  url: string,
  method: string,
  headers: Record<string, string>,
  body: Buffer,
  provider: string
): Promise<BufferedResult> {
  const startTime = Date.now();
  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), READ_TIMEOUT_MS);

    const fetchOptions: RequestInit = {
      method,
      headers,
      signal: controller.signal,
    };

    if (method !== "GET" && method !== "HEAD" && body.length > 0) {
      fetchOptions.body = body;
    }

    const upstream = await fetch(url, fetchOptions);
    clearTimeout(timeout);

    const elapsed = Date.now() - startTime;
    console.log(
      `[llm-proxy] ${provider} buffered response status=${upstream.status} elapsed=${elapsed}ms`
    );

    if (upstream.status >= 400) {
      const responseBody = await upstream.arrayBuffer();
      const errorPreview = Buffer.from(responseBody).toString().slice(0, 500);
      console.error(`[llm-proxy] ${provider} upstream error (${upstream.status}): ${errorPreview}`);
      return {
        status: upstream.status,
        contentType: upstream.headers.get("content-type"),
        body: Buffer.from(responseBody),
      };
    }

    const responseBody = await upstream.arrayBuffer();
    return {
      status: upstream.status,
      contentType: upstream.headers.get("content-type"),
      body: Buffer.from(responseBody),
    };
  } catch (error) {
    const elapsed = Date.now() - startTime;
    const msg = error instanceof Error ? error.message : String(error);
    console.error(`[llm-proxy] ${provider} fetch error after ${elapsed}ms: ${msg}`);
    return {
      status: msg.includes("abort") ? 504 : 502,
      contentType: "application/json",
      body: Buffer.from(
        JSON.stringify({ error: msg.includes("abort") ? "Upstream timeout" : "Upstream error" })
      ),
    };
  }
}

// ── Main request handler with failover ──────────────────────────────────

async function handleRequestWithFailover(
  req: Request,
  res: Response,
  primaryProvider: string,
  primaryCreds: (LlmCredentials & { sessionId: string }) | null,
  proxyKey: string,
  apiPath: string,
  body: Buffer,
  credentialStore: CredentialStore,
  callbacks?: LlmProxyCallbacks
): Promise<void> {
  const modelChains = credentialStore.getModelChains(proxyKey);
  const streaming = req.method === "POST" && body.length > 0 && isStreamingRequest(body);

  // Build list of providers to try
  const providersToTry: Array<{ provider: string; creds: LlmCredentials; model: string | null }> =
    [];

  if (primaryProvider === "sandbox") {
    // Profile-based routing: model name in body IS the profile name.
    // Look up the chain for this profile and try each real provider in order.
    const profileName = extractModelFromBody(body);
    if (!profileName || !modelChains) {
      res.status(400).json({ error: "Missing profile name or model chains for sandbox routing" });
      return;
    }

    const chain = modelChains[profileName];
    if (!chain || chain.length === 0) {
      res.status(400).json({ error: `Unknown sandbox profile: ${profileName}` });
      return;
    }

    for (const entry of chain) {
      const creds = credentialStore.getByLlmProxyKey(proxyKey, entry.provider);
      if (creds) {
        providersToTry.push({
          provider: entry.provider,
          creds,
          model: entry.model,
        });
      }
    }

    if (providersToTry.length === 0) {
      res.status(500).json({ error: "No credentials available for any provider in chain" });
      return;
    }

    console.log(
      `[llm-proxy] sandbox profile=${profileName} chain=${providersToTry.map((p) => p.provider).join(",")}`
    );
  } else {
    // Direct provider routing (legacy path): provider in URL is primary
    if (!primaryCreds) {
      res.status(403).json({ error: "Invalid proxy key or provider" });
      return;
    }
    providersToTry.push({ provider: primaryProvider, creds: primaryCreds, model: null });

    // Find alternative providers from model chains for failover
    if (modelChains) {
      const requestModel = extractModelFromBody(body);
      if (requestModel) {
        const chain =
          modelChains[requestModel] || modelChains[`${primaryProvider}/${requestModel}`];
        if (chain) {
          for (const entry of chain) {
            const altBaseProvider = entry.provider.split("-")[0];
            if (altBaseProvider === primaryProvider.split("-")[0]) continue;
            const altCreds = credentialStore.getByLlmProxyKey(proxyKey, altBaseProvider);
            if (altCreds) {
              providersToTry.push({
                provider: altBaseProvider,
                creds: altCreds,
                model: entry.model,
              });
            }
          }
        }
      }
    }
  }

  console.log(
    `[llm-proxy] mode=${streaming ? "streaming" : "buffered"} bodySize=${body.length} providers=${providersToTry.map((p) => p.provider).join(",")}`
  );

  // Try each provider
  for (let i = 0; i < providersToTry.length; i++) {
    const attempt = providersToTry[i];
    const isLastAttempt = i === providersToTry.length - 1;

    // Strip provider prefix from model name in request body.
    // Providers expect just the model name, not the routing prefix
    // (e.g. "deepinfra/Qwen/Qwen3-32B" → "Qwen/Qwen3-32B").
    // This applies to BOTH primary and failover attempts because OpenCode
    // may or may not strip the prefix depending on model name format.
    let attemptBody = body;
    const baseProvider = attempt.provider.split("-")[0];
    if (attempt.model) {
      let apiModel = attempt.model;
      if (apiModel.startsWith(`${baseProvider}/`)) {
        apiModel = apiModel.slice(baseProvider.length + 1);
      }
      attemptBody = rewriteModelInBody(body, apiModel);
    } else {
      // Primary attempt: check if model in body has the provider prefix
      const bodyModel = extractModelFromBody(body);
      if (bodyModel && bodyModel.startsWith(`${baseProvider}/`)) {
        const stripped = bodyModel.slice(baseProvider.length + 1);
        attemptBody = rewriteModelInBody(body, stripped);
      }
    }

    // Build upstream URL for this provider
    const baseUrl = attempt.creds.baseUrl || PROVIDER_BASE_URLS[attempt.provider] || "";
    if (!baseUrl) {
      if (isLastAttempt) {
        res.status(400).json({ error: `Unknown provider: ${attempt.provider}` });
        return;
      }
      continue;
    }

    const finalApiPath = rewriteApiPath(apiPath, attempt.provider, baseUrl);
    const upstreamUrl = `${baseUrl.replace(/\/$/, "")}/${finalApiPath}`;

    // Build headers with injected auth
    const headers: Record<string, string> = {};
    if (req.headers["content-type"])
      headers["Content-Type"] = req.headers["content-type"] as string;
    if (req.headers["accept"]) headers["Accept"] = req.headers["accept"] as string;
    if (req.headers["anthropic-version"])
      headers["anthropic-version"] = req.headers["anthropic-version"] as string;
    if (req.headers["anthropic-beta"])
      headers["anthropic-beta"] = req.headers["anthropic-beta"] as string;
    injectAuthHeaders(headers, attempt.provider, attempt.creds.apiKey);

    if (i > 0) {
      const rewriteInfo = finalApiPath !== apiPath ? ` (rewritten from ${apiPath})` : "";
      console.log(
        `[llm-proxy] FAILOVER: trying ${attempt.provider} (attempt ${i + 1}/${providersToTry.length}) model=${attempt.model}${rewriteInfo} → ${upstreamUrl}`
      );
    } else {
      const rewriteInfo = finalApiPath !== apiPath ? ` (rewritten from ${apiPath})` : "";
      console.log(
        `[llm-proxy] ${req.method} ${attempt.provider}/${finalApiPath}${rewriteInfo} → ${upstreamUrl}`
      );
    }

    // Track whether the downstream client has dropped. `res.on('close')`
    // fires as soon as opencode disconnects; we stop retrying immediately
    // rather than burning quota on an orphaned request.
    let clientGone = false;
    res.on("close", () => {
      clientGone = true;
    });
    const isClientGone = () => clientGone || res.writableEnded || res.destroyed;

    if (streaming) {
      // We commit to SSE headers BEFORE the first upstream call so we can
      // send keepalive comments during back-off sleeps. Without this,
      // opencode's HTTP client idles out after a few tens of seconds while
      // the proxy waits on a flaky upstream, and the whole retry budget
      // is wasted on an already-dead socket.
      //
      // SSE comment lines (starting with ':') are ignored by parsers —
      // they exist specifically to keep the socket warm.
      let headersCommitted = false;
      const commitStreamingHeaders = () => {
        if (headersCommitted || res.headersSent) return;
        res.writeHead(200, {
          "Content-Type": "text/event-stream",
          "Cache-Control": "no-cache",
          Connection: "keep-alive",
          "X-Accel-Buffering": "no", // disable proxy buffering (nginx etc.)
        });
        headersCommitted = true;
      };
      const writeKeepalive = (): boolean => {
        commitStreamingHeaders();
        try {
          return res.write(`: keepalive ${Date.now()}\n\n`);
        } catch {
          return false;
        }
      };

      const startedAt = Date.now();
      let retry = 0;
      let lastFailureReason: string = "failed_before_headers";

      while (Date.now() - startedAt < SAME_PROVIDER_RETRY_BUDGET_MS) {
        if (isClientGone()) {
          console.log(
            `[llm-proxy] ${attempt.provider} client disconnected during retry loop; abandoning`
          );
          trackLlmResult(proxyKey, attempt.provider, false, credentialStore, callbacks);
          return;
        }

        if (retry > 0) {
          const delay = nextBackoffDelay(retry);
          const budgetLeft = SAME_PROVIDER_RETRY_BUDGET_MS - (Date.now() - startedAt);
          console.log(
            `[llm-proxy] ${attempt.provider} retry ${retry} after ${delay}ms ` +
              `(budget left: ${Math.round(budgetLeft / 1000)}s, last: ${lastFailureReason})`
          );
          const disconnected = await sleepWithKeepalive(delay, writeKeepalive, isClientGone);
          if (disconnected) {
            trackLlmResult(proxyKey, attempt.provider, false, credentialStore, callbacks);
            return;
          }
        }

        const result = await attemptStreamingRequest(
          upstreamUrl,
          req.method,
          headers,
          attemptBody,
          res,
          attempt.provider,
          commitStreamingHeaders
        );

        if (result === "success") {
          trackLlmResult(proxyKey, attempt.provider, true, credentialStore, callbacks);
          return;
        }
        if (result === "headers_sent") {
          // The upstream started streaming but then errored mid-flight.
          // We can't recover — headers are already downstream and partial
          // bytes were forwarded. Let opencode see the truncation.
          trackLlmResult(proxyKey, attempt.provider, false, credentialStore, callbacks);
          return;
        }
        // failed_before_headers — upstream returned 4xx/5xx or connection
        // died before data flowed to the client. Safe to retry.
        lastFailureReason = result;
        retry++;
      }

      // Wall-clock budget exhausted on this provider.
      console.warn(
        `[llm-proxy] ${attempt.provider} retry budget exhausted after ${Math.round(
          (Date.now() - startedAt) / 1000
        )}s and ${retry} attempts`
      );
      trackLlmResult(proxyKey, attempt.provider, false, credentialStore, callbacks);

      if (isLastAttempt) {
        // Nothing more to try. We already committed SSE 200 headers (to
        // keep the client alive during back-offs), so surface the error
        // as an SSE error event rather than an HTTP status code.
        if (headersCommitted) {
          try {
            res.write(
              `event: error\ndata: ${JSON.stringify({
                error: "All providers failed after retry budget exhausted",
              })}\n\n`
            );
            res.end();
          } catch {
            // client already gone
          }
        } else if (!res.headersSent) {
          res.status(502).json({ error: "All providers failed" });
        }
        return;
      }
      continue;
    } else {
      // Buffered (non-streaming) path: we don't have a downstream socket
      // to keep warm since the client is waiting for the full response,
      // but we still want the retry budget so the caller eventually
      // sees success on transient upstream outages.
      let lastResult: BufferedResult | null = null;
      const startedAt = Date.now();
      let retry = 0;

      while (Date.now() - startedAt < SAME_PROVIDER_RETRY_BUDGET_MS) {
        if (isClientGone()) {
          console.log(
            `[llm-proxy] ${attempt.provider} client disconnected during buffered retry loop; abandoning`
          );
          trackLlmResult(proxyKey, attempt.provider, false, credentialStore, callbacks);
          return;
        }

        if (retry > 0) {
          const delay = nextBackoffDelay(retry);
          const budgetLeft = SAME_PROVIDER_RETRY_BUDGET_MS - (Date.now() - startedAt);
          console.log(
            `[llm-proxy] ${attempt.provider} buffered retry ${retry} after ${delay}ms ` +
              `(budget left: ${Math.round(budgetLeft / 1000)}s)`
          );
          const disconnected = await sleepWithKeepalive(delay, null, isClientGone);
          if (disconnected) {
            trackLlmResult(proxyKey, attempt.provider, false, credentialStore, callbacks);
            return;
          }
        }

        lastResult = await attemptBufferedRequest(
          upstreamUrl,
          req.method,
          headers,
          attemptBody,
          attempt.provider
        );

        const isRetryable = lastResult.status >= 500 || lastResult.status === 429;

        if (!isRetryable) {
          // Success or non-retryable error (4xx) — send response
          trackLlmResult(proxyKey, attempt.provider, true, credentialStore, callbacks);
          res.status(lastResult.status);
          if (lastResult.contentType) res.setHeader("Content-Type", lastResult.contentType);
          res.send(lastResult.body);
          return;
        }

        console.log(
          `[llm-proxy] ${attempt.provider} returned ${lastResult.status}, retrying same provider within budget`
        );
        retry++;
      }

      // Wall-clock budget exhausted.
      console.warn(
        `[llm-proxy] ${attempt.provider} buffered retry budget exhausted after ${Math.round(
          (Date.now() - startedAt) / 1000
        )}s and ${retry} attempts`
      );
      trackLlmResult(proxyKey, attempt.provider, false, credentialStore, callbacks);

      if (isLastAttempt && lastResult) {
        res.status(lastResult.status);
        if (lastResult.contentType) res.setHeader("Content-Type", lastResult.contentType);
        res.send(lastResult.body);
        return;
      }
      continue;
    }
  }
}

// ── Setup ───────────────────────────────────────────────────────────────

export function setupLlmProxy(
  app: Express,
  credentialStore: CredentialStore,
  callbacks?: LlmProxyCallbacks
): void {
  // Raw body parser for LLM proxy routes
  const rawParser = (req: Request, res: Response, next: () => void) => {
    if (!req.path.startsWith("/llm-proxy/")) return next();

    const contentLength = parseInt(req.headers["content-length"] || "0", 10);
    if (contentLength > MAX_BODY_SIZE) {
      res.status(413).json({ error: "Request body too large" });
      return;
    }

    const chunks: Buffer[] = [];
    let size = 0;

    req.on("data", (chunk: Buffer) => {
      size += chunk.length;
      if (size > MAX_BODY_SIZE) {
        res.status(413).json({ error: "Request body too large" });
        req.destroy();
        return;
      }
      chunks.push(chunk);
    });

    req.on("end", () => {
      (req as any).rawBody = Buffer.concat(chunks);
      next();
    });

    req.on("error", (err) => {
      console.error("[llm-proxy] Request stream error:", err.message);
      res.status(500).json({ error: "Stream error" });
    });
  };

  app.all("/llm-proxy/:proxyKey/:provider/*", rawParser, async (req: Request, res: Response) => {
    const proxyKey = req.params.proxyKey as string;
    const provider = req.params.provider as string;
    const apiPath = (req.params[0] as string) || "";

    const body: Buffer = (req as any).rawBody || Buffer.alloc(0);

    if (provider === "sandbox") {
      // Virtual "sandbox" provider — just verify the proxy key is valid.
      // Real provider credentials are resolved per-attempt from the chain.
      const sessionId = credentialStore.getSessionIdByLlmProxyKey(proxyKey);
      if (!sessionId) {
        console.warn(`[llm-proxy] Invalid proxy key for sandbox provider`);
        res.status(403).json({ error: "Invalid proxy key" });
        return;
      }

      await handleRequestWithFailover(
        req,
        res,
        provider,
        null,
        proxyKey,
        apiPath,
        body,
        credentialStore,
        callbacks
      );
      return;
    }

    // Direct provider routing — look up credentials for the specific provider
    const creds = credentialStore.getByLlmProxyKey(proxyKey, provider);
    if (!creds) {
      console.warn(`[llm-proxy] Invalid proxy key or unknown provider: ${provider}`);
      res.status(403).json({ error: "Invalid proxy key or provider" });
      return;
    }

    await handleRequestWithFailover(
      req,
      res,
      provider,
      creds,
      proxyKey,
      apiPath,
      body,
      credentialStore,
      callbacks
    );
  });
}
