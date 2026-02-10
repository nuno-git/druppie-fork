/**
 * WorkflowEvent - Displays a single workflow event with category-based styling
 */

import React, { useState } from 'react'
import {
  Hammer,
  ChevronDown,
  ChevronRight,
  ExternalLink,
  CheckCircle,
  XCircle,
} from 'lucide-react'
import {
  getEventIcon,
  getEventCategory,
  getCategoryStyles,
  formatEventTitle,
  getEventDescription,
} from '../../utils/eventUtils'
import TestResultCard from './TestResultCard'

const WorkflowEvent = ({ event, defaultExpanded = false }) => {
  const [isExpanded, setIsExpanded] = useState(defaultExpanded)
  const eventType = event.event_type || event.type || ''
  const category = getEventCategory(eventType)
  const styles = getCategoryStyles(category, event.status)
  const displayTitle = event.title || formatEventTitle({ ...event, event_type: eventType })
  const displayDescription = event.description || getEventDescription({ ...event, event_type: eventType })
  const hasToolArgs = event.data?.args || event.data?.arguments || event.data?.args_preview
  const hasToolResult = event.data?.result || event.data?.output
  const hasExpandableContent = hasToolArgs || hasToolResult || (event.data?.error && event.data.error.length > 50)
  const isToolEvent = category === 'tool'

  const formatArgs = (args) => {
    if (!args) return null
    if (typeof args === 'string') return args.length > 100 ? args.substring(0, 100) + '...' : args
    try {
      const str = JSON.stringify(args, null, 2)
      return str.length > 200 ? str.substring(0, 200) + '...' : str
    } catch {
      return String(args)
    }
  }

  // Check if this is a test result event
  const isTestResultEvent = category === 'test' && 
    (eventType === 'test_result' || eventType === 'test_completed' || eventType === 'tdd_validation')

  // If it's a test result event, render the TestResultCard
  if (isTestResultEvent) {
    const testResultData = {
      ...event.data,
      verdict: event.data?.verdict || event.data?.status,
      summary: event.data?.summary,
      coverage: event.data?.coverage,
      retry_count: event.data?.retry_count,
      max_retries: event.data?.max_retries,
      feedback: event.data?.feedback,
      framework: event.data?.framework,
      duration_ms: event.data?.duration_ms,
      should_retry: event.data?.should_retry,
      next_action: event.data?.next_action,
    }
    return <TestResultCard testResult={testResultData} defaultExpanded={defaultExpanded} />
  }

  return (
    <div className={`flex items-start gap-2 p-2.5 rounded-lg border ${styles.bg} ${styles.border} ${styles.text} mb-1.5 transition-all`}>
      <div className={`p-1.5 rounded-full ${styles.iconBg} ${styles.iconText} flex-shrink-0`}>
        {getEventIcon(eventType, event.status)}
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className={`text-[10px] uppercase font-semibold px-1.5 py-0.5 rounded ${styles.badge}`}>
            {category}
          </span>
          <span className="font-medium text-sm">{displayTitle}</span>
          {event.data?.agent_id && (
            <span className="text-xs bg-purple-100 text-purple-700 px-1.5 py-0.5 rounded-full font-medium">
              {event.data.agent_id.replace('_agent', '')}
            </span>
          )}
          {event.data?.duration_ms && (
            <span className="text-xs text-gray-500 font-mono">{event.data.duration_ms}ms</span>
          )}
          {event.status === 'success' && <CheckCircle className="w-3.5 h-3.5 text-green-500" />}
          {event.status === 'error' && <XCircle className="w-3.5 h-3.5 text-red-500" />}
        </div>
        {displayDescription && <div className="text-xs opacity-80 mt-1">{displayDescription}</div>}
        {isToolEvent && (event.data?.tool || event.data?.tool_name) && (
          <div className="flex items-center gap-2 mt-1.5">
            <span className="inline-flex items-center gap-1 bg-orange-200 text-orange-800 px-2 py-0.5 rounded text-xs font-mono">
              <Hammer className="w-3 h-3" />
              {event.data.tool || event.data.tool_name}
            </span>
            {hasExpandableContent && (
              <button onClick={() => setIsExpanded(!isExpanded)} className="text-xs text-gray-500 hover:text-gray-700 flex items-center gap-1">
                {isExpanded ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
                {isExpanded ? 'Hide' : 'Show'} details
              </button>
            )}
          </div>
        )}
        {isExpanded && hasExpandableContent && (
          <div className="mt-2 space-y-2">
            {hasToolArgs && (
              <div className="bg-gray-900 rounded p-2 text-xs">
                <div className="text-gray-400 text-[10px] uppercase mb-1">Arguments</div>
                <pre className="text-green-400 font-mono whitespace-pre-wrap overflow-x-auto">
                  {formatArgs(event.data?.args || event.data?.arguments || event.data?.args_preview)}
                </pre>
              </div>
            )}
            {hasToolResult && (
              <div className={`rounded p-2 text-xs ${event.status === 'error' ? 'bg-red-900' : 'bg-gray-900'}`}>
                <div className={`text-[10px] uppercase mb-1 ${event.status === 'error' ? 'text-red-400' : 'text-gray-400'}`}>
                  {event.status === 'error' ? 'Error' : 'Result'}
                </div>
                <pre className={`font-mono whitespace-pre-wrap overflow-x-auto ${event.status === 'error' ? 'text-red-400' : 'text-blue-400'}`}>
                  {formatArgs(event.data?.result || event.data?.output)}
                </pre>
              </div>
            )}
            {event.data?.error && !hasToolResult && (
              <div className="bg-red-900 rounded p-2 text-xs">
                <div className="text-red-400 text-[10px] uppercase mb-1">Error</div>
                <pre className="text-red-300 font-mono whitespace-pre-wrap overflow-x-auto">{event.data.error}</pre>
              </div>
            )}
          </div>
        )}
        {event.data?.tool_calls && event.data.tool_calls.length > 0 && (
          <div className="text-xs mt-1.5 flex flex-wrap gap-1">
            <span className="text-gray-500 mr-1">Tools:</span>
            {event.data.tool_calls.map((tc, i) => (
              <span key={i} className="inline-flex items-center gap-1 bg-orange-100 text-orange-700 px-1.5 py-0.5 rounded font-mono">
                <Hammer className="w-2.5 h-2.5" />
                {typeof tc === 'string' ? tc : tc.name || tc}
              </span>
            ))}
          </div>
        )}
        {event.data?.repo_url && (
          <a href={event.data.repo_url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-xs mt-1.5 text-blue-600 hover:underline font-medium">
            <ExternalLink className="w-3 h-3" />
            View Repository
          </a>
        )}
        {event.data?.url && (
          <a href={event.data.url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-xs mt-1.5 text-green-600 hover:underline font-medium">
            <ExternalLink className="w-3 h-3" />
            Open App
          </a>
        )}
        {event.data?.features && event.data.features.length > 0 && (
          <div className="text-xs mt-1 opacity-70">Features: {event.data.features.join(', ')}</div>
        )}
      </div>
    </div>
  )
}

export default WorkflowEvent
