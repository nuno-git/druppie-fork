package logging

import (
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sync"
	"time"

	"github.com/sjhoeksma/druppie/core/internal/paths"
)

var (
	logMu sync.Mutex
)

// LogInteraction appends a formatted interaction log to the plan's execution.log
func LogInteraction(planID string, tag string, input string, output string) error {
	logMu.Lock()
	defer logMu.Unlock()

	if planID == "" {
		return nil
	}

	// plans/<id>/logs/execution.log
	logDir, _ := paths.ResolvePath(".druppie", "plans", planID, "logs")
	if err := os.MkdirAll(logDir, 0755); err != nil {
		return err
	}
	path := filepath.Join(logDir, "execution.log")

	f, err := os.OpenFile(path, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0644)
	if err != nil {
		return err
	}
	defer f.Close()

	timestamp := time.Now().Format(time.RFC3339)
	entry := fmt.Sprintf("--- [%s] %s ---\nINPUT:\n%s\nOUTPUT:\n%s\n\n", tag, timestamp, input, output)
	_, err = f.WriteString(entry)
	return err
}

// AppendRawLog appends a raw line to the plan's execution.log
func AppendRawLog(planID string, message string) error {
	logMu.Lock()
	defer logMu.Unlock()

	if planID == "" {
		return fmt.Errorf("planID is empty")
	}

	logDir, _ := paths.ResolvePath(".druppie", "plans", planID, "logs")
	if err := os.MkdirAll(logDir, 0755); err != nil {
		return err
	}
	path := filepath.Join(logDir, "execution.log")

	f, err := os.OpenFile(path, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0644)
	if err != nil {
		return err
	}
	defer f.Close()

	_, err = f.WriteString(message + "\n")
	return err
}

// GetLogPath returns the absolute path to the execution.log for a given plan
func GetLogPath(planID string) (string, error) {
	return paths.ResolvePath(".druppie", "plans", planID, "logs", "execution.log")
}

// GetLogs reads the execution.log for a given plan
func GetLogs(planID string) (string, error) {
	logMu.Lock()
	defer logMu.Unlock()

	path, _ := paths.ResolvePath(".druppie", "plans", planID, "logs", "execution.log")
	data, err := os.ReadFile(path)
	if err != nil {
		return "", err
	}
	return string(data), nil
}

// Log is a convenience function for formatted logging
func Log(planID string, format string, args ...interface{}) error {
	return AppendRawLog(planID, fmt.Sprintf(format, args...))
}

// LogWriter is an io.Writer that appends to the execution log
type LogWriter struct {
	PlanID string
}

// NewLogWriter creates a new io.Writer for the given plan
func NewLogWriter(planID string) io.Writer {
	return &LogWriter{PlanID: planID}
}

func (w *LogWriter) Write(p []byte) (n int, err error) {
	// Note: basic implementation that opens/closes file per write.
	// For high throughput streaming, this might be slow, but it guarantees safety.
	err = AppendRawLog(w.PlanID, string(p))
	if err != nil {
		return 0, err
	}
	return len(p), nil
}
