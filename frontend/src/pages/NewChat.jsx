/**
 * NewChat - Simple debug page for testing the new backend API
 *
 * Shows raw JSON responses from:
 * - GET /api/sessions (list sessions)
 * - GET /api/sessions/{id} (session details)
 * - POST /api/chat (send message)
 */

import React, { useState, useEffect } from 'react'
import { getToken } from '../services/keycloak'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

// Copy button component
const CopyButton = ({ text, label = 'Copy', className = '' }) => {
  const [copied, setCopied] = useState(false)

  const handleCopy = async (e) => {
    e.stopPropagation()
    e.preventDefault()
    if (text === undefined || text === null) {
      console.warn('CopyButton: nothing to copy')
      return
    }
    try {
      const textToCopy = typeof text === 'string' ? text : JSON.stringify(text, null, 2)
      await navigator.clipboard.writeText(textToCopy)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch (err) {
      console.error('Failed to copy:', err)
    }
  }

  return (
    <button
      onClick={handleCopy}
      className={`px-2 py-0.5 text-xs rounded hover:bg-gray-300 transition-colors ${
        copied ? 'bg-green-200 text-green-800' : 'bg-gray-200 text-gray-600'
      } ${className}`}
      title={copied ? 'Copied!' : `Copy ${label}`}
    >
      {copied ? 'Copied!' : label}
    </button>
  )
}

// Collapsible section component
const Collapsible = ({ title, children, defaultOpen = false, className = '', headerClass = '', copyData = null }) => {
  const [isOpen, setIsOpen] = useState(defaultOpen)

  return (
    <div className={`border rounded-lg overflow-hidden ${className}`}>
      <div
        className={`w-full text-left px-3 py-2 bg-gray-100 hover:bg-gray-200 flex items-center gap-2 font-medium cursor-pointer ${headerClass}`}
      >
        <div onClick={() => setIsOpen(!isOpen)} className="flex items-center gap-2 flex-1 min-w-0">
          <span className="text-gray-500">{isOpen ? '▼' : '▶'}</span>
          <span className="flex-1 truncate">{title}</span>
        </div>
        {copyData && <CopyButton text={copyData} label="Copy" />}
      </div>
      {isOpen && (
        <div className="p-3 border-t bg-white">
          {children}
        </div>
      )}
    </div>
  )
}

// Status badge component
const StatusBadge = ({ status }) => {
  const colors = {
    completed: 'bg-green-100 text-green-800',
    running: 'bg-blue-100 text-blue-800',
    pending: 'bg-gray-100 text-gray-800',
    waiting_answer: 'bg-yellow-100 text-yellow-800',
    failed: 'bg-red-100 text-red-800',
    active: 'bg-blue-100 text-blue-800',
  }
  return (
    <span className={`px-2 py-0.5 rounded text-xs font-medium ${colors[status] || 'bg-gray-100'}`}>
      {status}
    </span>
  )
}

// Tool call display component
const ToolCallView = ({ toolCall, index }) => {
  return (
    <Collapsible
      title={
        <span className="flex items-center gap-2">
          <span className="text-gray-500">#{index}</span>
          <code className="text-purple-600">{toolCall.tool_name}</code>
          <StatusBadge status={toolCall.status} />
          {toolCall.question_id && <span className="text-xs text-yellow-600">(HITL)</span>}
        </span>
      }
      className="bg-gray-50"
      copyData={toolCall}
    >
      <div className="space-y-2 text-sm">
        <div className="flex items-center gap-2 text-xs text-gray-500">
          <span>ID:</span>
          <code>{toolCall.id}</code>
          <CopyButton text={toolCall.id} label="ID" />
          {toolCall.question_id && (
            <>
              <span className="ml-2">Question ID:</span>
              <code>{toolCall.question_id}</code>
              <CopyButton text={toolCall.question_id} label="Q-ID" />
            </>
          )}
        </div>
        <div>
          <div className="flex items-center gap-2 mb-1">
            <span className="font-medium text-gray-600">Arguments:</span>
            <CopyButton text={toolCall.arguments} label="Copy" />
          </div>
          <pre className="bg-gray-100 p-2 rounded text-xs overflow-auto max-h-40">
            {JSON.stringify(toolCall.arguments, null, 2)}
          </pre>
        </div>
        {toolCall.result && (
          <div>
            <div className="flex items-center gap-2 mb-1">
              <span className="font-medium text-gray-600">Result:</span>
              <CopyButton text={toolCall.result} label="Copy" />
            </div>
            <pre className="bg-green-50 p-2 rounded text-xs overflow-auto max-h-40">
              {typeof toolCall.result === 'string' ? toolCall.result : JSON.stringify(toolCall.result, null, 2)}
            </pre>
          </div>
        )}
        {toolCall.error && (
          <div>
            <div className="flex items-center gap-2 mb-1">
              <span className="font-medium text-red-600">Error:</span>
              <CopyButton text={toolCall.error} label="Copy" />
            </div>
            <pre className="bg-red-50 p-2 rounded text-xs">{toolCall.error}</pre>
          </div>
        )}
        {toolCall.approval && (
          <div>
            <div className="flex items-center gap-2 mb-1">
              <span className="font-medium text-gray-600">Approval:</span>
              <CopyButton text={toolCall.approval} label="Copy" />
            </div>
            <pre className="bg-blue-50 p-2 rounded text-xs">
              {JSON.stringify(toolCall.approval, null, 2)}
            </pre>
          </div>
        )}
        {toolCall.child_run && (
          <div>
            <span className="font-medium text-gray-600">Child Agent Run:</span>
            <AgentRunView agentRun={toolCall.child_run} />
          </div>
        )}
      </div>
    </Collapsible>
  )
}

// LLM call display component
const LLMCallView = ({ llmCall, index }) => {
  return (
    <Collapsible
      title={
        <span className="flex items-center gap-2">
          <span className="text-gray-500">LLM Call #{index}</span>
          <code className="text-sm text-gray-600">{llmCall.model}</code>
          <span className="text-xs text-gray-500">
            ({llmCall.token_usage?.total_tokens || 0} tokens)
          </span>
        </span>
      }
      className="bg-blue-50"
      copyData={llmCall}
    >
      <div className="space-y-3">
        {/* ID and metadata */}
        <div className="flex items-center gap-2 text-xs text-gray-500">
          <span>ID:</span>
          <code>{llmCall.id}</code>
          <CopyButton text={llmCall.id} label="ID" />
          <span className="ml-2">Provider:</span>
          <code>{llmCall.provider}</code>
          {llmCall.duration_ms && (
            <>
              <span className="ml-2">Duration:</span>
              <code>{llmCall.duration_ms}ms</code>
            </>
          )}
        </div>

        {/* Messages sent to LLM */}
        <Collapsible
          title={`Messages (${llmCall.messages?.length || 0})`}
          className="text-sm"
          copyData={llmCall.messages}
        >
          <div className="space-y-2">
            {llmCall.messages?.map((msg, i) => (
              <div key={i} className="border-l-2 border-gray-300 pl-2">
                <div className="flex items-center gap-2">
                  <span className="font-medium text-gray-600">{msg.role}:</span>
                  <CopyButton text={msg.content || msg} label="Copy" />
                </div>
                <pre className="text-xs bg-gray-50 p-2 mt-1 rounded overflow-auto max-h-32">
                  {typeof msg.content === 'string' ? msg.content : JSON.stringify(msg.content, null, 2)}
                </pre>
              </div>
            ))}
          </div>
        </Collapsible>

        {/* Raw request to LLM */}
        {llmCall.raw_request && (
          <Collapsible
            title="Raw Request (messages sent to LLM)"
            className="text-sm"
            copyData={llmCall.raw_request}
          >
            <pre className="text-xs bg-yellow-50 p-2 rounded overflow-auto max-h-96">
              {JSON.stringify(llmCall.raw_request, null, 2)}
            </pre>
          </Collapsible>
        )}

        {/* Raw response from LLM */}
        {llmCall.raw_response && (
          <Collapsible
            title="Raw LLM Response"
            className="text-sm"
            copyData={llmCall.raw_response}
          >
            <pre className="text-xs bg-gray-100 p-2 rounded overflow-auto max-h-60">
              {JSON.stringify(llmCall.raw_response, null, 2)}
            </pre>
          </Collapsible>
        )}

        {/* Tool calls */}
        {llmCall.tool_calls?.length > 0 && (
          <div>
            <div className="flex items-center gap-2 mb-2">
              <h4 className="font-medium text-gray-600">Tool Calls ({llmCall.tool_calls.length})</h4>
              <CopyButton text={llmCall.tool_calls} label="Copy All" />
            </div>
            <div className="space-y-2">
              {llmCall.tool_calls.map((tc, i) => (
                <ToolCallView key={tc.id || i} toolCall={tc} index={i} />
              ))}
            </div>
          </div>
        )}
      </div>
    </Collapsible>
  )
}

// Agent run display component
const AgentRunView = ({ agentRun }) => {
  return (
    <Collapsible
      title={
        <span className="flex items-center gap-2">
          <span className="font-semibold text-indigo-600">{agentRun.agent_id}</span>
          <StatusBadge status={agentRun.status} />
          <span className="text-xs text-gray-500">
            ({agentRun.llm_calls?.length || 0} LLM calls, {agentRun.token_usage?.total_tokens || 0} tokens)
          </span>
        </span>
      }
      defaultOpen={true}
      className="border-indigo-200"
      copyData={agentRun}
    >
      <div className="space-y-3">
        {/* Summary info */}
        <div className="text-sm text-gray-600 grid grid-cols-2 gap-2">
          <div className="flex items-center gap-1">
            <span>ID:</span>
            <code className="text-xs">{agentRun.id}</code>
            <CopyButton text={agentRun.id} label="ID" />
          </div>
          <div>Sequence: {agentRun.sequence_number ?? 'N/A'}</div>
          {agentRun.started_at && <div>Started: {new Date(agentRun.started_at).toLocaleTimeString()}</div>}
          {agentRun.completed_at && <div>Completed: {new Date(agentRun.completed_at).toLocaleTimeString()}</div>}
        </div>

        {/* Planned prompt (for pending runs) */}
        {agentRun.planned_prompt && (
          <Collapsible title="Planned Prompt" className="text-sm" copyData={agentRun.planned_prompt}>
            <pre className="text-xs bg-yellow-50 p-2 rounded overflow-auto max-h-40">
              {agentRun.planned_prompt}
            </pre>
          </Collapsible>
        )}

        {/* LLM calls */}
        {agentRun.llm_calls?.length > 0 && (
          <div className="space-y-2">
            {agentRun.llm_calls.map((llm, i) => (
              <LLMCallView key={llm.id || i} llmCall={llm} index={i} />
            ))}
          </div>
        )}
      </div>
    </Collapsible>
  )
}

// Message display component
const MessageView = ({ message }) => {
  const roleColors = {
    user: 'border-blue-300 bg-blue-50',
    assistant: 'border-green-300 bg-green-50',
    system: 'border-gray-300 bg-gray-50',
  }
  return (
    <div className={`border-l-4 p-3 rounded-r ${roleColors[message.role] || 'border-gray-300'}`}>
      <div className="flex items-center gap-2 mb-1">
        <span className="font-medium capitalize">{message.role}</span>
        {message.agent_id && <code className="text-xs text-gray-500">({message.agent_id})</code>}
        <span className="text-xs text-gray-400">{new Date(message.created_at).toLocaleTimeString()}</span>
        <CopyButton text={message.content} label="Copy" />
        <CopyButton text={message.id} label="ID" />
      </div>
      <div className="text-sm whitespace-pre-wrap">{message.content}</div>
    </div>
  )
}

// Timeline display component
const TimelineView = ({ timeline }) => {
  if (!timeline || timeline.length === 0) {
    return <p className="text-gray-500 italic">No timeline entries</p>
  }

  return (
    <div className="space-y-3">
      {timeline.map((entry, i) => (
        <div key={i}>
          {entry.type === 'message' && entry.message && (
            <MessageView message={entry.message} />
          )}
          {entry.type === 'agent_run' && entry.agent_run && (
            <AgentRunView agentRun={entry.agent_run} />
          )}
        </div>
      ))}
    </div>
  )
}

// Simple fetch wrapper that logs everything
const apiFetch = async (endpoint, options = {}) => {
  const token = getToken()

  const headers = {
    'Content-Type': 'application/json',
    ...options.headers,
  }

  if (token) {
    headers['Authorization'] = `Bearer ${token}`
  }

  const url = `${API_URL}${endpoint}`
  const method = options.method || 'GET'

  console.log('========================================')
  console.log(`API ${method} ${endpoint}`)
  console.log('URL:', url)
  console.log('Headers:', headers)
  if (options.body) {
    console.log('Body:', JSON.parse(options.body))
  }
  console.log('----------------------------------------')

  try {
    const response = await fetch(url, { ...options, headers })
    const data = await response.json()

    console.log('Status:', response.status)
    console.log('Response:', data)
    console.log('========================================')

    return { ok: response.ok, status: response.status, data }
  } catch (err) {
    console.error('Error:', err)
    console.log('========================================')
    return { ok: false, error: err.message }
  }
}

export default function NewChat() {
  const [sessions, setSessions] = useState(null)
  const [selectedSession, setSelectedSession] = useState(null)
  const [sessionDetail, setSessionDetail] = useState(null)
  const [message, setMessage] = useState('')
  const [chatResponse, setChatResponse] = useState(null)
  const [loading, setLoading] = useState({})
  const [answerText, setAnswerText] = useState('')
  const [answerResponse, setAnswerResponse] = useState(null)

  // Fetch sessions on mount
  useEffect(() => {
    fetchSessions()
  }, [])

  const fetchSessions = async () => {
    setLoading(l => ({ ...l, sessions: true }))
    const result = await apiFetch('/api/sessions')
    setSessions(result)
    setLoading(l => ({ ...l, sessions: false }))
  }

  const fetchSessionDetail = async (sessionId) => {
    setSelectedSession(sessionId)
    setSessionDetail(null)
    setLoading(l => ({ ...l, detail: true }))
    const result = await apiFetch(`/api/sessions/${sessionId}`)
    setSessionDetail(result)
    setLoading(l => ({ ...l, detail: false }))
  }

  const sendChat = async () => {
    if (!message.trim()) return

    setLoading(l => ({ ...l, chat: true }))
    setChatResponse(null)

    const result = await apiFetch('/api/chat', {
      method: 'POST',
      body: JSON.stringify({ message: message.trim() }),
    })

    setChatResponse(result)
    setLoading(l => ({ ...l, chat: false }))

    // Refresh sessions list after sending
    if (result.ok) {
      fetchSessions()
      // If we got a session_id, fetch its details
      if (result.data?.session_id) {
        fetchSessionDetail(result.data.session_id)
      }
    }
  }

  // Find pending HITL questions from session detail
  const findPendingQuestion = () => {
    if (!sessionDetail?.ok || !sessionDetail?.data?.timeline) return null

    for (const entry of sessionDetail.data.timeline) {
      if (entry.type === 'agent_run' && entry.agent_run?.llm_calls) {
        for (const llmCall of entry.agent_run.llm_calls) {
          for (const toolCall of llmCall.tool_calls || []) {
            if (toolCall.status === 'waiting_answer' && toolCall.question_id) {
              return {
                questionId: toolCall.question_id,
                question: toolCall.arguments?.question || 'No question text',
                toolName: toolCall.tool_name,
                agentId: entry.agent_run.agent_id,
              }
            }
          }
        }
      }
    }
    return null
  }

  const submitAnswer = async (questionId) => {
    if (!answerText.trim()) return

    setLoading(l => ({ ...l, answer: true }))
    setAnswerResponse(null)

    const result = await apiFetch(`/api/questions/${questionId}/answer`, {
      method: 'POST',
      body: JSON.stringify({ answer: answerText.trim() }),
    })

    setAnswerResponse(result)
    setLoading(l => ({ ...l, answer: false }))

    // Refresh session detail after answering
    if (result.ok && selectedSession) {
      setAnswerText('')
      // Wait a moment for workflow to progress
      setTimeout(() => fetchSessionDetail(selectedSession), 1000)
    }
  }

  const pendingQuestion = findPendingQuestion()

  return (
    <div className="p-4 space-y-6">
      <h1 className="text-2xl font-bold">New Chat - API Debug Page</h1>
      <p className="text-gray-600">Check browser console for detailed API logs</p>

      {/* Send Chat Section */}
      <div className="border rounded-lg p-4 bg-white">
        <h2 className="text-lg font-semibold mb-3">POST /api/chat</h2>
        <div className="flex gap-2">
          <input
            type="text"
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && sendChat()}
            placeholder="Type a message..."
            className="flex-1 px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
          <button
            onClick={sendChat}
            disabled={loading.chat || !message.trim()}
            className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50"
          >
            {loading.chat ? 'Sending...' : 'Send'}
          </button>
        </div>

        {chatResponse && (
          <div className="mt-4">
            <div className="flex items-center gap-2 mb-2">
              <h3 className="font-medium">Response:</h3>
              <CopyButton text={chatResponse} label="Copy" />
              {chatResponse.data?.session_id && (
                <CopyButton text={chatResponse.data.session_id} label="Session ID" />
              )}
            </div>
            <pre className="bg-gray-100 p-3 rounded-lg text-sm overflow-auto max-h-60">
              {JSON.stringify(chatResponse, null, 2)}
            </pre>
          </div>
        )}
      </div>

      {/* Sessions List Section */}
      <div className="border rounded-lg p-4 bg-white">
        <div className="flex justify-between items-center mb-3">
          <h2 className="text-lg font-semibold">GET /api/sessions</h2>
          <button
            onClick={fetchSessions}
            disabled={loading.sessions}
            className="px-3 py-1 bg-gray-200 rounded hover:bg-gray-300 text-sm"
          >
            {loading.sessions ? 'Loading...' : 'Refresh'}
          </button>
        </div>

        {sessions && (
          <div>
            <div className="flex items-center gap-2 mb-2">
              <h3 className="font-medium">Raw Response:</h3>
              <CopyButton text={sessions} label="Copy" />
            </div>
            <pre className="bg-gray-100 p-3 rounded-lg text-sm overflow-auto max-h-40 mb-4">
              {JSON.stringify(sessions, null, 2)}
            </pre>

            {/* Clickable session list */}
            {sessions.ok && sessions.data?.items && (
              <div>
                <h3 className="font-medium mb-2">Click a session to view details:</h3>
                <div className="space-y-2">
                  {sessions.data.items.map((session) => (
                    <div
                      key={session.id}
                      className={`p-3 rounded-lg border transition-colors ${
                        selectedSession === session.id
                          ? 'bg-blue-50 border-blue-300'
                          : 'hover:bg-gray-50'
                      }`}
                    >
                      <div className="flex items-center justify-between">
                        <button
                          onClick={() => fetchSessionDetail(session.id)}
                          className="flex-1 text-left"
                        >
                          <div className="font-medium truncate">{session.title || 'Untitled'}</div>
                          <div className="text-sm text-gray-500 flex items-center gap-2">
                            <span>ID: {session.id}</span>
                            <StatusBadge status={session.status} />
                          </div>
                        </button>
                        <CopyButton text={session.id} label="ID" className="ml-2" />
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Pending Question Section */}
      {pendingQuestion && (
        <div className="border-2 border-yellow-400 rounded-lg p-4 bg-yellow-50">
          <h2 className="text-lg font-semibold mb-3 text-yellow-800">
            Agent Waiting for Your Answer
          </h2>
          <div className="mb-3 flex items-center gap-2 text-sm">
            <span className="text-gray-600">Agent:</span>
            <span className="font-medium">{pendingQuestion.agentId}</span>
            <span className="text-gray-600 ml-2">Question ID:</span>
            <code className="text-xs">{pendingQuestion.questionId}</code>
            <CopyButton text={pendingQuestion.questionId} label="ID" />
          </div>
          <div className="mb-4 p-3 bg-white rounded-lg border">
            <div className="flex items-start justify-between gap-2">
              <p className="font-medium text-gray-800">{pendingQuestion.question}</p>
              <CopyButton text={pendingQuestion.question} label="Copy" />
            </div>
          </div>
          <div className="flex gap-2">
            <input
              type="text"
              value={answerText}
              onChange={(e) => setAnswerText(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && submitAnswer(pendingQuestion.questionId)}
              placeholder="Type your answer..."
              className="flex-1 px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-yellow-500"
            />
            <button
              onClick={() => submitAnswer(pendingQuestion.questionId)}
              disabled={loading.answer || !answerText.trim()}
              className="px-4 py-2 bg-yellow-600 text-white rounded-lg hover:bg-yellow-700 disabled:opacity-50"
            >
              {loading.answer ? 'Submitting...' : 'Submit Answer'}
            </button>
          </div>
          {answerResponse && (
            <div className="mt-4">
              <div className="flex items-center gap-2 mb-2">
                <h3 className="font-medium">Response:</h3>
                <CopyButton text={answerResponse} label="Copy" />
              </div>
              <pre className="bg-white p-3 rounded-lg text-sm overflow-auto max-h-40 border">
                {JSON.stringify(answerResponse, null, 2)}
              </pre>
            </div>
          )}
        </div>
      )}

      {/* Session Detail Section */}
      {selectedSession && (
        <div className="border rounded-lg p-4 bg-white">
          <div className="flex justify-between items-center mb-3">
            <h2 className="text-lg font-semibold">
              GET /api/sessions/{selectedSession}
            </h2>
            <div className="flex gap-2">
              <button
                onClick={() => fetchSessionDetail(selectedSession)}
                disabled={loading.detail}
                className="px-3 py-1 bg-gray-200 rounded hover:bg-gray-300 text-sm"
              >
                {loading.detail ? 'Loading...' : 'Refresh'}
              </button>
            </div>
          </div>

          {loading.detail ? (
            <p className="text-gray-500">Loading...</p>
          ) : sessionDetail ? (
            <div className="space-y-4">
              {/* Session Summary */}
              {sessionDetail.ok && sessionDetail.data && (
                <div className="bg-gray-50 p-3 rounded-lg">
                  <div className="flex items-center gap-2 mb-2 text-xs text-gray-500">
                    <span>Session ID:</span>
                    <code>{sessionDetail.data.id}</code>
                    <CopyButton text={sessionDetail.data.id} label="ID" />
                    {sessionDetail.data.user_id && (
                      <>
                        <span className="ml-2">User ID:</span>
                        <code>{sessionDetail.data.user_id}</code>
                        <CopyButton text={sessionDetail.data.user_id} label="User ID" />
                      </>
                    )}
                  </div>
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
                    <div>
                      <span className="text-gray-500">Title:</span>{' '}
                      <span className="font-medium">{sessionDetail.data.title}</span>
                    </div>
                    <div>
                      <span className="text-gray-500">Status:</span>{' '}
                      <StatusBadge status={sessionDetail.data.status} />
                    </div>
                    <div>
                      <span className="text-gray-500">Tokens:</span>{' '}
                      <span className="font-medium">{sessionDetail.data.token_usage?.total_tokens || 0}</span>
                    </div>
                    <div>
                      <span className="text-gray-500">Timeline:</span>{' '}
                      <span className="font-medium">{sessionDetail.data.timeline?.length || 0} entries</span>
                    </div>
                  </div>
                </div>
              )}

              {/* Timeline View */}
              {sessionDetail.ok && sessionDetail.data?.timeline && (
                <div>
                  <div className="flex items-center gap-2 mb-3">
                    <h3 className="font-medium">Timeline</h3>
                    <CopyButton text={sessionDetail.data.timeline} label="Copy All" />
                  </div>
                  <TimelineView timeline={sessionDetail.data.timeline} />
                </div>
              )}

              {/* Raw JSON (collapsed) */}
              <Collapsible title="Raw JSON Response" className="text-sm" copyData={sessionDetail}>
                <pre className="bg-gray-100 p-3 rounded-lg text-xs overflow-auto max-h-96">
                  {JSON.stringify(sessionDetail, null, 2)}
                </pre>
              </Collapsible>
            </div>
          ) : null}
        </div>
      )}
    </div>
  )
}
