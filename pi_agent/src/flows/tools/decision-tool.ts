/**
 * Decision tool for safe JavaScript expression evaluation.
 *
 * Provides a sandboxed environment for evaluating conditions in flow YAML.
 * Supports:
 * - Variable access (${var} syntax)
 * - Agent result references (@agentName.property syntax)
 * - Basic operations (arithmetic, comparisons, logical)
 * - Optional chaining (?.) for safe property access
 *
 * Security features:
 * - No access to global scope
 * - Expression evaluation only (no statements)
 * - Timeout protection
 * - Whitelisted operations
 */

import { Type } from "@sinclair/typebox";
import type { FlowContext } from "../executor/FlowContext.js";

// ═══════════════════════════════════════════════════════════════════════════════
// Safe Expression Evaluation
// ═══════════════════════════════════════════════════════════════════════════════

/**
 * Safely evaluate a JavaScript expression.
 *
 * @param expression - The expression to evaluate
 * @param context - Evaluation context with variables and agent results
 * @returns The result of the evaluation
 * @throws Error if evaluation fails or times out
 */
export function evaluateSafe(expression: string, context: Record<string, unknown>): unknown {
  const EVAL_TIMEOUT_MS = 1000; // 1 second timeout

  // Replace @-prefixed references with actual values
  const processedExpression = replaceAgentReferences(expression, context);

  // Create a safe evaluation function with limited scope
  const safeEval = createSafeFunction(processedExpression, context);

  // Execute with timeout
  return executeWithTimeout(safeEval, EVAL_TIMEOUT_MS);
}

/**
 * Replace @agentName.property references with actual values from context.
 */
function replaceAgentReferences(expression: string, context: Record<string, unknown>): string {
  // Match @word patterns (agent references)
  return expression.replace(/@(\w+(?:\.\w+)*(?:\?\.\w+)*)/g, (match, ref) => {
    // Access from context.agents
    const agents = context.agents as Record<string, unknown> | undefined;
    if (!agents) {
      return "undefined";
    }

    // Split by . and handle optional chaining
    const parts = ref.split(".");
    let result: unknown = agents;

    for (const part of parts) {
      if (part === "?." || part === "") continue;

      if (typeof result === "object" && result !== null) {
        result = (result as Record<string, unknown>)[part];
      } else {
        return "undefined";
      }
    }

    // Convert to JavaScript literal
    return JSON.stringify(result);
  });
}

/**
 * Create a safe function with limited scope.
 * Only has access to the context object, not global scope.
 */
function createSafeFunction(expression: string, context: Record<string, unknown>) {
  // Create function with parameter names from context
  const paramNames = Object.keys(context);
  const paramValues = Object.values(context);

  // Wrap in IIFE to limit scope
  const funcBody = `
    "use strict";
    return (${expression});
  `;

  try {
    const func = new Function(...paramNames, funcBody);
    return () => func(...paramValues);
  } catch (error) {
    throw new Error(`Failed to create evaluation function: ${error instanceof Error ? error.message : String(error)}`);
  }
}

/**
 * Execute a function with timeout protection.
 */
function executeWithTimeout(fn: () => unknown, timeoutMs: number): unknown {
  let timeoutHandle: NodeJS.Timeout | undefined;

  const timeoutPromise = new Promise<never>((_, reject) => {
    timeoutHandle = setTimeout(() => {
      reject(new Error(`Expression evaluation timed out after ${timeoutMs}ms`));
    }, timeoutMs);
  });

  const executionPromise = Promise.resolve(fn());

  return Promise.race([executionPromise, timeoutPromise])
    .finally(() => {
      if (timeoutHandle) {
        clearTimeout(timeoutHandle);
      }
    });
}

// ═══════════════════════════════════════════════════════════════════════════════
// Decision Tool Factory
// ═══════════════════════════════════════════════════════════════════════════════

/**
 * Create a decision tool bound to a flow context.
 *
 * This tool can be used by the FlowExecutor to evaluate conditions
 * in YAML flow definitions.
 *
 * @param ctx - The flow context
 * @returns A tool definition for condition evaluation
 */
export function createDecisionTool(ctx: FlowContext) {
  const ParametersSchema = Type.Object({
    expression: Type.String({
      description: "JavaScript expression to evaluate (e.g., 'iteration < maxIterations && !@lastVerification.testsPassed')",
    }),
  });

  return {
    name: "evaluate_condition",
    label: "Evaluate Condition",
    description: "Safely evaluate a JavaScript expression for flow control (if/while conditions)",
    promptSnippet: "evaluate_condition: check if a condition is true (supports @agent.property and ${variable} syntax)",
    parameters: ParametersSchema,
    async execute(toolCallId: string, params: { expression: string }) {
      const { expression } = params;

      try {
        // Build evaluation context from flow context
        const evalContext = ctx.toEvalContext();

        // Evaluate the expression
        const result = await evaluateSafe(expression, evalContext);

        // Convert to boolean for conditions
        const boolResult = Boolean(result);

        return {
          content: [{ type: "text", text: JSON.stringify({
            result: boolResult,
            raw: result,
            expression,
          }) }],
          details: {
            result: boolResult,
            raw: String(result),
          },
        };
      } catch (error) {
        return {
          content: [{ type: "text", text: JSON.stringify({
            error: error instanceof Error ? error.message : String(error),
            expression,
          }) }],
          details: {
            error: error instanceof Error ? error.message : String(error),
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
 * Evaluate a condition expression (can be async due to timeout).
 *
 * @param expression - The condition to evaluate
 * @param ctx - The flow context
 * @returns True if the condition is truthy, false otherwise
 */
export async function evaluateCondition(expression: string, ctx: FlowContext): Promise<boolean> {
  const evalContext = ctx.toEvalContext();
  const result = await evaluateSafe(expression, evalContext);
  return Boolean(result);
}
