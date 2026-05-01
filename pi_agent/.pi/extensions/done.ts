import { Type } from "@sinclair/typebox";

export default function (pi: any) {
  pi.registerTool({
    name: "done",
    description:
      "Signal that the task is complete. Returns the result variables and stops the agent loop.",
    promptSnippet:
      'Use "done" when you have finished the task and want to return the result.',
    parameters: {
      type: "object",
      properties: {
        variables: Type.Record(Type.String(), Type.Unknown()),
        message: Type.String({ description: "Summary of what was accomplished" }),
      },
      required: ["variables", "message"],
    },
    async execute(
      _toolCallId: string,
      params: { variables: Record<string, unknown>; message: string }
    ) {
      const { variables, message } = params;
      return {
        content: [
          {
            type: "text" as const,
            text: JSON.stringify({ success: true, message, variables }),
          },
        ],
        terminate: true,
      };
    },
  });
}
