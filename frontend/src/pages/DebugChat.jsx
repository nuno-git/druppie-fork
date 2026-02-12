/**
 * DebugChat - Terminal-style session inspector
 *
 * Two-panel layout: session list (left) + session detail (right)
 * Detail shows: header, pending HITL banner, flat event log, floating detail overlay
 */

import React, { useState, useEffect, useMemo, useCallback, useRef } from 'react'
import {
  Search,
  X,
  PanelLeftClose,
  PanelLeftOpen,
  Copy,
  Download,
  MoreHorizontal,
  MessageSquare,
  Send,
  Loader2,
  PauseCircle,
  RefreshCw,
  Braces,
  Check,
} from 'lucide-react'
import { getToken } from '../services/keycloak'
import { getAgentConfig, formatToolName } from '../utils/agentConfig'
import { formatDuration, formatTokens } from '../utils/tokenUtils'
import CopyButton from '../components/shared/CopyButton'

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

const StatusBadge = ({ status }) => {
  let color = 'bg-gray-100 text-gray-600'
  if (status === 'failed') color = 'bg-red-50 text-red-700'
  else if (status === 'running' || status === 'active') color = 'bg-gray-100 text-gray-700'

  return (
    <span className={`px-1.5 py-0.5 rounded text-xs ${color}`}>
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
        className="p-1.5 rounded text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors"
        title="More actions"
      >
        <MoreHorizontal className="w-4 h-4" />
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          <div className="absolute right-0 top-full mt-1 bg-white border rounded shadow-lg z-20 py-1 min-w-[140px]">
            {items.map((item, i) => {
              const ItemIcon = item.icon
              return (
                <button
                  key={i}
                  onClick={(e) => { item.onClick(e); setOpen(false) }}
                  className="w-full text-left px-3 py-1.5 text-xs hover:bg-gray-50 text-gray-700 flex items-center gap-2"
                >
                  {ItemIcon && <ItemIcon className="w-3.5 h-3.5 text-gray-400" />}
                  {item.label}
                </button>
              )
            })}
          </div>
        </>
      )}
    </div>
  )
}

// ─── Date grouping helper ────────────────────────────────────────────────────

const groupByDate = (sessions) => {
  const groups = []
  const today = new Date()
  const yesterday = new Date(today)
  yesterday.setDate(yesterday.getDate() - 1)

  const isToday = (d) => d.toDateString() === today.toDateString()
  const isYesterday = (d) => d.toDateString() === yesterday.toDateString()

  let currentLabel = null
  for (const session of sessions) {
    const date = new Date(session.updated_at || session.created_at)
    let label
    if (isToday(date)) label = 'Today'
    else if (isYesterday(date)) label = 'Yesterday'
    else label = date.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: date.getFullYear() !== today.getFullYear() ? 'numeric' : undefined })

    if (label !== currentLabel) {
      groups.push({ type: 'label', label })
      currentLabel = label
    }
    groups.push({ type: 'session', session })
  }
  return groups
}

const formatRelativeTime = (dateStr) => {
  if (!dateStr) return ''
  const now = new Date()
  const date = new Date(dateStr)
  const diffMs = now - date
  const diffMins = Math.floor(diffMs / 60000)
  if (diffMins < 1) return 'just now'
  if (diffMins < 60) return `${diffMins}m ago`
  const diffHours = Math.floor(diffMins / 60)
  if (diffHours < 24) return `${diffHours}h ago`
  return date.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
}

// ─── Left panel: Session list ────────────────────────────────────────────────

const DebugSessionList = ({ sessions, selectedSession, loading, onSelect, onRefresh, onCollapse }) => {
  const [search, setSearch] = useState('')

  const items = sessions?.ok ? sessions.data?.items || [] : []
  const filtered = useMemo(() => {
    let result = search
      ? items.filter(s =>
          (s.title || '').toLowerCase().includes(search.toLowerCase()) ||
          s.id.includes(search)
        )
      : [...items]

    // Sort by most recent interaction first
    result.sort((a, b) => new Date(b.updated_at || b.created_at) - new Date(a.updated_at || a.created_at))
    return result
  }, [items, search])

  const grouped = useMemo(() => groupByDate(filtered), [filtered])

  return (
    <div className="bg-white overflow-hidden flex flex-col h-full">
      {/* Header */}
      <div className="px-3 py-3 border-b flex items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wider">Sessions</h2>
        <button
          onClick={onCollapse}
          className="p-1.5 rounded text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors"
          title="Collapse sidebar"
        >
          <PanelLeftClose className="w-3.5 h-3.5" />
        </button>
      </div>

      {/* Search */}
      <div className="px-3 py-2 border-b">
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search sessions..."
            className="w-full pl-8 pr-7 py-1.5 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-gray-400 focus:border-transparent"
          />
          {search && (
            <button
              onClick={() => setSearch('')}
              className="absolute right-2 top-1/2 -translate-y-1/2 p-0.5 hover:bg-gray-100 rounded"
            >
              <X className="w-3 h-3 text-gray-400" />
            </button>
          )}
        </div>
      </div>

      {/* Session items */}
      <div className="flex-1 overflow-y-auto">
        {!sessions && (
          <div className="flex items-center justify-center p-8 text-gray-400">
            <Loader2 className="w-5 h-5 animate-spin" />
          </div>
        )}
        {sessions && !sessions.ok && <p className="p-4 text-sm text-red-500">Error loading sessions</p>}
        {filtered.length === 0 && sessions?.ok && (
          <div className="text-center py-8 text-gray-400">
            <MessageSquare className="w-8 h-8 mx-auto mb-2 opacity-30" />
            <p className="text-sm">No sessions found</p>
          </div>
        )}
        {grouped.map((item, i) => {
          if (item.type === 'label') {
            return (
              <div key={`label-${item.label}`} className="px-4 pt-3 pb-1.5">
                <span className="text-xs font-medium text-gray-400 uppercase tracking-wide">{item.label}</span>
              </div>
            )
          }
          const session = item.session
          const isSelected = selectedSession === session.id
          return (
            <button
              key={session.id}
              onClick={() => onSelect(session.id)}
              className={`w-full text-left px-4 py-2.5 text-sm transition-colors ${
                isSelected
                  ? 'bg-gray-100 border-l-2 border-l-gray-800'
                  : 'hover:bg-gray-50 border-l-2 border-l-transparent'
              }`}
            >
              <div className="flex items-start gap-2">
                <MessageSquare className={`w-3.5 h-3.5 mt-0.5 flex-shrink-0 ${isSelected ? 'text-gray-700' : 'text-gray-400'}`} />
                <div className="flex-1 min-w-0">
                  <div className="font-medium truncate text-gray-800">
                    {session.title || 'Untitled'}
                  </div>
                  <div className="flex items-center gap-2 mt-1">
                    <StatusBadge status={session.status} />
                    <span className="text-xs text-gray-400">{formatRelativeTime(session.updated_at || session.created_at)}</span>
                    {session.token_usage?.total_tokens > 0 && (
                      <span className="text-xs text-gray-400">
                        {formatTokens(session.token_usage.total_tokens) || '0'} tok
                      </span>
                    )}
                  </div>
                </div>
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
  if (status === 'failed') return 'border-l-red-400'
  if (status === 'running') return 'border-l-gray-400'
  return 'border-l-gray-200'
}

const toolStatusColor = (status) => {
  if (status === 'failed') return 'text-red-600'
  return 'text-gray-500'
}

const AgentHeaderLine = ({ agentRun, selected, onSelect }) => {
  const config = getAgentConfig(agentRun.agent_id)
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
      } ${selected ? 'bg-gray-100' : 'hover:bg-gray-50'}`}
    >
      <span className="font-semibold uppercase text-xs tracking-wide text-gray-700">
        {config.name}
      </span>
      {tokens > 0 && (
        <span className="text-xs text-gray-400">{formatTokens(tokens)} tok</span>
      )}
      {duration && (
        <span className="text-xs text-gray-400">&middot; {duration}</span>
      )}
      {agentRun.status === 'running' && (
        <span className="ml-auto inline-block w-2 h-2 bg-gray-400 rounded-full animate-pulse" />
      )}
    </button>
  )
}

const ToolLine = ({ tc, selected, onSelect }) => {
  return (
    <button
      onClick={onSelect}
      className={`w-full text-left pl-8 pr-3 py-1 flex items-center gap-2 text-xs transition-colors ${
        selected ? 'bg-gray-100' : 'hover:bg-gray-50'
      }`}
    >
      <span className={`${toolStatusColor(tc.status)}`}>&rarr;</span>
      <span className={`font-medium ${toolStatusColor(tc.status)}`}>{formatToolName(tc.tool_name)}</span>
      {tc.question_id && <span className="bg-gray-100 text-gray-600 text-[10px] font-medium px-1.5 py-0.5 rounded">HITL</span>}
    </button>
  )
}

// ─── Detail pane (bottom of right panel) ─────────────────────────────────────

const darkCopyBtnClass = 'inline-flex items-center gap-1 px-2 py-0.5 text-xs rounded hover:bg-gray-700 transition-colors text-gray-400'

const ToolDetail = ({ tc, agentRun }) => {
  const config = getAgentConfig(agentRun.agent_id)

  return (
    <div className="space-y-3 text-xs">
      <div className="flex items-center gap-2">
        <span className="font-semibold text-gray-200">{formatToolName(tc.tool_name)}</span>
        <StatusBadge status={tc.status} />
        <span className="text-gray-500">({config.name})</span>
      </div>

      {/* Arguments */}
      {tc.arguments && (
        <div>
          <div className="flex items-center gap-2 mb-1">
            <span className="font-medium text-gray-400">Arguments</span>
            <CopyButton text={tc.arguments} label="Copy" showLabel className={darkCopyBtnClass} />
          </div>
          <pre className="bg-gray-800 p-2 rounded overflow-auto max-h-48 whitespace-pre-wrap break-all text-gray-300">
            {typeof tc.arguments === 'string' ? tc.arguments : JSON.stringify(tc.arguments, null, 2)}
          </pre>
        </div>
      )}

      {/* Result */}
      {tc.result && (
        <div>
          <div className="flex items-center gap-2 mb-1">
            <span className="font-medium text-gray-400">Result</span>
            <CopyButton text={tc.result} label="Copy" showLabel className={darkCopyBtnClass} />
          </div>
          <pre className="bg-gray-800 p-2 rounded overflow-auto max-h-48 whitespace-pre-wrap break-all text-gray-300">
            {typeof tc.result === 'string' ? tc.result : JSON.stringify(tc.result, null, 2)}
          </pre>
        </div>
      )}

      {/* Error */}
      {tc.error && (
        <div>
          <div className="flex items-center gap-2 mb-1">
            <span className="font-medium text-red-400">Error</span>
            <CopyButton text={tc.error} label="Copy" showLabel className={darkCopyBtnClass} />
          </div>
          <pre className="bg-red-900/30 p-2 rounded overflow-auto max-h-32 text-red-300">
            {tc.error}
          </pre>
        </div>
      )}

      {/* Approval */}
      {tc.approval && (
        <div>
          <div className="flex items-center gap-2 mb-1">
            <span className="font-medium text-gray-400">Approval</span>
            <CopyButton text={tc.approval} label="Copy" showLabel className={darkCopyBtnClass} />
          </div>
          <pre className="bg-gray-800 p-2 rounded overflow-auto max-h-32 mt-1 text-gray-300">
            {JSON.stringify(tc.approval, null, 2)}
          </pre>
        </div>
      )}
    </div>
  )
}

const AgentDetail = ({ agentRun }) => {
  const config = getAgentConfig(agentRun.agent_id)
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
        <span className="font-semibold text-gray-200">{config.name}</span>
        <StatusBadge status={agentRun.status} />
        {tokens > 0 && <span className="text-gray-500">{formatTokens(tokens)} tok</span>}
        {duration && <span className="text-gray-500">&middot; {duration}</span>}
      </div>

      {/* Planned prompt */}
      {agentRun.planned_prompt && (
        <div>
          <div className="flex items-center gap-2 mb-1">
            <span className="font-medium text-gray-400">Planned Prompt</span>
            <CopyButton text={agentRun.planned_prompt} label="Copy" showLabel className={darkCopyBtnClass} />
          </div>
          <pre className="bg-gray-800 p-2 rounded overflow-auto max-h-40 whitespace-pre-wrap break-all text-gray-300">
            {agentRun.planned_prompt}
          </pre>
        </div>
      )}

      {/* LLM calls table */}
      {llmCalls.length > 0 ? (
        <div>
          <span className="font-medium text-gray-400 mb-1 block">LLM Calls</span>
          <table className="w-full text-left">
            <thead>
              <tr className="text-gray-500 border-b border-gray-700">
                <th className="py-1 pr-3 font-medium">#</th>
                <th className="py-1 pr-3 font-medium">Model</th>
                <th className="py-1 pr-3 font-medium text-right">Tokens</th>
                <th className="py-1 pr-3 font-medium text-right">Duration</th>
                <th className="py-1 font-medium text-right">Tools</th>
              </tr>
            </thead>
            <tbody>
              {llmCalls.map((llm, i) => (
                <tr key={llm.id || i} className="border-b border-gray-800">
                  <td className="py-1 pr-3 text-gray-500 font-mono">{i + 1}</td>
                  <td className="py-1 pr-3 text-gray-300"><code>{llm.model}</code></td>
                  <td className="py-1 pr-3 text-right text-gray-400">
                    {formatTokens(llm.token_usage?.total_tokens)}
                  </td>
                  <td className="py-1 pr-3 text-right text-gray-400">
                    {formatDuration(llm.duration_ms) || '-'}
                  </td>
                  <td className="py-1 text-right text-gray-400">
                    {llm.tool_calls?.length || 0}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="text-gray-500 italic">No LLM calls yet</p>
      )}

      {/* Copy raw button */}
      <div>
        <CopyButton text={agentRun} label="Copy Raw JSON" showLabel className={darkCopyBtnClass} />
      </div>
    </div>
  )
}

const DetailPane = ({ selection, onClose }) => {
  if (!selection) return null

  return (
    <>
      {/* Backdrop */}
      <div className="fixed inset-0 bg-black/40 z-30" onClick={onClose} />
      {/* Floating panel */}
      <div className="fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 z-40 bg-gray-900 rounded-lg shadow-2xl border border-gray-700 flex flex-col"
        style={{ width: 'min(800px, 92vw)', maxHeight: '80vh' }}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-2.5 border-b border-gray-700 bg-gray-800 rounded-t-lg flex-shrink-0">
          <span className="text-sm font-medium text-gray-200">
            {selection.type === 'tool' ? formatToolName(selection.toolCall.tool_name) : getAgentConfig(selection.agentRun.agent_id).name}
          </span>
          <button
            onClick={onClose}
            className="p-1 rounded text-gray-400 hover:text-gray-200 hover:bg-gray-700 transition-colors"
            title="Close (Esc)"
          >
            <X className="w-4 h-4" />
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

// ─── Full JSON viewer modal ─────────────────────────────────────────────────

const JsonViewerModal = ({ data, title, onClose }) => {
  const [copied, setCopied] = useState(false)
  const jsonString = useMemo(() => JSON.stringify(data, null, 2), [data])

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(jsonString)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {}
  }

  return (
    <>
      <div className="fixed inset-0 bg-black/40 z-30" onClick={onClose} />
      <div
        className="fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 z-40 bg-gray-900 rounded-lg shadow-2xl border border-gray-700 flex flex-col"
        style={{ width: 'min(1100px, 95vw)', height: 'min(90vh, 860px)' }}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-2.5 border-b border-gray-700 bg-gray-800 rounded-t-lg flex-shrink-0">
          <div className="flex items-center gap-2">
            <Braces className="w-4 h-4 text-gray-400" />
            <span className="text-sm font-medium text-gray-200">{title || 'Session JSON'}</span>
            <span className="px-2 py-0.5 text-xs font-medium rounded bg-gray-700 text-gray-400">JSON</span>
          </div>
          <div className="flex items-center gap-1">
            <button
              onClick={handleCopy}
              className="flex items-center gap-1.5 px-2.5 py-1 text-xs rounded hover:bg-gray-700 transition-colors"
              title={copied ? 'Copied!' : 'Copy to clipboard'}
            >
              {copied ? (
                <>
                  <Check className="w-3.5 h-3.5 text-green-400" />
                  <span className="text-green-400">Copied!</span>
                </>
              ) : (
                <>
                  <Copy className="w-3.5 h-3.5 text-gray-400" />
                  <span className="text-gray-400">Copy</span>
                </>
              )}
            </button>
            <button
              onClick={() => downloadAsFile(data, title || 'session')}
              className="flex items-center gap-1.5 px-2.5 py-1 text-xs text-gray-400 rounded hover:bg-gray-700 transition-colors"
              title="Download JSON"
            >
              <Download className="w-3.5 h-3.5" />
              <span>Download</span>
            </button>
            <button
              onClick={onClose}
              className="p-1 ml-1 rounded text-gray-400 hover:text-gray-200 hover:bg-gray-700 transition-colors"
              title="Close (Esc)"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>
        {/* JSON content */}
        <div className="flex-1 overflow-auto p-4">
          <pre className="text-xs font-mono leading-5 text-gray-300 whitespace-pre">
            {jsonString}
          </pre>
        </div>
      </div>
    </>
  )
}

// ─── Right panel: Session detail ─────────────────────────────────────────────

const DebugSessionDetail = ({ sessionDetail, loading, onRefresh, selectedSession, answerText, setAnswerText, onSubmitAnswer, answerLoading }) => {
  const [selection, setSelection] = useState(null)
  const [showJson, setShowJson] = useState(false)

  // Close detail pane / JSON viewer on Esc
  useEffect(() => {
    const handleKeyDown = (e) => {
      if (e.key === 'Escape') {
        if (showJson) setShowJson(false)
        else setSelection(null)
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [showJson])

  // Clear selection and close JSON viewer when session changes
  useEffect(() => {
    setSelection(null)
    setShowJson(false)
  }, [selectedSession])

  const closeDetail = useCallback(() => setSelection(null), [])

  if (loading) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center text-gray-400 gap-3">
        <Loader2 className="w-6 h-6 animate-spin" />
        <span className="text-sm">Loading session...</span>
      </div>
    )
  }

  if (!sessionDetail || !sessionDetail.ok || !sessionDetail.data) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center text-gray-400 gap-2">
        <MessageSquare className="w-10 h-10 opacity-30" />
        <span className="text-sm">{sessionDetail?.error ? `Error: ${sessionDetail.error}` : 'Select a session to inspect'}</span>
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
      label: 'Refresh',
      icon: RefreshCw,
      onClick: (e) => { e.stopPropagation(); onRefresh() }
    },
    {
      label: 'Copy Summary',
      icon: Copy,
      onClick: async (e) => {
        e.stopPropagation()
        const text = JSON.stringify(generateTimelineSummary(timeline), null, 2)
        try { await navigator.clipboard.writeText(text) } catch {}
      }
    },
    {
      label: 'Copy JSON',
      icon: Copy,
      onClick: async (e) => {
        e.stopPropagation()
        const text = JSON.stringify(sessionDetail, null, 2)
        try { await navigator.clipboard.writeText(text) } catch {}
      }
    },
    {
      label: 'Download JSON',
      icon: Download,
      onClick: (e) => {
        e.stopPropagation()
        downloadAsFile(sessionDetail, 'session')
      }
    },
  ]

  const hasModalOpen = !!selection || showJson

  return (
    <div className="flex-1 bg-white overflow-hidden flex flex-col h-full">
      {/* Background content — hidden from Ctrl+F when a modal is open */}
      <div
        className="flex-1 flex flex-col overflow-hidden"
        style={hasModalOpen ? { visibility: 'hidden' } : undefined}
        inert={hasModalOpen ? '' : undefined}
      >
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
              <button
                onClick={() => setShowJson(true)}
                className="p-1.5 rounded text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors"
                title="View full JSON"
              >
                <Braces className="w-4 h-4" />
              </button>
              <OverflowMenu items={overflowItems} />
            </div>
          </div>
        </div>

        {/* Pending HITL question banner */}
        {pendingQuestion && (
          <div className="px-4 py-3 bg-amber-50/50 border-b border-amber-100 flex-shrink-0">
            <div className="flex items-center gap-2 text-sm mb-2">
              <PauseCircle className="w-3.5 h-3.5 text-amber-500" />
              <span className="font-medium text-gray-700">
                {getAgentConfig(pendingQuestion.agentId).name} is waiting for your answer
              </span>
            </div>
            <div className="p-2.5 bg-white rounded-lg border border-gray-200 mb-2.5 text-sm text-gray-800">
              {pendingQuestion.question}
            </div>
            <div className="flex gap-2">
              <input
                type="text"
                value={answerText}
                onChange={(e) => setAnswerText(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && onSubmitAnswer(pendingQuestion.questionId)}
                placeholder="Type your answer..."
                className="flex-1 px-3 py-1.5 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-gray-400 focus:border-transparent"
              />
              <button
                onClick={() => onSubmitAnswer(pendingQuestion.questionId)}
                disabled={answerLoading || !answerText.trim()}
                className="flex items-center gap-1.5 px-3 py-1.5 text-sm bg-gray-900 text-white rounded-lg hover:bg-gray-700 disabled:opacity-30 transition-colors"
              >
                {answerLoading ? (
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                ) : (
                  <Send className="w-3.5 h-3.5" />
                )}
                {answerLoading ? 'Sending...' : 'Answer'}
              </button>
            </div>
          </div>
        )}

        {/* Event log — flat, scrollable */}
        <div className="flex-1 overflow-y-auto bg-white">
          {eventItems.length === 0 && (
            <div className="flex flex-col items-center justify-center py-12 text-gray-400 gap-2">
              <MessageSquare className="w-8 h-8 opacity-30" />
              <p className="text-sm">No agent runs in this session</p>
            </div>
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
      </div>

      {/* Detail pane — appears when something is selected */}
      <DetailPane selection={selection} onClose={closeDetail} />

      {/* Full JSON viewer */}
      {showJson && (
        <JsonViewerModal
          data={sessionDetail.data}
          title={data.title || 'Session'}
          onClose={() => setShowJson(false)}
        />
      )}
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

  const fetchSessions = useCallback(async () => {
    setLoading(l => ({ ...l, sessions: true }))
    const result = await apiFetch('/api/sessions')
    setSessions(result)
    setLoading(l => ({ ...l, sessions: false }))
  }, [])

  const fetchSessionDetail = useCallback(async (sessionId) => {
    setSelectedSession(sessionId)
    setSessionDetail(null)
    setLoading(l => ({ ...l, detail: true }))
    const result = await apiFetch(`/api/sessions/${sessionId}`)
    setSessionDetail(result)
    setLoading(l => ({ ...l, detail: false }))
  }, [])

  // Silent refresh (no loading state) for polling
  const silentRefreshDetail = useCallback(async () => {
    if (!selectedSession) return
    const result = await apiFetch(`/api/sessions/${selectedSession}`)
    setSessionDetail(result)
  }, [selectedSession])

  // Initial load
  useEffect(() => {
    fetchSessions()
  }, [fetchSessions])

  // Auto-select most recent session on initial load
  const autoSelectedRef = useRef(false)
  useEffect(() => {
    if (!autoSelectedRef.current && sessions?.ok) {
      const items = sessions.data?.items || []
      if (items.length > 0) {
        const sorted = [...items].sort((a, b) =>
          new Date(b.updated_at || b.created_at) - new Date(a.updated_at || a.created_at)
        )
        autoSelectedRef.current = true
        fetchSessionDetail(sorted[0].id)
      }
    }
  }, [sessions, fetchSessionDetail])

  // Auto-poll session list every 15s
  useEffect(() => {
    const interval = setInterval(async () => {
      const result = await apiFetch('/api/sessions')
      setSessions(result)
    }, 15000)
    return () => clearInterval(interval)
  }, [])

  // Auto-poll active session detail every 5s
  useEffect(() => {
    const status = sessionDetail?.data?.status
    const isActive = status && ['running', 'active', 'paused_hitl', 'paused_tool', 'waiting_approval', 'waiting_answer'].includes(status)
    if (!isActive) return
    const interval = setInterval(silentRefreshDetail, 5000)
    return () => clearInterval(interval)
  }, [sessionDetail?.data?.status, silentRefreshDetail])

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

  const [sidebarOpen, setSidebarOpen] = useState(() =>
    localStorage.getItem('druppie-debug-sidebar') !== 'false'
  )

  const toggleSidebar = () => {
    setSidebarOpen((prev) => {
      localStorage.setItem('druppie-debug-sidebar', String(!prev))
      return !prev
    })
  }

  return (
    <div className="flex h-full flex-1">
      {/* Collapsible left sidebar */}
      <div
        className={`flex-shrink-0 bg-white border-r overflow-hidden transition-all duration-200 ${
          sidebarOpen ? 'w-72' : 'w-0'
        }`}
      >
        <div className="w-72 h-full">
          <DebugSessionList
            sessions={sessions}
            selectedSession={selectedSession}
            loading={loading.sessions}
            onSelect={fetchSessionDetail}
            onRefresh={fetchSessions}
            onCollapse={toggleSidebar}
          />
        </div>
      </div>

      {/* Right panel */}
      <div className="flex-1 overflow-hidden relative">
        {!sidebarOpen && (
          <button
            onClick={toggleSidebar}
            className="absolute top-3 left-3 z-10 p-1.5 rounded-lg text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors"
            title="Expand sidebar"
          >
            <PanelLeftOpen className="w-4 h-4" />
          </button>
        )}
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
    </div>
  )
}
