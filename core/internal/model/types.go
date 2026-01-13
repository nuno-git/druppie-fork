package model

import (
	"encoding/json"
	"fmt"
	"os"
	"strings"

	"gopkg.in/yaml.v3"
)

// BuildingBlockType defines the category of a building block
type BuildingBlockType string

const (
	TypeInfrastructure BuildingBlockType = "infrastructure"
	TypeService        BuildingBlockType = "service"
	TypeTool           BuildingBlockType = "tool"
)

// BuildingBlock represents a capability or tool available in the Registry
type BuildingBlock struct {
	ID           string            `json:"id" yaml:"id"`
	Name         string            `json:"name" yaml:"name"`
	Description  string            `json:"description" yaml:"description"`
	Type         BuildingBlockType `json:"type" yaml:"type"`
	Capabilities []string          `json:"capabilities" yaml:"capabilities"`
	Inputs       []string          `json:"inputs" yaml:"inputs"`
	Outputs      []string          `json:"outputs" yaml:"outputs"`
	GitRepo      string            `json:"git_repo" yaml:"git_repo"`
	// Original fields from Frontmatter might vary, so we map them as needed
	Labels     map[string]string `json:"labels,omitempty" yaml:"labels,omitempty"`
	AuthGroups []string          `json:"auth_groups,omitempty" yaml:"auth_groups,omitempty"`
}

func (b *BuildingBlock) UnmarshalYAML(value *yaml.Node) error {
	type Alias BuildingBlock
	var aux Alias
	if err := value.Decode(&aux); err != nil {
		return err
	}
	*b = BuildingBlock(aux)
	b.ID = strings.ReplaceAll(b.ID, "-", "_")
	return nil
}

// Skill represents an AI persona or system prompt
type Skill struct {
	ID           string   `json:"id" yaml:"id"`
	Name         string   `json:"name" yaml:"name"`
	Description  string   `json:"description" yaml:"description"`
	Type         string   `json:"type,omitempty" yaml:"type,omitempty"`
	SystemPrompt string   `json:"system_prompt" yaml:"system_prompt"`
	AllowedTools []string `json:"allowed_tools" yaml:"allowed_tools"`
	AuthGroups   []string `json:"auth_groups,omitempty" yaml:"auth_groups,omitempty"`
}

func (s *Skill) UnmarshalYAML(value *yaml.Node) error {
	type Alias Skill
	var aux Alias
	if err := value.Decode(&aux); err != nil {
		return err
	}
	*s = Skill(aux)
	s.ID = strings.ReplaceAll(s.ID, "-", "_")
	return nil
}

// Intent represents the analyzed user request
type Intent struct {
	InitialPrompt string `json:"initial_prompt"`
	Prompt        string `json:"prompt"`
	Action        string `json:"action"` // create, update, query, approval
	Category      string `json:"category"`
	ContentType   string `json:"content_type,omitempty"` // If category is 'create content', specify what (video, blog, code, etc.)
	Language      string `json:"language"`               // User's language
	Answer        string `json:"answer,omitempty"`       // Direct answer if action is general_chat
}

// TokenUsage tracks LLM token consumption
type TokenUsage struct {
	PromptTokens     int     `json:"prompt_tokens"`
	CompletionTokens int     `json:"completion_tokens"`
	TotalTokens      int     `json:"total_tokens"`
	EstimatedCost    float64 `json:"estimated_cost,omitempty"` // Cost in EUR (or base currency)
}

// Step represents a single unit of work in a plan
type Step struct {
	ID            int                    `json:"step_id"`
	AgentID       string                 `json:"agent_id"`
	Action        string                 `json:"action"`
	Params        map[string]interface{} `json:"params"`
	Result        string                 `json:"result,omitempty"`         // User feedback/answer for this step
	Error         string                 `json:"error,omitempty"`          // captured error message
	Status        string                 `json:"status"`                   // pending, running, completed, requires_approval
	DependsOn     []int                  `json:"depends_on,omitempty"`     // List of step IDs that must complete before this step starts
	DependsOnRaw  interface{}            `json:"-"`                        // Raw value for Mixed Dependency resolution
	AssignedGroup string                 `json:"assigned_group,omitempty"` // The group (e.g. "compliance") that must approve this step
	ApprovedBy    string                 `json:"approved_by,omitempty"`    // The user/agent that approved this step
	Usage         *TokenUsage            `json:"usage,omitempty"`          // Token usage for this step
}

func (s *Step) UnmarshalJSON(data []byte) error {
	type Alias Step
	aux := &struct {
		// Override DependsOn to accept any type (int array or mixed with strings)
		DependsOn interface{} `json:"depends_on"`
		*Alias
	}{
		Alias: (*Alias)(s),
	}
	if err := json.Unmarshal(data, &aux); err != nil {
		return err
	}
	s.AgentID = strings.ReplaceAll(s.AgentID, "-", "_")
	s.Action = strings.ReplaceAll(s.Action, "-", "_")

	// Parse DependsOn
	if aux.DependsOn != nil {
		s.DependsOnRaw = aux.DependsOn // Store raw for planner resolution
		if os.Getenv("DEBUG_PLANNER") == "true" {
			fmt.Printf("[Types DEBUG] Unmarshal Step %d (%s) DependsOn raw: %v\n", s.ID, s.Action, s.DependsOnRaw)
		}
		if arr, ok := aux.DependsOn.([]interface{}); ok {
			var ids []int
			allInts := true
			for _, v := range arr {
				if f, ok := v.(float64); ok {
					ids = append(ids, int(f))
				} else {
					allInts = false
				}
			}
			if allInts {
				s.DependsOn = ids
			}
		}
	}
	return nil
}

func (s *Step) UnmarshalYAML(value *yaml.Node) error {
	type Alias Step
	var aux Alias
	if err := value.Decode(&aux); err != nil {
		return err
	}
	*s = Step(aux)
	s.AgentID = strings.ReplaceAll(s.AgentID, "-", "_")
	s.Action = strings.ReplaceAll(s.Action, "-", "_")
	return nil
}

// ExecutionPlan represents a sequence of steps to fulfill an intent
type ExecutionPlan struct {
	ID                       string     `json:"plan_id"`
	CreatorID                string     `json:"creator_id,omitempty"`
	Intent                   Intent     `json:"intent"`
	Status                   string     `json:"status"`
	Steps                    []Step     `json:"steps"`
	SelectedAgents           []string   `json:"selected_agents"`
	Files                    []string   `json:"files,omitempty"`
	AllowedGroups            []string   `json:"allowed_groups,omitempty"`
	TotalUsage               TokenUsage `json:"total_usage,omitempty"`
	PlanningUsage            TokenUsage `json:"planning_usage,omitempty"`              // LLM usage from plan generation and UpdatePlan calls
	TotalCost                float64    `json:"total_cost,omitempty"`                  // Total cost in euros
	LastInteractionTotalCost float64    `json:"last_interaction_total_cost,omitempty"` // Cost snapshot at last user interaction
}

// MCPServer represents an external tool server
type MCPServer struct {
	ID         string           `json:"id" yaml:"id"`
	Name       string           `json:"name" yaml:"name"`
	URL        string           `json:"url,omitempty" yaml:"url,omitempty"`
	Command    string           `json:"command,omitempty" yaml:"command,omitempty"`
	Args       []string         `json:"args,omitempty" yaml:"args,omitempty"`
	Transport  string           `json:"transport" yaml:"transport"`                   // sse, stdio
	Category   string           `json:"category,omitempty" yaml:"category,omitempty"` // mcp, plugin
	Tools      []ToolDefinition `json:"tools,omitempty" yaml:"tools,omitempty"`
	AuthGroups []string         `json:"auth_groups,omitempty" yaml:"auth_groups,omitempty"`
}

func (m *MCPServer) UnmarshalYAML(value *yaml.Node) error {
	type Alias MCPServer
	var aux Alias
	if err := value.Decode(&aux); err != nil {
		return err
	}
	*m = MCPServer(aux)
	m.ID = strings.ReplaceAll(m.ID, "-", "_")
	return nil
}

// ToolDefinition allows advertising tools in the MCP template
type ToolDefinition struct {
	Name        string `json:"name" yaml:"name"`
	Description string `json:"description" yaml:"description"`
}

// AgentDefinition represents a temple for spawning agents
type AgentDefinition struct {
	ID           string            `json:"id" yaml:"id"`
	Name         string            `json:"name" yaml:"name"`
	Type         string            `json:"type" yaml:"type"` // e.g. "spec_agent", "execution_agent", "support_agent", "system_agent"
	Description  string            `json:"description" yaml:"description"`
	Instructions string            `json:"instructions" yaml:"instructions"` // Inline system prompt
	Provider     string            `json:"provider" yaml:"provider"`         //When empty use default provider
	Skills       []string          `json:"skills" yaml:"skills"`
	Tools        []string          `json:"tools" yaml:"tools"`                         // References to BuildingBlocks or MCPs
	SubAgents    []string          `json:"sub_agents" yaml:"sub_agents"`               // List of agent IDs that this agent orchestrates
	Condition    string            `json:"condition" yaml:"condition"`                 // Logic for when this agent should be triggered
	Workflow     string            `json:"workflow" yaml:"workflow"`                   // Mermaid diagram or text workflow
	Prompts      map[string]string `json:"prompts,omitempty" yaml:"prompts,omitempty"` // Specific prompts for native workflows
	Priority     float64           `json:"priority" yaml:"priority"`
	FinalActions []string          `json:"final_actions" yaml:"final_actions"` // Actions that trigger an immediate stop of the plan
	AuthGroups   []string          `json:"auth_groups,omitempty" yaml:"auth_groups,omitempty"`
}

func (a *AgentDefinition) UnmarshalJSON(data []byte) error {
	type Alias AgentDefinition
	aux := &struct {
		*Alias
	}{
		Alias: (*Alias)(a),
	}
	if err := json.Unmarshal(data, &aux); err != nil {
		return err
	}
	a.ID = strings.ReplaceAll(a.ID, "-", "_")
	for i, s := range a.Skills {
		a.Skills[i] = strings.ReplaceAll(s, "-", "_")
	}
	for i, s := range a.Tools {
		a.Tools[i] = strings.ReplaceAll(s, "-", "_")
	}
	for i, s := range a.SubAgents {
		a.SubAgents[i] = strings.ReplaceAll(s, "-", "_")
	}
	return nil
}

func (a *AgentDefinition) UnmarshalYAML(value *yaml.Node) error {
	type Alias AgentDefinition
	var aux Alias
	if err := value.Decode(&aux); err != nil {
		return err
	}
	*a = AgentDefinition(aux)
	a.ID = strings.ReplaceAll(a.ID, "-", "_")
	for i, s := range a.Skills {
		a.Skills[i] = strings.ReplaceAll(s, "-", "_")
	}
	for i, s := range a.Tools {
		a.Tools[i] = strings.ReplaceAll(s, "-", "_")
	}
	for i, s := range a.SubAgents {
		a.SubAgents[i] = strings.ReplaceAll(s, "-", "_")
	}
	return nil
}

// ComplianceRule represents a policy
type ComplianceRule struct {
	ID          string `json:"id" yaml:"id"`
	Name        string `json:"name" yaml:"name"`
	Description string `json:"description" yaml:"description"`
	RegoPolicy  string `json:"rego_policy" yaml:"rego_policy"`
	Sensitivity string `json:"sensitivity" yaml:"sensitivity"` // low, medium, high
}

func (c *ComplianceRule) UnmarshalYAML(value *yaml.Node) error {
	type Alias ComplianceRule
	var aux Alias
	if err := value.Decode(&aux); err != nil {
		return err
	}
	*c = ComplianceRule(aux)
	c.ID = strings.ReplaceAll(c.ID, "-", "_")
	return nil
}
