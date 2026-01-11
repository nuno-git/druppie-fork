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

// BusinessAnalystExecutor handles business analysis tasks
type BusinessAnalystExecutor struct {
	LLM      llm.Provider
	Registry *registry.Registry
}

func (e *BusinessAnalystExecutor) CanHandle(action string) bool {
	return action == "problem_exploration" ||
		action == "stakeholder_understanding" ||
		action == "requirement_structuring" ||
		action == "epic_definition" ||
		action == "user_story_refinement" ||
		action == "validation" ||
		action == "review" // Business Analyst review
}

func (e *BusinessAnalystExecutor) Execute(ctx context.Context, step model.Step, outputChan chan<- string) error {
	action := step.Action
	outputChan <- fmt.Sprintf("BusinessAnalystExecutor: Executing '%s'...", action)

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

	// Use LLM for analysis tasks
	if e.LLM != nil {
		language := ""
		if l, ok := step.Params["language"].(string); ok {
			language = l
		}

		// Lookup Provider and Instructions if AgentID is known
		var providerName string
		var agentInstructions string

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

		// Construct System Prompt
		systemPrompt := "You are a Senior Business Analyst. Analyze the request and provide structured requirements, stories, or validation reports in Markdown format."

		// Use Agent Instructions if available (User Request)
		if agentInstructions != "" {
			systemPrompt = agentInstructions
		}

		if language != "" {
			systemPrompt = fmt.Sprintf("IMPORTANT: You MUST write in %s language.\n%s", language, systemPrompt)
		}

		// Construct User Prompt with Context
		userPrompt := fmt.Sprintf("Task: %s\n\nContext: %v", action, step.Params)

		// Context Loading: Load previous architectural/analysis files (Session Handling via Filesystem)
		filesDir, _ := paths.ResolvePath(".druppie", "plans", planID, "files")
		if files, err := os.ReadDir(filesDir); err == nil {
			var fileContext strings.Builder
			fileContext.WriteString("\n\n--- EXISTING ARTIFACTS ---\n")
			count := 0
			for _, f := range files {
				if strings.HasSuffix(f.Name(), ".md") {
					content, _ := os.ReadFile(filepath.Join(filesDir, f.Name()))
					fileContext.WriteString(fmt.Sprintf("File: %s\nContent:\n%s\n\n", f.Name(), string(content)))
					count++
				}
			}
			if count > 0 {
				userPrompt += fileContext.String()
				outputChan <- fmt.Sprintf("BusinessAnalystExecutor: Loaded %d existing artifacts into context.", count)
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

func (e *BusinessAnalystExecutor) getFallbackResult(action string) string {
	return fmt.Sprintf("# Analysis Output for %s\n\nTask completed successfully.", action)
}
