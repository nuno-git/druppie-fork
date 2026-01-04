package builder

import (
	"context"
	"io"
)

// BuildEngine defines the interface for triggering builds
type BuildEngine interface {
	TriggerBuild(ctx context.Context, repoURL string, commitHash string, logPath string, logWriter io.Writer) (string, error)
	GetBuildStatus(ctx context.Context, buildID string) (string, error)
}
