package executor

import (
	"errors"

	"github.com/sjhoeksma/druppie/core/internal/builder"
	"github.com/sjhoeksma/druppie/core/internal/mcp"
)

// Dispatcher selects the correct executor for a step
type Dispatcher struct {
	executors []Executor
}

func NewDispatcher(buildEngine builder.BuildEngine, mcpManager *mcp.Manager) *Dispatcher {
	return &Dispatcher{
		executors: []Executor{
			&MCPExecutor{Manager: mcpManager}, // Check MCP tools first? Or specific executors first?
			// MCP tools are dynamic, so placing them high allows overriding.
			// But specific actions "create_code" etc should probably take precedence if they conflict.
			// However, "create_code" is unlikely to be an MCP tool name unless intentional override.

			&AudioCreatorExecutor{},
			&VideoCreatorExecutor{},
			&ImageCreatorExecutor{},              // Start valid Image Executor
			&FileReaderExecutor{},                // File Reader
			&DeveloperExecutor{},                 // Developer (Code Creator)
			&BuildExecutor{Builder: buildEngine}, // Helper for building code
			&RunExecutor{Builder: buildEngine},   // Helper for running code
			&ComplianceExecutor{},                // Compliance/Approval Handler
			// Legacy/Fallback last
			&SceneCreatorExecutor{},
		},
	}
}

func (d *Dispatcher) GetExecutor(action string) (Executor, error) {
	for _, e := range d.executors {
		if e.CanHandle(action) {
			return e, nil
		}
	}
	// Fallback? Or return error
	return nil, errors.New("no executor found for action: " + action)
}
