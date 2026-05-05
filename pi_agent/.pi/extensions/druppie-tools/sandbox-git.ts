/**
 * Git operations inside the sandbox via the daemon's /exec and /bundle endpoints.
 * The host never clones, checks out, or inspects the workspace directly.
 */
import type { SandboxClient } from "./sandbox-client.js";

export interface GitInitOptions {
  userName?: string;
  userEmail?: string;
  branch?: string;
  remoteUrl?: string;
}

export class SandboxGitOps {
  constructor(
    private readonly client: SandboxClient,
    private readonly relCwd: string = "",
  ) {}

  private async run(cmd: string): Promise<string> {
    const chunks: Buffer[] = [];
    const result = await this.client.execStream(
      { command: cmd, cwd: this.relCwd || undefined, timeout: 60 },
      (buf, kind) => {
        if (kind === "stdout") chunks.push(buf);
        else chunks.push(buf); // stderr too for error messages
      },
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

  async renameCurrentBranch(newName: string): Promise<void> {
    await this.run(`git branch -m ${shellQuote(newName)}`);
  }

  async listNewCommits(baseRef: string): Promise<Array<{ sha: string; message: string }>> {
    const out = await this.run(`git log --pretty=format:%h%x00%s ${shellQuote(baseRef)}..HEAD`);
    if (!out) return [];
    return out.split("\n").map((line) => {
      const [sha, message] = line.split("\0");
      return { sha: sha ?? "", message: message ?? "" };
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
