import { Type, type Static } from "@sinclair/typebox";
import type { ExtensionAPI, ToolDefinition } from "@mariozechner/pi-coding-agent";

const doneSchema = Type.Object({
  summary: Type.String({ description: "Summary of work completed" }),
});

export function registerDoneTool(pi: ExtensionAPI): void {
  const doneTool: ToolDefinition<typeof doneSchema, undefined> = {
    name: "done",
    label: "Done",
    description:
      "Signal that you have completed your work. Summarize what was accomplished " +
      "and any remaining items.",
    parameters: doneSchema,
    async execute(_toolCallId, params, _signal, _onUpdate, _ctx) {
      return {
        content: [{ type: "text" as const, text: `Done: ${params.summary}` }],
        details: undefined,
      };
    },
  };

  pi.registerTool(doneTool);
}
