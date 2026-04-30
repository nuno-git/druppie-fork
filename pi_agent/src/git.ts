/**
 * Git operations for the one-shot agent.
 * Local-fs variant — runs git directly against a host directory.
 * Every phase gets a commit.
 *
 * All methods are async to match the shape of SandboxGitOps (which must
 * RPC into the sandbox). The local impl just wraps execSync.
 */
import { execSync } from "node:child_process";

export interface GitLike {
  init(options?: GitInitOptions): Promise<void>;
  createBranch(name: string): Promise<void>;
  commit(message: string): Promise<string>;
  getCurrentHash(): Promise<string>;
  getCurrentBranch(): Promise<string>;
}

export interface GitInitOptions {
  userName?: string;
  userEmail?: string;
  branch?: string;
  remoteUrl?: string;
}

export class GitOps implements GitLike {
  constructor(private cwd: string) {}

  private run(cmd: string): string {
    return execSync(cmd, { cwd: this.cwd, encoding: "utf-8", timeout: 30_000 }).trim();
  }

  async init(_options: GitInitOptions = {}): Promise<void> {
    try {
      this.run("git rev-parse --git-dir");
    } catch {
      this.run("git init");
    }
    try {
      this.run("git config user.email");
    } catch {
      this.run('git config user.email "agent@oneshot-tdd.local"');
      this.run('git config user.name "oneshot-tdd-agent"');
    }
    try {
      this.run("git rev-parse HEAD");
    } catch {
      this.run("git add -A");
      this.run('git commit --allow-empty -m "initial commit"');
    }
  }

  async createBranch(name: string): Promise<void> {
    try {
      this.run(`git checkout -b ${name}`);
    } catch {
      this.run(`git checkout ${name}`);
    }
  }

  async commit(message: string): Promise<string> {
    this.run("git add -A");
    const status = this.run("git status --porcelain");
    if (!status) return this.getCurrentHashSync();
    this.run(`git commit -m ${JSON.stringify(message)}`);
    return this.getCurrentHashSync();
  }

  async getCurrentHash(): Promise<string> {
    return this.getCurrentHashSync();
  }

  private getCurrentHashSync(): string {
    return this.run("git rev-parse --short HEAD");
  }

  async getCurrentBranch(): Promise<string> {
    return this.run("git branch --show-current");
  }

  async push(remote = "origin"): Promise<void> {
    const branch = await this.getCurrentBranch();
    this.run(`git push -u ${remote} ${branch}`);
  }
}
