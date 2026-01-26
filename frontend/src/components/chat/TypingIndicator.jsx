/**
 * TypingIndicator - Minimal processing state with expandable details
 */

import React, { useState } from 'react'
import {
  Bot,
  Loader2,
  StopCircle,
  XCircle,
  ChevronDown,
  ChevronUp,
} from 'lucide-react'
import { getAgentConfig, getAgentColorClasses } from '../../utils/agentConfig'

const TypingIndicator = ({ currentStep, liveEvents = [], onStop, isStopping = false }) => {
  const [confirmStop, setConfirmStop] = useState(false)
  const [expanded, setExpanded] = useState(false)

  // Find the current active agent
  const activeAgentEvent = liveEvents.filter(e => e.event_type === 'agent_started' || e.data?.agent_id).pop()
  const activeAgent = activeAgentEvent?.data?.agent_id
  const agentConfig = activeAgent ? getAgentConfig(activeAgent) : null
  const AgentIcon = agentConfig?.icon || Bot
  const colorClasses = agentConfig ? getAgentColorClasses(agentConfig.color) : 'bg-blue-100 text-blue-700 border-blue-200'

  return (
    <div className="flex justify-start mb-4">
      <div className="bg-white border border-gray-200 rounded-2xl rounded-bl-none px-4 py-3 shadow-sm">
        {/* Minimal Header - just agent + spinner */}
        <div className="flex items-center gap-3">
          <div className={`w-8 h-8 rounded-full flex items-center justify-center ${colorClasses.split(' ')[0]} border ${colorClasses.split(' ').find(c => c.startsWith('border-')) || 'border-gray-200'}`}>
            <AgentIcon className={`w-4 h-4 ${colorClasses.split(' ').find(c => c.startsWith('text-')) || 'text-gray-600'}`} />
          </div>
          <div className="flex items-center gap-2">
            <Loader2 className="w-4 h-4 text-blue-500 animate-spin" />
            <span className="text-sm text-gray-700">
              {agentConfig ? (
                <><span className="font-medium">{agentConfig.name}</span> is working...</>
              ) : (
                currentStep || 'Processing...'
              )}
            </span>
          </div>

          {/* Expand/collapse toggle when there are events */}
          {liveEvents.length > 0 && (
            <button
              onClick={() => setExpanded(!expanded)}
              className="ml-2 p-1 text-gray-400 hover:text-gray-600 rounded"
            >
              {expanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
            </button>
          )}

          {/* Compact stop button */}
          {onStop && !confirmStop && (
            <button
              onClick={() => setConfirmStop(true)}
              className="ml-2 p-1 text-gray-400 hover:text-red-500 rounded"
              title="Stop execution"
            >
              <StopCircle className="w-4 h-4" />
            </button>
          )}
        </div>

        {/* Stop confirmation */}
        {confirmStop && (
          <div className="flex items-center gap-2 mt-2 pt-2 border-t border-gray-100">
            <span className="text-xs text-red-600">Stop execution?</span>
            <button
              onClick={() => {
                onStop()
                setConfirmStop(false)
              }}
              disabled={isStopping}
              className="px-2 py-1 text-xs bg-red-500 text-white rounded hover:bg-red-600 disabled:opacity-50"
            >
              {isStopping ? 'Stopping...' : 'Yes'}
            </button>
            <button
              onClick={() => setConfirmStop(false)}
              disabled={isStopping}
              className="px-2 py-1 text-xs bg-gray-200 text-gray-700 rounded hover:bg-gray-300"
            >
              No
            </button>
          </div>
        )}

        {/* Expanded details (only when clicked) */}
        {expanded && liveEvents.length > 0 && (
          <div className="mt-3 pt-3 border-t border-gray-100 max-h-48 overflow-y-auto">
            <div className="space-y-1 text-xs text-gray-600">
              {liveEvents.slice(-10).map((event, idx) => (
                <div key={idx} className="flex items-center gap-2">
                  <span className="w-1.5 h-1.5 rounded-full bg-gray-400 flex-shrink-0" />
                  <span className="truncate">{event.title || event.displayTitle || event.event_type}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

export default TypingIndicator
