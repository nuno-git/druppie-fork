/**
 * TypingIndicator - Shows processing state with real-time workflow steps and stop button
 */

import React, { useState } from 'react'
import {
  Bot,
  Brain,
  Clock,
  Zap,
  Hammer,
  CheckCircle,
  Loader2,
  StopCircle,
  XCircle,
} from 'lucide-react'
import { getEventCategory, getCategoryStyles, formatEventTitle } from '../../utils/eventUtils'
import { getAgentConfig, getAgentColorClasses } from '../../utils/agentConfig'

const TypingIndicator = ({ currentStep, liveEvents = [], onStop, isStopping = false }) => {
  const [confirmStop, setConfirmStop] = useState(false)
  // Process live events to show completed and current steps
  const processedEvents = liveEvents.map((event, index) => {
    const isLast = index === liveEvents.length - 1
    const category = getEventCategory(event.event_type || event.type || '')
    return {
      ...event,
      displayTitle: formatEventTitle(event),
      isComplete: !isLast || event.status === 'success',
      isCurrent: isLast && event.status !== 'success',
      category,
    }
  })

  // Deduplicate consecutive similar events
  const uniqueEvents = processedEvents.reduce((acc, event) => {
    const lastEvent = acc[acc.length - 1]
    if (!lastEvent || lastEvent.displayTitle !== event.displayTitle) {
      acc.push(event)
    } else if (event.isComplete && !lastEvent.isComplete) {
      acc[acc.length - 1] = { ...lastEvent, isComplete: true, isCurrent: false }
    }
    return acc
  }, [])

  // Keep last 8 events for display
  const displayEvents = uniqueEvents.slice(-8)

  // Find the current active agent
  const activeAgentEvent = liveEvents.filter(e => e.event_type === 'agent_started' || e.data?.agent_id).pop()
  const activeAgent = activeAgentEvent?.data?.agent_id
  const agentConfig = activeAgent ? getAgentConfig(activeAgent) : null
  const AgentIcon = agentConfig?.icon || Bot

  // Count stats
  const toolCalls = liveEvents.filter(e => e.event_type?.includes('tool_')).length
  const llmCalls = liveEvents.filter(e => e.event_type?.includes('llm_')).length

  return (
    <div className="flex justify-start mb-4">
      <div className="bg-white border-2 border-blue-200 rounded-2xl rounded-bl-none px-5 py-4 shadow-lg min-w-[380px] max-w-[480px]">
        {/* Prominent Working Header */}
        <div className="flex items-center gap-4 mb-4 pb-4 border-b border-gray-100">
          <div className="relative">
            <div className={`w-12 h-12 rounded-full flex items-center justify-center ${
              agentConfig ? getAgentColorClasses(agentConfig.color).replace('border-', 'bg-').split(' ')[0] : 'bg-gradient-to-br from-blue-500 to-purple-600'
            }`}>
              {agentConfig ? (
                <AgentIcon className="w-6 h-6" />
              ) : (
                <Loader2 className="w-6 h-6 text-white animate-spin" />
              )}
            </div>
            <span className="absolute -bottom-1 -right-1 w-4 h-4 bg-green-500 rounded-full border-2 border-white flex items-center justify-center">
              <Loader2 className="w-2.5 h-2.5 text-white animate-spin" />
            </span>
          </div>
          <div className="flex-1">
            <div className="flex items-center gap-2">
              {agentConfig && (
                <span className={`px-2.5 py-1 rounded-full text-xs font-semibold ${getAgentColorClasses(agentConfig.color)}`}>
                  {agentConfig.name}
                </span>
              )}
              <span className="text-sm font-semibold text-gray-800">
                {agentConfig ? 'is working...' : 'Processing...'}
              </span>
            </div>
            <div className="text-xs text-gray-500 mt-0.5">
              {agentConfig?.description || currentStep || 'Analyzing your request'}
            </div>
            {/* Mini stats */}
            {(toolCalls > 0 || llmCalls > 0) && (
              <div className="flex gap-2 mt-2">
                {llmCalls > 0 && (
                  <span className="text-[10px] bg-indigo-100 text-indigo-700 px-1.5 py-0.5 rounded flex items-center gap-1">
                    <Brain className="w-2.5 h-2.5" /> {llmCalls} LLM
                  </span>
                )}
                {toolCalls > 0 && (
                  <span className="text-[10px] bg-orange-100 text-orange-700 px-1.5 py-0.5 rounded flex items-center gap-1">
                    <Hammer className="w-2.5 h-2.5" /> {toolCalls} tools
                  </span>
                )}
              </div>
            )}
          </div>
        </div>

        {/* Stop button */}
        {onStop && (
          <div className="mb-3 pb-3 border-b border-gray-100">
            {confirmStop ? (
              <div className="flex items-center justify-between bg-red-50 rounded-lg px-3 py-2">
                <span className="text-sm text-red-700">Stop execution?</span>
                <div className="flex gap-2">
                  <button
                    onClick={() => {
                      onStop()
                      setConfirmStop(false)
                    }}
                    disabled={isStopping}
                    className="px-3 py-1 text-sm font-medium bg-red-500 text-white rounded hover:bg-red-600 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-1"
                  >
                    {isStopping ? (
                      <>
                        <Loader2 className="w-3 h-3 animate-spin" />
                        Stopping...
                      </>
                    ) : (
                      <>
                        <XCircle className="w-3 h-3" />
                        Yes, stop
                      </>
                    )}
                  </button>
                  <button
                    onClick={() => setConfirmStop(false)}
                    disabled={isStopping}
                    className="px-3 py-1 text-sm font-medium bg-gray-200 text-gray-700 rounded hover:bg-gray-300 disabled:opacity-50"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            ) : (
              <button
                onClick={() => setConfirmStop(true)}
                className="w-full flex items-center justify-center gap-2 px-4 py-2 text-sm font-medium text-gray-600 bg-gray-100 rounded-lg hover:bg-red-100 hover:text-red-600 transition-colors"
              >
                <StopCircle className="w-4 h-4" />
                Stop Execution
              </button>
            )}
          </div>
        )}

        {/* Live progress steps with category colors */}
        {displayEvents.length > 0 ? (
          <div className="space-y-2 pl-3 border-l-2 border-blue-200 ml-1 max-h-64 overflow-y-auto">
            {displayEvents.map((event, idx) => {
              const catStyles = getCategoryStyles(event.category, event.status)
              return (
                <div
                  key={idx}
                  className={`flex items-center gap-2 text-sm transition-all duration-300 ${
                    event.isCurrent ? 'text-blue-700 font-medium' : event.isComplete ? 'text-gray-600' : 'text-gray-400'
                  }`}
                >
                  {event.isCurrent ? (
                    <Loader2 className="w-4 h-4 animate-spin text-blue-500 flex-shrink-0" />
                  ) : event.isComplete ? (
                    <CheckCircle className="w-4 h-4 text-green-500 flex-shrink-0" />
                  ) : (
                    <div className="w-4 h-4 rounded-full border-2 border-gray-300 flex-shrink-0" />
                  )}
                  <span className={`text-[10px] uppercase font-semibold px-1 py-0.5 rounded ${catStyles.badge}`}>
                    {event.category}
                  </span>
                  <span className="truncate flex-1">{event.displayTitle}</span>
                </div>
              )
            })}
          </div>
        ) : (
          /* Fallback: Generic progress steps when no live events */
          <div className="flex items-center justify-between px-2 pt-2">
            {[
              { id: 'analyzing', label: 'Analyzing', icon: Brain, color: 'purple' },
              { id: 'planning', label: 'Planning', icon: Clock, color: 'blue' },
              { id: 'executing', label: 'Executing', icon: Zap, color: 'green' },
            ].map((step, idx) => {
              const StepIcon = step.icon
              const stepLower = (currentStep || '').toLowerCase()
              let isActive = false
              let isComplete = false

              if (stepLower.includes('analyz') || stepLower.includes('router')) {
                isActive = idx === 0
              } else if (stepLower.includes('plan')) {
                isComplete = idx === 0
                isActive = idx === 1
              } else if (stepLower.includes('execut') || stepLower.includes('generat') || stepLower.includes('develop')) {
                isComplete = idx < 2
                isActive = idx === 2
              }

              return (
                <div key={step.id} className="flex items-center">
                  <div className="flex flex-col items-center">
                    <div
                      className={`w-10 h-10 rounded-full flex items-center justify-center transition-all ${
                        isActive
                          ? `bg-${step.color}-500 text-white shadow-lg shadow-${step.color}-200`
                          : isComplete
                          ? 'bg-green-500 text-white'
                          : 'bg-gray-200 text-gray-400'
                      }`}
                    >
                      {isComplete ? (
                        <CheckCircle className="w-5 h-5" />
                      ) : isActive ? (
                        <Loader2 className="w-5 h-5 animate-spin" />
                      ) : (
                        <StepIcon className="w-5 h-5" />
                      )}
                    </div>
                    <span className={`text-xs mt-1.5 font-medium ${isActive ? `text-${step.color}-600` : isComplete ? 'text-green-600' : 'text-gray-400'}`}>
                      {step.label}
                    </span>
                  </div>
                  {idx < 2 && (
                    <div className={`w-10 h-0.5 mx-2 rounded ${isComplete ? 'bg-green-500' : 'bg-gray-200'}`} />
                  )}
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}

export default TypingIndicator
