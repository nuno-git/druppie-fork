/**
 * WorkflowTimeline - Collapsible timeline showing agent/LLM activity
 */

import React from 'react'
import {
  ChevronDown,
  ChevronRight,
  Bot,
  Brain,
  Hammer,
  XCircle,
  Loader2,
} from 'lucide-react'
import { processWorkflowEvents } from '../../utils/eventUtils'
import { getAgentConfig, getAgentColorClasses } from '../../utils/agentConfig'
import WorkflowEvent from './WorkflowEvent'

const WorkflowTimeline = ({ events, isExpanded, onToggle, isWorking = false }) => {
  if (!events || events.length === 0) return null

  // Process events to update statuses
  const processedEvents = processWorkflowEvents(events)

  // Count LLM calls, tools, and agents
  const llmCalls = processedEvents.filter(e => e.event_type === 'llm_response' || e.event_type === 'llm_call').length
  const toolCalls = processedEvents.filter(e => e.event_type?.includes('tool_') || e.event_type === 'mcp_tool').length
  const agentsRun = [...new Set(processedEvents.filter(e => e.data?.agent_id).map(e => e.data.agent_id))].length
  const hasErrors = processedEvents.some(e => e.status === 'error')

  // Get the current active agent (from the last agent_started event without a corresponding completed)
  const activeAgentEvent = processedEvents.filter(e => e.event_type === 'agent_started').pop()
  const activeAgent = activeAgentEvent?.data?.agent_id

  return (
    <div className={`mt-3 border-t pt-3 ${isWorking ? 'border-blue-200 bg-blue-50/50 -mx-4 px-4 py-3 rounded-lg' : 'border-gray-100'}`}>
      {/* Working indicator header when active */}
      {isWorking && activeAgent && (
        <div className="flex items-center gap-3 mb-3 pb-3 border-b border-blue-200">
          <div className="relative">
            <div className="w-10 h-10 rounded-full bg-gradient-to-br from-blue-500 to-purple-600 flex items-center justify-center">
              <Loader2 className="w-5 h-5 text-white animate-spin" />
            </div>
            <span className="absolute -bottom-1 -right-1 w-4 h-4 bg-green-500 rounded-full border-2 border-white animate-pulse" />
          </div>
          <div>
            <div className="text-sm font-semibold text-blue-900 flex items-center gap-2">
              <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${getAgentColorClasses(getAgentConfig(activeAgent).color)}`}>
                {getAgentConfig(activeAgent).name}
              </span>
              is working...
            </div>
            <div className="text-xs text-blue-600">{getAgentConfig(activeAgent).description}</div>
          </div>
        </div>
      )}

      <button
        onClick={onToggle}
        className={`flex items-center gap-2 text-sm mb-2 w-full focus:outline-none focus:ring-2 focus:ring-blue-500 rounded ${
          isWorking ? 'text-blue-700 hover:text-blue-900' : 'text-gray-600 hover:text-gray-800'
        }`}
        aria-expanded={isExpanded}
        aria-label={isExpanded ? 'Collapse execution log' : 'Expand execution log'}
      >
        {isExpanded ? <ChevronDown className="w-4 h-4" aria-hidden="true" /> : <ChevronRight className="w-4 h-4" aria-hidden="true" />}
        <span className="font-medium">Execution Log</span>
        <div className="flex items-center gap-2 ml-auto flex-wrap">
          {agentsRun > 0 && (
            <span className="text-xs bg-purple-100 text-purple-700 px-2 py-0.5 rounded-full flex items-center gap-1">
              <Bot className="w-3 h-3" />
              {agentsRun}
            </span>
          )}
          {llmCalls > 0 && (
            <span className="text-xs bg-indigo-100 text-indigo-700 px-2 py-0.5 rounded-full flex items-center gap-1">
              <Brain className="w-3 h-3" />
              {llmCalls}
            </span>
          )}
          {toolCalls > 0 && (
            <span className="text-xs bg-orange-100 text-orange-700 px-2 py-0.5 rounded-full flex items-center gap-1">
              <Hammer className="w-3 h-3" />
              {toolCalls}
            </span>
          )}
          {hasErrors && (
            <span className="text-xs bg-red-100 text-red-700 px-2 py-0.5 rounded-full flex items-center gap-1">
              <XCircle className="w-3 h-3" />
              errors
            </span>
          )}
          <span className="text-xs bg-gray-100 px-2 py-0.5 rounded-full">{processedEvents.length} events</span>
        </div>
      </button>

      {isExpanded && (
        <div className="space-y-1 pl-2 border-l-2 border-blue-200 ml-2 max-h-96 overflow-y-auto">
          {processedEvents.map((event, index) => (
            <WorkflowEvent key={index} event={event} />
          ))}
        </div>
      )}
    </div>
  )
}

export default WorkflowTimeline
