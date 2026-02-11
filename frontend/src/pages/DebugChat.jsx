/**
 * DebugChat - Terminal-style session inspector
 *
 * Two-panel layout: session list (left) + session detail (right)
 * Detail shows: header, pending HITL banner, flat event log, floating detail overlay
 */

import React, { useState, useEffect, useMemo, useCallback } from 'react'
import { getToken } from '../services/keycloak'
import { getAgentConfig, getAgentMessageColors, formatToolName } from '../utils/agentConfig'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

const WAITING_STATUSES = new Set(['paused_hitl', 'paused_tool', 'waiting_approval', 'waiting_answer'])

// ─── Utilities ───────────────────────────────────────────────────────────────

const generateTimelineSummary = (timeline) => {
  if (!timeline) return null
  return timeline.map(entry => {
    if (entry.type === 'message' && entry.message) {
      return {
        type: 'message',
        timestamp: entry.timestamp,
        role: entry.message.role,
        content: entry.message.content,
        agent_id: entry.message.agent_id,
      }
    }
    if (entry.type === 'agent_run' && entry.agent_run) {
      const run = entry.agent_run
      return {
        type: 'agent_run',
        timestamp: entry.timestamp,
        agent_id: run.agent_id,
        status: run.status,
        sequence_number: run.sequence_number,
        token_usage: run.token_usage,
        llm_calls: run.llm_calls?.map(llm => ({
          model: llm.model,
          provider: llm.provider,
          duration_ms: llm.duration_ms,
          token_usage: llm.token_usage,
          tool_calls: llm.tool_calls?.map(tc => ({
            tool_name: tc.tool_name,
            status: tc.status,
            arguments: tc.arguments,
            result: tc.result,
            error: tc.error || undefined,
          }))
        }))
      }
    }
    return entry
  })
}

const fallbackCopy = (textToCopy) => {
  const textarea = document.createElement('textarea')
  textarea.value = textToCopy
  textarea.style.position = 'fixed'
  textarea.style.left = '-9999px'
  textarea.style.top = '-9999px'
  document.body.appendChild(textarea)
  textarea.focus()
  textarea.select()
  try {
    const success = document.execCommand('copy')
    document.body.removeChild(textarea)
    return success
  } catch (err) {
    document.body.removeChild(textarea)
    return false
  }
}

const downloadAsFile = (data, filename = 'data') => {
  const textToDownload = typeof data === 'string' ? data : JSON.stringify(data, null, 2)
  try {
    const blob = new Blob([textToDownload], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${filename}-${Date.now()}.json`
    a.style.display = 'none'
    document.body.appendChild(a)
    a.click()
    setTimeout(() => { document.body.removeChild(a); URL.revokeObjectURL(url) }, 100)
    return true
  } catch (err) {
    console.error('Download failed:', err)
    return false
  }
}

const formatDuration = (ms) => {
  if (!ms) return null
  if (ms < 1000) return `${ms}ms`
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`
  const mins = Math.floor(ms / 60000)
  const secs = Math.round((ms % 60000) / 1000)
  return `${mins}m ${secs}s`
}

const formatTokens = (n) => {
  if (!n) return '0'
  return n.toLocaleString()
}

const apiFetch = async (endpoint, options = {}) => {
  const token = getToken()
  const headers = { 'Content-Type': 'application/json', ...options.headers }
  if (token) headers['Authorization'] = `Bearer ${token}`
  const url = `${API_URL}${endpoint}`
  try {
    const response = await fetch(url, { ...options, headers })
    const data = await response.json()
    return { ok: response.ok, status: response.status, data }
  } catch (err) {
    console.error('API Error:', err)
    return { ok: false, error: err.message }
  }
}

// ─── Shared small components ─────────────────────────────────────────────────

const CopyButton = ({ text, label = 'Copy', className = '' }) => {
  const [copied, setCopied] = useState(false)
  const [failed, setFailed] = useState(false)

  const handleCopy = async (e) => {
    e.stopPropagation()
    e.preventDefault()
    if (text === undefined || text === null) {
      setFailed(true); setTimeout(() => setFailed(false), 1500); return
    }
    const textToCopy = typeof text === 'string' ? text : JSON.stringify(text, null, 2)
    let success = false
    if (navigator.clipboard?.writeText) {
      try { await navigator.clipboard.writeText(textToCopy); success = true } catch {}
    }
    if (!success) success = fallbackCopy(textToCopy)
    if (success) { setCopied(true); setFailed(false); setTimeout(() => setCopied(false), 1500) }
    else { setFailed(true); setTimeout(() => setFailed(false), 1500) }
  }

  return (
    <button
      onClick={handleCopy}
      className={`px-2 py-0.5 text-xs rounded hover:bg-gray-300 transition-colors ${
        copied ? 'bg-green-200 text-green-800' : failed ? 'bg-red-200 text-red-800' : 'bg-gray-200 text-gray-600'
      } ${className}`}
      title={copied ? 'Copied!' : failed ? 'Failed!' : `Copy ${label}`}
    >
      {copied ? 'Copied!' : failed ? 'Failed!' : label}
    </button>
  )
}

const StatusBadge = ({ status }) => {
  const colors = {
    completed: 'bg-green-100 text-green-800',
    running: 'bg-blue-100 text-blue-800',
    pending: 'bg-gray-100 text-gray-800',
    waiting_answer: 'bg-yellow-100 text-yellow-800',
    paused_hitl: 'bg-yellow-100 text-yellow-800',
    paused_tool: 'bg-yellow-100 text-yellow-800',
    waiting_approval: 'bg-yellow-100 text-yellow-800',
    failed: 'bg-red-100 text-red-800',
    active: 'bg-blue-100 text-blue-800',
  }
  return (
    <span className={`px-2 py-0.5 rounded text-xs font-medium ${colors[status] || 'bg-gray-100'}`}>
      {status}
    </span>
  )
}

// ─── Overflow menu ───────────────────────────────────────────────────────────

const OverflowMenu = ({ items }) => {
  const [open, setOpen] = useState(false)

  return (
    <div className="relative">
      <button
        onClick={() => setOpen(!open)}
        className="px-2 py-0.5 text-xs bg-gray-100 rounded hover:bg-gray-200 text-gray-600"
      >
        &middot;&middot;&middot;
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          <div className="absolute right-0 top-full mt-1 bg-white border rounded shadow-lg z-20 py-1 min-w-[140px]">
            {items.map((item, i) => (
              <button
                key={i}
                onClick={(e) => { item.onClick(e); setOpen(false) }}
                className="w-full text-left px-3 py-1.5 text-xs hover:bg-gray-50 text-gray-700"
              >
                {item.label}
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  )
}

// ─── Left panel: Session list ────────────────────────────────────────────────

const DebugSessionList = ({ sessions, selectedSession, loading, onSelect, onRefresh }) => {
  const [search, setSearch] = useState('')

  const items = sessions?.ok ? sessions.data?.items || [] : []
  const filtered = search
    ? items.filter(s =>
        (s.title || '').toLowerCase().includes(search.toLowerCase()) ||
        s.id.includes(search)
      )
    : items

  return (
    <div className="w-72 flex-shrink-0 border-r bg-white flex flex-col h-full">
      {/* Header */}
      <div className="px-3 py-2 border-b flex items-center justify-between">
        <span className="text-sm font-semibold text-gray-700">Sessions</span>
        <button
          onClick={onRefresh}
          disabled={loading}
          className="px-2 py-0.5 text-xs bg-gray-100 rounded hover:bg-gray-200 disabled:opacity-50"
        >
          {loading ? '...' : 'Refresh'}
        </button>
      </div>

      {/* Search */}
      <div className="px-3 py-2 border-b">
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search sessions..."
          className="w-full px-2 py-1 text-sm border rounded focus:outline-none focus:ring-1 focus:ring-blue-400"
        />
      </div>

      {/* Session items */}
      <div className="flex-1 overflow-y-auto">
        {!sessions && <p className="p-3 text-sm text-gray-400">Loading...</p>}
        {sessions && !sessions.ok && <p className="p-3 text-sm text-red-500">Error loading sessions</p>}
        {filtered.length === 0 && sessions?.ok && (
          <p className="p-3 text-sm text-gray-400">No sessions found</p>
        )}
        {filtered.map((session) => {
          const isSelected = selectedSession === session.id
          return (
            <button
              key={session.id}
              onClick={() => onSelect(session.id)}
              className={`w-full text-left px-3 py-2 border-b text-sm transition-colors ${
                isSelected
                  ? 'bg-blue-50 border-l-2 border-l-blue-500'
                  : 'hover:bg-gray-50 border-l-2 border-l-transparent'
              }`}
            >
              <div className="font-medium truncate text-gray-800">
                {session.title || 'Untitled'}
              </div>
              <div className="flex items-center gap-2 mt-0.5">
                <StatusBadge status={session.status} />
                {session.token_usage?.total_tokens > 0 && (
                  <span className="text-xs text-gray-400">
                    {formatTokens(session.token_usage.total_tokens)} tok
                  </span>
                )}
              </div>
            </button>
          )
        })}
      </div>
    </div>
  )
}

// ─── Event log lines (flat, no expand/collapse) ─────────────────────────────

const agentStatusBorder = (status) => {
  if (status === 'completed') return 'border-l-green-500'
  if (status === 'failed') return 'border-l-red-500'
  if (status === 'running') return 'border-l-blue-500'
  if (WAITING_STATUSES.has(status)) return 'border-l-yellow-500'
  return 'border-l-gray-300'
}

const toolArrowColor = (status) => {
  if (status === 'completed') return 'text-green-500'
  if (status === 'failed') return 'text-red-500'
  if (status === 'running') return 'text-blue-500'
  if (WAITING_STATUSES.has(status)) return 'text-yellow-500'
  return 'text-gray-400'
}

const AgentHeaderLine = ({ agentRun, selected, onSelect }) => {
  const config = getAgentConfig(agentRun.agent_id)
  const colors = getAgentMessageColors(config.color)
  const tokens = agentRun.token_usage?.total_tokens || 0

  const duration = useMemo(() => {
    if (agentRun.started_at && agentRun.completed_at) {
      return formatDuration(new Date(agentRun.completed_at) - new Date(agentRun.started_at))
    }
    const total = agentRun.llm_calls?.reduce((sum, llm) => sum + (llm.duration_ms || 0), 0) || 0
    return total > 0 ? formatDuration(total) : null
  }, [agentRun])

  return (
    <button
      onClick={onSelect}
      className={`w-full text-left px-3 py-1.5 flex items-center gap-2 text-sm border-l-2 transition-colors ${
        agentStatusBorder(agentRun.status)
      } ${selected ? 'bg-blue-50' : 'hover:bg-gray-50'}`}
    >
      <span className={`font-semibold uppercase text-xs tracking-wide ${colors.accent}`}>
        {config.name}
      </span>
      {tokens > 0 && (
        <span className="text-xs text-gray-400">{formatTokens(tokens)} tok</span>
      )}
      {duration && (
        <span className="text-xs text-gray-400">&middot; {duration}</span>
      )}
      {agentRun.status === 'running' && (
        <span className="ml-auto inline-block w-2 h-2 bg-blue-500 rounded-full animate-pulse" />
      )}
    </button>
  )
}

const ToolLine = ({ tc, selected, onSelect }) => {
  return (
    <button
      onClick={onSelect}
      className={`w-full text-left pl-8 pr-3 py-1 flex items-center gap-2 text-xs transition-colors ${
        selected ? 'bg-blue-50' : 'hover:bg-gray-50'
      }`}
    >
      <span className={`font-bold ${toolArrowColor(tc.status)}`}>&rarr;</span>
      <span className={`font-medium ${toolArrowColor(tc.status)}`}>{formatToolName(tc.tool_name)}</span>
      {tc.question_id && <span className="bg-orange-100 text-orange-700 text-[10px] font-semibold px-1.5 py-0.5 rounded">HITL</span>}
    </button>
  )
}

// ─── Detail pane (bottom of right panel) ─────────────────────────────────────

const ToolDetail = ({ tc, agentRun }) => {
  const config = getAgentConfig(agentRun.agent_id)

  return (
    <div className="space-y-3 text-xs">
      <div className="flex items-center gap-2">
        <span className="text-purple-600 font-semibold">{formatToolName(tc.tool_name)}</span>
        <StatusBadge status={tc.status} />
        <span className="text-gray-400">({config.name})</span>
      </div>

      {/* Arguments */}
      {tc.arguments && (
        <div>
          <div className="flex items-center gap-2 mb-1">
            <span className="font-medium text-gray-500">Arguments</span>
            <CopyButton text={tc.arguments} label="Copy" />
          </div>
          <pre className="bg-gray-50 p-2 rounded overflow-auto max-h-48 whitespace-pre-wrap break-all text-gray-700">
            {typeof tc.arguments === 'string' ? tc.arguments : JSON.stringify(tc.arguments, null, 2)}
          </pre>
        </div>
      )}

      {/* Result */}
      {tc.result && (
        <div>
          <div className="flex items-center gap-2 mb-1">
            <span className="font-medium text-green-600">Result</span>
            <CopyButton text={tc.result} label="Copy" />
          </div>
          <pre className="bg-green-50 p-2 rounded overflow-auto max-h-48 whitespace-pre-wrap break-all text-gray-700">
            {typeof tc.result === 'string' ? tc.result : JSON.stringify(tc.result, null, 2)}
          </pre>
        </div>
      )}

      {/* Error */}
      {tc.error && (
        <div>
          <div className="flex items-center gap-2 mb-1">
            <span className="font-medium text-red-600">Error</span>
            <CopyButton text={tc.error} label="Copy" />
          </div>
          <pre className="bg-red-50 p-2 rounded overflow-auto max-h-32 text-red-700">
            {tc.error}
          </pre>
        </div>
      )}

      {/* Approval */}
      {tc.approval && (
        <div>
          <div className="flex items-center gap-2 mb-1">
            <span className="font-medium text-gray-500">Approval</span>
            <CopyButton text={tc.approval} label="Copy" />
          </div>
          <pre className="bg-blue-50 p-2 rounded overflow-auto max-h-32 mt-1">
            {JSON.stringify(tc.approval, null, 2)}
          </pre>
        </div>
      )}
    </div>
  )
}

const AgentDetail = ({ agentRun }) => {
  const config = getAgentConfig(agentRun.agent_id)
  const colors = getAgentMessageColors(config.color)
  const tokens = agentRun.token_usage?.total_tokens || 0
  const llmCalls = agentRun.llm_calls || []

  const duration = useMemo(() => {
    if (agentRun.started_at && agentRun.completed_at) {
      return formatDuration(new Date(agentRun.completed_at) - new Date(agentRun.started_at))
    }
    const total = llmCalls.reduce((sum, llm) => sum + (llm.duration_ms || 0), 0)
    return total > 0 ? formatDuration(total) : null
  }, [agentRun, llmCalls])

  return (
    <div className="space-y-3 text-xs">
      <div className="flex items-center gap-2">
        <span className={`font-semibold ${colors.accent}`}>{config.name}</span>
        <StatusBadge status={agentRun.status} />
        {tokens > 0 && <span className="text-gray-400">{formatTokens(tokens)} tok</span>}
        {duration && <span className="text-gray-400">&middot; {duration}</span>}
      </div>

      {/* Planned prompt */}
      {agentRun.planned_prompt && (
        <div>
          <div className="flex items-center gap-2 mb-1">
            <span className="font-medium text-gray-500">Planned Prompt</span>
            <CopyButton text={agentRun.planned_prompt} label="Copy" />
          </div>
          <pre className="bg-yellow-50 p-2 rounded overflow-auto max-h-40 whitespace-pre-wrap break-all text-gray-600">
            {agentRun.planned_prompt}
          </pre>
        </div>
      )}

      {/* LLM calls table */}
      {llmCalls.length > 0 ? (
        <div>
          <span className="font-medium text-gray-500 mb-1 block">LLM Calls</span>
          <table className="w-full text-left">
            <thead>
              <tr className="text-gray-400 border-b">
                <th className="py-1 pr-3 font-medium">#</th>
                <th className="py-1 pr-3 font-medium">Model</th>
                <th className="py-1 pr-3 font-medium text-right">Tokens</th>
                <th className="py-1 pr-3 font-medium text-right">Duration</th>
                <th className="py-1 font-medium text-right">Tools</th>
              </tr>
            </thead>
            <tbody>
              {llmCalls.map((llm, i) => (
                <tr key={llm.id || i} className="border-b border-gray-50">
                  <td className="py-1 pr-3 text-gray-400 font-mono">{i + 1}</td>
                  <td className="py-1 pr-3 text-gray-600"><code>{llm.model}</code></td>
                  <td className="py-1 pr-3 text-right text-gray-500">
                    {formatTokens(llm.token_usage?.total_tokens)}
                  </td>
                  <td className="py-1 pr-3 text-right text-gray-500">
                    {formatDuration(llm.duration_ms) || '-'}
                  </td>
                  <td className="py-1 text-right text-purple-500">
                    {llm.tool_calls?.length || 0}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="text-gray-400 italic">No LLM calls yet</p>
      )}

      {/* Copy raw button */}
      <div>
        <CopyButton text={agentRun} label="Copy Raw JSON" />
      </div>
    </div>
  )
}

const DetailPane = ({ selection, onClose }) => {
  if (!selection) return null

  return (
    <>
      {/* Backdrop */}
      <div className="fixed inset-0 bg-black/20 z-30" onClick={onClose} />
      {/* Floating panel */}
      <div className="fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 z-40 bg-white rounded-lg shadow-2xl border flex flex-col"
        style={{ width: 'min(640px, 90vw)', maxHeight: '70vh' }}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-2.5 border-b bg-gray-50 rounded-t-lg flex-shrink-0">
          <span className="text-sm font-medium text-gray-700">
            {selection.type === 'tool' ? formatToolName(selection.toolCall.tool_name) : getAgentConfig(selection.agentRun.agent_id).name}
          </span>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600 text-lg leading-none px-1"
            title="Close (Esc)"
          >
            &times;
          </button>
        </div>
        {/* Content */}
        <div className="flex-1 overflow-y-auto px-4 py-3">
          {selection.type === 'tool' && (
            <ToolDetail tc={selection.toolCall} agentRun={selection.agentRun} />
          )}
          {selection.type === 'agent' && (
            <AgentDetail agentRun={selection.agentRun} />
          )}
        </div>
      </div>
    </>
  )
}

// ─── Right panel: Session detail ─────────────────────────────────────────────

const DebugSessionDetail = ({ sessionDetail, loading, onRefresh, selectedSession, answerText, setAnswerText, onSubmitAnswer, answerLoading }) => {
  const [selection, setSelection] = useState(null)

  // Close detail pane on Esc
  useEffect(() => {
    const handleKeyDown = (e) => {
      if (e.key === 'Escape') setSelection(null)
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [])

  // Clear selection when session changes
  useEffect(() => {
    setSelection(null)
  }, [selectedSession])

  const closeDetail = useCallback(() => setSelection(null), [])

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center text-gray-400">
        Loading session...
      </div>
    )
  }

  if (!sessionDetail || !sessionDetail.ok || !sessionDetail.data) {
    return (
      <div className="flex-1 flex items-center justify-center text-gray-400">
        {sessionDetail?.error ? `Error: ${sessionDetail.error}` : 'Select a session to inspect'}
      </div>
    )
  }

  const data = sessionDetail.data
  const timeline = data.timeline || []
  const totalTokens = data.token_usage?.total_tokens || 0

  // Extract agent runs from timeline
  const agentRuns = timeline
    .filter(e => e.type === 'agent_run' && e.agent_run)
    .map(e => e.agent_run)

  // Find pending HITL question
  const pendingQuestion = (() => {
    for (const entry of timeline) {
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
  })()

  // Compute session duration
  const sessionDuration = (() => {
    if (data.created_at && data.updated_at) {
      const ms = new Date(data.updated_at) - new Date(data.created_at)
      return formatDuration(ms)
    }
    return null
  })()

  // Build flat event list: agent headers + tool call lines
  const eventItems = []
  for (const run of agentRuns) {
    eventItems.push({ type: 'agent', agentRun: run })
    for (const llm of run.llm_calls || []) {
      for (const tc of llm.tool_calls || []) {
        eventItems.push({ type: 'tool', toolCall: tc, agentRun: run })
      }
    }
  }

  // Check if a given item matches the current selection
  const isSelected = (item) => {
    if (!selection) return false
    if (item.type === 'agent' && selection.type === 'agent') {
      return item.agentRun === selection.agentRun
    }
    if (item.type === 'tool' && selection.type === 'tool') {
      return item.toolCall === selection.toolCall
    }
    return false
  }

  // Overflow menu items
  const overflowItems = [
    {
      label: 'Copy Summary',
      onClick: async (e) => {
        e.stopPropagation()
        const text = JSON.stringify(generateTimelineSummary(timeline), null, 2)
        try { await navigator.clipboard.writeText(text) } catch { fallbackCopy(text) }
      }
    },
    {
      label: 'Copy JSON',
      onClick: async (e) => {
        e.stopPropagation()
        const text = JSON.stringify(sessionDetail, null, 2)
        try { await navigator.clipboard.writeText(text) } catch { fallbackCopy(text) }
      }
    },
    {
      label: 'Download JSON',
      onClick: (e) => {
        e.stopPropagation()
        downloadAsFile(sessionDetail, 'session')
      }
    },
  ]

  return (
    <div className="flex-1 flex flex-col h-full overflow-hidden">
      {/* Header bar — simplified */}
      <div className="px-4 py-3 border-b bg-white flex-shrink-0">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3 min-w-0">
            <h2 className="text-base font-semibold text-gray-800 truncate">
              {data.title || 'Untitled'}
            </h2>
            <StatusBadge status={data.status} />
          </div>
          <div className="flex items-center gap-2 flex-shrink-0">
            {totalTokens > 0 && (
              <span className="text-xs text-gray-400">{formatTokens(totalTokens)} tok</span>
            )}
            {sessionDuration && (
              <span className="text-xs text-gray-400">{sessionDuration}</span>
            )}
            <OverflowMenu items={overflowItems} />
            <button
              onClick={onRefresh}
              className="px-2 py-0.5 text-xs bg-gray-100 rounded hover:bg-gray-200"
            >
              &#8635;
            </button>
          </div>
        </div>
      </div>

      {/* Pending HITL question banner */}
      {pendingQuestion && (
        <div className="px-4 py-3 bg-yellow-50 border-b border-yellow-200 flex-shrink-0">
          <div className="flex items-center gap-2 text-sm mb-2">
            <span className="font-medium text-yellow-800">
              {getAgentConfig(pendingQuestion.agentId).name} is waiting for your answer
            </span>
          </div>
          <div className="p-2 bg-white rounded border border-yellow-200 mb-2 text-sm text-gray-800">
            {pendingQuestion.question}
          </div>
          <div className="flex gap-2">
            <input
              type="text"
              value={answerText}
              onChange={(e) => setAnswerText(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && onSubmitAnswer(pendingQuestion.questionId)}
              placeholder="Type your answer..."
              className="flex-1 px-2 py-1 text-sm border rounded focus:outline-none focus:ring-1 focus:ring-yellow-400"
            />
            <button
              onClick={() => onSubmitAnswer(pendingQuestion.questionId)}
              disabled={answerLoading || !answerText.trim()}
              className="px-3 py-1 text-sm bg-yellow-600 text-white rounded hover:bg-yellow-700 disabled:opacity-50"
            >
              {answerLoading ? 'Sending...' : 'Answer'}
            </button>
          </div>
        </div>
      )}

      {/* Event log — flat, scrollable */}
      <div className={`flex-1 overflow-y-auto bg-white ${selection ? '' : ''}`}>
        {eventItems.length === 0 && (
          <p className="p-4 text-sm text-gray-400 italic">No agent runs in this session</p>
        )}
        {eventItems.map((item, i) => {
          if (item.type === 'agent') {
            return (
              <AgentHeaderLine
                key={`agent-${item.agentRun.id || i}`}
                agentRun={item.agentRun}
                selected={isSelected(item)}
                onSelect={() => setSelection({ type: 'agent', agentRun: item.agentRun })}
              />
            )
          }
          return (
            <ToolLine
              key={`tool-${item.toolCall.id || i}`}
              tc={item.toolCall}
              selected={isSelected(item)}
              onSelect={() => setSelection({ type: 'tool', toolCall: item.toolCall, agentRun: item.agentRun })}
            />
          )
        })}
      </div>

      {/* Detail pane — appears when something is selected */}
      <DetailPane selection={selection} onClose={closeDetail} />
    </div>
  )
}

// ─── Main component ──────────────────────────────────────────────────────────

export default function DebugChat() {
  const [sessions, setSessions] = useState(null)
  const [selectedSession, setSelectedSession] = useState(null)
  const [sessionDetail, setSessionDetail] = useState(null)
  const [loading, setLoading] = useState({})
  const [answerText, setAnswerText] = useState('')

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

  const submitAnswer = async (questionId) => {
    if (!answerText.trim()) return
    setLoading(l => ({ ...l, answer: true }))
    const result = await apiFetch(`/api/questions/${questionId}/answer`, {
      method: 'POST',
      body: JSON.stringify({ answer: answerText.trim() }),
    })
    setLoading(l => ({ ...l, answer: false }))
    if (result.ok && selectedSession) {
      setAnswerText('')
      setTimeout(() => fetchSessionDetail(selectedSession), 1000)
    }
  }

  return (
    <div className="flex h-[calc(100vh-4rem)] bg-gray-50">
      <DebugSessionList
        sessions={sessions}
        selectedSession={selectedSession}
        loading={loading.sessions}
        onSelect={fetchSessionDetail}
        onRefresh={fetchSessions}
      />
      <DebugSessionDetail
        sessionDetail={sessionDetail}
        loading={loading.detail}
        onRefresh={() => selectedSession && fetchSessionDetail(selectedSession)}
        selectedSession={selectedSession}
        answerText={answerText}
        setAnswerText={setAnswerText}
        onSubmitAnswer={submitAnswer}
        answerLoading={loading.answer}
      />
    </div>
  )
}
