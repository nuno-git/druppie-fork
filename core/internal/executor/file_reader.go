package executor

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"github.com/sjhoeksma/druppie/core/internal/model"
)

type FileReaderExecutor struct{}

func (e *FileReaderExecutor) CanHandle(action string) bool {
	return strings.EqualFold(action, "read_file") || strings.EqualFold(action, "analyze_file")
}

func (e *FileReaderExecutor) Execute(ctx context.Context, step model.Step, outputChan chan<- string) error {
	outputChan <- fmt.Sprintf("📂 [File Reader] Processing: %v", step.Params)

	// Get filename from params
	fileNameRaw, ok := step.Params["filename"]
	if !ok {
		// Try aliases
		if val, exists := step.Params["file"]; exists {
			fileNameRaw = val
			ok = true
		} else if val, exists := step.Params["file_path"]; exists {
			fileNameRaw = val
			ok = true
		} else if val, exists := step.Params["path"]; exists {
			fileNameRaw = val
			ok = true
		}
	}

	if !ok || fileNameRaw == "" {
		return fmt.Errorf("missing 'filename' parameter")
	}

	filename := fmt.Sprintf("%v", fileNameRaw)

	// Determine Root
	rootDir, _ := os.Getwd()
	// Adjust for running from core/cmd vs root
	if strings.HasSuffix(rootDir, "core") {
		rootDir = filepath.Dir(rootDir)
	}

	// Resolve Path
	var finalPath string

	// Check if absolute or specific relative path provided by Planner (e.g. agents/planner.md)
	// If it looks like a path string (contains /), treat it as relative to Workspace Root
	// Check if absolute or specific relative path provided by Planner (e.g. agents/planner.md)
	// If it looks like a path string (contains /), treat it as relative to Workspace Root
	if strings.Contains(filename, "/") || strings.Contains(filename, "\\") {
		// Security Check: prevent traversal
		if strings.Contains(filename, "..") {
			return fmt.Errorf("directory traversal not allowed: %s", filename)
		}

		// 1. Try exact path
		cand := filepath.Join(rootDir, filename)
		if _, err := os.Stat(cand); err == nil {
			finalPath = cand
		}

		// 2. Try stripping .druppie/ prefix (Planner hallucination fix)
		if finalPath == "" && strings.HasPrefix(filename, ".druppie/") {
			stripped := strings.TrimPrefix(filename, ".druppie/")
			cand := filepath.Join(rootDir, stripped)
			if _, err := os.Stat(cand); err == nil {
				finalPath = cand
			}
		}

		// Check if exists logic moved inside
	}

	// If standard lookup by Plan ID
	if finalPath == "" {
		planID := ""
		if p, ok := step.Params["plan_id"].(string); ok {
			planID = p
		} else if p, ok := step.Params["_plan_id"].(string); ok {
			planID = p
		}

		if planID != "" {
			finalPath = filepath.Join(rootDir, ".druppie", "files", planID, filename)
		} else {
			// Search
			glob := filepath.Join(rootDir, ".druppie", "files", "*", filename)
			matches, _ := filepath.Glob(glob)
			if len(matches) > 0 {
				finalPath = matches[0] // Pick first
			}
		}
	}

	if finalPath == "" {
		// Last resort: Check if it exists relative to CWD
		cand := filepath.Join(rootDir, filename)
		if _, err := os.Stat(cand); err == nil {
			finalPath = cand
		} else {
			return fmt.Errorf("file not found: %s", filename)
		}
	}
	path := finalPath

	// Read
	data, err := os.ReadFile(path)
	if err != nil {
		return fmt.Errorf("failed to read file: %w", err)
	}

	content := string(data)
	if len(content) > 2000 {
		content = content[:2000] + "\n... (truncated)"
	}

	outputChan <- fmt.Sprintf("✅ [File Reader] Read %d bytes.", len(data))
	outputChan <- fmt.Sprintf("RESULT_FILE_CONTENT=%s", content)

	return nil
}
