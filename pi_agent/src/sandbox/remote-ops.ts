/**
 * Remote tool operations — shim the Pi SDK's pluggable tool operations
 * so that bash/read/write/edit/ls/grep/find all route to the sandbox daemon
 * instead of the local filesystem.
 *
 * Pi's own tools handle schemas, abort signals, truncation, diff rendering,
 * and result shape. We only replace the syscalls they make.
 */
import { Buffer } from "node:buffer";
import type { Stats } from "node:fs";
import type { SandboxClient } from "./client.js";

// ── Path handling ─────────────────────────────────────────────────────────
// Pi tools resolve user paths via `resolveToCwd(path, cwd)`. cwd is the host
// "workspace" string we pass in (we use the sentinel "/workspace" so Pi's
// cwd and the sandbox's workspace line up 1:1). `resolveToCwd` will return
// absolute paths starting with /workspace — we strip the prefix and forward
// the relative path to the daemon.

export const SANDBOX_CWD_SENTINEL = "/workspace";

function toRel(absOrRel: string): string {
  let p = absOrRel;
  if (p.startsWith(`${SANDBOX_CWD_SENTINEL}/`)) p = p.slice(SANDBOX_CWD_SENTINEL.length + 1);
  else if (p === SANDBOX_CWD_SENTINEL) p = "";
  else if (p.startsWith("/")) {
    // Absolute path outside /workspace — reject.
    throw new Error(`path outside sandbox workspace: ${absOrRel}`);
  }
  return p;
}

// ── Bash ──────────────────────────────────────────────────────────────────

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
        (buf) => onData(buf),
        signal,
      );
      if (result.timedOut) throw new Error(`timeout:${timeout}`);
      return { exitCode: result.exitCode };
    },
  };
}

// ── Read / Write / Edit (async, use async HTTP) ───────────────────────────

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
      // Good enough for now — let pi treat everything as text. If we need
      // image support, do a remote /stat + extension lookup.
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
      // write endpoint already mkdir -p's the parent, so this is a no-op for
      // pi's write tool path. If pi calls mkdir explicitly, run it via exec.
      // (Not triggered in current pi versions.)
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

// ── Sync ops (ls, grep, find) — pi calls these synchronously ──────────────

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
      const res = client.postSync<{ exists: boolean; isFile: boolean; isDirectory: boolean; size: number; mtimeMs: number }>(
        "/stat", { path: rel },
      );
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
      // Pi's grep falls back to JS-level regex over file contents if the
      // built-in rg fast-path isn't used. We delegate to the daemon's rg
      // via a top-level /grep call — so this per-file readFile shouldn't
      // actually be called. Implemented for completeness.
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
    // Provide glob() so pi uses it instead of spawning local `fd`.
    async glob(
      pattern: string,
      searchPath: string,
      _opts: { ignore?: string[]; limit?: number },
    ): Promise<string[]> {
      const rel = toRel(searchPath);
      const res = await client.post<{ files: string[] }>(
        "/find", { pattern, path: rel, limit: _opts?.limit ?? 1000 },
      );
      return res.files.map((f) => {
        // Convert absolute /workspace/... paths back to cwd-relative for pi's display
        if (f.startsWith(`${SANDBOX_CWD_SENTINEL}/`)) return f;
        return f;
      });
    },
  };
}

// ── Helpers ───────────────────────────────────────────────────────────────

function synthStats(res: { isFile: boolean; isDirectory: boolean; size: number; mtimeMs: number }): Stats {
  const now = new Date(res.mtimeMs || Date.now());
  // Pi only uses stat() to check isFile/isDirectory/size — the rest can be stubs.
  return {
    isFile: () => res.isFile,
    isDirectory: () => res.isDirectory,
    isBlockDevice: () => false,
    isCharacterDevice: () => false,
    isSymbolicLink: () => false,
    isFIFO: () => false,
    isSocket: () => false,
    size: res.size,
    atime: now,
    mtime: now,
    ctime: now,
    birthtime: now,
    atimeMs: res.mtimeMs,
    mtimeMs: res.mtimeMs,
    ctimeMs: res.mtimeMs,
    birthtimeMs: res.mtimeMs,
    dev: 0, ino: 0, mode: 0, nlink: 1, uid: 0, gid: 0, rdev: 0, blksize: 4096, blocks: 0,
  } as Stats;
}
