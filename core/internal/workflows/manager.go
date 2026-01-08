package workflows

import (
	"context"

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
