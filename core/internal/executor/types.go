package executor

import (
	"context"

	"github.com/sjhoeksma/druppie/core/internal/model"
)

// Executor defines the interface for executing a single step
type Executor interface {
	Execute(ctx context.Context, step model.Step, outputChan chan<- string) error
	CanHandle(action string) bool
}
