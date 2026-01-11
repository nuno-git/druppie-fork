package mcp

import (
	"context"
	"fmt"
	"strings"
)

// Call is a helper to execute an MCP tool with variadic arguments and return a simple string result.
// It simplifies interaction by abstracting the arguments map and result parsing.
//
// Usage:
//
//	output, err := mcpManager.Call(ctx, "list_directory", "path", "/tmp")
func (m *Manager) Call(ctx context.Context, toolName string, kvArgs ...interface{}) (string, error) {
	if len(kvArgs)%2 != 0 {
		return "", fmt.Errorf("Call requires even number of arguments (key-value pairs)")
	}

	args := make(map[string]interface{})
	for i := 0; i < len(kvArgs); i += 2 {
		key, ok := kvArgs[i].(string)
		if !ok {
			return "", fmt.Errorf("argument key at index %d must be string", i)
		}
		args[key] = kvArgs[i+1]
	}

	result, err := m.ExecuteTool(ctx, toolName, args)
	if err != nil {
		return "", err
	}

	// Handle MCP Error Protocol
	if result.IsError {
		var errMsgs []string
		for _, c := range result.Content {
			if c.Type == "text" {
				errMsgs = append(errMsgs, c.Text)
			}
		}
		if len(errMsgs) > 0 {
			return "", fmt.Errorf("tool error: %s", strings.Join(errMsgs, "\n"))
		}
		return "", fmt.Errorf("tool returned error status")
	}

	// Success - aggregate text content
	var texts []string
	for _, c := range result.Content {
		if c.Type == "text" {
			texts = append(texts, c.Text)
		} else {
			texts = append(texts, fmt.Sprintf("[%s content]", c.Type))
		}
	}

	if len(texts) == 0 {
		return "", nil // or "OK"? No, empty string is faithful to no content.
	}

	return strings.Join(texts, "\n"), nil
}
