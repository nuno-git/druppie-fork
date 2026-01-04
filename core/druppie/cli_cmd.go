package main

import (
	"fmt"
	"os"
	"os/exec"

	"github.com/spf13/cobra"
)

func newCliCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "cli",
		Short: "Run the interactive druppie CLI (druppie.sh)",
		Run: func(cmd *cobra.Command, args []string) {
			if err := runCli(args); err != nil {
				fmt.Printf("Error running CLI: %v\n", err)
				os.Exit(1)
			}
		},
	}
}

func runCli(args []string) error {
	// Ensure we are in the project root to find druppie.sh
	if err := ensureProjectRoot(); err != nil {
		return fmt.Errorf("could not find project root containing druppie.sh: %w", err)
	}

	scriptPath := "./script/druppie.sh"
	if _, err := os.Stat(scriptPath); os.IsNotExist(err) {
		return fmt.Errorf("druppie.sh not found in script directory")
	}

	// Make executable just in case
	_ = os.Chmod(scriptPath, 0755)

	fmt.Println("Starting Druppie CLI...")

	// Execute shell script, passing any args along
	// We use direct execution. If args are provided, they are passed.
	c := exec.Command(scriptPath, args...)

	// Connect IO
	c.Stdin = os.Stdin
	c.Stdout = os.Stdout
	c.Stderr = os.Stderr

	if err := c.Run(); err != nil {
		// If script returns non-zero, we can return error or just pass it up.
		// Usually for a shell wrapper, we might exit with same code, but for now returning err is fine.
		return fmt.Errorf("druppie.sh exited with error: %w", err)
	}

	return nil
}
