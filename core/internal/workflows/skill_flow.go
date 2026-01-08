package workflows

import (
	"encoding/json"
	"fmt"
	"strings"

	"github.com/sjhoeksma/druppie/core/internal/model"
)

type SkillExecutionWorkflow struct{}

func (w *SkillExecutionWorkflow) Name() string { return "skill-executor" }

func (w *SkillExecutionWorkflow) Run(wc *WorkflowContext, initialPrompt string) error {
	wc.OutputChan <- fmt.Sprintf("⚙️ [SkillWorkflow] Starting Skill Execution for: %s", initialPrompt)

	// 1. Analyze Intent to identify the skill/action
	action, params, usage, err := w.analyzeSkillIntent(wc, initialPrompt)
	if err != nil {
		return err
	}

	wc.OutputChan <- fmt.Sprintf("🔍 [SkillWorkflow] Identified Skill: %s", action)

	// 2. Execute Skill via Dispatcher
	// We wrap this in a loop to allow for retry logic if needed, but for now single pass

	// Create step for tracking, attaching the analysis usage
	stepID := wc.AppendStep(model.Step{
		AgentID: "skill-executor",
		Action:  action,
		Status:  "running",
		Params:  params,
		Usage:   &usage,
	})

	executor, err := wc.Dispatcher.GetExecutor(action)
	if err != nil {
		wc.AppendStep(model.Step{
			ID:      stepID,
			AgentID: "skill-executor",
			Action:  action,
			Status:  "failed",
			Result:  fmt.Sprintf("No executor found: %v", err),
			Usage:   &usage,
		})
		return err
	}

	execChan := make(chan string, 100)
	var capturedResult string

	go func() {
		defer close(execChan)
		// Inject plan_id if needed by executors
		if params == nil {
			params = make(map[string]interface{})
		}
		params["plan_id"] = wc.PlanID

		_ = executor.Execute(wc.Ctx, model.Step{
			Action:  action,
			Params:  params,
			AgentID: "skill-executor",
		}, execChan)
	}()

	for msg := range execChan {
		// Log normal messages
		wc.OutputChan <- fmt.Sprintf("  %s", msg)

		// Capture structured results
		if strings.HasPrefix(msg, "RESULT_") {
			if capturedResult != "" {
				capturedResult += "\n"
			}
			capturedResult += msg
		}
	}

	wc.OutputChan <- "✅ [SkillWorkflow] Execution Completed."

	wc.AppendStep(model.Step{
		ID:      stepID,
		AgentID: "skill-executor",
		Action:  action,
		Status:  "completed",
		Params:  params,
		Result:  capturedResult,
		Usage:   &usage, // Ensure usage persists in final state
	})

	return nil
}

func (w *SkillExecutionWorkflow) analyzeSkillIntent(wc *WorkflowContext, prompt string) (string, map[string]interface{}, model.TokenUsage, error) {
	// Simple analysis: Ask LLM to extract action and params
	// This makes it generic for any skill supported by the system

	sysPrompt := `You are a Skill Dispatcher. Analyze the user request and map it to a specific system action.
Available Actions likely include: "text-to-speech", "image-generation", "video-generation", "read_file", "write_file", "search_web".
Output JSON: { "action": "action_name", "params": { "key": "value" } }`

	if agent, err := wc.GetAgent("skill-executor"); err == nil {
		if p, ok := agent.Prompts["analyze_skill"]; ok && p != "" {
			sysPrompt = p
		}
	}

	resp, usage, err := wc.LLM.Generate(wc.Ctx, "Analyze Skill", sysPrompt+"\nRequest: "+prompt)
	if wc.UpdateTokenUsage != nil {
		wc.UpdateTokenUsage(usage)
	}

	if err != nil {
		return "", nil, usage, err
	}

	// Clean JSON
	clean := strings.TrimSpace(resp)
	if idx := strings.Index(clean, "{"); idx != -1 {
		clean = clean[idx:]
	}
	if idx := strings.LastIndex(clean, "}"); idx != -1 {
		clean = clean[:idx+1]
	}

	var raw struct {
		Action string                 `json:"action"`
		Params map[string]interface{} `json:"params"`
	}

	if err := json.Unmarshal([]byte(clean), &raw); err != nil {
		return "", nil, usage, fmt.Errorf("failed to parse skill intent: %w", err)
	}

	return raw.Action, raw.Params, usage, nil
}
