/**
 * Flow executor — generic engine for executing YAML flow definitions.
 *
 * Orchestrates agents according to flow YAML definitions:
 * - Sequential phase execution
 * - Loop support (while conditions)
 * - Conditional phases (if conditions)
 * - Variable interpolation and propagation
 * - Agent summary collection
 */

import { join } from "node:path";
import type { Model, Api } from "@mariozechner/pi-ai";
import {
  AuthStorage as AuthStorageType,
  ModelRegistry as ModelRegistryType,
  createAgentSession,
  SessionManager,
  SettingsManager,
} from "@mariozechner/pi-coding-agent";
import type { TaskSpec, AgentConfig } from "../../types.js";
import type { FlowDef, PhaseDef } from "../schema.js";
import { parseFlow } from "../schema.js";
import { FlowContext } from "./FlowContext.js";
import { evaluateCondition } from "../tools/decision-tool.js";
import type { Journal } from "../../journal.js";
import {
  discoverAgents,
  runSubagent,
  type AgentDefinition,
  type RunSubagentOptions,
  type SubagentResult,
} from "../../agents/runner.js";
import { createDoneTool } from "../tools/done-tool.js";

// ═══════════════════════════════════════════════════════════════════════════════
// Flow Result
// ═══════════════════════════════════════════════════════════════════════════════

/**
 * Result of executing a flow.
 */
export interface FlowResult {
  success: boolean;
  flowName: string;
  summaries: Record<string, string>;
  variables: Record<string, string | number | boolean>;
  errors: string[];
  deliverables?: {
    branch?: string;
    pr_url?: string;
    commits?: string[];
  };
}

// ═══════════════════════════════════════════════════════════════════════════════
// Flow Executor Class
// ═══════════════════════════════════════════════════════════════════════════════

/**
 * Executes flows defined in YAML.
 */
export class FlowExecutor {
  private journal?: Journal;
  private doneToolUsed: boolean = false;
  private doneToolVariables: Record<string, unknown> = {};
  private doneToolMessage: string = "";

  constructor(journal?: Journal) {
    this.journal = journal;
  }

  /**
   * Execute a flow from a YAML file.
   *
   * @param flowPath - Absolute path to the YAML flow file
   * @param task - Task specification
   * @param config - Agent configuration
   * @returns Flow execution result
   */
  async execute(
    flowPath: string,
    task: TaskSpec,
    config: AgentConfig
  ): Promise<FlowResult> {
    // Parse and validate flow
    const flow = parseFlow(flowPath);
    this.journal?.write("flow_start", { flow: flow.name, path: flowPath });

    // Initialize flow context
    const ctx = new FlowContext(task, flow.variables);

    // Discover available agents
    const extraAgentDirs: string[] = [];
    if (config.projectRoot) {
      extraAgentDirs.push(join(config.projectRoot, ".pi", "agents"));
    }
    const agents = discoverAgents(config.workDir, extraAgentDirs);
    const agentMap = new Map<string, AgentDefinition>();
    for (const agent of agents) {
      agentMap.set(agent.name, agent);
    }

    // Create auth storage and model registry (like tdd.ts does)
    const authStorage = AuthStorageType.create();
    if (config.apiKey) authStorage.setRuntimeApiKey("anthropic", config.apiKey);
    const modelRegistry = ModelRegistryType.create(authStorage);

    // Register GLM/Z.AI key if provided
    if (config.glmApiKey) {
      authStorage.setRuntimeApiKey("zai", config.glmApiKey);
    }

    // Resolve default model
    const modelSpec = config.model ?? "zai/glm-5.1";
    let defaultModel: Model<Api> | undefined;
    if (modelSpec.includes("/")) {
      const [prov, id] = modelSpec.split("/", 2);
      defaultModel = modelRegistry.find(prov, id);
    } else {
      defaultModel = modelRegistry.getAll().find((m) => m.id === modelSpec);
    }
    if (!defaultModel) throw new Error(`Default model not found: ${modelSpec}`);

    // Prepare base options for subagents
    const baseOpts = this.prepareBaseOptions(config, ctx, authStorage, modelRegistry, defaultModel);

    const errors: string[] = [];

    try {
      // Execute phases
      for (const phase of flow.phases) {
        await this.executePhase(phase, ctx, agentMap, baseOpts);
      }

      // Build result
      const summaries = Object.fromEntries(ctx.getSummaries());
      const variables = Object.fromEntries(ctx.getVariables());

      this.journal?.write("flow_end", { success: true, flow: flow.name });

      return {
        success: true,
        flowName: flow.name,
        summaries,
        variables,
        errors,
      };
    } catch (error) {
      const errorMsg = error instanceof Error ? error.message : String(error);
      errors.push(errorMsg);

      this.journal?.write("flow_end", { success: false, flow: flow.name, error: errorMsg });
      this.journal?.error(errorMsg);

      return {
        success: false,
        flowName: flow.name,
        summaries: Object.fromEntries(ctx.getSummaries()),
        variables: Object.fromEntries(ctx.getVariables()),
        errors,
      };
    }
  }

  /**
   * Execute a single phase (which may be a simple agent phase, a loop, or a conditional).
   */
  private async executePhase(
    phase: PhaseDef,
    ctx: FlowContext,
    agentMap: Map<string, AgentDefinition>,
    baseOpts: RunSubagentOptions
  ): Promise<void> {
    // Record phase start
    this.journal?.phaseStart(phase.name, ctx.getIteration(phase.name));

    // Check if this is a loop or conditional phase
    if (phase.phases) {
      // This is a loop or conditional
      if (phase.while) {
        await this.executeWhileLoop(phase, ctx, agentMap, baseOpts);
      } else if (phase.if) {
        await this.executeConditional(phase, ctx, agentMap, baseOpts);
      } else {
        throw new Error(`Phase "${phase.name}" has sub-phases but no while or if condition`);
      }
    } else if (phase.agent) {
      // Simple agent phase
      await this.executeAgentPhase(phase, ctx, agentMap, baseOpts);
    } else {
      throw new Error(`Phase "${phase.name}" has no agent or sub-phases`);
    }

    // Set variables after phase execution
    if (phase.set) {
      for (const [key, expression] of Object.entries(phase.set)) {
        const interpolated = ctx.interpolate(expression);
        // Try to evaluate as an expression, fallback to string
        try {
          const result = await evaluateCondition(interpolated, ctx);
          ctx.setVariable(key, result);
        } catch {
          // Not a condition, just use the string value
          ctx.setVariable(key, interpolated);
        }
      }
    }

    // Record phase end
    this.journal?.phaseEnd();
  }

  /**
   * Execute a simple agent phase.
   */
  private async executeAgentPhase(
    phase: PhaseDef,
    ctx: FlowContext,
    agentMap: Map<string, AgentDefinition>,
    baseOpts: RunSubagentOptions
  ): Promise<void> {
    const agentName = phase.agent!;
    const agent = agentMap.get(agentName);

    if (!agent) {
      throw new Error(`Agent "${agentName}" not found. Available: ${Array.from(agentMap.keys()).join(", ")}`);
    }

    // Reset done tool tracking for this phase
    this.doneToolUsed = false;
    this.doneToolVariables = {};
    this.doneToolMessage = "";

    // Build prompt
    const prompt = this.buildPrompt(phase, ctx);

    // Run agent
    this.journal?.write("agent_start", { agent: agentName, phase: phase.name });
    const result = await runSubagent(agent, prompt, baseOpts);
    this.journal?.write("agent_end", { agent: agentName, phase: phase.name, success: result.success });

    // Enforce done tool usage if phase has required variables
    if (phase.variables && phase.variables.length > 0) {
      this.enforceDoneTool(phase, agentName, result.output);
    }

    // Store summary
    if (result.summary) {
      ctx.addSummary(agentName, result.summary);
    }

    // Store variables from done tool
    if (this.doneToolUsed) {
      for (const [key, value] of Object.entries(this.doneToolVariables)) {
        // Ensure value is of the correct type
        if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
          ctx.setVariable(key, value);
        } else {
          // Convert to string for complex types
          ctx.setVariable(key, String(value));
        }
      }
    } else if (result.variables) {
      // Fallback to legacy variable extraction if no done tool
      for (const [key, value] of result.variables.entries()) {
        ctx.setVariable(key, value);
      }
    }

    // Check for errors
    if (!result.success) {
      throw new Error(`Agent "${agentName}" failed: ${result.error || "unknown error"}`);
    }
  }

  /**
   * Execute a while loop.
   */
  private async executeWhileLoop(
    phase: PhaseDef,
    ctx: FlowContext,
    agentMap: Map<string, AgentDefinition>,
    baseOpts: RunSubagentOptions
  ): Promise<void> {
    const maxIterations = 100; // Safety limit
    let iteration = 0;

    while (iteration < maxIterations) {
      // Check loop condition
      const condition = ctx.interpolate(phase.while!);
      const shouldContinue = await evaluateCondition(condition, ctx);

      if (!shouldContinue) {
        break;
      }

      // Increment iteration
      iteration++;
      ctx.incrementIteration(phase.name);

      // Execute sub-phases
      for (const subPhase of phase.phases!) {
        await this.executePhase(subPhase, ctx, agentMap, baseOpts);
      }
    }

    if (iteration >= maxIterations) {
      throw new Error(`Phase "${phase.name}" exceeded maximum iterations (${maxIterations})`);
    }
  }

  /**
   * Execute a conditional phase.
   */
  private async executeConditional(
    phase: PhaseDef,
    ctx: FlowContext,
    agentMap: Map<string, AgentDefinition>,
    baseOpts: RunSubagentOptions
  ): Promise<void> {
    // Check condition
    const condition = ctx.interpolate(phase.if!);
    const shouldExecute = await evaluateCondition(condition, ctx);

    if (!shouldExecute) {
      // Skip this phase
      return;
    }

    // Execute sub-phases
    for (const subPhase of phase.phases!) {
      await this.executePhase(subPhase, ctx, agentMap, baseOpts);
    }
  }

  /**
   * Build a prompt for an agent phase.
   */
  private buildPrompt(phase: PhaseDef, ctx: FlowContext): string {
    const parts: string[] = [];

    // Add description if available
    if (phase.description) {
      parts.push(`## Task\n${phase.description}`);
    }

    // Add previous summaries if requested
    if (phase.inputs?.previousSummaries) {
      const summaries = ctx.getSummariesFormatted();
      parts.push(`\n## Previous Agent Summaries\n${summaries}`);
    }

    return parts.join("\n");
  }

  /**
   * Enforce done tool usage for phases with required variables.
   *
   * Checks if the done tool was used and validates that all required variables were set.
   * Raises descriptive errors if enforcement fails.
   */
  private enforceDoneTool(phase: PhaseDef, agentName: string, agentOutput: string): void {
    // Extract done tool usage from agent output
    this.extractDoneToolUsage(agentOutput);

    // Check if done tool was used
    if (!this.doneToolUsed) {
      throw new Error(
        `Agent "${agentName}" in phase "${phase.name}" did not use the done tool. ` +
        `This phase requires the following variables to be set: ${phase.variables?.map(v => v.name).join(", ") || "none"}. ` +
        `You MUST use the done tool at the end of your work with all required variables.`
      );
    }

    // Validate that all required variables were set
    const missingVariables: string[] = [];
    if (phase.variables) {
      for (const variable of phase.variables) {
        if (!(variable.name in this.doneToolVariables)) {
          missingVariables.push(variable.name);
        }
      }
    }

    if (missingVariables.length > 0) {
      throw new Error(
        `Agent "${agentName}" in phase "${phase.name}" did not set all required variables via done tool. ` +
        `Missing variables: ${missingVariables.join(", ")}. ` +
        `Required variables: ${phase.variables?.map(v => v.name).join(", ") || "none"}. ` +
        `Please use the done tool with all required variables.`
      );
    }

    // Log successful done tool usage
    this.journal?.write("done_tool_used", {
      agent: agentName,
      phase: phase.name,
      message: this.doneToolMessage,
      variables: Object.keys(this.doneToolVariables),
    });
  }

  /**
   * Extract done tool usage from agent output.
   *
   * Looks for done tool calls in the agent's output and extracts the variables and message.
   */
  private extractDoneToolUsage(output: string): void {
    // Look for done tool usage in various formats

    // Format 1: Function call like done(variables={...}, message="...")
    // This handles the equals sign format used in agent examples
    const equalsFormatMatch = output.match(/done\s*\(\s*variables\s*=\s*\{[\s\S]*?\}[\s\S]*?\)/);
    if (equalsFormatMatch) {
      const callStr = equalsFormatMatch[0];

      // Extract variables object
      const varsMatch = callStr.match(/variables\s*=\s*(\{[\s\S]*?\})/);
      // Extract message
      const msgMatch = callStr.match(/message\s*=\s*"([^"]*)"/);

      if (varsMatch || msgMatch) {
        this.doneToolUsed = true;
        this.doneToolMessage = msgMatch ? msgMatch[1] : "";

        if (varsMatch) {
          try {
            this.doneToolVariables = JSON.parse(varsMatch[1]);
          } catch {
            this.doneToolVariables = this.extractVariablesFromText(varsMatch[1]);
          }
        }
        return;
      }
    }

    // Format 2: Function call like done({variables: {...}, message: "..."})
    const colonFormatMatch = output.match(/done\s*\(\s*\{[\s\S]*?\}/);
    if (colonFormatMatch) {
      const callStr = colonFormatMatch[0];

      // Extract variables object
      const varsMatch = callStr.match(/variables\s*:\s*(\{[\s\S]*?\})/);
      // Extract message
      const msgMatch = callStr.match(/message\s*:\s*"([^"]*)"/);

      if (varsMatch || msgMatch) {
        this.doneToolUsed = true;
        this.doneToolMessage = msgMatch ? msgMatch[1] : "";

        if (varsMatch) {
          try {
            this.doneToolVariables = JSON.parse(varsMatch[1]);
          } catch {
            this.doneToolVariables = this.extractVariablesFromText(varsMatch[1]);
          }
        }
        return;
      }
    }

    // Format 3: JSON-style tool call
    const jsonToolMatch = output.match(/"name"\s*:\s*"done"[\s\S]*?"parameters"\s*:\s*\{[\s\S]*?"variables"\s*:\s*(\{[^}]*\})[\s\S]*?"message"\s*:\s*"([^"]*)"/);
    if (jsonToolMatch) {
      this.doneToolUsed = true;
      this.doneToolMessage = jsonToolMatch[2];
      try {
        this.doneToolVariables = JSON.parse(jsonToolMatch[1]);
      } catch {
        this.doneToolVariables = this.extractVariablesFromText(jsonToolMatch[1]);
      }
      return;
    }

    // Format 4: Simple done(variables, message) format
    const simpleMatch = output.match(/done\s*\(\s*(\{[^}]*\})\s*,\s*"([^"]*)"\s*\)/);
    if (simpleMatch) {
      this.doneToolUsed = true;
      this.doneToolMessage = simpleMatch[2];
      try {
        this.doneToolVariables = JSON.parse(simpleMatch[1]);
      } catch {
        this.doneToolVariables = this.extractVariablesFromText(simpleMatch[1]);
      }
      return;
    }

    // Format 5: Look for explicit done tool usage in tool calls
    const toolCallMatch = output.match(/tool_call\s*:\s*\{[\s\S]*?"name"\s*:\s*"done"[\s\S]*?\}/);
    if (toolCallMatch) {
      this.doneToolUsed = true;
      // Extract variables from the tool call
      const variablesMatch = toolCallMatch[0].match(/"variables"\s*:\s*(\{[^}]*\})/);
      const messageMatch = toolCallMatch[0].match(/"message"\s*:\s*"([^"]*)"/);
      if (variablesMatch) {
        try {
          this.doneToolVariables = JSON.parse(variablesMatch[1]);
        } catch {
          this.doneToolVariables = this.extractVariablesFromText(variablesMatch[1]);
        }
      }
      if (messageMatch) {
        this.doneToolMessage = messageMatch[1];
      }
      return;
    }

    // No done tool usage found
    this.doneToolUsed = false;
  }

  /**
   * Extract variables from text when JSON parsing fails.
   */
  private extractVariablesFromText(text: string): Record<string, unknown> {
    const variables: Record<string, unknown> = {};
    const lines = text.split("\n");

    for (const line of lines) {
      const trimmed = line.trim();
      if (trimmed.includes(":")) {
        const [key, ...valueParts] = trimmed.split(":");
        const value = valueParts.join(":").trim();
        if (key) {
          // Try to parse as JSON, otherwise keep as string
          try {
            variables[key.trim()] = JSON.parse(value);
          } catch {
            variables[key.trim()] = value;
          }
        }
      }
    }

    return variables;
  }

  /**
   * Prepare base options for subagent execution.
   */
  private prepareBaseOptions(
    config: AgentConfig,
    ctx: FlowContext,
    authStorage: AuthStorageType,
    modelRegistry: ModelRegistryType,
    defaultModel: Model<Api>
  ): RunSubagentOptions {
    // Create done tool for this execution context
    const doneTool = createDoneTool(ctx);

    return {
      cwd: config.workDir,
      authStorage,
      modelRegistry,
      defaultModel,
      maxTurns: config.maxTurnsPerAgent,
      onOutput: (delta) => process.stdout.write(delta),
      journal: this.journal,
      extraCustomTools: [doneTool],
    };
  }
}
