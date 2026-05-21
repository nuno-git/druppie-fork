# Observability

Every run produces a per-run journal (streaming JSONL), a final
summary.json, and a pretty ASCII table on stdout. Plus a failure-injection
proxy for testing retry resilience end-to-end.

## Per-run artefacts

Location: `sessions/runs/<iso-timestamp>-<slug>/`. A single directory per
run containing:

```
sessions/runs/2026-04-23T11-16-20-722Z/
  journal.jsonl          # streaming events, one per line, append-only
  summary.json           # final rollup written at close
  <agent>.jsonl × N      # pi's own per-subagent transcripts
```

The agent jsonl files are pi's SessionManager output — full message
history with thinking blocks, tool calls, results, every raw LLM round-trip.

## Journal events

Source: [`src/journal.ts`](../src/journal.ts). Every event has a common
envelope:

```json
{"ts":"2026-04-22T13:41:00.500Z","elapsedMs":42117,"type":"<event>","<other fields>"...}
```

Event types emitted during a run:

| Event | When |
|---|---|
| `run_start` | orchestrator entered, task captured |
| `sandbox_start` / `sandbox_ready` / `sandbox_stop` | container lifecycle |
| `source_clone` | host-side clone + bundle import completed |
| `phase_start` / `phase_end` | ANALYZE / PLAN / EXECUTE / VERIFY transitions |
| `subagent_start` / `subagent_end` | per-agent lifecycle (turns, tokens, cost, retries, duration) |
| `tool_call` / `tool_result` | every bash/read/edit/write/grep/find the agent invoked (args truncated at 800 chars, results at 400) |
| `llm_retry_start` / `llm_retry_end` | pi's auto_retry_* events surfaced (`attempt` counter) |
| `branch_renamed` | analyst-proposed name replaced the temp name |
| `commit` | every real agent-authored commit (agent + sha + message) |
| `push_start` / `push_done` | bundle size, push result |
| `pr_ensured` | action (`created`/`exists`/`skipped`), PR number, URL |
| `sim_server_started` / `sim_server_stats` | if failure-injection proxy was on |
| `error` | errors pushed into the errors[] array |
| `run_end` | final outcome + duration |

The journal is append-only JSONL — resilient to crashes. If the process is
SIGKILLed mid-run, the journal still contains everything up to that point.

## summary.json

At end of run, `Journal.close(success)` writes a rolled-up
[`RunSummary`](../src/journal.ts) shape:

```json
{
  "success": true,
  "startedAt": "2026-04-23T11:16:20Z",
  "endedAt":   "2026-04-23T11:18:49Z",
  "durationMs": 148338,
  "sandbox": { "bootMs": 2186 },
  "phases": [
    { "phase": "ANALYZE", "iteration": 0, "durationMs": ..., "subagents": ["analyst-1"] },
    { "phase": "PLAN",    "iteration": 1, "durationMs": ..., "subagents": ["planner-1"] },
    { "phase": "EXECUTE", "iteration": 1, "durationMs": ..., "subagents": ["builder-1"] },
    { "phase": "VERIFY",  "iteration": 1, "durationMs": ..., "subagents": ["verifier-1"] }
  ],
  "agents": [
    {
      "id": "analyst-1", "name": "analyst", "model": "zai/glm-5.1",
      "turns": 3, "toolCalls": 2,
      "tokensInput": 4033, "tokensOutput": 602,
      "tokensCacheRead": 1600, "tokensCacheWrite": 0,
      "costUsd": 0, "retries": 0, "durationMs": 38402,
      "success": true
    },
    ...
  ],
  "commits": [
    { "phase": "agent", "sha": "329822d5", "message": "chore: append..." }
  ],
  "push": { "ok": true, "branch": "chore/append-oneshot-tdd-agent-test" },
  "pr":   { "action": "created", "number": 175, "url": "https://github.com/..." },
  "issues": [],
  "errors": []
}
```

Stable schema you can diff across runs or pipe into analytics.

## End-of-run pretty table

[`printRunSummary()`](../src/journal.ts) prints this on stdout:

```
══════════════════════════════════════════════════════════════════════
  RUN  chore/append-oneshot-tdd-agent-test   ✓
══════════════════════════════════════════════════════════════════════
  duration      2m 12s (boot 2.2s)
  branch        chore/append-oneshot-tdd-agent-test   1 commits
  push          ok
  pr            https://github.com/nuno-git/druppie-fork/pull/177

  agent               turns   tools    tok-in   tok-out   elapsed   retries
  -------------------------------------------------------------------------
  analyst                 3       2     4,033       602     38.4s         0
  planner                 1       0       523       523     21.8s         0
  builder                 6       5     4,033       177     37.8s         1
  verifier                3       4     2,952       197     22.5s         0
  pr-author               5       4     1,200       380     25.1s         0
  -------------------------------------------------------------------------
  total                  18      15    12,741     1,879                   1

  journal       /mnt/.../sessions/runs/2026-04-23T11-16-20-722Z
══════════════════════════════════════════════════════════════════════
```

For quick scanning — token budgets, retry hotspots, slow agents all
visible at a glance.

## Retry visibility

Pi's retry machinery emits `auto_retry_start` / `auto_retry_end` events
internally. [`src/agents/runner.ts`](../src/agents/runner.ts) subscribes:

```ts
if ((event as any).type === "auto_retry_start") {
  handle?.retryStart(ev.attempt ?? 0, ev.reason);
}
if ((event as any).type === "auto_retry_end") {
  handle?.retryEnd(ev.attempt ?? 0, !ev.error);
}
```

Each event becomes a `llm_retry_start` / `llm_retry_end` line in the
journal, and the agent's per-session retry count appears in
`subagent_end.retries`. Roll-up: total retries in the pretty table.

Default retry config (set by
[`src/agents/runner.ts`](../src/agents/runner.ts)):

```ts
retry: {
  enabled: true,
  maxRetries: 5000,
  baseDelayMs: 2000,
  maxDelayMs: 24 * 60 * 60 * 1000,
}
```

See [SANDBOX.md](SANDBOX.md) §Retry configuration for what this actually
buys you.

## Sim provider (failure injection)

[`src/providers/sim.ts`](../src/providers/sim.ts) is a tiny HTTP proxy
that sits in front of Z.AI. Enable with `ONESHOT_SIM_FAILURES=1`. Tunable:

- `ONESHOT_SIM_FAILURE_RATE` (default 0.5) — probability of injecting a
  fake failure per request
- `errorStatuses` (default [429, 500, 502, 503]) — pool of injected error
  codes. 429s include a random `Retry-After` (2-6 seconds) so pi honours
  upstream backoff hints.

Request flow:

```
pi → POST :<random-port>/chat/completions
        │
        ▼
    dice(failureRate) → inject?
        │
        ├── yes: return 429/500/502/503 synthetically
        │       no upstream call
        │
        └── no:  forward to real Z.AI
                stream SSE response back verbatim
```

On startup, orchestrator does `modelRegistry.registerProvider("zai", {
baseUrl: simServer.baseUrl })` — this re-routes every `zai/*` model request
to the proxy without any other code change. Agents don't know the
difference.

Stats tracked per-run:

- `total` / `failed` (injected) / `succeeded` (proxied)
- `byStatus` — histogram like `{ "200": 23, "429": 53, "500": 62, "502": 65, "503": 57 }`

Surfaced to the journal (`sim_server_stats`) at run end and to stdout:

```
[sim] final stats: 260 total, 237 injected failures, 23 proxied successes, byStatus={"200":23,...}
```

Use cases:

- **Retry resilience**: crank rate to 0.9, watch the journal for retry
  counts. Every subagent should still succeed, just slowly.
- **Rate-limit honouring**: 429 responses include Retry-After; verify
  pi's retry respects upstream's delay.
- **Regression detection**: after a dep bump, a pipeline change, or a
  prompt edit, run at 0.3-0.5 to confirm nothing collapses under transient
  failures.

### Cost note

Failure-injected requests never reach Z.AI. At 0.9 failure rate, only 10%
of LLM calls are billed. Handy for cheap stress testing of the orchestrator
logic.

## Debugging tips

**"The run says it succeeded but the branch is empty on GitHub."**
Check `commits` in the summary. If empty, `listNewCommits(baseSha)` found
nothing between `baseSha` and HEAD — meaning no agent committed. Inspect
per-agent jsonl files for their bash commands + outputs.

**"Pi says success:true but the output looks partial."**
The success check in the runner is lenient (`!output.includes("STEP
FAILED")`). Agent might have hit max turns (30) without explicitly printing
`STEP FAILED`. Check `turns` in `subagent_end`. Stricter agent outputs
like VERIFY's JSON schema still get validated by the orchestrator.

**"Consecutive tool errors killed the agent."**
The runner aborts after 5 consecutive tool failures. This fires for stuck
agents that repeat a broken bash command. Find the details in the agent's
jsonl file.

**"Where did this log line come from?"**
Every `[sandbox]`, `[pr]`, `[push]`, `[commits]`, `[auth]` prefix in stdout
is console.log'd from orchestrator.ts. grep the file, the context is
always a few lines above.

**"The sim proxy is eating all my traffic and I can't tell why."**
Check `simServer.baseUrl` in the journal's `sim_server_started` event to
confirm it's on. Watch `[sim] INJECT`/`[sim] PROXY` logs in stdout to see
per-request behaviour. `ONESHOT_SIM_FAILURES=0` disables it entirely.
