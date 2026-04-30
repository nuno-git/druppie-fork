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

    // 2. Verify the requested branch exists; otherwise fall back to the
    //    remote's default (HEAD). Without this, callers hardcoding
    //    e.g. "colab-dev" break against test fixtures that only have main.
    const effectiveBranch = resolveBranch(bareDir, opts.branch);

    // 3. Bundle everything — all refs, all history.
    const bundlePath = join(work, "src.bundle");
    run("git", ["-C", bareDir, "bundle", "create", bundlePath, "--all"]);

    // 4. POST the bundle bytes to the sandbox's /import-bundle endpoint.
    const body = readFileSync(bundlePath);
    const agent = new Agent();
    const url = `http://${endpoint.host}:${endpoint.port}/import-bundle?branch=${encodeURIComponent(effectiveBranch)}`;
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
  // Allow both https (external providers like GitHub) and http (internal
  // dev providers like druppie's Gitea on the docker bridge). The clear-wire
  // concern doesn't apply on a private compose network, and refusing http
  // there broke Gitea-backed runs entirely.
  if (parsed.protocol !== "https:" && parsed.protocol !== "http:") {
    throw new Error(`sourceRepoUrl must be http(s), got: ${url}`);
  }
  // x-access-token is GitHub's documented username for installation / PAT
  // auth; Gitea accepts the same shape (any username works with a PAT).
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

/** Pick the branch to check out inside the sandbox. If `requested` exists in
 * the bare clone, use it. Otherwise fall back to the remote's default
 * branch (HEAD) — this stops runs from exploding on legitimately-missing
 * branches (e.g. caller hardcoded "colab-dev" but the repo only has main).
 */
function resolveBranch(bareDir: string, requested: string): string {
  const has = (ref: string): boolean => {
    const res = spawnSync("git", ["-C", bareDir, "show-ref", "--verify", "--quiet", ref], { stdio: "ignore" });
    return res.status === 0;
  };
  if (requested && has(`refs/heads/${requested}`)) return requested;

  // Default: whatever HEAD points at in the remote.
  const headRef = spawnSync(
    "git",
    ["-C", bareDir, "symbolic-ref", "--short", "HEAD"],
    { encoding: "utf-8", stdio: ["ignore", "pipe", "pipe"] },
  );
  const head = headRef.stdout?.trim();
  if (headRef.status === 0 && head) {
    if (requested && requested !== head) {
      console.warn(`[source-clone] requested branch "${requested}" not found; falling back to default "${head}"`);
    }
    return head;
  }
  // Last-ditch: pick any branch so the sandbox at least boots.
  const anyBranch = spawnSync(
    "git",
    ["-C", bareDir, "for-each-ref", "--format=%(refname:short)", "--count=1", "refs/heads/"],
    { encoding: "utf-8", stdio: ["ignore", "pipe", "pipe"] },
  );
  const fallback = anyBranch.stdout?.trim();
  if (fallback) return fallback;
  throw new Error(`could not determine a branch to use in ${bareDir}`);
}
