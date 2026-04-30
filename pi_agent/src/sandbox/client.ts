/**
 * Tiny HTTP client for the sandbox daemon.
 *
 * Talks over a unix socket (default) or HTTP host:port. Provides both
 * async (native `fetch` with undici agent) and sync (`curl --unix-socket`)
 * variants — a handful of pi tools (ls/grep/find) call their operations
 * synchronously and can't be made async without rewriting them.
 *
 * Auth: Bearer token on every request. The daemon rejects 401 otherwise.
 */
import { execFileSync } from "node:child_process";
import { Agent, fetch as undiciFetch } from "undici";

export interface SandboxEndpoint {
  socketPath?: string;
  host?: string;
  port?: number;
  authToken: string;
}

export class SandboxClient {
  private readonly agent: Agent;
  private readonly baseUrl: string;

  constructor(private readonly endpoint: SandboxEndpoint) {
    if (endpoint.socketPath) {
      this.agent = new Agent({
        connect: { socketPath: endpoint.socketPath },
      });
      this.baseUrl = "http://sandbox";
    } else if (endpoint.host) {
      this.agent = new Agent();
      this.baseUrl = `http://${endpoint.host}:${endpoint.port ?? 8000}`;
    } else {
      throw new Error("SandboxClient: socketPath or host is required");
    }
  }

  async post<T = unknown>(path: string, body: unknown, signal?: AbortSignal): Promise<T> {
    const res = await undiciFetch(`${this.baseUrl}${path}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${this.endpoint.authToken}`,
      },
      body: JSON.stringify(body),
      dispatcher: this.agent,
      signal,
    });
    if (!res.ok) {
      const text = await res.text();
      throw new Error(`sandbox ${path} ${res.status}: ${text}`);
    }
    return (await res.json()) as T;
  }

  async get<T = unknown>(path: string, signal?: AbortSignal): Promise<T> {
    const res = await undiciFetch(`${this.baseUrl}${path}`, {
      method: "GET",
      headers: { Authorization: `Bearer ${this.endpoint.authToken}` },
      dispatcher: this.agent,
      signal,
    });
    if (!res.ok) {
      const text = await res.text();
      throw new Error(`sandbox ${path} ${res.status}: ${text}`);
    }
    return (await res.json()) as T;
  }

  /** Stream an exec response. Calls onData on every stdout/stderr chunk, resolves with the exit info. */
  async execStream(
    body: { command: string; cwd?: string; timeout?: number },
    onData: (chunk: Buffer, kind: "stdout" | "stderr") => void,
    signal?: AbortSignal,
  ): Promise<{ exitCode: number; timedOut: boolean }> {
    const res = await undiciFetch(`${this.baseUrl}/exec`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${this.endpoint.authToken}`,
      },
      body: JSON.stringify(body),
      dispatcher: this.agent,
      signal,
    });
    if (!res.ok || !res.body) {
      const text = await res.text().catch(() => "");
      throw new Error(`sandbox /exec ${res.status}: ${text}`);
    }

    let exitInfo: { exitCode: number; timedOut: boolean } | null = null;
    let buf = "";
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      // SSE frames separated by blank line
      let idx: number;
      while ((idx = buf.indexOf("\n\n")) !== -1) {
        const frame = buf.slice(0, idx);
        buf = buf.slice(idx + 2);
        const lines = frame.split("\n");
        let event = "message";
        let data = "";
        for (const line of lines) {
          if (line.startsWith("event:")) event = line.slice(6).trim();
          else if (line.startsWith("data:")) data += line.slice(5).trim();
        }
        if (!data) continue;
        try {
          const payload = JSON.parse(data);
          if (event === "data") {
            onData(Buffer.from(payload.data, "utf-8"), payload.stream);
          } else if (event === "exit") {
            exitInfo = payload;
          }
        } catch {
          // ignore parse errors
        }
      }
    }
    if (!exitInfo) throw new Error("sandbox /exec ended without exit event");
    return exitInfo;
  }

  /** Synchronous POST via curl — needed for pi's sync tool ops (ls, grep, find). */
  postSync<T = unknown>(path: string, body: unknown): T {
    const args = [
      "-sS",
      "-X", "POST",
      "-H", "Content-Type: application/json",
      "-H", `Authorization: Bearer ${this.endpoint.authToken}`,
      "--data-binary", "@-",
      "--max-time", "30",
    ];
    if (this.endpoint.socketPath) {
      args.push("--unix-socket", this.endpoint.socketPath);
      args.push(`http://sandbox${path}`);
    } else {
      args.push(`${this.baseUrl}${path}`);
    }
    const out = execFileSync("curl", args, {
      input: JSON.stringify(body),
      encoding: "utf-8",
      maxBuffer: 64 * 1024 * 1024,
    });
    return JSON.parse(out) as T;
  }
}
