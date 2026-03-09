/**
 * DebugEventLog - Inspect mode for session detail
 *
 * Split layout: compact outline on the left, rich detail on the right.
 * Left panel shows agents with their tool call summaries (scannable).
 * Clicking an agent or tool shows full detail on the right — planned
 * prompts, LLM responses, tool args/results all visible without extra clicks.
 */

import { useState, useEffect, useMemo, useCallback, useRef } from 'react'
import {
  X,
  Copy,
  Download,
  Braces,
  Check,
  Clock,
  Terminal,
  MessageSquare,
  Bot,
  Zap,
  Hash,
  RotateCcw,
} from 'lucide-react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { getAgentConfig, getAgentMessageColors, formatToolName } from '../../utils/agentConfig'
import { formatDuration, formatTokens } from '../../utils/tokenUtils'
import { retryFromRun, getSandboxEvents } from '../../services/api'
import CopyButton from '../shared/CopyButton'
import ContainerLogsModal from '../shared/ContainerLogsModal'

// ─── Utilities ───────────────────────────────────────────────────────────────

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
  } catch (err) {
    console.error('Download failed:', err)
  }
}

const parseArgs = (args) => {
  if (!args) return null
  if (typeof args === 'object') return args
  try { return JSON.parse(args) } catch { return null }
}

const formatValue = (val) =>
  typeof val === 'string' ? val : JSON.stringify(val, null, 2)

const getToolContextHint = (tc) => {
  const args = parseArgs(tc.arguments)
  if (!args) return null
  if (args.path || args.file_path) return args.path || args.file_path
  if (args.command) {
    const cmd = String(args.command)
    return cmd.length > 60 ? cmd.slice(0, 57) + '...' : cmd
  }
  if (args.commit_message) {
    const msg = args.commit_message
    return msg.length > 60 ? msg.slice(0, 57) + '...' : msg
  }
  if (args.question) {
    const q = args.question
    return q.length > 60 ? q.slice(0, 57) + '...' : q
  }
  if (args.files && typeof args.files === 'object') {
    const paths = Object.keys(args.files)
    return `${paths.length} file${paths.length !== 1 ? 's' : ''}`
  }
  return null
}

const extractAllToolCalls = (agentRun) =>
  (agentRun.llm_calls || []).flatMap(llm =>
    (llm.tool_calls || []).map(tc => ({
      tool_name: tc.tool_name,
      status: tc.status,
      arguments: parseArgs(tc.arguments),
      result: tc.result || undefined,
      error: tc.error || undefined,
    }))
  )

// ─── Small shared components ─────────────────────────────────────────────────

const StatusBadge = ({ status }) => {
  let color = 'bg-gray-100 text-gray-600'
  if (status === 'failed') color = 'bg-red-50 text-red-700'
  else if (status === 'completed') color = 'bg-green-50 text-green-700'
  else if (status === 'running' || status === 'active') color = 'bg-blue-50 text-blue-700'
  return (
    <span className={`px-1.5 py-0.5 rounded text-xs ${color}`}>
      {status}
    </span>
  )
}

const copyBtnClass = 'inline-flex items-center gap-1 px-2 py-0.5 text-xs rounded hover:bg-gray-100 transition-colors text-gray-500'

// ─── Inspect Summary ─────────────────────────────────────────────────────────

const InspectSummary = ({ agentRuns, data }) => {
  const stats = useMemo(() => {
    let llmCallCount = 0
    let toolCallCount = 0
    const agentTokens = {}
    agentRuns.forEach((run) => {
      const config = getAgentConfig(run.agent_id)
      const tokens = run.token_usage?.total_tokens || 0
      if (tokens > 0) agentTokens[config.name] = (agentTokens[config.name] || 0) + tokens
      run.llm_calls?.forEach((llm) => {
        llmCallCount++
        toolCallCount += llm.tool_calls?.length || 0
      })
    })
    return { agentCount: agentRuns.length, llmCallCount, toolCallCount, totalTokens: data.token_usage?.total_tokens || 0, agentTokens }
  }, [agentRuns, data])

  return (
    <div className="border-b bg-gray-50 flex-shrink-0 px-3 py-1.5 flex flex-wrap items-center gap-3 text-xs text-gray-500">
      <span className="flex items-center gap-1"><Hash className="w-3 h-3" />{stats.agentCount} agents</span>
      <span className="flex items-center gap-1"><Bot className="w-3 h-3" />{stats.llmCallCount} LLM calls</span>
      <span className="flex items-center gap-1"><Zap className="w-3 h-3" />{stats.toolCallCount} tools</span>
      {stats.totalTokens > 0 && <span>{formatTokens(stats.totalTokens)} tokens</span>}
      {Object.keys(stats.agentTokens).length > 0 && (
        <>
          <span className="text-gray-300">|</span>
          {Object.entries(stats.agentTokens).sort((a, b) => b[1] - a[1]).map(([agent, tokens]) => (
            <span key={agent} className="inline-flex items-center gap-1">
              <span className="font-medium text-gray-600">{agent}</span>
              <span className="text-gray-400">{formatTokens(tokens)}</span>
            </span>
          ))}
        </>
      )}
    </div>
  )
}

// ─── LEFT PANEL: Outline ────────────────────────────────────────────────────

const OutlineAgentHeader = ({ agentRun, selected, onClick }) => {
  const config = getAgentConfig(agentRun.agent_id)
  const AgentIcon = config.icon
  const colors = getAgentMessageColors(config.color)
  const tokens = agentRun.token_usage?.total_tokens || 0

  const duration = useMemo(() => {
    if (agentRun.started_at && agentRun.completed_at) return formatDuration(new Date(agentRun.completed_at) - new Date(agentRun.started_at))
    const total = agentRun.llm_calls?.reduce((sum, llm) => sum + (llm.duration_ms || 0), 0) || 0
    return total > 0 ? formatDuration(total) : null
  }, [agentRun])

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onClick}
      onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onClick() } }}
      className={`w-full text-left px-3 py-2 flex items-center gap-2 transition-colors border-l-2 cursor-pointer select-text ${
        selected ? `${colors.bg} border-l-current ${colors.accent}` : 'border-l-transparent hover:bg-gray-50'
      }`}
    >
      <AgentIcon className={`w-3.5 h-3.5 flex-shrink-0 ${colors.accent}`} />
      <span className={`text-xs font-semibold truncate ${selected ? colors.accent : 'text-gray-700'}`}>
        {config.name}
      </span>
      <span className="ml-auto flex items-center gap-1.5 flex-shrink-0">
        {tokens > 0 && <span className="text-[10px] text-gray-400">{formatTokens(tokens)}</span>}
        {duration && <span className="text-[10px] text-gray-400">{duration}</span>}
        {agentRun.status === 'running' && <span className="w-1.5 h-1.5 bg-blue-400 rounded-full animate-pulse" />}
        {agentRun.status === 'failed' && <span className="w-1.5 h-1.5 bg-red-400 rounded-full" />}
      </span>
    </div>
  )
}

const OutlineToolLine = ({ tc, selected, onClick }) => {
  const StatusIcon = tc.status === 'completed' ? Check : tc.status === 'failed' ? X : Clock
  const statusColor = tc.status === 'completed' ? 'text-green-500' : tc.status === 'failed' ? 'text-red-500' : 'text-amber-500'
  const hint = getToolContextHint(tc)

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onClick}
      onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onClick() } }}
      className={`w-full text-left pl-9 pr-3 py-1 flex items-center gap-1.5 text-[11px] transition-colors cursor-pointer select-text ${
        selected ? 'bg-blue-50 text-blue-700' : 'hover:bg-gray-50 text-gray-500'
      }`}
    >
      <StatusIcon className={`w-3 h-3 flex-shrink-0 ${statusColor}`} />
      <span className={`font-medium truncate ${selected ? 'text-blue-700' : 'text-gray-600'}`}>
        {formatToolName(tc.tool_name)}
      </span>
      {tc.question_id && <span className="bg-amber-50 text-amber-600 text-[9px] font-medium px-1 py-0.5 rounded flex-shrink-0">HITL</span>}
      {hint && <span className="text-gray-400 font-mono truncate ml-auto text-[10px]" title={hint}>{hint}</span>}
    </div>
  )
}

// ─── Retry Confirmation Dialog ──────────────────────────────────────────────

const RetryConfirmDialog = ({ agentName, plannedPrompt, onConfirm, onCancel, isPending }) => {
  const [editedPrompt, setEditedPrompt] = useState(plannedPrompt || '')

  return (
    <>
      <div className="fixed inset-0 bg-black/30 z-30" onClick={onCancel} />
      <div className={`fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 z-40 bg-white rounded-lg shadow-2xl border border-gray-200 p-5 ${plannedPrompt ? 'w-[32rem]' : 'w-96'}`}>
        <div className="flex items-center gap-2 mb-3">
          <RotateCcw className="w-5 h-5 text-amber-600" />
          <h3 className="text-sm font-semibold text-gray-900">Retry from here</h3>
        </div>
        <div className="text-sm text-gray-600 space-y-2 mb-4">
          <p>This will revert <strong>{agentName}</strong> and all subsequent agents.</p>
          <p>Git commits will be reset and force-pushed.</p>
        </div>
        {plannedPrompt && (
          <div className="mb-4">
            <label className="block text-xs font-medium text-gray-500 mb-1">Planned Prompt</label>
            <textarea
              value={editedPrompt}
              onChange={(e) => setEditedPrompt(e.target.value)}
              disabled={isPending}
              rows={6}
              className="w-full text-xs font-mono bg-gray-50 border border-gray-200 rounded p-2.5 resize-y focus:outline-none focus:ring-1 focus:ring-amber-400 focus:border-amber-400 disabled:opacity-50"
            />
          </div>
        )}
        <div className="flex justify-end gap-2">
          <button
            onClick={onCancel}
            disabled={isPending}
            className="px-3 py-1.5 text-sm text-gray-600 rounded-md hover:bg-gray-100 transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={() => onConfirm(plannedPrompt ? editedPrompt : null)}
            disabled={isPending}
            className="px-3 py-1.5 text-sm font-medium bg-amber-600 text-white rounded-md hover:bg-amber-700 disabled:opacity-50 transition-colors flex items-center gap-1.5"
          >
            {isPending ? (
              <span className="w-3.5 h-3.5 border-2 border-white border-t-transparent rounded-full animate-spin" />
            ) : (
              <RotateCcw className="w-3.5 h-3.5" />
            )}
            Retry from here
          </button>
        </div>
      </div>
    </>
  )
}

// ─── RIGHT PANEL: Agent Detail ──────────────────────────────────────────────

const AgentDetailPanel = ({ agentRun, sessionId, sessionStatus }) => {
  const config = getAgentConfig(agentRun.agent_id)
  const AgentIcon = config.icon
  const colors = getAgentMessageColors(config.color)
  const tokens = agentRun.token_usage?.total_tokens || 0
  const llmCalls = agentRun.llm_calls || []
  const [showRetryConfirm, setShowRetryConfirm] = useState(false)
  const queryClient = useQueryClient()

  const retryMutation = useMutation({
    mutationFn: (editedPrompt) => retryFromRun(sessionId, agentRun.id, editedPrompt),
    onSuccess: () => {
      setShowRetryConfirm(false)
      queryClient.invalidateQueries({ queryKey: ['session', sessionId] })
      queryClient.invalidateQueries({ queryKey: ['sessions'] })
    },
  })

  const canRetry = sessionStatus && sessionStatus !== 'active'

  const duration = useMemo(() => {
    if (agentRun.started_at && agentRun.completed_at) return formatDuration(new Date(agentRun.completed_at) - new Date(agentRun.started_at))
    const total = llmCalls.reduce((sum, llm) => sum + (llm.duration_ms || 0), 0)
    return total > 0 ? formatDuration(total) : null
  }, [agentRun, llmCalls])

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className={`flex items-center gap-2.5 px-4 py-2.5 -mx-4 -mt-3 ${colors.bg} border-b ${colors.border}`}>
        <AgentIcon className={`w-4 h-4 ${colors.accent}`} />
        <span className={`text-sm font-semibold ${colors.accent}`}>{config.name}</span>
        <StatusBadge status={agentRun.status} />
        {tokens > 0 && <span className="text-xs text-gray-500">{formatTokens(tokens)} tok</span>}
        {duration && <span className="text-xs text-gray-500">&middot; {duration}</span>}
        {agentRun.status === 'running' && <span className="w-2 h-2 bg-blue-400 rounded-full animate-pulse" />}
        <span className="ml-auto flex items-center gap-1">
          {canRetry && (
            <button
              onClick={() => setShowRetryConfirm(true)}
              className="inline-flex items-center gap-1 px-2 py-0.5 text-xs rounded hover:bg-amber-100 transition-colors text-amber-700"
              title="Retry from this agent"
            >
              <RotateCcw className="w-3 h-3" />
              <span>Retry</span>
            </button>
          )}
          <CopyButton text={extractAllToolCalls(agentRun)} label="Copy Tools" showLabel className={copyBtnClass} />
          <CopyButton text={agentRun} label="Copy JSON" showLabel className={copyBtnClass} />
        </span>
      </div>

      {showRetryConfirm && (
        <RetryConfirmDialog
          agentName={config.name}
          plannedPrompt={agentRun.planned_prompt}
          onConfirm={(editedPrompt) => retryMutation.mutate(editedPrompt)}
          onCancel={() => setShowRetryConfirm(false)}
          isPending={retryMutation.isPending}
        />
      )}

      {retryMutation.isError && (
        <div className="bg-red-50 border border-red-200 rounded p-2 text-xs text-red-700">
          Retry failed: {retryMutation.error.message}
        </div>
      )}

      {/* Planned prompt */}
      {agentRun.planned_prompt && (
        <div>
          <div className="flex items-center gap-2 mb-1">
            <span className="text-xs font-medium text-gray-500">Planned Prompt</span>
            <CopyButton text={agentRun.planned_prompt} label="Copy" className={copyBtnClass} />
          </div>
          <pre className="bg-gray-50 border border-gray-200 p-2.5 rounded overflow-auto max-h-40 whitespace-pre-wrap break-words text-xs text-gray-700 leading-relaxed">
            {agentRun.planned_prompt}
          </pre>
        </div>
      )}

      {/* LLM calls with responses + tool details inline */}
      {llmCalls.map((llm, i) => (
        <LlmCallSection key={llm.id || i} llm={llm} index={i} isOnly={llmCalls.length === 1} />
      ))}

      {llmCalls.length === 0 && agentRun.status !== 'pending' && (
        <p className="text-xs text-gray-400 italic">No LLM calls</p>
      )}
    </div>
  )
}

const LlmCallSection = ({ llm, index, isOnly }) => {
  const tokens = llm.token_usage?.total_tokens || 0
  const dur = formatDuration(llm.duration_ms)
  const toolCount = llm.tool_calls?.length || 0

  return (
    <div className={!isOnly ? 'border-t border-gray-100 pt-3' : undefined}>
      {/* LLM call header */}
      {!isOnly && (
        <div className="flex items-center gap-2 text-xs text-gray-500 mb-2">
          <span className="font-mono text-gray-400">LLM #{index + 1}</span>
          <code className="text-gray-600">{llm.model}</code>
          {tokens > 0 && <span>{formatTokens(tokens)} tok</span>}
          {dur && <span>&middot; {dur}</span>}
        </div>
      )}

      {/* Response — always visible */}
      {llm.response_content && (
        <div className="mb-3">
          <div className="flex items-center gap-2 mb-1">
            <span className="text-xs font-medium text-gray-500">Response</span>
            <CopyButton text={llm.response_content} label="Copy" className={copyBtnClass} />
          </div>
          <pre className="bg-blue-50/40 border border-blue-100 p-2.5 rounded overflow-auto max-h-64 whitespace-pre-wrap text-xs text-gray-700 leading-relaxed">
            {llm.response_content}
          </pre>
        </div>
      )}

      {/* Tool calls — all shown with full details */}
      {toolCount > 0 && (
        <div className="space-y-3">
          <div className="flex items-center gap-2 text-xs text-gray-400">
            <span>{toolCount} tool call{toolCount !== 1 ? 's' : ''}</span>
            <CopyButton text={llm.tool_calls} label="Copy all" showLabel className={copyBtnClass} />
          </div>
          {llm.tool_calls.map((tc, ti) => (
            <ToolCallDetail key={tc.id || ti} tc={tc} />
          ))}
        </div>
      )}

      {/* Raw/advanced data */}
      {(llm.messages?.length > 0 || llm.tools_provided?.length > 0 || llm.response_tool_calls?.length > 0) && (
        <div className="mt-3 flex flex-wrap gap-1.5 text-xs">
          {llm.messages?.length > 0 && (
            <details>
              <summary className="cursor-pointer text-gray-400 hover:text-gray-600 px-1.5 py-0.5 rounded hover:bg-gray-100 transition-colors select-none">
                Messages ({llm.messages.length})
              </summary>
              <div className="mt-1 space-y-2 ml-1">
                {llm.messages.map((msg, idx) => (
                  <div key={idx} className="border-l-2 border-gray-300 pl-2">
                    <span className="font-medium text-gray-500">{msg.role}</span>
                    <pre className="bg-gray-50 border border-gray-200 p-2 mt-0.5 rounded overflow-auto max-h-32 whitespace-pre-wrap text-gray-700">
                      {typeof msg.content === 'string' ? msg.content : JSON.stringify(msg.content, null, 2)}
                    </pre>
                  </div>
                ))}
              </div>
            </details>
          )}
          {llm.tools_provided?.length > 0 && (
            <details>
              <summary className="cursor-pointer text-gray-400 hover:text-gray-600 px-1.5 py-0.5 rounded hover:bg-gray-100 transition-colors select-none">
                Tools provided ({llm.tools_provided.length})
              </summary>
              <pre className="mt-1 bg-gray-50 border border-gray-200 p-2 rounded overflow-auto max-h-40 text-gray-700">
                {JSON.stringify(llm.tools_provided, null, 2)}
              </pre>
            </details>
          )}
          {llm.response_tool_calls?.length > 0 && (
            <details>
              <summary className="cursor-pointer text-gray-400 hover:text-gray-600 px-1.5 py-0.5 rounded hover:bg-gray-100 transition-colors select-none">
                Raw tool calls ({llm.response_tool_calls.length})
              </summary>
              <pre className="mt-1 bg-gray-50 border border-gray-200 p-2 rounded overflow-auto max-h-40 text-gray-700">
                {JSON.stringify(llm.response_tool_calls, null, 2)}
              </pre>
            </details>
          )}
          {llm.id && (
            <span className="text-[10px] text-gray-300 px-1.5 py-0.5">
              ID: {llm.id}{llm.provider ? ` · ${llm.provider}` : ''}
            </span>
          )}
        </div>
      )}
    </div>
  )
}

// ─── Sandbox Events Copy Button ─────────────────────────────────────────────

const CopySandboxEventsButton = ({ sandboxSessionId }) => {
  const [status, setStatus] = useState('idle') // idle | loading | copied | error

  const handleCopy = async () => {
    setStatus('loading')
    try {
      const data = await getSandboxEvents(sandboxSessionId)
      await navigator.clipboard.writeText(JSON.stringify(data, null, 2))
      setStatus('copied')
      setTimeout(() => setStatus('idle'), 2000)
    } catch (e) {
      setStatus('error')
      setTimeout(() => setStatus('idle'), 2000)
    }
  }

  return (
    <button
      onClick={handleCopy}
      disabled={status === 'loading'}
      className={`flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded transition-colors ${
        status === 'copied' ? 'bg-green-100 text-green-700' :
        status === 'error' ? 'bg-red-100 text-red-700' :
        'bg-blue-50 text-blue-600 hover:bg-blue-100'
      }`}
    >
      {status === 'loading' ? <Clock className="w-3 h-3 animate-spin" /> :
       status === 'copied' ? <Check className="w-3 h-3" /> :
       <Copy className="w-3 h-3" />}
      {status === 'copied' ? 'Copied!' : status === 'error' ? 'Failed' : 'Copy Sandbox Events'}
    </button>
  )
}

/** Extract sandbox_session_id from a tool call result */
const getSandboxSessionId = (tc) => {
  if (tc.tool_name !== 'execute_coding_task') return null
  let result = tc.result
  if (typeof result === 'string') {
    try { result = JSON.parse(result) } catch { return null }
  }
  return result?.sandbox_session_id || null
}

// ─── RIGHT PANEL: Tool Detail ───────────────────────────────────────────────

const ToolCallDetail = ({ tc }) => {
  const statusColor = tc.status === 'completed' ? 'text-green-600' : tc.status === 'failed' ? 'text-red-600' : 'text-amber-600'
  const StatusIcon = tc.status === 'completed' ? Check : tc.status === 'failed' ? X : Clock
  const sandboxId = getSandboxSessionId(tc)

  return (
    <div className="border border-gray-200 rounded-lg overflow-hidden">
      {/* Tool header */}
      <div className="flex items-center gap-2 px-3 py-1.5 bg-gray-50 border-b border-gray-200 text-xs">
        <StatusIcon className={`w-3.5 h-3.5 ${statusColor}`} />
        <span className="font-medium text-gray-700">{formatToolName(tc.tool_name)}</span>
        <StatusBadge status={tc.status} />
        {tc.question_id && <span className="bg-amber-50 text-amber-700 text-[10px] font-medium px-1.5 py-0.5 rounded">HITL</span>}
        {sandboxId && <CopySandboxEventsButton sandboxSessionId={sandboxId} />}
        <CopyButton text={tc} label="Copy" className={`ml-auto ${copyBtnClass}`} />
      </div>

      {/* Tool body — all visible */}
      <div className="px-3 py-2 space-y-2 text-xs">
        {tc.arguments && (
          <div>
            <div className="flex items-center gap-2">
              <span className="font-medium text-gray-400">Arguments</span>
              <CopyButton text={tc.arguments} label="Copy" className={copyBtnClass} />
            </div>
            <pre className="mt-0.5 bg-gray-50 border border-gray-200 p-2 rounded overflow-auto max-h-48 whitespace-pre-wrap break-all text-gray-700">
              {formatValue(tc.arguments)}
            </pre>
          </div>
        )}

        {tc.result && (
          <div>
            <div className="flex items-center gap-2">
              <span className="font-medium text-gray-400">Result</span>
              <CopyButton text={tc.result} label="Copy" className={copyBtnClass} />
            </div>
            <pre className="mt-0.5 bg-gray-50 border border-gray-200 p-2 rounded overflow-auto max-h-48 whitespace-pre-wrap break-all text-gray-700">
              {formatValue(tc.result)}
            </pre>
          </div>
        )}

        {tc.error && (
          <div>
            <div className="flex items-center gap-2">
              <span className="font-medium text-red-600">Error</span>
              <CopyButton text={tc.error} label="Copy" className={copyBtnClass} />
            </div>
            <pre className="mt-0.5 bg-red-50 border border-red-200 p-2 rounded overflow-auto max-h-32 whitespace-pre-wrap text-red-700">
              {tc.error}
            </pre>
          </div>
        )}

        {tc.approval && (
          <div>
            <span className="font-medium text-gray-400">Approval</span>
            <pre className="mt-0.5 bg-gray-50 border border-gray-200 p-2 rounded overflow-auto max-h-24 whitespace-pre-wrap text-gray-700">
              {JSON.stringify(tc.approval, null, 2)}
            </pre>
          </div>
        )}

        {tc.normalizations?.length > 0 && (
          <div>
            <span className="font-medium text-amber-600">Normalizations ({tc.normalizations.length})</span>
            <div className="mt-0.5 space-y-1">
              {tc.normalizations.map((norm, nIdx) => (
                <div key={nIdx} className="bg-amber-50 p-2 rounded border border-amber-200">
                  <span className="font-mono text-amber-800">{norm.field_name}: </span>
                  <code className="text-red-600">{norm.original_value}</code>
                  <span className="text-gray-400"> → </span>
                  <code className="text-green-700">{norm.normalized_value}</code>
                </div>
              ))}
            </div>
          </div>
        )}

        {!tc.arguments && !tc.result && !tc.error && (
          <span className="text-gray-400 italic">No data</span>
        )}
      </div>
    </div>
  )
}

// ─── Standalone Tool Detail Panel (when a tool is selected directly) ────────

const ToolDetailPanel = ({ tc, agentRun }) => {
  const config = getAgentConfig(agentRun.agent_id)
  const sandboxId = getSandboxSessionId(tc)

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 text-xs text-gray-400 -mt-1">
        <span>{config.name}</span>
        <span>&middot;</span>
        <span className="font-medium text-gray-700">{formatToolName(tc.tool_name)}</span>
        <StatusBadge status={tc.status} />
        {tc.question_id && <span className="bg-amber-50 text-amber-700 text-[10px] font-medium px-1.5 py-0.5 rounded">HITL</span>}
        {sandboxId && <CopySandboxEventsButton sandboxSessionId={sandboxId} />}
        <CopyButton text={tc} label="Copy JSON" showLabel className={`ml-auto ${copyBtnClass}`} />
      </div>

      {tc.arguments && (
        <div>
          <div className="flex items-center gap-2 mb-1">
            <span className="text-xs font-medium text-gray-500">Arguments</span>
            <CopyButton text={tc.arguments} label="Copy" className={copyBtnClass} />
          </div>
          <pre className="bg-gray-50 border border-gray-200 p-2.5 rounded overflow-auto max-h-72 whitespace-pre-wrap break-all text-xs text-gray-700">
            {formatValue(tc.arguments)}
          </pre>
        </div>
      )}

      {tc.result && (
        <div>
          <div className="flex items-center gap-2 mb-1">
            <span className="text-xs font-medium text-gray-500">Result</span>
            <CopyButton text={tc.result} label="Copy" className={copyBtnClass} />
          </div>
          <pre className="bg-gray-50 border border-gray-200 p-2.5 rounded overflow-auto max-h-72 whitespace-pre-wrap break-all text-xs text-gray-700">
            {formatValue(tc.result)}
          </pre>
        </div>
      )}

      {tc.error && (
        <div>
          <div className="flex items-center gap-2 mb-1">
            <span className="text-xs font-medium text-red-600">Error</span>
            <CopyButton text={tc.error} label="Copy" className={copyBtnClass} />
          </div>
          <pre className="bg-red-50 border border-red-200 p-2.5 rounded overflow-auto max-h-48 whitespace-pre-wrap text-xs text-red-700">
            {tc.error}
          </pre>
        </div>
      )}

      {tc.approval && (
        <div>
          <div className="flex items-center gap-2 mb-1">
            <span className="text-xs font-medium text-gray-500">Approval</span>
          </div>
          <pre className="bg-gray-50 border border-gray-200 p-2.5 rounded overflow-auto max-h-32 whitespace-pre-wrap text-xs text-gray-700">
            {JSON.stringify(tc.approval, null, 2)}
          </pre>
        </div>
      )}

      {tc.normalizations?.length > 0 && (
        <div>
          <span className="text-xs font-medium text-amber-600">Normalizations ({tc.normalizations.length})</span>
          <div className="mt-1 space-y-1">
            {tc.normalizations.map((norm, nIdx) => (
              <div key={nIdx} className="bg-amber-50 p-2 rounded border border-amber-200 text-xs">
                <span className="font-mono text-amber-800">{norm.field_name}: </span>
                <code className="text-red-600">{norm.original_value}</code>
                <span className="text-gray-400"> → </span>
                <code className="text-green-700">{norm.normalized_value}</code>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

// ─── JSON viewer modal ──────────────────────────────────────────────────────

const JsonViewerModal = ({ data, title, onClose }) => {
  const [copied, setCopied] = useState(false)
  const jsonString = useMemo(() => JSON.stringify(data, null, 2), [data])
  const handleCopy = async () => {
    try { await navigator.clipboard.writeText(jsonString); setCopied(true); setTimeout(() => setCopied(false), 2000) } catch {}
  }
  return (
    <>
      <div className="fixed inset-0 bg-black/30 z-30" onClick={onClose} />
      <div className="fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 z-40 bg-white rounded-lg shadow-2xl border border-gray-200 flex flex-col" style={{ width: 'min(1100px, 95vw)', height: 'min(90vh, 860px)' }}>
        <div className="flex items-center justify-between px-4 py-2.5 border-b border-gray-200 bg-gray-50 rounded-t-lg flex-shrink-0">
          <div className="flex items-center gap-2">
            <Braces className="w-4 h-4 text-gray-500" />
            <span className="text-sm font-medium text-gray-700">{title || 'Session JSON'}</span>
          </div>
          <div className="flex items-center gap-1">
            <button onClick={handleCopy} className="flex items-center gap-1.5 px-2.5 py-1 text-xs rounded hover:bg-gray-100 transition-colors">
              {copied ? <><Check className="w-3.5 h-3.5 text-green-600" /><span className="text-green-600">Copied!</span></> : <><Copy className="w-3.5 h-3.5 text-gray-500" /><span className="text-gray-500">Copy</span></>}
            </button>
            <button onClick={() => downloadAsFile(data, title || 'session')} className="flex items-center gap-1.5 px-2.5 py-1 text-xs text-gray-500 rounded hover:bg-gray-100 transition-colors"><Download className="w-3.5 h-3.5" /><span>Download</span></button>
            <button onClick={onClose} className="p-1 ml-1 rounded text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors" title="Close (Esc)"><X className="w-4 h-4" /></button>
          </div>
        </div>
        <div className="flex-1 overflow-auto p-4">
          <pre className="text-xs font-mono leading-5 text-gray-700 whitespace-pre">{jsonString}</pre>
        </div>
      </div>
    </>
  )
}

// ─── Main component ──────────────────────────────────────────────────────────

const DebugEventLog = ({ data, sessionId, sessionStatus }) => {
  const [selection, setSelection] = useState(null) // { type: 'agent'|'tool', agentRun, toolCall? }
  const [showJson, setShowJson] = useState(false)
  const [showLogs, setShowLogs] = useState(false)
  const detailRef = useRef(null)
  const [leftWidth, setLeftWidth] = useState(288)
  const isDragging = useRef(false)
  const dragStartX = useRef(0)
  const dragStartWidth = useRef(0)

  const timeline = data?.timeline || []
  const agentRuns = useMemo(() =>
    timeline.filter(e => e.type === 'agent_run' && e.agent_run).map(e => e.agent_run),
    [timeline]
  )

  // Auto-select first agent when data loads or session changes
  useEffect(() => {
    setSelection(null)
    setShowJson(false)
    setShowLogs(false)
  }, [sessionId])

  useEffect(() => {
    if (!selection && agentRuns.length > 0) {
      setSelection({ type: 'agent', agentRun: agentRuns[0] })
    }
  }, [agentRuns, selection])

  // Scroll detail panel to top on selection change
  useEffect(() => {
    if (detailRef.current) detailRef.current.scrollTop = 0
  }, [selection])

  useEffect(() => {
    const handleKeyDown = (e) => {
      if (e.key === 'Escape') {
        if (showLogs) setShowLogs(false)
        else if (showJson) setShowJson(false)
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [showJson, showLogs])

  const handleDragStart = useCallback((e) => {
    isDragging.current = true
    dragStartX.current = e.clientX
    dragStartWidth.current = leftWidth
    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'
  }, [leftWidth])

  useEffect(() => {
    const handleMouseMove = (e) => {
      if (!isDragging.current) return
      const delta = e.clientX - dragStartX.current
      const newWidth = Math.min(Math.max(dragStartWidth.current + delta, 200), 600)
      setLeftWidth(newWidth)
    }
    const handleMouseUp = () => {
      if (isDragging.current) {
        isDragging.current = false
        document.body.style.cursor = ''
        document.body.style.userSelect = ''
      }
    }
    window.addEventListener('mousemove', handleMouseMove)
    window.addEventListener('mouseup', handleMouseUp)
    return () => {
      window.removeEventListener('mousemove', handleMouseMove)
      window.removeEventListener('mouseup', handleMouseUp)
    }
  }, [])

  const selectAgent = useCallback((run) => setSelection({ type: 'agent', agentRun: run }), [])
  const selectTool = useCallback((tc, run) => setSelection({ type: 'tool', agentRun: run, toolCall: tc }), [])

  const isAgentSelected = (run) => selection?.agentRun === run
  const isToolSelected = (tc) => selection?.type === 'tool' && selection?.toolCall === tc

  return (
    <div className="flex-1 overflow-hidden flex flex-col min-h-0">
      {/* Toolbar */}
      <div className="flex items-center gap-1 px-3 py-1.5 border-b bg-gray-50 flex-shrink-0">
        <button onClick={() => setShowJson(true)} className="flex items-center gap-1.5 px-2 py-1 text-xs text-gray-500 rounded hover:bg-gray-200 transition-colors" title="View full JSON">
          <Braces className="w-3.5 h-3.5" /><span>View JSON</span>
        </button>
        <button onClick={() => setShowLogs(true)} className="flex items-center gap-1.5 px-2 py-1 text-xs text-gray-500 rounded hover:bg-gray-200 transition-colors" title="Backend logs">
          <Terminal className="w-3.5 h-3.5" /><span>Backend Logs</span>
        </button>
        <button onClick={() => downloadAsFile(data, data?.title || 'session')} className="flex items-center gap-1.5 px-2 py-1 text-xs text-gray-500 rounded hover:bg-gray-200 transition-colors" title="Download session JSON">
          <Download className="w-3.5 h-3.5" /><span>Download</span>
        </button>
      </div>

      {/* Summary stats */}
      {agentRuns.length > 0 && <InspectSummary agentRuns={agentRuns} data={data} />}

      {/* Split layout */}
      <div className="flex-1 flex min-h-0">
        {/* Left: outline */}
        <div style={{ width: leftWidth }} className="flex-shrink-0 overflow-y-auto border-r border-gray-200 bg-white">
          {agentRuns.length === 0 && (
            <div className="flex flex-col items-center justify-center py-12 text-gray-400 gap-2">
              <MessageSquare className="w-8 h-8 opacity-30" />
              <p className="text-xs">No agent runs</p>
            </div>
          )}
          {agentRuns.map((run) => {
            const allTools = []
            for (const llm of run.llm_calls || []) {
              for (const tc of llm.tool_calls || []) {
                allTools.push(tc)
              }
            }
            return (
              <div key={run.id}>
                <OutlineAgentHeader
                  agentRun={run}
                  selected={isAgentSelected(run) && selection?.type === 'agent'}
                  onClick={() => selectAgent(run)}
                />
                {allTools.map((tc, ti) => (
                  <OutlineToolLine
                    key={tc.id || ti}
                    tc={tc}
                    selected={isToolSelected(tc)}
                    onClick={() => selectTool(tc, run)}
                  />
                ))}
              </div>
            )
          })}
        </div>

        {/* Drag handle */}
        <div
          onMouseDown={handleDragStart}
          className="w-1 flex-shrink-0 cursor-col-resize hover:bg-blue-300 active:bg-blue-400 transition-colors"
        />

        {/* Right: detail */}
        <div ref={detailRef} className="flex-1 overflow-y-auto bg-white">
          {selection ? (
            <div className="p-4">
              {selection.type === 'agent' && <AgentDetailPanel agentRun={selection.agentRun} sessionId={sessionId} sessionStatus={sessionStatus} />}
              {selection.type === 'tool' && <ToolDetailPanel tc={selection.toolCall} agentRun={selection.agentRun} />}
            </div>
          ) : (
            <div className="flex items-center justify-center h-full text-gray-400 text-sm">
              Select an agent or tool
            </div>
          )}
        </div>
      </div>

      {showJson && <JsonViewerModal data={data} title={data.title || 'Session'} onClose={() => setShowJson(false)} />}
      {showLogs && <ContainerLogsModal containerName="druppie-new-backend" onClose={() => setShowLogs(false)} />}
    </div>
  )
}

export default DebugEventLog
