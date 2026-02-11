/**
 * Chat Page - Two-panel polling-based session viewer
 *
 * Left sidebar: session list (polls every 5s)
 * Right panel: new session input or session detail (polls every 0.5s)
 * URL param ?session=<id> drives which session is shown
 */

import React, { useState, useRef, useEffect } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Send, ExternalLink, Plus, Copy, Check, CheckCircle, XCircle, Loader2 } from 'lucide-react'
import {
  getSessions,
  getSession,
  sendChat,
  approveApproval,
  rejectApproval,
  answerQuestion,
} from '../services/api'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { getUserInfo } from '../services/keycloak'
import { getAgentConfig, getAgentMessageColors } from '../utils/agentConfig'
import ApprovalCard from '../components/chat/ApprovalCard'
import HITLQuestionMessage from '../components/chat/HITLQuestionMessage'
import WorkflowPipeline from '../components/chat/WorkflowPipeline'

// --- Helpers ---

const STATUS_STYLES = {
  completed: 'bg-green-100 text-green-700',
  running: 'bg-blue-100 text-blue-700',
  pending: 'bg-gray-100 text-gray-600',
  failed: 'bg-red-100 text-red-700',
  paused_hitl: 'bg-yellow-100 text-yellow-700',
  paused_tool: 'bg-yellow-100 text-yellow-700',
  waiting_approval: 'bg-yellow-100 text-yellow-700',
  waiting_answer: 'bg-yellow-100 text-yellow-700',
  approved: 'bg-green-100 text-green-700',
  rejected: 'bg-red-100 text-red-700',
}

const STATUS_LABELS = {
  paused_hitl: 'Awaiting Input',
  paused_tool: 'Awaiting Approval',
  waiting_approval: 'Awaiting Approval',
  waiting_answer: 'Awaiting Input',
}

const StatusBadge = ({ status }) => (
  <span
    className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${
      STATUS_STYLES[status] || 'bg-gray-100 text-gray-600'
    }`}
  >
    {status === 'running' && <Loader2 className="w-3 h-3 animate-spin" />}
    {STATUS_LABELS[status] || status?.replace(/_/g, ' ')}
  </span>
)

const timeAgo = (dateStr) => {
  if (!dateStr) return ''
  const seconds = Math.floor((Date.now() - new Date(dateStr).getTime()) / 1000)
  if (seconds < 60) return 'just now'
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`
  return `${Math.floor(seconds / 86400)}d ago`
}

const copyToClipboard = async (text) => {
  try {
    await navigator.clipboard.writeText(text)
  } catch {
    const textarea = document.createElement('textarea')
    textarea.value = text
    textarea.style.position = 'fixed'
    textarea.style.left = '-9999px'
    document.body.appendChild(textarea)
    textarea.select()
    document.execCommand('copy')
    document.body.removeChild(textarea)
  }
}

const CopyJsonButton = ({ getData, label = 'Copy JSON' }) => {
  const [copied, setCopied] = useState(false)

  const handleCopy = async () => {
    const json = getData()
    await copyToClipboard(JSON.stringify(json, null, 2))
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <button
      onClick={handleCopy}
      className={`inline-flex items-center gap-1 px-2 py-1 text-xs rounded transition-colors ${
        copied
          ? 'bg-green-100 text-green-700'
          : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
      }`}
      title={label}
    >
      {copied ? <Check className="w-3 h-3" /> : <Copy className="w-3 h-3" />}
      {copied ? 'Copied!' : label}
    </button>
  )
}

/**
 * Build a JSON snapshot reflecting exactly what's expanded in the UI.
 * Walks the session data and checks the open state of each <details> via data attributes.
 */
const buildVisibleJson = (data, containerEl) => {
  // Session metadata (always included)
  const result = {
    id: data.id,
    title: data.title,
    status: data.status,
    ...(data.created_at && { created_at: data.created_at }),
    ...(data.project_id && { project_id: data.project_id }),
    ...(data.project_name && { project_name: data.project_name }),
    ...(data.repo_url && { repo_url: data.repo_url }),
    ...(data.token_usage && { token_usage: data.token_usage }),
    timeline: [],
  }

  if (!containerEl || !data.timeline) return result

  data.timeline.forEach((entry, i) => {
    if (entry.type === 'message' && entry.message) {
      const m = entry.message
      result.timeline.push({
        type: 'message',
        role: m.role,
        content: m.content,
        ...(m.agent_id && { agent_id: m.agent_id }),
      })
      return
    }

    if (entry.type === 'agent_run' && entry.agent_run) {
      const run = entry.agent_run

      const runEntry = {
        type: 'agent_run',
        agent_id: run.agent_id,
        status: run.status,
        sequence_number: run.sequence_number,
      }

      // LLM call summaries (details are in the workflow pipeline bar)
      if (run.llm_calls?.length) {
        runEntry.llm_calls = run.llm_calls.map((llm) => ({
          model: llm.model,
          total_tokens: llm.token_usage?.total_tokens || 0,
          tool_calls: llm.tool_calls?.map((tc) => ({
            tool_name: tc.tool_name,
            status: tc.status,
          })),
        }))
      }

      result.timeline.push(runEntry)
    }
  })

  return result
}

// --- Extract approvals from LLM calls (questions are now rendered as timeline bubbles) ---

const extractSurfacedApprovals = (llmCalls) => {
  const items = []
  llmCalls?.forEach((llm) => {
    llm.tool_calls?.forEach((tc) => {
      if (tc.approval) {
        items.push({ type: 'approval', tc })
      }
    })
  })
  return items
}

// --- Extract HITL questions from an agent run's LLM calls ---

const extractQuestions = (agentRun) => {
  const questions = []
  agentRun.llm_calls?.forEach((llm) => {
    llm.tool_calls?.forEach((tc) => {
      if (tc.tool_name?.includes('hitl_ask')) {
        questions.push({ tc, agentId: agentRun.agent_id })
      }
    })
  })
  return questions
}

// --- Find the pending question across the entire timeline ---

const findPendingQuestion = (timeline) => {
  if (!timeline) return null
  for (const entry of timeline) {
    if (entry.type !== 'agent_run' || !entry.agent_run) continue
    for (const llm of entry.agent_run.llm_calls || []) {
      for (const tc of llm.tool_calls || []) {
        if (tc.tool_name?.includes('hitl_ask') && tc.status === 'waiting_answer') {
          return { tc, agentId: entry.agent_run.agent_id }
        }
      }
    }
  }
  return null
}

// --- Surfaced Approval Card (uses ApprovalCard for pending, simple display for resolved) ---

const SurfacedApproval = ({ tc, sessionId }) => {
  const queryClient = useQueryClient()
  const user = getUserInfo()

  const approveMut = useMutation({
    mutationFn: (approvalId) => approveApproval(approvalId, ''),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['session', sessionId] }),
  })

  const rejectMut = useMutation({
    mutationFn: ({ approvalId, reason }) => rejectApproval(approvalId, reason || ''),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['session', sessionId] }),
  })

  const isPending = tc.approval.status === 'pending'
  const isApproved = tc.approval.status === 'approved'
  const isRejected = tc.approval.status === 'rejected'

  const approvalData = {
    task_id: tc.approval.id,
    task_name: tc.tool_name,
    mcp_tool: tc.tool_name,
    mcp_arguments: tc.arguments,
    required_role: tc.approval.required_role,
    required_roles: tc.approval.required_role ? [tc.approval.required_role] : ['admin'],
    approval_type: 'single',
    required_approvals: 1,
    current_approvals: isPending ? 0 : 1,
    approved_by_roles: [],
    approved_by_ids: [],
  }

  return (
    <>
      <ApprovalCard
        approval={approvalData}
        onApprove={(id) => approveMut.mutate(id)}
        onReject={(id, reason) => rejectMut.mutate({ approvalId: id, reason })}
        isProcessing={approveMut.isPending || rejectMut.isPending}
        currentUserId={user?.id}
        sessionId={sessionId}
        userRoles={user?.roles || []}
        chatInline
        resolved={!isPending}
      />
      {(isApproved || isRejected) && (
        <div className={`mt-2 mx-3 rounded-lg border p-3 flex items-center gap-2 ${
          isApproved ? 'bg-green-50 border-green-200' : 'bg-red-50 border-red-200'
        }`}>
          {isApproved ? (
            <CheckCircle className="w-4 h-4 text-green-600" />
          ) : (
            <XCircle className="w-4 h-4 text-red-600" />
          )}
          <span className={`text-sm font-medium ${isApproved ? 'text-green-800' : 'text-red-800'}`}>
            {isApproved ? 'Approved' : 'Rejected'}
          </span>
          {tc.approval.resolved_at && (
            <span className="text-xs text-gray-500 ml-auto">
              {new Date(tc.approval.resolved_at).toLocaleString()}
            </span>
          )}
        </div>
      )}
    </>
  )
}

// --- Timeline HITL Question (rendered as a chat bubble via HITLQuestionMessage) ---

const TimelineQuestion = ({ tc, agentId, sessionId }) => {
  const queryClient = useQueryClient()

  const answerMut = useMutation({
    mutationFn: ({ questionId, answer }) => answerQuestion(questionId, answer),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['session', sessionId] }),
  })

  const isAnswered = tc.status === 'completed'

  // Normalize choices - API may return strings or objects
  const rawChoices = tc.arguments?.choices || tc.arguments?.options || []
  const choices = rawChoices.map(c =>
    typeof c === 'string' ? c : c.text || c.label || String(c)
  )

  // Parse the answer - tc.result may be a JSON string with {answer, question, status, ...}
  let displayAnswer = null
  if (isAnswered && tc.result) {
    try {
      const parsed = typeof tc.result === 'string' ? JSON.parse(tc.result) : tc.result
      displayAnswer = parsed.answer || parsed.text || (typeof parsed === 'string' ? parsed : tc.result)
    } catch {
      displayAnswer = tc.result
    }
    // If still an object, stringify it cleanly
    if (typeof displayAnswer === 'object') {
      displayAnswer = JSON.stringify(displayAnswer)
    }
  }

  const questionData = {
    id: tc.question_id,
    agent_id: agentId,
    question: tc.arguments?.question || 'Agent is asking a question',
    choices,
    context: tc.arguments?.context,
  }

  return (
    <>
      <HITLQuestionMessage
        question={questionData}
        onChoiceSelect={(answer) => answerMut.mutate({ questionId: tc.question_id, answer })}
        isAnswering={answerMut.isPending}
        answered={isAnswered}
      />
      {/* User's answer rendered as a regular right-aligned chat bubble */}
      {isAnswered && displayAnswer && (
        <div className="flex justify-end">
          <div className="max-w-[80%] rounded-lg px-4 py-2 text-sm bg-blue-600 text-white">
            <div className="whitespace-pre-wrap">{displayAnswer}</div>
          </div>
        </div>
      )}
    </>
  )
}

// --- Agent Run ---

const AgentRunItem = ({ run, timelineIndex, sessionId, hasFollowingMessage }) => {
  // Only show resolved approvals inline; pending ones render at the bottom of the timeline
  const resolvedItems = hasFollowingMessage ? [] : extractSurfacedApprovals(run.llm_calls)
    .filter((item) => item.tc.approval.status !== 'pending')

  return (
    <div data-type="agent-run" data-timeline-idx={timelineIndex}>
      {resolvedItems.length > 0 && (
        <div className="ml-11 mt-2 space-y-3">
          {resolvedItems.map((item, i) => (
            <div key={i}>
              <SurfacedApproval tc={item.tc} sessionId={sessionId} />
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// --- Message ---

const MessageItem = ({ message, agentRun, sessionId }) => {
  const isUser = message.role === 'user'
  const hasAgent = message.agent_id && !isUser
  // Only show resolved approvals inline; pending ones render at the bottom of the timeline
  const surfacedApprovals = agentRun
    ? extractSurfacedApprovals(agentRun.llm_calls).filter((item) => item.tc.approval.status !== 'pending')
    : []

  // User messages: right-aligned blue
  if (isUser) {
    return (
      <div className="flex justify-end">
        <div className="max-w-[80%] rounded-lg px-4 py-2 text-sm bg-blue-600 text-white">
          <div className="whitespace-pre-wrap">{message.content}</div>
          <div className="text-xs mt-1 text-blue-200">
            {message.created_at && new Date(message.created_at).toLocaleTimeString()}
          </div>
        </div>
      </div>
    )
  }

  // Agent messages: icon circle + agent-colored bubble
  if (hasAgent) {
    const config = getAgentConfig(message.agent_id)
    const AgentIcon = config.icon
    const colors = getAgentMessageColors(config.color)

    return (
      <>
        <div className="flex justify-start">
          <div className="flex items-start gap-3 max-w-[85%]">
            <div className={`w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0 ${colors.bg} border ${colors.border}`}>
              <AgentIcon className={`w-5 h-5 ${colors.accent}`} />
            </div>
            <div className={`rounded-2xl rounded-tl-none shadow-sm border px-4 py-3 ${colors.bg} ${colors.border}`}>
              <div className={`text-xs font-semibold ${colors.accent}`}>{config.name}</div>
              {message.agent_id === 'summarizer' ? (
                <div className="markdown-content text-sm mt-1">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown>
                </div>
              ) : (
                <div className="whitespace-pre-wrap text-sm mt-1">{message.content}</div>
              )}
              <div className="text-xs mt-1 text-gray-400">
                {message.created_at && new Date(message.created_at).toLocaleTimeString()}
              </div>
            </div>
          </div>
        </div>
        {/* Resolved approvals — rendered below the message bubble, aligned with content */}
        {surfacedApprovals.length > 0 && (
          <div className="ml-11 mt-2 space-y-3">
            {surfacedApprovals.map((item, i) => (
              <div key={i}>
                <SurfacedApproval tc={item.tc} sessionId={sessionId} />
              </div>
            ))}
          </div>
        )}
      </>
    )
  }

  // Non-agent, non-user messages (system, etc.)
  return (
    <div className="flex justify-start">
      <div className="max-w-[80%] rounded-lg px-4 py-2 text-sm bg-gray-100 text-gray-900">
        <div className="whitespace-pre-wrap">{message.content}</div>
        <div className="text-xs mt-1 text-gray-400">
          {message.created_at && new Date(message.created_at).toLocaleTimeString()}
        </div>
      </div>
    </div>
  )
}

// --- Session Detail (right panel when session selected) ---

const SessionDetail = ({ sessionId }) => {
  const timelineEndRef = useRef(null)
  const timelineRef = useRef(null)
  const prevLengthRef = useRef(0)
  const [continueInput, setContinueInput] = useState('')
  const queryClient = useQueryClient()

  const { data, isLoading, error } = useQuery({
    queryKey: ['session', sessionId],
    queryFn: () => getSession(sessionId),
    refetchInterval: (query) => {
      const status = query.state.data?.status
      if (status === 'completed' || status === 'failed') return false
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

  // Auto-scroll when timeline grows
  useEffect(() => {
    const currentLength = data?.timeline?.length || 0
    if (currentLength > prevLengthRef.current) {
      timelineEndRef.current?.scrollIntoView({ behavior: 'smooth' })
    }
    prevLengthRef.current = currentLength
  }, [data?.timeline?.length])

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-full text-gray-500">
        <div className="w-6 h-6 border-2 border-blue-600 border-t-transparent rounded-full animate-spin mr-2" />
        Loading session...
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-full text-red-500">
        Error loading session: {error.message}
      </div>
    )
  }

  if (!data) return null

  // Derive pending HITL question for input bar routing
  const pendingQuestion = findPendingQuestion(data.timeline)

  const handleContinueSend = () => {
    const trimmed = continueInput.trim()
    if (!trimmed) return
    if (pendingQuestion) {
      // Route to answerQuestion instead of sendChat
      answerQuestion(pendingQuestion.tc.question_id, trimmed).then(() => {
        setContinueInput('')
        queryClient.invalidateQueries({ queryKey: ['session', sessionId] })
      })
      return
    }
    continueMutation.mutate(trimmed)
  }

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="px-4 py-3 border-b bg-white flex-shrink-0">
        <div className="flex items-center gap-3">
          <h2 className="text-lg font-semibold truncate">
            {data.title || 'Untitled Session'}
          </h2>
          <StatusBadge status={data.status} />
          <div className="ml-auto flex-shrink-0">
            <CopyJsonButton
              getData={() => buildVisibleJson(data, timelineRef.current)}
              label="Copy JSON"
            />
          </div>
        </div>
        <div className="text-xs text-gray-500 mt-1 flex items-center gap-3">
          <span>ID: {data.id}</span>
          {data.project_id && (
            <a
              href={`/projects/${data.project_id}`}
              className="inline-flex items-center gap-1 text-blue-600 hover:underline"
            >
              <ExternalLink className="w-3 h-3" />
              {data.project_name || 'Project'}
            </a>
          )}
          {data.token_usage?.total_tokens > 0 && (
            <span>{data.token_usage.total_tokens} total tokens</span>
          )}
        </div>
      </div>

      {/* Workflow Pipeline */}
      <WorkflowPipeline timeline={data.timeline} />

      {/* Timeline */}
      <div ref={timelineRef} className="flex-1 overflow-y-auto px-4 py-4 space-y-3">
        {(!data.timeline || data.timeline.length === 0) && (
          <p className="text-gray-400 text-center py-8">
            No timeline entries yet
          </p>
        )}
        {(() => {
          // Map each agent's LAST non-user message to its preceding agent_run (for approval positioning)
          const messageRunMap = new Map()
          const runsWithMessages = new Set()
          if (data.timeline) {
            let lastRun = null
            let lastRunIdx = null
            let lastMsgIdx = null
            for (let idx = 0; idx < data.timeline.length; idx++) {
              const e = data.timeline[idx]
              if (e.type === 'agent_run' && e.agent_run) {
                if (lastRun && lastMsgIdx !== null) {
                  messageRunMap.set(lastMsgIdx, lastRun)
                  runsWithMessages.add(lastRunIdx)
                }
                lastRun = e.agent_run
                lastRunIdx = idx
                lastMsgIdx = null
              } else if (
                e.type === 'message' &&
                e.message?.role !== 'user' &&
                lastRun
              ) {
                lastMsgIdx = idx
              }
            }
            if (lastRun && lastMsgIdx !== null) {
              messageRunMap.set(lastMsgIdx, lastRun)
              runsWithMessages.add(lastRunIdx)
            }
          }

          return data.timeline?.map((entry, i) => {
            // Skip pending agent runs — they only appear in the pipeline
            if (
              entry.type === 'agent_run' &&
              entry.agent_run?.status === 'pending' &&
              (entry.agent_run?.llm_calls?.length || 0) === 0
            ) {
              return null
            }
            const questions = entry.type === 'agent_run' && entry.agent_run
              ? extractQuestions(entry.agent_run)
              : []
            return (
              <div key={i}>
                {entry.type === 'message' && entry.message && (
                  <MessageItem
                    message={entry.message}
                    agentRun={messageRunMap.get(i)}
                    sessionId={sessionId}
                  />
                )}
                {entry.type === 'agent_run' && entry.agent_run && (
                  <>
                    <AgentRunItem
                      run={entry.agent_run}
                      timelineIndex={i}
                      sessionId={sessionId}
                      hasFollowingMessage={runsWithMessages.has(i)}
                    />
                    {/* HITL questions rendered as chat bubbles below the agent run */}
                    {questions.map((q, qi) => (
                      <div key={qi} className="mt-3">
                        <TimelineQuestion tc={q.tc} agentId={q.agentId} sessionId={sessionId} />
                      </div>
                    ))}
                  </>
                )}
              </div>
            )
          })
        })()}
        {/* Trailing thinking bubble for running agents */}
        {(() => {
          const runningEntry = data.timeline?.findLast(
            (e) => e.type === 'agent_run' && e.agent_run?.status === 'running'
          )
          if (!runningEntry) return null
          const run = runningEntry.agent_run
          const config = getAgentConfig(run.agent_id)
          const AgentIcon = config.icon
          const colors = getAgentMessageColors(config.color)
          return (
            <div className="flex justify-start">
              <div className="flex items-start gap-3 max-w-[85%]">
                <div className={`w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0 ${colors.bg} border ${colors.border}`}>
                  <AgentIcon className={`w-5 h-5 ${colors.accent}`} />
                </div>
                <div className={`rounded-2xl rounded-tl-none shadow-sm border px-4 py-3 ${colors.bg} ${colors.border}`}>
                  <div className={`text-xs font-semibold ${colors.accent}`}>{config.name}</div>
                  <div className="flex items-center gap-2 mt-1 text-sm text-gray-500">
                    <Loader2 className="w-4 h-4 animate-spin" />
                    <span>{config.thinkingLabel || 'Thinking...'}</span>
                  </div>
                </div>
              </div>
            </div>
          )
        })()}
        {/* Pending approvals — always at the bottom, just above the input bar */}
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
                <SurfacedApproval key={tc.approval.id || i} tc={tc} sessionId={sessionId} />
              ))}
            </div>
          )
        })()}
        <div ref={timelineEndRef} />
      </div>

      {/* Input bar - always visible except when failed */}
      {data.status !== 'failed' && (
        <div className="px-4 py-3 border-t bg-white flex-shrink-0">
          <div className="flex gap-2">
            <input
              type="text"
              value={continueInput}
              onChange={(e) => setContinueInput(e.target.value)}
              onKeyDown={(e) =>
                e.key === 'Enter' && !continueMutation.isPending && handleContinueSend()
              }
              placeholder={
                pendingQuestion
                  ? 'Type your answer...'
                  : data.status === 'completed'
                    ? 'Send a follow-up message...'
                    : 'Type a message...'
              }
              className="flex-1 px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent text-sm"
              disabled={continueMutation.isPending}
            />
            <button
              onClick={handleContinueSend}
              disabled={!continueInput.trim() || continueMutation.isPending}
              className="px-3 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {continueMutation.isPending ? (
                <div className="w-5 h-5 border-2 border-white border-t-transparent rounded-full animate-spin" />
              ) : (
                <Send className="w-5 h-5" />
              )}
            </button>
          </div>
          {continueMutation.isError && (
            <p className="mt-1 text-xs text-red-600">
              {continueMutation.error.message}
            </p>
          )}
        </div>
      )}
    </div>
  )
}

// --- Session Sidebar (left panel) ---

const SessionSidebar = ({ activeSessionId, onSelectSession, onNewChat }) => {
  const { data } = useQuery({
    queryKey: ['sessions'],
    queryFn: () => getSessions(1, 50),
    refetchInterval: 5000,
  })

  const sessions = data?.items || []

  return (
    <div className="flex flex-col h-full">
      <div className="px-4 py-3 border-b flex items-center justify-between">
        <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wider">
          Sessions
        </h2>
        <button
          onClick={onNewChat}
          className="p-1.5 rounded-lg bg-blue-600 text-white hover:bg-blue-700 transition-colors"
          title="New chat"
        >
          <Plus className="w-4 h-4" />
        </button>
      </div>
      <div className="flex-1 overflow-y-auto">
        {sessions.length === 0 && (
          <p className="text-gray-400 text-sm text-center py-8">
            No sessions yet
          </p>
        )}
        {sessions.map((s) => (
          <button
            key={s.id}
            onClick={() => onSelectSession(s.id)}
            className={`w-full text-left px-4 py-3 border-b hover:bg-gray-50 transition-colors ${
              activeSessionId === s.id
                ? 'bg-blue-50 border-l-2 border-l-blue-600'
                : ''
            }`}
          >
            <div className="text-sm font-medium truncate">
              {s.title || 'Untitled'}
            </div>
            <div className="flex items-center gap-2 mt-1">
              <StatusBadge status={s.status} />
              {s.project_name && (
                <span className="text-xs text-gray-400 truncate">
                  {s.project_name}
                </span>
              )}
              <span className="text-xs text-gray-400 ml-auto">
                {timeAgo(s.created_at)}
              </span>
            </div>
          </button>
        ))}
      </div>
    </div>
  )
}

// --- New Session Panel (right panel when no session selected) ---

const NewSessionPanel = ({ onSessionCreated }) => {
  const [input, setInput] = useState('')
  const queryClient = useQueryClient()

  const mutation = useMutation({
    mutationFn: (message) => sendChat(message),
    onSuccess: (data) => {
      setInput('')
      queryClient.invalidateQueries({ queryKey: ['sessions'] })
      if (data.session_id) {
        onSessionCreated(data.session_id)
      }
    },
  })

  const handleSend = () => {
    const trimmed = input.trim()
    if (!trimmed) return
    mutation.mutate(trimmed)
  }

  return (
    <div className="flex flex-col items-center justify-center h-full px-8">
      <div className="text-center mb-8">
        <h2 className="text-2xl font-bold text-gray-900 mb-2">New Session</h2>
        <p className="text-gray-500">
          Send a message to start a new governance session
        </p>
      </div>
      <div className="w-full max-w-lg">
        <div className="flex gap-2">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) =>
              e.key === 'Enter' && !mutation.isPending && handleSend()
            }
            placeholder="Describe what you'd like to build..."
            className="flex-1 px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            disabled={mutation.isPending}
          />
          <button
            onClick={handleSend}
            disabled={!input.trim() || mutation.isPending}
            className="px-4 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {mutation.isPending ? (
              <div className="w-5 h-5 border-2 border-white border-t-transparent rounded-full animate-spin" />
            ) : (
              <Send className="w-5 h-5" />
            )}
          </button>
        </div>
        {mutation.isError && (
          <p className="mt-2 text-sm text-red-600">
            {mutation.error.message}
          </p>
        )}
      </div>
    </div>
  )
}

// --- Main Chat Page ---

const ChatPage = () => {
  const [searchParams, setSearchParams] = useSearchParams()
  const sessionId = searchParams.get('session')

  const selectSession = (id) => {
    setSearchParams({ session: id })
  }

  const startNewChat = () => {
    setSearchParams({})
  }

  return (
    <div className="flex gap-4 h-[calc(100vh-8rem)]">
      {/* Left sidebar */}
      <div className="w-80 flex-shrink-0 bg-white border rounded-lg overflow-hidden">
        <SessionSidebar
          activeSessionId={sessionId}
          onSelectSession={selectSession}
          onNewChat={startNewChat}
        />
      </div>

      {/* Right panel */}
      <div className="flex-1 bg-white border rounded-lg overflow-hidden">
        {sessionId ? (
          <SessionDetail sessionId={sessionId} />
        ) : (
          <NewSessionPanel onSessionCreated={selectSession} />
        )}
      </div>
    </div>
  )
}

export default ChatPage
