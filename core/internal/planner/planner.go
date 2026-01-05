package planner

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"sort"
	"strings"
	"time"

	"github.com/sjhoeksma/druppie/core/internal/iam"
	"github.com/sjhoeksma/druppie/core/internal/llm"
	"github.com/sjhoeksma/druppie/core/internal/model"
	"github.com/sjhoeksma/druppie/core/internal/registry"
	"github.com/sjhoeksma/druppie/core/internal/store"
)

type Planner struct {
	llm      llm.Provider
	registry *registry.Registry
	Store    store.Store
	Debug    bool
}

func (p *Planner) GetLLM() llm.Provider {
	return p.llm
}

func NewPlanner(llm llm.Provider, reg *registry.Registry, store store.Store, debug bool) *Planner {
	return &Planner{
		llm:      llm,
		registry: reg,
		Store:    store,
		Debug:    debug,
	}
}

func (p *Planner) cleanJSONResponse(resp string) string {
	clean := strings.TrimSpace(resp)
	if start := strings.Index(clean, "```"); start != -1 {
		if newline := strings.Index(clean[start:], "\n"); newline != -1 {
			start += newline + 1
		} else {
			start += 3
		}
		end := strings.LastIndex(clean, "```")
		if end > start {
			clean = clean[start:end]
		} else {
			clean = clean[start:]
		}
	}
	clean = strings.TrimSpace(clean)

	// Sanitize: Replace literal control characters (newlines, tabs) with spaces to ensure valid JSON parsing
	// because LLMs often fail to escape them inside strings.
	// We accept the minor loss of formatting in text fields in exchange for structural validity.
	clean = strings.ReplaceAll(clean, "\n", " ")
	clean = strings.ReplaceAll(clean, "\r", " ")
	clean = strings.ReplaceAll(clean, "\t", " ")

	// Robustly close brackets and braces
	depthMap := map[rune]int{'{': 0, '[': 0}
	for _, r := range clean {
		switch r {
		case '{':
			depthMap['{']++
		case '}':
			depthMap['{']--
		case '[':
			depthMap['[']++
		case ']':
			depthMap['[']--
		}
	}
	// Append missing closers in reverse order? Simple check:
	for depthMap['['] > 0 {
		clean += "]"
		depthMap['[']--
	}
	for depthMap['{'] > 0 {
		clean += "}"
		depthMap['{']--
	}
	return clean
}

func (p *Planner) selectRelevantAgents(ctx context.Context, intent model.Intent, agents []model.AgentDefinition) []string {
	var detailedList []string
	for _, a := range agents {
		detailedList = append(detailedList, fmt.Sprintf("%s: %s", a.ID, a.Description))
	}
	prompt := fmt.Sprintf("Goal: %s\nAvailable Agents:\n%v\n\nTask: Return exactly one JSON array of strings containing Agent IDs. Be extremely restrictive.\nGuidelines:\n- For video content, use 'video-content-creator' ONLY (it replaces business-analyst).\n- For research/data tasks, use 'data-scientist'.\n- For infrastructure/ops, use 'infrastructure-engineer'.\n- For architecture, use 'architect'.\n- For other VAGUE goals, include 'business-analyst'.\nExample: [\"video-content-creator\"]", intent.Prompt, detailedList)
	resp, err := p.llm.Generate(ctx, "Select Agents", prompt)
	if err != nil {
		return nil
	}

	clean := p.cleanJSONResponse(resp)
	var selected []string
	if err := json.Unmarshal([]byte(clean), &selected); err != nil {
		// Try parsing as a wrapped object
		var wrapped struct {
			SelectedAgents []string `json:"selected_agents"`
		}
		if err2 := json.Unmarshal([]byte(clean), &wrapped); err2 == nil && len(wrapped.SelectedAgents) > 0 {
			selected = wrapped.SelectedAgents
		} else {
			if p.Debug {
				fmt.Printf("[Planner] Failed to parse agent selection: %v. Raw: %s\n", err, resp)
			}
			return nil
		}
	}
	return selected
}

func (p *Planner) CreatePlan(ctx context.Context, intent model.Intent, planID string) (model.ExecutionPlan, error) {
	// Extract user groups for filtering
	userGroups := []string{}
	if user, ok := iam.GetUserFromContext(ctx); ok && user != nil {
		userGroups = user.Groups
	}

	// 1. Gather Context from Registry
	blocks := p.registry.ListBuildingBlocks(userGroups)
	blockNames := make([]string, 0, len(blocks))
	for _, b := range blocks {
		blockNames = append(blockNames, b.Name)
	}

	allAgents := p.registry.ListAgents(userGroups)

	// Filter Agents
	selectedIDs := p.selectRelevantAgents(ctx, intent, allAgents)

	// Expand Selection with Sub-Agents
	selectedSet := make(map[string]bool)
	for _, id := range selectedIDs {
		selectedSet[id] = true
	}

	// Expand to include declared sub-agents
	// We iterate allAgents to find the definitions of the selected ones so we can read their SubAgents
	for _, a := range allAgents {
		if selectedSet[a.ID] {
			for _, sub := range a.SubAgents {
				selectedSet[sub] = true
			}
		}
	}

	var activeAgents []model.AgentDefinition
	if len(selectedSet) > 0 {
		for _, a := range allAgents {
			if selectedSet[a.ID] {
				activeAgents = append(activeAgents, a)
			}
		}
	}

	// Safety Net: If selection yielded 0 valid agents (e.g. hallucination), use all
	if len(activeAgents) == 0 {
		activeAgents = allAgents
	}

	// Sort agents by priority (descending)
	sort.Slice(activeAgents, func(i, j int) bool {
		return activeAgents[i].Priority > activeAgents[j].Priority
	})

	sortedIDs := make([]string, 0, len(activeAgents))
	agentList := make([]string, 0, len(activeAgents))
	for _, a := range activeAgents {
		sortedIDs = append(sortedIDs, a.ID)
		agentList = append(agentList, fmt.Sprintf(
			"ID: %s\n  Name: %s\n  Type: %s\n  Condition: %s\n  Sub-Agents: %v\n  Skills: %v\n  Priority: %.1f\n  Description: %s\n  Workflow:\n%s\n  Directives & Structure:\n%s",
			a.ID, a.Name, a.Type, a.Condition, a.SubAgents, a.Skills, a.Priority, a.Description, a.Workflow, a.Instructions,
		))
	}
	//fmt.Printf("[Planner - Agents] %v\n", sortedIDs)

	// 2. Prompt LLM
	sysTemplate := ""
	if plannerAgent, err := p.registry.GetAgent("planner"); err == nil && plannerAgent.Instructions != "" {
		sysTemplate = plannerAgent.Instructions
	} else {
		fmt.Println("[Planner] Planner agent not found or no instructions")
		os.Exit(1)
	}

	replacer := strings.NewReplacer(
		"%goal%", intent.Prompt,
		"%action%", intent.Action,
		"%language%", intent.Language,
		"%tools%", fmt.Sprintf("%v", blockNames),
		"%agents%", fmt.Sprintf("%v", agentList),
	)
	sysPrompt := replacer.Replace(sysTemplate)

	var steps []model.Step
	var validationErr error
	var resp string

	// Retry Loop for LLM Generation & Validation (Max 3 attempts)
	for attempt := 0; attempt < 3; attempt++ {
		if attempt > 0 && validationErr != nil {
			// Augment prompt with error
			sysPrompt += fmt.Sprintf("\n\nCRITICAL ERROR in previous attempt: %v\nYOU MUST FIX THIS. RE-GENERATE THE JSON.", validationErr)
			fmt.Printf("[Planner] Retrying Plan Generation (Attempt %d). Error: %v\n", attempt+1, validationErr)
		}

		var err error
		resp, err = p.llm.Generate(ctx, "Generate plan data", sysPrompt)
		if err != nil {
			return model.ExecutionPlan{}, err
		}

		// 3. Parse Response
		cleanResp := p.cleanJSONResponse(resp)

		// Attempt 1: Direct Array
		if err := json.Unmarshal([]byte(cleanResp), &steps); err != nil {
			// Attempt 2: Wrapped Object {"steps": [...]}
			var wrapped struct {
				Steps []model.Step `json:"steps"`
			}
			if err2 := json.Unmarshal([]byte(cleanResp), &wrapped); err2 == nil && len(wrapped.Steps) > 0 {
				steps = wrapped.Steps
			} else {
				// Attempt 3: Single Object
				var singleStep model.Step
				if err3 := json.Unmarshal([]byte(cleanResp), &singleStep); err3 == nil && singleStep.Action != "" {
					steps = []model.Step{singleStep}
				} else {
					// JSON Parse Error - Retry
					validationErr = fmt.Errorf("invalid json format: %v", err)
					continue
				}
			}
		}

		// Ensure all steps have a status and normalized params
		validationErr = nil // Reset
		for i := range steps {
			if steps[i].Status == "" {
				steps[i].Status = "pending"
			}

			// Normalize 'av_script' aliases
			if steps[i].Params != nil {
				for _, alias := range []string{"script_outline", "scene_outline", "scenes_draft", "scenes"} {
					if val, ok := steps[i].Params[alias]; ok {
						if _, hasAv := steps[i].Params["av_script"]; !hasAv {
							steps[i].Params["av_script"] = val
							delete(steps[i].Params, alias)
						}
					}
				}
			}

			// CRITICAL VALIDATION: Content Review MUST have av_script
			action := strings.ToLower(steps[i].Action)
			if action == "content-review" || action == "draft-scenes" || action == "draft_scenes" {
				if _, ok := steps[i].Params["av_script"]; !ok {
					// Check aliases again just in case (redundant but safe)
					found := false
					for _, alias := range []string{"script", "scenes", "outline"} {
						if _, ok := steps[i].Params[alias]; ok {
							found = true
							break
						}
					}
					if !found {
						validationErr = fmt.Errorf("step %d (content-review) is MISSING required param 'av_script'. Params found: %v", steps[i].ID, steps[i].Params)
						break
					}
				}
			}
		}

		if validationErr == nil {
			break // Success!
		}
	}

	// Final check
	if validationErr != nil {
		fmt.Printf("[Planner] Validation failed after retries: %v\n", validationErr)
		// Fallback: Inject a placeholder script to prevent crash
		for i := range steps {
			if strings.Contains(steps[i].Action, "content-review") {
				steps[i].Params["av_script"] = []map[string]interface{}{
					{
						"scene_id":      1,
						"audio_text":    "Placeholder Scene 1 (Auto-injected due to generation failure)",
						"visual_prompt": "Placeholder Visual",
						"duration":      5,
					},
				}
				fmt.Printf("[Planner] INJECTED PLACEHOLDER AV_SCRIPT for Step %d\n", steps[i].ID)
			}
		}
	}

	// 4. Construct Plan
	if planID == "" {
		planID = fmt.Sprintf("plan-%d", time.Now().Unix())
	}

	creatorID := ""
	if u, ok := iam.GetUserFromContext(ctx); ok {
		creatorID = u.ID
	}

	plan := model.ExecutionPlan{
		// Use a UUID or timestamp.
		// Note: The Caller (main.go) dictates the ID in the async flow, but for synchronous creation we generate one.
		ID:             planID,
		CreatorID:      creatorID,
		Intent:         intent,
		Status:         "created",
		Steps:          steps,
		SelectedAgents: selectedIDs,
	}

	// Persistent Logging
	// NOTE: Plan is NOT saved here - caller is responsible for saving with correct ID
	if p.Store != nil {
		planJSON, _ := json.MarshalIndent(plan, "", "  ")
		_ = p.Store.LogInteraction(plan.ID, "Planner Create",
			fmt.Sprintf("--- PROMPT ---\n%s\n--- END PROMPT ---", sysPrompt),
			fmt.Sprintf("--- RESPONSE ---\n%s\n--- END RESPONSE ---\n\nRESULTING PLAN:\n%s", resp, string(planJSON)))
	}

	return plan, nil
}

// UpdatePlan updates an existing plan based on user feedback or answers.
func (p *Planner) UpdatePlan(ctx context.Context, plan *model.ExecutionPlan, feedback string) (*model.ExecutionPlan, error) {
	// 0. Handle Feedback
	// Find the first non-completed step that matches the feedback category and mark it as completed
	for i := range plan.Steps {
		status := plan.Steps[i].Status
		// If it was already completed (by TaskManager /accept logic), just ensure the result is set if empty
		if status == "completed" {
			action := plan.Steps[i].Action
			if action == "ask_questions" || action == "copywriting" || action == "video-design" || action == "content-review" || action == "draft_scenes" {
				if plan.Steps[i].Result == "" {
					plan.Steps[i].Result = feedback
				}
				// We don't break yet, in case there's another active one (unlikely but safe)
			}
			continue
		}
		if status == "pending" || status == "waiting_input" || status == "running" {
			// If it's a question or content creation step, mark it as completed
			action := plan.Steps[i].Action
			if action == "ask_questions" || action == "copywriting" || action == "video-design" || action == "content-review" || action == "draft_scenes" {
				plan.Steps[i].Status = "completed"
				plan.Steps[i].Result = feedback
				break
			}
		}
	}

	// 1. Construct Effective Goal (Context)
	effectiveGoal := plan.Intent.InitialPrompt
	for _, s := range plan.Steps {
		if s.Result != "" {
			effectiveGoal += fmt.Sprintf("\n- %s", s.Result)
		}
	}
	// Update the active prompt to reflect the full gathered context
	plan.Intent.Prompt = effectiveGoal

	// Truncate pending steps: we want the LLM to redefine the future of the plan
	// based on the new information/feedback.
	var completedSteps []model.Step
	for _, s := range plan.Steps {
		if s.Status == "completed" {
			completedSteps = append(completedSteps, s)
		}
	}
	plan.Steps = completedSteps

	// --- INTERNAL WORKFLOW EXPANSION ---
	// Check if the last completed step was an 'expand_loop' directive
	if len(completedSteps) > 0 {
		lastStep := completedSteps[len(completedSteps)-1]
		if lastStep.Action == "expand_loop" {
			// Perform Micro-Expansion logic internally
			if p.Debug {
				fmt.Printf("[Planner] Auto-expanding loop for step %d\n", lastStep.ID)
			}
			newSteps, err := p.expandLoop(lastStep, completedSteps, plan.Steps)
			if err == nil {
				// Append and Return immediately -> SKIP LLM
				plan.Steps = append(plan.Steps, newSteps...)
				if p.Store != nil {
					_ = p.Store.SavePlan(*plan)
					planJSON, _ := json.MarshalIndent(plan, "", "  ")
					_ = p.Store.LogInteraction(plan.ID, fmt.Sprintf("Internal Expansion (Step %d)", lastStep.ID),
						"Internal Logic: expand_loop",
						fmt.Sprintf("Expanded %d steps.\n\nRESULTING PLAN:\n%s", len(newSteps), string(planJSON)))
				}
				return plan, nil
			} else {
				fmt.Printf("[Planner] Expansion failed: %v\n", err)
			}
		}
	}
	// -----------------------------------

	// 2. Re-Prompt LLM for Next Steps
	// Filter Active Agents based on Plan Selection
	// Only show agents that were originally selected + their sub-agents
	// Extract user groups
	userGroups := []string{}
	if user, ok := iam.GetUserFromContext(ctx); ok && user != nil {
		userGroups = user.Groups
	}
	allRegistryAgents := p.registry.ListAgents(userGroups)
	allowedMap := make(map[string]bool)
	for _, id := range plan.SelectedAgents {
		allowedMap[id] = true
		// Find sub-agents
		if agent, err := p.registry.GetAgent(id); err == nil {
			for _, sub := range agent.SubAgents {
				allowedMap[sub] = true
			}
		}
	}

	var activeAgents []model.AgentDefinition
	for _, a := range allRegistryAgents {
		if allowedMap[a.ID] {
			activeAgents = append(activeAgents, a)
		}
	}
	// Fallback: If map is empty (legacy plan?), use all
	if len(activeAgents) == 0 {
		activeAgents = allRegistryAgents
	}

	// Sort agents by priority (descending)
	sort.Slice(activeAgents, func(i, j int) bool {
		return activeAgents[i].Priority > activeAgents[j].Priority
	})

	sortedIDs := make([]string, 0, len(activeAgents))
	//agentList := make([]string, 0, len(activeAgents))
	updatedAgentList := make([]string, 0, len(activeAgents))

	for _, a := range activeAgents {
		sortedIDs = append(sortedIDs, a.ID)

		// Create the detailed description string for the prompt
		updatedAgentList = append(updatedAgentList, fmt.Sprintf(
			"ID: %s\n  Name: %s\n  Type: %s\n  Condition: %s\n  Sub-Agents: %v\n  Skills: %v\n  Priority: %.1f\n  Description: %s\n  Workflow:\n%s",
			a.ID, a.Name, a.Type, a.Condition, a.SubAgents, a.Skills, a.Priority, a.Description, a.Workflow,
		))
	}
	// Backward compatibility link if needed, or just use updatedAgentList in prompt
	// agentList := updatedAgentList

	// --- AUTO-STOP LOGIC REMOVED ---
	// Previously, this stopped planning if scene count matched script length.
	// This prevented post-production steps (Merge/Final Review) from being scheduled.
	// We now let the LLM decide when to stop based on the workflow state.
	// --------------------------------

	// Load System Prompt from Agent Definition
	sysTemplate := ""
	if plannerAgent, err := p.registry.GetAgent("planner"); err == nil && plannerAgent.Instructions != "" {
		sysTemplate = plannerAgent.Instructions
	} else {
		fmt.Println("[Planner] Planner agent not found or no instructions")
		os.Exit(1)
	}

	blocks := p.registry.ListBuildingBlocks(userGroups)
	blockNames := make([]string, 0, len(blocks))
	for _, b := range blocks {
		blockNames = append(blockNames, b.Name)
	}

	replacer := strings.NewReplacer(
		"%goal%", plan.Intent.Prompt,
		"%action%", plan.Intent.Action,
		"%language%", plan.Intent.Language,
		"%tools%", fmt.Sprintf("%v", blockNames),
		"%agents%", fmt.Sprintf("%v", updatedAgentList),
	)
	baseSystemPrompt := replacer.Replace(sysTemplate)

	startID := 0
	if len(plan.Steps) > 0 {
		startID = plan.Steps[len(plan.Steps)-1].ID
	}

	stepsJSON, _ := json.MarshalIndent(plan.Steps, "", "  ")
	taskPrompt := fmt.Sprintf(
		"--- HISTORY & PROGRESS ---\n"+
			"Current Steps (with results): %s\n"+
			"Uploaded Files: %v\n"+
			"Latest User Input: %s\n\n"+
			"--- TASK ---\n"+
			"1. REPLAN: Review 'Objective' and 'Current Steps'. If a step has a 'result', that info is now known.\n"+
			"2. STATUS CHECK: Review 'Current Steps'. If 'content-review' is pending, WAITING for user feedback. If 'scene-creator' is pending, WAITING for execution.\n"+
			"3. GENERATE: Provide NEXT steps (starting from id %d). Follow the Strategies defined above.\n"+
			"4. AVOID LOOPS: If the last completed step was an interactive agent (e.g. business-analyst) and the result was a confirmation/answer, DO NOT immediately schedule the same agent for the same task. Proceed to execution or the next phase.\n"+
			"5. OUTPUT: Return a JSON array of Step objects.",
		string(stepsJSON),
		plan.Files,
		feedback,
		startID+1, // Start ID for new steps
	)

	fullPrompt := baseSystemPrompt + "\n\n" + taskPrompt

	resp, err := p.llm.Generate(ctx, "Refine Plan", fullPrompt)
	if err != nil {
		return nil, err
	}

	// 3. Parse and Append
	cleanResp := p.cleanJSONResponse(resp)

	// Temporary struct to handle string dependencies from LLM
	// Explicit struct to avoid embedding issues and handle flexible dependencies
	type ParsingStep struct {
		StepID       int                    `json:"step_id"`
		AgentID      string                 `json:"agent_id"`
		Action       string                 `json:"action"`
		Params       map[string]interface{} `json:"params"`
		DependsOnRaw interface{}            `json:"depends_on"`
	}
	var parsingSteps []ParsingStep

	if err := json.Unmarshal([]byte(cleanResp), &parsingSteps); err != nil {
		// Try wrapped
		var wrapped struct {
			Steps []ParsingStep `json:"steps"`
		}
		if err2 := json.Unmarshal([]byte(cleanResp), &wrapped); err2 == nil && len(wrapped.Steps) > 0 {
			parsingSteps = wrapped.Steps
		} else {
			// Try single object
			var single ParsingStep
			if err3 := json.Unmarshal([]byte(cleanResp), &single); err3 == nil {
				if single.Action != "" {
					parsingSteps = []ParsingStep{single}
				} else if p.Debug {
					fmt.Printf("[Planner] Single object parsed but Action is empty. Struct: %+v. RAW JSON: %s\n", single, cleanResp)
				}
			} else {
				if p.Debug {
					fmt.Printf("[Planner] Single object parse failed: %v\n", err3)
				}
				// Attempt 4: Error Object
				var errorResp struct {
					Error string `json:"error"`
				}
				if err4 := json.Unmarshal([]byte(cleanResp), &errorResp); err4 == nil && errorResp.Error != "" {
					if p.Debug {
						fmt.Printf("[Planner] LLM returned error: %s\n", errorResp.Error)
					}
				}
			}
		}
	}

	var newSteps []model.Step
	for _, ps := range parsingSteps {
		s := model.Step{
			ID:      ps.StepID,
			AgentID: ps.AgentID,
			Action:  ps.Action,
			Params:  ps.Params,
		}

		// Normalize 'av_script' aliases
		if s.Params != nil {
			for _, alias := range []string{"script_outline", "scene_outline", "scenes_draft", "scenes"} {
				if val, ok := s.Params[alias]; ok {
					if _, hasAv := s.Params["av_script"]; !hasAv {
						s.Params["av_script"] = val
						delete(s.Params, alias)
					}
				}
			}
		}

		// Resolve Dependencies
		if ps.DependsOnRaw != nil {
			if arr, ok := ps.DependsOnRaw.([]interface{}); ok {
				for _, item := range arr {
					if f, ok := item.(float64); ok {
						s.DependsOn = append(s.DependsOn, int(f))
					}
				}
			} else if f, ok := ps.DependsOnRaw.(float64); ok {
				s.DependsOn = append(s.DependsOn, int(f))
			}
		}

		newSteps = append(newSteps, s)
	}

	if len(newSteps) == 0 && p.Debug {
		// fmt.Printf("[Planner] No new steps generated. Raw response:\n%s\n", resp)
	}

	// Adjust IDs using existing startID
	// startID is already calculated above

	for i := range newSteps {
		newSteps[i].ID = startID + i + 1
		newSteps[i].Status = "pending"

		// Self-Correction: Fix missing AgentID by looking up Skill
		if newSteps[i].AgentID == "" {
			action := strings.ToLower(newSteps[i].Action)
			for _, agent := range activeAgents {
				for _, skill := range agent.Skills {
					if strings.EqualFold(skill, action) {
						newSteps[i].AgentID = agent.ID
						break
					}
				}
				if newSteps[i].AgentID != "" {
					break
				}
			}
			// If still empty, we could fallback or leave it empty (which might cause issues)
			if newSteps[i].AgentID == "" && p.Debug {
				fmt.Printf("[Planner] WARNING: Could not resolve AgentID for action '%s'\n", newSteps[i].Action)
			}
		}

		// Resolve Dependencies (String -> Int)
		ps := parsingSteps[i]
		if ps.DependsOnRaw != nil {
			// Helper to resolve one dependency item
			resolveDep := func(dep interface{}) {
				if idFloat, ok := dep.(float64); ok {
					newSteps[i].DependsOn = append(newSteps[i].DependsOn, int(idFloat))
				} else if depStr, ok := dep.(string); ok {
					// Look for matching action in *newly created* steps (preceding this one)
					for j := 0; j < i; j++ {
						if newSteps[j].Action == depStr {
							newSteps[i].DependsOn = append(newSteps[i].DependsOn, newSteps[j].ID)
							break
						}
					}
				}
			}

			switch v := ps.DependsOnRaw.(type) {
			case []interface{}:
				for _, d := range v {
					resolveDep(d)
				}
			case string:
				resolveDep(v) // Handle single string case
			case float64:
				resolveDep(v)
			}
		}
	}

	// Filter out duplicate steps (LLMGuard)
	// Filter out duplicate steps (LLMGuard)
	// DISABLED: We trust the Planner/Agent logic to avoid loops, or we WANT loops (e.g. rejection -> retry).
	filteredSteps := newSteps

	// Append
	plan.Steps = append(plan.Steps, filteredSteps...)

	// Save to Store
	if p.Store != nil {
		_ = p.Store.SavePlan(*plan)
		planJSON, _ := json.MarshalIndent(plan, "", "  ")
		_ = p.Store.LogInteraction(plan.ID, fmt.Sprintf("Planner Update (Step %d)", startID+1),
			fmt.Sprintf("--- PROMPT ---\n%s\n--- END PROMPT ---", fullPrompt),
			fmt.Sprintf("--- RESPONSE ---\n%s\n--- END RESPONSE ---\n\nRESULTING PLAN:\n%s", resp, string(planJSON)))
	}

	return plan, nil
}
