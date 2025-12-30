package registry

import (
	"fmt"
	"sync"

	"github.com/sjhoeksma/druppie/core/internal/model"
)

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

// ListBuildingBlocks returns all blocks
func (r *Registry) ListBuildingBlocks() []model.BuildingBlock {
	r.mu.RLock()
	defer r.mu.RUnlock()

	list := make([]model.BuildingBlock, 0, len(r.BuildingBlocks))
	for _, v := range r.BuildingBlocks {
		list = append(list, v)
	}
	return list
}

// ListAgents returns all agents
func (r *Registry) ListAgents() []model.AgentDefinition {
	r.mu.RLock()
	defer r.mu.RUnlock()

	list := make([]model.AgentDefinition, 0, len(r.Agents))
	for _, v := range r.Agents {
		if v.Type == "system-agent" {
			continue
		}
		list = append(list, v)
	}
	return list
}

// ListSkills returns all skills
func (r *Registry) ListSkills() []model.Skill {
	r.mu.RLock()
	defer r.mu.RUnlock()

	list := make([]model.Skill, 0, len(r.Skills))
	for _, v := range r.Skills {
		list = append(list, v)
	}
	return list
}

// ListMCPServers returns all MCP servers
func (r *Registry) ListMCPServers() []model.MCPServer {
	r.mu.RLock()
	defer r.mu.RUnlock()

	list := make([]model.MCPServer, 0, len(r.MCPServers))
	for _, v := range r.MCPServers {
		list = append(list, v)
	}
	return list
}

// Stats returns a summary of the loaded items
func (r *Registry) Stats() map[string]int {
	r.mu.RLock()
	defer r.mu.RUnlock()

	return map[string]int{
		"building_blocks":  len(r.BuildingBlocks),
		"skills":           len(r.Skills),
		"mcp_servers":      len(r.MCPServers),
		"agents":           len(r.Agents),
		"compliance_rules": len(r.Compliance),
	}
}
