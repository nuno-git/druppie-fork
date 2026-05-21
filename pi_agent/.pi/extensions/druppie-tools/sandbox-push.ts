/**
 * Isolated push — push a git bundle from a throwaway, security-hardened
 * container. The main sandbox NEVER sees the push credential.
 */
import { copyFileSync, existsSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { join } from "node:path";
import { randomBytes } from "node:crypto";

import type { PushResult } from "./types.js";

const DEFAULT_PUSH_IMAGE = "oneshot-push-sandbox:latest";

export interface BundlePushOptions {
  bundleHostPath: string;
  remoteUrl: string;
  branch: string;
  token: string;
  pushImage?: string;
  timeoutSec?: number;
}

export function pushBundleIsolated(opts: BundlePushOptions): PushResult {
  if (!existsSync(opts.bundleHostPath)) {
    return { ok: false, output: `bundle not found on host: ${opts.bundleHostPath}` };
  }

  const image = opts.pushImage ?? DEFAULT_PUSH_IMAGE;
  ensurePushImage(image);

  const bundleVolume = process.env.PI_AGENT_BUNDLE_VOLUME;
  let mountFlag: string;
  let cleanupScratch: (() => void) | null = null;

  if (bundleVolume) {
    mountFlag = `${bundleVolume}:/in:ro`;
  } else {
    const scratch = `/tmp/oneshot-push-${Date.now()}-${randomBytes(4).toString("hex")}`;
    spawnSync("mkdir", ["-p", scratch]);
    const inPath = join(scratch, "run.bundle");
    copyFileSync(opts.bundleHostPath, inPath);
    mountFlag = `${scratch}:/in:ro`;
    cleanupScratch = () => spawnSync("rm", ["-rf", scratch]);
  }

  try {
    const pushNetwork = process.env.PI_AGENT_SANDBOX_NETWORK || "bridge";
    const args = [
      "run", "--rm",
      "--read-only",
      "--tmpfs=/tmp:rw,exec,size=128m",
      "--security-opt=no-new-privileges",
      "--cap-drop=ALL",
      `--network=${pushNetwork}`,
      "-e", `REMOTE_URL=${opts.remoteUrl}`,
      "-e", `BRANCH=${opts.branch}`,
      "-e", `GITHUB_TOKEN=${opts.token}`,
      "-e", "GIT_ASKPASS=/usr/local/bin/git-askpass",
      "-v", mountFlag,
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
    cleanupScratch?.();
  }
}

function ensurePushImage(image: string): void {
  const check = spawnSync("docker", ["image", "inspect", image], { stdio: "ignore" });
  if (check.status === 0) return;
  throw new Error(`push-sandbox image not found: ${image}\nBuild it with: docker build -t ${image} push-sandbox/`);
}
