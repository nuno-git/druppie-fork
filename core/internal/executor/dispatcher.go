package executor

import (
	"errors"
	"strings"

	"github.com/sjhoeksma/druppie/core/internal/builder"
	"github.com/sjhoeksma/druppie/core/internal/llm"
	"github.com/sjhoeksma/druppie/core/internal/mcp"
	"github.com/sjhoeksma/druppie/core/internal/registry"
)

// Dispatcher selects the correct executor for a step
type Dispatcher struct {
	executors []Executor
}

func NewDispatcher(buildEngine builder.BuildEngine, mcpManager *mcp.Manager, llmProvider llm.Provider, reg *registry.Registry) *Dispatcher {
	stdCtx := &StandardContext{
		MCPManager:      mcpManager,
		StandardActions: &StandardActions{},
	}

	return &Dispatcher{
		executors: []Executor{
			&MCPExecutor{Manager: mcpManager}, // Check MCP tools first? Or specific executors first?
			// MCP tools are dynamic, so placing them high allows overriding.
			// But specific actions "create_repo" etc should probably take precedence if they conflict.
			// However, "create_repo" is unlikely to be an MCP tool name unless intentional override.

			&AudioCreatorExecutor{LLM: llmProvider},
			&VideoCreatorExecutor{LLM: llmProvider},
			&ImageCreatorExecutor{LLM: llmProvider},                   // Start valid Image Executor
			&FileReaderExecutor{},                                     // File Reader
			&DeveloperExecutor{},                                      // Developer (Code Creator)
			&BuildExecutor{Builder: buildEngine},                      // Helper for building code
			&RunExecutor{Builder: buildEngine},                        // Helper for running code
			&PluginExecutor{MCPManager: mcpManager},                   // Plugin testing and promotion
			&ComplianceExecutor{LLM: llmProvider, Registry: reg},      // Compliance/Approval Handler
			&BusinessAnalystExecutor{LLM: llmProvider, Registry: reg}, // Business Analyst Handler
			&StandardExecutor{StdCtx: stdCtx},                         // Standard/Infra Handler (Replaces InfrastructureExecutor)
			&DataScientistExecutor{LLM: llmProvider, Registry: reg},   // Data Scientist Handler
			&ArchitectExecutor{LLM: llmProvider, Registry: reg},       // Architect Handler
			&ContentMergerExecutor{},                                  // Final Video Merger
			// Legacy/Fallback last
			&SceneCreatorExecutor{},
		},
	}
}

func (d *Dispatcher) GetExecutor(action string) (Executor, error) {
	// Normalize action to snake_case to match user requirement
	// e.g. "text-to-speech" -> "text_to_speech"
	action = strings.ReplaceAll(action, "-", "_")
	for _, e := range d.executors {
		if e.CanHandle(action) {
			return e, nil
		}
	}
	// Fallback? Or return error
	return nil, errors.New("no executor found for action: " + action)
}
