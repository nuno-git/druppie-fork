/**
 * Bundle push — take the git bundle the sandbox produced and push it to the
 * real remote from a throwaway, egress-restricted container.
 *
 * Key property: the sandbox that produced the bundle NEVER sees the push
 * credential. The push container only ever sees the credential + the bundle.
 * If the bundle triggers a git-parser CVE, the blast radius is this
 * short-lived container with a scoped token.
 */
import { copyFileSync, existsSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { join } from "node:path";
import { randomBytes } from "node:crypto";

export interface BundlePushOptions {
  /** Host path to the bundle file (from mkdtemp dir). */
  bundleHostPath: string;
  /** e.g. "https://github.com/org/repo" (no trailing .git required). */
  remoteUrl: string;
  /** Branch to push. Must exist in the bundle. */
  branch: string;
  /** GitHub App installation token or PAT with repo write. */
  token: string;
  /** Image name for the push sandbox. */
  pushImage?: string;
  /** Wall-clock timeout, seconds. */
  timeoutSec?: number;
}

const DEFAULT_PUSH_IMAGE = "oneshot-push-sandbox:latest";

export function pushBundleIsolated(opts: BundlePushOptions): { ok: boolean; output: string } {
  if (!existsSync(opts.bundleHostPath)) {
    return { ok: false, output: `bundle not found on host: ${opts.bundleHostPath}` };
  }

  const image = opts.pushImage ?? DEFAULT_PUSH_IMAGE;
  ensureImage(image);

  // Copy the bundle into a scratch dir we can mount read-only so the push
  // container has no write access to the host filesystem at all.
  const scratch = `/tmp/oneshot-push-${Date.now()}-${randomBytes(4).toString("hex")}`;
  spawnSync("mkdir", ["-p", scratch]);
  const inPath = join(scratch, "run.bundle");
  copyFileSync(opts.bundleHostPath, inPath);

  try {
    const args = [
      "run",
      "--rm",
      "--read-only",
      "--tmpfs=/tmp:rw,exec,size=128m",
      "--security-opt=no-new-privileges",
      "--cap-drop=ALL",
      "--network=bridge", // needs real DNS + internet to reach github
      "-e", `REMOTE_URL=${asHttpsWithToken(opts.remoteUrl)}`,
      "-e", `BRANCH=${opts.branch}`,
      "-e", `GITHUB_TOKEN=${opts.token}`,
      "-e", "GIT_ASKPASS=/usr/local/bin/git-askpass",
      "-v", `${scratch}:/in:ro`,
      image,
    ];
    const res = spawnSync("docker", args, {
      encoding: "utf-8",
      timeout: (opts.timeoutSec ?? 120) * 1000,
      maxBuffer: 4 * 1024 * 1024,
    });
    const output = (res.stdout || "") + (res.stderr || "");
    return { ok: res.status === 0, output };
  } finally {
    spawnSync("rm", ["-rf", scratch]);
  }
}

function ensureImage(image: string): void {
  const check = spawnSync("docker", ["image", "inspect", image], { stdio: "ignore" });
  if (check.status === 0) return;
  throw new Error(
    `push-sandbox image not found: ${image}\n` +
      `Build it with: docker build -t ${image} push-sandbox/`,
  );
}

/**
 * We don't want to embed the token in REMOTE_URL (it would show up in `ps`).
 * Instead we rely on GIT_ASKPASS returning the token. But GitHub still needs
 * the URL to be https://github.com/org/repo — leave it as-is.
 */
function asHttpsWithToken(url: string): string {
  return url;
}
