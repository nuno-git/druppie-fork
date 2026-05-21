import { execFileSync, spawnSync } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { randomBytes } from "node:crypto";

import { SandboxClient } from "./sandbox-client.js";
import { KATA_RUNTIME, SYSBOX_RUNTIME } from "./types.js";
import type { SandboxRuntime, SandboxLaunchOptions, RunningSandbox } from "./types.js";

export type LaunchedSandbox = RunningSandbox & { client: SandboxClient };

const DEFAULT_IMAGE = "oneshot-sandbox:latest";

export function defaultSandboxLaunchOptions(): SandboxLaunchOptions {
  const runtimeEnv = process.env.ONESHOT_SANDBOX_RUNTIME ?? KATA_RUNTIME;
  if (runtimeEnv !== KATA_RUNTIME && runtimeEnv !== SYSBOX_RUNTIME) {
    throw new Error(
      `Unsupported sandbox runtime "${runtimeEnv}". Set ONESHOT_SANDBOX_RUNTIME to "${KATA_RUNTIME}" (prod) or "${SYSBOX_RUNTIME}" (dev).`,
    );
  }
  return {
    image: process.env.ONESHOT_SANDBOX_IMAGE ?? DEFAULT_IMAGE,
    runtime: runtimeEnv,
    memoryLimit: process.env.ONESHOT_SANDBOX_MEMORY ?? "4g",
    cpuLimit: process.env.ONESHOT_SANDBOX_CPUS ?? "2",
    pidsLimit: Number(process.env.ONESHOT_SANDBOX_PIDS ?? 8192),
    allowNetwork: (process.env.ONESHOT_SANDBOX_NETWORK ?? "1") !== "0",
    timeoutSec: Number(process.env.ONESHOT_SANDBOX_TIMEOUT ?? 24 * 3600),
  };
}

export async function launchSandbox(opts: SandboxLaunchOptions): Promise<LaunchedSandbox> {
  ensureImage(opts.image);
  ensureRuntimeAvailable(opts.runtime);

  const stamp = Date.now();
  const rand = randomBytes(4).toString("hex");
  const containerName = `oneshot-sandbox-${stamp}-${rand}`;
  const authToken = randomBytes(32).toString("hex");

  const workDir = mkdtempSync(join(tmpdir(), "oneshot-sandbox-"));
  const bundleHostDir = join(workDir, "out");
  execFileSync("mkdir", ["-p", bundleHostDir]);

  const envFlags: string[] = [];
  envFlags.push("-e", `SANDBOX_AUTH_TOKEN=${authToken}`);
  envFlags.push("-e", "SANDBOX_BIND_HOST=0.0.0.0");
  envFlags.push("-e", "SANDBOX_BIND_PORT=8000");
  for (const [k, v] of Object.entries(opts.env ?? {})) {
    envFlags.push("-e", `${k}=${v}`);
  }

  const isolationFlags = opts.runtime === KATA_RUNTIME ? ["--privileged"] : [];

  const sharedNetwork = process.env.PI_AGENT_SANDBOX_NETWORK;
  const networkFlags = sharedNetwork
    ? ["--network", sharedNetwork]
    : (opts.allowNetwork ? [] : ["--network=none"]);
  const portFlags = sharedNetwork ? [] : ["-p", "127.0.0.1::8000"];

  const bundleVolume = process.env.PI_AGENT_BUNDLE_VOLUME;
  const bundleHostDirOverride = process.env.PI_AGENT_BUNDLE_HOST_DIR;
  const effectiveBundleHostDir = bundleVolume
    ? (bundleHostDirOverride || "/app/pi_agent_bundles")
    : bundleHostDir;
  const bundleMountFlags = bundleVolume
    ? ["-v", `${bundleVolume}:/out`]
    : ["-v", `${bundleHostDir}:/out`];

  const args = [
    "run", "-d",
    "--name", containerName,
    `--runtime=${opts.runtime}`,
    ...isolationFlags,
    `--memory=${opts.memoryLimit}`,
    `--cpus=${opts.cpuLimit}`,
    `--pids-limit=${opts.pidsLimit}`,
    ...networkFlags,
    ...portFlags,
    ...bundleMountFlags,
    ...envFlags,
    opts.image,
  ];

  const result = spawnSync("docker", args, { encoding: "utf-8" });
  if (result.status !== 0) {
    rmSync(workDir, { recursive: true, force: true });
    throw new Error(`docker run failed: ${result.stderr || result.stdout}`);
  }

  let sandboxHost: string;
  let hostPort: number;
  if (sharedNetwork) {
    sandboxHost = containerName;
    hostPort = 8000;
  } else {
    const portOut = spawnSync("docker", ["port", containerName, "8000/tcp"], { encoding: "utf-8" });
    const portMatch = (portOut.stdout || "").match(/:(\d+)\s*$/m);
    hostPort = portMatch ? Number(portMatch[1]) : 0;
    if (!hostPort) {
      spawnSync("docker", ["rm", "-f", containerName], { stdio: "ignore" });
      rmSync(workDir, { recursive: true, force: true });
      throw new Error(`could not resolve sandbox host port: ${portOut.stdout}`);
    }
    sandboxHost = process.env.PI_AGENT_SANDBOX_HOST ?? "127.0.0.1";
  }

  const client = new SandboxClient({ host: sandboxHost, port: hostPort, authToken });
  await waitForHealth(client, opts.timeoutSec);

  const timeoutHandle = setTimeout(() => {
    console.warn(`[sandbox] wall-clock timeout hit (${opts.timeoutSec}s), stopping container`);
    stop();
  }, opts.timeoutSec * 1000);
  if (typeof timeoutHandle.unref === "function") timeoutHandle.unref();

  let stopped = false;
  function stop() {
    if (stopped) return;
    stopped = true;
    clearTimeout(timeoutHandle);
    try { spawnSync("docker", ["rm", "-f", containerName], { stdio: "ignore" }); } catch { /* ignore */ }
    try { rmSync(workDir, { recursive: true, force: true }); } catch { /* ignore */ }
  }

  return { containerName, bundleHostDir: effectiveBundleHostDir, authToken, host: sandboxHost, hostPort, client, stop };
}

export function stopSandbox(containerId: string): void {
  spawnSync("docker", ["rm", "-f", containerId], { stdio: "ignore" });
}

function ensureImage(image: string): void {
  const check = spawnSync("docker", ["image", "inspect", image], { stdio: "ignore" });
  if (check.status === 0) return;
  throw new Error(`sandbox image not found: ${image}\nBuild it with: docker build -t ${image} sandbox/`);
}

function ensureRuntimeAvailable(runtime: SandboxRuntime): void {
  const res = spawnSync("docker", ["info", "--format", "{{json .Runtimes}}"], { encoding: "utf-8" });
  if (res.status !== 0) {
    throw new Error(`docker info failed: ${res.stderr || res.stdout}`);
  }
  try {
    const runtimes = JSON.parse(res.stdout) as Record<string, unknown>;
    if (!runtimes[runtime]) {
      const installHint = runtime === KATA_RUNTIME
        ? "https://github.com/kata-containers/kata-containers/blob/main/docs/install/docker/"
        : "https://github.com/nestybox/sysbox/blob/master/docs/user-guide/install-package.md";
      throw new Error(
        `Runtime "${runtime}" is not registered with Docker.\nInstall it and restart dockerd:\n${installHint}\nAvailable runtimes: ${Object.keys(runtimes).join(", ")}`,
      );
    }
  } catch (err) {
    if (err instanceof SyntaxError) {
      throw new Error(`could not parse docker info output: ${res.stdout}`);
    }
    throw err;
  }
}

async function waitForHealth(client: SandboxClient, timeoutSec: number): Promise<void> {
  const deadline = Date.now() + Math.min(timeoutSec, 60) * 1000;
  let lastErr: unknown;
  while (Date.now() < deadline) {
    try {
      await client.get("/health");
      return;
    } catch (err) {
      lastErr = err;
      await new Promise((r) => setTimeout(r, 200));
    }
  }
  throw new Error(`sandbox daemon did not become ready: ${lastErr}`);
}
