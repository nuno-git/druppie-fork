/**
 * Remote tool operations — shim Pi SDK's pluggable tool operations so
 * bash/read/write/edit/ls/grep/find route to the sandbox daemon.
 */
import { Buffer } from "node:buffer";
import type { Stats } from "node:fs";

import type { SandboxClient } from "./sandbox-client.js";
import { synthStats } from "./types.js";

export const SANDBOX_CWD_SENTINEL = "/workspace";

function toRel(absOrRel: string): string {
  let p = absOrRel;
  if (p.startsWith(`${SANDBOX_CWD_SENTINEL}/`)) p = p.slice(SANDBOX_CWD_SENTINEL.length + 1);
  else if (p === SANDBOX_CWD_SENTINEL) p = "";
  else if (p.startsWith("/")) {
    throw new Error(`path outside sandbox workspace: ${absOrRel}`);
  }
  return p;
}

export function createRemoteBashOps(client: SandboxClient) {
  return {
    async exec(
      command: string,
      cwd: string,
      {
        onData,
        signal,
        timeout,
      }: {
        onData: (data: Buffer) => void;
        signal?: AbortSignal;
        timeout?: number;
        env?: NodeJS.ProcessEnv;
      },
    ): Promise<{ exitCode: number | null }> {
      const rel = toRel(cwd);
      const result = await client.execStream(
        { command, cwd: rel || undefined, timeout },
        (buf, _kind) => onData(buf),
        signal,
      );
      if (result.timedOut) throw new Error(`timeout:${timeout}`);
      return { exitCode: result.exitCode };
    },
  };
}

export function createRemoteReadOps(client: SandboxClient) {
  return {
    async readFile(path: string): Promise<Buffer> {
      const rel = toRel(path);
      const res = await client.post<{ content: string; encoding: string; size: number }>(
        "/read", { path: rel },
      );
      return res.encoding === "base64"
        ? Buffer.from(res.content, "base64")
        : Buffer.from(res.content, "utf-8");
    },
    async access(path: string): Promise<void> {
      const rel = toRel(path);
      await client.post("/access", { path: rel, mode: "r" });
    },
    async detectImageMimeType(_path: string): Promise<string | null | undefined> {
      return undefined;
    },
  };
}

export function createRemoteWriteOps(client: SandboxClient) {
  return {
    async writeFile(path: string, content: string | Buffer): Promise<void> {
      const rel = toRel(path);
      const isBuf = Buffer.isBuffer(content);
      await client.post("/write", {
        path: rel,
        content: isBuf ? (content as Buffer).toString("base64") : content,
        encoding: isBuf ? "base64" : "utf-8",
      });
    },
    async mkdir(_dir: string): Promise<void> {
      // write endpoint already mkdir -p's the parent
    },
  };
}

export function createRemoteEditOps(client: SandboxClient) {
  return {
    async readFile(path: string): Promise<Buffer> {
      const rel = toRel(path);
      const res = await client.post<{ content: string; encoding: string }>(
        "/read", { path: rel },
      );
      return res.encoding === "base64"
        ? Buffer.from(res.content, "base64")
        : Buffer.from(res.content, "utf-8");
    },
    async writeFile(path: string, content: string | Buffer): Promise<void> {
      const rel = toRel(path);
      const isBuf = Buffer.isBuffer(content);
      await client.post("/write", {
        path: rel,
        content: isBuf ? (content as Buffer).toString("base64") : content,
        encoding: isBuf ? "base64" : "utf-8",
      });
    },
    async access(path: string): Promise<void> {
      const rel = toRel(path);
      await client.post("/access", { path: rel, mode: "rw" });
    },
  };
}

export function createRemoteLsOps(client: SandboxClient) {
  return {
    exists(path: string): boolean {
      const rel = toRel(path);
      try {
        const res = client.postSync<{ exists: boolean }>("/stat", { path: rel });
        return res.exists;
      } catch {
        return false;
      }
    },
    stat(path: string): Stats {
      const rel = toRel(path);
      const res = client.postSync<{
        exists: boolean; isFile: boolean; isDirectory: boolean;
        size: number; mtimeMs: number;
      }>("/stat", { path: rel });
      if (!res.exists) throw new Error(`ENOENT: ${path}`);
      return synthStats(res);
    },
    readdir(path: string): string[] {
      const rel = toRel(path);
      const res = client.postSync<{ entries: Array<{ name: string }> }>(
        "/ls", { path: rel },
      );
      return res.entries.map((e) => e.name);
    },
  };
}

export function createRemoteGrepOps(client: SandboxClient) {
  return {
    async isDirectory(path: string): Promise<boolean> {
      const rel = toRel(path);
      const res = await client.post<{ exists: boolean; isDirectory: boolean }>(
        "/stat", { path: rel },
      );
      return res.exists && res.isDirectory;
    },
    async readFile(_path: string): Promise<string> {
      const rel = toRel(_path);
      const res = await client.post<{ content: string }>("/read", { path: rel });
      return res.content;
    },
  };
}

export function createRemoteFindOps(client: SandboxClient) {
  return {
    exists(path: string): boolean {
      const rel = toRel(path);
      try {
        const res = client.postSync<{ exists: boolean }>("/stat", { path: rel });
        return res.exists;
      } catch {
        return false;
      }
    },
    async glob(
      pattern: string,
      searchPath: string,
      _opts: { ignore?: string[]; limit?: number },
    ): Promise<string[]> {
      const rel = toRel(searchPath);
      const res = await client.post<{ files: string[] }>(
        "/find", { pattern, path: rel, limit: _opts?.limit ?? 1000 },
      );
      return res.files;
    },
  };
}


