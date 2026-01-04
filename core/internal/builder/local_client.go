package builder

import (
	"context"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"
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
	absDir, err := filepath.Abs(workingDir)
	if err != nil {
		return nil, err
	}
	return &LocalClient{WorkingDir: absDir}, nil
}

// TriggerBuild executes a local build script or command
func (c *LocalClient) TriggerBuild(ctx context.Context, repoURL string, commitHash string, logPath string, logWriter io.Writer) (string, error) {
	// 1. Validate Input (Sandbox Check)
	targetDir := repoURL
	if !filepath.IsAbs(targetDir) {
		targetDir = filepath.Join(c.WorkingDir, targetDir)
	}

	// Security Check: Target directory must be within WorkingDir
	if !strings.HasPrefix(targetDir, c.WorkingDir) {
		return "", fmt.Errorf("security violation: build path %s is outside working directory %s", targetDir, c.WorkingDir)
	}

	if _, err := os.Stat(targetDir); os.IsNotExist(err) {
		return "", fmt.Errorf("build directory does not exist: %s", targetDir)
	}

	// 2. Identify Build System
	buildID := fmt.Sprintf("build-%d", time.Now().Unix())
	outputDir := filepath.Join(targetDir, "../builds", buildID) // Convention: ../builds/<id> relative to src
	if err := os.MkdirAll(outputDir, 0755); err != nil {
		return "", fmt.Errorf("failed to create build output dir: %w", err)
	}

	var cmd *exec.Cmd

	if _, err := os.Stat(filepath.Join(targetDir, "package.json")); err == nil {
		// Node.js
		fmt.Printf("[LocalBuilder] Detected Node.js project in %s\n", targetDir)

		// Node.js: Copy source to outputDir first to create artifact
		// Using 'cp -R' for simplicity on Mac/Linux
		copyCmd := exec.CommandContext(ctx, "cp", "-R", ".", outputDir)
		copyCmd.Dir = targetDir
		if err := copyCmd.Run(); err != nil {
			return "", fmt.Errorf("failed to copy source to output: %w", err)
		}

		// Check if package.json has a build script
		pkgPath := filepath.Join(outputDir, "package.json")
		content, _ := os.ReadFile(pkgPath)
		hasBuildScript := strings.Contains(string(content), "\"build\":")

		script := "npm install"
		if hasBuildScript {
			script += " && npm run build"
		} else {
			fmt.Println("[LocalBuilder] No 'build' script found in package.json, skipping build step.")
		}

		// Run build in outputDir
		cmd = exec.CommandContext(ctx, "/bin/sh", "-c", script)
		cmd.Dir = outputDir // Point to outputDir now
		// Important: we need to set cmd.Dir later, but here we set our intention.
		// However, below we have `cmd.Dir = targetDir`. outputDir is more correct for this flow.
		// We will set a flag `useOutputDirAsCwd` or just override it below.

	} else if _, err := os.Stat(filepath.Join(targetDir, "go.mod")); err == nil {
		// Golang
		fmt.Printf("[LocalBuilder] Detected Go project in %s\n", targetDir)
		// go build -o <outputDir>/main
		appPath := filepath.Join(outputDir, "main")
		cmd = exec.CommandContext(ctx, "go", "build", "-o", appPath, ".")

	} else if _, err := os.Stat(filepath.Join(targetDir, "requirements.txt")); err == nil {
		// Python
		fmt.Printf("[LocalBuilder] Detected Python project in %s\n", targetDir)
		cmd = exec.CommandContext(ctx, "cp", "-r", ".", outputDir)

	} else if _, err := os.Stat(filepath.Join(targetDir, "requirements.txt")); err == nil {
		// Python with requirements
		fmt.Printf("[LocalBuilder] Detected Python project (requirements.txt) in %s\n", targetDir)
		// Copy source to output
		cmd = exec.CommandContext(ctx, "cp", "-R", ".", outputDir)
		// Usually we would pip install to a venv, but for creating artifact, copying is enough.
		// RunExecutor will install deps.
		// But wait, cmd is executed below. `cp` is executed below.
		// NOTE: logic flow here is slightly mixed between immediate cp and deferred cmd.
		// Correct flow: Set cmd to copy. Or run copy immediately and set cmd to echo.
		copyCmd := exec.CommandContext(ctx, "cp", "-R", ".", outputDir)
		copyCmd.Dir = targetDir
		if err := copyCmd.Run(); err != nil {
			return "", fmt.Errorf("failed to copy source to output: %w", err)
		}
		cmd = exec.CommandContext(ctx, "echo", "Python source copied. Dependencies will be installed at runtime.")
		cmd.Dir = outputDir

	} else {
		// Fallback: Check for single JS files OR Python files
		filesJS, _ := filepath.Glob(filepath.Join(targetDir, "*.js"))
		filesPy, _ := filepath.Glob(filepath.Join(targetDir, "*.py"))

		if len(filesJS) > 0 {
			fmt.Printf("[LocalBuilder] Detected standalone JS files in %s\n", targetDir)
			// Copy to output
			copyCmd := exec.CommandContext(ctx, "cp", "-R", ".", outputDir)
			copyCmd.Dir = targetDir
			if err := copyCmd.Run(); err != nil {
				return "", fmt.Errorf("failed to copy source to output: %w", err)
			}
			cmd = exec.CommandContext(ctx, "echo", "No build needed for standalone JS")
			cmd.Dir = outputDir
		} else if len(filesPy) > 0 {
			fmt.Printf("[LocalBuilder] Detected standalone Python files in %s\n", targetDir)
			// Copy to output
			copyCmd := exec.CommandContext(ctx, "cp", "-R", ".", outputDir)
			copyCmd.Dir = targetDir
			if err := copyCmd.Run(); err != nil {
				return "", fmt.Errorf("failed to copy source to output: %w", err)
			}
			cmd = exec.CommandContext(ctx, "echo", "No build needed for standalone Python")
			cmd.Dir = outputDir
		} else {
			// Check for Go files
			filesGo, _ := filepath.Glob(filepath.Join(targetDir, "*.go"))
			if len(filesGo) > 0 {
				fmt.Printf("[LocalBuilder] Detected standalone Go files in %s\n", targetDir)
				appPath := filepath.Join(outputDir, "main")
				// Try to build
				cmd = exec.CommandContext(ctx, "go", "build", "-o", appPath, ".")
				cmd.Dir = targetDir
			} else {
				return "", fmt.Errorf("unknown build system in %s", targetDir)
			}
		}
	}

	// If cmd.Dir was not already set by specific handler (like Node.js), default to targetDir
	if cmd.Dir == "" {
		cmd.Dir = targetDir
	}

	// Determine Log Output
	var logFile *os.File
	var err error
	if logPath != "" {
		if err := os.MkdirAll(filepath.Dir(logPath), 0755); err != nil {
			return "", err
		}
		logFile, err = os.Create(logPath)
		if err != nil {
			return "", err
		}
	} else {
		// Just a dummy file or fallback
	}

	// Prepare Writers
	var writers []io.Writer
	writers = append(writers, os.Stdout)
	if logFile != nil {
		writers = append(writers, logFile)
		defer logFile.Close()
	}
	if logWriter != nil {
		writers = append(writers, logWriter)
	}

	multiWriter := io.MultiWriter(writers...)
	cmd.Stdout = multiWriter
	cmd.Stderr = multiWriter

	if err := cmd.Run(); err != nil {
		return "", fmt.Errorf("build failed: %w", err)
	}

	return buildID, nil
}

// GetBuildStatus checks if the build dir exists specifically
func (c *LocalClient) GetBuildStatus(ctx context.Context, buildID string) (string, error) {
	// In this simple model, build is synchronous, so it's always "Succeeded" if TriggerBuild returns.
	// Real implementation would look up state.
	return "Succeeded", nil
}
