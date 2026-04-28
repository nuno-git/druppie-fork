/**
 * Flow schema definitions and YAML parser for pi_agent.
 *
 * Defines the structure of YAML flow files that orchestrate agents.
 * Supports variables, phases, loops, conditionals, and outputs.
 */

import { readFileSync } from "node:fs";
import * as yaml from "js-yaml";
import type { TaskSpec } from "../types.js";

// ═══════════════════════════════════════════════════════════════════════════════
// Type Definitions
// ═══════════════════════════════════════════════════════════════════════════════

/**
 * A flow definition from a YAML file.
 */
export interface FlowDef {
  /** Flow identifier (e.g., "tdd", "explore") */
  name: string;
  /** Human-readable description */
  description: string;
  /** Initial variables for the flow */
  variables?: Record<string, string | number | boolean>;
  /** Phases to execute sequentially */
  phases: PhaseDef[];
  /** Output configuration */
  output?: OutputDef;
}

/**
 * A single phase in the flow.
 * Can be a simple agent phase, a loop, or a conditional.
 */
export interface PhaseDef {
  /** Phase identifier (used for logging and variable scoping) */
  name: string;
  /** Human-readable description */
  description?: string;

  // Agent execution
  /** Agent to run (mutually exclusive with phases) */
  agent?: string;
  /** Whether this is a built-in system agent */
  builtIn?: boolean;
  /** Configuration for built-in agents */
  config?: Record<string, unknown>;
  /** Input configuration for the agent */
  inputs?: PhaseInputs;

  // Control flow
  /** Sub-phases (for loops/conditionals) */
  phases?: PhaseDef[];
  /** Loop condition (while: "condition") */
  while?: string;
  /** Conditional condition (if: "condition") */
  if?: string;
  /** Variables to set after phase execution */
  set?: Record<string, string>;
}

/**
 * Input configuration for a phase.
 */
export interface PhaseInputs {
  /** Include all previous agent summaries in the prompt */
  previousSummaries?: boolean;
}

/**
 * Output configuration for the flow.
 */
export interface OutputDef {
  /** Output format: "summaries" returns all agent summaries */
  format: "summaries" | "deliverables" | "both";
  /** Which agent summaries to include (if format is "summaries") */
  include?: string[];
}

// ═══════════════════════════════════════════════════════════════════════════════
// Validation
// ═══════════════════════════════════════════════════════════════════════════════

/**
 * Error thrown when flow validation fails.
 */
export class FlowValidationError extends Error {
  constructor(
    message: string,
    public readonly flowPath: string,
    public readonly errors: string[]
  ) {
    super(`Flow validation failed for ${flowPath}: ${message}`);
    this.name = "FlowValidationError";
  }
}

/**
 * Validate a flow definition.
 * Throws FlowValidationError if invalid.
 */
export function validateFlow(flow: FlowDef, flowPath: string): void {
  const errors: string[] = [];

  // Validate name
  if (!flow.name || typeof flow.name !== "string") {
    errors.push("Flow must have a string 'name' field");
  }

  // Validate description
  if (!flow.description || typeof flow.description !== "string") {
    errors.push("Flow must have a string 'description' field");
  }

  // Validate phases
  if (!flow.phases || !Array.isArray(flow.phases) || flow.phases.length === 0) {
    errors.push("Flow must have a non-empty 'phases' array");
  } else {
    flow.phases.forEach((phase, index) => {
      validatePhase(phase, flowPath, index, errors);
    });
  }

  // Validate output
  if (flow.output) {
    validateOutput(flow.output, flowPath, errors);
  }

  if (errors.length > 0) {
    throw new FlowValidationError(
      `Found ${errors.length} validation error(s)`,
      flowPath,
      errors
    );
  }
}

/**
 * Validate a single phase.
 */
function validatePhase(
  phase: PhaseDef,
  flowPath: string,
  index: number,
  errors: string[]
): void {
  const prefix = `Phase ${index} (${phase.name || "unnamed"})`;

  // Must have either agent or phases (for loops/conditionals)
  if (!phase.agent && !phase.phases) {
    errors.push(`${prefix}: Must have either 'agent' or 'phases'`);
  }

  // Cannot have both agent and phases
  if (phase.agent && phase.phases) {
    errors.push(`${prefix}: Cannot have both 'agent' and 'phases'`);
  }

  // If agent, must have name
  if (phase.agent && typeof phase.agent !== "string") {
    errors.push(`${prefix}: 'agent' must be a string`);
  }

  // If loop or conditional, must have condition
  if (phase.phases && !phase.while && !phase.if) {
    errors.push(`${prefix}: 'phases' requires 'while' or 'if' condition`);
  }

  // Validate sub-phases recursively
  if (phase.phases) {
    phase.phases.forEach((subPhase, subIndex) => {
      validatePhase(subPhase, flowPath, subIndex, errors);
    });
  }

  // Validate variables to set
  if (phase.set) {
    if (typeof phase.set !== "object" || Array.isArray(phase.set)) {
      errors.push(`${prefix}: 'set' must be an object`);
    } else {
      for (const [key, value] of Object.entries(phase.set)) {
        if (typeof value !== "string") {
          errors.push(`${prefix}: 'set.${key}' must be a string (expression)`);
        }
      }
    }
  }
}

/**
 * Validate output configuration.
 */
function validateOutput(output: OutputDef, flowPath: string, errors: string[]): void {
  if (!["summaries", "deliverables", "both"].includes(output.format)) {
    errors.push(`Output format must be 'summaries', 'deliverables', or 'both'`);
  }

  if (output.format === "summaries" && !output.include) {
    errors.push(`Output format 'summaries' requires 'include' array`);
  }

  if (output.include && !Array.isArray(output.include)) {
    errors.push(`Output 'include' must be an array`);
  }
}

// ═══════════════════════════════════════════════════════════════════════════════
// YAML Parsing
// ═══════════════════════════════════════════════════════════════════════════════

/**
 * Parse a flow YAML file.
 *
 * @param flowPath - Absolute path to the YAML file
 * @returns Parsed and validated flow definition
 * @throws FlowValidationError if the file is invalid
 */
export function parseFlow(flowPath: string): FlowDef {
  try {
    const content = readFileSync(flowPath, "utf-8");
    const flow = yaml.load(content) as FlowDef;
    validateFlow(flow, flowPath);
    return flow;
  } catch (error) {
    if (error instanceof FlowValidationError) {
      throw error;
    }
    throw new Error(`Failed to read flow file ${flowPath}: ${error instanceof Error ? error.message : String(error)}`);
  }
}

/**
 * Parse YAML content as a flow definition.
 * Does not validate - use validateFlow() after parsing.
 *
 * @param content - YAML content
 * @param source - Source path for error messages
 * @returns Parsed flow definition
 */
export function parseFlowContent(content: string, source: string): FlowDef {
  try {
    return yaml.load(content) as FlowDef;
  } catch (error) {
    throw new Error(`Failed to parse YAML from ${source}: ${error instanceof Error ? error.message : String(error)}`);
  }
}
