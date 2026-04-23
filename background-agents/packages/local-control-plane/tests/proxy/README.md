# LLM proxy retry tests

End-to-end tests for `src/proxy/llm-proxy.ts` — drives the real
`setupLlmProxy()` handler against a configurable "chaos upstream" so we
can verify retry, back-off, keepalive, and client-abandon behaviour
without calling a real LLM provider.

## Files

- `chaos-upstream.ts` — a fake OpenAI-compatible provider. Configurable
  per-request via query params (`?fail=N&status=429&id=TOKEN`). Exposes
  `/_counters/<id>` and `/_reset` admin endpoints for test assertions.
- `retry-integration.test.ts` — the test driver. Starts the chaos
  upstream as a subprocess, mounts the real proxy on a random port, and
  drives it through four scenarios.

## Run

From `background-agents/packages/local-control-plane`:

```
npm run test:proxy
```

The `test:proxy` script sets short back-off delays
(`LLM_RETRY_DELAYS_MS=200,400,800,1600`) so the whole suite finishes in
about 10 seconds. Production defaults (10s/30s/2min/5min with a 24h
budget) are unchanged — those envs exist **only** so tests can shrink
them.

## What it covers

| Case | Asserts |
|---|---|
| Eventual success after N 429s (buffered) | request count, back-off elapsed, response body |
| Eventual success after N 429s (streaming) | keepalive comments flow during back-off, final SSE data arrives, `[DONE]` terminator |
| Client disconnects mid-retry | upstream stops receiving requests the instant the client socket closes (no orphan quota burn) |
| Parallel requests | per-`id` counters stay independent (no shared mutable state across requests) |

## Adding a new case

1. Add a query-param knob to `chaos-upstream.ts` if the fault type
   doesn't exist yet (e.g. slow first byte, truncate mid-stream).
2. Add a `test("...", async () => { ... })` block in
   `retry-integration.test.ts`. Always pass a unique `id=...` so the
   chaos counters don't cross-contaminate with other tests.
3. Keep runtimes short — if a scenario needs more than a couple of
   seconds, the chaos schedule is probably wrong, not the proxy.
