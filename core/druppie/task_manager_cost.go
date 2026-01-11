package main

import (
	"github.com/sjhoeksma/druppie/core/internal/model"
)

// updatePlanCost calculates and updates the cost for a plan based on current LLM pricing
func (tm *TaskManager) updatePlanCost(plan *model.ExecutionPlan) {
	if plan == nil {
		return
	}

	// CalculateCost now aggregates individual step costs
	plan.CalculateCost()
}
