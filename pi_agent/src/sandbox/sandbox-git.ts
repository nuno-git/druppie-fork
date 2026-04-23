/**
 * SandboxGitOps — matches the surface of src/git.ts but runs every git
 * command inside the sandbox via the daemon's /exec endpoint. This means
 * the sandbox's local VM disk is the one and only source of truth for the
 * working tree; the host never clones, checks out, or inspects the workspace.
 */
import type { GitLike, GitInitOptions } from "../git.js";
import type { SandboxClient } from "./client.js";

export class SandboxGitOps implements GitLike {
  constructor(
    private readonly client: SandboxClient,
    private readonly relCwd: string = "",
  ) {}

  private async run(cmd: string): Promise<string> {
    const chunks: Buffer[] = [];
    const result = await this.client.execStream(
      { command: cmd, cwd: this.relCwd || undefined, timeout: 60 },
      (buf) => chunks.push(buf),
    );
    const out = Buffer.concat(chunks).toString("utf-8").trim();
    if (result.exitCode !== 0) {
      throw new Error(`git command failed (${result.exitCode}): ${cmd}\n${out}`);
    }
    return out;
  }

  async init(options: GitInitOptions = {}): Promise<void> {
    await this.client.post("/init", {
      userName: options.userName ?? "oneshot-tdd-agent",
      userEmail: options.userEmail ?? "agent@oneshot-tdd.local",
      branch: options.branch ?? "main",
      remoteUrl: options.remoteUrl,
    });
  }

  async createBranch(name: string): Promise<void> {
    try {
      await this.run(`git checkout -b ${shellQuote(name)}`);
    } catch {
      await this.run(`git checkout ${shellQuote(name)}`);
    }
  }

  async stageAll(): Promise<void> {
    await this.run("git add -A");
  }

  async commit(message: string): Promise<string> {
    await this.stageAll();
    const status = await this.run("git status --porcelain");
    if (!status) return this.getCurrentHash();
    await this.run(`git commit -m ${shellQuote(message)}`);
    return this.getCurrentHash();
  }

  async getCurrentHash(): Promise<string> {
    return this.run("git rev-parse --short HEAD");
  }

  async getCurrentBranch(): Promise<string> {
    return this.run("git branch --show-current");
  }

  /** Rename the current branch in-place. */
  async renameCurrentBranch(newName: string): Promise<void> {
    await this.run(`git branch -m ${shellQuote(newName)}`);
  }

  /** List commits on the current branch that aren't on `baseRef`. Newest first. */
  async listNewCommits(baseRef: string): Promise<Array<{ sha: string; message: string }>> {
    const out = await this.run(`git log --pretty=format:%h%x00%s ${shellQuote(baseRef)}..HEAD`);
    if (!out) return [];
    return out.split("\n").map((line) => {
      const [sha, message] = line.split("\0");
      return { sha, message };
    });
  }

  async createBundle(name = "run.bundle"): Promise<{ path: string; size: number }> {
    const res = await this.client.post<{ ok: boolean; bundlePath: string; size: number; error?: string }>(
      "/bundle", { refs: ["--all"], name },
    );
    if (!res.ok) throw new Error(`bundle failed: ${res.error}`);
    return { path: res.bundlePath, size: res.size };
  }
}

function shellQuote(s: string): string {
  return `'${s.replace(/'/g, "'\\''")}'`;
}
