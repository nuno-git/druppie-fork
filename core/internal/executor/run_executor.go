package executor

import (
	"bufio"
	"context"
	"os/exec"
	"sync"

	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/docker/docker/api/types/container"
	"github.com/docker/docker/api/types/image"
	"github.com/docker/docker/client"
	"github.com/docker/docker/pkg/stdcopy"
	"github.com/sjhoeksma/druppie/core/internal/builder"
	"github.com/sjhoeksma/druppie/core/internal/model"
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
	// "build_id" from previous step result?
	// "executable_path"?
	// "command"?

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

	if buildID == "" && cmdStr == "" {
		// We still try to proceed because the auto-detection logic below might find a build
		// But if we are really stuck, we'll return the error later or during detection
	}

	// If we have buildID, we need to find where it is.
	// This implies we know the project root.
	// HACK: We need PROJECT_ROOT to resolve ".druppie/plans/..."
	// We can guess it from working dir or passed context.
	// Since we are running in the 'druppie' binary, CWD is often project root.
	cwd, _ := os.Getwd()

	// Construct path to build artifacts
	// .druppie/plans/<plan-id>/builds/<build-id>
	// But how do we know plan-id if not passed? We inject `_plan_id`.

	var artifactPath string
	buildsDir := filepath.Join(cwd, ".druppie", "plans", planID, "builds")

	if planID != "" {
		if buildID != "" {
			artifactPath = filepath.Join(buildsDir, buildID)
		}

		// Validation: Check if specific artifactPath exists and is non-empty
		isValid := false
		if artifactPath != "" {
			if entries, err := os.ReadDir(artifactPath); err == nil && len(entries) > 0 {
				isValid = true
			}
		}

		// Fallback: Find latest build if invalid
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
						if err == nil {
							if info.ModTime().After(latestTime) {
								latestTime = info.ModTime()
								latestDir = e.Name()
							}
						}
					}
				}
			}

			if latestDir != "" {
				artifactPath = filepath.Join(buildsDir, latestDir)
				outputChan <- fmt.Sprintf("Auto-detected latest build: %s", latestDir)
			}
		}

		if artifactPath == "" {
			// LAST RESORT: Try the source directory
			srcDir := filepath.Join(cwd, ".druppie", "plans", planID, "src")
			if entries, err := os.ReadDir(srcDir); err == nil && len(entries) > 0 {
				artifactPath = srcDir
				outputChan <- "No build artifacts found. Falling back to source directory for execution."
			}
		}
	}

	if artifactPath == "" && cmdStr == "" {
		return fmt.Errorf("run_code requires 'build_id' or 'command', and no artifacts were found in context")
	}

	var cli *client.Client
	if !e.Builder.IsLocal() {
		var err error
		cli, err = client.NewClientWithOpts(client.FromEnv, client.WithAPIVersionNegotiation())
		if err != nil {
			return fmt.Errorf("failed to create docker client: %w", err)
		}
	}

	// Determine Run Strategy
	// 1. Is there a docker image built? (Not implemented in builder yet)
	// 2. Is there an executable?
	// We just run a container similar to builder, mount the artifact path, and run the command.

	imageRef := "ubuntu:latest" // Fallback
	var cmd []string

	// Debug: List files in artifactPath
	if entries, err := os.ReadDir(artifactPath); err == nil {
		var files []string
		for _, e := range entries {
			files = append(files, e.Name())
		}
		outputChan <- fmt.Sprintf("Checking artifacts in %s: %v", artifactPath, files)
	} else {
		outputChan <- fmt.Sprintf("Failed to list artifacts in %s: %v", artifactPath, err)
	}

	// Detect artifact type
	if _, err := os.Stat(filepath.Join(artifactPath, "main")); err == nil {
		// Go binary (preferred)
		imageRef = "ubuntu:latest"
		cmd = []string{"./main"}
	} else if _, err := os.Stat(filepath.Join(artifactPath, "app")); err == nil {
		// Go binary (legacy/alternate)
		imageRef = "ubuntu:latest"
		cmd = []string{"./app"}
	} else if _, err := os.Stat(filepath.Join(artifactPath, "main.py")); err == nil {
		// Python root
		imageRef = "python:3.11-slim"
		cmd = []string{"python", "main.py"}
	} else if _, err := os.Stat(filepath.Join(artifactPath, "src/main.py")); err == nil {
		// Python src (fallback)
		imageRef = "python:3.11-slim"
		cmd = []string{"python", "src/main.py"}
	} else if _, err := os.Stat(filepath.Join(artifactPath, "package.json")); err == nil {
		// Node
		imageRef = "node:20-alpine"
		// If we ran build, maybe main is in dist/index.js? Or start script?
		cmd = []string{"npm", "start", "--silent"}
	} else {
		// Fallback: Check for *.js
		jsFiles, _ := filepath.Glob(filepath.Join(artifactPath, "*.js"))
		if len(jsFiles) > 0 {
			imageRef = "node:20-alpine"
			// Use the first JS file found if no command specified
			baseName := filepath.Base(jsFiles[0])
			cmd = []string{"node", baseName}
		} else {
			// Fallback: Check for *.py
			pyFiles, _ := filepath.Glob(filepath.Join(artifactPath, "*.py"))

			if len(pyFiles) > 0 && cmdStr == "" {
				imageRef = "python:3.11-slim"
				baseName := filepath.Base(pyFiles[0])
				cmd = []string{"python", baseName}
			} else if cmdStr != "" {
				// Intelligent Image Selection based on command
				cmd = strings.Fields(cmdStr)

				// HEURISTIC: Binary name mismatch (main vs app)
				if len(cmd) > 0 && (cmd[0] == "./main" || cmd[0] == "main" || cmd[0] == "./app" || cmd[0] == "app") {
					target := cmd[0]
					if !strings.HasPrefix(target, "./") && !strings.HasPrefix(target, "npm") && !strings.HasPrefix(target, "python") {
						target = "./" + target
					}
					// If specified file DOES NOT exist
					if _, err := os.Stat(filepath.Join(artifactPath, target)); os.IsNotExist(err) {
						// Look for the other one
						other := "app"
						if strings.Contains(target, "app") {
							other = "main"
						}
						if _, errOther := os.Stat(filepath.Join(artifactPath, other)); errOther == nil {
							outputChan <- fmt.Sprintf("Correction: binary '%s' not found, mapping to '%s'", target, other)
							if strings.HasPrefix(target, "./") {
								cmd[0] = "./" + other
							} else {
								cmd[0] = other
							}
						}
					}
				}

				// HEURISTIC: If command tries to access src/ but it doesn't exist, strip it
				// Example: "python src/hello.py" -> "python hello.py"
				for i, arg := range cmd {
					if strings.HasPrefix(arg, "src/") || strings.HasPrefix(arg, "src\\") {
						possiblePath := strings.TrimPrefix(strings.TrimPrefix(arg, "src/"), "src\\")
						if _, err := os.Stat(filepath.Join(artifactPath, possiblePath)); err == nil {
							// If the file exists without src/ prefix, but NOT with it
							if _, errSrc := os.Stat(filepath.Join(artifactPath, arg)); os.IsNotExist(errSrc) {
								outputChan <- fmt.Sprintf("Correction: stripping 'src/' prefix from command argument: %s", arg)
								cmd[i] = possiblePath
							}
						}
					}
				}

				if len(cmd) > 0 {
					switch cmd[0] {
					case "python", "python3":
						imageRef = "python:3.11-slim"
					case "node", "npm":
						imageRef = "node:20-alpine"
					case "go":
						imageRef = "golang:1.21"
					default:
						imageRef = "ubuntu:latest"
					}
				} else {
					imageRef = "ubuntu:latest"
				}

				// Clean up npm command log noise
				if len(cmd) > 0 && cmd[0] == "npm" {
					if len(cmd) > 1 && (cmd[1] == "start" || cmd[1] == "run") {
						// Add --silent if not present
						hasSilent := false
						for _, arg := range cmd {
							if arg == "--silent" || arg == "-s" {
								hasSilent = true
								break
							}
						}
						if !hasSilent {
							cmd = append(cmd, "--silent")
						}
					}
				}
			}
		}
	}

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
		go func() {
			defer wg.Done()
			scanner := bufio.NewScanner(pr)
			count := 0
			const maxLines = 100
			for scanner.Scan() {
				line := scanner.Text()
				outputChan <- line
				if count < maxLines {
					if count > 0 {
						sb.WriteString("\n")
					}
					sb.WriteString(line)
					count++
				}
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

		// Emit accumulated output as result
		result := sb.String()
		if result != "" {
			outputChan <- fmt.Sprintf("RESULT_CONSOLE_OUTPUT=%s", result)
		}

		if err != nil {
			return fmt.Errorf("local process exited with error: %w", err)
		}
		return nil
	}

	outputChan <- fmt.Sprintf("Pulling image %s...", imageRef)
	reader, err := cli.ImagePull(ctx, imageRef, image.PullOptions{})
	if err != nil {
		return fmt.Errorf("failed to pull image %s: %w", imageRef, err)
	}
	io.Copy(io.Discard, reader)
	reader.Close()

	outputChan <- fmt.Sprintf("Running container with command: %v", cmd)

	// Mount artifact path to /workspace
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
		go func() {
			defer wg.Done()
			stdcopy.StdCopy(w, w, out)
			w.Close()
			out.Close()
		}()

		go func() {
			defer wg.Done()
			var sb strings.Builder
			scanner := bufio.NewScanner(r)
			count := 0
			// Limit capture to avoid excessive memory usage for long running processes
			const maxLines = 100

			for scanner.Scan() {
				line := scanner.Text()
				outputChan <- line

				if count < maxLines {
					if count > 0 {
						sb.WriteString("\n")
					}
					sb.WriteString(line)
					count++
				}
			}
			if err := scanner.Err(); err != nil {
				outputChan <- fmt.Sprintf("Error reading stream: %v", err)
			}

			// Emit accumulated output as result
			result := sb.String()
			if result != "" {
				outputChan <- fmt.Sprintf("RESULT_CONSOLE_OUTPUT=%s", result)
			}
		}()
	}

	// Wait
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

	// Wait for output goroutines to finish
	wg.Wait()

	// Cleanup with detached context to ensure it runs even on cancellation
	cleanupCtx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	_ = cli.ContainerRemove(cleanupCtx, resp.ID, container.RemoveOptions{Force: true})

	if exitCode != 0 {
		return fmt.Errorf("container exited with non-zero status: %d", exitCode)
	}

	outputChan <- "Execution completed."
	return nil
}
