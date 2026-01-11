package config

import (
	"fmt"
	"os"
	"sync" // For thread-safe updates

	"github.com/sjhoeksma/druppie/core/internal/store"
	"gopkg.in/yaml.v3"
)

// Config holds the runtime configuration
type Config struct {
	LLM            LLMConfig            `yaml:"llm" json:"llm"`
	Build          BuildConfig          `yaml:"build" json:"build"`
	Git            GitConfig            `yaml:"git" json:"git"`
	IAM            IAMConfig            `yaml:"iam" json:"iam"`
	ApprovalGroups map[string][]string  `yaml:"approval_groups" json:"approval_groups"`
	General        GeneralConfig        `yaml:"general" json:"general"`
	ScheduledJobs  []ScheduledJobConfig `yaml:"scheduled_jobs" json:"scheduled_jobs"`
}

type ScheduledJobConfig struct {
	Name     string            `yaml:"name" json:"name"`
	Type     string            `yaml:"type" json:"type"` // "cleanup", "llm"
	Schedule string            `yaml:"schedule" json:"schedule"`
	Params   map[string]string `yaml:"params" json:"params"`
}

type GeneralConfig struct {
	MaxUnattendedCost float64            `yaml:"max_unattended_cost" json:"max_unattended_cost"`
	InternalCosts     map[string]float64 `yaml:"internal_costs" json:"internal_costs"`
	ServerPort        string             `yaml:"server_port" json:"server_port"`
	CleanupDays       int                `yaml:"cleanup_days" json:"cleanup_days"`
	MaxAgentSelection int                `yaml:"max_agent_selections" json:"max_agent_selections"`
	Memory            MemoryConfig       `yaml:"memory" json:"memory"`
}

// ... (other types unchanged)

type MemoryConfig struct {
	MaxWindowTokens int `yaml:"max_window_tokens" json:"max_window_tokens"` // e.g. 128000
	SummarizeAfter  int `yaml:"summarize_after" json:"summarize_after"`     // Turn count
}

type IAMConfig struct {
	Provider string         `yaml:"provider" json:"provider"` // "local", "keycloak"
	Keycloak KeycloakConfig `yaml:"keycloak" json:"keycloak"`
}

type KeycloakConfig struct {
	URL          string `yaml:"url" json:"url"`
	Realm        string `yaml:"realm" json:"realm"`
	ClientID     string `yaml:"client_id" json:"client_id"`
	ClientSecret string `yaml:"client_secret" json:"client_secret"`
}

type GitConfig struct {
	Provider string `yaml:"provider" json:"provider"` // "gitea", "github", "gitlab"
	URL      string `yaml:"url" json:"url"`           // e.g. "http://gitea-http.gitea.svc.cluster.local:3000"
	User     string `yaml:"user" json:"user"`
	Token    string `yaml:"token" json:"token"`
}

type BuildConfig struct {
	DefaultProvider string                         `yaml:"default_provider" json:"default_provider"` // "tekton", "local"
	Providers       map[string]BuildProviderConfig `yaml:"providers" json:"providers"`
	// Legacy
	Provider  string `yaml:"provider,omitempty" json:"provider,omitempty"`
	Namespace string `yaml:"namespace,omitempty" json:"namespace,omitempty"`
}

type BuildProviderConfig struct {
	Type       string `yaml:"type" json:"type"` // "tekton", "local"
	Namespace  string `yaml:"namespace,omitempty" json:"namespace,omitempty"`
	WorkingDir string `yaml:"working_dir,omitempty" json:"working_dir,omitempty"`
}

type LLMConfig struct {
	DefaultProvider string                    `yaml:"default_provider" json:"default_provider"` // "gemini", "ollama", "lmstudio"
	TimeoutSeconds  int                       `yaml:"timeout_seconds,omitempty" json:"timeout_seconds,omitempty"`
	Retries         int                       `yaml:"retries,omitempty" json:"retries,omitempty"`
	Providers       map[string]ProviderConfig `yaml:"providers" json:"providers"`
}

type ProviderConfig struct {
	Type                    string  `yaml:"type" json:"type"` // "gemini", "ollama", "lmstudio"
	APIKey                  string  `yaml:"api_key,omitempty" json:"api_key,omitempty"`
	Model                   string  `yaml:"model,omitempty" json:"model,omitempty"` // Default model for this provider
	URL                     string  `yaml:"url,omitempty" json:"url,omitempty"`     // For local LLMs
	ProjectID               string  `yaml:"project_id,omitempty" json:"project_id,omitempty"`
	ClientID                string  `yaml:"client_id,omitempty" json:"client_id,omitempty"`
	ClientSecret            string  `yaml:"client_secret,omitempty" json:"client_secret,omitempty"`
	PricePerPromptToken     float64 `yaml:"price_per_prompt_token,omitempty" json:"price_per_prompt_token,omitempty"`         // € per 1M tokens
	PricePerCompletionToken float64 `yaml:"price_per_completion_token,omitempty" json:"price_per_completion_token,omitempty"` // € per 1M tokens
	PricePerRequest         float64 `yaml:"price_per_request,omitempty" json:"price_per_request,omitempty"`                   // € per request (e.g. image)
	PricePerWord            float64 `yaml:"price_per_word,omitempty" json:"price_per_word,omitempty"`                         // € per word (e.g. TTS)
}

// Manager handles concurrent access to the configuration
type Manager struct {
	mu     sync.RWMutex
	config *Config
	store  store.Store
}

// NewManager creates a new config manager and loads the config from store
// NewManager creates a new config manager and loads the config from store
func NewManager(s store.Store) (*Manager, error) {
	mgr := &Manager{
		store: s,
		config: &Config{
			LLM: LLMConfig{
				DefaultProvider: "ollama",
				TimeoutSeconds:  120,
				Retries:         3,
				Providers: map[string]ProviderConfig{
					"ollama": {
						Type:                    "ollama",
						Model:                   "qwen3:8b",
						URL:                     "http://localhost:11434",
						PricePerPromptToken:     0.0, // Free for local models
						PricePerCompletionToken: 0.0,
					},
					"gemini": {
						Type:                    "gemini",
						Model:                   "gemini-2.0-flash-exp",
						PricePerPromptToken:     0.075, // €0.075 per 1M input tokens
						PricePerCompletionToken: 0.30,  // €0.30 per 1M output tokens
					},
				},
			},
			General: GeneralConfig{
				MaxUnattendedCost: 1.0,
				ServerPort:        "8080",
				CleanupDays:       7,
				MaxAgentSelection: 3,
				Memory: MemoryConfig{
					MaxWindowTokens: 12000,
					SummarizeAfter:  20,
				},
			},
			Build: BuildConfig{
				DefaultProvider: "local",
				Providers: map[string]BuildProviderConfig{
					"tekton": {
						Type:      "tekton",
						Namespace: "default",
					},
					"local": {
						Type:       "local",
						WorkingDir: ".",
					},
				},
			},
			Git: GitConfig{
				Provider: "gitea",
				URL:      "http://gitea-http.gitea.svc.cluster.local:3000",
			},
			IAM: IAMConfig{
				Provider: "local",
			},
		},
	}

	// Try to load
	if err := mgr.Load(); err != nil {
		// If load fails (e.g. empty), assume default specific logic?
		// For now, if load fails, we rely on the struct above being the default.
		// Check environment variables as fallback
		mgr.loadEnv()

		// Optional: Save default to store if it was empty?
		// _ = mgr.Save()
	}

	return mgr, nil
}

// Load reads the config from store
func (m *Manager) Load() error {
	m.mu.Lock()
	defer m.mu.Unlock()

	data, err := m.store.LoadConfig()
	if err != nil {
		// If config not found, return error or nil?
		// NewManager ignores error essentially, but logging it might be good.
		return fmt.Errorf("failed to read config from store: %w", err)
	}

	if err := yaml.Unmarshal(data, m.config); err != nil {
		return fmt.Errorf("failed to parse config file: %w", err)
	}
	return nil
}

// Save writes the current config to disk via store
func (m *Manager) Save() error {
	m.mu.RLock()
	defer m.mu.RUnlock()

	data, err := yaml.Marshal(m.config)
	if err != nil {
		return fmt.Errorf("failed to marshal config: %w", err)
	}

	if err := m.store.SaveConfig(data); err != nil {
		return fmt.Errorf("failed to write config to store: %w", err)
	}
	return nil
}

// Clone creates a deep copy of the Config
func (c Config) Clone() Config {
	newCfg := c
	if c.LLM.Providers != nil {
		newCfg.LLM.Providers = make(map[string]ProviderConfig, len(c.LLM.Providers))
		for k, v := range c.LLM.Providers {
			newCfg.LLM.Providers[k] = v
		}
	}
	if c.Build.Providers != nil {
		newCfg.Build.Providers = make(map[string]BuildProviderConfig, len(c.Build.Providers))
		for k, v := range c.Build.Providers {
			newCfg.Build.Providers[k] = v
		}
	}
	if c.General.InternalCosts != nil {
		newCfg.General.InternalCosts = make(map[string]float64, len(c.General.InternalCosts))
		for k, v := range c.General.InternalCosts {
			newCfg.General.InternalCosts[k] = v
		}
	}
	if c.ScheduledJobs != nil {
		newCfg.ScheduledJobs = make([]ScheduledJobConfig, len(c.ScheduledJobs))
		for i, job := range c.ScheduledJobs {
			newJob := job
			if job.Params != nil {
				newJob.Params = make(map[string]string, len(job.Params))
				for k, v := range job.Params {
					newJob.Params[k] = v
				}
			}
			newCfg.ScheduledJobs[i] = newJob
		}
	}
	return newCfg
}

// Sanitize returns a copy of the config with sensitive data redacted
func (c Config) Sanitize() Config {
	safe := c.Clone()
	safe.Git.Token = ""

	for name, p := range safe.LLM.Providers {
		p.APIKey = ""
		safe.LLM.Providers[name] = p
	}
	safe.IAM.Keycloak.ClientSecret = ""
	return safe
}

// Get returns specific config copy
func (m *Manager) Get() Config {
	m.mu.RLock()
	defer m.mu.RUnlock()
	return m.config.Clone()
}

// Update updates the configuration and saves it
func (m *Manager) Update(newConfig Config) error {
	m.mu.Lock()
	m.config = &newConfig
	m.mu.Unlock()
	return m.Save()
}

func (m *Manager) loadEnv() {
	if key := os.Getenv("GEMINI_API_KEY"); key != "" {
		// Update gemini provider in map if exists, or create it
		if m.config.LLM.Providers == nil {
			m.config.LLM.Providers = make(map[string]ProviderConfig)
		}
		p := m.config.LLM.Providers["gemini"]
		p.Type = "gemini"
		p.APIKey = key
		m.config.LLM.Providers["gemini"] = p

		// Set default if not set
		if m.config.LLM.DefaultProvider == "" {
			m.config.LLM.DefaultProvider = "gemini"
		}
	}
	if port := os.Getenv("PORT"); port != "" {
		m.config.General.ServerPort = port
	}
	if cleanup := os.Getenv("CLEANUP_DAYS"); cleanup != "" {
		var days int
		if _, err := fmt.Sscanf(cleanup, "%d", &days); err == nil && days > 0 {
			m.config.General.CleanupDays = days
		}
	}
	if iam := os.Getenv("IAM_PROVIDER"); iam != "" {
		m.config.IAM.Provider = iam
	}
}
