package executor

import (
	"errors"

	"github.com/sjhoeksma/druppie/core/internal/builder"
)

// Dispatcher selects the correct executor for a step
type Dispatcher struct {
	executors []Executor
}

func NewDispatcher(buildEngine builder.BuildEngine) *Dispatcher {
	return &Dispatcher{
		executors: []Executor{
			&AudioCreatorExecutor{},
			&VideoCreatorExecutor{},
			&ImageCreatorExecutor{},              // Start valid Image Executor
			&FileReaderExecutor{},                // File Reader
			&DeveloperExecutor{},                 // Developer (Code Creator)
			&BuildExecutor{Builder: buildEngine}, // Helper for building code
			&RunExecutor{},                       // Helper for running code
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
