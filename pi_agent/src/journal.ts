/**
 * Run journal — append-only timeline of every interesting event + a final
 * rolled-up summary. When running standalone it writes journal.jsonl +
 * summary.json on disk. When launched by druppie's execute_coding_task_pi,
 * PI_AGENT_INGEST_URL is set and each event is additionally POSTed to the
 * druppie backend so it lands in the PiCodingRun row for UI playback.
 *
 * Directory layout under `sessions/runs/<iso>-<slug>/` (standalone mode):
 *   journal.jsonl       ← streaming events, one per line
 *   summary.json        ← final rollup written at close()
 *   <agent>.jsonl       ← pi-managed per-subagent transcripts (written by SDK)
 */
import { createWriteStream, mkdirSync, writeFileSync, type WriteStream } from "node:fs";
import { join } from "node:path";

import type { TaskSpec } from "./types.js";

// ── Druppie ingest sink ────────────────────────────────────────────────────

const INGEST_URL = process.env.PI_AGENT_INGEST_URL;
const INGEST_TOKEN = process.env.PI_AGENT_INGEST_TOKEN;
const INGEST_SUMMARY_URL = INGEST_URL?.replace(/\/events$/, "/summary");

async function postEvent(event: Record<string, unknown>): Promise<void> {
  if (!INGEST_URL || !INGEST_TOKEN) return;
  try {
    await fetch(INGEST_URL, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        authorization: `Bearer ${INGEST_TOKEN}`,
      },
      body: JSON.stringify(event),
    });
  } catch (e) {
    // Ingest failures are non-fatal — the agent keeps running and the
    // file-based journal remains available for post-hoc recovery.
    console.error("[journal] ingest POST failed:", (e as Error).message);
  }
}

async function postSummary(summary: RunSummary): Promise<void> {
  if (!INGEST_SUMMARY_URL || !INGEST_TOKEN) return;
  try {
    await fetch(INGEST_SUMMARY_URL, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        authorization: `Bearer ${INGEST_TOKEN}`,
      },
      body: JSON.stringify(summary),
    });
  } catch (e) {
    console.error("[journal] summary POST failed:", (e as Error).message);
  }
}

// ── Event shape ────────────────────────────────────────────────────────────

export type JournalEvent =
  | { type: "run_start" }
  | { type: "sandbox_start" }
  | { type: "sandbox_stop" }
  | { type: "source_clone" }
  | { type: "phase_start" }
  | { type: "phase_end" }
  | { type: "subagent_start" }
  | { type: "subagent_end" }
  | { type: "tool_call" }
  | { type: "tool_result" }
  | { type: "llm_retry_start" }
  | { type: "llm_retry_end" }
  | { type: "branch_renamed" }
  | { type: "commit" }
  | { type: "push_start" }
  | { type: "push_done" }
  | { type: "pr_ensured" }
  | { type: "error" }
  | { type: "run_end" };

// ── Per-agent bookkeeping ─────────────────────────────────────────────────

interface AgentStats {
  id: string;
  name: string;
  model: string;
  startedAt: number;
  endedAt?: number;
  turns: number;
  toolCalls: number;
  tokensInput: number;
  tokensOutput: number;
  tokensCacheRead: number;
  tokensCacheWrite: number;
  costUsd: number;
  retries: number;
  success?: boolean;
  error?: string;
}

interface PhaseRecord {
  phase: string;
  iteration: number;
  startedAt: number;
  endedAt?: number;
  subagents: string[]; // ids of subagents spawned during this phase
}

interface Issue {
  agentId: string;
  reason: string;
  resolved: boolean;
}

interface AgentNarrative {
  agent: string;
  iteration: number;
  text: string;
}

// ── Journal ───────────────────────────────────────────────────────────────

/**
 * When PI_AGENT_INGEST_URL is set (druppie run), the DB is the only home for
 * session data — no JSONL or summary.json on disk. When unset (standalone
 * CLI debug), we fall back to the original file-based journal.
 */
const WRITE_FILES = !process.env.PI_AGENT_INGEST_URL;

export class Journal {
  private readonly stream: WriteStream | null;
  private readonly startMs: number;
  private readonly agents = new Map<string, AgentStats>();
  private readonly phases: PhaseRecord[] = [];
  private readonly commits: Array<{ phase: string; sha: string; message: string }> = [];
  private readonly issues: Issue[] = [];
  private readonly errors: string[] = [];
  private readonly narratives: AgentNarrative[] = [];
  private currentPhase?: PhaseRecord;
  private sandboxStartedAt?: number;
  private sandboxReadyAt?: number;
  private pushResult?: { ok: boolean; branch?: string };
  private prResult?: { action: string; number?: number; url?: string };

  constructor(public readonly dir: string, task: TaskSpec) {
    if (WRITE_FILES) {
      mkdirSync(dir, { recursive: true });
      this.stream = createWriteStream(join(dir, "journal.jsonl"), { flags: "a" });
    } else {
      this.stream = null;
    }
    this.startMs = Date.now();
    this.write("run_start", { task });
  }

  /** Append one event. Local file only in standalone mode, ingest always. */
  write(type: string, data: Record<string, unknown> = {}): void {
    const event = { ts: new Date().toISOString(), elapsedMs: Date.now() - this.startMs, type, ...data };
    this.stream?.write(JSON.stringify(event) + "\n");
    // Fire-and-forget ingest — no await so journal semantics stay synchronous.
    void postEvent(event);
  }

  // ── Sandbox lifecycle ────────────────────────────────────────────────────

  sandboxStart(containerName: string, runtime: string): void {
    this.sandboxStartedAt = Date.now();
    this.write("sandbox_start", { containerName, runtime });
  }

  sandboxReady(): void {
    this.sandboxReadyAt = Date.now();
  }

  sandboxStop(): void {
    this.write("sandbox_stop", {});
  }

  sourceClone(remoteUrl: string, branch: string, bundleBytes?: number): void {
    this.write("source_clone", { remoteUrl, branch, bundleBytes });
  }

  // ── Phases ───────────────────────────────────────────────────────────────

  phaseStart(phase: string, iteration: number): void {
    if (this.currentPhase) this.phaseEnd();
    this.currentPhase = { phase, iteration, startedAt: Date.now(), subagents: [] };
    this.phases.push(this.currentPhase);
    this.write("phase_start", { phase, iteration });
  }

  phaseEnd(): void {
    if (!this.currentPhase) return;
    this.currentPhase.endedAt = Date.now();
    this.write("phase_end", {
      phase: this.currentPhase.phase,
      iteration: this.currentPhase.iteration,
      durationMs: this.currentPhase.endedAt - this.currentPhase.startedAt,
      subagents: this.currentPhase.subagents,
    });
    this.currentPhase = undefined;
  }

  // ── Subagents ────────────────────────────────────────────────────────────

  startAgent(name: string, model: string): AgentHandle {
    const ordinal = [...this.agents.values()].filter((a) => a.name === name).length + 1;
    const id = `${name}-${ordinal}`;
    const stats: AgentStats = {
      id,
      name,
      model,
      startedAt: Date.now(),
      turns: 0,
      toolCalls: 0,
      tokensInput: 0,
      tokensOutput: 0,
      tokensCacheRead: 0,
      tokensCacheWrite: 0,
      costUsd: 0,
      retries: 0,
    };
    this.agents.set(id, stats);
    this.currentPhase?.subagents.push(id);
    this.write("subagent_start", { id, name, model });
    return new AgentHandle(this, stats);
  }

  /** Internal — called by AgentHandle.end(). */
  _endAgent(stats: AgentStats, success: boolean, error?: string): void {
    stats.endedAt = Date.now();
    stats.success = success;
    stats.error = error;
    this.write("subagent_end", {
      id: stats.id,
      success,
      turns: stats.turns,
      toolCalls: stats.toolCalls,
      tokensIn: stats.tokensInput,
      tokensOut: stats.tokensOutput,
      costUsd: stats.costUsd,
      retries: stats.retries,
      durationMs: stats.endedAt - stats.startedAt,
      ...(error ? { error } : {}),
    });
  }

  // ── Other timeline events ────────────────────────────────────────────────

  branchRenamed(from: string, to: string): void {
    this.write("branch_renamed", { from, to });
  }

  commit(phase: string, sha: string, message: string): void {
    this.commits.push({ phase, sha, message });
    this.write("commit", { phase, sha, message });
  }

  pushStart(branch: string, bundleBytes: number): void {
    this.write("push_start", { branch, bundleBytes });
  }

  pushDone(branch: string, ok: boolean, output?: string): void {
    this.pushResult = { ok, branch };
    this.write("push_done", { branch, ok, ...(output ? { output: output.slice(0, 500) } : {}) });
  }

  prEnsured(action: string, number?: number, url?: string, message?: string): void {
    this.prResult = { action, number, url };
    this.write("pr_ensured", { action, number, url, message });
  }

  error(message: string, context?: Record<string, unknown>): void {
    this.errors.push(message);
    this.write("error", { message, ...context });
  }

  /** Record the free-text summary a subagent produced at end-of-run.
   * Trimmed to 2000 chars per call to keep the summary payload bounded. */
  recordNarrative(agent: string, iteration: number, text: string): void {
    const trimmed = (text ?? "").trim().slice(0, 2000);
    if (!trimmed) return;
    this.narratives.push({ agent, iteration, text: trimmed });
    this.write("subagent_narrative", { agent, iteration, chars: trimmed.length });
  }

  // ── Close ────────────────────────────────────────────────────────────────

  async close(success: boolean): Promise<{ summaryPath: string; summary: RunSummary }> {
    if (this.currentPhase) this.phaseEnd();
    const endedAt = Date.now();
    const summary: RunSummary = {
      success,
      startedAt: new Date(this.startMs).toISOString(),
      endedAt: new Date(endedAt).toISOString(),
      durationMs: endedAt - this.startMs,
      sandbox: {
        bootMs:
          this.sandboxStartedAt && this.sandboxReadyAt
            ? this.sandboxReadyAt - this.sandboxStartedAt
            : undefined,
      },
      phases: this.phases.map((p) => ({
        phase: p.phase,
        iteration: p.iteration,
        durationMs: (p.endedAt ?? endedAt) - p.startedAt,
        subagents: p.subagents,
      })),
      agents: [...this.agents.values()].map((a) => ({
        id: a.id,
        name: a.name,
        model: a.model,
        turns: a.turns,
        toolCalls: a.toolCalls,
        tokensInput: a.tokensInput,
        tokensOutput: a.tokensOutput,
        tokensCacheRead: a.tokensCacheRead,
        tokensCacheWrite: a.tokensCacheWrite,
        costUsd: a.costUsd,
        retries: a.retries,
        durationMs: (a.endedAt ?? endedAt) - a.startedAt,
        success: a.success ?? false,
        error: a.error,
      })),
      commits: this.commits,
      push: this.pushResult,
      pr: this.prResult,
      issues: this.issues,
      errors: this.errors,
      narratives: this.narratives,
    };

    this.write("run_end", { success, durationMs: summary.durationMs });

    const summaryPath = join(this.dir, "summary.json");
    if (WRITE_FILES) {
      writeFileSync(summaryPath, JSON.stringify(summary, null, 2));
    }

    await postSummary(summary);

    if (this.stream) {
      await new Promise<void>((resolve, reject) => {
        this.stream!.end((err?: Error | null) => (err ? reject(err) : resolve()));
      });
    }
    return { summaryPath, summary };
  }
}

// ── AgentHandle — thin accessor passed to runSubagent ──────────────────────

export class AgentHandle {
  constructor(private readonly journal: Journal, private readonly stats: AgentStats) {}

  get id(): string {
    return this.stats.id;
  }

  /** Called from pi event handler on tool_execution_start. */
  toolCall(tool: string, args: unknown, callId: string): void {
    this.stats.toolCalls++;
    this.journal.write("tool_call", { agentId: this.stats.id, tool, args: truncateArgs(args), callId });
  }

  /** Called on tool_execution_end. */
  toolResult(callId: string, ok: boolean, durationMs: number, preview?: string): void {
    this.journal.write("tool_result", {
      agentId: this.stats.id,
      callId,
      ok,
      durationMs,
      ...(preview ? { preview: preview.slice(0, 400) } : {}),
    });
  }

  turn(): void {
    this.stats.turns++;
  }

  usage(u: { input?: number; output?: number; cacheRead?: number; cacheWrite?: number; cost?: { total?: number } }): void {
    this.stats.tokensInput += u.input ?? 0;
    this.stats.tokensOutput += u.output ?? 0;
    this.stats.tokensCacheRead += u.cacheRead ?? 0;
    this.stats.tokensCacheWrite += u.cacheWrite ?? 0;
    this.stats.costUsd += u.cost?.total ?? 0;
  }

  retryStart(attempt: number, reason?: string): void {
    this.stats.retries++;
    this.journal.write("llm_retry_start", { agentId: this.stats.id, attempt, reason });
  }

  retryEnd(attempt: number, success: boolean): void {
    this.journal.write("llm_retry_end", { agentId: this.stats.id, attempt, success });
  }

  end(success: boolean, error?: string): void {
    this.journal._endAgent(this.stats, success, error);
  }
}

function truncateArgs(args: unknown): unknown {
  try {
    const json = JSON.stringify(args);
    if (json.length <= 800) return args;
    return { _truncated: true, preview: json.slice(0, 800) };
  } catch {
    return { _unserialisable: true };
  }
}

// ── Summary shape ─────────────────────────────────────────────────────────

export interface RunSummary {
  success: boolean;
  startedAt: string;
  endedAt: string;
  durationMs: number;
  sandbox: { bootMs?: number };
  phases: Array<{ phase: string; iteration: number; durationMs: number; subagents: string[] }>;
  agents: Array<{
    id: string;
    name: string;
    model: string;
    turns: number;
    toolCalls: number;
    tokensInput: number;
    tokensOutput: number;
    tokensCacheRead: number;
    tokensCacheWrite: number;
    costUsd: number;
    retries: number;
    durationMs: number;
    success: boolean;
    error?: string;
  }>;
  commits: Array<{ phase: string; sha: string; message: string }>;
  push?: { ok: boolean; branch?: string };
  pr?: { action: string; number?: number; url?: string };
  issues: Issue[];
  errors: string[];
  narratives: AgentNarrative[];
}

// ── Pretty end-of-run summary for stdout ─────────────────────────────────

export function printRunSummary(summary: RunSummary, journalDir: string, branch: string, prUrl?: string): void {
  const line = (s: string) => console.log(s);
  const sep = "═".repeat(70);

  line("");
  line(sep);
  const status = summary.success ? "✓" : "✗";
  line(`  RUN  ${branch}   ${status}`);
  line(sep);
  const bootStr = summary.sandbox.bootMs ? ` (boot ${fmtMs(summary.sandbox.bootMs)})` : "";
  line(`  duration      ${fmtMs(summary.durationMs)}${bootStr}`);
  line(`  branch        ${branch}   ${summary.commits.length} commits`);
  if (summary.push) line(`  push          ${summary.push.ok ? "ok" : "FAILED"}`);
  if (prUrl) line(`  pr            ${prUrl}`);
  line("");

  // Per-agent table
  const hdr = `  ${"agent".padEnd(18)}${"turns".padStart(7)}${"tools".padStart(8)}${"tok-in".padStart(10)}${"tok-out".padStart(10)}${"elapsed".padStart(10)}${"retries".padStart(10)}`;
  line(hdr);
  line(`  ${"-".repeat(hdr.length - 2)}`);
  for (const a of summary.agents) {
    line(
      `  ${a.name.padEnd(18)}${String(a.turns).padStart(7)}${String(a.toolCalls).padStart(8)}${fmtNum(a.tokensInput).padStart(10)}${fmtNum(a.tokensOutput).padStart(10)}${fmtMs(a.durationMs).padStart(10)}${String(a.retries).padStart(10)}`,
    );
  }

  // Totals
  const totals = summary.agents.reduce(
    (acc, a) => ({
      turns: acc.turns + a.turns,
      tools: acc.tools + a.toolCalls,
      tin: acc.tin + a.tokensInput,
      tout: acc.tout + a.tokensOutput,
      retries: acc.retries + a.retries,
      cost: acc.cost + a.costUsd,
    }),
    { turns: 0, tools: 0, tin: 0, tout: 0, retries: 0, cost: 0 },
  );
  line(`  ${"-".repeat(hdr.length - 2)}`);
  line(
    `  ${"total".padEnd(18)}${String(totals.turns).padStart(7)}${String(totals.tools).padStart(8)}${fmtNum(totals.tin).padStart(10)}${fmtNum(totals.tout).padStart(10)}${" ".padStart(10)}${String(totals.retries).padStart(10)}`,
  );
  if (totals.cost > 0) line(`  cost          $${totals.cost.toFixed(4)}`);

  if (summary.issues.length) {
    line("");
    line("  Non-fatal issues");
    for (const i of summary.issues) {
      line(`    - ${i.agentId}: ${i.reason}${i.resolved ? " → ok" : ""}`);
    }
  }
  if (summary.errors.length) {
    line("");
    line("  Errors");
    for (const e of summary.errors) line(`    - ${e}`);
  }

  line("");
  line(`  journal       ${journalDir}`);
  line(sep);
}

function fmtMs(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  const s = ms / 1000;
  if (s < 60) return `${s.toFixed(1)}s`;
  const m = Math.floor(s / 60);
  const rs = Math.round(s % 60);
  return `${m}m ${rs}s`;
}

function fmtNum(n: number): string {
  return n.toLocaleString("en-US");
}
