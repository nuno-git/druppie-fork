package builder

import (
	"fmt"

	"github.com/sjhoeksma/druppie/core/internal/config"
)

// NewEngine creates a new BuildEngine based on configuration
func NewEngine(cfg config.BuildConfig) (BuildEngine, error) {
	// 1. Identify which provider key to use
	//    Legacy fallback: if Provider is set directly in root struct and we have no DefaultProvider?
	//    But we prefer DefaultProvider.

	providerName := cfg.DefaultProvider
	if providerName == "" && cfg.Provider != "" {
		providerName = cfg.Provider // Legacy fallback
	}
	if providerName == "" {
		providerName = "local" // Final fallback
	}

	// 2. Get config for that provider
	var pCfg config.BuildProviderConfig
	if cfg.Providers != nil {
		if v, ok := cfg.Providers[providerName]; ok {
			pCfg = v
		}
	}

	// Fallback/Legacy: map root settings to pCfg if missing
	if pCfg.Type == "" {
		pCfg.Type = providerName // assume name is type if not specified
		if cfg.Namespace != "" {
			pCfg.Namespace = cfg.Namespace // Legacy namespace
		}
	}

	// 3. Instantiate
	switch pCfg.Type {
	case "tekton":
		client, err := NewTektonClient(pCfg.Namespace)
		if err != nil {
			return nil, fmt.Errorf("failed to initialize tekton client: %w", err)
		}
		return client, nil
	case "local":
		client, err := NewLocalClient(pCfg.WorkingDir)
		if err != nil {
			return nil, fmt.Errorf("failed to initialize local client: %w", err)
		}
		return client, nil
	default:
		return nil, fmt.Errorf("unknown build provider type: %s", pCfg.Type)
	}
}
