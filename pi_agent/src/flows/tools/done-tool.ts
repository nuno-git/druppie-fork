/**
 * Done tool for flow system.
 *
 * This tool allows agents to mark their work as complete and set variables
 * in the FlowState. Agents MUST use this tool to finish their work.
 *
 * The done tool:
 * - Sets variables in FlowState (required for flow continuation)
 * - Provides a completion message describing what was done
 * - Signals to the flow executor that the agent has completed its phase
 *
 * Usage:
 * - Agents must call this tool with all required variables for their flow phase
 * - The variables object should include all variables specified in the flow YAML phase
 * - The message should describe the completion outcome clearly
 */

import { Type } from "@sinclair/typebox";
import type { FlowContext } from "../executor/FlowContext.js";

// ═══════════════════════════════════════════════════════════════════════════════
// Tool Result Types
// ═══════════════════════════════════════════════════════════════════════════════

/**
 * Result from the done tool execution.
 */
export interface DoneToolResult {
  success: boolean;
  message: string;
  variablesSet: Record<string, string | number | boolean>;
}

// ═══════════════════════════════════════════════════════════════════════════════
// Done Tool Factory
// ═══════════════════════════════════════════════════════════════════════════════

/**
 * Create a done tool bound to a flow context.
 *
 * This tool is used by agents to mark their work as complete and set
 * variables in the FlowState. The flow executor will read these variables
 * to determine the next phase or action.
 *
 * @param ctx - The flow context
 * @returns A tool definition for marking work as complete
 */
export function createDoneTool(ctx: FlowContext) {
  const ParametersSchema = Type.Object({
    variables: Type.Record(
      Type.String(),
      Type.Unknown(),
      {
        description:
          "Variables to set in FlowState. MUST include all variables specified in the flow YAML phase. These variables will be available to subsequent phases via ${variable} syntax.",
      }
    ),
    message: Type.String({
      description:
        "Completion message describing what was done. THIS IS REQUIRED. Should clearly state the outcome and any important details.",
    }),
  });

  return {
    name: "done",
    label: "Mark Work as Complete",
    description:
      "Mark your work as complete. YOU MUST USE THIS TOOL TO FINISH. Sets variables in FlowState for subsequent phases and provides a completion message.",
    promptSnippet:
      "done: mark your work as complete and set variables for the next flow phase",
    parameters: ParametersSchema,
  async execute(
      toolCallId: string,
      params: { variables: Record<string, unknown>; message: string }
    ) {
      const { variables, message } = params;

      // Validate required parameters at runtime
      // Ensure 'variables' is provided
      if (!variables) {
        throw new Error(
          "Done tool requires 'variables' parameter. " +
          "Usage: done(variables={...}, message='...')"
        );
      }

      // Ensure 'message' is provided
      if (message === undefined || message === null) {
        throw new Error(
          "Done tool requires 'message' parameter. " +
          "Usage: done(variables={...}, message='...')"
        );
      }

      // Ensure 'message' is a non-empty string
      if (typeof message !== "string" || message.trim() === "") {
        throw new Error(
          "Done tool 'message' parameter must be a non-empty string. " +
          "Please provide a descriptive message about what was accomplished."
        );
      }

      try {
        // Validate and set all variables in the flow context
        const validatedVariables: Record<string, string | number | boolean> = {};
        const invalidKeys: string[] = [];

        for (const [key, value] of Object.entries(variables)) {
          // Only accept primitive types (string, number, boolean)
          if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
            validatedVariables[key] = value;
            ctx.setVariable(key, value);
          } else {
            invalidKeys.push(key);
          }
        }

        // Warn about invalid variables
        if (invalidKeys.length > 0) {
          console.warn(`[done-tool] Skipped invalid variables (non-primitive types): ${invalidKeys.join(", ")}`);
        }

        // Build the result
        const result: DoneToolResult = {
          success: true,
          message,
          variablesSet: validatedVariables,
        };

        return {
          content: [{ type: "text", text: JSON.stringify(result) }],
          details: {
            message,
            variablesSet: Object.keys(validatedVariables),
            ...(invalidKeys.length > 0 ? { warnings: [`Skipped invalid variables: ${invalidKeys.join(", ")}`] } : {}),
          },
        };
      } catch (error) {
        const errorMessage = error instanceof Error ? error.message : String(error);

        return {
          content: [{ type: "text", text: JSON.stringify({
            success: false,
            error: errorMessage,
            variables: variables ? Object.keys(variables) : [],
          }) }],
          details: {
            error: errorMessage,
          },
        };
      }
    },
  };
}

// ═══════════════════════════════════════════════════════════════════════════════
// Utility Functions
// ═══════════════════════════════════════════════════════════════════════════════

/**
 * Mark work as complete with variables and message.
 *
 * This is a convenience function that can be used programmatically
 * outside of the tool interface (e.g., in tests or custom flow logic).
 *
 * @param ctx - The flow context
 * @param variables - Variables to set in FlowState
 * @param message - Completion message
 * @returns The tool result
 */
export function markWorkComplete(
  ctx: FlowContext,
  variables: Record<string, unknown>,
  message: string
): DoneToolResult {
  try {
    // Validate and set all variables in the flow context
    const validatedVariables: Record<string, string | number | boolean> = {};
    const invalidKeys: string[] = [];

    for (const [key, value] of Object.entries(variables)) {
      // Only accept primitive types (string, number, boolean)
      if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
        validatedVariables[key] = value;
        ctx.setVariable(key, value);
      } else {
        invalidKeys.push(key);
      }
    }

    // Warn about invalid variables
    if (invalidKeys.length > 0) {
      console.warn(`[done-tool] Skipped invalid variables (non-primitive types): ${invalidKeys.join(", ")}`);
    }

    return {
      success: true,
      message,
      variablesSet: validatedVariables,
    };
  } catch (error) {
    throw new Error(
      `Failed to mark work as complete: ${error instanceof Error ? error.message : String(error)}`
    );
  }
}

// ═══════════════════════════════════════════════════════════════════════════════
// Tool Definition Export (for backward compatibility)
// ═══════════════════════════════════════════════════════════════════════════════

/**
 * Export a function to create the tool definition that can be imported by other modules.
 * This matches the pattern used by other tools in the codebase.
 */
export { createDoneTool as default };
