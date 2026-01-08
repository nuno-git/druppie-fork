package executor

import (
	"context"
	"fmt"
	"path/filepath"
	"strings"

	"github.com/sjhoeksma/druppie/core/internal/mcp"
	"github.com/sjhoeksma/druppie/core/internal/model"
	"github.com/sjhoeksma/druppie/core/internal/paths"
)

// MCPExecutor handles execution of tools provided by MCP servers
type MCPExecutor struct {
	Manager *mcp.Manager
}

// CanHandle checks if the action corresponds to a known MCP tool
func (e *MCPExecutor) CanHandle(action string) bool {
	if e.Manager == nil {
		return false
	}
	// Direct tool name match
	_, ok := e.Manager.GetServerForTool(action)
	return ok
}

// Execute calls the tool via the MCP Manager
func (e *MCPExecutor) Execute(ctx context.Context, step model.Step, outputChan chan<- string) error {
	outputChan <- fmt.Sprintf("[mcp] Executing: %s", step.Action)

	// Normalize Parameters (AI alias handling)
	// Map common variations to strict MCP schema keys
	if p, ok := step.Params["file_path"].(string); ok && step.Params["path"] == nil {
		step.Params["path"] = p
	} else if p, ok := step.Params["filename"].(string); ok && step.Params["path"] == nil {
		step.Params["path"] = p
	}
	if c, ok := step.Params["data"].(string); ok && step.Params["content"] == nil {
		step.Params["content"] = c
	} else if c, ok := step.Params["body"].(string); ok && step.Params["content"] == nil {
		step.Params["content"] = c
	}

	// Normalize Path for Filesystem Tools
	// The Planner often generates relative paths, but MCP servers usually require absolute paths used in setup.
	if step.Action == "write_file" || step.Action == "read_file" || step.Action == "list_directory" || step.Action == "create_directory" {
		if pathVal, ok := step.Params["path"].(string); ok && pathVal != "" {
			if !filepath.IsAbs(pathVal) {
				// Resolve relative to Plan Directory
				planID, _ := step.Params["plan_id"].(string)
				if planID == "" {
					planID, _ = step.Params["_plan_id"].(string)
				}

				if planID != "" {
					// Construction: .druppie/plans/<id>
					planRoot, _ := paths.ResolvePath(".druppie", "plans", planID)
					absPath := filepath.Join(planRoot, pathVal)

					// Security Check: Prevent directory traversal
					// Ensure the resulting path is still within the planRoot
					cleanRoot := filepath.Clean(planRoot)
					cleanPath := filepath.Clean(absPath)
					if !strings.HasPrefix(cleanPath, cleanRoot) {
						return fmt.Errorf("security violation: path %s escapes plan execution directory %s", pathVal, planID)
					}

					step.Params["path"] = absPath
				}
			}
		}
	}

	// Call the tool
	result, err := e.Manager.ExecuteTool(ctx, step.Action, step.Params)
	if err != nil {
		return fmt.Errorf("mcp tool execution failed: %w", err)
	}

	// Process Output
	if result.IsError {
		return fmt.Errorf("mcp tool returned error status")
	}

	var texts []string
	for _, content := range result.Content {
		switch content.Type {
		case "text":
			texts = append(texts, content.Text)
			outputChan <- content.Text
		case "image":
			outputChan <- "[Image Content Received]"
		default:
			outputChan <- fmt.Sprintf("[%s content]", content.Type)
		}
	}

	if len(texts) == 0 {
		texts = append(texts, "Tool executed successfully.")
		outputChan <- "Tool executed successfully."
	}

	// Capture result for Plan History
	finalOutput := strings.Join(texts, "\n")
	outputChan <- fmt.Sprintf("RESULT_CONSOLE_OUTPUT=%s", finalOutput)

	return nil
}
