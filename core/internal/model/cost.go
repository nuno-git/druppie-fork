package model

// CalculateCost computes the total cost in euros based on token usage and pricing config
// pricePerPromptToken and pricePerCompletionToken are in € per 1M tokens
func (p *ExecutionPlan) CalculateCost(pricePerPromptToken, pricePerCompletionToken float64) {
	if p.TotalUsage.TotalTokens == 0 {
		p.TotalCost = 0
		return
	}

	// Convert tokens to millions and multiply by price per 1M tokens
	promptCost := (float64(p.TotalUsage.PromptTokens) / 1000000.0) * pricePerPromptToken
	completionCost := (float64(p.TotalUsage.CompletionTokens) / 1000000.0) * pricePerCompletionToken

	p.TotalCost = promptCost + completionCost
}
