package registry

import (
	"bytes"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"strings"

	"github.com/sjhoeksma/druppie/core/internal/model"
	"gopkg.in/yaml.v3"
)

// LoadRegistry scans the given root directory and populates a new Registry
func LoadRegistry(rootDir string) (*Registry, error) {
	reg := NewRegistry()
	if err := reg.Load(rootDir); err != nil {
		return nil, err
	}
	return reg, nil
}

// Load scans the given root directory and updates the Registry atomically
func (r *Registry) Load(rootDir string) error {
	// Initialize temporary maps
	blocks := make(map[string]model.BuildingBlock)
	skills := make(map[string]model.Skill)
	agents := make(map[string]model.AgentDefinition)
	mcps := make(map[string]model.MCPServer)
	comp := make(map[string]model.ComplianceRule)

	// 1. Load Building Blocks
	err := walkAndLoad(filepath.Join(rootDir, "blocks"), []string{".md"}, func(path string, fm []byte, body []byte) error {
		var block model.BuildingBlock
		if err := yaml.Unmarshal(fm, &block); err != nil {
			return fmt.Errorf("failed to parse building block %s: %w", path, err)
		}
		// Fallback ID if missing
		if block.ID == "" {
			block.ID = strings.TrimSuffix(filepath.Base(path), filepath.Ext(path))
			block.ID = strings.ReplaceAll(block.ID, "-", "_")
		}
		blocks[block.ID] = block
		return nil
	})
	if err != nil && !os.IsNotExist(err) {
		return fmt.Errorf("error loading building blocks: %w", err)
	}

	// 2. Load Skills
	err = walkAndLoad(filepath.Join(rootDir, "skills"), []string{".md"}, func(path string, fm []byte, body []byte) error {
		var skill model.Skill
		if err := yaml.Unmarshal(fm, &skill); err != nil {
			return fmt.Errorf("failed to parse skill %s: %w", path, err)
		}
		if skill.ID == "" {
			skill.ID = strings.TrimSuffix(filepath.Base(path), filepath.Ext(path))
			skill.ID = strings.ReplaceAll(skill.ID, "-", "_")
		}

		// Use body as SystemPrompt if available and not set in FM
		if len(body) > 0 {
			cleanBody := strings.TrimSpace(string(body))
			if cleanBody != "" {
				if skill.SystemPrompt == "" {
					skill.SystemPrompt = cleanBody
				} else {
					skill.SystemPrompt = skill.SystemPrompt + "\n\n" + cleanBody
				}
			}
		}
		skills[skill.ID] = skill
		return nil
	})
	if err != nil && !os.IsNotExist(err) {
		return fmt.Errorf("error loading skills: %w", err)
	}

	// 3. Load Agents
	err = walkAndLoad(filepath.Join(rootDir, "agents"), []string{".yaml", ".yml", ".md"}, func(path string, fm []byte, body []byte) error {
		var agent model.AgentDefinition
		if err := yaml.Unmarshal(fm, &agent); err != nil {
			return fmt.Errorf("failed to parse agent %s: %w", path, err)
		}
		if agent.ID == "" {
			agent.ID = strings.TrimSuffix(filepath.Base(path), filepath.Ext(path))
			agent.ID = strings.ReplaceAll(agent.ID, "-", "_")
		}

		// Use body as Instructions if available
		if len(body) > 0 {
			cleanBody := strings.TrimSpace(string(body))
			if cleanBody != "" {
				if agent.Instructions == "" {
					agent.Instructions = cleanBody
				} else {
					agent.Instructions = agent.Instructions + "\n\n" + cleanBody
				}
			}
		}
		agents[agent.ID] = agent
		return nil
	})
	if err != nil && !os.IsNotExist(err) {
		return fmt.Errorf("error loading agents: %w", err)
	}

	// 4. Load MCP
	err = walkAndLoad(filepath.Join(rootDir, "mcp"), []string{".yaml", ".yml", ".md"}, func(path string, fm []byte, body []byte) error {
		var mcp model.MCPServer
		if err := yaml.Unmarshal(fm, &mcp); err != nil {
			return fmt.Errorf("failed to parse mcp %s: %w", path, err)
		}
		if mcp.ID == "" {
			mcp.ID = strings.TrimSuffix(filepath.Base(path), filepath.Ext(path))
			mcp.ID = strings.ReplaceAll(mcp.ID, "-", "_")
		}
		mcps[mcp.ID] = mcp
		return nil
	})
	if err != nil && !os.IsNotExist(err) {
		return fmt.Errorf("error loading mcp: %w", err)
	}

	// 5. Load Compliance Policies
	err = walkAndLoad(filepath.Join(rootDir, "compliance"), []string{".md"}, func(path string, fm []byte, body []byte) error {
		var rule model.ComplianceRule
		if err := yaml.Unmarshal(fm, &rule); err != nil {
			return fmt.Errorf("failed to parse compliance rule %s: %w", path, err)
		}
		if rule.ID == "" {
			rule.ID = strings.TrimSuffix(filepath.Base(path), filepath.Ext(path))
			rule.ID = strings.ReplaceAll(rule.ID, "-", "_")
		}

		if len(body) > 0 && rule.RegoPolicy == "" {
			rule.RegoPolicy = string(body)
		}
		comp[rule.ID] = rule
		return nil
	})
	if err != nil && !os.IsNotExist(err) {
		return fmt.Errorf("error loading compliance: %w", err)
	}

	// 6. Load Plugins (MCP definitions from .druppie/plugins/*/mcp.md)
	pluginsDir := filepath.Join(rootDir, ".druppie", "plugins")
	err = walkAndLoad(pluginsDir, []string{".md"}, func(path string, fm []byte, body []byte) error {
		// Only load mcp.md files
		if filepath.Base(path) != "mcp.md" {
			return nil
		}

		var mcp model.MCPServer
		if err := yaml.Unmarshal(fm, &mcp); err != nil {
			return fmt.Errorf("failed to parse plugin mcp %s: %w", path, err)
		}

		// Fallback ID to parent directory name if missing
		if mcp.ID == "" {
			mcp.ID = filepath.Base(filepath.Dir(path))
			mcp.ID = strings.ReplaceAll(mcp.ID, "-", "_")
		}

		// Force category to plugin
		mcp.Category = "plugin"
		mcps[mcp.ID] = mcp
		return nil
	})
	// Ignore if plugins dir doesn't exist, but report actual errors
	if err != nil && !os.IsNotExist(err) {
		return fmt.Errorf("error loading plugins: %w", err)
	}

	// Atomic Update
	r.mu.Lock()
	defer r.mu.Unlock()
	r.BuildingBlocks = blocks
	r.Skills = skills
	r.Agents = agents
	r.MCPServers = mcps
	r.Compliance = comp

	return nil
}

// walkAndLoad walks a directory, finding files with allowed extensions, extracting data, and calling the handler.
// allowedExtensions: e.g. []string{".md", ".yaml"}
func walkAndLoad(dir string, allowedExtensions []string, handler func(path string, fm []byte, body []byte) error) error {
	// Check if dir exists
	if _, err := os.Stat(dir); os.IsNotExist(err) {
		return err
	}

	return filepath.WalkDir(dir, func(path string, d fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if d.IsDir() {
			return nil
		}

		ext := filepath.Ext(path)
		isAllowed := false
		for _, allowed := range allowedExtensions {
			if ext == allowed {
				isAllowed = true
				break
			}
		}
		if !isAllowed {
			return nil
		}

		// Read file
		content, err := os.ReadFile(path)
		if err != nil {
			return err
		}

		var fm []byte
		var body []byte

		switch ext {
		case ".md":
			// Parse Frontmatter + Body
			var extractErr error
			fm, body, extractErr = extractFrontmatter(content)
			if extractErr != nil {
				// Error reading frontmatter, maybe log? For now skip or assume whole file is body?
				// If FM missing, we might assume it's just a text file but we need FM to define ID etc.
				// Based on current logic, if FM extraction fails, we skip.
				return nil
			}
			if fm == nil {
				// No frontmatter found
				return nil
			}
		case ".yaml", ".yml":
			// YAML file IS the FM, no body
			fm = content
		}

		return handler(path, fm, body)
	})
}

// extractFrontmatter peeks at the file content and extracts the YAML block between --- and ---
// Returns: frontmatter, body, error
func extractFrontmatter(content []byte) ([]byte, []byte, error) {
	if !bytes.HasPrefix(content, []byte("---")) {
		return nil, content, nil // No valid FM start
	}

	// Find closing delimiter \n---
	const delim = "\n---"
	// We search starting after first ---
	startSearch := 3
	end := bytes.Index(content[startSearch:], []byte(delim))
	if end == -1 {
		// Possibly \r\n---
		delim2 := "\r\n---"
		end = bytes.Index(content[startSearch:], []byte(delim2))
		if end == -1 {
			return nil, content, nil // No valid FM end
		}
		// Found \r\n---
		actualEnd := startSearch + end
		fm := content[startSearch:actualEnd]

		bodyStart := actualEnd + len(delim2)
		// consume next newline if present
		if bodyStart < len(content) && content[bodyStart] == '\n' {
			bodyStart++
		}
		return fm, content[bodyStart:], nil
	}

	// Found \n---
	actualEnd := startSearch + end
	fm := content[startSearch:actualEnd]

	bodyStart := actualEnd + len(delim)
	// consume next newline if present
	if bodyStart < len(content) && content[bodyStart] == '\n' {
		bodyStart++
	} else if bodyStart < len(content) && content[bodyStart] == '\r' {
		bodyStart++
		if bodyStart < len(content) && content[bodyStart] == '\n' {
			bodyStart++
		}
	}

	return fm, content[bodyStart:], nil
}
