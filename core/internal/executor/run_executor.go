package executor

import (
	"bufio"
	"context"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"time"

	"github.com/docker/docker/api/types/container"
	"github.com/docker/docker/api/types/image"
	"github.com/docker/docker/client"
	"github.com/docker/docker/pkg/stdcopy"
	"github.com/sjhoeksma/druppie/core/internal/builder"
	"github.com/sjhoeksma/druppie/core/internal/logging"
	"github.com/sjhoeksma/druppie/core/internal/model"
	"github.com/sjhoeksma/druppie/core/internal/paths"
)

// RunExecutor handles "run_code" actions
type RunExecutor struct {
	Builder builder.BuildEngine
}

func (e *RunExecutor) CanHandle(action string) bool {
	return action == "run_code"
}

func (e *RunExecutor) Execute(ctx context.Context, step model.Step, outputChan chan<- string) error {
	outputChan <- "RunExecutor: Initializing..."

	// Extract params
	buildID, _ := step.Params["build_id"].(string)
	cmdStr, _ := step.Params["command"].(string)

	// If buildID is the placeholder, treat it as empty for now to allow auto-detection
	if buildID == "${BUILD_ID}" || buildID == "BUILD_ID" {
		buildID = ""
	}

	planID := ""
	if p, ok := step.Params["plan_id"].(string); ok {
		planID = p
	} else if p, ok := step.Params["_plan_id"].(string); ok {
		planID = p
	}

	// Resolve Artifact Path
	var artifactPath string
	buildsDir, _ := paths.ResolvePath(".druppie", "plans", planID, "builds")

	if planID != "" {
		if buildID != "" {
			artifactPath = filepath.Join(buildsDir, buildID)
		}

		// Validation
		isValid := false
		if artifactPath != "" {
			if entries, err := os.ReadDir(artifactPath); err == nil && len(entries) > 0 {
				isValid = true
			}
		}

		// Fallback: Find latest build
		if !isValid {
			if buildID != "" {
				outputChan <- fmt.Sprintf("Warning: buildID '%s' not found or empty. Searching for latest build...", buildID)
			}
			entries, err := os.ReadDir(buildsDir)
			var latestDir string
			var latestTime time.Time
			if err == nil {
				for _, e := range entries {
					if e.IsDir() && strings.HasPrefix(e.Name(), "build-") {
						info, err := e.Info()
						if err == nil && info.ModTime().After(latestTime) {
							latestTime = info.ModTime()
							latestDir = e.Name()
						}
					}
				}
			}
			if latestDir != "" {
				artifactPath = filepath.Join(buildsDir, latestDir)
				outputChan <- fmt.Sprintf("Auto-detected latest build: %s", latestDir)
			}
		}

		// Last Resort: Source Directory
		if artifactPath == "" {
			srcDir, _ := paths.ResolvePath(".druppie", "plans", planID, "src")
			if entries, err := os.ReadDir(srcDir); err == nil && len(entries) > 0 {
				artifactPath = srcDir
				outputChan <- "No build artifacts found. Falling back to source directory for execution."
			}
		}
	}

	if artifactPath == "" && cmdStr == "" {
		return fmt.Errorf("run_code requires 'build_id' or 'command', and no artifacts were found in context")
	}

	// Create Docker Client if needed
	var cli *client.Client
	if !e.Builder.IsLocal() {
		var err error
		cli, err = client.NewClientWithOpts(client.FromEnv, client.WithAPIVersionNegotiation())
		if err != nil {
			return fmt.Errorf("failed to create docker client: %w", err)
		}
		defer cli.Close()
	}

	// Detect Command/Image
	var imageRef string
	var cmd []string

	if cmdStr != "" {
		cmd = strings.Fields(cmdStr)
		imageRef = "ubuntu:latest" // Default
	}

	// Helper to check file existence
	fileExists := func(name string) bool {
		_, err := os.Stat(filepath.Join(artifactPath, name))
		return err == nil
	}

	if len(cmd) == 0 {
		// Auto-detection logic based on files
		if fileExists("package.json") {
			imageRef = "node:20-alpine"
			cmd = []string{"npm", "start", "--silent"}
		} else if fileExists("go.mod") || fileExists("main") {
			imageRef = "ubuntu:latest" // Executable
			cmd = []string{"./main"}
			if !fileExists("main") && fileExists("app") {
				cmd = []string{"./app"}
			}
		} else if fileExists("requirements.txt") || fileExists("main.py") {
			imageRef = "python:3.11-slim"
			cmd = []string{"python", "main.py"}
		} else {
			// Fallback heuristics
			jsFiles, _ := filepath.Glob(filepath.Join(artifactPath, "*.js"))
			pyFiles, _ := filepath.Glob(filepath.Join(artifactPath, "*.py"))
			if len(jsFiles) > 0 {
				imageRef = "node:20-alpine"
				cmd = []string{"node", filepath.Base(jsFiles[0])}
			} else if len(pyFiles) > 0 {
				imageRef = "python:3.11-slim"
				cmd = []string{"python", filepath.Base(pyFiles[0])}
			}
		}
	} else {
		// Command refinement (e.g. mapping "python" to image)
		switch cmd[0] {
		case "python", "python3":
			imageRef = "python:3.11-slim"
		case "node", "npm":
			imageRef = "node:20-alpine"
		case "go":
			imageRef = "golang:1.21"
		}
	}

	// Local Execution Branch
	if e.Builder.IsLocal() {
		outputChan <- fmt.Sprintf("Running command locally in %s: %v", artifactPath, cmd)
		lcmd := exec.CommandContext(ctx, cmd[0], cmd[1:]...)
		lcmd.Dir = artifactPath

		// Capture output
		pr, pw := io.Pipe()
		lcmd.Stdout = pw
		lcmd.Stderr = pw

		var wg sync.WaitGroup
		wg.Add(1)
		var sb strings.Builder

		// Unified Log Writer for Local Execution
		var writers []io.Writer
		if planID != "" {
			writers = append(writers, logging.NewLogWriter(planID))
		}
		// We capture outputChan in passing via `scanner` below, but for PERSISTENCE we need the file writer.
		// Wait, the scanner reads from `pr`. So `lcmd` writes to `pw`.
		// If we want persistence, we should split `pw`.
		// Actually, simpler: read line by line, send to outputChan AND logFile.
		// BUT `logging.NewLogWriter` is thread safe.

		go func() {
			defer wg.Done()
			scanner := bufio.NewScanner(pr)
			// Optional: Use file writer here too?
			// Instead of splitting the pipe, we can just write to file writer inside this loop.

			var fileWriter io.Writer
			if planID != "" {
				fileWriter = logging.NewLogWriter(planID)
			}

			for scanner.Scan() {
				line := scanner.Text()
				outputChan <- line
				if fileWriter != nil {
					fileWriter.Write([]byte(line + "\n"))
				}
				sb.WriteString(line + "\n")
			}
		}()

		if err := lcmd.Start(); err != nil {
			pw.Close()
			wg.Wait()
			return fmt.Errorf("failed to start local process: %w", err)
		}
		err := lcmd.Wait()
		pw.Close()
		wg.Wait()

		if sb.Len() > 0 {
			outputChan <- fmt.Sprintf("RESULT_CONSOLE_OUTPUT=%s", sb.String())
		}
		if err != nil {
			return fmt.Errorf("local process exited with error: %w", err)
		}
		return nil
	}

	// Docker Execution Branch
	outputChan <- fmt.Sprintf("Running container %s with command: %v", imageRef, cmd)

	// Pull Image
	reader, err := cli.ImagePull(ctx, imageRef, image.PullOptions{})
	if err == nil {
		io.Copy(io.Discard, reader)
		reader.Close()
	} else {
		outputChan <- fmt.Sprintf("Warning: Failed to pull image %s (might exist locally): %v", imageRef, err)
	}

	// Container Config
	containerConfig := &container.Config{
		Image:        imageRef,
		Cmd:          cmd,
		WorkingDir:   "/workspace",
		AttachStdout: true,
		AttachStderr: true,
	}
	hostConfig := &container.HostConfig{
		Binds: []string{
			fmt.Sprintf("%s:/workspace", artifactPath),
		},
	}

	resp, err := cli.ContainerCreate(ctx, containerConfig, hostConfig, nil, nil, "")
	if err != nil {
		return fmt.Errorf("failed to create run container: %w", err)
	}

	if err := cli.ContainerStart(ctx, resp.ID, container.StartOptions{}); err != nil {
		return fmt.Errorf("failed to start run container: %w", err)
	}

	// Stream Output
	out, err := cli.ContainerLogs(ctx, resp.ID, container.LogsOptions{ShowStdout: true, ShowStderr: true, Follow: true})
	var wg sync.WaitGroup
	if err == nil {
		r, w := io.Pipe()
		wg.Add(2)

		// Create unified writer: Pipe (for UI/Scanner) + File (for execution.log)
		var writers []io.Writer
		writers = append(writers, w)
		if planID != "" {
			writers = append(writers, logging.NewLogWriter(planID))
		}
		multiWriter := io.MultiWriter(writers...)

		go func() {
			defer wg.Done()
			stdcopy.StdCopy(multiWriter, multiWriter, out)
			w.Close()
			out.Close()
		}()

		go func() {
			defer wg.Done()
			var sb strings.Builder
			scanner := bufio.NewScanner(r)
			for scanner.Scan() {
				line := scanner.Text()
				// Send to UI
				outputChan <- line
				sb.WriteString(line + "\n")
			}
			if sb.Len() > 0 {
				outputChan <- fmt.Sprintf("RESULT_CONSOLE_OUTPUT=%s", sb.String())
			}
		}()
	}

	// Wait for container
	statusCh, errCh := cli.ContainerWait(ctx, resp.ID, container.WaitConditionNotRunning)
	var exitCode int64
	select {
	case err := <-errCh:
		if err != nil {
			return fmt.Errorf("error waiting for run container: %w", err)
		}
	case status := <-statusCh:
		exitCode = status.StatusCode
	}

	wg.Wait()

	// Cleanup
	cleanupCtx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	_ = cli.ContainerRemove(cleanupCtx, resp.ID, container.RemoveOptions{Force: true})

	if exitCode != 0 {
		return fmt.Errorf("container exited with non-zero status: %d", exitCode)
	}

	outputChan <- "Execution completed."
	return nil
}
