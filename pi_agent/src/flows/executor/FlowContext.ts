/**
 * Flow context for managing state during flow execution.
 *
 * Handles:
 * - Variable storage and interpolation (${var} syntax)
 * - Agent summary tracking and propagation
 * - Loop iteration tracking
 * - Evaluation context for decision tool
 */

import type { TaskSpec } from "../../types.js";

// ═══════════════════════════════════════════════════════════════════════════════
// FlowContext Class
// ═══════════════════════════════════════════════════════════════════════════════

/**
 * Manages flow state during execution.
 */
export class FlowContext {
  private variables: Map<string, string | number | boolean>;
  private summaries: Map<string, string>;
  private iterationCounts: Map<string, number>;
  private task: TaskSpec;

  constructor(task: TaskSpec, initialVariables?: Record<string, string | number | boolean>) {
    this.task = task;
    this.variables = new Map();
    this.summaries = new Map();
    this.iterationCounts = new Map();

    // Set initial variables
    if (initialVariables) {
      for (const [key, value] of Object.entries(initialVariables)) {
        this.variables.set(key, value);
      }
    }

    // Set built-in variables from task
    this.variables.set("task.description", task.description);
    this.variables.set("task.language", task.language);
    if (task.targetDir) this.variables.set("task.targetDir", task.targetDir);
    if (task.testCommand) this.variables.set("task.testCommand", task.testCommand);
    if (task.buildCommand) this.variables.set("task.buildCommand", task.buildCommand);
    if (task.pushOnComplete !== undefined) {
      this.variables.set("task.pushOnComplete", String(task.pushOnComplete));
    }
    if (task.sourceRepoUrl) this.variables.set("task.sourceRepoUrl", task.sourceRepoUrl);
    if (task.sourceBranch) this.variables.set("task.sourceBranch", task.sourceBranch);
  }

  /**
   * Set a variable value.
   */
  setVariable(name: string, value: string | number | boolean): void {
    this.variables.set(name, value);
  }

  /**
   * Get a variable value.
   */
  getVariable(name: string): string | number | boolean | undefined {
    return this.variables.get(name);
  }

  /**
   * Get all variables.
   */
  getVariables(): Map<string, string | number | boolean> {
    return new Map(this.variables);
  }

  /**
   * Add an agent summary to the context.
   */
  addSummary(agentName: string, summary: string): void {
    this.summaries.set(agentName, summary);
  }

  /**
   * Get an agent summary.
   */
  getSummary(agentName: string): string | undefined {
    return this.summaries.get(agentName);
  }

  /**
   * Get all agent summaries.
   */
  getSummaries(): Map<string, string> {
    return new Map(this.summaries);
  }

  /**
   * Get all summaries formatted for inclusion in a prompt.
   */
  getSummariesFormatted(): string {
    if (this.summaries.size === 0) {
      return "(No previous agent summaries)";
    }

    const parts: string[] = [];
    for (const [agentName, summary] of this.summaries.entries()) {
      parts.push(`## ${agentName}\n${summary}`);
    }
    return parts.join("\n\n");
  }

  /**
   * Increment the iteration count for a loop.
   */
  incrementIteration(loopName: string): number {
    const current = this.iterationCounts.get(loopName) || 0;
    const next = current + 1;
    this.iterationCounts.set(loopName, next);
    this.variables.set(`iteration`, next);
    this.variables.set(`${loopName}.iteration`, next);
    return next;
  }

  /**
   * Get the current iteration count for a loop.
   */
  getIteration(loopName: string): number {
    return this.iterationCounts.get(loopName) || 0;
  }

  /**
   * Interpolate variables in a string.
   * Replaces ${varName} with variable values.
   *
   * @param str - String with ${varName} placeholders
   * @returns Interpolated string
   */
  interpolate(str: string): string {
    // Replace ${var} with variable values
    return str.replace(/\$\{([^}]+)\}/g, (match, varName) => {
      const value = this.variables.get(varName);
      if (value === undefined) {
        // Keep the placeholder if variable not found
        return match;
      }
      return String(value);
    });
  }

  /**
   * Build an evaluation context for the decision tool.
   * Includes variables and agent summaries.
   */
  toEvalContext(): Record<string, unknown> {
    const context: Record<string, unknown> = {};

    // Add variables
    for (const [key, value] of this.variables.entries()) {
      // Support dot notation keys
      const parts = key.split(".");
      let current = context;
      for (let i = 0; i < parts.length - 1; i++) {
        if (!(parts[i] in current)) {
          current[parts[i]] = {};
        }
        current = current[parts[i]] as Record<string, unknown>;
      }
      current[parts[parts.length - 1]] = value;
    }

    // Add agent summaries with @ prefix (e.g., @lastAnalyst.summary)
    const agentResults: Record<string, unknown> = {};
    for (const [agentName, summary] of this.summaries.entries()) {
      agentResults[agentName] = { summary };
    }

    return {
      ...context,
      variables: Object.fromEntries(this.variables.entries()),
      agents: agentResults,
      task: {
        description: this.task.description,
        language: this.task.language,
        targetDir: this.task.targetDir,
        testCommand: this.task.testCommand,
        buildCommand: this.task.buildCommand,
        pushOnComplete: this.task.pushOnComplete,
      },
    };
  }

  /**
   * Parse a @-prefixed reference to an agent result.
   * e.g., "@lastVerification.testsPassed" → extracts from verifier summary
   */
  getAgentReference(ref: string): unknown {
    // Remove @ prefix
    const cleanRef = ref.replace(/^@/, "");

    // Parse dot notation
    const parts = cleanRef.split(".");
    if (parts.length < 2) {
      return undefined;
    }

    const agentName = parts[0];
    const summary = this.summaries.get(agentName);
    if (!summary) {
      return undefined;
    }

    // Try to parse summary as JSON for structured access
    try {
      // Look for ## Variables section
      const varMatch = summary.match(/## Variables\n([\s\S]+?)(?=\n##|\n*$)/);
      if (varMatch) {
        const varText = varMatch[1];
        const vars: Record<string, unknown> = {};
        for (const line of varText.split("\n")) {
          const trimmed = line.trim();
          if (trimmed && trimmed.includes(":")) {
            const [key, ...valueParts] = trimmed.split(":");
            const value = valueParts.join(":").trim();
            // Try to parse as JSON, fallback to string
            try {
              vars[key.trim()] = JSON.parse(value);
            } catch {
              vars[key.trim()] = value;
            }
          }
        }

        // Access nested property
        let result: unknown = vars;
        for (let i = 1; i < parts.length; i++) {
          if (typeof result === "object" && result !== null) {
            result = (result as Record<string, unknown>)[parts[i]];
          } else {
            return undefined;
          }
        }
        return result;
      }
    } catch {
      // If parsing fails, return undefined
    }

    return undefined;
  }
}
