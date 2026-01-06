package store

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sync"
	"time"

	"github.com/sjhoeksma/druppie/core/internal/model"
)

// Store defines the interface for persisting execution plans and configuration.
type Store interface {
	// Plans
	SavePlan(plan model.ExecutionPlan) error
	GetPlan(id string) (model.ExecutionPlan, error)
	ListPlans() ([]model.ExecutionPlan, error)
	DeletePlan(id string) error

	// Interaction Logging
	LogInteraction(planID string, tag string, input string, output string) error
	AppendRawLog(planID string, message string) error
	GetLogs(id string) (string, error)

	// Config (raw bytes to avoid cycle, manager handles marshaling)
	SaveConfig(data []byte) error
	LoadConfig() ([]byte, error)

	// MCP Servers
	SaveMCPServers(data []byte) error
	LoadMCPServers() ([]byte, error)
}

// FileStore implements Store using local file system.
// baseDir should be the root persistent dir (e.g. .druppie)
type FileStore struct {
	baseDir string
	mu      sync.RWMutex
}

func NewFileStore(baseDir string) (*FileStore, error) {
	// Create base dir (e.g. .druppie)
	if err := os.MkdirAll(baseDir, 0755); err != nil {
		return nil, fmt.Errorf("failed to create store directory: %w", err)
	}
	// Create plans subdir
	plansDir := filepath.Join(baseDir, "plans")
	if err := os.MkdirAll(plansDir, 0755); err != nil {
		return nil, fmt.Errorf("failed to create plans directory: %w", err)
	}
	return &FileStore{baseDir: baseDir}, nil
}

func (s *FileStore) SavePlan(plan model.ExecutionPlan) error {
	s.mu.Lock()
	defer s.mu.Unlock()

	data, err := json.MarshalIndent(plan, "", "  ")
	if err != nil {
		return fmt.Errorf("failed to marshal plan: %w", err)
	}

	planDir := filepath.Join(s.baseDir, "plans", plan.ID)
	if err := os.MkdirAll(planDir, 0755); err != nil {
		return fmt.Errorf("failed to create plan directory: %w", err)
	}

	filename := filepath.Join(planDir, "plan.json")
	if err := os.WriteFile(filename, data, 0644); err != nil {
		return fmt.Errorf("failed to write plan file: %w", err)
	}

	return nil
}

func (s *FileStore) GetPlan(id string) (model.ExecutionPlan, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()

	filename := filepath.Join(s.baseDir, "plans", id, "plan.json")
	data, err := os.ReadFile(filename)
	if err != nil {
		if os.IsNotExist(err) {
			return model.ExecutionPlan{}, fmt.Errorf("plan not found: %s", id)
		}
		return model.ExecutionPlan{}, fmt.Errorf("failed to read plan file: %w", err)
	}

	var plan model.ExecutionPlan
	if err := json.Unmarshal(data, &plan); err != nil {
		return model.ExecutionPlan{}, fmt.Errorf("failed to unmarshal plan: %w", err)
	}

	return plan, nil
}

func (s *FileStore) ListPlans() ([]model.ExecutionPlan, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()

	plansDir := filepath.Join(s.baseDir, "plans")
	entries, err := os.ReadDir(plansDir)
	if err != nil {
		return nil, fmt.Errorf("failed to list plans: %w", err)
	}

	var plans []model.ExecutionPlan
	for _, entry := range entries {
		if entry.IsDir() {
			planFile := filepath.Join(plansDir, entry.Name(), "plan.json")
			data, err := os.ReadFile(planFile)
			if err != nil {
				if !os.IsNotExist(err) {
					fmt.Printf("[Store] Error reading plan %s: %v\n", entry.Name(), err)
				}
				continue
			}

			var p model.ExecutionPlan
			if err := json.Unmarshal(data, &p); err != nil {
				fmt.Printf("[Store] Error unmarshaling plan %s: %v\n", entry.Name(), err)
				continue
			}
			plans = append(plans, p)
		}
	}
	return plans, nil
}

func (s *FileStore) DeletePlan(id string) error {
	s.mu.Lock()
	defer s.mu.Unlock()

	// Delete plan directory (contains plan.json, logs/, files/)
	planDir := filepath.Join(s.baseDir, "plans", id)
	if err := os.RemoveAll(planDir); err != nil && !os.IsNotExist(err) {
		return fmt.Errorf("failed to delete plan directory: %w", err)
	}

	return nil
}

func (s *FileStore) LogInteraction(planID string, tag string, input string, output string) error {
	s.mu.Lock()
	defer s.mu.Unlock()

	if planID == "" {
		return nil
	}

	// plans/<id>/logs/execution.log
	logDir := filepath.Join(s.baseDir, "plans", planID, "logs")
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

func (s *FileStore) AppendRawLog(planID string, message string) error {
	s.mu.Lock()
	defer s.mu.Unlock()

	if planID == "" {
		return fmt.Errorf("planID is empty")
	}

	logDir := filepath.Join(s.baseDir, "plans", planID, "logs")
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

func (s *FileStore) GetLogs(id string) (string, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()

	path := filepath.Join(s.baseDir, "plans", id, "logs", "execution.log")
	data, err := os.ReadFile(path)
	if err != nil {
		return "", err
	}
	return string(data), nil
}

func (s *FileStore) SaveConfig(data []byte) error {
	s.mu.Lock()
	defer s.mu.Unlock()

	filename := filepath.Join(s.baseDir, "config.yaml")
	if err := os.WriteFile(filename, data, 0644); err != nil {
		return fmt.Errorf("failed to write config file: %w", err)
	}
	return nil
}

func (s *FileStore) LoadConfig() ([]byte, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()

	filename := filepath.Join(s.baseDir, "config.yaml")
	data, err := os.ReadFile(filename)
	if err != nil {
		return nil, err // Let caller handle not found
	}
	return data, nil
}

func (s *FileStore) SaveMCPServers(data []byte) error {
	s.mu.Lock()
	defer s.mu.Unlock()

	filename := filepath.Join(s.baseDir, "mcp_servers.json")
	if err := os.WriteFile(filename, data, 0644); err != nil {
		return fmt.Errorf("failed to write mcp servers file: %w", err)
	}
	return nil
}

func (s *FileStore) LoadMCPServers() ([]byte, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()

	filename := filepath.Join(s.baseDir, "mcp_servers.json")
	data, err := os.ReadFile(filename)
	if err != nil {
		return nil, err
	}
	return data, nil
}
