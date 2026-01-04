package executor

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"github.com/sjhoeksma/druppie/core/internal/model"
)

// DeveloperExecutor handles "create_code" and "modify_code" actions
type DeveloperExecutor struct{}

func (e *DeveloperExecutor) CanHandle(action string) bool {
	return action == "create_code" || action == "modify_code"
}

func (e *DeveloperExecutor) Execute(ctx context.Context, step model.Step, outputChan chan<- string) error {
	outputChan <- "DeveloperExecutor: Processing request..."

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
	cwd, _ := os.Getwd()
	// Default to .druppie/plans/<plan-id>/src
	projectRoot := filepath.Join(cwd, ".druppie", "plans", planID, "src")

	// Ensure root exists
	if err := os.MkdirAll(projectRoot, 0755); err != nil {
		return fmt.Errorf("failed to create project root: %w", err)
	}

	if step.Action == "create_code" {
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

		// Debug params
		outputChan <- fmt.Sprintf("Debug: Received params for create_code: %+v", step.Params)

		if len(fileMap) == 0 {
			// Template Fallback
			if tName, ok := step.Params["template"].(string); ok {
				pType, _ := step.Params["project_type"].(string)
				outputChan <- fmt.Sprintf("Applying template: %s for project type: %s", tName, pType)
				switch strings.ToLower(tName) {
				case "hello-world":
					switch strings.ToLower(pType) {
					case "go", "golang":
						fileMap = map[string]interface{}{"main.go": "package main\n\nimport \"fmt\"\n\nfunc main() {\n    fmt.Println(\"Hello, Druppie Go World!\")\n}\n"}
					case "python", "py":
						fileMap = map[string]interface{}{"main.py": "print(\"Hello, Druppie Python World!\")\n"}
					case "nodejs", "javascript", "js":
						fileMap = map[string]interface{}{"app.js": "console.log(\"Hello, Druppie Node World!\");\n"}
					}
				}
			}
			// Fallback: Check for single file in root params (filename/path + content/code)
			var path, content string

			for _, key := range []string{"filename", "file_name", "path", "file"} {
				if p, ok := step.Params[key].(string); ok {
					path = p
					break
				}
			}

			for _, key := range []string{"content", "code", "body", "text"} {
				if c, ok := step.Params[key].(string); ok {
					content = c
					break
				}
			}

			// Check for Language/Project Type hint
			lang := ""
			if l, ok := step.Params["language"].(string); ok {
				lang = strings.ToLower(l)
			}
			if lang == "" {
				if pt, ok := step.Params["project_type"].(string); ok {
					lang = strings.ToLower(pt)
				}
			}

			// Auto-Infer Path if missing but content exists
			if path == "" && content != "" {
				switch lang {
				case "nodejs", "javascript", "js":
					path = "app.js"
				case "python", "py":
					path = "main.py"
				case "go", "golang":
					path = "main.go"
				case "html":
					path = "index.html"
				default:
					// Generic
					path = "script.txt"
				}
				outputChan <- fmt.Sprintf("Auto-inferred filename: %s (from language/project_type: %s)", path, lang)
			}

			if path != "" && content != "" {
				fileMap = map[string]interface{}{path: content}
				outputChan <- fmt.Sprintf("Recovered single file from params: %s", path)
			} else {
				return fmt.Errorf("create_code requires 'files' parameter map or list of objects (none found in %v)", step.Params)
			}
		}

		for path, content := range fileMap {
			strContent, ok := content.(string)
			if !ok {
				outputChan <- fmt.Sprintf("Skipping %s: content is not string", path)
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

			outputChan <- fmt.Sprintf("Created file: %s", path)
		}
	}

	outputChan <- "DeveloperExecutor: Completed."
	return nil
}
