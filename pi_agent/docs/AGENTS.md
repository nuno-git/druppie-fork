# Agents

"Agent" here means: a Pi multi-turn LLM session with a system prompt, a
scoped tool set, and a defined output contract. Each is defined by a single
markdown file in `.pi/agents/` and invoked by the orchestrator as part of
the TDD flow.

## The five agents

Located in [`.pi/agents/`](../.pi/agents/):

| Agent | Role | Write access | Output |
|---|---|---|---|
| **analyst** | Restate goal, define acceptance criteria, propose test cases, pick branch name | read-only | `GoalAnalysis` JSON |
| **planner** | Given the analysis + failure context, produce a wave-based build plan | read-only | `BuildPlan` JSON |
| **builder** | Execute a single step from a wave: write code, commit | read/write/edit | `STEP COMPLETE` after commit |
| **verifier** | Run tests + build, fix trivial issues, commit if fixed | read/write/edit | `VerificationResult` JSON + verdict |
| **pr-author** | Inspect commits/diff and author PR title + body | read-only | `{title, body}` JSON |

## Agent file format

Every agent is a `.md` file with YAML frontmatter plus a system prompt:

```markdown
---
name: builder
description: Executes a single build step ...
tools: read,bash,edit,write,grep,find,ls
model: zai/glm-5.1
---

You are the **Builder** agent. ...
```

Parsed at orchestrator start by
[`discoverAgents()`](../src/agents/runner.ts) — the frontmatter becomes an
`AgentDefinition` and the body becomes the system prompt.

### `tools` field

Comma-separated subset of: `read, bash, edit, write, ls, grep, find`.
This is the exact set of tools the agent's LLM can call. We take the list
literally — no fallback to "all tools" if you miss one.

Enforced in [`src/sandbox/tools-factory.ts`](../src/sandbox/tools-factory.ts)
and [`src/agents/runner.ts`](../src/agents/runner.ts) `buildLocalTools`.
Unknown tool names are logged as a warning and dropped.

### `model` field

Either `"provider/id"` (e.g. `zai/glm-5.1`, `anthropic/claude-sonnet-4-5`)
or bare `"id"` (searched across all registered providers). Resolved at
runtime via `pi`'s `ModelRegistry`. All current agents use
`zai/glm-5.1` — the GLM 5.1 model via the Z.AI coding endpoint.

If the model field is missing or the id isn't found, the agent falls back
to the global `defaultModel` passed from the orchestrator (which is in turn
configurable via `config.model` — defaults to `zai/glm-5.1`).

### System prompt

Everything after the frontmatter becomes the LLM's system prompt. Kept
human-readable and terse. Each prompt contains:

- Role statement ("You are the Builder agent")
- Process (numbered steps)
- Output format (required JSON schema or marker strings like `STEP COMPLETE`)
- Rules / constraints (commit requirements, don't-do-X etc.)

## How an agent runs

[`src/agents/runner.ts`](../src/agents/runner.ts) `runSubagent()` is the
single entry point. Each call is one complete LLM session with one top-level
user prompt.

```
runSubagent(agent, prompt, options):
  1. resolve model (per-agent override or global default)
  2. build tools:
       if sandboxClient set:
         customTools = buildSandboxTools(sandboxClient, agent.tools)
         (these replace pi's built-ins by name)
       else:
         tools = buildLocalTools(agent.tools, cwd)
         (only used if sandbox is disabled — shouldn't happen in prod)
  3. create a DefaultResourceLoader with systemPromptOverride(agent.systemPrompt)
  4. createAgentSession({model, tools, customTools, resourceLoader, sessionManager, settingsManager, authStorage, modelRegistry})
  5. subscribe to the session event stream
       tool_execution_start/end → journal + abort on consecutive errors
       turn_end → count turns (abort if maxTurns reached)
       auto_retry_start/end → journal + bump agent's retry count
       message_end → capture token usage
  6. session.prompt(prompt)
  7. resolve { success, output, turnCount }
```

`success` is determined by `!output.includes("STEP FAILED") && !output.includes("VERIFICATION FAILED")`
— a lenient check. Strictness for semantics comes from the orchestrator
validating the expected JSON shape (e.g. `buildPlan.waves.length > 0`).

### Retry configuration

Passed to pi via `SettingsManager.inMemory`:

```ts
retry: {
  enabled: true,
  maxRetries: 5000,               // effectively unlimited within wall-clock
  baseDelayMs: 2000,              // 2s base, exponential backoff
  maxDelayMs: 24 * 60 * 60 * 1000 // honour Retry-After up to 24h
}
```

The real stop condition is the sandbox wall-clock timeout (default 24h),
not pi's retry count. If the upstream LLM flakes 90% for a day, the run
eventually fails due to that wall clock — not because pi gives up.

Retries are per-LLM-request. Pi's `auto_retry_start` and `auto_retry_end`
events fire per transient failure (429, 5xx) and are streamed into the
journal so you can see the exact retry cadence per subagent.

### Consecutive tool-error guard

If the LLM produces 5 consecutive tool-call errors (e.g. it's stuck in a
retry loop where every `bash` returns exit 1), the runner aborts the session
with `STEP FAILED: Aborted after N consecutive tool errors`. Prevents
billion-turn infinite loops from stuck agents.

## The orchestrator's view

[`src/orchestrator.ts`](../src/orchestrator.ts) is **not** an agent. It's
plain-code orchestration that invokes agents. No LLM call originates from
orchestrator logic.

Its phase machine:

```
ANALYZE (iteration 0)
  run analyst
  parse GoalAnalysis JSON  →  throw if missing branchName or invalid
  renameCurrentBranch(goalAnalysis.branchName)

for iteration = 1..maxIterations:
  PLAN
    build prompt (initial or fix-mode depending on iteration > 1)
    run planner
    parse BuildPlan JSON  →  if invalid, continue (next iteration)

  EXECUTE
    for each wave in plan:
      if wave has 1 step: runSubagent(builder)
      if wave has >1: runSubagentsParallel(builders)  // up to MAX_CONCURRENCY=4

  VERIFY
    build verify prompt containing test/build cmds + step results
    run verifier
    parse VerificationResult JSON

  decide:
    testsPassed && buildPassed    →  break out of loop
    else                          →  continue, feed failure context to next PLAN
```

On `break`, control falls through to the post-loop push/PR/journal-close
block. The loop body uses `continue` for retries; `break` for success.
Neither uses `return` — that would skip the post-loop work. See
[ARCHITECTURE.md](ARCHITECTURE.md) for the classic bug-class this avoids.

## Commit expectations

Source of truth: the agent prompts
([`.pi/agents/builder.md`](../.pi/agents/builder.md) and
[`.pi/agents/verifier.md`](../.pi/agents/verifier.md)).

Summary of the contract:

- **Builder** MUST end each task with a successful commit + verification via
  `git log --oneline -1`. `STEP COMPLETE` without a confirmed commit is
  a protocol violation.
- **Verifier** only commits if it made a fix. If no fix was needed,
  verifier skips commit.
- Neither agent uses `git checkout` to switch branches (the prompt
  explicitly forbids it). If an agent accidentally switched, the
  orchestrator's push-time guard (`RESERVED_BRANCHES` check +
  `livePushBranch === task.sourceBranch`) would refuse to push.

Recovery: if an agent's `git commit` fails with `Author identity unknown`,
the prompt tells it to run `git config user.email ... && git config
user.name ...` and retry. The sandbox's `/init` endpoint already sets
these at orchestrator start, so this is belt-and-braces.

If the agent forgets to commit entirely, the orchestrator's
`listNewCommits(baseSha)` post-loop step still captures whatever commits
exist. If the branch hasn't advanced at all, `commits: []` in the summary
surfaces the problem.

## Agent-authored PR text

[`pr-author`](../.pi/agents/pr-author.md) is a read-only agent that runs
after push succeeds. Its sole job: produce a JSON `{title, body}` for the
PR. Gets a prompt containing the `baseSha` and expected PR base ref, so it
can run `git log <base>..HEAD`, `git diff --stat`, etc.

Invoked by the orchestrator with a retry loop (up to 3 attempts). If the
agent's output doesn't parse to valid `{title, body}` after 3 tries, the
PR ensure step fails with a clear error. No template fallback.

Manual overrides: if the caller set `config.sandbox.prTitle` or
`config.sandbox.prBody` (via `--pr-title` CLI flag or programmatically),
the agent is skipped and the override is used.

## Adding a new agent

1. Create `.pi/agents/<name>.md` with frontmatter + system prompt.
2. The orchestrator auto-discovers it on next run (via `discoverAgents`).
3. Reference it in orchestrator code with `getAgent("<name>")`.

If the new agent participates in the phase loop, add a corresponding branch
in `orchestrator.ts`. If it's a one-off (like pr-author), invoke it directly
where appropriate.
