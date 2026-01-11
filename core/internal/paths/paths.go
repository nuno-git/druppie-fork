package paths

import (
	"fmt"
	"os"
	"path/filepath"
	"sync"
)

var (
	// cachedRoot stores the project root once found
	cachedRoot string
	// cachedRootErr stores any error encountered while finding the root
	cachedRootErr error
	// once ensures the root is only searched for once
	once sync.Once
)

// findProjectRootOnce performs the actual search for the project root
// This is called only once via sync.Once
func findProjectRootOnce() {
	cwd, err := os.Getwd()
	if err != nil {
		cachedRootErr = err
		return
	}

	for {
		if _, err := os.Stat(filepath.Join(cwd, ".druppie")); err == nil {
			cachedRoot = cwd
			return
		}
		if _, err := os.Stat(filepath.Join(cwd, "blocks")); err == nil {
			cachedRoot = cwd
			return
		}
		if _, err := os.Stat(filepath.Join(cwd, "doc_registry.js")); err == nil {
			cachedRoot = cwd
			return
		}
		if _, err := os.Stat(filepath.Join(cwd, "script", "druppie.sh")); err == nil {
			cachedRoot = cwd
			return
		}

		parent := filepath.Dir(cwd)
		if parent == cwd {
			cachedRootErr = fmt.Errorf("project root not found (searched for .druppie, blocks, doc_registry.js, druppie.sh)")
			return
		}
		cwd = parent
	}
}

// FindProjectRoot looks for markers like .druppie, blocks, doc_registry.js, or druppie.sh
// The search is performed only once and the result is cached for subsequent calls
func FindProjectRoot() (string, error) {
	once.Do(findProjectRootOnce)
	return cachedRoot, cachedRootErr
}

// EnsureProjectRoot finds the root and changes the current working directory to it
func EnsureProjectRoot() error {
	root, err := FindProjectRoot()
	if err != nil {
		return err
	}
	cwd, _ := os.Getwd()
	if root != cwd {
		// fmt.Printf("Switching to project root: %s\n", root)
		if err := os.Chdir(root); err != nil {
			return fmt.Errorf("failed to chdir to project root: %w", err)
		}
	}
	return nil
}

// ResolvePath returns the absolute path joined with the project root.
// If project root cannot be found, it uses the current working directory.
func ResolvePath(elem ...string) (string, error) {
	root, err := FindProjectRoot()
	if err != nil {
		// Fallback to current working directory
		cwd, cwdErr := os.Getwd()
		if cwdErr != nil {
			return "", fmt.Errorf("failed to find project root and get cwd: %w", err)
		}
		root = cwd
	}

	// Ensure root is absolute
	absRoot, err := filepath.Abs(root)
	if err != nil {
		return "", fmt.Errorf("failed to get absolute path for root: %w", err)
	}

	result := filepath.Join(append([]string{absRoot}, elem...)...)
	return result, nil
}

// ResolveRepoURL resolves and validates a repository URL for a given plan.
// It handles empty URLs, relative paths, and ensures the path points to the 'src' directory.
// If the URL points to the plan root, it automatically redirects to the 'src' subdirectory.
// It also detects and corrects common LLM hallucinations (wrong plan IDs, placeholder values).
//
// Parameters:
//   - repoURL: The repository URL from parameters (may be empty or relative)
//   - planID: The plan identifier
//
// Returns:
//   - The resolved absolute path to the repository
//   - A warning message if auto-correction was applied (empty string otherwise)
//   - An error if the path cannot be resolved
func ResolveRepoURL(repoURL, planID string) (string, string, error) {
	if planID == "" {
		if repoURL == "" {
			return "", "", fmt.Errorf("missing both plan_id and repo_url")
		}
		// No plan context, return as-is
		return repoURL, "", nil
	}

	// Define the safe base path for code (src directory)
	basePath, err := ResolvePath(".druppie", "plans", planID, "src")
	if err != nil {
		return "", "", fmt.Errorf("failed to resolve base path: %w", err)
	}

	// HALLUCINATION CHECK: Detect if repoURL contains a plan ID that doesn't match the current one
	// This catches common LLM mistakes like copying examples or using placeholder values
	if repoURL != "" && !containsString(repoURL, planID) {
		// Check for hallucination patterns
		if containsString(repoURL, "plan-") ||
			containsString(repoURL, "<YOUR_PLAN_ID>") ||
			containsString(repoURL, "/plans/1/") ||
			containsString(repoURL, "${PLAN_ID}") {
			// Auto-correct to the current plan's src directory
			return basePath, "⚠️  Detected invalid plan ID in path. Auto-correcting to current plan.", nil
		}
	}

	// If repoURL is empty or current directory, use basePath
	if repoURL == "" || repoURL == "." || repoURL == "./" {
		return basePath, "", nil
	}

	// Try joining with base path if not absolute
	var resolvedPath string
	if !filepath.IsAbs(repoURL) {
		joinedPath := filepath.Join(basePath, repoURL)

		// Use the joined path if it exists
		if _, err := os.Stat(joinedPath); err == nil {
			resolvedPath = joinedPath
		} else {
			// Fallback: Check if repoURL was already a valid path
			if _, err := os.Stat(repoURL); err == nil {
				resolvedPath = repoURL
			} else {
				resolvedPath = joinedPath
			}
		}
	} else {
		resolvedPath = repoURL
	}

	// AUTO-CORRECTION: If repoURL points to the Plan Root (parent of src), force it to src
	// This prevents copying 'logs', 'builds', etc. recursively.
	planRoot, _ := ResolvePath(".druppie", "plans", planID)
	if filepath.Clean(resolvedPath) == filepath.Clean(planRoot) {
		return basePath, "⚠️  Auto-correcting build path from Plan Root to 'src' to avoid recursive copy.", nil
	}

	return resolvedPath, "", nil
}

// containsString checks if a string contains a substring (case-sensitive)
func containsString(s, substr string) bool {
	return len(s) >= len(substr) && (s == substr || len(s) > len(substr) &&
		(s[:len(substr)] == substr || s[len(s)-len(substr):] == substr ||
			findSubstring(s, substr)))
}

// findSubstring performs a simple substring search
func findSubstring(s, substr string) bool {
	for i := 0; i <= len(s)-len(substr); i++ {
		if s[i:i+len(substr)] == substr {
			return true
		}
	}
	return false
}
