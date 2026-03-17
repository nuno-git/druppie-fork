/**
 * Session Detail - right panel when a session is selected in Chat
 */

import { useState, useRef, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Send, CheckCircle, XCircle, Shield, ShieldOff, Loader2, ExternalLink, MessageSquare, FileCode, FilePlus, StopCircle, PlayCircle, ArrowUp, AlertTriangle, Terminal, ChevronDown, ChevronRight } from 'lucide-react'
import { Link } from 'react-router-dom'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { getSession, sendChat, cancelChat, resumeSession, approveApproval, rejectApproval, answerQuestion, getSandboxEvents } from '../../services/api'
import { getUserInfo } from '../../services/keycloak'
import { useAuth } from '../../App'
import { getAgentConfig, getAgentMessageColors, formatToolName } from '../../utils/agentConfig'
import { FilePreviewModal } from './ApprovalCard'
import HITLQuestionMessage from './HITLQuestionMessage'
import WorkflowPipeline from './WorkflowPipeline'
import DebugEventLog from './DebugEventLog'
import AnnotationBar from './AnnotationBar'
import {
  chatMarkdownComponents,
  CopyJsonButton,
  buildVisibleJson,
  extractSurfacedApprovals,
  extractOrderedItems,
  extractSurfacedFileWrites,
  extractDependencyInstalls,
  findPendingQuestion,
} from './ChatHelpers'
import TestResultCard from './TestResultCard'
import PlanCard from './PlanCard'
import SandboxEventCard, {
  processEvents,
  groupBySubagent,
  SubagentGroup,
  EventItem,
  AgentTextBlock,
  ConversationTimeline,
  toolCategoryConfig,
  getToolCategory,
} from './SandboxEventCard'

// --- Tool label helper ---

const getToolLabel = (toolName) => {
  if (!toolName) return 'Unknown Tool'
  const labels = {
    'write_file': 'Write File',
    'coding:write_file': 'Write File',
    'batch_write_files': 'Write Files',
    'coding:batch_write_files': 'Write Files',
    'run_command': 'Run Command',
    'coding:run_command': 'Run Command',
    'commit_and_push': 'Git Commit & Push',
    'coding:commit_and_push': 'Git Commit & Push',
  }
  return labels[toolName] || toolName?.split(':').pop() || 'Tool Action'
}

// --- Inline Approval (minimal chat card) ---

const InlineApproval = ({ tc, sessionId }) => {
  const queryClient = useQueryClient()
  const user = getUserInfo()
  const [rejectMode, setRejectMode] = useState(false)
  const [rejectReason, setRejectReason] = useState('')
  const [showFilePreview, setShowFilePreview] = useState(false)

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['session', sessionId] })
    queryClient.invalidateQueries({ queryKey: ['tasks'] })
    queryClient.invalidateQueries({ queryKey: ['approvalHistory'] })
    queryClient.invalidateQueries({ queryKey: ['pending-approvals-count'] })
  }

  const approveMut = useMutation({
    mutationFn: (approvalId) => approveApproval(approvalId, ''),
    onSuccess: invalidate,
  })

  const rejectMut = useMutation({
    mutationFn: ({ approvalId, reason }) => rejectApproval(approvalId, reason || ''),
    onSuccess: () => {
      invalidate()
      setRejectMode(false)
      setRejectReason('')
    },
  })

  const isPending = tc.approval.status === 'pending'
  const isApproved = tc.approval.status === 'approved'
  const isRejected = tc.approval.status === 'rejected'
  const isProcessing = approveMut.isPending || rejectMut.isPending

  const toolLabel = formatToolName(tc.tool_name)
  const args = tc.arguments || {}
  const contextLine = args.path || args.file_path || args.command || args.message || args.commit_message || null

  const userRoles = user?.roles || []
  const requiredRoles = tc.approval.required_role ? [tc.approval.required_role] : ['admin']
  const userCanApprove = userRoles.includes('admin') || requiredRoles.some((r) => userRoles.includes(r))

  return (
    <div className="group">
      <div className="flex items-center gap-2 mb-1.5">
        <div className="w-6 h-6 rounded-full flex items-center justify-center flex-shrink-0 bg-amber-50 border border-amber-200">
          <Shield className="w-3.5 h-3.5 text-amber-600" />
        </div>
        <span className="text-sm font-medium text-amber-700">System</span>
        {tc.approval.resolved_at && (
          <span className="text-xs text-gray-300">
            {new Date(tc.approval.resolved_at).toLocaleTimeString()}
          </span>
        )}
      </div>
      <div className="pl-8">
        <div className={`rounded-lg border p-3 ${
          isApproved ? 'bg-green-50 border-green-200'
            : isRejected ? 'bg-red-50 border-red-200'
            : 'bg-amber-50 border-amber-200'
        }`}>
          <div className="flex items-center gap-2">
            <span className={`text-xs font-semibold uppercase tracking-wider ${
              isApproved ? 'text-green-700'
                : isRejected ? 'text-red-700'
                : 'text-amber-700'
            }`}>
              {isApproved ? 'Approved' : isRejected ? 'Rejected' : 'Approval Required'}
            </span>
          </div>
          <div className="mt-1 text-sm font-medium text-gray-900">{toolLabel}</div>
          {contextLine && (
            <div className="mt-0.5 text-xs text-gray-500 font-mono truncate" title={contextLine}>
              {contextLine}
            </div>
          )}

          {/* File preview for write operations */}
          {(() => {
            const filePath = args.path || args.file_path
            const content = args.content
            const batchFiles = args.files
            const isBatchWrite = !!batchFiles && Object.keys(batchFiles).length > 0
            const hasFile = !!(content || isBatchWrite)
            if (!hasFile) return null
            const files = isBatchWrite
              ? Object.entries(batchFiles).map(([p, c]) => ({ path: p, content: c }))
              : [{ path: filePath || 'file', content }]
            return (
              <div className="mt-1.5">
                <button
                  onClick={() => setShowFilePreview(true)}
                  className="flex items-center gap-1.5 text-xs text-blue-600 hover:text-blue-800 transition-colors"
                >
                  {isBatchWrite ? <FileCode className="w-3.5 h-3.5" /> : <FilePlus className="w-3.5 h-3.5" />}
                  View {isBatchWrite ? `${files.length} files` : filePath || 'file'}
                </button>
                {showFilePreview && (
                  <FilePreviewModal files={files} onClose={() => setShowFilePreview(false)} />
                )}
              </div>
            )
          })()}

          {isPending && (
            <div className="mt-2">
              {userCanApprove ? (
                !rejectMode ? (
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => approveMut.mutate(tc.approval.id)}
                      disabled={isProcessing}
                      className="inline-flex items-center gap-1 px-2.5 py-1 text-xs font-medium bg-green-600 text-white rounded-md hover:bg-green-700 disabled:opacity-50 transition-colors"
                    >
                      {isProcessing ? <Loader2 className="w-3 h-3 animate-spin" /> : <CheckCircle className="w-3 h-3" />}
                      Approve
                    </button>
                    <button
                      onClick={() => setRejectMode(true)}
                      disabled={isProcessing}
                      className="px-2.5 py-1 text-xs text-gray-500 hover:text-red-600 hover:bg-red-50 rounded-md transition-colors"
                    >
                      Reject
                    </button>
                  </div>
                ) : (
                  <div className="flex items-center gap-1.5">
                    <input
                      type="text"
                      value={rejectReason}
                      onChange={(e) => setRejectReason(e.target.value)}
                      placeholder="Reason..."
                      aria-label="Rejection reason"
                      className="flex-1 min-w-0 px-2 py-1 text-xs border border-gray-200 rounded-md focus:outline-none focus:ring-1 focus:ring-red-400"
                      autoFocus
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' && rejectReason.trim()) {
                          rejectMut.mutate({ approvalId: tc.approval.id, reason: rejectReason })
                        }
                        if (e.key === 'Escape') {
                          setRejectMode(false)
                          setRejectReason('')
                        }
                      }}
                    />
                    <button
                      onClick={() => rejectMut.mutate({ approvalId: tc.approval.id, reason: rejectReason })}
                      disabled={isProcessing || !rejectReason.trim()}
                      className="px-2 py-1 text-xs bg-red-600 text-white rounded-md hover:bg-red-700 disabled:opacity-50 transition-colors"
                    >
                      Reject
                    </button>
                    <button
                      onClick={() => { setRejectMode(false); setRejectReason('') }}
                      className="px-2 py-1 text-xs text-gray-400 hover:text-gray-600 transition-colors"
                    >
                      Cancel
                    </button>
                  </div>
                )
              ) : (
                <span className="text-xs text-amber-600">
                  Waiting for {requiredRoles.join(' or ')} approval
                </span>
              )}
            </div>
          )}

          <Link
            to="/tasks"
            className="mt-2 inline-flex items-center gap-1 text-xs text-blue-600 hover:text-blue-800 transition-colors"
          >
            View full details <ExternalLink className="w-3 h-3" />
          </Link>
        </div>
      </div>
    </div>
  )
}

// --- Timeline HITL Question ---

const TimelineQuestion = ({ tc, agentId, sessionId }) => {
  const queryClient = useQueryClient()

  const answerMut = useMutation({
    mutationFn: ({ questionId, answer }) => answerQuestion(questionId, answer),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['session', sessionId] }),
  })

  const isAnswered = tc.status === 'completed'

  const rawChoices = tc.arguments?.choices || tc.arguments?.options || []
  const choices = rawChoices.map(c =>
    typeof c === 'string' ? c : c.text || c.label || String(c)
  )

  let displayAnswer = null
  if (isAnswered && tc.result) {
    try {
      const parsed = typeof tc.result === 'string' ? JSON.parse(tc.result) : tc.result
      displayAnswer = parsed.answer || parsed.text || (typeof parsed === 'string' ? parsed : tc.result)
    } catch {
      displayAnswer = tc.result
    }
    if (typeof displayAnswer === 'object') {
      displayAnswer = JSON.stringify(displayAnswer)
    }
  }

  const allowOther = tc.tool_name === 'hitl_ask_multiple_choice_question'

  // If the LLM put the question text in context instead of question, promote it
  const hasQuestion = !!tc.arguments?.question
  const questionData = {
    id: tc.question_id,
    agent_id: agentId,
    question: tc.arguments?.question || tc.arguments?.context || 'Agent is asking a question',
    choices,
    context: hasQuestion ? tc.arguments?.context : undefined,
    allowOther,
  }

  return (
    <>
      <HITLQuestionMessage
        question={questionData}
        onChoiceSelect={(answer) => answerMut.mutate({ questionId: tc.question_id, answer })}
        isAnswering={answerMut.isPending}
        answered={isAnswered}
      />
      {isAnswered && displayAnswer && (
        <div className="flex justify-end">
          <div className="max-w-[85%] rounded-2xl px-4 py-2.5 text-sm bg-gray-100 text-gray-900">
            <div className="whitespace-pre-wrap">{displayAnswer}</div>
          </div>
        </div>
      )}
    </>
  )
}

// --- Agent Run ---

const AgentRunItem = ({ run, timelineIndex, sessionId, hasFollowingMessage }) => {
  const orderedItems = extractOrderedItems(run, hasFollowingMessage)

  // Show agent trace for completed runs that have no following message
  const showAgentTrace = !hasFollowingMessage && run.status !== 'running'

  if (!showAgentTrace && orderedItems.length === 0) return null

  const config = getAgentConfig(run.agent_id)
  const AgentIcon = config.icon
  const colors = getAgentMessageColors(config.color)

  return (
    <div data-type="agent-run" data-timeline-idx={timelineIndex}>
      {showAgentTrace && (
        <div className="group">
          <div className="flex items-center gap-2">
            <div className={`w-6 h-6 rounded-full flex items-center justify-center flex-shrink-0 ${colors.bg} border ${colors.border}`}>
              <AgentIcon className={`w-3.5 h-3.5 ${colors.accent}`} />
            </div>
            <span className={`text-sm font-medium ${colors.accent}`}>{config.name}</span>
          </div>
        </div>
      )}
      {orderedItems.map((item, i) => {
        if (item.type === 'approval') {
          return (
            <div key={i} className="mt-2">
              <InlineApproval tc={item.tc} sessionId={sessionId} />
            </div>
          )
        }
        if (item.type === 'question') {
          return (
            <div key={i} className="mt-3">
              <TimelineQuestion tc={item.tc} agentId={item.agentId} sessionId={sessionId} />
            </div>
          )
        }
        if (item.type === 'test') {
          return (
            <div key={i} className="mt-2">
              <TestResultCard testResults={[item.data]} />
            </div>
          )
        }
        if (item.type === 'sandbox') {
          return (
            <div key={i} className="mt-2">
              <SandboxEventCard sandboxResult={item.data} />
            </div>
          )
        }
        if (item.type === 'plan') {
          return (
            <div key={i} className="mt-2">
              <PlanCard content={item.data.content} />
            </div>
          )
        }
        return null
      })}
    </div>
  )
}

// --- Message ---

const MessageItem = ({ message, agentRun, sessionId }) => {
  const isUser = message.role === 'user'
  const hasAgent = message.agent_id && !isUser
  const surfacedApprovals = agentRun
    ? extractSurfacedApprovals(agentRun.llm_calls).filter((item) => item.tc.approval.status !== 'pending')
    : []

  if (isUser) {
    return (
      <div className="group flex justify-end gap-2">
        <span className="text-xs text-gray-300 self-end pb-1">
          {message.created_at && new Date(message.created_at).toLocaleTimeString()}
        </span>
        <div className="max-w-[85%] rounded-2xl px-4 py-2.5 text-sm bg-gray-100 text-gray-900 overflow-hidden">
          <div className="whitespace-pre-wrap break-words">{message.content}</div>
        </div>
      </div>
    )
  }

  if (hasAgent) {
    const config = getAgentConfig(message.agent_id)
    const AgentIcon = config.icon
    const colors = getAgentMessageColors(config.color)

    return (
      <>
        <div className="group">
          <div className="flex items-center gap-2 mb-1.5">
            <div className={`w-6 h-6 rounded-full flex items-center justify-center flex-shrink-0 ${colors.bg} border ${colors.border}`}>
              <AgentIcon className={`w-3.5 h-3.5 ${colors.accent}`} />
            </div>
            <span className={`text-sm font-medium ${colors.accent}`}>{config.name}</span>
            <span className="text-xs text-gray-300">
              {message.created_at && new Date(message.created_at).toLocaleTimeString()}
            </span>
          </div>
          <div className="pl-8 markdown-content text-sm text-gray-800 leading-relaxed break-words overflow-hidden">
            <ReactMarkdown remarkPlugins={[remarkGfm]} components={chatMarkdownComponents}>
              {message.content}
            </ReactMarkdown>
          </div>
        </div>
        {surfacedApprovals.length > 0 && (
          <div className="mt-3 space-y-3">
            {surfacedApprovals.map((item, i) => (
              <InlineApproval key={i} tc={item.tc} sessionId={sessionId} />
            ))}
          </div>
        )}
      </>
    )
  }

  return (
    <div className="group">
      <div className="flex items-center gap-2 mb-1.5">
        <div className="w-6 h-6 rounded-full flex items-center justify-center flex-shrink-0 bg-gray-100 border border-gray-200">
          <Shield className="w-3.5 h-3.5 text-gray-500" />
        </div>
        <span className="text-sm font-medium text-gray-500">System</span>
        <span className="text-xs text-gray-300">
          {message.created_at && new Date(message.created_at).toLocaleTimeString()}
        </span>
      </div>
      <div className="pl-8 text-sm text-gray-700 leading-relaxed overflow-hidden">
        <div className="whitespace-pre-wrap break-words">{message.content}</div>
      </div>
    </div>
  )
}

// --- Sandbox Live Progress ---

/** Extract sandbox_session_id from a waiting_sandbox tool call in the timeline */
const findWaitingSandboxId = (timeline) => {
  if (!timeline) return null
  for (let i = timeline.length - 1; i >= 0; i--) {
    const entry = timeline[i]
    if (entry.type !== 'agent_run' || !entry.agent_run) continue
    for (const llm of (entry.agent_run.llm_calls || [])) {
      for (const tc of (llm.tool_calls || [])) {
        if (tc.tool_name === 'execute_coding_task' && (tc.status === 'waiting_sandbox' || tc.status === 'retrying')) {
          let result = tc.result
          if (typeof result === 'string') {
            try { result = JSON.parse(result) } catch { continue }
          }
          if (result?.sandbox_session_id) return result.sandbox_session_id
        }
      }
    }
  }
  return null
}

const SandboxLiveProgress = ({ sandboxSessionId }) => {
  const [expanded, setExpanded] = useState(true)
  const [filterTool, setFilterTool] = useState(null)

  const { data: eventsData } = useQuery({
    queryKey: ['sandbox-events-live', sandboxSessionId],
    queryFn: () => getSandboxEvents(sandboxSessionId),
    refetchInterval: 3000,
    enabled: !!sandboxSessionId,
  })

  const rawEvents = eventsData?.events || (Array.isArray(eventsData) ? eventsData : [])
  // API returns newest-first; reverse for chronological display, then process
  const events = processEvents([...rawEvents].reverse())

  // Compute tool stats for filter buttons
  const toolCounts = events.reduce((acc, e) => {
    if (e.type === 'tool_call') {
      const tool = (e.data?.tool || 'unknown').toLowerCase()
      acc[tool] = (acc[tool] || 0) + 1
    }
    return acc
  }, {})

  const filteredEvents = filterTool
    ? events.filter((e) => e.type === 'tool_call' && (e.data?.tool || '').toLowerCase() === filterTool)
    : events

  // Group events by subagent when not filtering
  const grouped = !filterTool ? groupBySubagent(events) : null
  const hasSubagents = grouped?.some((g) => g.type === 'subagent')

  // Latest event for header summary
  const lastToolEvent = [...events].reverse().find(e => e.type === 'tool_call')
  const latestLabel = lastToolEvent?.data?.tool

  if (!sandboxSessionId) return null

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
    <div className="pl-8 mt-1">
      <div className="border border-blue-200 rounded-lg bg-blue-50/50 overflow-hidden">
        {/* Header */}
        <button
          onClick={() => setExpanded(!expanded)}
          className="w-full flex items-center gap-2 px-3 py-2 text-xs hover:bg-blue-100/50 transition-colors"
        >
          <Terminal className="w-3.5 h-3.5 text-blue-500 flex-shrink-0" />
          <Loader2 className="w-3 h-3 text-blue-400 animate-spin flex-shrink-0" />
          <span className="text-blue-600 font-medium">Sandbox Agent</span>
          {latestLabel && (
            <span className="text-blue-400 truncate">— {latestLabel}</span>
          )}
          <span className="ml-auto text-blue-300 flex-shrink-0">
            {events.length > 0 && <span className="mr-1">{events.length} events</span>}
            {expanded ? <ChevronDown className="w-3 h-3 inline" /> : <ChevronRight className="w-3 h-3 inline" />}
          </span>
        </button>

        {/* Expanded: full event timeline (same as completed view) */}
        {expanded && (
          <div className="border-t border-blue-200 px-3 py-1.5">
            {events.length === 0 ? (
              <span className="text-xs text-blue-400 italic">Starting up…</span>
            ) : (
              <>
                {/* Conversation timeline */}
                <ConversationTimeline events={events} />

                {/* Tool filter bar */}
                {Object.keys(toolCounts).length > 1 && (
                  <div className="mt-1 mb-1 flex flex-wrap gap-1 items-center">
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
                <div className="max-h-[500px] overflow-y-auto">
                  {hasSubagents && !filterTool ? (
                    renderGroupedEvents()
                  ) : (
                    filteredEvents.map((event, i) => (
                      event.type === 'token'
                        ? <AgentTextBlock key={event.id || `t-${i}`} event={event} />
                        : <EventItem key={event.id || i} event={event} index={i} />
                    ))
                  )}
                </div>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

// --- Main SessionDetail ---

const VALID_VIEW_MODES = new Set(['chat', 'annotated', 'inspect'])
// AgentRunStatus values that indicate the agent has started processing (not pending)
// Note: 'paused_user' was removed as it doesn't exist; 'paused_crashed' added
const STARTED_STATUSES = new Set(['running', 'completed', 'failed', 'paused_hitl', 'paused_tool', 'paused_sandbox', 'paused_crashed', 'waiting_approval', 'waiting_answer'])

const SessionDetail = ({ sessionId, initialViewMode }) => {
  const timelineEndRef = useRef(null)
  const timelineRef = useRef(null)
  const prevLengthRef = useRef(0)
  const inputRef = useRef(null)
  const [continueInput, setContinueInput] = useState('')
  const savedInspectScroll = useRef(0)
  const [viewMode, _setViewMode] = useState(() => {
    if (initialViewMode && VALID_VIEW_MODES.has(initialViewMode)) return initialViewMode
    return 'chat'
  })
  const setViewMode = (newMode) => {
    // Save scroll only when leaving timeline for inspect
    if (viewMode !== 'inspect' && newMode === 'inspect' && timelineRef.current) {
      savedInspectScroll.current = timelineRef.current.scrollTop
    }
    _setViewMode(newMode)
  }
  const queryClient = useQueryClient()
  const { user } = useAuth()
  const canDebug = user?.roles?.some(r => r === 'developer' || r === 'admin')

  const { data, isLoading, error } = useQuery({
    queryKey: ['session', sessionId],
    queryFn: () => getSession(sessionId),
    retry: (failureCount, error) => {
      if (error?.status === 403 || error?.status === 404) return false
      return failureCount < 3
    },
    refetchInterval: (query) => {
      if (query.state.error) return false
      const status = query.state.data?.status
      if (status === 'completed' || status === 'failed') return false
      if (status === 'paused_crashed') return 2000
      if (status === 'paused_sandbox') return 2000
      if (status === 'paused' || status === 'paused_approval' || status === 'paused_hitl') {
        // Fast poll while stopping (agent still finishing current op), slow poll when fully paused
        const hasRunning = query.state.data?.timeline?.some(
          e => e.type === 'agent_run' && e.agent_run?.status === 'running'
        )
        return hasRunning ? 500 : 2000
      }
      return 500
    },
    enabled: !!sessionId,
  })

  const continueMutation = useMutation({
    mutationFn: (message) => sendChat(message, sessionId),
    onSuccess: () => {
      setContinueInput('')
      queryClient.invalidateQueries({ queryKey: ['session', sessionId] })
      queryClient.invalidateQueries({ queryKey: ['sessions'] })
    },
  })

  const cancelMutation = useMutation({
    mutationFn: () => cancelChat(sessionId),
    onSuccess: () => {
      queryClient.refetchQueries({ queryKey: ['session', sessionId] })
      queryClient.invalidateQueries({ queryKey: ['sessions'] })
    },
    onError: (err) => {
      console.error('Cancel failed:', err)
    },
  })

  const resumeMutation = useMutation({
    mutationFn: () => resumeSession(sessionId),
    onSuccess: () => {
      queryClient.refetchQueries({ queryKey: ['session', sessionId] })
      queryClient.invalidateQueries({ queryKey: ['sessions'] })
    },
    onError: (err) => {
      console.error('Resume failed:', err)
    },
  })

  // Derive "stopping" state: session is paused but agent is still finishing current operation
  const hasRunningAgentRun = data?.timeline?.some(
    e => e.type === 'agent_run' && e.agent_run?.status === 'running'
  )
  const isStopping = data?.status === 'paused' && hasRunningAgentRun

  // When session has pending approvals, keep the tasks/badge cache fresh
  useEffect(() => {
    const status = data?.status
    if (status === 'paused_approval' || status === 'waiting_approval') {
      queryClient.invalidateQueries({ queryKey: ['tasks'] })
      queryClient.invalidateQueries({ queryKey: ['pending-approvals-count'] })
    }
  }, [data?.status, queryClient])

  useEffect(() => {
    const currentLength = data?.timeline?.length || 0
    if (currentLength > prevLengthRef.current) {
      const isInitial = prevLengthRef.current === 0
      // Double rAF for initial load: ensures flex layout is fully computed
      // (cached data can arrive before the container has its final height).
      // Single rAF suffices for incremental new-message scrolls.
      const schedule = isInitial
        ? (fn) => requestAnimationFrame(() => requestAnimationFrame(fn))
        : (fn) => requestAnimationFrame(fn)
      schedule(() => {
        const el = timelineRef.current
        if (el) el.scrollTo({ top: el.scrollHeight, behavior: isInitial ? 'instant' : 'smooth' })
      })
    }
    prevLengthRef.current = currentLength
  }, [data?.timeline?.length])

  // Restore scroll position when returning from inspect to timeline
  const prevViewMode = useRef(viewMode)
  useEffect(() => {
    if (prevViewMode.current === 'inspect' && viewMode !== 'inspect') {
      const saved = savedInspectScroll.current
      requestAnimationFrame(() => {
        if (timelineRef.current) {
          timelineRef.current.scrollTop = saved
        }
      })
    }
    prevViewMode.current = viewMode
  }, [viewMode])

  useEffect(() => {
    if (inputRef.current) {
      inputRef.current.style.height = 'auto'
      inputRef.current.style.height = Math.min(inputRef.current.scrollHeight, 160) + 'px'
    }
  }, [continueInput])

  if (isLoading) {
    return (
      <div className="flex flex-col h-full min-w-0">
        {/* Skeleton header */}
        <div className="px-4 py-3 border-b flex items-center gap-3">
          <div className="w-32 h-4 bg-gray-200 rounded animate-pulse" />
          <div className="w-20 h-4 bg-gray-100 rounded animate-pulse" />
        </div>
        {/* Skeleton messages */}
        <div className="flex-1 p-4 space-y-6">
          {/* User message skeleton */}
          <div className="flex justify-end">
            <div className="w-2/3 h-12 bg-gray-100 rounded-2xl animate-pulse" />
          </div>
          {/* Agent message skeleton */}
          <div className="flex items-start gap-2">
            <div className="w-6 h-6 bg-gray-200 rounded-full animate-pulse flex-shrink-0" />
            <div className="space-y-2 flex-1">
              <div className="w-24 h-3 bg-gray-200 rounded animate-pulse" />
              <div className="w-full h-20 bg-gray-100 rounded-lg animate-pulse" />
            </div>
          </div>
          {/* Another user message */}
          <div className="flex justify-end">
            <div className="w-1/2 h-10 bg-gray-100 rounded-2xl animate-pulse" />
          </div>
        </div>
      </div>
    )
  }

  if (error) {
    const isAccessDenied = error.status === 403
    const isNotFound = error.status === 404
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-center max-w-sm space-y-3">
          {isAccessDenied ? (
            <>
              <ShieldOff className="w-12 h-12 text-gray-300 mx-auto" />
              <h3 className="text-lg font-semibold text-gray-700">Access Denied</h3>
              <p className="text-sm text-gray-500">You don't have permission to view this session. It may belong to another user.</p>
            </>
          ) : isNotFound ? (
            <>
              <MessageSquare className="w-12 h-12 text-gray-300 mx-auto" />
              <h3 className="text-lg font-semibold text-gray-700">Session Not Found</h3>
              <p className="text-sm text-gray-500">This session doesn't exist or may have been deleted.</p>
            </>
          ) : (
            <>
              <AlertTriangle className="w-12 h-12 text-red-300 mx-auto" />
              <h3 className="text-lg font-semibold text-gray-700">Something Went Wrong</h3>
              <p className="text-sm text-gray-500">{error.message}</p>
            </>
          )}
          <Link to="/chat" className="inline-block text-sm text-blue-600 hover:text-blue-700 mt-2">
            ← Back to conversations
          </Link>
        </div>
      </div>
    )
  }

  if (!data) return null

  const pendingQuestion = findPendingQuestion(data.timeline)

  const handleContinueSend = () => {
    const trimmed = continueInput.trim()
    if (!trimmed) return
    if (pendingQuestion) {
      answerQuestion(pendingQuestion.tc.question_id, trimmed)
        .then(() => {
          setContinueInput('')
          queryClient.invalidateQueries({ queryKey: ['session', sessionId] })
        })
        .catch((err) => {
          console.error('Failed to answer question:', err.message || err)
        })
      return
    }
    continueMutation.mutate(trimmed)
  }

  const statusDotColor = isStopping
    ? 'bg-amber-500 animate-pulse'
    : {
        completed: 'bg-green-500',
        active: 'bg-blue-500 animate-pulse',
        running: 'bg-blue-500 animate-pulse',
        failed: 'bg-red-500',
        pending: 'bg-gray-400',
        paused: 'bg-amber-500',
        paused_crashed: 'bg-red-500',
        paused_hitl: 'bg-amber-500 animate-pulse',
        paused_tool: 'bg-amber-500 animate-pulse',
        paused_sandbox: 'bg-blue-500 animate-pulse',
        paused_approval: 'bg-amber-500 animate-pulse',
        waiting_approval: 'bg-amber-500 animate-pulse',
        waiting_answer: 'bg-amber-500 animate-pulse',
      }[data.status] || 'bg-gray-400'

  return (
    <div className="flex flex-col h-full min-w-0">
      {/* Header */}
      <div className="px-4 py-2.5 border-b flex-shrink-0">
        <div className="flex items-center gap-2.5 min-w-0">
          <span className={`w-2 h-2 rounded-full flex-shrink-0 ${statusDotColor}`} />
          <h2 className="text-sm font-medium text-gray-900 truncate">
            {data.title || 'Untitled Session'}
          </h2>
          <div className="ml-auto flex items-center gap-3 flex-shrink-0">
            {/* Stopping indicator — session is paused but agent still finishing */}
            {isStopping && (
              <span className="inline-flex items-center gap-1 px-2.5 py-1 text-xs font-medium text-amber-600 bg-amber-50 border border-amber-200 rounded-lg">
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
                Stopping…
              </span>
            )}
            {/* Sandbox running indicator */}
            {data.status === 'paused_sandbox' && (
              <span className="inline-flex items-center gap-1 px-2.5 py-1 text-xs font-medium text-blue-600 bg-blue-50 border border-blue-200 rounded-lg">
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
                Sandbox running…
              </span>
            )}
            {/* Continue button — when fully stopped, crashed, or failed */}
            {['paused', 'paused_crashed', 'failed'].includes(data.status) && !isStopping && (
              <button
                onClick={() => resumeMutation.mutate()}
                disabled={resumeMutation.isPending}
                className="inline-flex items-center gap-1 px-2.5 py-1 text-xs font-medium text-green-600 bg-green-50 border border-green-200 rounded-lg hover:bg-green-100 disabled:opacity-50 transition-colors"
              >
                {resumeMutation.isPending ? (
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                ) : (
                  <PlayCircle className="w-3.5 h-3.5" />
                )}
                Continue
              </button>
            )}
            {data.status === 'active' && (
              <button
                onClick={() => cancelMutation.mutate()}
                disabled={cancelMutation.isPending}
                className="inline-flex items-center gap-1 px-2.5 py-1 text-xs font-medium text-red-600 bg-red-50 border border-red-200 rounded-lg hover:bg-red-100 disabled:opacity-50 transition-colors"
              >
                {cancelMutation.isPending ? (
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                ) : (
                  <StopCircle className="w-3.5 h-3.5" />
                )}
                Stop
              </button>
            )}
            {(cancelMutation.isError || resumeMutation.isError) && (
              <span className="text-xs text-red-600">
                {cancelMutation.error?.message || resumeMutation.error?.message || 'Action failed'}
              </span>
            )}
            {canDebug && (
              <div className="flex items-center bg-gray-100 rounded-lg p-0.5 text-xs">
                {['chat', 'annotated', 'inspect'].map((mode) => (
                  <button
                    key={mode}
                    onClick={() => setViewMode(mode)}
                    className={`px-2 py-1 rounded transition-colors capitalize ${
                      viewMode === mode
                        ? 'bg-white shadow-sm text-gray-900 font-medium'
                        : 'text-gray-500 hover:text-gray-700'
                    }`}
                  >
                    {mode === 'inspect' ? 'Inspect' : mode === 'annotated' ? 'Annotated' : 'Chat'}
                  </button>
                ))}
              </div>
            )}
            {data.project && (
              <a
                href={`/projects/${data.project.id}`}
                className="text-xs text-gray-400 hover:text-blue-500 flex items-center gap-1 transition-colors"
              >
                {data.project.name}
              </a>
            )}
            <CopyJsonButton
              getData={() => buildVisibleJson(data, timelineRef.current)}
              label="Copy JSON"
            />
          </div>
        </div>
      </div>

      {/* Crash recovery banner */}
      {data.status === 'paused_crashed' && (
        <div className="mx-4 mt-2 px-3 py-2 bg-amber-50 border border-amber-200 rounded-lg flex items-start gap-2">
          <AlertTriangle className="w-4 h-4 text-amber-500 mt-0.5 flex-shrink-0" />
          <div className="text-xs text-amber-800">
            <span className="font-medium">The system restarted during this run.</span>{' '}
            Click Continue to pick up where it left off.
          </div>
        </div>
      )}

      {/* Workflow Pipeline — quick-glance status bar for all modes */}
      <WorkflowPipeline timeline={data.timeline} />

      {/* Content area: Chat/Annotated timeline or Inspect event log */}
      {viewMode === 'inspect' ? (
        <DebugEventLog data={data} sessionId={sessionId} sessionStatus={data.status} />
      ) : (
        <div ref={timelineRef} className="flex-1 overflow-y-auto overflow-x-hidden">
          <div className="max-w-3xl mx-auto px-4 py-6 space-y-6">
          {(!data.timeline || data.timeline.length === 0) && (
            <div className="text-center py-12 flex flex-col items-center gap-2">
              <MessageSquare className="w-8 h-8 text-gray-300" />
              <p className="text-gray-400 text-sm">No timeline entries yet</p>
            </div>
          )}
          {(() => {
            // messageRunMap: pairs each agent's last non-user message with its run
            // (used for surfaced approvals in chat bubbles)
            const messageRunMap = new Map()
            const runsWithMessages = new Set()
            // annotationMap: places each agent's AnnotationBar after the last
            // timeline entry (any message role) before the next agent_run starts
            const annotationMap = new Map()
            if (data.timeline) {
              let lastRun = null
              let lastRunIdx = null
              let lastMsgIdx = null
              // For annotation placement
              let annotCurrentRun = null
              let annotCurrentRunIdx = null
              let annotLastEntryIdx = null
              for (let idx = 0; idx < data.timeline.length; idx++) {
                const e = data.timeline[idx]
                if (e.type === 'agent_run' && e.agent_run) {
                  // messageRunMap logic (non-user messages only)
                  if (lastRun && lastMsgIdx !== null) {
                    messageRunMap.set(lastMsgIdx, lastRun)
                    runsWithMessages.add(lastRunIdx)
                  }
                  lastRun = e.agent_run
                  lastRunIdx = idx
                  lastMsgIdx = null
                  // annotationMap logic (all messages)
                  if (annotCurrentRun) {
                    annotationMap.set(annotLastEntryIdx ?? annotCurrentRunIdx, annotCurrentRun)
                  }
                  annotCurrentRun = e.agent_run
                  annotCurrentRunIdx = idx
                  annotLastEntryIdx = null
                } else if (e.type === 'message') {
                  if (e.message?.role !== 'user' && lastRun) {
                    lastMsgIdx = idx
                  }
                  annotLastEntryIdx = idx
                }
              }
              if (lastRun && lastMsgIdx !== null) {
                messageRunMap.set(lastMsgIdx, lastRun)
                runsWithMessages.add(lastRunIdx)
              }
              if (annotCurrentRun) {
                annotationMap.set(annotLastEntryIdx ?? annotCurrentRunIdx, annotCurrentRun)
              }
            }

            const renderAnnotation = (i) => {
              if (viewMode !== 'annotated') return null
              const run = annotationMap.get(i)
              if (!run) return null
              return (
                <div className="pl-8 mt-1">
                  <AnnotationBar run={run} />
                </div>
              )
            }

            return data.timeline?.map((entry, i) => {
              // Messages always render
              if (entry.type === 'message' && entry.message) {
                return (
                  <div key={i}>
                    <MessageItem
                      message={entry.message}
                      agentRun={messageRunMap.get(i)}
                      sessionId={sessionId}
                    />
                    {renderAnnotation(i)}
                  </div>
                )
              }

              // Agent runs: render if they have visible content or completed without a message
              if (entry.type === 'agent_run' && entry.agent_run) {
                // Skip pending agents that haven't started yet — they show in the workflow bar
                if (!STARTED_STATUSES.has(entry.agent_run.status)) return null

                const hasFollowingMessage = runsWithMessages.has(i)
                const orderedItems = extractOrderedItems(entry.agent_run, hasFollowingMessage)
                // Show completed runs without a following message (e.g. architect)
                const isCompletedWithoutMessage = !hasFollowingMessage && entry.agent_run.status !== 'running'
                if (orderedItems.length === 0 && !isCompletedWithoutMessage) {
                  return null
                }
                return (
                  <div key={i}>
                    <AgentRunItem
                      run={entry.agent_run}
                      timelineIndex={i}
                      sessionId={sessionId}
                      hasFollowingMessage={hasFollowingMessage}
                    />
                    {renderAnnotation(i)}
                  </div>
                )
              }

              return null
            })
          })()}
          {/* Trailing thinking / sandbox-waiting indicator */}
          {(() => {
            // Don't show thinking indicator if session itself has ended
            if (data.status === 'failed' || data.status === 'completed') return null
            const activeEntry = data.timeline?.findLast(
              (e) => e.type === 'agent_run' && (e.agent_run?.status === 'running' || e.agent_run?.status === 'paused_sandbox')
            )
            if (!activeEntry) return null
            const run = activeEntry.agent_run
            const isSandboxWaiting = run.status === 'paused_sandbox'
            const config = getAgentConfig(run.agent_id)
            const AgentIcon = config.icon
            const colors = getAgentMessageColors(config.color)
            return (
              <div>
                <div className="flex items-center gap-2 mb-1.5">
                  <div className={`w-6 h-6 rounded-full flex items-center justify-center flex-shrink-0 ${colors.bg} border ${colors.border}`}>
                    <AgentIcon className={`w-3.5 h-3.5 ${colors.accent}`} />
                  </div>
                  <span className={`text-sm font-medium ${colors.accent}`}>{config.name}</span>
                </div>
                {isSandboxWaiting ? (
                  <SandboxLiveProgress sandboxSessionId={findWaitingSandboxId(data.timeline)} />
                ) : (
                  <div className="pl-8 flex items-center gap-1.5 py-1">
                    <span className="w-1.5 h-1.5 bg-gray-400 rounded-full animate-bounce [animation-delay:0ms]" />
                    <span className="w-1.5 h-1.5 bg-gray-400 rounded-full animate-bounce [animation-delay:150ms]" />
                    <span className="w-1.5 h-1.5 bg-gray-400 rounded-full animate-bounce [animation-delay:300ms]" />
                  </div>
                )}
              </div>
            )
          })()}
          {/* Pending approvals */}
          {(() => {
            const pending = []
            data.timeline?.forEach((entry) => {
              if (entry.type !== 'agent_run' || !entry.agent_run) return
              entry.agent_run.llm_calls?.forEach((llm) => {
                llm.tool_calls?.forEach((tc) => {
                  if (tc.approval?.status === 'pending') {
                    pending.push(tc)
                  }
                })
              })
            })
            if (pending.length === 0) return null
            return (
              <div className="space-y-3">
                {pending.map((tc, i) => (
                  <InlineApproval key={tc.approval.id || i} tc={tc} sessionId={sessionId} />
                ))}
              </div>
            )
          })()}
          <div ref={timelineEndRef} />
          </div>
        </div>
      )}

      {/* Sandbox waiting bar — replaces input when sandbox is running */}
      {data.status === 'paused_sandbox' && viewMode !== 'inspect' && (
        <div className="px-4 pb-4 pt-2 flex-shrink-0">
          <div className="max-w-3xl mx-auto">
            <div className="flex items-center justify-center gap-2 border border-blue-200 rounded-2xl shadow-sm px-4 py-3.5 bg-blue-50">
              <Loader2 className="w-4 h-4 text-blue-500 animate-spin" />
              <span className="text-sm text-blue-600">Coding agent is running in sandbox…</span>
            </div>
          </div>
        </div>
      )}

      {/* Floating input bar — hidden in inspect mode and during sandbox */}
      {data.status !== 'failed' && data.status !== 'paused_sandbox' && viewMode !== 'inspect' && (
        <div className="px-4 pb-4 pt-2 flex-shrink-0">
          <div className="max-w-3xl mx-auto">
            <div className="flex items-end gap-2 border border-gray-200 rounded-2xl shadow-lg px-4 py-3 bg-white focus-within:border-gray-300 focus-within:shadow-xl transition-shadow">
              <textarea
                ref={inputRef}
                value={continueInput}
                onChange={(e) => setContinueInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey && !continueMutation.isPending) {
                    e.preventDefault()
                    handleContinueSend()
                  }
                }}
                placeholder={
                  pendingQuestion
                    ? 'Type your answer...'
                    : data.status === 'completed'
                      ? 'Send a follow-up message...'
                      : 'Type a message...'
                }
                rows={1}
                className="flex-1 resize-none bg-transparent outline-none text-sm leading-6 py-1 max-h-40"
                aria-label="Chat message input"
                disabled={continueMutation.isPending}
              />
              {isStopping ? (
                <button
                  disabled
                  className="flex-shrink-0 p-2 rounded-xl bg-amber-500 text-white transition-colors"
                  aria-label="Stopping"
                >
                  <Loader2 className="w-4 h-4 animate-spin" />
                </button>
              ) : data.status === 'active' ? (
                <button
                  onClick={() => cancelMutation.mutate()}
                  disabled={cancelMutation.isPending}
                  className="flex-shrink-0 p-2 rounded-xl bg-red-600 text-white hover:bg-red-700 disabled:opacity-50 transition-colors"
                  aria-label="Stop agent"
                >
                  {cancelMutation.isPending ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : (
                    <StopCircle className="w-4 h-4" />
                  )}
                </button>
              ) : ['paused', 'paused_crashed', 'failed'].includes(data.status) ? (
                <button
                  onClick={() => resumeMutation.mutate()}
                  disabled={resumeMutation.isPending}
                  className="flex-shrink-0 p-2 rounded-xl bg-green-600 text-white hover:bg-green-700 disabled:opacity-50 transition-colors"
                  aria-label="Continue agent"
                >
                  {resumeMutation.isPending ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : (
                    <PlayCircle className="w-4 h-4" />
                  )}
                </button>
              ) : (
                <button
                  onClick={handleContinueSend}
                  disabled={!continueInput.trim() || continueMutation.isPending}
                  className="flex-shrink-0 p-2 rounded-xl bg-gray-900 text-white hover:bg-gray-700 disabled:opacity-30 disabled:hover:bg-gray-900 transition-colors"
                  aria-label="Send message"
                >
                  {continueMutation.isPending ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : (
                    <ArrowUp className="w-4 h-4" />
                  )}
                </button>
              )}
            </div>
            {continueMutation.isError && (
              <p className="mt-2 text-xs text-red-600 text-center">
                {continueMutation.error.message}
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

export default SessionDetail
