/**
 * WorkflowEventMessage - Displays agent lifecycle events (start/complete)
 * Tool calls are now handled by ToolDecisionCard
 */

import React, { useState } from 'react'
import {
  ChevronDown,
  ChevronRight,
  Play,
  CheckCircle,
  Clock,
  Loader2,
} from 'lucide-react'
import { getAgentConfig, getAgentMessageColors } from '../../utils/agentConfig'

const WorkflowEventMessage = ({ event }) => {
  const [expanded, setExpanded] = useState(false)

  const eventType = event.type || event.event_type || ''
  const agentId = event.agent_id || event.agent || event.data?.agent_id
  const agentConfig = agentId ? getAgentConfig(agentId) : null
  const AgentIcon = agentConfig?.icon || Clock
  const colors = agentConfig ? getAgentMessageColors(agentConfig.color) : null

  // Format timestamp
  const timestamp = event.timestamp ? new Date(event.timestamp).toLocaleTimeString() : ''

  // Agent started
  if (eventType === 'agent_started') {
    return (
      <div className="flex justify-start mb-2">
        <div className={`max-w-[90%] rounded-lg px-3 py-2 border ${colors?.bg || 'bg-blue-50'} ${colors?.border || 'border-blue-200'}`}>
          <div className="flex items-center gap-2">
            {agentConfig && (
              <div className={`w-6 h-6 rounded-full flex items-center justify-center ${colors?.bg || 'bg-gray-100'} border ${colors?.border || 'border-gray-200'}`}>
                <AgentIcon className={`w-3.5 h-3.5 ${colors?.accent || 'text-gray-600'}`} />
              </div>
            )}
            <Play className="w-4 h-4 text-blue-500" />
            <Loader2 className="w-3.5 h-3.5 text-blue-500 animate-spin" />
            <span className="text-sm font-medium text-gray-800">
              {agentConfig?.name || agentId || 'Agent'} started working
            </span>
            <span className="text-xs font-bold px-2 py-0.5 rounded-full bg-blue-100 text-blue-700">
              WORKING
            </span>
            {timestamp && (
              <span className="text-xs text-gray-400 ml-auto">{timestamp}</span>
            )}
          </div>
        </div>
      </div>
    )
  }

  // Agent completed
  if (eventType === 'agent_completed') {
    const summary = event.summary || event.data?.summary
    const hasSummary = !!summary

    return (
      <div className="flex justify-start mb-2">
        <div className={`max-w-[90%] rounded-lg px-3 py-2 border ${colors?.bg || 'bg-green-50'} ${colors?.border || 'border-green-200'}`}>
          <div className="flex items-center gap-2">
            {agentConfig && (
              <div className={`w-6 h-6 rounded-full flex items-center justify-center ${colors?.bg || 'bg-gray-100'} border ${colors?.border || 'border-gray-200'}`}>
                <AgentIcon className={`w-3.5 h-3.5 ${colors?.accent || 'text-gray-600'}`} />
              </div>
            )}
            <CheckCircle className="w-4 h-4 text-green-500" />
            <span className="text-sm font-medium text-gray-800">
              {agentConfig?.name || agentId || 'Agent'} finished
            </span>
            <span className="text-xs font-bold px-2 py-0.5 rounded-full bg-green-100 text-green-700">
              DONE
            </span>
            {timestamp && (
              <span className="text-xs text-gray-400 ml-auto">{timestamp}</span>
            )}
            {hasSummary && (
              <button
                onClick={() => setExpanded(!expanded)}
                className="ml-1 p-1 text-gray-400 hover:text-gray-600 hover:bg-gray-200 rounded transition-colors"
              >
                {expanded ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
              </button>
            )}
          </div>
          {expanded && hasSummary && (
            <div className="mt-2 pt-2 border-t border-gray-200 ml-8">
              <div className="text-xs text-gray-600">{summary}</div>
            </div>
          )}
        </div>
      </div>
    )
  }

  // Fallback for other event types (shouldn't happen with new structure)
  return null
}

export default WorkflowEventMessage
