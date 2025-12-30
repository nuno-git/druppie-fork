package builder

import (
	"context"
	"fmt"
	"os/exec"
)

// LocalClient implements BuildEngine for local builds
type LocalClient struct {
	WorkingDir string
}

// NewLocalClient creates a new Local client
func NewLocalClient(workingDir string) (*LocalClient, error) {
	if workingDir == "" {
		workingDir = "."
	}
	return &LocalClient{WorkingDir: workingDir}, nil
}

// TriggerBuild executes a local build script or command
// For simplicity, this assumes a "build.sh" exists or runs "go build ./..." if Go
func (c *LocalClient) TriggerBuild(ctx context.Context, repoURL string, commitHash string) (string, error) {
	// 1. In a real scenario, this would clone the repo to c.WorkingDir/builds/<id>
	// 2. Checkout the commit
	// 3. Run build

	// For this prototype, we'll just log that we are building
	fmt.Printf("[LocalBuilder] Mocking build for %s @ %s in %s\n", repoURL, commitHash, c.WorkingDir)

	// Example of running a command
	cmd := exec.CommandContext(ctx, "echo", "Building locally...")
	cmd.Dir = c.WorkingDir
	if output, err := cmd.CombinedOutput(); err != nil {
		return "", fmt.Errorf("local build failed: %v, output: %s", err, string(output))
	}

	return fmt.Sprintf("local-build-%s", commitHash), nil
}

// GetBuildStatus mocks status check
func (c *LocalClient) GetBuildStatus(ctx context.Context, buildID string) (string, error) {
	return "Succeeded", nil
}
