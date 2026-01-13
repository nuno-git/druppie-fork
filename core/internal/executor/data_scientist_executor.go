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

// DataScientistExecutor handles data science tasks
type DataScientistExecutor struct {
	LLM      llm.Provider
	Registry *registry.Registry
}

func (e *DataScientistExecutor) CanHandle(action string) bool {
	action = strings.ToLower(action)
	return action == "data_scientist" ||
		action == "problem_framing" ||
		action == "data_understanding" ||
		action == "ds_planning" ||
		action == "scaffolding" ||
		action == "ds_implementation" ||
		action == "ds_validation" ||
		action == "packaging" ||
		action == "deployment_prep" ||
		action == "ds_review"
}

func (e *DataScientistExecutor) Execute(ctx context.Context, step model.Step, outputChan chan<- string) error {
	action := step.Action
	outputChan <- fmt.Sprintf("DataScientistExecutor: Executing '%s'...", action)

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

	// Use LLM for DS tasks
	if e.LLM != nil {
		language := ""
		if l, ok := step.Params["language"].(string); ok {
			language = l
		}

		// Lookup Provider and Instructions if AgentID is known
		var providerName string
		var agentInstructions string

		// Default to 'data_scientist' agent if not specified
		agentID := step.AgentID
		if agentID == "" {
			agentID = "data_scientist"
		}

		if e.Registry != nil {
			if agent, err := e.Registry.GetAgent(agentID); err == nil {
				if agent.Provider != "" {
					providerName = agent.Provider
				}
				if agent.Instructions != "" {
					agentInstructions = agent.Instructions
				}
			}
		}

		// Construct System Prompt (Hierarchical: Action Prompt > Agent Instructions > Default)
		defaultPrompt := "You are a Senior Data Scientist. Design and implement Python-based data science solutions."
		if agentInstructions != "" {
			defaultPrompt = agentInstructions
		}

		// Use generic GetActionPrompt to load from agent definition
		systemPrompt := GetActionPrompt(e.Registry, agentID, action, defaultPrompt)

		// Lookup and Append Skill Instructions (Action + Agent Skills)
		skillInstructions := GetCompositeSkillInstructions(e.Registry, agentID, step.Action)

		if skillInstructions != "" {
			systemPrompt += skillInstructions
		}

		// FINAL LANGUAGE ENFORCEMENT
		if language != "" {
			systemPrompt += fmt.Sprintf("\n\n### LANGUAGE REQUIREMENT\n**CRITICAL**: The entire response (narrative, labels, notes) MUST be in **%s**.\nDo NOT translate technical terms if they are standard in English (e.g. Python, Pandas, AWS), but all explanations must be in %s.", language, language)
		}

		// Construct User Prompt with Context
		userPrompt := fmt.Sprintf("Task: %s\n\nContext: %v", action, step.Params)

		// Context Loading: Load previous files (Session Handling via Filesystem)
		filesDir, _ := paths.ResolvePath(".druppie", "plans", planID, "files")
		if files, err := os.ReadDir(filesDir); err == nil {
			var fileContext strings.Builder
			fileContext.WriteString("\n\n--- EXISTING ARTIFACTS ---\n")
			count := 0
			// Load top 5 most recent files? Or all? Usually all relevant ones.
			// For simplicity, we load .md files to understand flow.
			for _, f := range files {
				if strings.HasSuffix(f.Name(), ".md") {
					content, _ := os.ReadFile(filepath.Join(filesDir, f.Name()))
					fileContext.WriteString(fmt.Sprintf("File: %s\nContent:\n%s\n\n", f.Name(), string(content)))
					count++
				}
			}
			if count > 0 {
				userPrompt += fileContext.String()
				outputChan <- fmt.Sprintf("DataScientistExecutor: Loaded %d existing artifacts into context.", count)
			}
		}

		if language != "" {
			userPrompt += fmt.Sprintf("\n\nReminder: Output must be in %s.", language)
		}

		// Debug Logging
		outputChan <- fmt.Sprintf("LLM Prompt Length: %d chars.", len(userPrompt))

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

	// Sanitize Output: Fix Mermaid/Markdown syntax
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
		outputChan <- fmt.Sprintf("Error writing analysis file: %v", err)
		return err
	}

	outputChan <- fmt.Sprintf("Document saved to: %s", filePath)

	// Report usage
	if usage.TotalTokens > 0 || usage.EstimatedCost > 0 {
		outputChan <- fmt.Sprintf("RESULT_TOKEN_USAGE=%d,%d,%d,%.5f", usage.PromptTokens, usage.CompletionTokens, usage.TotalTokens, usage.EstimatedCost)
	}

	return nil
}

func (e *DataScientistExecutor) getFallbackResult(action string) string {
	return fmt.Sprintf("# Data Science Output for %s\n\nTask completed successfully.", action)
}
