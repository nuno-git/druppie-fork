/**
 * WorkflowPipeline - Compact horizontal stepper showing agent pipeline
 *
 * Derives agent steps from timeline agent_run entries.
 * Shows: [Agent ✓] → [Agent ⟳] → [Agent ○]
 * Clicking an agent pill expands its LLM call details below the bar.
 * Only rendered when there are 2+ agent runs.
 */

import React, { useState } from 'react'
import { Check, Loader2, Circle, Pause, ChevronDown, ChevronUp } from 'lucide-react'
import { getAgentConfig, getAgentColorClasses, getAgentMessageColors, formatToolName } from '../../utils/agentConfig'

const WAITING_STATUSES = new Set([
  'paused_hitl',
  'paused_tool',
  'waiting_approval',
  'waiting_answer',
])

const WorkflowPipeline = ({ timeline }) => {
  const [expandedRunId, setExpandedRunId] = useState(null)

  if (!timeline) return null

  // Extract agent runs from timeline
  const agentRuns = timeline
    .filter((e) => e.type === 'agent_run' && e.agent_run)
    .map((e) => e.agent_run)

  // Only show when 2+ agent runs
  if (agentRuns.length < 2) return null

  const expandedRun = agentRuns.find((r) => r.id === expandedRunId)

  return (
    <div className="border-b bg-gray-50 flex-shrink-0">
      {/* Pipeline bar */}
      <div className="px-4 py-2 flex items-center gap-1 overflow-x-auto">
        {agentRuns.map((run, i) => {
          const config = getAgentConfig(run.agent_id)
          const colorClasses = getAgentColorClasses(config.color)
          const isCompleted = run.status === 'completed'
          const isRunning = run.status === 'running'
          const isWaiting = WAITING_STATUSES.has(run.status)
          const isFailed = run.status === 'failed'
          const isPending = !isCompleted && !isRunning && !isWaiting && !isFailed
          const llmCount = run.llm_calls?.length || 0
          const isExpanded = expandedRunId === run.id

          return (
            <React.Fragment key={run.id || i}>
              {i > 0 && (
                <span className="text-gray-300 text-xs flex-shrink-0 mx-0.5">&rarr;</span>
              )}
              <button
                onClick={() => llmCount > 0 && setExpandedRunId(isExpanded ? null : run.id)}
                className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium border flex-shrink-0 transition-colors ${colorClasses} ${
                  isPending ? 'opacity-50' : ''
                } ${isExpanded ? 'ring-2 ring-offset-1 ring-gray-300' : ''} ${
                  llmCount > 0 ? 'cursor-pointer hover:opacity-80' : 'cursor-default'
                }`}
              >
                {isCompleted && <Check className="w-3 h-3" />}
                {isRunning && <Loader2 className="w-3 h-3 animate-spin" />}
                {isWaiting && <Pause className="w-3 h-3" />}
                {isFailed && <span className="w-3 h-3 text-red-500">!</span>}
                {isPending && <Circle className="w-3 h-3 opacity-50" />}
                {config.name}
                {llmCount > 0 && (
                  <span className="text-[10px] opacity-60">
                    {isExpanded ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
                  </span>
                )}
              </button>
            </React.Fragment>
          )
        })}
      </div>

      {/* Expanded LLM call details for selected agent */}
      {expandedRun && expandedRun.llm_calls?.length > 0 && (
        <ExpandedRunDetails run={expandedRun} />
      )}
    </div>
  )
}

// --- Expanded detail section for a single agent run ---

const ExpandedRunDetails = ({ run }) => {
  const config = getAgentConfig(run.agent_id)
  const colors = getAgentMessageColors(config.color)
  const totalTokens = run.token_usage?.total_tokens || 0
  const llmCalls = run.llm_calls || []

  return (
    <div className={`px-4 py-3 border-t ${colors.bg} text-sm`}>
      <div className="flex items-center gap-2 mb-2">
        <span className={`font-medium text-xs ${colors.accent}`}>{config.name}</span>
        <span className="text-xs text-gray-500">
          {llmCalls.length} LLM call{llmCalls.length !== 1 ? 's' : ''}
          {totalTokens > 0 ? ` · ${totalTokens.toLocaleString()} tokens` : ''}
        </span>
      </div>
      <div className="space-y-1 max-h-64 overflow-y-auto">
        {llmCalls.map((llm, i) => (
          <LlmCallRow key={llm.id || i} llm={llm} index={i} />
        ))}
      </div>
    </div>
  )
}

// --- Single LLM call row ---

const LlmCallRow = ({ llm, index }) => {
  const [open, setOpen] = useState(false)
  const toolCount = llm.tool_calls?.length || 0
  const tokens = llm.token_usage?.total_tokens || 0

  return (
    <div className="border-l-2 border-gray-200 pl-3 py-0.5">
      <button
        onClick={() => toolCount > 0 && setOpen(!open)}
        className={`flex items-center gap-2 text-xs w-full text-left ${
          toolCount > 0 ? 'cursor-pointer hover:text-gray-700' : 'cursor-default'
        } text-gray-500`}
      >
        <span className="text-gray-400">#{index + 1}</span>
        <code className="text-gray-600">{llm.model}</code>
        {tokens > 0 && <span className="text-gray-400">{tokens.toLocaleString()} tok</span>}
        {toolCount > 0 && (
          <span className="text-purple-600">
            {toolCount} tool{toolCount !== 1 ? 's' : ''}
          </span>
        )}
      </button>
      {open && toolCount > 0 && (
        <div className="ml-4 mt-1 space-y-0.5">
          {llm.tool_calls.map((tc, ti) => (
            <ToolCallRow key={tc.id || ti} tc={tc} />
          ))}
        </div>
      )}
    </div>
  )
}

// --- Single tool call row ---

const ToolCallRow = ({ tc }) => {
  const [open, setOpen] = useState(false)
  const statusColor = tc.status === 'completed' ? 'text-green-600'
    : tc.status === 'failed' ? 'text-red-600'
    : 'text-gray-500'

  return (
    <div>
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-2 text-xs text-gray-500 hover:text-gray-700 w-full text-left"
      >
        <span className="text-purple-600 font-medium">{formatToolName(tc.tool_name)}</span>
        <span className={statusColor}>{tc.status}</span>
      </button>
      {open && (
        <div className="ml-4 mt-1 space-y-1 text-xs">
          {tc.arguments && (
            <details>
              <summary className="text-gray-500 cursor-pointer hover:text-gray-700">Arguments</summary>
              <pre className="mt-1 p-2 bg-white/50 rounded text-xs overflow-auto max-h-40 whitespace-pre-wrap break-all">
                {typeof tc.arguments === 'string' ? tc.arguments : JSON.stringify(tc.arguments, null, 2)}
              </pre>
            </details>
          )}
          {tc.result && (
            <details>
              <summary className="text-gray-500 cursor-pointer hover:text-gray-700">Result</summary>
              <pre className="mt-1 p-2 bg-white/50 rounded text-xs overflow-auto max-h-40 whitespace-pre-wrap break-all">
                {typeof tc.result === 'string' ? tc.result : JSON.stringify(tc.result, null, 2)}
              </pre>
            </details>
          )}
          {tc.error && (
            <div className="p-2 bg-red-50 border border-red-200 rounded text-red-700">
              <strong>Error:</strong> {tc.error}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export default WorkflowPipeline
