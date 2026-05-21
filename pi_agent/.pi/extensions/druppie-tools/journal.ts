/**
 * Journal hooks — fire-and-forget event posting to an HTTP ingest endpoint.
 * No-op when PI_AGENT_INGEST_URL is not set (standalone TUI mode).
 */
import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";

export function registerJournalHooks(pi: ExtensionAPI): void {
  const ingestUrl = process.env.PI_AGENT_INGEST_URL;
  if (!ingestUrl) return;

  const postEvent = (payload: Record<string, unknown>): void => {
    fetch(ingestUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }).catch(() => { /* fire-and-forget */ });
  };

  pi.on("tool_execution_start", (event) => {
    postEvent({
      type: "tool_execution_start",
      toolCallId: event.toolCallId,
      toolName: event.toolName,
      timestamp: Date.now(),
    });
  });

  pi.on("tool_execution_end", (event) => {
    postEvent({
      type: "tool_execution_end",
      toolCallId: event.toolCallId,
      toolName: event.toolName,
      isError: event.isError,
      timestamp: Date.now(),
    });
  });

  pi.on("session_shutdown", () => {
    postEvent({ type: "session_shutdown", timestamp: Date.now() });
  });
}
