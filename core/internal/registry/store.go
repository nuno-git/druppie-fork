package registry

import (
	"fmt"
	"sync"

	"github.com/sjhoeksma/druppie/core/internal/model"
)

// RegistryInterface defines the interface for accessing registry items
type RegistryInterface interface {
	GetSkill(id string) (model.Skill, error)
	GetAgent(id string) (model.AgentDefinition, error)
}

// Registry acts as the in-memory database for all system capabilities
type Registry struct {
	mu             sync.RWMutex
	BuildingBlocks map[string]model.BuildingBlock
	Skills         map[string]model.Skill
	MCPServers     map[string]model.MCPServer
	Agents         map[string]model.AgentDefinition
	Compliance     map[string]model.ComplianceRule
}

// NewRegistry creates an empty registry
func NewRegistry() *Registry {
	return &Registry{
		BuildingBlocks: make(map[string]model.BuildingBlock),
		Skills:         make(map[string]model.Skill),
		MCPServers:     make(map[string]model.MCPServer),
		Agents:         make(map[string]model.AgentDefinition),
		Compliance:     make(map[string]model.ComplianceRule),
	}
}

// GetBuildingBlock retrieves a building block by ID
func (r *Registry) GetBuildingBlock(id string) (model.BuildingBlock, error) {
	r.mu.RLock()
	defer r.mu.RUnlock()

	if val, ok := r.BuildingBlocks[id]; ok {
		return val, nil
	}
	return model.BuildingBlock{}, fmt.Errorf("building block %s not found", id)
}

// RegisterBuildingBlock adds or updates a building block dynamically
func (r *Registry) RegisterBuildingBlock(block model.BuildingBlock) {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.BuildingBlocks[block.ID] = block
}

// GetSkill retrieves a skill by ID
func (r *Registry) GetSkill(id string) (model.Skill, error) {
	r.mu.RLock()
	defer r.mu.RUnlock()

	if val, ok := r.Skills[id]; ok {
		return val, nil
	}
	return model.Skill{}, fmt.Errorf("skill %s not found", id)
}

// GetAgent retrieves an agent definition by ID
func (r *Registry) GetAgent(id string) (model.AgentDefinition, error) {
	r.mu.RLock()
	defer r.mu.RUnlock()

	if val, ok := r.Agents[id]; ok {
		return val, nil
	}
	return model.AgentDefinition{}, fmt.Errorf("agent %s not found", id)
}

// hasAccess checks if the user has access to the item based on groups
func hasAccess(itemGroups, userGroups []string) bool {
	if len(itemGroups) == 0 {
		return true
	}
	if len(userGroups) == 0 {
		return false
	}
	for _, ig := range itemGroups {
		for _, ug := range userGroups {
			if ig == ug {
				return true
			}
		}
	}
	return false
}

// ListBuildingBlocks returns all blocks accessible to the user
func (r *Registry) ListBuildingBlocks(userGroups []string) []model.BuildingBlock {
	r.mu.RLock()
	defer r.mu.RUnlock()

	list := make([]model.BuildingBlock, 0, len(r.BuildingBlocks))
	for _, v := range r.BuildingBlocks {
		if hasAccess(v.AuthGroups, userGroups) {
			list = append(list, v)
		}
	}
	return list
}

// ListAgents returns all agents accessible to the user
func (r *Registry) ListAgents(userGroups []string) []model.AgentDefinition {
	r.mu.RLock()
	defer r.mu.RUnlock()

	list := make([]model.AgentDefinition, 0, len(r.Agents))
	for _, v := range r.Agents {
		if v.Type == "system_agent" {
			continue
		}
		if hasAccess(v.AuthGroups, userGroups) {
			list = append(list, v)
		}
	}
	return list
}

// ListSkills returns all skills accessible to the user
func (r *Registry) ListSkills(userGroups []string) []model.Skill {
	r.mu.RLock()
	defer r.mu.RUnlock()

	list := make([]model.Skill, 0, len(r.Skills))
	for _, v := range r.Skills {
		if hasAccess(v.AuthGroups, userGroups) {
			list = append(list, v)
		}
	}
	return list
}

// ListMCPServers returns all MCP servers accessible to the user
func (r *Registry) ListMCPServers(userGroups []string) []model.MCPServer {
	r.mu.RLock()
	defer r.mu.RUnlock()

	list := make([]model.MCPServer, 0, len(r.MCPServers))
	for _, v := range r.MCPServers {
		if hasAccess(v.AuthGroups, userGroups) {
			list = append(list, v)
		}
	}
	return list
}

// Stats returns a summary of the loaded items
func (r *Registry) Stats() map[string]int {
	r.mu.RLock()
	defer r.mu.RUnlock()

	// Count MCP vs Plugins
	mcpCount := 0
	pluginCount := 0
	for _, s := range r.MCPServers {
		if s.Category == "plugin" {
			pluginCount++
		} else {
			mcpCount++
		}
	}

	return map[string]int{
		"building_blocks":  len(r.BuildingBlocks),
		"skills":           len(r.Skills),
		"mcp_servers":      mcpCount,
		"plugins":          pluginCount,
		"agents":           len(r.Agents),
		"compliance_rules": len(r.Compliance),
	}
}

// GetMCPServer retrieves an MCP server definition by ID
func (r *Registry) GetMCPServer(id string) (model.MCPServer, error) {
	r.mu.RLock()
	defer r.mu.RUnlock()

	if val, ok := r.MCPServers[id]; ok {
		return val, nil
	}
	return model.MCPServer{}, fmt.Errorf("mcp server %s not found", id)
}

// ListAllMCPServers returns all MCP servers without filtering
func (r *Registry) ListAllMCPServers() []model.MCPServer {
	r.mu.RLock()
	defer r.mu.RUnlock()

	list := make([]model.MCPServer, 0, len(r.MCPServers))
	for _, v := range r.MCPServers {
		list = append(list, v)
	}
	return list
}
