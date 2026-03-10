/**
 * SandboxEventCard - Expandable card displaying a single sandbox session.
 *
 * Props: { sandboxResult: Object } — a single execute_coding_task result:
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
  Pencil,
  Eye,
  Search,
  TerminalSquare,
  Filter,
  GitBranch,
  MessageCircle,
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

/** Tool categorization for colors and icons */
const getToolCategory = (toolName) => {
  const t = (toolName || '').toLowerCase()
  if (t === 'write' || t === 'write_file' || t === 'batch_write_files') return 'write'
  if (t === 'edit') return 'edit'
  if (t === 'read') return 'read'
  if (t === 'bash') return 'bash'
  if (t === 'glob' || t === 'grep' || t === 'search') return 'search'
  if (t === 'task') return 'task'
  return 'other'
}

const toolCategoryConfig = {
  write:  { colors: 'text-emerald-700 bg-emerald-50', Icon: FileCode },
  edit:   { colors: 'text-amber-700 bg-amber-50', Icon: Pencil },
  read:   { colors: 'text-sky-700 bg-sky-50', Icon: Eye },
  bash:   { colors: 'text-purple-700 bg-purple-50', Icon: TerminalSquare },
  search: { colors: 'text-indigo-700 bg-indigo-50', Icon: Search },
  task:   { colors: 'text-violet-700 bg-violet-50', Icon: GitBranch },
  other:  { colors: 'text-gray-600 bg-gray-100', Icon: Wrench },
}

/** Get a short context hint for a tool call event */
const getToolHint = (data) => {
  if (!data) return null
  const args = data.args || {}
  // For task (subagent) calls, show subagent type + description
  if ((data.tool || '').toLowerCase() === 'task') {
    const parts = []
    if (args.subagent_type) parts.push(args.subagent_type)
    if (args.description) parts.push(args.description)
    const hint = parts.join(': ')
    return hint.length > 80 ? hint.slice(0, 77) + '...' : hint || null
  }
  const filePath = args.filePath || args.path || args.file_path || ''
  if (filePath) return filePath.replace(/^\/workspace\/[^/]+\//, '')
  const cmd = args.command || args.cmd || ''
  if (cmd) return cmd.length > 80 ? cmd.slice(0, 77) + '...' : cmd
  const pattern = args.pattern || args.glob || ''
  if (pattern) return pattern
  return null
}

/**
 * Process raw events into a clean display list:
 * - Filter out step_start/step_finish noise
 * - Deduplicate tool_call pairs (invocation + result) into single entries
 * - Merge result/output back into the invocation event
 */
const processEvents = (rawEvents) => {
  const toolCalls = new Map() // callId -> merged event
  const result = []

  for (const event of rawEvents) {
    const type = event.type || ''
    // Skip noise events
    if (type === 'step_start' || type === 'step_finish' || type === 'heartbeat') continue

    if (type === 'tool_call') {
      const data = event.data || {}
      const callId = data.callId || data.call_id || data.id

      if (callId && toolCalls.has(callId)) {
        // This is the result half — merge output and status into existing entry
        const existing = toolCalls.get(callId)
        // Prefer non-empty output from the result event
        if (data.output && data.output !== existing.data.output) {
          existing.data = { ...existing.data, output: data.output }
        }
        // Always take the latest non-empty status (completed/error overrides pending)
        if (data.status && data.status !== existing.data.status) {
          existing.data = { ...existing.data, status: data.status }
        }
        // Merge args if missing (invocation might have args, result might not)
        if (data.args && Object.keys(data.args).length > 0 && (!existing.data.args || Object.keys(existing.data.args).length === 0)) {
          existing.data = { ...existing.data, args: data.args }
        }
        continue
      }

      // First occurrence — store and add to result
      const entry = { ...event, data: { ...data } }
      if (callId) toolCalls.set(callId, entry)
      result.push(entry)
    } else {
      result.push(event)
    }
  }

  return result
}

/**
 * Group processed events by subagent boundaries.
 * tool_call with tool="task" marks a subagent invocation.
 * - If task errored immediately: push as closed group with 0 events,
 *   subsequent events belong to the main agent (not the failed subagent).
 * - If task is running/completed: capture subsequent events until next task or boundary.
 */
const groupBySubagent = (events) => {
  const groups = []
  let currentSubagent = null
  const boundaryTypes = new Set(['execution_complete', 'conversation_history', 'token_usage'])

  for (const event of events) {
    const type = event.type || ''
    const toolName = (event.data?.tool || '').toLowerCase()
    const isTaskCall = type === 'tool_call' && toolName === 'task'
    const isBoundary = boundaryTypes.has(type)

    if (isBoundary) {
      if (currentSubagent) {
        groups.push(currentSubagent)
        currentSubagent = null
      }
      groups.push({ type: 'event', event })
    } else if (isTaskCall) {
      if (currentSubagent) {
        groups.push(currentSubagent)
        currentSubagent = null
      }
      const args = event.data?.args || {}
      const taskStatus = event.data?.status

      const subagentGroup = {
        type: 'subagent',
        event,
        name: args.subagent_type || args.description || 'Subagent',
        description: args.description || '',
        prompt: args.prompt || '',
        subagentType: args.subagent_type || '',
        taskId: args.task_id,
        status: taskStatus,
        output: event.data?.output || '',
        error: event.data?.error || '',
        events: [],
      }

      if (taskStatus === 'error') {
        // Failed immediately — closed group, subsequent events are main agent
        groups.push(subagentGroup)
      } else {
        // Running/completed — capture subsequent events
        currentSubagent = subagentGroup
      }
    } else if (currentSubagent) {
      currentSubagent.events.push(event)
    } else {
      groups.push({ type: 'event', event })
    }
  }

  if (currentSubagent) {
    groups.push(currentSubagent)
  }

  return groups
}

const SubagentGroup = ({ group, startIndex }) => {
  const [expanded, setExpanded] = useState(!group.error)
  const [showResult, setShowResult] = useState(false)
  const [showPrompt, setShowPrompt] = useState(false)
  const { description, subagentType, events, output, status, prompt, error: errorMsg } = group
  const isError = status === 'error'

  // For errors, show error message. For success, show output or fallback to last token.
  const fallbackResult = !isError && !output
    ? [...events].reverse().find(e => e.type === 'token' && e.data?.type !== 'reasoning')?.data?.content
    : null
  const displayResult = isError ? (errorMsg || output || null) : (output || fallbackResult)

  // Compute tool stats within this subagent (exclude token events)
  const toolCalls = events.filter(e => e.type === 'tool_call')
  const toolSummary = toolCalls.reduce((acc, e) => {
    const t = (e.data?.tool || 'other').toLowerCase()
    acc[t] = (acc[t] || 0) + 1
    return acc
  }, {})
  const summaryStr = Object.entries(toolSummary)
    .sort((a, b) => b[1] - a[1])
    .map(([t, n]) => `${n} ${t}`)
    .join(', ')

  // Status badge styling
  const statusLabel = status || 'running'
  const statusColors = isError
    ? 'text-red-600 bg-red-100'
    : status === 'completed'
      ? 'text-green-600 bg-green-100'
      : 'text-gray-500 bg-gray-100'

  return (
    <div className={`border-l-2 ${isError ? 'border-red-300' : 'border-violet-300'} ml-1 pl-2 my-2`}>
      {/* Subagent header */}
      <div
        className={`flex items-center gap-1.5 rounded px-2 py-1.5 cursor-pointer ${isError ? 'bg-red-50 hover:bg-red-100' : 'bg-violet-50 hover:bg-violet-100'} transition-colors`}
        onClick={() => events.length > 0 && setExpanded(!expanded)}
      >
        <GitBranch className={`w-3.5 h-3.5 flex-shrink-0 ${isError ? 'text-red-500' : 'text-violet-500'}`} />
        <span className={`text-xs font-semibold ${isError ? 'text-red-700' : 'text-violet-700'}`}>
          {subagentType || 'Subagent'}
        </span>
        {description && (
          <span className="text-xs text-gray-500 truncate min-w-0">
            {description.length > 60 ? description.slice(0, 57) + '...' : description}
          </span>
        )}
        <span className="flex-1" />
        <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${statusColors}`}>{statusLabel}</span>
        {summaryStr && <span className="text-[10px] text-gray-400 flex-shrink-0 ml-1">{summaryStr}</span>}
        {events.length > 0 && (
          <>
            <span className="text-[10px] text-gray-400 flex-shrink-0 ml-1">{events.length} events</span>
            {expanded ? <ChevronDown className="w-3 h-3 text-gray-400" /> : <ChevronRight className="w-3 h-3 text-gray-400" />}
          </>
        )}
      </div>

      {/* Error message shown inline for failed subagents */}
      {isError && errorMsg && (
        <div className="mt-1 ml-1 text-xs text-red-600 bg-red-50 rounded px-2 py-1 font-mono">
          {errorMsg}
        </div>
      )}

      {/* Subagent result (what it told the main agent) - only for non-error */}
      {!isError && displayResult && (
        <div className="mt-1 ml-1">
          <button
            onClick={() => setShowResult(!showResult)}
            className="flex items-center gap-1 text-xs font-medium text-violet-600 hover:text-violet-800"
          >
            {showResult ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
            Result
            {!output && fallbackResult && <span className="text-[10px] text-gray-400 ml-1">(from agent text)</span>}
          </button>
          {showResult && (
            <pre className="mt-1 p-2 rounded text-xs font-mono whitespace-pre-wrap overflow-x-auto max-h-48 overflow-y-auto bg-gray-900 text-gray-300">
              {typeof displayResult === 'string' ? displayResult : JSON.stringify(displayResult, null, 2)}
            </pre>
          )}
        </div>
      )}

      {/* Subagent prompt (expandable) */}
      {prompt && (
        <div className="mt-0.5 ml-1">
          <button
            onClick={() => setShowPrompt(!showPrompt)}
            className="flex items-center gap-1 text-[10px] text-gray-400 hover:text-gray-600"
          >
            {showPrompt ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
            Prompt
          </button>
          {showPrompt && (
            <pre className="mt-1 p-2 bg-gray-900 rounded text-xs text-gray-300 font-mono whitespace-pre-wrap overflow-x-auto max-h-32 overflow-y-auto">
              {prompt}
            </pre>
          )}
        </div>
      )}

      {/* Subagent events */}
      {expanded && events.length > 0 && (
        <div className="mt-1">
          {events.map((event, i) => (
            event.type === 'token'
              ? <AgentTextBlock key={event.id || `sa-t-${startIndex}-${i}`} event={event} />
              : <EventItem key={event.id || `sa-${startIndex}-${i}`} event={event} index={startIndex + i} />
          ))}
        </div>
      )}
    </div>
  )
}

const AgentTextBlock = ({ event }) => {
  const data = event.data || {}
  const content = data.content || ''
  const isReasoning = data.type === 'reasoning' || data.type === 'thinking'
  const [expanded, setExpanded] = useState(false)

  if (!content) return null

  // Reasoning tokens: collapsed by default, subtle gray styling
  if (isReasoning) {
    return (
      <div className="py-0.5 border-b border-gray-100 last:border-0">
        <div
          className="flex items-center gap-1.5 rounded px-1 -mx-1 py-0.5 cursor-pointer hover:bg-gray-50"
          onClick={() => setExpanded(!expanded)}
        >
          <Bot className="w-3 h-3 flex-shrink-0 text-gray-300" />
          <span className="text-[10px] text-gray-400 italic">thinking...</span>
          <span className="flex-1" />
          {expanded ? <ChevronDown className="w-3 h-3 text-gray-300" /> : <ChevronRight className="w-3 h-3 text-gray-300" />}
        </div>
        {expanded && (
          <pre className="ml-5 mt-0.5 p-1.5 text-[11px] text-gray-400 italic whitespace-pre-wrap break-words max-h-32 overflow-y-auto bg-gray-50 rounded">
            {content}
          </pre>
        )}
      </div>
    )
  }

  // Text output: show preview with expand
  const timestamp = event.timestamp || event.createdAt || event.created_at
  const timeStr = timestamp
    ? new Date(typeof timestamp === 'number' ? timestamp * (timestamp < 1e12 ? 1000 : 1) : timestamp).toLocaleTimeString()
    : null
  const preview = content.length > 200 ? content.slice(0, 197) + '...' : content
  const needsExpand = content.length > 200

  return (
    <div className="py-1.5 border-b border-gray-100 last:border-0">
      <div
        className={`flex items-start gap-1.5 rounded px-1 -mx-1 py-0.5 ${needsExpand ? 'cursor-pointer hover:bg-gray-50' : ''}`}
        onClick={() => needsExpand && setExpanded(!expanded)}
      >
        <MessageCircle className="w-3 h-3 flex-shrink-0 text-blue-500 mt-0.5" />
        <span className="text-xs px-1.5 py-0.5 rounded font-medium text-blue-700 bg-blue-50 flex-shrink-0">
          agent
        </span>
        <span className="text-xs text-gray-600 whitespace-pre-wrap min-w-0 break-words flex-1">
          {expanded ? content : preview}
        </span>
        {timeStr && <span className="text-[10px] text-gray-400 flex-shrink-0 ml-1">{timeStr}</span>}
        {needsExpand && (
          <span className="text-xs text-gray-400 flex-shrink-0">
            {expanded ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
          </span>
        )}
      </div>
    </div>
  )
}

const EventItem = ({ event, index }) => {
  const [showDetail, setShowDetail] = useState(false)
  const type = event.type || event.event_type || 'event'
  const timestamp = event.timestamp || event.createdAt || event.created_at
  const timeStr = timestamp ? new Date(typeof timestamp === 'number' ? timestamp * (timestamp < 1e12 ? 1000 : 1) : timestamp).toLocaleTimeString() : null
  const data = event.data || {}

  const isToolCall = type === 'tool_call'
  const toolName = isToolCall ? (data.tool || 'tool') : null
  const category = isToolCall ? getToolCategory(toolName) : 'other'
  const { colors, Icon } = toolCategoryConfig[category] || toolCategoryConfig.other
  const toolHint = isToolCall ? getToolHint(data) : null
  const displayLabel = toolName || type
  const hasExpandable = isToolCall && !!(data.args || data.output)

  return (
    <div className="py-1 border-b border-gray-100 last:border-0">
      <div
        className={`flex items-center gap-1.5 rounded px-1 -mx-1 py-0.5 ${hasExpandable ? 'cursor-pointer hover:bg-gray-50' : ''}`}
        onClick={() => hasExpandable && setShowDetail(!showDetail)}
      >
        <span className="text-[10px] text-gray-300 w-5 text-right flex-shrink-0">{index + 1}</span>
        <Icon className={`w-3 h-3 flex-shrink-0 ${colors.split(' ')[0]}`} />
        <span className={`text-xs px-1.5 py-0.5 rounded font-medium ${colors}`}>
          {displayLabel}
        </span>
        {toolHint && (
          <span className="text-xs text-gray-500 font-mono truncate min-w-0">{toolHint}</span>
        )}
        <span className="flex-1" />
        {timeStr && <span className="text-[10px] text-gray-400 flex-shrink-0">{timeStr}</span>}
        {hasExpandable && (
          <span className="text-xs text-gray-400 flex-shrink-0">
            {showDetail ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
          </span>
        )}
      </div>
      {showDetail && (
        <div className="mt-1 ml-7 space-y-1.5">
          {data.args && (
            <div>
              <div className="text-[10px] font-medium text-gray-400 uppercase mb-0.5">Args</div>
              <pre className="p-2 bg-gray-900 rounded text-xs text-gray-300 font-mono whitespace-pre-wrap overflow-x-auto max-h-48 overflow-y-auto">
                {JSON.stringify(data.args, null, 2)}
              </pre>
            </div>
          )}
          {data.output && (
            <div>
              <div className="text-[10px] font-medium text-gray-400 uppercase mb-0.5">Output</div>
              <pre className="p-2 bg-gray-900 rounded text-xs text-gray-300 font-mono whitespace-pre-wrap overflow-x-auto max-h-48 overflow-y-auto">
                {typeof data.output === 'string' ? data.output : JSON.stringify(data.output, null, 2)}
              </pre>
            </div>
          )}
        </div>
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
    return null // Hide in conversation view too
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
    let data
    try {
      data = typeof convEvent.data === 'string' ? JSON.parse(convEvent.data) : (convEvent.data || {})
    } catch {
      data = {}
    }
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
  const [filterTool, setFilterTool] = useState(null)

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
      // API returns newest-first; reverse for chronological, then process
      setEvents(processEvents([...raw].reverse()))
      setShowEvents(true)
    } catch (e) {
      setError(e.message || 'Failed to load events')
    } finally {
      setLoading(false)
    }
  }

  // Compute tool stats for filter buttons
  const toolCounts = events ? events.reduce((acc, e) => {
    if (e.type === 'tool_call') {
      const tool = (e.data?.tool || 'unknown').toLowerCase()
      acc[tool] = (acc[tool] || 0) + 1
    }
    return acc
  }, {}) : {}

  const filteredEvents = events && filterTool
    ? events.filter((e) => e.type === 'tool_call' && (e.data?.tool || '').toLowerCase() === filterTool)
    : events

  // Group events by subagent when not filtering
  const grouped = events && !filterTool ? groupBySubagent(events) : null
  const hasSubagents = grouped?.some((g) => g.type === 'subagent')

  const renderGroupedEvents = () => {
    let idx = 0
    return grouped.map((g, i) => {
      if (g.type === 'subagent') {
        const startIdx = idx
        idx += g.events.length
        return <SubagentGroup key={g.taskId || `sg-${i}`} group={g} startIndex={startIdx} />
      }
      if (g.event.type === 'token') {
        return <AgentTextBlock key={g.event.id || `t-${i}`} event={g.event} />
      }
      return <EventItem key={g.event.id || `e-${i}`} event={g.event} index={idx++} />
    })
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
        {events && <span className="text-gray-300 ml-1">({events.length})</span>}
      </button>

      {error && (
        <div className="mt-1 text-xs text-red-500">{error}</div>
      )}

      {/* Conversation timeline (from conversation_history event) */}
      {showEvents && events && <ConversationTimeline events={events} />}

      {/* Tool filter bar */}
      {showEvents && events && Object.keys(toolCounts).length > 1 && (
        <div className="mt-2 flex flex-wrap gap-1 items-center">
          <Filter className="w-3 h-3 text-gray-400" />
          <button
            onClick={() => setFilterTool(null)}
            className={`text-[10px] px-1.5 py-0.5 rounded transition-colors ${!filterTool ? 'bg-gray-700 text-white' : 'bg-gray-100 text-gray-500 hover:bg-gray-200'}`}
          >
            all ({events.length})
          </button>
          {Object.entries(toolCounts).sort((a, b) => b[1] - a[1]).map(([tool, count]) => {
            const cat = getToolCategory(tool)
            const { colors } = toolCategoryConfig[cat]
            const isActive = filterTool === tool
            return (
              <button
                key={tool}
                onClick={() => setFilterTool(isActive ? null : tool)}
                className={`text-[10px] px-1.5 py-0.5 rounded transition-colors ${isActive ? 'bg-gray-700 text-white' : colors + ' hover:opacity-80'}`}
              >
                {tool} ({count})
              </button>
            )
          })}
        </div>
      )}

      {/* Events timeline */}
      {showEvents && filteredEvents && (
        <div className="mt-2 max-h-[500px] overflow-y-auto">
          {filteredEvents.length === 0 ? (
            <div className="text-xs text-gray-400 italic">No events recorded</div>
          ) : hasSubagents && !filterTool ? (
            renderGroupedEvents()
          ) : (
            filteredEvents.map((event, i) => (
              event.type === 'token'
                ? <AgentTextBlock key={event.id || `t-${i}`} event={event} />
                : <EventItem key={event.id || i} event={event} index={i} />
            ))
          )}
        </div>
      )}
    </div>
  )
}

const SandboxEventCard = ({ sandboxResult }) => {
  const [isExpanded, setIsExpanded] = useState(false)

  if (!sandboxResult) return null

  const result = sandboxResult
  const fileCount = (result.changed_files || []).length
  const elapsed = result.elapsed_seconds || 0
  const success = result.success

  const summaryParts = []
  if (fileCount > 0) summaryParts.push(`${fileCount} file${fileCount !== 1 ? 's' : ''} changed`)
  if (elapsed > 0) summaryParts.push(formatTime(elapsed))

  return (
    <div className={`rounded-xl border bg-gray-50 border-gray-200 border-l-4 ${success ? 'border-l-blue-500' : 'border-l-amber-500'} transition-all`}>
      {/* Header */}
      <div className="px-4 pt-3 pb-1">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Terminal className={`w-4 h-4 ${success ? 'text-blue-500' : 'text-amber-500'}`} />
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
        {summaryParts.length > 0 && (
          <div className="mt-1.5 pb-2 flex items-center gap-1 text-xs text-gray-500 flex-wrap">
            {summaryParts.map((part, i) => (
              <span key={i} className="flex items-center gap-1">
                {i > 0 && <span className="text-gray-300">&middot;</span>}
                {part}
              </span>
            ))}
          </div>
        )}
      </div>

      {/* Expanded details */}
      {isExpanded && (
        <div className="px-4 pb-3 border-t border-gray-200">
          <SandboxSessionSection result={result} />
        </div>
      )}
    </div>
  )
}

export default SandboxEventCard

// Exported for reuse by SandboxLiveProgress (same rendering for live and completed views)
export { processEvents, groupBySubagent, SubagentGroup, EventItem, AgentTextBlock, ConversationTimeline, toolCategoryConfig, getToolCategory }
