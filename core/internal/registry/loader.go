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

	// 1. Load Building Blocks (blocks -> mapped to BuildingBlocks)
	err := walkAndLoad(filepath.Join(rootDir, "blocks"), []string{".md"}, func(path string, fm []byte, body []byte) error {
		var block model.BuildingBlock
		if err := yaml.Unmarshal(fm, &block); err != nil {
			return fmt.Errorf("failed to parse building block %s: %w", path, err)
		}
		// Fallback ID if missing
		if block.ID == "" {
			block.ID = strings.TrimSuffix(filepath.Base(path), filepath.Ext(path))
		}
		reg.mu.Lock()
		reg.BuildingBlocks[block.ID] = block
		reg.mu.Unlock()
		return nil
	})
	if err != nil {
		// Just log warning instead of failing hard? For now fail hard to ensure correctness
		// But directory might not exist yet
		if !os.IsNotExist(err) {
			return nil, fmt.Errorf("error loading building blocks: %w", err)
		}
	}

	// 2. Load Skills
	err = walkAndLoad(filepath.Join(rootDir, "skills"), []string{".md"}, func(path string, fm []byte, body []byte) error {
		var skill model.Skill
		if err := yaml.Unmarshal(fm, &skill); err != nil {
			return fmt.Errorf("failed to parse skill %s: %w", path, err)
		}
		if skill.ID == "" {
			skill.ID = strings.TrimSuffix(filepath.Base(path), filepath.Ext(path))
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

		reg.mu.Lock()
		reg.Skills[skill.ID] = skill
		reg.mu.Unlock()
		return nil
	})
	if err != nil && !os.IsNotExist(err) {
		return nil, fmt.Errorf("error loading skills: %w", err)
	}

	// 3. Load Agents
	err = walkAndLoad(filepath.Join(rootDir, "agents"), []string{".yaml", ".yml", ".md"}, func(path string, fm []byte, body []byte) error {
		var agent model.AgentDefinition
		if err := yaml.Unmarshal(fm, &agent); err != nil {
			return fmt.Errorf("failed to parse agent %s: %w", path, err)
		}
		if agent.ID == "" {
			agent.ID = strings.TrimSuffix(filepath.Base(path), filepath.Ext(path))
		}

		// Use body as Instructions if available
		if len(body) > 0 {
			cleanBody := strings.TrimSpace(string(body))
			if cleanBody != "" {
				if agent.Instructions == "" {
					agent.Instructions = cleanBody
				} else {
					// Check if body already contains what FM had?
					// Assume appending.
					agent.Instructions = agent.Instructions + "\n\n" + cleanBody
				}
			}
		}

		reg.mu.Lock()
		reg.Agents[agent.ID] = agent
		reg.mu.Unlock()
		return nil
	})
	if err != nil && !os.IsNotExist(err) {
		return nil, fmt.Errorf("error loading agents: %w", err)
	}

	// 4. Load MCP
	err = walkAndLoad(filepath.Join(rootDir, "mcp"), []string{".yaml", ".yml", ".md"}, func(path string, fm []byte, body []byte) error {
		var mcp model.MCPServer
		if err := yaml.Unmarshal(fm, &mcp); err != nil {
			return fmt.Errorf("failed to parse mcp %s: %w", path, err)
		}
		if mcp.ID == "" {
			mcp.ID = strings.TrimSuffix(filepath.Base(path), filepath.Ext(path))
		}
		reg.mu.Lock()
		reg.MCPServers[mcp.ID] = mcp
		reg.mu.Unlock()
		return nil
	})
	if err != nil && !os.IsNotExist(err) {
		return nil, fmt.Errorf("error loading mcp: %w", err)
	}

	return reg, nil
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

		if ext == ".md" {
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
		} else if ext == ".yaml" || ext == ".yml" {
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
