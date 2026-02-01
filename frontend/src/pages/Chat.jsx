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
import { Send, ExternalLink, Plus, Copy, Check } from 'lucide-react'
import {
  getSessions,
  getSession,
  sendChat,
  approveApproval,
  rejectApproval,
  answerQuestion,
} from '../services/api'
import { getAgentConfig, getAgentColorClasses } from '../utils/agentConfig'

// --- Helpers ---

const STATUS_STYLES = {
  completed: 'bg-green-100 text-green-700',
  running: 'bg-blue-100 text-blue-700 animate-pulse',
  pending: 'bg-gray-100 text-gray-600',
  failed: 'bg-red-100 text-red-700',
  paused_hitl: 'bg-yellow-100 text-yellow-700',
  paused_tool: 'bg-yellow-100 text-yellow-700',
  waiting_approval: 'bg-yellow-100 text-yellow-700',
  waiting_answer: 'bg-yellow-100 text-yellow-700',
  approved: 'bg-green-100 text-green-700',
  rejected: 'bg-red-100 text-red-700',
}

const StatusBadge = ({ status }) => (
  <span
    className={`inline-block px-2 py-0.5 rounded-full text-xs font-medium ${
      STATUS_STYLES[status] || 'bg-gray-100 text-gray-600'
    }`}
  >
    {status?.replace(/_/g, ' ')}
  </span>
)

const JsonBlock = ({ label, data }) => {
  if (data === null || data === undefined) return null
  return (
    <details className="mt-1" data-label={label}>
      <summary className="text-xs text-gray-500 cursor-pointer hover:text-gray-700">
        {label}
      </summary>
      <pre className="mt-1 p-2 bg-gray-50 rounded text-xs overflow-auto max-h-60 whitespace-pre-wrap break-all">
        {typeof data === 'string' ? data : JSON.stringify(data, null, 2)}
      </pre>
    </details>
  )
}

const AgentBadge = ({ agentId }) => {
  const config = getAgentConfig(agentId)
  const colorClasses = getAgentColorClasses(config.color)
  return (
    <span
      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium border ${colorClasses}`}
    >
      {config.name}
    </span>
  )
}

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
      const runEl = containerEl.querySelector(
        `details[data-type="agent-run"][data-timeline-idx="${i}"]`
      )

      const runEntry = {
        type: 'agent_run',
        agent_id: run.agent_id,
        status: run.status,
        sequence_number: run.sequence_number,
      }

      // Only include LLM calls if the agent run <details> is open
      if (runEl?.open && run.llm_calls?.length) {
        runEntry.llm_calls = run.llm_calls.map((llm, li) => {
          const llmEl = runEl.querySelector(
            `details[data-type="llm-call"][data-llm-idx="${li}"]`
          )
          const llmEntry = {
            model: llm.model,
            total_tokens: llm.token_usage?.total_tokens || 0,
          }

          // Only include tool calls if the LLM call <details> is open
          if (llmEl?.open && llm.tool_calls?.length) {
            llmEntry.tool_calls = llm.tool_calls.map((tc, ti) => {
              const tcEl = llmEl.querySelector(
                `details[data-type="tool-call"][data-tc-idx="${ti}"]`
              )
              const tcEntry = {
                tool_name: tc.tool_name,
                status: tc.status,
              }

              // Only include args/result/approval if the tool call <details> is open
              if (tcEl?.open) {
                const argsOpen = tcEl.querySelector(
                  'details[data-label="Arguments"]'
                )?.open
                const resultOpen = tcEl.querySelector(
                  'details[data-label="Result"]'
                )?.open
                const approvalOpen = tcEl.querySelector(
                  'details[data-label="Approval details"]'
                )?.open

                if (argsOpen && tc.arguments) tcEntry.arguments = tc.arguments
                if (resultOpen && tc.result) tcEntry.result = tc.result
                if (tc.error) tcEntry.error = tc.error
                if (approvalOpen && tc.approval) tcEntry.approval = tc.approval
              }

              return tcEntry
            })
          }

          return llmEntry
        })
      }

      result.timeline.push(runEntry)
    }
  })

  return result
}

const ACTIVE_STATUSES = new Set([
  'running',
  'paused_hitl',
  'paused_tool',
  'waiting_approval',
  'waiting_answer',
])

// --- Tool Call ---

const ToolCallItem = ({ tc, tcIndex, sessionId }) => {
  const queryClient = useQueryClient()
  const [answer, setAnswer] = useState('')

  const approveMut = useMutation({
    mutationFn: () => approveApproval(tc.approval?.id, ''),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ['session', sessionId] }),
  })

  const rejectMut = useMutation({
    mutationFn: () => rejectApproval(tc.approval?.id, ''),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ['session', sessionId] }),
  })

  const answerMut = useMutation({
    mutationFn: () => answerQuestion(tc.question_id, answer),
    onSuccess: () => {
      setAnswer('')
      queryClient.invalidateQueries({ queryKey: ['session', sessionId] })
    },
  })

  const isPendingApproval = tc.approval?.status === 'pending'
  const isWaitingAnswer = tc.status === 'waiting_answer' && tc.question_id
  const needsAction = isPendingApproval || isWaitingAnswer

  const detailsRef = useRef(null)
  const autoOpenedRef = useRef(false)

  useEffect(() => {
    if (needsAction && !autoOpenedRef.current && detailsRef.current) {
      detailsRef.current.open = true
      autoOpenedRef.current = true
    }
  }, [needsAction])

  return (
    <div className="ml-4 border-l-2 border-gray-200 pl-3 py-1">
      <details ref={detailsRef} data-type="tool-call" data-tc-idx={tcIndex}>
        <summary className="cursor-pointer text-sm flex items-center gap-2">
          <code className="text-purple-600 font-medium">{tc.tool_name}</code>
          <StatusBadge status={tc.status} />
          {isPendingApproval && (
            <span className="text-xs text-yellow-600 font-medium">
              needs approval
            </span>
          )}
          {isWaitingAnswer && (
            <span className="text-xs text-yellow-600 font-medium">
              needs answer
            </span>
          )}
        </summary>
        <div className="mt-2 space-y-2 text-sm">
          <JsonBlock label="Arguments" data={tc.arguments} />
          <JsonBlock label="Result" data={tc.result} />
          {tc.error && (
            <div className="p-2 bg-red-50 border border-red-200 rounded text-xs text-red-700">
              <strong>Error:</strong> {tc.error}
            </div>
          )}
          {tc.approval && <JsonBlock label="Approval details" data={tc.approval} />}
        </div>
      </details>

      {isPendingApproval && (
        <div className="mt-2 ml-4 p-3 bg-blue-50 border border-blue-200 rounded">
          <p className="text-sm text-gray-700 mb-2">
            <strong>{tc.tool_name}</strong> requires approval
          </p>
          <div className="flex gap-2">
            <button
              onClick={() => approveMut.mutate()}
              disabled={approveMut.isPending}
              className="px-3 py-1.5 bg-green-600 text-white text-sm rounded hover:bg-green-700 disabled:opacity-50"
            >
              {approveMut.isPending ? 'Approving...' : 'Approve'}
            </button>
            <button
              onClick={() => rejectMut.mutate()}
              disabled={rejectMut.isPending}
              className="px-3 py-1.5 bg-red-600 text-white text-sm rounded hover:bg-red-700 disabled:opacity-50"
            >
              {rejectMut.isPending ? 'Rejecting...' : 'Reject'}
            </button>
          </div>
        </div>
      )}

      {isWaitingAnswer && (
        <div className="mt-2 ml-4 p-3 bg-yellow-50 border border-yellow-200 rounded">
          <p className="text-sm font-medium text-yellow-800 mb-2">
            {tc.arguments?.question || 'Agent is waiting for your answer'}
          </p>
          <div className="flex gap-2">
            <input
              type="text"
              value={answer}
              onChange={(e) => setAnswer(e.target.value)}
              onKeyDown={(e) =>
                e.key === 'Enter' && answer.trim() && answerMut.mutate()
              }
              placeholder="Type your answer..."
              className="flex-1 px-3 py-1.5 text-sm border rounded focus:outline-none focus:ring-2 focus:ring-yellow-500"
            />
            <button
              onClick={() => answerMut.mutate()}
              disabled={!answer.trim() || answerMut.isPending}
              className="px-3 py-1.5 bg-yellow-600 text-white text-sm rounded hover:bg-yellow-700 disabled:opacity-50"
            >
              {answerMut.isPending ? 'Sending...' : 'Answer'}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

// --- LLM Call ---

const LLMCallItem = ({ llmCall, index, sessionId }) => {
  const toolCount = llmCall.tool_calls?.length || 0
  const hasActionableTools = llmCall.tool_calls?.some(
    (tc) => tc.approval?.status === 'pending' || (tc.status === 'waiting_answer' && tc.question_id)
  )

  const detailsRef = useRef(null)
  const autoOpenedRef = useRef(false)

  useEffect(() => {
    if (hasActionableTools && !autoOpenedRef.current && detailsRef.current) {
      detailsRef.current.open = true
      autoOpenedRef.current = true
    }
  }, [hasActionableTools])

  return (
    <details ref={detailsRef} data-type="llm-call" data-llm-idx={index} className="ml-4 border-l-2 border-blue-200 pl-3 py-1">
      <summary className="cursor-pointer text-sm flex items-center gap-2">
        <span className="text-gray-500">LLM #{index + 1}</span>
        <code className="text-xs text-gray-600">{llmCall.model}</code>
        <span className="text-xs text-gray-400">
          {llmCall.token_usage?.total_tokens || 0} tokens
        </span>
        {toolCount > 0 && (
          <span className="text-xs text-purple-600">
            {toolCount} tool call{toolCount !== 1 ? 's' : ''}
          </span>
        )}
      </summary>
      <div className="mt-2 space-y-1">
        {llmCall.tool_calls?.map((tc, i) => (
          <ToolCallItem key={tc.id || i} tc={tc} tcIndex={i} sessionId={sessionId} />
        ))}
        {toolCount === 0 && (
          <p className="text-xs text-gray-400 ml-4">No tool calls</p>
        )}
      </div>
    </details>
  )
}

// --- Agent Run ---

const AgentRunItem = ({ run, timelineIndex, sessionId }) => {
  const detailsRef = useRef(null)
  const autoOpenedRef = useRef(false)
  const isActive = ACTIVE_STATUSES.has(run.status)
  const llmCount = run.llm_calls?.length || 0

  // Auto-open once when run becomes active, then let user control
  useEffect(() => {
    if (isActive && !autoOpenedRef.current && detailsRef.current) {
      detailsRef.current.open = true
      autoOpenedRef.current = true
    }
  }, [isActive])

  return (
    <details ref={detailsRef} data-type="agent-run" data-timeline-idx={timelineIndex} className="border rounded-lg overflow-hidden">
      <summary className="cursor-pointer px-4 py-3 bg-gray-50 hover:bg-gray-100 flex items-center gap-2 text-sm">
        <AgentBadge agentId={run.agent_id} />
        <StatusBadge status={run.status} />
        <span className="text-xs text-gray-500">#{run.sequence_number}</span>
        <span className="text-xs text-gray-400">
          {llmCount} LLM call{llmCount !== 1 ? 's' : ''}
          {run.token_usage?.total_tokens
            ? ` · ${run.token_usage.total_tokens} tokens`
            : ''}
        </span>
      </summary>
      <div className="px-4 py-3 space-y-1 border-t">
        {run.llm_calls?.map((llm, i) => (
          <LLMCallItem
            key={llm.id || i}
            llmCall={llm}
            index={i}
            sessionId={sessionId}
          />
        ))}
        {llmCount === 0 && (
          <p className="text-sm text-gray-400">No LLM calls yet</p>
        )}
      </div>
    </details>
  )
}

// --- Message ---

const MessageItem = ({ message }) => {
  const isUser = message.role === 'user'
  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
      <div
        className={`max-w-[80%] rounded-lg px-4 py-2 text-sm ${
          isUser ? 'bg-blue-600 text-white' : 'bg-gray-100 text-gray-900'
        }`}
      >
        {message.agent_id && !isUser && (
          <div className="mb-1">
            <AgentBadge agentId={message.agent_id} />
          </div>
        )}
        <div className="whitespace-pre-wrap">{message.content}</div>
        <div
          className={`text-xs mt-1 ${isUser ? 'text-blue-200' : 'text-gray-400'}`}
        >
          {message.created_at &&
            new Date(message.created_at).toLocaleTimeString()}
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

      {/* Timeline */}
      <div ref={timelineRef} className="flex-1 overflow-y-auto px-4 py-4 space-y-3">
        {(!data.timeline || data.timeline.length === 0) && (
          <p className="text-gray-400 text-center py-8">
            No timeline entries yet
          </p>
        )}
        {data.timeline?.map((entry, i) => (
          <div key={i}>
            {entry.type === 'message' && entry.message && (
              <MessageItem message={entry.message} />
            )}
            {entry.type === 'agent_run' && entry.agent_run && (
              <AgentRunItem run={entry.agent_run} timelineIndex={i} sessionId={sessionId} />
            )}
          </div>
        ))}
        <div ref={timelineEndRef} />
      </div>
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
