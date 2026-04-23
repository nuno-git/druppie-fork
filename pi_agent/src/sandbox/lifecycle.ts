/**
 * Sandbox lifecycle — launch/tear down a Kata Containers microVM running the
 * sandbox daemon, and hold the handles the host needs to talk to it.
 *
 * The sandbox ALWAYS runs as a Kata microVM (`docker run --runtime=kata-runtime`).
 * The host must have Kata installed as a Docker runtime. There is no
 * "plain docker" or "runsc" fallback — every container gets its own kernel.
 */
import { execFileSync, spawnSync } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { randomBytes } from "node:crypto";

import { SandboxClient } from "./client.js";

export const KATA_RUNTIME = "kata-runtime";
export const SYSBOX_RUNTIME = "sysbox-runc";

/**
 * Runtime selection — "kata-runtime" in production (microVM, own kernel) or
 * "sysbox-runc" for development on hosts without nested virt (user-namespace
 * isolation + docker-in-docker support, no VM). Override with
 * `ONESHOT_SANDBOX_RUNTIME` env var.
 */
export type SandboxRuntime = typeof KATA_RUNTIME | typeof SYSBOX_RUNTIME;

export interface SandboxLaunchOptions {
  image: string;
  runtime: SandboxRuntime;
  memoryLimit: string; // e.g. "4g"
  cpuLimit: string; // e.g. "2"
  pidsLimit: number; // e.g. 8192
  allowNetwork: boolean; // default true — sandbox needs internet to npm/pip install
  timeoutSec: number; // wall-clock cap before we tear down
  env?: Record<string, string>;
}

export interface RunningSandbox {
  containerName: string;
  bundleHostDir: string;
  authToken: string;
  hostPort: number;
  client: SandboxClient;
  stop: () => void;
}

const DEFAULT_IMAGE = "oneshot-sandbox:latest";

export function defaultSandboxLaunchOptions(): SandboxLaunchOptions {
  const runtimeEnv = process.env.ONESHOT_SANDBOX_RUNTIME ?? KATA_RUNTIME;
  if (runtimeEnv !== KATA_RUNTIME && runtimeEnv !== SYSBOX_RUNTIME) {
    throw new Error(
      `Unsupported sandbox runtime "${runtimeEnv}". ` +
        `Set ONESHOT_SANDBOX_RUNTIME to "${KATA_RUNTIME}" (prod) or "${SYSBOX_RUNTIME}" (dev).`,
    );
  }
  return {
    image: process.env.ONESHOT_SANDBOX_IMAGE ?? DEFAULT_IMAGE,
    runtime: runtimeEnv,
    memoryLimit: process.env.ONESHOT_SANDBOX_MEMORY ?? "4g",
    cpuLimit: process.env.ONESHOT_SANDBOX_CPUS ?? "2",
    pidsLimit: Number(process.env.ONESHOT_SANDBOX_PIDS ?? 8192),
    allowNetwork: (process.env.ONESHOT_SANDBOX_NETWORK ?? "1") !== "0",
    // 24h default — the idea is "retry through transient failures indefinitely,
    // but eventually give up". Override with ONESHOT_SANDBOX_TIMEOUT env var.
    timeoutSec: Number(process.env.ONESHOT_SANDBOX_TIMEOUT ?? 24 * 3600),
  };
}

export async function launchSandbox(opts: SandboxLaunchOptions): Promise<RunningSandbox> {
  ensureImage(opts.image);
  ensureRuntimeAvailable(opts.runtime);

  const stamp = Date.now();
  const rand = randomBytes(4).toString("hex");
  const containerName = `oneshot-sandbox-${stamp}-${rand}`;
  const authToken = randomBytes(32).toString("hex");

  // Host-side working dir: holds the out/ dir where the daemon drops the final
  // git bundle. Daemon communication is over loopback TCP (a dynamic host port),
  // not a shared unix socket — that avoids UID-mismatch headaches on bind mounts
  // and works identically under docker/runsc/kata runtimes.
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

  // Under Kata, --privileged is VM-scoped (safe) and dockerd inside needs it.
  // Under Sysbox, privileges come from sysbox-fs (user namespaces) — do NOT
  // pass --privileged, as it would bypass the isolation we came for. Sysbox
  // gives dockerd-in-container the right caps without global privilege.
  const isolationFlags = opts.runtime === KATA_RUNTIME ? ["--privileged"] : [];

  const args = [
    "run",
    "-d",
    "--name", containerName,
    `--runtime=${opts.runtime}`,
    ...isolationFlags,
    `--memory=${opts.memoryLimit}`,
    `--cpus=${opts.cpuLimit}`,
    `--pids-limit=${opts.pidsLimit}`,
    ...(opts.allowNetwork ? [] : ["--network=none"]),
    // Publish the exec-daemon port on a random loopback port chosen by Docker.
    "-p", "127.0.0.1::8000",
    // Bundle output dir — only opaque git-pack bytes ever cross this boundary.
    "-v", `${bundleHostDir}:/out`,
    ...envFlags,
    opts.image,
  ];

  const result = spawnSync("docker", args, { encoding: "utf-8" });
  if (result.status !== 0) {
    rmSync(workDir, { recursive: true, force: true });
    throw new Error(`docker run failed: ${result.stderr || result.stdout}`);
  }

  // Ask docker for the dynamically chosen host port
  const portOut = spawnSync("docker", ["port", containerName, "8000/tcp"], { encoding: "utf-8" });
  const portMatch = (portOut.stdout || "").match(/:(\d+)\s*$/m);
  const hostPort = portMatch ? Number(portMatch[1]) : 0;
  if (!hostPort) {
    spawnSync("docker", ["rm", "-f", containerName], { stdio: "ignore" });
    rmSync(workDir, { recursive: true, force: true });
    throw new Error(`could not resolve sandbox host port: ${portOut.stdout}`);
  }

  // Build the client and wait for the daemon to become reachable.
  // Host override: when pi_agent runs inside another container (e.g. druppie's
  // backend container with /var/run/docker.sock bind-mounted), the sandbox is
  // a *sibling* container. Its published port lives on the real host's
  // 127.0.0.1, which is NOT the same loopback as inside our container.
  // PI_AGENT_SANDBOX_HOST=host.docker.internal (aliased via extra_hosts)
  // routes through the host-gateway and reaches the published port correctly.
  const sandboxHost = process.env.PI_AGENT_SANDBOX_HOST ?? "127.0.0.1";
  const client = new SandboxClient({ host: sandboxHost, port: hostPort, authToken });
  await waitForHealth(client, opts.timeoutSec);

  // Schedule a wall-clock timeout to forcibly tear down
  const timeoutHandle = setTimeout(() => {
    console.warn(`[sandbox] wall-clock timeout hit (${opts.timeoutSec}s), stopping container`);
    stop();
  }, opts.timeoutSec * 1000);
  // Don't let this keep the event loop alive if we finish early
  if (typeof timeoutHandle.unref === "function") timeoutHandle.unref();

  let stopped = false;
  const stop = () => {
    if (stopped) return;
    stopped = true;
    clearTimeout(timeoutHandle);
    try {
      spawnSync("docker", ["rm", "-f", containerName], { stdio: "ignore" });
    } catch {
      // ignore
    }
    try {
      rmSync(workDir, { recursive: true, force: true });
    } catch {
      // ignore
    }
  };

  return { containerName, bundleHostDir, authToken, hostPort, client, stop };
}

function ensureImage(image: string): void {
  const check = spawnSync("docker", ["image", "inspect", image], { stdio: "ignore" });
  if (check.status === 0) return;
  throw new Error(
    `sandbox image not found: ${image}\n` +
      `Build it with: docker build -t ${image} sandbox/`,
  );
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
        ? "  https://github.com/kata-containers/kata-containers/blob/main/docs/install/docker/"
        : "  https://github.com/nestybox/sysbox/blob/master/docs/user-guide/install-package.md";
      throw new Error(
        `Runtime "${runtime}" is not registered with Docker.\n` +
          `Install it and restart dockerd:\n${installHint}\n` +
          `Available runtimes: ${Object.keys(runtimes).join(", ")}`,
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
