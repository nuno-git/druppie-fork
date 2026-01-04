package main

import (
	"fmt"
	"os"
	"path/filepath"
)

// findProjectRoot looks for markers like .druppie, blocks, doc_registry.js, or druppie.sh
func findProjectRoot() (string, error) {
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

// ensureProjectRoot finds the root and changes the current working directory to it
func ensureProjectRoot() error {
	root, err := findProjectRoot()
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
