package paths

import (
	"fmt"
	"os"
	"path/filepath"
)

// FindProjectRoot looks for markers like .druppie, blocks, doc_registry.js, or druppie.sh
func FindProjectRoot() (string, error) {
	cwd, err := os.Getwd()
	if err != nil {
		return "", err
	}

	for {
		if _, err := os.Stat(filepath.Join(cwd, ".druppie")); err == nil {
			return cwd, nil
		}
		if _, err := os.Stat(filepath.Join(cwd, "blocks")); err == nil {
			return cwd, nil
		}
		if _, err := os.Stat(filepath.Join(cwd, "doc_registry.js")); err == nil {
			return cwd, nil
		}
		if _, err := os.Stat(filepath.Join(cwd, "script", "druppie.sh")); err == nil {
			return cwd, nil
		}

		parent := filepath.Dir(cwd)
		if parent == cwd {
			return "", fmt.Errorf("project root not found (searched for .druppie, blocks, doc_registry.js, druppie.sh)")
		}
		cwd = parent
	}
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
func ResolvePath(elem ...string) (string, error) {
	root, err := FindProjectRoot()
	if err != nil {
		return "", err
	}
	return filepath.Join(append([]string{root}, elem...)...), nil
}
