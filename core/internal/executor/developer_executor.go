package executor

import (
	"context"
	"fmt"
	"os"
	"path/filepath"

	"github.com/sjhoeksma/druppie/core/internal/model"
	"github.com/sjhoeksma/druppie/core/internal/paths"
)

// DeveloperExecutor handles "create_repo" and "modify_code" actions
type DeveloperExecutor struct{}

func (e *DeveloperExecutor) CanHandle(action string) bool {
	return action == "create_repo" || action == "modify_code"
}

func (e *DeveloperExecutor) Execute(ctx context.Context, step model.Step, outputChan chan<- string) error {
	planID := ""
	if p, ok := step.Params["plan_id"].(string); ok {
		planID = p
	} else if p, ok := step.Params["_plan_id"].(string); ok {
		planID = p
	}

	if planID == "" {
		return fmt.Errorf("missing plan ID in context")
	}

	// Determine Project Root (mimic other executors)
	// Default to .druppie/plans/<plan-id>/src
	projectRoot, _ := paths.ResolvePath(".druppie", "plans", planID, "src")

	// Ensure root exists
	if err := os.MkdirAll(projectRoot, 0755); err != nil {
		return fmt.Errorf("failed to create project root: %w", err)
	}

	if step.Action == "create_repo" {
		// Check for common mistake: using 'template' instead of 'files'
		if template, ok := step.Params["template"].(string); ok {
			return fmt.Errorf("invalid parameter 'template': %s. The developer agent requires actual code content in the 'files' parameter, not template names. Please provide the full code content for each file", template)
		}

		var fileMap map[string]interface{}

		if f, ok := step.Params["files"].(map[string]interface{}); ok {
			fileMap = f
		} else if fList, ok := step.Params["files"].([]interface{}); ok {
			// Convert list of objects to map if possible, e.g. [{"path": "p", "content": "c"}]
			fileMap = make(map[string]interface{})
			for _, item := range fList {
				if itemMap, ok := item.(map[string]interface{}); ok {
					if p, ok := itemMap["path"].(string); ok {
						if c, ok := itemMap["content"].(string); ok {
							fileMap[p] = c
						}
					}
				}
			}
		}

		if len(fileMap) == 0 {
			return fmt.Errorf("missing required parameter 'files' with code content. The developer agent needs actual code, not template references")
		}

		// LOGIC: Auto-Create go.mod if missing for Go projects (Reliability Fix)
		hasGoFiles := false
		hasGoMod := false
		for path := range fileMap {
			if filepath.Ext(path) == ".go" {
				hasGoFiles = true
			}
			if filepath.Base(path) == "go.mod" {
				hasGoMod = true
			}
		}
		if hasGoFiles && !hasGoMod {
			fileMap["go.mod"] = "module main\n\ngo 1.20"
			outputChan <- "[developer] Auto-created 'go.mod' (Defensive Fix)"
		}

		for path, content := range fileMap {
			strContent, ok := content.(string)
			if !ok {
				outputChan <- fmt.Sprintf("[developer] skipping %s: content is not string", path)
				continue
			}

			// Clean path to prevent traversal escape
			cleanPath := filepath.Clean(path)

			if cleanPath == "." || cleanPath == "/" {
				continue
			}
			fullPath := filepath.Join(projectRoot, cleanPath)

			// Ensure dir exists
			if err := os.MkdirAll(filepath.Dir(fullPath), 0755); err != nil {
				return fmt.Errorf("failed to create dir for %s: %w", path, err)
			}

			if err := os.WriteFile(fullPath, []byte(strContent), 0644); err != nil {
				return fmt.Errorf("failed to write %s: %w", path, err)
			}

			outputChan <- fmt.Sprintf("[developer] created file: %s", path)
		}
	}

	return nil
}
