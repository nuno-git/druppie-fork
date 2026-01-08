package memory

import (
	"encoding/json"
	"fmt"
	"strings"
	"sync"
	"time"

	"github.com/sjhoeksma/druppie/core/internal/store"
)

// MemoryType distinguishes between short-term chat history and long-term vector store
type MemoryType string

const (
	MemoryShortTerm MemoryType = "short_term" // In-context sliding window
	MemoryLongTerm  MemoryType = "long_term"  // Vector/semantic search
)

// HistoryEntry represents a single turn in the conversation
type HistoryEntry struct {
	Timestamp time.Time `json:"timestamp"`
	Role      string    `json:"role"`    // user, ai, system
	Content   string    `json:"content"` // Full text
	Summary   string    `json:"summary,omitempty"`
	Tokens    int       `json:"tokens"`
	PlanID    string    `json:"plan_id"`
}

// MemoryContext is the aggregated context returned for a specific plan/turn
type MemoryContext struct {
	RecentTurns   []HistoryEntry `json:"recent_turns"`
	RelevantFacts []string       `json:"relevant_facts"`
}

// Manager handles storage and retrieval of conversation history
type Manager struct {
	mu        sync.RWMutex
	shortTerm map[string][]HistoryEntry // planID -> history
	store     store.Store

	// Configuration
	MaxWindowTokens int
	SummarizeAfter  int
}

// NewManager creates a new Memory Manager
func NewManager(maxTokens int, s store.Store) *Manager {
	if maxTokens <= 0 {
		maxTokens = 12000 // Default safety limit
	}
	return &Manager{
		shortTerm:       make(map[string][]HistoryEntry),
		store:           s,
		MaxWindowTokens: maxTokens,
		SummarizeAfter:  10, // Default
		// Future: VectorStore: enabled by default per plan (.druppie/plans/<id>/vector_store)

	}
}

// AddEntry adds a new message to the plan's history
func (m *Manager) AddEntry(planID, role, content string) {
	m.mu.Lock()
	defer m.mu.Unlock()

	// Ensure we have the latest history loaded
	if _, ok := m.shortTerm[planID]; !ok {
		if m.store != nil {
			if data, err := m.store.LoadMemory(planID); err == nil {
				var hist []HistoryEntry
				if json.Unmarshal(data, &hist) == nil {
					m.shortTerm[planID] = hist
				}
			}
		}
	}

	entry := HistoryEntry{
		Timestamp: time.Now(),
		Role:      role,
		Content:   content,
		PlanID:    planID,
		Tokens:    estimateTokens(content),
	}

	m.shortTerm[planID] = append(m.shortTerm[planID], entry)

	// Prune history to stay within token limits
	// We keep system prompt (usually handled by caller) separate, so this is just chat history
	m.pruneHistory(planID)

	// Persist immediately
	if m.store != nil {
		if data, err := json.Marshal(m.shortTerm[planID]); err == nil {
			_ = m.store.SaveMemory(planID, data)
		}
	}
}

// LoadHistory ensures the memory for a plan is loaded from store
func (m *Manager) LoadHistory(planID string) error {
	m.mu.Lock()
	defer m.mu.Unlock()

	if _, ok := m.shortTerm[planID]; ok {
		return nil
	}

	if m.store != nil {
		if data, err := m.store.LoadMemory(planID); err == nil {
			var hist []HistoryEntry
			if err := json.Unmarshal(data, &hist); err != nil {
				return err
			}
			m.shortTerm[planID] = hist
			return nil
		}
	}
	return nil
}

// GetContext retrieves the constructed context for the next LLM call
func (m *Manager) GetContext(planID string) string {
	m.mu.RLock()
	defer m.mu.RUnlock()

	history, ok := m.shortTerm[planID]
	if !ok {
		// Try loading from store
		if m.store != nil {
			if data, err := m.store.LoadMemory(planID); err == nil {
				var hist []HistoryEntry
				if json.Unmarshal(data, &hist) == nil {
					m.shortTerm[planID] = hist
					history = hist
				}
			}
		}
	}
	if len(history) == 0 {
		return ""
	}

	var sb strings.Builder
	for _, entry := range history {
		// Simple format: Role: Content
		role := strings.ToUpper(entry.Role)
		if role == "AI" {
			role = "ASSISTANT"
		}
		sb.WriteString(fmt.Sprintf("%s: %s\n", role, entry.Content))
	}
	return sb.String()
}

// pruneHistory removes oldest messages if token count exceeds limit
// Always preserves the most recent messages
func (m *Manager) pruneHistory(planID string) {
	history := m.shortTerm[planID]
	if len(history) == 0 {
		return
	}

	totalTokens := 0
	for _, e := range history {
		totalTokens += e.Tokens
	}

	if totalTokens <= m.MaxWindowTokens {
		return
	}

	// Simple FIFO pruning from the start
	// In a real system, we might want to summarize instead of delete
	kbCutoff := 0
	for i, e := range history {
		totalTokens -= e.Tokens
		if totalTokens <= m.MaxWindowTokens {
			kbCutoff = i + 1
			break
		}
	}

	if kbCutoff > 0 && kbCutoff < len(history) {
		// Keep the new slice
		m.shortTerm[planID] = history[kbCutoff:]
	}
}

// Simple approximation: 1 token ~= 4 chars (english)
func estimateTokens(text string) int {
	return len(text) / 4
}

// Store/Load persistence methods could be added here
func (m *Manager) Save(planID string) ([]byte, error) {
	m.mu.RLock()
	defer m.mu.RUnlock()
	return json.Marshal(m.shortTerm[planID])
}

func (m *Manager) Load(planID string, data []byte) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	var history []HistoryEntry
	if err := json.Unmarshal(data, &history); err != nil {
		return err
	}
	m.shortTerm[planID] = history
	return nil
}
