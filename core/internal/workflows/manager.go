package workflows

import (
	"context"
	"fmt"

	"github.com/sjhoeksma/druppie/core/internal/executor"
	"github.com/sjhoeksma/druppie/core/internal/llm"
	"github.com/sjhoeksma/druppie/core/internal/model"
	"github.com/sjhoeksma/druppie/core/internal/store"
)

// WorkflowContext carries the dependencies needed by a workflow
type WorkflowContext struct {
	Ctx               context.Context
	LLM               llm.Provider
	Dispatcher        *executor.Dispatcher
	Store             store.Store
	PlanID            string
	OutputChan        chan<- string
	InputChan         <-chan string
	UpdateStatus      func(status string)
	UpdateTokenUsage  func(usage model.TokenUsage)
	AppendStep        func(step model.Step) int // Callback to add a executed step to the plan log
	FindCompletedStep func(action string, paramKey string, paramValue interface{}) *model.Step
	GetAgent          func(id string) (model.AgentDefinition, error)
}

// Workflow defines the interface for a hard-coded process
type Workflow interface {
	Name() string
	Run(wc *WorkflowContext, initialPrompt string) error
}

type Manager struct {
	workflows map[string]Workflow
}

func NewManager() *Manager {
	m := &Manager{
		workflows: make(map[string]Workflow),
	}
	// Load all registered workflows
	RegisterAll(m)
	return m
}

func (m *Manager) Register(w Workflow) {
	m.workflows[w.Name()] = w
}

func (m *Manager) GetWorkflow(name string) (Workflow, bool) {
	w, ok := m.workflows[name]
	return w, ok
}

// CallLLM executes a generation request and returns the response and specific usage (as pointer).
// It does NOT update the global plan usage automatically; the caller must attach it to a Step or call UpdateTokenUsage.
// opts[0] (optional) specifies the provider name (e.g. "gemini", "ollama").
func (wc *WorkflowContext) CallLLM(prompt string, systemPrompt string, opts ...string) (string, *model.TokenUsage, error) {
	providerName := ""
	if len(opts) > 0 {
		providerName = opts[0]
	}

	if providerName != "" {
		if mgr, ok := wc.LLM.(*llm.Manager); ok {
			resp, usage, err := mgr.GenerateWithProvider(wc.Ctx, providerName, prompt, systemPrompt)
			if wc.Store != nil {
				_ = wc.Store.LogInteraction(wc.PlanID, "Workflow ("+systemPrompt+") ["+providerName+"]",
					fmt.Sprintf("--- PROMPT ---\n%s\n--- END PROMPT ---", prompt),
					fmt.Sprintf("--- RESPONSE ---\n%s\n--- END RESPONSE ---", resp))
			}
			if err != nil {
				return "", nil, err
			}
			return resp, &usage, nil
		}
		return "", nil, fmt.Errorf("provider selection '%s' failed: underlying LLM is not a Manager", providerName)
	}

	resp, usage, err := wc.LLM.Generate(wc.Ctx, prompt, systemPrompt)
	if wc.Store != nil {
		_ = wc.Store.LogInteraction(wc.PlanID, "Workflow ("+systemPrompt+")",
			fmt.Sprintf("--- PROMPT ---\n%s\n--- END PROMPT ---", prompt),
			fmt.Sprintf("--- RESPONSE ---\n%s\n--- END RESPONSE ---", resp))
	}
	if err != nil {
		return "", nil, err
	}
	return resp, &usage, nil
}
