/**
 * AnnotationDetail - Expandable inline detail panel for agent LLM calls
 *
 * Reuses LlmCallRow from WorkflowPipeline for consistent light-themed
 * rendering of LLM calls and tool call details.
 */

import { useState } from 'react'
import { ChevronsUpDown } from 'lucide-react'
import { LlmCallRow } from './WorkflowPipeline'
import { getAgentConfig, getAgentMessageColors } from '../../utils/agentConfig'

const AnnotationDetail = ({ run }) => {
  const [allExpanded, setAllExpanded] = useState(false)
  const config = getAgentConfig(run.agent_id)
  const colors = getAgentMessageColors(config.color)
  const llmCalls = run.llm_calls || []
  const totalTokens = run.token_usage?.total_tokens || 0

  if (llmCalls.length === 0) return null

  return (
    <div className={`mt-1 px-3 py-2 rounded-lg border ${colors.bg} ${colors.border} text-sm`}>
      <div className="flex items-center gap-2 mb-1.5">
        <span className="text-xs text-gray-500">
          {llmCalls.length} LLM call{llmCalls.length !== 1 ? 's' : ''}
          {totalTokens > 0 ? ` \u00b7 ${totalTokens.toLocaleString()} tokens` : ''}
        </span>
        <button
          onClick={() => setAllExpanded((v) => !v)}
          className={`inline-flex items-center gap-1 text-[11px] px-1.5 py-0.5 rounded transition-colors ${
            allExpanded
              ? 'bg-gray-200 text-gray-700 hover:bg-gray-300'
              : 'text-gray-400 hover:text-gray-600 hover:bg-white/60'
          }`}
          title={allExpanded ? 'Collapse all tool details' : 'Expand all tool details'}
        >
          <ChevronsUpDown className="w-3 h-3" />
          {allExpanded ? 'Collapse' : 'Expand'}
        </button>
      </div>
      <div className="space-y-1 max-h-80 overflow-y-auto">
        {llmCalls.map((llm, i) => (
          <LlmCallRow key={llm.id || i} llm={llm} index={i} forceOpen={allExpanded} />
        ))}
      </div>
    </div>
  )
}

export default AnnotationDetail
