/**
 * Clone a remote repo on the host, bundle the single target branch, and ship
 * the bundle bytes into the sandbox. The sandbox never sees the remote URL,
 * never sees the auth token, and never opens a network connection to GitHub
 * for the clone — it only imports opaque packfile bytes.
 */
import { execFileSync, spawnSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fetch as undiciFetch, Agent } from "undici";

import type { SandboxClient } from "./client.js";

export interface SourceCloneOptions {
  remoteUrl: string; // https://github.com/org/repo
  branch: string;
  token: string; // PAT or minted App installation token
}

export async function cloneSourceIntoSandbox(
  client: SandboxClient,
  endpoint: { host: string; port: number; authToken: string },
  opts: SourceCloneOptions,
): Promise<void> {
  const work = mkdtempSync(join(tmpdir(), "oneshot-source-"));
  try {
    const bareDir = join(work, "src.git");

    // 1. Full bare clone on the host — all branches, full history. The agent
    //    inside the sandbox gets every branch locally, so it can checkout,
    //    inspect history, cherry-pick, look at feature branches, etc.
    const authedUrl = injectTokenIntoHttpsUrl(opts.remoteUrl, opts.token);
    run("git", [
      "-c", "core.hooksPath=/dev/null",
      "clone",
      "--bare",
      authedUrl,
      bareDir,
    ]);

    // 2. Bundle everything — all refs, all history.
    const bundlePath = join(work, "src.bundle");
    run("git", ["-C", bareDir, "bundle", "create", bundlePath, "--all"]);

    // 3. POST the bundle bytes to the sandbox's /import-bundle endpoint.
    const body = readFileSync(bundlePath);
    const agent = new Agent();
    const url = `http://${endpoint.host}:${endpoint.port}/import-bundle?branch=${encodeURIComponent(opts.branch)}`;
    const res = await undiciFetch(url, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${endpoint.authToken}`,
        "Content-Type": "application/octet-stream",
      },
      body,
      dispatcher: agent,
    });
    if (!res.ok) {
      const text = await res.text();
      throw new Error(`import-bundle ${res.status}: ${text}`);
    }
  } finally {
    rmSync(work, { recursive: true, force: true });
  }
}

function injectTokenIntoHttpsUrl(url: string, token: string): string {
  const parsed = new URL(url);
  if (parsed.protocol !== "https:") {
    throw new Error(`sourceRepoUrl must be https, got: ${url}`);
  }
  // x-access-token is GitHub's documented username for installation / PAT auth.
  parsed.username = "x-access-token";
  parsed.password = token;
  return parsed.toString();
}

function run(cmd: string, args: string[]): void {
  const res = spawnSync(cmd, args, { encoding: "utf-8", stdio: ["ignore", "pipe", "pipe"] });
  if (res.status !== 0) {
    throw new Error(`${cmd} ${args.join(" ")} failed (${res.status}): ${res.stderr || res.stdout}`);
  }
}
