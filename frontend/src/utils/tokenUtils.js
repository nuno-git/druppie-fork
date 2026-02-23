/**
 * Token and Cost Utilities
 *
 * Provides formatting for token counts and cost estimation
 * Cost is estimated based on typical LLM API pricing
 */

// Estimated cost per million tokens (average of input/output)
// Based on DeepInfra Qwen model pricing (~$0.40/million tokens)
const COST_PER_MILLION_TOKENS = 0.40

/**
 * Format token count with K/M suffix for readability
 * @param {number} count - Raw token count
 * @returns {string|null} Formatted string like "141.8K" or null if no count
 */
export const formatTokens = (count) => {
  if (!count) return null
  if (count >= 1000000) return `${(count / 1000000).toFixed(1)}M`
  if (count >= 1000) return `${(count / 1000).toFixed(1)}K`
  return count.toString()
}

/**
 * Calculate estimated cost from token count
 * @param {number} tokens - Token count
 * @returns {number} Estimated cost in dollars
 */
export const calculateCost = (tokens) => {
  if (!tokens) return 0
  return (tokens / 1000000) * COST_PER_MILLION_TOKENS
}

/**
 * Format cost as currency string
 * @param {number} cost - Cost in dollars
 * @returns {string} Formatted string like "$0.05" or "<$0.01"
 */
export const formatCost = (cost) => {
  if (!cost || cost === 0) return null
  if (cost < 0.01) return '<$0.01'
  if (cost < 1) return `$${cost.toFixed(2)}`
  return `$${cost.toFixed(2)}`
}

/**
 * Format duration in ms to human-readable string
 * @param {number} ms - Duration in milliseconds
 * @returns {string|null} Formatted string like "1.5s" or "2m 30s"
 */
export const formatDuration = (ms) => {
  if (!ms) return null
  if (ms < 1000) return `${ms}ms`
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`
  const mins = Math.floor(ms / 60000)
  const secs = Math.round((ms % 60000) / 1000)
  return `${mins}m ${secs}s`
}

/**
 * Format tokens with cost estimate
 * @param {number} tokens - Token count
 * @returns {object} Object with formatted tokens and cost
 */
export const formatTokensWithCost = (tokens) => {
  const formattedTokens = formatTokens(tokens)
  const cost = calculateCost(tokens)
  const formattedCost = formatCost(cost)

  return {
    tokens: formattedTokens,
    cost: formattedCost,
    rawCost: cost,
  }
}
