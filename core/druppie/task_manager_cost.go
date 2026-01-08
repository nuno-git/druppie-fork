package main

import (
"github.com/sjhoeksma/druppie/core/internal/config"
"github.com/sjhoeksma/druppie/core/internal/model"
"gopkg.in/yaml.v3"
)

// updatePlanCost calculates and updates the cost for a plan based on current LLM pricing
func (tm *TaskManager) updatePlanCost(plan *model.ExecutionPlan) {
	if plan == nil {
		return
	}

	// Get current config
	cfgBytes, err := tm.planner.Store.LoadConfig()
	if err != nil {
		return // Silently fail if config not available
	}

	var cfg config.Config
	if err := yaml.Unmarshal(cfgBytes, &cfg); err != nil {
		return
	}

	// Get pricing for the default provider
	if providerCfg, ok := cfg.LLM.Providers[cfg.LLM.DefaultProvider]; ok {
		plan.CalculateCost(providerCfg.PricePerPromptToken, providerCfg.PricePerCompletionToken)
	}
}
