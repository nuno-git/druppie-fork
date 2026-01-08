package model

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

// Skill represents an AI persona or system prompt
type Skill struct {
	ID           string   `json:"id" yaml:"id"`
	Name         string   `json:"name" yaml:"name"`
	Description  string   `json:"description" yaml:"description"`
	SystemPrompt string   `json:"system_prompt" yaml:"system_prompt"`
	AllowedTools []string `json:"allowed_tools" yaml:"allowed_tools"`
	AuthGroups   []string `json:"auth_groups,omitempty" yaml:"auth_groups,omitempty"`
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
	PromptTokens     int `json:"prompt_tokens"`
	CompletionTokens int `json:"completion_tokens"`
	TotalTokens      int `json:"total_tokens"`
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
	AssignedGroup string                 `json:"assigned_group,omitempty"` // The group (e.g. "compliance") that must approve this step
	ApprovedBy    string                 `json:"approved_by,omitempty"`    // The user/agent that approved this step
	Usage         *TokenUsage            `json:"usage,omitempty"`          // Token usage for this step
}

// ExecutionPlan represents a sequence of steps to fulfill an intent
type ExecutionPlan struct {

	ID             string     `json:"plan_id"`
	CreatorID      string     `json:"creator_id,omitempty"`
	Intent         Intent     `json:"intent"`
	Status         string     `json:"status"`
	Steps          []Step     `json:"steps"`
	SelectedAgents []string   `json:"selected_agents"`
	Files          []string   `json:"files,omitempty"`
	AllowedGroups  []string   `json:"allowed_groups,omitempty"`
	TotalUsage     TokenUsage `json:"total_usage,omitempty"`
	TotalCost      float64    `json:"total_cost,omitempty"` // Total cost in euros
}
// MCPServer represents an external tool server
type MCPServer struct {
	ID         string           `json:"id" yaml:"id"`
	Name       string           `json:"name" yaml:"name"`
	URL        string           `json:"url,omitempty" yaml:"url,omitempty"`
	Command    string           `json:"command,omitempty" yaml:"command,omitempty"`
	Args       []string         `json:"args,omitempty" yaml:"args,omitempty"`
	Transport  string           `json:"transport" yaml:"transport"` // sse, stdio
	Tools      []ToolDefinition `json:"tools,omitempty" yaml:"tools,omitempty"`
	AuthGroups []string         `json:"auth_groups,omitempty" yaml:"auth_groups,omitempty"`
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
	Type         string            `json:"type" yaml:"type"` // e.g. "spec-agent", "execution-agent", "support-agent", "system-agent"
	Description  string            `json:"description" yaml:"description"`
	Instructions string            `json:"instructions" yaml:"instructions"` // Inline system prompt
	Provider     string            `json:"provider" yaml:"provider"`         //When empty use default provider
	Model        string            `json:"model" yaml:"model"`               //When empty use default model
	Skills       []string          `json:"skills" yaml:"skills"`
	Tools        []string          `json:"tools" yaml:"tools"`                         // References to BuildingBlocks or MCPs
	SubAgents    []string          `json:"sub_agents" yaml:"sub_agents"`               // List of agent IDs that this agent orchestrates
	Condition    string            `json:"condition" yaml:"condition"`                 // Logic for when this agent should be triggered
	Workflow     string            `json:"workflow" yaml:"workflow"`                   // Mermaid diagram or text workflow
	Prompts      map[string]string `json:"prompts,omitempty" yaml:"prompts,omitempty"` // Specific prompts for native workflows
	Priority     float64           `json:"priority" yaml:"priority"`
	AuthGroups   []string          `json:"auth_groups,omitempty" yaml:"auth_groups,omitempty"`
}

// ComplianceRule represents a policy
type ComplianceRule struct {
	ID          string `json:"id" yaml:"id"`
	Name        string `json:"name" yaml:"name"`
	Description string `json:"description" yaml:"description"`
	RegoPolicy  string `json:"rego_policy" yaml:"rego_policy"`
	Sensitivity string `json:"sensitivity" yaml:"sensitivity"` // low, medium, high
}
