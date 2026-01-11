package planner

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"sort"
	"strings"
	"time"

	"reflect"

	"github.com/sjhoeksma/druppie/core/internal/iam"
	"github.com/sjhoeksma/druppie/core/internal/llm"
	"github.com/sjhoeksma/druppie/core/internal/mcp"
	"github.com/sjhoeksma/druppie/core/internal/memory"
	"github.com/sjhoeksma/druppie/core/internal/model"
	"github.com/sjhoeksma/druppie/core/internal/registry"
	"github.com/sjhoeksma/druppie/core/internal/store"
)

type Planner struct {
	llm               llm.Provider
	Registry          *registry.Registry
	Store             store.Store
	Debug             bool
	MCPManager        *mcp.Manager
	Memory            *memory.Manager
	MaxAgentSelection int
}

func (p *Planner) GetLLM() llm.Provider {
	return p.llm
}

func NewPlanner(llm llm.Provider, reg *registry.Registry, store store.Store, mcpMgr *mcp.Manager, memMgr *memory.Manager, maxAgentSelection int, debug bool) *Planner {
	if memMgr == nil {
		memMgr = memory.NewManager(12000, store)
	}
	if maxAgentSelection <= 0 {
		maxAgentSelection = 3 // Default safety
	}
	return &Planner{
		llm:               llm,
		Registry:          reg,
		Store:             store,
		MCPManager:        mcpMgr,
		Memory:            memMgr,
		MaxAgentSelection: maxAgentSelection,
		Debug:             debug,
	}
}

func (p *Planner) cleanJSONResponse(resp string) string {
	clean := strings.TrimSpace(resp)

	// 1. Extract from Markdown Code Blocks if present
	if start := strings.Index(clean, "```"); start != -1 {
		if newline := strings.Index(clean[start:], "\n"); newline != -1 {
			start += newline + 1
		} else {
			start += 3
		}
		end := strings.LastIndex(clean, "```")
		if end > start {
			clean = clean[start:end]
		}
	}

	// 2. Scan for Outermost Brackets (Array or Object) to ignore chatty prefixes/suffixes
	startArr := strings.Index(clean, "[")
	startObj := strings.Index(clean, "{")

	var start, end int
	// Determine if we are looking for Array or Object start
	if startArr != -1 && (startObj == -1 || startArr < startObj) {
		start = startArr
		end = strings.LastIndex(clean, "]")
	} else if startObj != -1 {
		start = startObj
		end = strings.LastIndex(clean, "}")
	} else {
		// No brackets found, return original trimmed (likely will Assert Error later)
		return clean
	}

	if end > start {
		clean = clean[start : end+1]
	}

	// 3. REMOVED Destructive Newline Replacement
	// We trust the LLM/Template to produce valid JSON-escaped strings for code content.
	// Replacing \n with space corrupts 'create_repo' file contents.

	return clean
}

func (p *Planner) selectRelevantAgents(ctx context.Context, intent model.Intent, agents []model.AgentDefinition, planID string) ([]string, model.TokenUsage) {
	var detailedList []string
	for _, a := range agents {
		// Include ID and Description, maybe Skills?
		detailedList = append(detailedList, fmt.Sprintf("%s: %s", a.ID, a.Description))
	}
	// Prompt asks for sorted list by relevance
	prompt := fmt.Sprintf(`Goal: %s

Available Agents:
%v

Task: Select the most relevant agents for this goal.
Rules:
1. Return exactly one JSON array of strings containing Agent IDs.
2. Sort the array by relevance (most relevant first).
3. Select ALL agents necessary for the complete workflow.
   - **CRITICAL**: If the goal involves writing source code, building software, or technical implementation of apps, YOU MUST INCLUDE 'developer'.
4. Guidelines:
   - Video projects -> 'video_content_creator' (This agent handles its own sub-agents like audio/image).
   - Research/Data -> 'data_scientist'
   - Infrastructure/Ops -> 'infrastructure_engineer'
   - Compliance/Policy -> 'compliance'
   - Architecture -> 'architect'
   - General/Ambiguous -> 'business_analyst' (Skip if a specialized agent like 'video_content_creator' is selected).

Example: ["business_analyst"]`, intent.Prompt, detailedList)

	resp, usage, err := p.llm.Generate(ctx, "Select Agents", prompt)
	if err != nil {
		fmt.Printf("[Planner] Agent selection failed: %v\n", err)
		return nil, model.TokenUsage{}
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
			return nil, usage
		}
	}

	// Limit selection based on config
	if len(selected) > p.MaxAgentSelection {
		selected = selected[:p.MaxAgentSelection]
	}

	// Log interaction for visibility
	if p.Store != nil {
		_ = p.Store.LogInteraction(planID, "Agent Selection",
			fmt.Sprintf("--- PROMPT ---\n%s\n--- END PROMPT ---", prompt),
			fmt.Sprintf("--- RESPONSE ---\n%s\n--- END RESPONSE ---\n\nGoal: %s\nSelected: %v\n(Limited to Top %d)", resp, intent.Prompt, selected, p.MaxAgentSelection))
	}

	return selected, usage
}

func (p *Planner) CreatePlan(ctx context.Context, intent model.Intent, planID string) (model.ExecutionPlan, error) {
	// Extract user groups for filtering
	userGroups := []string{}
	if user, ok := iam.GetUserFromContext(ctx); ok && user != nil {
		userGroups = user.Groups
	}

	// 1. Gather Context from Registry
	// Optimization: Only include Registry Building Blocks (Infrastructure/Services) if the intent requires orchestration or infrastructure.
	// For simple 'create_project' code tasks, we reduce token usage by skipping irrelevant blocks.
	var blocks []model.BuildingBlock
	if intent.Action == "orchestrate_complex" || intent.Category == "infrastructure" || intent.Action == "query_registry" {
		blocks = p.Registry.ListBuildingBlocks(userGroups)
	}

	blockNames := make([]string, 0, len(blocks))
	for _, b := range blocks {
		blockNames = append(blockNames, fmt.Sprintf("%s (%s)", b.Name, b.Description))
	}

	// Add MCP Tools from Registry (Templates & Static Definitions)
	// This allows the planner to see tools from servers that aren't running yet (like plan-scoped templates).
	mcpServers := p.Registry.ListMCPServers(userGroups)
	for _, s := range mcpServers {
		for _, t := range s.Tools {
			blockNames = append(blockNames, fmt.Sprintf("%s (%s)", t.Name, t.Description))
		}
	}

	// Add MCP Tools from Running Servers (Dynamic Discovery)
	if p.MCPManager != nil {
		// --- AUTH CHECK ---
		authorizedMap := make(map[string]bool)
		allRegistryMap := make(map[string]bool)

		// ListMCPServers filters by groups
		for _, s := range p.Registry.ListMCPServers(userGroups) {
			authorizedMap[s.Name] = true
		}
		// ListAllMCPServers returns everything
		for _, s := range p.Registry.ListAllMCPServers() {
			allRegistryMap[s.Name] = true
		}

		mcpTools := p.MCPManager.ListAllTools()
		for _, t := range mcpTools {
			// Find server for tool to create Namespaced Name
			srv, _ := p.MCPManager.GetToolServer(t.Name)

			// Check Access
			if allRegistryMap[srv] {
				// If it is a Registry-managed server, it MUST be authorized
				if !authorizedMap[srv] {
					continue // Restricted
				}
			}
			// If not in RegistryMap, it is Dynamic -> Allowed by default logic

			// Format schema for Planner (JSON)
			schemaBytes, _ := json.Marshal(t.InputSchema)
			schemaStr := string(schemaBytes)
			// Truncate schema if too long
			if len(schemaStr) > 200 {
				schemaStr = schemaStr[:200] + "..."
			}

			// Format: server__tool (Description) Args: schema
			// Using namespaced name ensures uniqueness
			namespaced := fmt.Sprintf("%s__%s", srv, t.Name)
			blockNames = append(blockNames, fmt.Sprintf("%s (%s) Args: %s", namespaced, t.Description, schemaStr))
		}
	}

	allAgents := p.Registry.ListAgents(userGroups)

	// Filter Agents
	selectedIDs, usageAgents := p.selectRelevantAgents(ctx, intent, allAgents, planID)

	// Usage tracking
	totalUsage := usageAgents

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

		var sb strings.Builder
		sb.WriteString(fmt.Sprintf("ID: %s\n", a.ID))
		sb.WriteString(fmt.Sprintf("  Name: %s\n", a.Name))
		sb.WriteString(fmt.Sprintf("  Type: %s\n", a.Type))
		if a.Condition != "" {
			sb.WriteString(fmt.Sprintf("  Condition: %s\n", a.Condition))
		}
		if len(a.SubAgents) > 0 {
			sb.WriteString(fmt.Sprintf("  Sub-Agents: %v\n", a.SubAgents))
		}
		if len(a.Skills) > 0 {
			sb.WriteString(fmt.Sprintf("  Skills: %v\n", a.Skills))
		}
		sb.WriteString(fmt.Sprintf("  Priority: %.1f\n", a.Priority))
		sb.WriteString(fmt.Sprintf("  Description: %s\n", a.Description))
		if a.Workflow != "" {
			sb.WriteString(fmt.Sprintf("  Workflow:\n%s\n", a.Workflow))
		}
		// Optimization: Do NOT include full Agent Instructions/Directives here.
		// The Planner only needs Workflow, Skills, and Description to make decisions.
		// Detailed templates (e.g. in Developer agent) differ from Planner logic and waste tokens.
		if a.Instructions != "" {
			sb.WriteString(fmt.Sprintf("  Directives:\n%s", a.Instructions))
		}
		agentList = append(agentList, sb.String())
	}
	//fmt.Printf("[Planner - Agents] %v\n", sortedIDs)

	// 2. Prompt LLM
	// Filter Tools based on User Request ("select the onces which are linked to the agents selected")
	requiredTools := make(map[string]bool)
	for _, a := range activeAgents {
		for _, t := range a.Tools {
			requiredTools[t] = true
		}
	}

	// Rebuild blockNames filtered
	if len(requiredTools) > 0 {
		filteredBlockNames := make([]string, 0)

		// Filter Building Blocks
		for _, b := range blocks {
			if requiredTools[b.ID] || requiredTools["*"] {
				filteredBlockNames = append(filteredBlockNames, fmt.Sprintf("%s (%s)", b.Name, b.Description))
			}
		}

		// Filter MCP Tools
		// Check against Server ID AND Tool Name to be safe
		for _, s := range mcpServers {
			serverMatch := requiredTools[s.ID]
			for _, t := range s.Tools {
				if serverMatch || requiredTools[t.Name] || requiredTools["*"] {
					filteredBlockNames = append(filteredBlockNames, fmt.Sprintf("%s (%s)", t.Name, t.Description))
				}
			}
		}

		// Also check dynamic MCPs (Running Servers)
		// We need to re-scan p.MCPManager.ListTools if needed,
		// but 'blockNames' currently only includes static Registry definitions + dynamic discovery from earlier lines.
		// The earlier dynamic discovery loop (lines 192-239) appended to 'blockNames'.
		// Since we are Overwriting 'blockNames' (or rather replacing it), we need to capture ALL sources.

		// ISSUE: 'blocks' and 'mcpServers' (static) are available variables.
		// But dynamic tools were added to 'blockNames' loop around line 210. We lost the source objects effectively unless we re-fetch.

		// Simpler approach: Filter 'blockNames' strings?
		// No, strings are formatted "Name (Desc)". Parsing back is fragile.

		// Re-run Dynamic Logic here
		if p.MCPManager != nil {
			_, cancel := context.WithTimeout(ctx, 2*time.Second)
			allTools := p.MCPManager.ListAllTools()
			cancel()

			for _, tool := range allTools {
				// Check if tool allowed
				// Tool struct has Name. ServerID? Not easily accessible here maybe.
				if requiredTools[tool.Name] || requiredTools["*"] {
					filteredBlockNames = append(filteredBlockNames, fmt.Sprintf("%s (%s)", tool.Name, tool.Description))
				}
			}
		}

		blockNames = filteredBlockNames
	}
	sysTemplate := ""
	if plannerAgent, err := p.Registry.GetAgent("planner"); err == nil && plannerAgent.Instructions != "" {
		sysTemplate = plannerAgent.Instructions
	} else {
		return model.ExecutionPlan{}, fmt.Errorf("Planner agent not found or no instructions in registry. Ensure agents/planner.md exists")
	}

	replacer := strings.NewReplacer(
		"%goal%", intent.Prompt,
		"%action%", intent.Action,
		"%language%", intent.Language,
		"%tools%", fmt.Sprintf("--- AVAILABLE TOOLS & BLOCKS ---\n%v\n--- END TOOLS ---", blockNames),
		"%agents%", fmt.Sprintf("--- AVAILABLE AGENT DEFINITIONS ---\n%v\n--- END AGENTS ---", agentList),
	)

	if p.Store != nil {
		reqTools := make([]string, 0, len(requiredTools))
		for k := range requiredTools {
			reqTools = append(reqTools, k)
		}
		_ = p.Store.LogInteraction(planID, "Planner", "Context Assembly",
			fmt.Sprintf("Built context for plan %s.\nIncluded Agents: %v\nRequested Tools: %v\nFound Tools/Blocks: %v", planID, sortedIDs, reqTools, blockNames))
	}

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
		var usage model.TokenUsage
		resp, usage, err = p.llm.Generate(ctx, "Generate plan data", sysPrompt)
		if err != nil {
			return model.ExecutionPlan{}, err
		}

		// Accumulate usage
		totalUsage.PromptTokens += usage.PromptTokens
		totalUsage.CompletionTokens += usage.CompletionTokens
		totalUsage.TotalTokens += usage.TotalTokens

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
		idMap := make(map[int]int)
		for i := range steps {
			// Enforce valid, sequential ID and map original ID
			originalID := steps[i].ID
			steps[i].ID = i + 1
			if originalID != 0 {
				idMap[originalID] = steps[i].ID
			}

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

			// Ensure Params initialized and Language injected
			if steps[i].Params == nil {
				steps[i].Params = make(map[string]interface{})
			}
			if _, ok := steps[i].Params["language"]; !ok {
				steps[i].Params["language"] = intent.Language
			}

			// Resolve Dependencies (String -> Int) - Ported from UpdatePlan
			if steps[i].DependsOnRaw != nil {
				resolveDep := func(dep interface{}) {
					if idFloat, ok := dep.(float64); ok {
						oldID := int(idFloat)
						if newID, matches := idMap[oldID]; matches {
							steps[i].DependsOn = append(steps[i].DependsOn, newID)
						} else {
							steps[i].DependsOn = append(steps[i].DependsOn, oldID)
						}
					} else if depStr, ok := dep.(string); ok {
						depStr = strings.ReplaceAll(depStr, "-", "_")
						for j := i - 1; j >= 0; j-- {
							targetAction := strings.ReplaceAll(steps[j].Action, "-", "_") // Normalize
							checkStr := depStr
							if strings.Contains(depStr, ":") {
								parts := strings.SplitN(depStr, ":", 2)
								if len(parts) == 2 {
									checkStr = parts[1]
								}
							}
							if strings.EqualFold(targetAction, checkStr) {
								steps[i].DependsOn = append(steps[i].DependsOn, steps[j].ID)
								break
							}
						}
					}
				}

				switch v := steps[i].DependsOnRaw.(type) {
				case []interface{}:
					for _, d := range v {
						resolveDep(d)
					}
				case string:
					resolveDep(v)
				case float64:
					resolveDep(v)
				}
			}

			// Fallback: If no dependencies defined, enforce sequential execution within the batch
			if len(steps[i].DependsOn) == 0 && i > 0 {
				// Debug Log
				fmt.Printf("[Planner Create TRACER] Fallback triggered for Step %d -> %d\n", steps[i].ID, steps[i-1].ID)
				steps[i].DependsOn = append(steps[i].DependsOn, steps[i-1].ID)
			}

			// CRITICAL VALIDATION: Content Review MUST have av_script
			action := strings.ToLower(steps[i].Action)
			// Action is normalized to snake_case in CreatePlan parsing, but here we process raw steps from slice
			// Wait, parsing happens AFTER validation in the current file flow?
			// No, CreatePlan -> Generate -> Unwrap -> newSteps loop.
			// This block (lines 400-500) seems to be inside CreatePlan loop?
			// Wait, CreatePlan calls Generate.
			// Snippet 4136 showed parsing logic at line 900.
			// Snippet 4197 shows validation at 460?
			// Is 460 inside CreatePlan?
			// CreatePlan in Snippet 4133 lines 700+.
			// Validation seems to be inside a loop RETRYING generation (lines 600-900?).
			// If this loops over `steps`, `steps` are `ParsingStep`.
			// `ParsingStep` `Action` is RAW from LLM.
			// So normalization to snake_case hasn't happened yet if it happens at line 930.

			// Ah, I should normalize `steps[i].Action` HERE too if I want consistency.
			// Or check both. But user wants code to be standard.
			// I'll normalize `action` variable.
			action = strings.ReplaceAll(action, "-", "_")

			if action == "content_review" || action == "draft_scenes" {
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
						validationErr = fmt.Errorf("step %d (content_review) is MISSING required param 'av_script'. Params found: %v", steps[i].ID, steps[i].Params)
						break
					}
				}
			}
		}

		if validationErr == nil {
			break // Success!
		}
	}

	// 4. Construct Plan
	if planID == "" {
		planID = fmt.Sprintf("plan-%d", time.Now().Unix())
	}

	// Initialize Memory Context
	if p.Memory != nil {
		p.Memory.AddEntry(planID, "user", fmt.Sprintf("Goal: %s\nAction: %s", intent.Prompt, intent.Action))
	}

	creatorID := ""
	if u, ok := iam.GetUserFromContext(ctx); ok {
		creatorID = u.ID
	}
	plan := model.ExecutionPlan{
		// ...
		ID:             planID,
		CreatorID:      creatorID,
		Intent:         intent,
		Status:         "created",
		Steps:          steps,
		SelectedAgents: selectedIDs,
		TotalUsage:     totalUsage,
		PlanningUsage:  totalUsage, // Initial plan generation counts as planning usage
	}

	// Persistent Logging
	if p.Store != nil {
		planJSON, _ := json.MarshalIndent(plan, "", "  ")
		_ = p.Store.LogInteraction(plan.ID, "Planner Create",
			fmt.Sprintf("--- PROMPT ---\n%s\n--- END PROMPT ---", sysPrompt),
			fmt.Sprintf("--- RESPONSE ---\n%s\n--- END RESPONSE ---\n\nRESULTING PLAN:\n%s", resp, string(planJSON)))
	}

	// Assign initial usage to the "generate_plan" step if it exists
	for i := range plan.Steps {
		if plan.Steps[i].Action == "generate_plan" {
			plan.Steps[i].Usage = &totalUsage
			break
		}
	}

	return plan, nil

} // UpdatePlan updates an existing plan based on user feedback or answers.
func (p *Planner) UpdatePlan(ctx context.Context, plan *model.ExecutionPlan, feedback string) (*model.ExecutionPlan, error) {
	// 0. Handle Feedback
	// Find the first non-completed step that matches the feedback category and mark it as completed
	for i := range plan.Steps {
		status := plan.Steps[i].Status
		// If it was already completed (by TaskManager /accept logic), just ensure the result is set if empty
		if status == "completed" {
			action := plan.Steps[i].Action
			if action == "ask_questions" || action == "copywriting" || action == "video_design" || action == "content_review" || action == "draft_scenes" || action == "review_and_governance" || action == "review_governance" || action == "audit_request" {
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
			if action == "ask_questions" || action == "copywriting" || action == "video_design" || action == "content_review" || action == "draft_scenes" || action == "review_and_governance" || action == "review_governance" || action == "audit_request" {
				plan.Steps[i].Status = "completed"
				plan.Steps[i].Result = feedback
				break
			}
		}
	}

	// 1. Construct Effective Goal (Context)
	// ONLY update Intent.Prompt if explicit 'refine_intent' step occurred (User Request)
	for _, s := range plan.Steps {
		if s.Action == "refine_intent" && s.Status == "completed" && s.Result != "" {
			// Start fresh from Initial if explicitly refining? Or append?
			// User said "add it to the intent". Usually refinement clarifies/replaces.
			// Safeguard: If result is huge, maybe truncate? But for intent we want query.
			plan.Intent.Prompt = s.Result
		}
	}

	// Truncate pending steps: we want the LLM to redefine the future of the plan
	// based on the new information/feedback.
	var completedSteps []model.Step
	for _, s := range plan.Steps {
		if s.Status == "completed" || (s.Status == "running" && s.Action == "replanning") {
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
	allRegistryAgents := p.Registry.ListAgents(userGroups)
	allowedMap := make(map[string]bool)
	for _, id := range plan.SelectedAgents {
		allowedMap[id] = true
		// Find sub-agents
		if agent, err := p.Registry.GetAgent(id); err == nil {
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

		var sb strings.Builder
		sb.WriteString(fmt.Sprintf("ID: %s\n", a.ID))
		sb.WriteString(fmt.Sprintf("  Name: %s\n", a.Name))
		sb.WriteString(fmt.Sprintf("  Type: %s\n", a.Type))
		if a.Condition != "" {
			sb.WriteString(fmt.Sprintf("  Condition: %s\n", a.Condition))
		}
		if len(a.SubAgents) > 0 {
			sb.WriteString(fmt.Sprintf("  Sub-Agents: %v\n", a.SubAgents))
		}
		if len(a.Skills) > 0 {
			sb.WriteString(fmt.Sprintf("  Skills: %v\n", a.Skills))
		}
		sb.WriteString(fmt.Sprintf("  Priority: %.1f\n", a.Priority))
		sb.WriteString(fmt.Sprintf("  Description: %s\n", a.Description))
		if a.Workflow != "" {
			sb.WriteString(fmt.Sprintf("  Workflow:\n%s\n", a.Workflow))
		}
		// Optimization: Instructions removed from context
		if a.Instructions != "" {
			sb.WriteString(fmt.Sprintf("  Directives:\n%s", a.Instructions))
		}
		updatedAgentList = append(updatedAgentList, sb.String())
	}
	// Backward compatibility link if needed, or just use updatedAgentList in prompt
	// agentList := updatedAgentList

	// --- AUTO-STOP LOGIC (OPTIMIZATION) ---
	// If the workflow reaches a definitive terminal state, stop immediately to save tokens.
	if len(completedSteps) > 0 {
		var lastStep *model.Step
		// Find last meaningful step (ignore replanning)
		for i := len(completedSteps) - 1; i >= 0; i-- {
			if completedSteps[i].Action != "replanning" {
				lastStep = &completedSteps[i]
				break
			}
		}

		if lastStep != nil {
			// Hard Stop for 'promote_plugin' (Terminal action for Plugin workflow)
			if lastStep.Action == "promote_plugin" ||
				lastStep.Action == "run_code" ||
				lastStep.Action == "tool_usage" ||
				lastStep.Action == "image_generation" ||
				lastStep.Action == "video_generation" ||
				lastStep.Action == "text_to_speech" {
				if p.Store != nil {
					_ = p.Store.LogInteraction(plan.ID, "Planner", "Auto-Stop", "Detected terminal action. Stopping plan.")
				}
				return plan, nil
			}
		}
	}
	// --------------------------------

	// Load System Prompt from Agent Definition
	sysTemplate := ""
	if plannerAgent, err := p.Registry.GetAgent("planner"); err == nil && plannerAgent.Instructions != "" {
		sysTemplate = plannerAgent.Instructions
	} else {
		fmt.Println("[Planner] Planner agent not found or no instructions")
		os.Exit(1)
	}

	blocks := p.Registry.ListBuildingBlocks(userGroups)
	blockNames := make([]string, 0, len(blocks))
	for _, b := range blocks {
		blockNames = append(blockNames, b.Name)
	}

	// Add Dynamic MCP Tools to UpdatePlan Context (Previously Missing)
	if p.MCPManager != nil {
		// --- AUTH CHECK ---
		authorizedMap := make(map[string]bool)
		allRegistryMap := make(map[string]bool)

		// ListMCPServers filters by groups
		for _, s := range p.Registry.ListMCPServers(userGroups) {
			authorizedMap[s.Name] = true
		}
		// ListAllMCPServers returns everything
		for _, s := range p.Registry.ListAllMCPServers() {
			allRegistryMap[s.Name] = true
		}

		mcpTools := p.MCPManager.ListAllTools()
		for _, t := range mcpTools {
			srv, _ := p.MCPManager.GetToolServer(t.Name)

			// Check Access
			if allRegistryMap[srv] {
				// If it is a Registry-managed server, it MUST be authorized
				if !authorizedMap[srv] {
					continue // Restricted
				}
			}
			// If not in RegistryMap, it is Dynamic -> Allowed by default logic

			schemaBytes, _ := json.Marshal(t.InputSchema)
			schemaStr := string(schemaBytes)
			if len(schemaStr) > 200 {
				schemaStr = schemaStr[:200] + "..."
			}
			namespaced := fmt.Sprintf("%s__%s", srv, t.Name)
			blockNames = append(blockNames, fmt.Sprintf("%s (%s) Args: %s", namespaced, t.Description, schemaStr))
		}
	}

	replacer := strings.NewReplacer(
		"%goal%", plan.Intent.Prompt,
		"%action%", plan.Intent.Action,
		"%language%", plan.Intent.Language,
		"%tools%", fmt.Sprintf("--- AVAILABLE TOOLS & BLOCKS ---\n%v\n--- END TOOLS ---", blockNames),
		"%agents%", fmt.Sprintf("--- AVAILABLE AGENT DEFINITIONS ---\n%v\n--- END AGENTS ---", updatedAgentList),
	)
	baseSystemPrompt := replacer.Replace(sysTemplate)

	startID := 0
	if len(plan.Steps) > 0 {
		startID = plan.Steps[len(plan.Steps)-1].ID
	}

	// Optimization: Minify Steps for History (Exclude Usage, Truncate Result)
	type MinifiedStep struct {
		StepID    int                    `json:"step_id"`
		AgentID   string                 `json:"agent_id"`
		Action    string                 `json:"action"`
		Params    map[string]interface{} `json:"params,omitempty"`
		Result    string                 `json:"result,omitempty"`
		Status    string                 `json:"status"`
		DependsOn []int                  `json:"depends_on,omitempty"`
	}
	minSteps := make([]MinifiedStep, len(plan.Steps))
	for i, s := range plan.Steps {
		res := s.Result
		if len(res) > 500 {
			res = res[:500] + "... (truncated)"
		}
		minSteps[i] = MinifiedStep{
			StepID:    s.ID,
			AgentID:   s.AgentID,
			Action:    s.Action,
			Params:    s.Params,
			Result:    res,
			Status:    s.Status,
			DependsOn: s.DependsOn,
		}
	}
	stepsJSON, _ := json.MarshalIndent(minSteps, "", "  ")

	// Manage Memory
	if p.Memory != nil && feedback != "" {
		p.Memory.AddEntry(plan.ID, "user", feedback)
	}

	chatHistory := ""
	if p.Memory != nil {
		chatHistory = p.Memory.GetContext(plan.ID)
	} else {
		chatHistory = "User Feedback: " + feedback
	}

	taskPrompt := fmt.Sprintf(
		"--- HISTORY & PROGRESS ---\n"+
			"Current Steps (with results): %s\n"+
			"Uploaded Files: %v\n"+
			"Conversation History:\n%s\n\n"+
			"--- TASK ---\n"+
			"1. REPLAN: Review 'Objective' and 'Current Steps'. If a step has a 'result', that info is now known.\n"+
			"2. STATUS CHECK: Review 'Current Steps'. If 'content-review' is pending, WAITING for user feedback. If 'scene-creator' is pending, WAITING for execution.\n"+
			"3. GENERATE: Provide NEXT steps (starting from id %d). Follow the Strategies defined above.\n"+
			"4. AVOID LOOPS: If the last completed step was an interactive agent (e.g. business-analyst) and the result was a confirmation/answer, DO NOT immediately schedule the same agent for the same task. Proceed to execution or the next phase.\n"+
			"5. COMPLETION CHECK: If the 'current steps' have successfully achieved the 'Goal', you MUST return an empty JSON array `[]`. This will stop the plan.\n"+
			"6. LANGUAGE: Ensure all generated content/parameters use the user's language: %s. NO ENGLISH when not requested.\n"+
			"7. OUTPUT: Return a JSON array of Step objects.",
		string(stepsJSON),
		plan.Files,
		chatHistory,
		startID+1,            // Start ID for new steps
		plan.Intent.Language, // Inject Language
	)

	fullPrompt := baseSystemPrompt + "\n\n" + taskPrompt

	// Add a temporary replanning step to show in Kanban
	replanID := 1
	if len(plan.Steps) > 0 {
		replanID = plan.Steps[len(plan.Steps)-1].ID + 1
	}
	replanStep := model.Step{
		ID:      replanID,
		AgentID: "planner",
		Action:  "replanning",
		Status:  "running",
		Result:  "Replanning based on feedback...",
	}
	plan.Steps = append(plan.Steps, replanStep)
	// Persist so UI sees "Running"
	_ = p.Store.SavePlan(*plan)

	resp, usage, err := p.llm.Generate(ctx, "Refine Plan", fullPrompt)
	if err != nil {
		// Mark replan step as failed
		for i := len(plan.Steps) - 1; i >= 0; i-- {
			if plan.Steps[i].Action == "replanning" && plan.Steps[i].Status == "running" {
				plan.Steps[i].Status = "failed"
				plan.Steps[i].Result = fmt.Sprintf("Error: %v", err)
				break
			}
		}
		_ = p.Store.SavePlan(*plan)
		return nil, err
	}

	// Accumulate Usage in both TotalUsage and PlanningUsage
	plan.TotalUsage.PromptTokens += usage.PromptTokens
	plan.TotalUsage.CompletionTokens += usage.CompletionTokens
	plan.TotalUsage.TotalTokens += usage.TotalTokens
	plan.TotalUsage.EstimatedCost += usage.EstimatedCost

	plan.PlanningUsage.PromptTokens += usage.PromptTokens
	plan.PlanningUsage.CompletionTokens += usage.CompletionTokens
	plan.PlanningUsage.TotalTokens += usage.TotalTokens
	plan.PlanningUsage.EstimatedCost += usage.EstimatedCost

	// Attribute usage to the replanning step
	for i := range plan.Steps {
		if plan.Steps[i].Action == "replanning" && plan.Steps[i].Status == "running" {
			plan.Steps[i].Status = "completed"
			plan.Steps[i].Usage = &usage
			break
		}
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
				}
			} else {
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
			Action:  strings.ReplaceAll(ps.Action, "-", "_"),
			Params:  ps.Params,
		}

		// --- LOOP PREVENTION (Strict) ---
		// Check against LAST completed/running step in history (plan.Steps) to prevent immediate stutter/loop
		// We iterate backwards to find the most recent relevant step
		isDuplicate := false
		if len(plan.Steps) > 0 {
			// Check against the last few steps (window of 3)
			limit := len(plan.Steps) - 3
			if limit < 0 {
				limit = 0
			}
			for k := len(plan.Steps) - 1; k >= limit; k-- {
				oldStep := plan.Steps[k]
				// Skip 'replanning' steps in history comparison
				if oldStep.Action == "replanning" {
					continue
				}

				if oldStep.AgentID == s.AgentID && oldStep.Action == s.Action {
					// Deep Compare Params
					// Note: JSON unmarshal might produce different types (float64 vs int), but let's assume standard unmarshal
					if reflect.DeepEqual(s.Params, oldStep.Params) {
						isDuplicate = true
						if p.Debug {
							fmt.Printf("[Planner] Dropping Loop Duplicate: Step %s:%s (Matches Step %d)\n", s.AgentID, s.Action, oldStep.ID)
						}
						break
					}
				}
			}
		}

		if isDuplicate {
			continue // Skip adding this step
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

		// Inject Language if missing (General Fix)
		if s.Params == nil {
			s.Params = make(map[string]interface{})
		}
		if _, ok := s.Params["language"]; !ok {
			s.Params["language"] = plan.Intent.Language
		}

		// Preserve raw dependencies for later resolution
		s.DependsOnRaw = ps.DependsOnRaw

		// --- Duplicate Audit Prevention (User Request) ---
		if s.Action == "audit_request" {
			auditSatisfied := false
			// Check history
			for _, prev := range plan.Steps {
				if prev.Action == "audit_request" && (prev.Status == "completed" || prev.Status == "requires_approval") {
					auditSatisfied = true
					break
				}
			}
			// Check current batch
			if !auditSatisfied {
				for _, pending := range newSteps {
					if pending.Action == "audit_request" {
						auditSatisfied = true // Already added one in this batch
						break
					}
				}
			}

			if auditSatisfied {
				// SKIP this duplicate audit
				continue
			}
		}

		newSteps = append(newSteps, s)
	}

	// Adjust IDs using existing startID
	// Recalculate startID based on current plan state (including replanning step)
	// Recalculate startID based on current plan state (including replanning step)
	isReplanningSequence := false
	if len(plan.Steps) > 0 {
		startID = plan.Steps[len(plan.Steps)-1].ID
		if plan.Steps[len(plan.Steps)-1].Action == "replanning" {
			isReplanningSequence = true
		}
	}

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
		if newSteps[i].DependsOnRaw != nil {
			// Helper to resolve one dependency item
			resolveDep := func(dep interface{}) {
				var resolvedID int
				found := false

				if idFloat, ok := dep.(float64); ok {
					resolvedID = int(idFloat)
					found = true
				} else if depStr, ok := dep.(string); ok {
					// Normalize dependency string (replace - with _)
					depStr = strings.ReplaceAll(depStr, "-", "_")

					// Look for matching action in *newly created* steps (preceding this one)
					for j := i - 1; j >= 0; j-- {
						targetAction := newSteps[j].Action
						checkStr := depStr
						if strings.Contains(depStr, ":") {
							parts := strings.SplitN(depStr, ":", 2)
							if len(parts) == 2 {
								checkStr = parts[1]
							}
						}

						if strings.EqualFold(targetAction, checkStr) {
							resolvedID = newSteps[j].ID
							found = true
							break
						}
					}

					// If not found in new steps, search HISTORY (plan.Steps)
					if !found && len(plan.Steps) > 0 {
						for k := len(plan.Steps) - 1; k >= 0; k-- {
							targetAction := plan.Steps[k].Action
							targetAction = strings.ReplaceAll(targetAction, "-", "_")

							checkStr := depStr
							if strings.Contains(depStr, ":") {
								parts := strings.SplitN(depStr, ":", 2)
								if len(parts) == 2 {
									checkStr = parts[1]
								}
							}

							if strings.EqualFold(targetAction, checkStr) {
								resolvedID = plan.Steps[k].ID
								found = true
								if p.Debug {
									fmt.Printf("[Planner] Resolved dependency '%s' to History Step %d\n", depStr, plan.Steps[k].ID)
								}
								break
							}
						}
					}
				}

				if found {
					// Apply Shift: If we are in a replanning sequence and the dependency points to the step
					// immediately preceding the replanner (startID - 1), shift it to the replanner (startID).
					// This ensures the new plan links to the replanning event, not just the old history.
					if isReplanningSequence && resolvedID == startID-1 {
						resolvedID = startID
					}
					for j, d := range newSteps[i].DependsOn {
						newSteps[i].DependsOn[j] = d + 1
					}
					//newSteps[i].DependsOn = append(newSteps[i].DependsOn, resolvedID)
				}
			}

			switch v := newSteps[i].DependsOnRaw.(type) {
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
		// Fallback: If no dependencies defined, enforce sequential execution within the batch
		if len(newSteps[i].DependsOn) == 0 && i > 0 {
			newSteps[i].DependsOn = append(newSteps[i].DependsOn, newSteps[i-1].ID)
		}

		// Enforce Sequential Execution for SAME AGENT
		// If the current step belongs to the same agent as the previous step,
		// and no dependency on the previous step exists, add it.
		// This prevents agents from racing with themselves (e.g. Architect Intake vs Motivation).
		if i > 0 && newSteps[i].AgentID == newSteps[i-1].AgentID {
			hasDep := false
			prevID := newSteps[i-1].ID
			for _, d := range newSteps[i].DependsOn {
				if d == prevID {
					hasDep = true
					break
				}
			}
			if !hasDep {
				newSteps[i].DependsOn = append(newSteps[i].DependsOn, prevID)
			}
		}

	}

	// Filter out duplicate steps (LLMGuard)
	filteredSteps := newSteps

	// Append
	plan.Steps = append(plan.Steps, filteredSteps...)

	// Save to Store
	// Calculate cost before saving
	p.updatePlanCost(plan)

	if p.Store != nil {
		_ = p.Store.SavePlan(*plan)
		planJSON, _ := json.MarshalIndent(plan, "", "  ")
		_ = p.Store.LogInteraction(plan.ID, fmt.Sprintf("Planner Update (Step %d)", startID+1),
			fmt.Sprintf("--- PROMPT ---\n%s\n--- END PROMPT ---", fullPrompt),
			fmt.Sprintf("--- RESPONSE ---\n%s\n--- END RESPONSE ---\n\nRESULTING PLAN:\n%s", resp, string(planJSON)))
	}

	return plan, nil
}

// updatePlanCost calculates and updates the cost for a plan based on current LLM pricing
func (p *Planner) updatePlanCost(plan *model.ExecutionPlan) {
	if plan == nil || p.Store == nil {
		return
	}

	// CalculateCost now aggregates individual step costs
	plan.CalculateCost()
}
