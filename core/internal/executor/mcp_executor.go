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
	if action == "tool_usage" {
		return true
	}
	// Direct tool name match
	_, ok := e.Manager.GetToolServer(action)
	return ok
}

// Execute calls the tool via the MCP Manager
func (e *MCPExecutor) Execute(ctx context.Context, step model.Step, outputChan chan<- string) error {
	// Handle generic "tool_usage" action
	if step.Action == "tool_usage" {
		toolName, ok := step.Params["tool"].(string)
		if !ok {
			toolName, ok = step.Params["tool_name"].(string)
		}
		if !ok {
			return fmt.Errorf("action is 'tool_usage' but no 'tool' or 'tool_name' parameter provided")
		}

		// Update step action to the actual tool
		step.Action = toolName
		outputChan <- fmt.Sprintf("[mcp] Unwrapped tool_usage -> %s", toolName)

		// Rescope params: prefer "arguments" or "args", otherwise usage remaining params
		if args, ok := step.Params["arguments"].(map[string]interface{}); ok {
			step.Params = args
		} else if args, ok := step.Params["args"].(map[string]interface{}); ok {
			step.Params = args
		}
		// If neither, we assume the top-level params (minus 'tool') are the args,
		// but cleaning them is safer to do in the normalization block below.
	}

	// Identify Server
	serverName, _ := e.Manager.GetToolServer(step.Action)
	if serverName == "" {
		serverName = "unknown"
	}
	outputChan <- fmt.Sprintf("[mcp] Executing tool '%s' on server '%s'", step.Action, serverName)

	// Normalize Parameters (AI alias handling)
	// Flatten 'input' or 'args' if they wrap the actual parameters
	if inputParams, ok := step.Params["input"].(map[string]interface{}); ok {
		for k, v := range inputParams {
			step.Params[k] = v
		}
	}
	if argsParams, ok := step.Params["args"].(map[string]interface{}); ok {
		for k, v := range argsParams {
			step.Params[k] = v
		}
	}
	if argsParams, ok := step.Params["arguments"].(map[string]interface{}); ok {
		for k, v := range argsParams {
			step.Params[k] = v
		}
	}
	// Add tool_input alias (Found in Step 1722)
	if toolInputParams, ok := step.Params["tool_input"].(map[string]interface{}); ok {
		for k, v := range toolInputParams {
			step.Params[k] = v
		}
	}

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
		texts = append(texts, "Tool executed successfully (No text content returned).")
		outputChan <- "Tool executed successfully (No text content returned)."
		outputChan <- "DEBUG: Ensure the MCP Plugin returns { content: [{ type: 'text', text: '...' }] }"
	}

	// Capture result for Plan History
	finalOutput := strings.Join(texts, "\n")
	outputChan <- fmt.Sprintf("RESULT_CONSOLE_OUTPUT=%s", finalOutput)

	return nil
}
