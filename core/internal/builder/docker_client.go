package builder

import (
	"context"
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
)

// DockerClient implements BuildEngine using Docker containers
type DockerClient struct {
	WorkingDir string
	Client     *client.Client
}

// NewDockerClient creates a new Docker client
func NewDockerClient(workingDir string) (*DockerClient, error) {
	cli, err := client.NewClientWithOpts(client.FromEnv, client.WithAPIVersionNegotiation())
	if err != nil {
		return nil, fmt.Errorf("failed to create docker client: %w", err)
	}

	if workingDir == "" {
		workingDir = "."
	}
	absDir, err := filepath.Abs(workingDir)
	if err != nil {
		return nil, err
	}

	return &DockerClient{
		WorkingDir: absDir,
		Client:     cli,
	}, nil
}

// TriggerBuild runs a build inside a container
func (c *DockerClient) TriggerBuild(ctx context.Context, repoURL string, commitHash string, logPath string, logWriter io.Writer) (string, error) {
	// 1. Path Resolution & Security
	targetDir := repoURL
	if !filepath.IsAbs(targetDir) {
		// If repoURL starts with .druppie/..., and WorkingDir is /repo-root,
		// then Join(WorkingDir, targetDir) IS what we want.
		// BUT we should verify if targetDir accidentally contains WorkingDir prefix already
		// or if we need to resolve against CWD if WorkingDir is not set to root.

		targetDir = filepath.Join(c.WorkingDir, targetDir)
	}
	// Sanity Check: Ensure targetDir is inside WorkingDir
	if !strings.HasPrefix(targetDir, c.WorkingDir) {
		return "", fmt.Errorf("security violation: path %s outside workspace", targetDir)
	}

	// 2. Prepare Output Directory
	buildID := fmt.Sprintf("build-%d", time.Now().Unix())
	outputDir := filepath.Join(targetDir, "../builds", buildID)
	if err := os.MkdirAll(outputDir, 0755); err != nil {
		return "", fmt.Errorf("failed to create output dir: %w", err)
	}

	// 3. Determine Build Strategy
	var imageRef string
	var commands []string

	// Check for files to determine Language
	if _, err := os.Stat(filepath.Join(targetDir, "package.json")); err == nil {
		imageRef = "node:20-alpine"

		// Check if package.json has a build script
		pkgPath := filepath.Join(targetDir, "package.json")
		content, _ := os.ReadFile(pkgPath)
		hasBuildScript := strings.Contains(string(content), "\"build\":")

		if hasBuildScript {
			commands = []string{"/bin/sh", "-c", "npm install && npm run build && cp -r . ../builds/" + buildID}
		} else {
			// No build script - just install and copy
			commands = []string{"/bin/sh", "-c", "npm install && cp -r . ../builds/" + buildID}
		}
	} else if _, err := os.Stat(filepath.Join(targetDir, "go.mod")); err == nil {
		imageRef = "golang:1.24-alpine"
		// Go builds to the mounted output dir
		// We need to be careful with paths inside the container
		commands = []string{"/bin/sh", "-c", "go build -o ../builds/" + buildID + "/main ."}
	} else if _, err := os.Stat(filepath.Join(targetDir, "requirements.txt")); err == nil {
		imageRef = "python:3.11-slim"
		// Python often doesn't "build" binaries, but let's assume we want to prep dependencies or artifacts
		// A simple 'cp' might be enough for this proof of concept, or running a setup script
		// pip install -r requirements.txt --target ../builds/<id>/deps
		commands = []string{"/bin/sh", "-c", "pip install -r requirements.txt --target ../builds/" + buildID + "/deps && cp -r . ../builds/" + buildID + "/src"}
	} else {
		// Fallback: Check for standalone files
		pyFiles, _ := filepath.Glob(filepath.Join(targetDir, "*.py"))
		goFiles, _ := filepath.Glob(filepath.Join(targetDir, "*.go"))
		jsFiles, _ := filepath.Glob(filepath.Join(targetDir, "*.js"))

		if len(pyFiles) > 0 {
			// Standalone Python file - just copy to output
			imageRef = "python:3.11-slim"
			commands = []string{"/bin/sh", "-c", "cp -r . ../builds/" + buildID}
		} else if len(goFiles) > 0 {
			// Standalone Go file - build it
			imageRef = "golang:1.24-alpine"
			commands = []string{"/bin/sh", "-c", "go build -o ../builds/" + buildID + "/main ."}
		} else if len(jsFiles) > 0 {
			// Standalone JS file - copy
			imageRef = "node:20-alpine"
			commands = []string{"/bin/sh", "-c", "cp -r . ../builds/" + buildID}
		} else {
			return "", fmt.Errorf("unknown project type in %s", targetDir)
		}
	}

	// 4. Pull Image (if needed)
	// Use simplified pull (reader needs to be closed/read)
	reader, err := c.Client.ImagePull(ctx, imageRef, image.PullOptions{})
	if err != nil {
		return "", fmt.Errorf("failed to pull image %s: %w", imageRef, err)
	}
	io.Copy(io.Discard, reader)
	reader.Close()

	// 5. Create Container
	// Mount the ENTIRE WorkingDir to /workspace so relative paths work (like ../builds)
	// We'll set WorkingDir inside container to /workspace/<relative-path-to-target>
	relTarget, _ := filepath.Rel(c.WorkingDir, targetDir)
	containerWorkDir := filepath.Join("/workspace", relTarget)

	resp, err := c.Client.ContainerCreate(ctx, &container.Config{
		Image:        imageRef,
		Cmd:          commands,
		WorkingDir:   containerWorkDir,
		AttachStdout: true,
		AttachStderr: true,
	}, &container.HostConfig{
		Binds: []string{
			// Mount host working dir to /workspace
			fmt.Sprintf("%s:/workspace", c.WorkingDir),
		},
	}, nil, nil, "")
	if err != nil {
		return "", fmt.Errorf("failed to create container: %w", err)
	}

	// 6. Start Container
	if err := c.Client.ContainerStart(ctx, resp.ID, container.StartOptions{}); err != nil {
		return "", fmt.Errorf("failed to start container: %w", err)
	}

	// 7. Stream Logs
	var logFile *os.File
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

	// Create MultiWriter: File + Stdout + Provided Writer
	var writers []io.Writer
	writers = append(writers, os.Stdout)
	if logFile != nil {
		writers = append(writers, logFile)
		defer logFile.Close()
	}
	if logWriter != nil {
		writers = append(writers, logWriter)
	}

	out, err := c.Client.ContainerLogs(ctx, resp.ID, container.LogsOptions{ShowStdout: true, ShowStderr: true, Follow: true})
	if err == nil {
		mw := io.MultiWriter(writers...)
		stdcopy.StdCopy(mw, mw, out)
		out.Close()
	}

	// 8. Wait for completion
	statusCh, errCh := c.Client.ContainerWait(ctx, resp.ID, container.WaitConditionNotRunning)
	select {
	case err := <-errCh:
		if err != nil {
			return "", fmt.Errorf("error waiting for container: %w", err)
		}
	case status := <-statusCh:
		if status.StatusCode != 0 {
			return "", fmt.Errorf("build failed: exit status %d", status.StatusCode)
		}
	}

	// 9. Cleanup
	// Use separate context in case the main one is cancelled
	cleanupCtx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	_ = c.Client.ContainerRemove(cleanupCtx, resp.ID, container.RemoveOptions{Force: true})

	return buildID, nil
}

func (c *DockerClient) GetBuildStatus(ctx context.Context, buildID string) (string, error) {
	return "Succeeded", nil
}
