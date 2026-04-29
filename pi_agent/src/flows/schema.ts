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

  // Variable requirements
  /** Variable definitions for this phase (e.g., [{name: "succeeded", type: "bool"}]) */
  variables?: PhaseVariable[];
}

/**
 * Variable definition for a phase.
 * Parsed from YAML format: `- variable_name: type`
 */
export interface PhaseVariable {
  /** Variable name */
  name: string;
  /** Variable type: "str", "int", "float", "bool", or custom */
  type: VariableType;
}

/**
 * Supported variable types for phase variables.
 */
export type VariableType = "str" | "int" | "float" | "bool";

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
 * Validate that a variable value matches its declared type.
 */
export function validateVariableType(variable: PhaseVariable, value: unknown): boolean {
  switch (variable.type) {
    case "str":
      return typeof value === "string";
    case "int":
      return typeof value === "number" && Number.isInteger(value);
    case "float":
      return typeof value === "number";
    case "bool":
      return typeof value === "boolean";
    default:
      console.warn(`Unknown variable type: ${variable.type}`);
      return true;
  }
}

/**
 * Validate that all variables required by a phase were set by the agent
 * and that their values match the declared types.
 */
export function validatePhaseVariables(
  phase: PhaseDef,
  setVariables: Record<string, unknown>,
  flowPath: string
): void {
  const errors: string[] = [];
  const prefix = `Phase "${phase.name}"`;

  if (phase.variables) {
    for (const variable of phase.variables) {
      if (!(variable.name in setVariables)) {
        errors.push(
          `${prefix}: Required variable '${variable.name}' (type: ${variable.type}) was not set by agent`
        );
        continue;
      }

      const value = setVariables[variable.name];
      if (!validateVariableType(variable, value)) {
        errors.push(
          `${prefix}: Variable '${variable.name}' expected type '${variable.type}' ` +
          `but got ${typeof value} (value: ${JSON.stringify(value)})`
        );
      }
    }
  }

  if (errors.length > 0) {
    throw new FlowValidationError(
      `Phase variable validation failed`,
      flowPath,
      errors
    );
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
        // Allow string expressions, boolean values, or numeric values
        if (typeof value !== "string" && typeof value !== "boolean" && typeof value !== "number") {
          errors.push(`${prefix}: 'set.${key}' must be a string, boolean, or number`);
        }
      }
    }
  }

  // Validate variable definitions
  if (phase.variables) {
    if (!Array.isArray(phase.variables)) {
      errors.push(`${prefix}: 'variables' must be an array`);
    } else {
      phase.variables.forEach((variable, varIndex) => {
        const varPrefix = `${prefix}.variables[${varIndex}]`;

        // Variable should be an object with name and type properties
        if (typeof variable !== "object" || variable === null) {
          errors.push(`${varPrefix}: Must be an object`);
        } else {
          // Handle object format: {name: "variable_name", type: "string"}
          if (!variable.name || typeof variable.name !== "string") {
            errors.push(`${varPrefix}: 'name' must be a string`);
          }
          if (!variable.type || typeof variable.type !== "string") {
            errors.push(`${varPrefix}: 'type' must be a string`);
          }
        }
      });
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
    const flow = parseFlowContent(content, flowPath);
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
    const rawFlow = yaml.load(content) as Record<string, unknown>;
    // Transform variable definitions from "- name: type" format to {name, type} objects
    return transformVariableDefinitions(rawFlow) as unknown as FlowDef;
  } catch (error) {
    throw new Error(`Failed to parse YAML from ${source}: ${error instanceof Error ? error.message : String(error)}`);
  }
}

/**
 * Transform variable definitions from YAML format to TypeScript objects.
 * Converts "- variable_name: type" to {name: "variable_name", type: "type"}
 */
function transformVariableDefinitions(obj: Record<string, unknown>): Record<string, unknown> {
  const result: Record<string, unknown> = { ...obj };

  // Transform phases recursively
  if (result.phases && Array.isArray(result.phases)) {
    result.phases = result.phases.map((phase) => transformPhaseVariables(phase));
  }

  return result;
}

/**
 * Transform variable definitions in a phase.
 */
function transformPhaseVariables(phase: Record<string, unknown>): Record<string, unknown> {
  const result: Record<string, unknown> = { ...phase };

  // Transform variables if present
  if (result.variables && Array.isArray(result.variables)) {
    result.variables = result.variables.map((variable) => {
      // If it's a string in format "name: type", convert to object
      if (typeof variable === "string") {
        const match = variable.match(/^(\w+):\s*(.+)$/);
        if (match) {
          return { name: match[1], type: match[2] };
        }
      }
      // If it's an object with a single key-value pair, convert to {name, type}
      if (typeof variable === "object" && variable !== null) {
        const keys = Object.keys(variable);
        // Check if it's a single-key object (YAML format: "- name: type")
        if (keys.length === 1 && typeof variable[keys[0]] === "string") {
          return { name: keys[0], type: variable[keys[0]] as string };
        }
        // If it's already in {name, type} format, return as-is
        if (variable.name && variable.type) {
          return variable;
        }
      }
      // Fallback: return as-is for validation to catch
      return variable;
    });
  }

  // Recursively transform sub-phases
  if (result.phases && Array.isArray(result.phases)) {
    result.phases = result.phases.map((subPhase) => transformPhaseVariables(subPhase));
  }

  return result;
}
