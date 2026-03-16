/**
 * WorkflowPipeline - Read-only horizontal stepper showing agent pipeline
 *
 * Derives agent steps from timeline agent_run entries.
 * Shows: [Agent ✓] → [Agent ⟳] → [Agent ○]
 * Only rendered in Chat mode when there are 2+ agent runs.
 * Detail expansion is handled by AnnotationBar in Annotated mode.
 */

import React, { useState, useEffect, useRef, useCallback } from 'react'
import { Check, Loader2, Circle, Pause } from 'lucide-react'
import { getAgentConfig, getAgentColorClasses, formatToolName } from '../../utils/agentConfig'

const WAITING_STATUSES = new Set([
  'paused_hitl',
  'paused_tool',
  'paused_sandbox',
  'waiting_approval',
  'waiting_answer',
])

const WorkflowPipeline = ({ timeline, hidePending }) => {
  const pillRefs = useRef({})
  const scrollContainerRef = useRef(null)

  // Assign a ref callback for each agent pill
  const setPillRef = useCallback((id, el) => {
    if (el) pillRefs.current[id] = el
    else delete pillRefs.current[id]
  }, [])

  if (!timeline) return null

  // Extract agent runs from timeline
  const allAgentRuns = timeline
    .filter((e) => e.type === 'agent_run' && e.agent_run)
    .map((e) => e.agent_run)

  // Optionally hide pending (not yet started) agents
  const agentRuns = hidePending
    ? allAgentRuns.filter((r) => r.status === 'completed' || r.status === 'running' || r.status === 'failed' || WAITING_STATUSES.has(r.status))
    : allAgentRuns

  // Only show when 2+ agent runs
  if (agentRuns.length < 2) return null

  // Find the active agent (running or waiting) — last one wins
  const activeRunId = (() => {
    for (let i = agentRuns.length - 1; i >= 0; i--) {
      const s = agentRuns[i].status
      if (s === 'running' || WAITING_STATUSES.has(s)) return agentRuns[i].id
    }
    return null
  })()

  return (
    <div className="border-b bg-gray-50 flex-shrink-0 min-w-0 overflow-hidden">
      {/* Pipeline bar */}
      <div ref={scrollContainerRef} className="px-4 py-2 flex items-center gap-1 overflow-x-auto scrollbar-thin">
        {agentRuns.map((run, i) => {
          const config = getAgentConfig(run.agent_id)
          const colorClasses = getAgentColorClasses(config.color)
          const isCompleted = run.status === 'completed'
          const isRunning = run.status === 'running'
          const isWaiting = WAITING_STATUSES.has(run.status)
          const isFailed = run.status === 'failed'
          const isPending = !isCompleted && !isRunning && !isWaiting && !isFailed
          const hasFailedTools = isCompleted && run.llm_calls?.some(llm =>
            llm.tool_calls?.some(tc => tc.status === 'failed')
          )

          return (
            <React.Fragment key={run.id || i}>
              {i > 0 && (
                <span className="text-gray-300 text-xs flex-shrink-0 mx-0.5">&rarr;</span>
              )}
              <div
                ref={(el) => setPillRef(run.id, el)}
                className={`relative inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium border flex-shrink-0 ${colorClasses} ${
                  isPending ? 'opacity-50' : ''
                }`}
              >
                {isCompleted && <Check className="w-3 h-3" />}
                {isRunning && <Loader2 className="w-3 h-3 animate-spin" />}
                {isWaiting && <Pause className="w-3 h-3" />}
                {isFailed && <span className="w-3 h-3 text-red-500">!</span>}
                {isPending && <Circle className="w-3 h-3 opacity-50" />}
                {config.name}
                {hasFailedTools && (
                  <span className="absolute -top-0.5 -right-0.5 w-2 h-2 rounded-full bg-red-500" />
                )}
              </div>
            </React.Fragment>
          )
        })}
      </div>
      {/* Auto-scroll active agent into view */}
      <ActivePillScroller activeRunId={activeRunId} pillRefs={pillRefs} />
    </div>
  )
}

// --- Auto-scroll the active pill into view (effect-only component) ---

const ActivePillScroller = ({ activeRunId, pillRefs }) => {
  useEffect(() => {
    if (!activeRunId) return
    const el = pillRefs.current[activeRunId]
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'center' })
    }
  }, [activeRunId, pillRefs])

  return null
}

// --- Single LLM call row ---

export const LlmCallRow = ({ llm, index, forceOpen }) => {
  const [manualOpen, setManualOpen] = useState(false)
  const toolCount = llm.tool_calls?.length || 0
  const tokens = llm.token_usage?.total_tokens || 0
  const isOpen = forceOpen || manualOpen

  return (
    <div className="border-l-2 border-gray-200 pl-3 py-0.5">
      <button
        onClick={() => toolCount > 0 && setManualOpen(!manualOpen)}
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
      {isOpen && toolCount > 0 && (
        <div className="ml-4 mt-1 space-y-0.5">
          {llm.tool_calls.map((tc, ti) => (
            <ToolCallRow key={tc.id || ti} tc={tc} forceOpen={forceOpen} />
          ))}
        </div>
      )}
    </div>
  )
}

// --- Single tool call row ---

export const ToolCallRow = ({ tc, forceOpen }) => {
  const [manualOpen, setManualOpen] = useState(false)
  const isOpen = forceOpen || manualOpen
  const statusColor = tc.status === 'completed' ? 'text-green-600'
    : tc.status === 'failed' ? 'text-red-600'
    : 'text-gray-500'

  return (
    <div>
      <button
        onClick={() => setManualOpen(!manualOpen)}
        className="flex items-center gap-2 text-xs text-gray-500 hover:text-gray-700 w-full text-left"
      >
        <span className="text-purple-600 font-medium">{formatToolName(tc.tool_name)}</span>
        <span className={statusColor}>{tc.status}</span>
      </button>
      {isOpen && (
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
