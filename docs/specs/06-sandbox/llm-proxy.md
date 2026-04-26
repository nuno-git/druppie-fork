# LLM Proxy

File: `background-agents/packages/local-control-plane/src/proxy/llm-proxy.ts` (~720 lines).

Route: `ALL /llm-proxy/:proxyKey/:provider/*`

## Why a proxy

Sandboxes can't hold long-term API keys (they'd leak if the container's memory was compromised). Instead:
1. At sandbox creation, Druppie generates a random `proxyKey` and stores `(proxyKey → provider chain, session)` in the control plane's in-memory credential store.
2. Sandbox-side OpenCode CLI points at `http://sandbox-control-plane:8787/llm-proxy/<proxyKey>/<provider>/…`.
3. The proxy looks up the credentials, forwards with real API keys, streams response back.

A compromised sandbox can only make LLM calls on behalf of its own session, within its session's quota, until the control plane evicts the proxyKey.

## Features

- **Streaming passthrough** — full Server-Sent Events (SSE) forwarding via `node:http/https` (not `fetch`) to avoid buffering.
- **Auth header injection**:
  - Anthropic: `x-api-key: <key>`, `anthropic-version: 2023-06-01`.
  - OpenAI-compatible (`openai`, `deepseek`, `deepinfra`, `zai`): `Authorization: Bearer <key>`.
- **API version path rewriting** — `zai` uses `/v4/…`; `deepinfra` strips `/v1/` prefix. The proxy normalises.
- **Model chain failover** — each proxyKey can have a list of providers. 5xx / 429 from one triggers the next.
- **Same-provider retries** — 3 attempts with 10s / 30s / 2min backoff before failing over.
- **Health tracking** — per-session consecutive error counter; at 3 errors on the same provider, `onProviderUnhealthy()` callback fires.

## Config constants

```ts
const MAX_BODY_SIZE = 10 * 1024 * 1024;      // 10 MB
const CONNECT_TIMEOUT_MS = 30_000;           // 30 s
const READ_TIMEOUT_MS = 300_000;             // 5 min
const RETRY_DELAYS_MS = [10_000, 30_000, 120_000];
const CONSECUTIVE_ERROR_THRESHOLD = 3;
```

## Request flow

```
1. Route receives /llm-proxy/:proxyKey/:provider/:rest
2. Credential lookup by proxyKey. 401 if not found.
3. Resolve provider chain:
   - if :provider == "sandbox" — use model chain from credential store indexed by model name.
   - else direct provider.
4. Attempt loop across chain:
   a. Rewrite URL path (provider-specific).
   b. Strip provider prefix from model name in body (e.g. "deepinfra/…" → "…").
   c. Add auth headers.
   d. Fire upstream request.
      - Streaming: tunnel via node:http with SSE parsing.
      - Buffered: fetch + json.
   e. On 5xx / 429:
      - Retry same provider up to 3× with backoff.
      - On persistent failure: next provider in chain.
   f. On 2xx:
      - Stream response to client.
      - Record success.
   g. On 4xx other than 429:
      - Non-retryable. Return error.
5. If all providers exhausted → 502.
```

## Error tracking

```ts
const sessionErrorCount: Map<proxyKey, {provider: string, count: number}> = new Map();

function trackLlmResult(proxyKey, provider, success) {
  const state = sessionErrorCount.get(proxyKey);
  if (success) {
    if (state?.provider === provider) sessionErrorCount.delete(proxyKey);
  } else {
    if (state?.provider === provider) state.count += 1;
    else sessionErrorCount.set(proxyKey, {provider, count: 1});
    if (state?.count >= CONSECUTIVE_ERROR_THRESHOLD) {
      onProviderUnhealthy(proxyKey, provider);
    }
  }
}
```

`onProviderUnhealthy` can be wired to emit an event so dashboards see provider degradation in real time.

## Provider list

Hard-coded in `llm-proxy.ts`:
- Anthropic
- OpenAI
- DeepSeek
- DeepInfra
- Z.AI

The "sandbox" pseudo-provider uses model-keyed chain lookup (defined in `credential-store.getModelChains()`). Example:
```ts
{
  "anthropic/claude-3.5-sonnet": ["anthropic", "openai"],
  "deepinfra/mistral": ["deepinfra"],
}
```

The first provider in each chain is the preferred one; subsequent providers are fallbacks.

## Metrics

Every attempt emits (internally):
- Latency
- Token usage (parsed from response when possible)
- Retry count
- Failover count

These feed the health endpoints on the control plane. Not surfaced to Druppie today.

## Streaming details

For `stream: true` requests:
- Response: `Transfer-Encoding: chunked`, `Content-Type: text/event-stream`.
- Upstream connect deadline: 30 s.
- Read deadline per chunk: 300 s.
- On read timeout mid-stream: attempt aborts, retry cycle kicks in.

For non-streaming:
- Buffer full response up to 10 MB.
- Parse JSON, forward to client.

## Security

- API keys are server-side only, never present in client-visible responses.
- CORS is not permissive — the proxy expects calls from the sandbox containers only.
- Sensitive headers (Authorization, x-api-key) stripped from forwarded request log lines.
