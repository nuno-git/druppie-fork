/**
 * TypingIndicator - Shows agent working state with expandable live event feed
 * Enhanced with current action display and better visual feedback
 */

import React, { useState } from 'react'
import {
  Bot,
  Loader2,
  StopCircle,
  ChevronDown,
  ChevronUp,
  Hammer,
  FileCode,
  Terminal,
  GitBranch,
  CheckCircle,
} from 'lucide-react'
import { getAgentConfig, getAgentColorClasses, getAgentMessageColors } from '../../utils/agentConfig'

// Get icon for tool type
const getToolIcon = (toolName) => {
  if (!toolName) return Hammer
  if (toolName.includes('write_file') || toolName.includes('batch_write')) return FileCode
  if (toolName.includes('run_command') || toolName.includes('run_tests')) return Terminal
  if (toolName.includes('commit') || toolName.includes('git')) return GitBranch
  return Hammer
}

const TypingIndicator = ({ currentStep, liveEvents = [], onStop, isStopping = false, agentId = null }) => {
  const [confirmStop, setConfirmStop] = useState(false)
  const [expanded, setExpanded] = useState(true) // Start expanded to show activity

  // Find the current active agent from events or use the passed agentId
  const activeAgentEvent = liveEvents.filter(e => e.event_type === 'agent_started' || e.data?.agent_id).pop()
  const activeAgent = activeAgentEvent?.data?.agent_id || agentId
  const agentConfig = activeAgent ? getAgentConfig(activeAgent) : null
  const AgentIcon = agentConfig?.icon || Bot
  const colors = agentConfig ? getAgentMessageColors(agentConfig.color) : null

  // Find the current tool being used
  const currentToolEvent = liveEvents.filter(e =>
    (e.event_type || e.type || '').includes('tool_call')
  ).pop()
  const currentTool = currentToolEvent?.data?.tool || currentToolEvent?.tool
  const ToolIcon = currentTool ? getToolIcon(currentTool) : null

  return (
    <div className="flex justify-start mb-4">
      <div className={`border-2 rounded-2xl rounded-bl-none px-4 py-3 shadow-sm min-w-[300px] ${
        colors ? `${colors.bg} ${colors.border}` : 'bg-white border-gray-200'
      }`}>
        {/* Header - agent info + spinner */}
        <div className="flex items-center gap-3">
          <div className={`w-9 h-9 rounded-full flex items-center justify-center ${
            colors ? `${colors.bg} border-2 ${colors.border}` : 'bg-blue-100 border-2 border-blue-200'
          }`}>
            <AgentIcon className={`w-5 h-5 ${colors?.accent || 'text-blue-600'}`} />
          </div>
          <div className="flex-1">
            <div className="flex items-center gap-2">
              <Loader2 className="w-4 h-4 text-blue-500 animate-spin" />
              <span className="text-sm font-semibold text-gray-800">
                {agentConfig ? agentConfig.name : 'Agent'} is working...
              </span>
            </div>
            {currentStep && (
              <div className="text-xs text-gray-500 mt-0.5">{currentStep}</div>
            )}
          </div>

          {/* Expand/collapse toggle */}
          {liveEvents.length > 0 && (
            <button
              onClick={() => setExpanded(!expanded)}
              className="p-1.5 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded transition-colors"
              title={expanded ? 'Hide activity' : 'Show activity'}
            >
              {expanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
            </button>
          )}

          {/* Compact stop button */}
          {onStop && !confirmStop && (
            <button
              onClick={() => setConfirmStop(true)}
              className="p-1.5 text-gray-400 hover:text-red-500 hover:bg-red-50 rounded transition-colors"
              title="Stop execution"
            >
              <StopCircle className="w-4 h-4" />
            </button>
          )}
        </div>

        {/* Current tool indicator */}
        {currentTool && (
          <div className="flex items-center gap-2 mt-2 px-2 py-1.5 bg-purple-50 border border-purple-200 rounded-lg">
            <ToolIcon className="w-4 h-4 text-purple-600" />
            <span className="text-xs font-medium text-purple-700">
              Using: <code className="bg-purple-100 px-1 rounded">{currentTool}</code>
            </span>
          </div>
        )}

        {/* Stop confirmation */}
        {confirmStop && (
          <div className="flex items-center gap-2 mt-3 pt-3 border-t border-gray-200">
            <span className="text-xs text-red-600 font-medium">Stop execution?</span>
            <button
              onClick={() => {
                onStop()
                setConfirmStop(false)
              }}
              disabled={isStopping}
              className="px-3 py-1 text-xs bg-red-500 text-white rounded-lg hover:bg-red-600 disabled:opacity-50 font-medium"
            >
              {isStopping ? 'Stopping...' : 'Yes, Stop'}
            </button>
            <button
              onClick={() => setConfirmStop(false)}
              disabled={isStopping}
              className="px-3 py-1 text-xs bg-gray-200 text-gray-700 rounded-lg hover:bg-gray-300 font-medium"
            >
              Cancel
            </button>
          </div>
        )}

        {/* Expanded live event feed */}
        {expanded && liveEvents.length > 0 && (
          <div className="mt-3 pt-3 border-t border-gray-200 max-h-56 overflow-y-auto">
            <div className="text-xs font-semibold text-gray-500 mb-2">Activity Log:</div>
            <div className="space-y-1.5">
              {liveEvents.slice(-8).map((event, idx) => {
                const eventType = event.event_type || event.type || ''
                const isComplete = eventType.includes('completed') || eventType.includes('success')
                const isTool = eventType.includes('tool')
                const isError = eventType.includes('error') || eventType.includes('failed')

                return (
                  <div
                    key={idx}
                    className={`flex items-center gap-2 px-2 py-1 rounded text-xs ${
                      isComplete ? 'bg-green-50 text-green-700' :
                      isError ? 'bg-red-50 text-red-700' :
                      isTool ? 'bg-purple-50 text-purple-700' :
                      'bg-gray-50 text-gray-600'
                    }`}
                  >
                    {isComplete ? (
                      <CheckCircle className="w-3 h-3 flex-shrink-0" />
                    ) : isTool ? (
                      <Hammer className="w-3 h-3 flex-shrink-0" />
                    ) : (
                      <span className="w-1.5 h-1.5 rounded-full bg-current flex-shrink-0" />
                    )}
                    <span className="truncate font-medium">
                      {event.title || event.displayTitle || eventType}
                    </span>
                    {event.timestamp && (
                      <span className="text-gray-400 ml-auto text-[10px]">
                        {new Date(event.timestamp).toLocaleTimeString()}
                      </span>
                    )}
                  </div>
                )
              })}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

export default TypingIndicator
