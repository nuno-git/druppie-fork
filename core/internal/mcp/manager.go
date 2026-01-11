package mcp

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"
	"sync"

	"github.com/sjhoeksma/druppie/core/internal/registry"
	"github.com/sjhoeksma/druppie/core/internal/store"
)

type ServerConfig struct {
	Name     string   `json:"name"`
	URL      string   `json:"url,omitempty"`
	Command  string   `json:"command,omitempty"`
	Args     []string `json:"args,omitempty"`
	Type     string   `json:"type,omitempty"`     // "dynamic" or "static"
	Category string   `json:"category,omitempty"` // "mcp" or "plugin"
}

// Manager handles multiple MCP servers and tool routing
type Manager struct {
	mu            sync.RWMutex
	servers       map[string]*Client
	tools         map[string]string // ToolName -> ServerName
	cachedTools   []Tool            // Cached list of all tools
	ServerConfigs []ServerConfig
	store         store.Store
	registry      *registry.Registry
}

func NewManager(ctx context.Context, s store.Store, reg *registry.Registry) *Manager {
	m := &Manager{
		servers:       make(map[string]*Client),
		tools:         make(map[string]string),
		cachedTools:   []Tool{},
		ServerConfigs: []ServerConfig{},
		store:         s,
		registry:      reg,
	}
	m.Load()          // Load configs
	m.ConnectAll(ctx) // Restore connections
	return m
}

// Load reads config from store
func (m *Manager) Load() error {
	if m.store == nil {
		return nil
	}
	data, err := m.store.LoadMCPServers()
	if err != nil {
		return err
	}
	if err := json.Unmarshal(data, &m.ServerConfigs); err != nil {
		return err
	}

	// Reconnect to all servers (in background? For now sync or lazy?)
	// Let's lazy connect? Or just populate struct and let AddServer handle re-add logic?
	// If we just load configs, we are not connected.
	// We should probably loop and connect.
	// BUT connecting requires Context. Load() signature doesn't have Context.
	// Let's spawn a background routine or just leave them disconnected until used?
	// Tools are needed immediately.
	// Let's assume the caller will call proper initialization or we blindly trust for now.
	// Valid approach: Just load them. Then have a "ConnectAll" method using a background context at startup.
	// Or better: Re-use AddServer logic iteratively. But AddServer saves.
	// Let's implement ConnectAll(ctx).
	return nil
}

// Save writes config to store
func (m *Manager) Save() error {
	if m.store == nil {
		return nil
	}
	m.mu.RLock()
	defer m.mu.RUnlock()
	// Filter out static servers if we merged them?
	// Or we keep ServerConfigs as dynamic only.
	// GetServers() will merge them.
	// So ServerConfigs stays pure dynamic.

	data, err := json.MarshalIndent(m.ServerConfigs, "", "  ")
	if err != nil {
		return err
	}
	return m.store.SaveMCPServers(data)
}

// ConnectAll restores connections from loaded configs AND registry
func (m *Manager) ConnectAll(ctx context.Context) {
	// 1. Dynamic Servers
	m.mu.RLock()
	configs := append([]ServerConfig(nil), m.ServerConfigs...)
	m.mu.RUnlock()

	for _, cfg := range configs {
		if err := m.connectServer(ctx, cfg); err != nil {
			fmt.Printf("MCP Restore Error [Dynamic:%s]: %v\n", cfg.Name, err)
		}
	}

	// 2. Static Servers from Registry
	if m.registry != nil {
		for _, mcpModel := range m.registry.MCPServers {
			// Avoid duplicate names? Dynamic overrides static.
			m.mu.RLock()
			_, exists := m.servers[mcpModel.Name]
			m.mu.RUnlock()

			if exists {
				continue
			}

			// Skip templates (unresolved variables)
			isTemplate := false
			for _, arg := range mcpModel.Args {
				if strings.Contains(arg, "{{") {
					isTemplate = true
					break
				}
			}
			if isTemplate {
				continue
			}

			cfg := ServerConfig{
				Name:    mcpModel.Name,
				URL:     mcpModel.URL,
				Command: mcpModel.Command,
				Args:    mcpModel.Args,
				Type:    "static",
			}
			if err := m.connectServer(ctx, cfg); err != nil {
				fmt.Printf("MCP Restore Error [Static:%s]: %v\n", mcpModel.Name, err)
			}
		}
	}
}

// Helper to connect without modifying config list or saving (used by ConnectAll and AddServer)
func (m *Manager) connectServer(ctx context.Context, cfg ServerConfig) error {
	m.mu.Lock()
	defer m.mu.Unlock()

	var transport Transport
	if cfg.URL != "" {
		transport = NewHTTPTransport(cfg.URL)
	} else if cfg.Command != "" {
		transport = NewStdioTransport(cfg.Command, cfg.Args)
	} else {
		return fmt.Errorf("server %s has no URL or Command", cfg.Name)
	}

	client := NewClient(transport)
	if err := client.Connect(ctx); err != nil {
		return err
	}
	m.servers[cfg.Name] = client
	return m.refreshToolsLocked(ctx)
}

// AddServer registers a new MCP server (HTTP only for CLI convenience)
func (m *Manager) AddServer(ctx context.Context, name, url string) error {
	cfg := ServerConfig{Name: name, URL: url}
	return m.AddServerConfig(ctx, cfg)
}

// AddServerConfig registers a new MCP server with full configuration
func (m *Manager) AddServerConfig(ctx context.Context, cfg ServerConfig) error {
	// First connect
	if err := m.connectServer(ctx, cfg); err != nil {
		return fmt.Errorf("failed to connect: %w", err)
	}

	// Then Add to config and Save
	m.mu.Lock()
	//Check dupes
	found := false
	for i, c := range m.ServerConfigs {
		if c.Name == cfg.Name {
			m.ServerConfigs[i] = cfg // Update existing
			found = true
			break
		}
	}
	if !found {
		m.ServerConfigs = append(m.ServerConfigs, cfg)
	}
	m.mu.Unlock()

	return m.Save()
}

// RemoveServer unregisters an MCP server
func (m *Manager) RemoveServer(ctx context.Context, name string) error {
	m.mu.Lock()
	defer m.mu.Unlock()

	if _, ok := m.servers[name]; !ok {
		return fmt.Errorf("server not found: %s", name)
	}

	delete(m.servers, name)

	// Remove from configs
	newConfigs := []ServerConfig{}
	for _, c := range m.ServerConfigs {
		if c.Name != name {
			newConfigs = append(newConfigs, c)
		}
	}
	m.ServerConfigs = newConfigs

	// Refresh tools (re-lists from remaining servers)
	if err := m.refreshToolsLocked(ctx); err != nil {
		fmt.Printf("Warning: failed to refresh tools after removal: %v\n", err)
	}

	// Save
	if m.store != nil {
		data, err := json.MarshalIndent(m.ServerConfigs, "", "  ")
		if err == nil {
			if err := m.store.SaveMCPServers(data); err != nil {
				return fmt.Errorf("failed to save config: %w", err)
			}
		}
	}
	return nil
}

// refreshToolsLocked (caller must hold lock)
func (m *Manager) refreshToolsLocked(ctx context.Context) error {
	m.cachedTools = []Tool{}
	m.tools = make(map[string]string)

	for name, client := range m.servers {
		tools, err := client.ListTools(ctx)
		if err != nil {
			fmt.Printf("Warning: failed to list tools from %s: %v\n", name, err)
			continue
		}
		for _, tool := range tools {
			// Register raw name (last write wins)
			m.tools[tool.Name] = name
			// Register namespaced name (server__tool) for uniqueness
			namespaced := fmt.Sprintf("%s__%s", name, tool.Name)
			m.tools[namespaced] = name
			m.cachedTools = append(m.cachedTools, tool)
		}
	}
	return nil
}

// ListTools returns all available tools across all servers
func (m *Manager) ListAllTools() []Tool {
	m.mu.RLock()
	defer m.mu.RUnlock()

	// Return copy
	return append([]Tool(nil), m.cachedTools...)
}

// GetToolServer finds which server hosts the tool
func (m *Manager) GetToolServer(toolName string) (string, bool) {
	m.mu.RLock()
	defer m.mu.RUnlock()
	server, ok := m.tools[toolName]
	return server, ok
}

// ExecuteTool finds the server and calls the tool
func (m *Manager) ExecuteTool(ctx context.Context, toolName string, args map[string]interface{}) (*CallToolResult, error) {
	m.mu.RLock()
	serverName, ok := m.tools[toolName]
	client := m.servers[serverName]
	m.mu.RUnlock()

	if !ok || client == nil {
		return nil, fmt.Errorf("tool not found: %s", toolName)
	}

	// Strip namespace if present
	realToolName := toolName
	if strings.HasPrefix(toolName, serverName+"__") {
		realToolName = strings.TrimPrefix(toolName, serverName+"__")
	}

	return client.CallTool(ctx, realToolName, args)
}

// GetServers returns list of configs
// GetServers returns a list of all server configs (dynamic + static)
func (m *Manager) GetServers() []ServerConfig {
	m.mu.RLock()
	defer m.mu.RUnlock()

	result := []ServerConfig{}
	seen := make(map[string]bool)

	for _, cfg := range m.ServerConfigs {
		cfg.Type = "dynamic"
		result = append(result, cfg)
		seen[cfg.Name] = true
	}

	// Add static servers from registry
	if m.registry != nil {
		for _, mcpModel := range m.registry.MCPServers {
			if seen[mcpModel.Name] {
				// Dynamic overrides static
				continue
			}
			result = append(result, ServerConfig{
				Name:     mcpModel.Name,
				URL:      mcpModel.URL,
				Command:  mcpModel.Command,
				Args:     mcpModel.Args,
				Type:     "static",
				Category: mcpModel.Category,
			})
		}
	}

	return result
}

// EnsurePlanServer provisions a plan-specific MCP server from a template
func (m *Manager) EnsurePlanServer(ctx context.Context, planID string) error {
	var template *ServerConfig

	// 1. Check Registry for 'plan-fs-template'
	if m.registry != nil {
		for _, mc := range m.registry.MCPServers {
			if mc.ID == "plan-fs-template" {
				t := ServerConfig{
					Name:    mc.Name,
					URL:     mc.URL,
					Command: mc.Command,
					Args:    mc.Args,
					Type:    "template",
				}
				template = &t
				break
			}
		}
	}

	// 2. Check Dynamic Configs if not found
	if template == nil {
		m.mu.RLock()
		for _, c := range m.ServerConfigs {
			if c.Name == "plan-fs-template" {
				t := c
				template = &t
				break
			}
		}
		m.mu.RUnlock()
	}

	if template == nil {
		return nil
	}

	newName := fmt.Sprintf("plan-%s-fs", planID)

	// Check if already running
	m.mu.RLock()
	_, exists := m.servers[newName]
	m.mu.RUnlock()
	if exists {
		return nil
	}

	// Create new config with substitution
	newArgs := make([]string, len(template.Args))
	for i, arg := range template.Args {
		newArgs[i] = strings.ReplaceAll(arg, "{{plan_id}}", planID)
	}

	newCfg := ServerConfig{
		Name:    newName,
		Command: template.Command,
		Args:    newArgs,
		Type:    "runtime-plan-scoped",
	}

	if err := m.connectServer(ctx, newCfg); err != nil {
		return fmt.Errorf("failed to start plan server: %w", err)
	}
	// Note: We don't save this to persistent config, it's ephemeral
	return nil
}
