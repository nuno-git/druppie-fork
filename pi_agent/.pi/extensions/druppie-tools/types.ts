import type { Stats } from "node:fs";

export interface SandboxEndpoint {
  socketPath?: string;
  host?: string;
  port?: number;
  authToken: string;
}

export const KATA_RUNTIME = "kata-runtime";
export const SYSBOX_RUNTIME = "sysbox-runc";
export type SandboxRuntime = typeof KATA_RUNTIME | typeof SYSBOX_RUNTIME;

export interface SandboxLaunchOptions {
  image: string;
  runtime: SandboxRuntime;
  memoryLimit: string;
  cpuLimit: string;
  pidsLimit: number;
  allowNetwork: boolean;
  timeoutSec: number;
  env?: Record<string, string>;
}

export interface RunningSandbox {
  containerName: string;
  bundleHostDir: string;
  authToken: string;
  host: string;
  hostPort: number;
  stop: () => void;
}

export type GitProviderKind = "github_app" | "gitea";

export interface GitProvider {
  kind: GitProviderKind;
  resolveToken(): Promise<string | undefined>;
  ensurePullRequest(opts: EnsurePrOptions): Promise<EnsurePrResult>;
}

export interface EnsurePrOptions {
  remoteUrl: string;
  head: string;
  base: string;
  token: string;
  title: string;
  body: string;
}

export interface EnsurePrResult {
  action: "created" | "exists" | "skipped";
  url?: string;
  number?: number;
  message?: string;
}

export interface PushResult {
  ok: boolean;
  output: string;
}

export interface StatResponse {
  exists: boolean;
  isFile: boolean;
  isDirectory: boolean;
  size: number;
  mtimeMs: number;
}

export function synthStats(res: StatResponse): Stats {
  const now = new Date(res.mtimeMs || Date.now());
  return {
    isFile: () => res.isFile,
    isDirectory: () => res.isDirectory,
    isBlockDevice: () => false,
    isCharacterDevice: () => false,
    isSymbolicLink: () => false,
    isFIFO: () => false,
    isSocket: () => false,
    size: res.size,
    atime: now, mtime: now, ctime: now, birthtime: now,
    atimeMs: res.mtimeMs, mtimeMs: res.mtimeMs, ctimeMs: res.mtimeMs, birthtimeMs: res.mtimeMs,
    dev: 0, ino: 0, mode: 0, nlink: 1, uid: 0, gid: 0, rdev: 0, blksize: 4096, blocks: 0,
  } as Stats;
}
