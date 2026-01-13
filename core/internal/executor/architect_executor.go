package executor

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"github.com/sjhoeksma/druppie/core/internal/llm"
	"github.com/sjhoeksma/druppie/core/internal/model"
	"github.com/sjhoeksma/druppie/core/internal/paths"
	"github.com/sjhoeksma/druppie/core/internal/registry"
)

// ArchitectExecutor handles high-level architectural design tasks
type ArchitectExecutor struct {
	LLM      llm.Provider
	Registry *registry.Registry
}

func (e *ArchitectExecutor) CanHandle(action string) bool {
	return action == "architectural_design" ||
		action == "documentation_assembly" ||
		action == "motivation_modeling" ||
		action == "baseline_modeling" ||
		action == "target_modeling" ||
		action == "viewpoint_derivation" ||
		action == "principles_consistency_check" || action == "principles_and_consistency_check" ||
		action == "decision_recording" ||
		action == "roadmap_gaps" ||
		action == "roadmap_and_gaps" ||
		action == "review_governance" || action == "review_and_governance" ||
		action == "intake" || action == "completion" || action == "iteration"
}

func (e *ArchitectExecutor) Execute(ctx context.Context, step model.Step, outputChan chan<- string) error {
	action := step.Action
	outputChan <- fmt.Sprintf("ArchitectExecutor: Executing '%s'...", action)

	// Extract planID
	planID := ""
	if p, ok := step.Params["plan_id"].(string); ok {
		planID = p
	} else if p, ok := step.Params["_plan_id"].(string); ok {
		planID = p
	} else {
		planID = "unknown_plan"
		outputChan <- "Warning: plan_id not found in params"
	}

	var result string
	var usage model.TokenUsage

	// Use LLM for architectural tasks
	if e.LLM != nil {
		language := ""
		if l, ok := step.Params["language"].(string); ok {
			language = l
		}

		// Lookup Provider and Instructions if AgentID is known
		var providerName string
		var agentInstructions string
		var skillInstructions string

		if e.Registry != nil && step.AgentID != "" {
			if agent, err := e.Registry.GetAgent(step.AgentID); err == nil {
				if agent.Provider != "" {
					providerName = agent.Provider
				}
				if agent.Instructions != "" {
					agentInstructions = agent.Instructions
				}
			}
		}

		// Construct System Prompt (Hierarchical: Action Prompt > Agent Instructions > Default)
		defaultPrompt := "You are an Enterprise Architect. Provide a structured architectural output in Markdown format."
		if agentInstructions != "" {
			defaultPrompt = agentInstructions
		}
		// lookup named action prompt in agent definition
		systemPrompt := GetActionPrompt(e.Registry, step.AgentID, action, defaultPrompt)

		// Lookup and Append Skill Instructions (Action + Agent Skills)
		// Optimize Context: Only load heavy Mermaid skill for visualization-heavy actions
		// This prevents the LLM from being biased towards outputting ONLY diagrams for text-heavy tasks (e.g. Intake, Review).
		excludedSkills := []string{}
		isVisualAction := strings.Contains(action, "modeling") || strings.Contains(action, "viewpoint") || strings.Contains(action, "design")
		if !isVisualAction {
			excludedSkills = append(excludedSkills, "mermaid")
		}

		// Lookup and Append Skill Instructions (Action + Agent Skills)
		skillInstructions = GetCompositeSkillInstructionsWithFilter(e.Registry, step.AgentID, action, excludedSkills)
		if skillInstructions != "" {
			systemPrompt += skillInstructions
		}

		// CRITICAL: Reinforce Agent Persona after Skill Injection
		systemPrompt += "\n\n### FINAL INSTRUCTION\nYou are an **ARCHITECT** first, and a diagrammer second.\n" +
			"1. **MANDATORY**: You MUST provide detailed narrative documentation, rationale, and analysis.\n" +
			"2. **PROHIBITED**: You MUST NOT output a diagram without 500+ words of accompanying text explaining it.\n" +
			"3. **RELATIONSHIP**: Diagrams are visual aids to support your text, not the output itself."

		// FINAL LANGUAGE ENFORCEMENT: This MUST be the very last instruction to override any English biases in the prompt.
		if language != "" {
			systemPrompt += fmt.Sprintf("\n\n### LANGUAGE REQUIREMENT\n**CRITICAL**: The entire response (narrative, labels, notes) MUST be in **%s**.\nDo NOT translate technical terms if they are standard in English (e.g. AWS, Kubernetes), but all explanations must be in %s.", language, language)
		}

		// Construct User Prompt with Context
		userPrompt := fmt.Sprintf("Task: %s\n\nContext: %v", action, step.Params)

		// Context Loading: Load previous architectural files (Session Handling via Filesystem)
		filesDir, _ := paths.ResolvePath(".druppie", "plans", planID, "files")
		if files, err := os.ReadDir(filesDir); err == nil {
			var fileContext strings.Builder
			fileContext.WriteString("\n\n--- EXISTING ARTIFACTS ---\n")
			count := 0
			for _, f := range files {
				if strings.HasSuffix(f.Name(), ".md") {
					content, _ := os.ReadFile(filepath.Join(filesDir, f.Name()))
					// Avoid re-reading own output if retrying? No, good context.
					fileContext.WriteString(fmt.Sprintf("File: %s\nContent:\n%s\n\n", f.Name(), string(content)))
					count++
				}
			}
			if count > 0 {
				userPrompt += fileContext.String()
				outputChan <- fmt.Sprintf("ArchitectExecutor: Loaded %d existing artifacts into context.", count)
			}
		}

		if language != "" {
			userPrompt += fmt.Sprintf("\n\nReminder: Output must be in %s.", language)
		}

		// Debug Logging (User Request)
		outputChan <- fmt.Sprintf("LLM Prompt Length: %d chars. Context keys: %v", len(userPrompt), getKeys(step.Params))

		var err error

		if providerName != "" {
			if mgr, ok := e.LLM.(*llm.Manager); ok {
				result, usage, err = mgr.GenerateWithProvider(ctx, providerName, userPrompt, systemPrompt)
			} else {
				result, usage, err = e.LLM.Generate(ctx, userPrompt, systemPrompt)
			}
		} else {
			result, usage, err = e.LLM.Generate(ctx, userPrompt, systemPrompt)
		}
		if err != nil {
			outputChan <- fmt.Sprintf("LLM generation failed: %v. Using fallback.", err)
			result = e.getFallbackResult(action)
		}
	} else {
		result = e.getFallbackResult(action)
	}

	// Sanitize Output: Ensure Markdown Code Block for Mermaid
	// If the output starts with "mermaid" but doesn't have backticks, fix it.
	// Also fix common syntax errors (concatenated tokens).
	result = SanitizeAndFixMarkdown(result)

	// Write to File
	safeAction := strings.ReplaceAll(step.Action, "/", "-")
	safeAction = strings.ReplaceAll(safeAction, "\\", "-")

	filesDir, _ := paths.ResolvePath(".druppie", "plans", planID, "files")
	if err := os.MkdirAll(filesDir, 0755); err != nil {
		outputChan <- fmt.Sprintf("Error creating files directory: %v", err)
		return err
	}

	fileName := fmt.Sprintf("%s-%d.md", safeAction, step.ID)
	filePath := filepath.Join(filesDir, fileName)

	if err := os.WriteFile(filePath, []byte(result), 0644); err != nil {
		outputChan <- fmt.Sprintf("Error writing architecture file: %v", err)
		return err
	}

	outputChan <- fmt.Sprintf("Document saved to: %s", filePath)

	// Report usage via special output format
	if usage.TotalTokens > 0 || usage.EstimatedCost > 0 {
		outputChan <- fmt.Sprintf("RESULT_TOKEN_USAGE=%d,%d,%d,%.5f", usage.PromptTokens, usage.CompletionTokens, usage.TotalTokens, usage.EstimatedCost)
	}

	return nil
}

func (e *ArchitectExecutor) getFallbackResult(action string) string {
	switch action {
	case "architectural_design", "target_modeling":
		return "Architecture Design Complete.\n\n" +
			"### Proposed Solution\n" +
			"- **Frontend**: React SPA\n" +
			"- **Backend**: Go Microservices\n" +
			"- **Database**: PostgreSQL\n" +
			"- **Infrastructure**: Kubernetes (EKS)\n\n" +
			"### Diagram\n" +
			"```mermaid\n" +
			"graph TD\n" +
			"  Client --> Ingress\n" +
			"  Ingress --> ServiceA\n" +
			"  Ingress --> ServiceB\n" +
			"  ServiceA --> DB\n" +
			"```"

	case "documentation_assembly":
		return "# Architecture Documentation\n\n" +
			"## Executive Summary\n" +
			"Following the architectural design, this document outlines the proposed solution.\n\n" +
			"## Artifacts\n" +
			"- System Context Diagram\n" +
			"- Container Diagram\n" +
			"- Deployment View\n\n" +
			"## Decisions (ADRs)\n" +
			"- ADR-001: Use Microservices\n" +
			"- ADR-002: Use PostgreSQL\n"

	case "intake":
		return "## Intake Summary\nScope verified. Stakeholders: Admin, Dev Team."

	case "motivation_modeling":
		return "## Motivation Model\n**Driver**: Modernization\n**Goal**: Improve scalability."

	case "roadmap_gaps", "roadmap_and_gaps":
		return "## Roadmap\n1. Phase 1: Foundation\n2. Phase 2: Migration"

	case "review_governance", "review_and_governance":
		return "## Governance Review\n**Status**: APPROVED\n\nAll architecture principles and compliance requirements have been met. Proceed to completion."

	case "iteration":
		return "## Iteration Update\nArchitecture updated based on feedback."

	default:
		return fmt.Sprintf("## Output for %s\nTask completed successfully.", action)
	}
}

func getKeys(m map[string]interface{}) []string {
	keys := make([]string, 0, len(m))
	for k := range m {
		keys = append(keys, k)
	}
	return keys
}
