/**
 * SandboxEventCard - Expandable card displaying sandbox session events.
 *
 * Props: { sandboxResults: Array } where each element is the raw execute_coding_task result:
 * { success, sandbox_session_id, changed_files, elapsed_seconds, agent_output }
 */

import { useState } from 'react'
import {
  ChevronDown,
  ChevronRight,
  Terminal,
  FileCode,
  Clock,
  Loader2,
  MessageSquare,
  Wrench,
  User,
  Bot,
} from 'lucide-react'
import { getSandboxEvents } from '../../services/api'

const formatTime = (sec) => {
  if (sec == null) return null
  return sec >= 60 ? `${(sec / 60).toFixed(1)}m` : `${sec.toFixed(1)}s`
}

/** Parse the ---SUMMARY--- block from agent_output if present */
const parseSummary = (agentOutput) => {
  if (!agentOutput) return null
  const match = agentOutput.match(/---SUMMARY---([\s\S]*?)---END SUMMARY---/)
  if (!match) return null
  return match[1].trim()
}

/** Categorize an event by its type for display */
const getEventCategory = (event) => {
  const type = event.type || event.event_type || ''
  if (type.includes('tool_call') || type.includes('tool_use')) return 'tool'
  if (type.includes('text') || type.includes('message') || type.includes('output')) return 'output'
  if (type.includes('file') || type.includes('write') || type.includes('edit')) return 'file'
  if (type.includes('command') || type.includes('bash') || type.includes('exec')) return 'command'
  return 'other'
}

const categoryColors = {
  tool: 'text-blue-600 bg-blue-50',
  output: 'text-gray-600 bg-gray-50',
  file: 'text-emerald-600 bg-emerald-50',
  command: 'text-amber-600 bg-amber-50',
  other: 'text-gray-500 bg-gray-50',
}

const EventItem = ({ event, index }) => {
  const [showDetail, setShowDetail] = useState(false)
  const category = getEventCategory(event)
  const colors = categoryColors[category]
  const type = event.type || event.event_type || 'event'
  const timestamp = event.timestamp || event.created_at
  const timeStr = timestamp ? new Date(timestamp).toLocaleTimeString() : null
  const content = event.content || event.data || event.message || event.text

  return (
    <div className="py-1.5 border-b border-gray-100 last:border-0">
      <div
        className="flex items-center gap-2 cursor-pointer hover:bg-gray-50 rounded px-1 -mx-1"
        onClick={() => content && setShowDetail(!showDetail)}
      >
        <span className="text-xs text-gray-300 w-6 text-right flex-shrink-0">{index + 1}</span>
        <span className={`text-xs px-1.5 py-0.5 rounded font-medium ${colors}`}>
          {type}
        </span>
        {timeStr && <span className="text-xs text-gray-400">{timeStr}</span>}
        {content && (
          <span className="text-xs text-gray-400 ml-auto">
            {showDetail ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
          </span>
        )}
      </div>
      {showDetail && content && (
        <pre className="mt-1 ml-8 p-2 bg-gray-900 rounded text-xs text-gray-300 font-mono whitespace-pre-wrap overflow-x-auto max-h-48 overflow-y-auto">
          {typeof content === 'string' ? content : JSON.stringify(content, null, 2)}
        </pre>
      )}
    </div>
  )
}

const ConversationPart = ({ part }) => {
  const [expanded, setExpanded] = useState(false)
  const type = part.type || ''

  if (type === 'text') {
    const text = part.text || ''
    if (!text) return null
    return (
      <pre className="text-xs text-gray-700 bg-white rounded p-2 whitespace-pre-wrap font-mono border border-gray-100">
        {text}
      </pre>
    )
  }

  if (type === 'tool-invocation' || type === 'tool-result') {
    const toolName = part.toolInvocation?.toolName || part.toolName || 'tool'
    const args = part.toolInvocation?.args || part.args
    const output = part.toolInvocation?.result || part.output || part.result
    return (
      <div className="border border-gray-200 rounded">
        <div
          className="flex items-center gap-1.5 px-2 py-1 cursor-pointer hover:bg-gray-50"
          onClick={() => setExpanded(!expanded)}
        >
          <Wrench className="w-3 h-3 text-blue-500 flex-shrink-0" />
          <span className="text-xs font-medium text-blue-700">{toolName}</span>
          <span className="text-xs text-gray-400 ml-auto">
            {expanded ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
          </span>
        </div>
        {expanded && (
          <div className="border-t border-gray-100 px-2 py-1.5 space-y-1.5">
            {args && (
              <div>
                <div className="text-[10px] font-medium text-gray-400 uppercase mb-0.5">Args</div>
                <pre className="text-xs text-gray-600 bg-gray-50 rounded p-1.5 font-mono whitespace-pre-wrap overflow-x-auto max-h-32 overflow-y-auto">
                  {typeof args === 'string' ? args : JSON.stringify(args, null, 2)}
                </pre>
              </div>
            )}
            {output && (
              <div>
                <div className="text-[10px] font-medium text-gray-400 uppercase mb-0.5">Output</div>
                <pre className="text-xs text-gray-600 bg-gray-50 rounded p-1.5 font-mono whitespace-pre-wrap overflow-x-auto max-h-32 overflow-y-auto">
                  {typeof output === 'string' ? output : JSON.stringify(output, null, 2)}
                </pre>
              </div>
            )}
          </div>
        )}
      </div>
    )
  }

  if (type === 'step-start' || type === 'step-finish') {
    return (
      <div className="text-[10px] text-gray-400 italic">
        {type === 'step-start' ? 'Step started' : 'Step finished'}
        {part.cost != null && ` · $${part.cost.toFixed(4)}`}
      </div>
    )
  }

  return null
}

const ConversationMessage = ({ message }) => {
  const isUser = message.role === 'user'
  const Icon = isUser ? User : Bot
  const parts = message.parts || []

  return (
    <div className={`flex gap-2 ${isUser ? '' : 'bg-gray-50 rounded'} p-2`}>
      <div className={`flex-shrink-0 w-5 h-5 rounded-full flex items-center justify-center ${isUser ? 'bg-gray-200' : 'bg-blue-100'}`}>
        <Icon className={`w-3 h-3 ${isUser ? 'text-gray-600' : 'text-blue-600'}`} />
      </div>
      <div className="flex-1 min-w-0 space-y-1.5">
        <div className="text-[10px] font-medium text-gray-400 uppercase">{isUser ? 'User' : 'Assistant'}</div>
        {parts.map((part, i) => (
          <ConversationPart key={i} part={part} />
        ))}
        {parts.length === 0 && (
          <div className="text-xs text-gray-400 italic">No content</div>
        )}
      </div>
    </div>
  )
}

const ConversationTimeline = ({ events }) => {
  const [showConversation, setShowConversation] = useState(false)

  if (!events) return null

  const convEvent = events.find((e) => {
    const type = e.type || e.event_type || ''
    if (type === 'conversation_history') return true
    const data = e.data || {}
    const dataType = typeof data === 'string' ? (() => { try { return JSON.parse(data) } catch { return {} } })().type : data.type
    return dataType === 'conversation_history'
  })

  if (!convEvent) return null

  let messages = convEvent.messages
  if (!messages) {
    const data = typeof convEvent.data === 'string' ? JSON.parse(convEvent.data) : (convEvent.data || {})
    messages = data.messages || []
  }

  if (!messages.length) return null

  return (
    <div className="mt-2">
      <button
        onClick={() => setShowConversation(!showConversation)}
        className="flex items-center gap-1 text-xs text-gray-400 hover:text-gray-600 transition-colors"
      >
        {showConversation ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
        <MessageSquare className="w-3 h-3" />
        {showConversation ? 'Hide conversation' : 'Show full conversation'}
        <span className="text-gray-300 ml-1">({messages.length} messages)</span>
      </button>

      {showConversation && (
        <div className="mt-2 space-y-1 max-h-[600px] overflow-y-auto border border-gray-200 rounded-lg">
          {messages.map((msg, i) => (
            <ConversationMessage key={msg.id || i} message={msg} />
          ))}
        </div>
      )}
    </div>
  )
}

const SandboxSessionSection = ({ result }) => {
  const [events, setEvents] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [showEvents, setShowEvents] = useState(false)

  const summary = parseSummary(result.agent_output)
  const changedFiles = result.changed_files || []

  const fetchEvents = async () => {
    if (events) {
      setShowEvents(!showEvents)
      return
    }
    setLoading(true)
    setError(null)
    try {
      const data = await getSandboxEvents(result.sandbox_session_id)
      const raw = Array.isArray(data) ? data : data.events || []
      // API returns newest-first; reverse for chronological display
      setEvents([...raw].reverse())
      setShowEvents(true)
    } catch (e) {
      setError(e.message || 'Failed to load events')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="py-2">
      {/* Changed files */}
      {changedFiles.length > 0 && (
        <div className="flex flex-wrap gap-1 mb-2">
          {changedFiles.map((f, i) => {
            const rawName = typeof f === 'string' ? f : f.path || f.name || JSON.stringify(f)
            const name = rawName.replace(/^\/workspace\/[^/]+\//, '')
            const action = typeof f === 'object' ? f.action : null
            return (
              <span key={i} className="inline-flex items-center gap-1 text-xs bg-gray-100 text-gray-600 px-1.5 py-0.5 rounded">
                <FileCode className="w-3 h-3" />
                {name}
                {action && <span className="text-gray-400">({action})</span>}
              </span>
            )
          })}
        </div>
      )}

      {/* Structured summary */}
      {summary && (
        <pre className="text-xs text-gray-600 bg-gray-50 rounded p-2 mb-2 whitespace-pre-wrap font-mono">
          {summary}
        </pre>
      )}

      {/* Events toggle */}
      <button
        onClick={fetchEvents}
        disabled={loading}
        className="flex items-center gap-1 text-xs text-gray-400 hover:text-gray-600 transition-colors"
      >
        {loading ? (
          <Loader2 className="w-3 h-3 animate-spin" />
        ) : showEvents ? (
          <ChevronDown className="w-3 h-3" />
        ) : (
          <ChevronRight className="w-3 h-3" />
        )}
        <Terminal className="w-3 h-3" />
        {loading ? 'Loading events...' : showEvents ? 'Hide events' : 'Show sandbox events'}
      </button>

      {error && (
        <div className="mt-1 text-xs text-red-500">{error}</div>
      )}

      {/* Conversation timeline (from conversation_history event) */}
      {showEvents && events && <ConversationTimeline events={events} />}

      {/* Events timeline */}
      {showEvents && events && (
        <div className="mt-2 max-h-96 overflow-y-auto">
          {events.length === 0 ? (
            <div className="text-xs text-gray-400 italic">No events recorded</div>
          ) : (
            events.map((event, i) => (
              <EventItem key={i} event={event} index={i} />
            ))
          )}
        </div>
      )}
    </div>
  )
}

const SandboxEventCard = ({ sandboxResults }) => {
  const [isExpanded, setIsExpanded] = useState(false)

  if (!sandboxResults?.length) return null

  // Aggregate stats
  const totalFiles = new Set(sandboxResults.flatMap((r) => r.changed_files || [])).size
  const totalTime = sandboxResults.reduce((sum, r) => sum + (r.elapsed_seconds || 0), 0)
  const allSuccess = sandboxResults.every((r) => r.success)

  const summaryParts = []
  if (totalFiles > 0) summaryParts.push(`${totalFiles} file${totalFiles !== 1 ? 's' : ''} changed`)
  if (totalTime > 0) summaryParts.push(formatTime(totalTime))
  summaryParts.push(`${sandboxResults.length} session${sandboxResults.length !== 1 ? 's' : ''}`)

  return (
    <div className={`rounded-xl border bg-gray-50 border-gray-200 border-l-4 ${allSuccess ? 'border-l-blue-500' : 'border-l-amber-500'} transition-all`}>
      {/* Header */}
      <div className="px-4 pt-3 pb-1">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Terminal className={`w-4 h-4 ${allSuccess ? 'text-blue-500' : 'text-amber-500'}`} />
            <span className="text-sm font-medium text-gray-800">Sandbox Session</span>
          </div>
          <button
            onClick={() => setIsExpanded(!isExpanded)}
            className="flex items-center gap-1 text-xs text-gray-400 hover:text-gray-600 transition-colors"
          >
            {isExpanded ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
            {isExpanded ? 'Collapse' : 'Details'}
          </button>
        </div>

        {/* Summary line */}
        <div className="mt-1.5 pb-2 flex items-center gap-1 text-xs text-gray-500 flex-wrap">
          {summaryParts.map((part, i) => (
            <span key={i} className="flex items-center gap-1">
              {i > 0 && <span className="text-gray-300">&middot;</span>}
              {part}
            </span>
          ))}
        </div>
      </div>

      {/* Expanded details */}
      {isExpanded && (
        <div className="px-4 pb-3 border-t border-gray-200">
          <div className="divide-y divide-gray-100">
            {sandboxResults.map((result, i) => (
              <SandboxSessionSection key={i} result={result} />
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

export default SandboxEventCard
