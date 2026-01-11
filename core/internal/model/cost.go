package model

// CalculateCost aggregates the total cost from steps and planning usage
func (p *ExecutionPlan) CalculateCost() {
	var total float64

	// Add Planning Logic Usage Cost
	total += p.PlanningUsage.EstimatedCost

	// Add Step Usage Costs
	for _, s := range p.Steps {
		if s.Usage != nil {
			total += s.Usage.EstimatedCost
		}
	}

	// Ensure TotalUsage struct also reflects this?
	// TotalUsage.TotalTokens is sum of tokens.
	// TotalUsage.EstimatedCost can also be sum.
	p.TotalUsage.EstimatedCost = total
	p.TotalCost = total
}
