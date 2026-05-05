/**
 * Source injection — clone on host, bundle, ship into sandbox.
 * The sandbox never sees the remote URL, auth token, or opens a network
 * connection to the git provider for the clone.
 */
import { execFileSync, spawnSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { Agent, fetch as undiciFetch } from "undici";

import { SandboxClient } from "./sandbox-client.js";

export interface SourceCloneOptions {
  remoteUrl: string;
  branch: string;
  token: string;
}

export async function cloneSourceIntoSandbox(
  client: SandboxClient,
  endpoint: { host: string; port: number; authToken: string },
  opts: SourceCloneOptions,
): Promise<void> {
  const work = mkdtempSync(join(tmpdir(), "oneshot-source-"));
  try {
    const bareDir = join(work, "src.git");

    const authedUrl = injectTokenIntoHttpsUrl(opts.remoteUrl, opts.token);
    run("git", ["-c", "core.hooksPath=/dev/null", "clone", "--bare", authedUrl, bareDir]);

    const effectiveBranch = resolveBranch(bareDir, opts.branch);

    const bundlePath = join(work, "src.bundle");
    run("git", ["-C", bareDir, "bundle", "create", bundlePath, "--all"]);

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
  if (parsed.protocol !== "https:" && parsed.protocol !== "http:") {
    throw new Error(`sourceRepoUrl must be http(s), got: ${url}`);
  }
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

function resolveBranch(bareDir: string, requested: string): string {
  const has = (ref: string): boolean => {
    const res = spawnSync("git", ["-C", bareDir, "show-ref", "--verify", "--quiet", ref], { stdio: "ignore" });
    return res.status === 0;
  };
  if (requested && has(`refs/heads/${requested}`)) return requested;

  const headRef = spawnSync(
    "git",
    ["-C", bareDir, "symbolic-ref", "--short", "HEAD"],
    { encoding: "utf-8", stdio: ["ignore", "pipe", "pipe"] },
  );
  const head = headRef.stdout?.trim();
  if (headRef.status === 0 && head) {
    if (requested && requested !== head) {
      console.warn(`[source-clone] branch "${requested}" not found; falling back to "${head}"`);
    }
    return head;
  }

  const anyBranch = spawnSync(
    "git",
    ["-C", bareDir, "for-each-ref", "--format=%(refname:short)", "--count=1", "refs/heads/"],
    { encoding: "utf-8", stdio: ["ignore", "pipe", "pipe"] },
  );
  const fallback = anyBranch.stdout?.trim();
  if (fallback) return fallback;
  throw new Error(`could not determine a branch to use in ${bareDir}`);
}
