/**
 * PiCodingRunLiveCard — live view of an execute_coding_task_pi run while it
 * executes. Polls /api/pi-agent-runs/by-tool-call/{toolCallId} every ~1.5s
 * until status is "succeeded" or "failed".
 *
 * Shape of each event comes from pi_agent/src/journal.ts — see JournalEvent.
 * Tool-call detail: each tool_call event carries `args`; the matching
 * tool_result (paired by callId) carries `preview` + `ok` + `durationMs`.
 *
 * Once the run is complete and PiCodingRunCard picks it up via the tool
 * result, this card is no longer rendered (SessionDetail switches to the
 * summary card based on tool_call.status === 'completed').
 */

import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  ChevronDown,
  ChevronRight,
  Loader2,
  Clock,
  Layers,
  Bot,
  Wrench,
  GitBranch,
  GitCommit,
  AlertTriangle,
  Radio,
  RefreshCw,
  Check,
  X,
} from 'lucide-react'

import { getPiCodingRunByToolCall } from '../../services/api'

const fmtMs = (ms) => {
  if (ms == null) return '—'
  if (ms < 1000) return `${ms}ms`
  const s = ms / 1000
  if (s < 60) return `${s.toFixed(1)}s`
  const m = Math.floor(s / 60)
  return `${m}m ${Math.round(s % 60)}s`
}

const fmtClock = (iso) => {
  if (!iso) return ''
  try {
    const d = new Date(iso)
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
  } catch {
    return ''
  }
}

const prettyJson = (val) => {
  if (val == null) return ''
  if (typeof val === 'string') return val
  try {
    return JSON.stringify(val, null, 2)
  } catch {
    return String(val)
  }
}

const phaseColor = {
  EXPLORE: 'bg-sky-100 text-sky-800',
  analyze: 'bg-sky-100 text-sky-800',
  plan: 'bg-indigo-100 text-indigo-800',
  build: 'bg-emerald-100 text-emerald-800',
  verify: 'bg-amber-100 text-amber-800',
  'pr-author': 'bg-violet-100 text-violet-800',
}

// Roll up raw journal events into: phase, subagents (each with their full
// tool-call history), sandbox state, commits, errors, narratives. Single
// pass so the render stays cheap even for long runs.
const rollup = (events) => {
  const agents = new Map()  // id -> { id, name, state, ..., toolCalls:[] }
  const callIndex = new Map()  // callId -> { agentId, idx } so tool_result can pair back
  const phases = []
  let currentPhase = null
  const commits = []
  const errors = []
  const narratives = []
  let sandbox = { state: 'pending' }
  let push = null
  let pr = null

  for (const e of events) {
    switch (e.type) {
      case 'sandbox_start':
        sandbox = { state: 'starting', runtime: e.runtime, containerName: e.containerName }
        break
      case 'sandbox_ready':
        sandbox = { ...sandbox, state: 'ready', containerName: e.containerName || sandbox.containerName }
        break
      case 'sandbox_stop':
        sandbox = { ...sandbox, state: 'stopped' }
        break
      case 'phase_start':
        currentPhase = { phase: e.phase, iteration: e.iteration, startedAt: e.ts, endedAt: null }
        phases.push(currentPhase)
        break
      case 'phase_end':
        if (currentPhase && currentPhase.phase === e.phase && currentPhase.iteration === e.iteration) {
          currentPhase.endedAt = e.ts
          currentPhase.durationMs = e.durationMs
        }
        currentPhase = null
        break
      case 'subagent_start':
        agents.set(e.id, {
          id: e.id, name: e.name, model: e.model,
          state: 'running', startedAt: e.ts,
          turns: 0, toolCalls: 0, retries: 0,
          toolHistory: [],
        })
        break
      case 'subagent_end': {
        const a = agents.get(e.id)
        if (a) {
          a.state = e.success ? 'done' : 'failed'
          a.turns = e.turns ?? a.turns
          a.toolCalls = e.toolCalls ?? a.toolCalls
          a.retries = e.retries ?? a.retries
          a.durationMs = e.durationMs
          a.error = e.error
        }
        break
      }
      case 'tool_call': {
        const a = agents.get(e.agentId)
        if (a) {
          a.toolCalls += 1
          const entry = {
            callId: e.callId, tool: e.tool, args: e.args,
            ts: e.ts, agentId: e.agentId,
            ok: null, durationMs: null, preview: null, done: false,
          }
          a.toolHistory.push(entry)
          if (e.callId) callIndex.set(e.callId, { agentId: e.agentId, idx: a.toolHistory.length - 1 })
        }
        break
      }
      case 'tool_result': {
        const ref = callIndex.get(e.callId)
        if (ref) {
          const a = agents.get(ref.agentId)
          const entry = a?.toolHistory[ref.idx]
          if (entry) {
            entry.ok = e.ok
            entry.durationMs = e.durationMs
            entry.preview = e.preview ?? null
            entry.done = true
          }
        }
        break
      }
      case 'llm_retry_start': {
        const a = agents.get(e.agentId)
        if (a) a.retries = Math.max(a.retries, e.attempt || 0)
        break
      }
      case 'commit':
        commits.push({ phase: e.phase, sha: e.sha, message: e.message })
        break
      case 'push_done':
        push = { ok: e.ok, branch: e.branch }
        break
      case 'pr_ensured':
        pr = { action: e.action, number: e.number, url: e.url }
        break
      case 'error':
        errors.push(e.message)
        break
      case 'subagent_narrative':
        narratives.push({ agent: e.agent, iteration: e.iteration, chars: e.chars })
        break
      default:
        break
    }
  }

  const allAgents = [...agents.values()]
  const active = allAgents.filter((a) => a.state === 'running')
  const done = allAgents.filter((a) => a.state !== 'running')
  return { currentPhase, phases, agents: allAgents, active, done, sandbox, commits, errors, narratives, push, pr, callIndex }
}

const friendlyEvent = (e) => {
  switch (e.type) {
    case 'run_start': return 'run started'
    case 'git_provider_selected': return `git provider: ${e.kind}`
    case 'flow_selected': return `flow: ${e.flow}`
    case 'sandbox_start': return `sandbox booting (${e.runtime})`
    case 'sandbox_ready': return `sandbox ready: ${e.containerName}`
    case 'source_clone': return `cloned ${e.branch}`
    case 'phase_start': return `phase ${e.phase} #${e.iteration}`
    case 'phase_end': return `phase ${e.phase} done (${fmtMs(e.durationMs)})`
    case 'subagent_start': return `${e.name} started (${e.id})`
    case 'subagent_end': return `${e.id} ${e.success ? 'done' : 'failed'} · ${e.turns}t ${e.toolCalls}tc ${fmtMs(e.durationMs)}`
    case 'llm_retry_start': return `${e.agentId} LLM retry #${e.attempt}${e.reason ? ' — ' + e.reason : ''}`
    case 'llm_retry_end': return `${e.agentId} LLM retry #${e.attempt} ${e.success ? 'ok' : 'err'}`
    case 'router_retry': return `router retry #${e.attempt}${e.reason ? ' — ' + e.reason : ''}`
    case 'branch_renamed': return `branch renamed ${e.from} → ${e.to}`
    case 'commit': return `commit ${(e.sha || '').slice(0, 7)}: ${e.message || ''}`
    case 'push_start': return `push ${e.branch} (${e.bundleBytes ?? 0}B)`
    case 'push_done': return `push ${e.branch} ${e.ok ? 'ok' : 'FAILED'}`
    case 'pr_ensured': return `PR ${e.action}${e.number ? ` #${e.number}` : ''}`
    case 'error': return `error: ${e.message}`
    case 'run_end': return `run ended (${e.success ? 'success' : 'failure'})`
    case 'subagent_narrative': return `${e.agent} narrative (${e.chars} chars)`
    default: return e.type
  }
}

const eventColor = (type) => {
  if (type === 'error') return 'text-rose-700'
  if (type.includes('retry')) return 'text-amber-700'
  if (type.startsWith('subagent')) return 'text-indigo-700'
  if (type.startsWith('phase')) return 'text-sky-700'
  if (type.startsWith('tool')) return 'text-gray-700'
  if (type.startsWith('sandbox')) return 'text-purple-700'
  if (type.startsWith('push') || type === 'commit' || type === 'pr_ensured') return 'text-emerald-700'
  return 'text-gray-600'
}

// Expandable tool-call row: shows `agent → tool (status, duration)` with
// an accordion for args and result preview. Used both in the timeline and
// in per-subagent drilldowns.
const ToolCallRow = ({ entry, showAgent = true }) => {
  const [open, setOpen] = useState(false)
  const hasArgs = entry.args && (typeof entry.args !== 'object' || Object.keys(entry.args).length > 0)
  const hasPreview = entry.preview && entry.preview.length > 0
  const clickable = hasArgs || hasPreview
  const status =
    entry.done == null || !entry.done ? 'pending' :
    entry.ok ? 'ok' : 'err'
  return (
    <div className="border-b border-gray-100 last:border-0">
      <button
        type="button"
        disabled={!clickable}
        onClick={() => setOpen((v) => !v)}
        className={`w-full flex items-center gap-2 px-2 py-1 text-left ${clickable ? 'hover:bg-gray-50 cursor-pointer' : 'cursor-default'}`}
      >
        <span className="text-gray-400 shrink-0 font-mono text-[11px]">{fmtClock(entry.ts)}</span>
        {status === 'pending' ? (
          <Loader2 size={12} className="animate-spin text-sky-600 shrink-0" />
        ) : status === 'ok' ? (
          <Check size={12} className="text-emerald-600 shrink-0" />
        ) : (
          <X size={12} className="text-rose-600 shrink-0" />
        )}
        {showAgent && <span className="text-indigo-700 font-mono text-[11px] shrink-0">{entry.agentId}</span>}
        <Wrench size={11} className="text-gray-400 shrink-0" />
        <span className="font-mono text-[11px] text-gray-800 truncate flex-1">{entry.tool}</span>
        {entry.durationMs != null && (
          <span className="text-gray-400 text-[10px] shrink-0">{fmtMs(entry.durationMs)}</span>
        )}
        {clickable && (
          <span className="text-gray-400 shrink-0">
            {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
          </span>
        )}
      </button>
      {open && clickable && (
        <div className="px-3 pb-2 pt-1 space-y-2 bg-gray-50 border-t border-gray-100">
          {hasArgs && (
            <div>
              <div className="text-[10px] uppercase tracking-wide text-gray-500 mb-0.5">arguments</div>
              <pre className="font-mono text-[11px] whitespace-pre-wrap break-words bg-white border rounded p-2 max-h-48 overflow-y-auto">
                {prettyJson(entry.args)}
              </pre>
            </div>
          )}
          {hasPreview && (
            <div>
              <div className="text-[10px] uppercase tracking-wide text-gray-500 mb-0.5">
                result {entry.ok === false && <span className="text-rose-700">· error</span>}
              </div>
              <pre className="font-mono text-[11px] whitespace-pre-wrap break-words bg-white border rounded p-2 max-h-48 overflow-y-auto">
                {entry.preview}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

const SubagentBlock = ({ agent }) => {
  const [open, setOpen] = useState(false)
  const isRunning = agent.state === 'running'
  const tools = agent.toolHistory || []
  return (
    <div className="bg-white border rounded">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-2 px-2 py-1 text-left hover:bg-gray-50"
      >
        {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
        {isRunning ? (
          <Loader2 size={12} className="animate-spin text-sky-600 shrink-0" />
        ) : agent.state === 'done' ? (
          <Check size={12} className="text-emerald-600 shrink-0" />
        ) : (
          <X size={12} className="text-rose-600 shrink-0" />
        )}
        <span className="font-mono text-[11px] font-medium">{agent.id}</span>
        <span className="text-gray-400 text-[10px]">{agent.model}</span>
        {agent.retries > 0 && (
          <span className="flex items-center gap-0.5 text-amber-700 text-[10px]">
            <RefreshCw size={10} /> {agent.retries}
          </span>
        )}
        <span className="ml-auto text-[10px] text-gray-500">
          {agent.turns}t · {agent.toolCalls}tc{agent.durationMs != null ? ` · ${fmtMs(agent.durationMs)}` : ''}
        </span>
      </button>
      {open && (
        <div className="border-t border-gray-100 bg-gray-50">
          {tools.length === 0 ? (
            <div className="px-3 py-1 text-[11px] text-gray-400 italic">no tool calls yet</div>
          ) : (
            tools.map((t) => (
              <ToolCallRow key={t.callId || t.ts} entry={t} showAgent={false} />
            ))
          )}
          {agent.error && (
            <div className="px-3 py-1 text-[11px] text-rose-700">error: {agent.error}</div>
          )}
        </div>
      )}
    </div>
  )
}

const PiCodingRunLiveCard = ({ toolCallId }) => {
  const [expanded, setExpanded] = useState(true)
  const [showAll, setShowAll] = useState(false)

  const { data, isLoading, error } = useQuery({
    queryKey: ['pi-coding-run', toolCallId],
    queryFn: () => getPiCodingRunByToolCall(toolCallId, 0),
    refetchInterval: (query) => {
      const s = query.state.data?.status
      if (!s || s === 'running') return 1500
      return false
    },
    retry: (failureCount, err) => {
      if (err?.status === 404) return failureCount < 10
      if (err?.status === 403) return false
      return failureCount < 3
    },
    enabled: !!toolCallId,
  })

  const events = data?.events || []
  const state = useMemo(() => rollup(events), [events])

  if (isLoading && !data) {
    return (
      <div className="border rounded-lg bg-white p-3 flex items-center gap-2 text-sm text-gray-600">
        <Loader2 className="animate-spin" size={14} /> pi coding run starting…
      </div>
    )
  }
  if (error && error.status !== 404) {
    return (
      <div className="border rounded-lg bg-rose-50 border-rose-200 p-3 text-sm text-rose-800">
        pi coding run: failed to load live state ({error.message || error.status})
      </div>
    )
  }
  if (!data) {
    return (
      <div className="border rounded-lg bg-white p-3 flex items-center gap-2 text-sm text-gray-600">
        <Loader2 className="animate-spin" size={14} /> pi coding run initializing…
      </div>
    )
  }

  const running = data.status === 'running'
  // Show a mixed timeline: every event except standalone tool_result (tool
  // info is folded into the corresponding tool_call row for richer detail).
  const timelineEvents = events.filter((e) => e.type !== 'tool_result')
  const visibleEvents = showAll ? timelineEvents : timelineEvents.slice(-30)

  return (
    <div className="border rounded-lg bg-white overflow-hidden">
      <button
        onClick={() => setExpanded((v) => !v)}
        className="w-full flex items-center gap-3 px-3 py-2 hover:bg-gray-50 text-left"
      >
        {expanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
        {running ? (
          <Loader2 size={16} className="text-sky-600 animate-spin" />
        ) : data.status === 'succeeded' ? (
          <Radio size={16} className="text-emerald-600" />
        ) : (
          <AlertTriangle size={16} className="text-rose-600" />
        )}
        <span className="font-medium text-sm">
          pi coding run <span className="text-gray-500">· {data.agent_name || 'flow'}</span>
        </span>
        <span className="text-xs text-gray-500 flex items-center gap-1">
          <Clock size={12} /> {fmtMs(data.elapsed_ms)}
        </span>
        <span className="text-xs text-gray-500 flex items-center gap-1">
          <GitBranch size={12} /> {data.branch_name || data.repo_target || '—'}
        </span>
        {state.currentPhase && (
          <span className={`text-xs px-2 py-0.5 rounded ${phaseColor[state.currentPhase.phase] || 'bg-gray-100 text-gray-700'}`}>
            {state.currentPhase.phase}
            {state.currentPhase.iteration > 1 && <span className="opacity-60"> ×{state.currentPhase.iteration}</span>}
          </span>
        )}
        <span className="ml-auto text-xs text-gray-500">
          {data.total_events} events
        </span>
      </button>

      {expanded && (
        <div className="px-3 py-3 border-t bg-gray-50 space-y-3 text-sm">
          {/* Sandbox status */}
          <div className="flex items-center gap-2 text-xs text-gray-700">
            <span className="uppercase tracking-wide text-gray-500">sandbox</span>
            <span className={
              state.sandbox.state === 'ready' ? 'text-emerald-700' :
              state.sandbox.state === 'starting' ? 'text-amber-700' :
              state.sandbox.state === 'stopped' ? 'text-gray-500' : 'text-gray-600'
            }>
              {state.sandbox.state}
            </span>
            {state.sandbox.containerName && state.sandbox.containerName !== '(pending)' && (
              <span className="text-gray-400 font-mono">{state.sandbox.containerName}</span>
            )}
          </div>

          {/* Subagents (active + done merged, each expandable to tool history) */}
          {state.agents.length > 0 && (
            <section>
              <div className="text-xs uppercase tracking-wide text-gray-500 mb-1 flex items-center gap-1">
                <Bot size={12} /> subagents ({state.active.length} active / {state.agents.length} total)
              </div>
              <div className="space-y-1">
                {state.agents.map((a) => <SubagentBlock key={a.id} agent={a} />)}
              </div>
            </section>
          )}

          {/* Commits as they happen */}
          {state.commits.length > 0 && (
            <section>
              <div className="text-xs uppercase tracking-wide text-gray-500 mb-1 flex items-center gap-1">
                <GitCommit size={12} /> commits ({state.commits.length})
              </div>
              <ul className="space-y-0.5">
                {state.commits.map((c, i) => (
                  <li key={i} className="text-xs flex gap-2">
                    <span className="font-mono text-gray-500">{(c.sha || '').slice(0, 7)}</span>
                    <span>{c.message}</span>
                  </li>
                ))}
              </ul>
            </section>
          )}

          {/* Errors */}
          {state.errors.length > 0 && (
            <section>
              <div className="text-xs uppercase tracking-wide text-rose-700 mb-1 flex items-center gap-1">
                <AlertTriangle size={12} /> errors
              </div>
              <ul className="list-disc pl-5 text-xs text-rose-800 space-y-0.5">
                {state.errors.map((m, i) => <li key={i}>{m}</li>)}
              </ul>
            </section>
          )}

          {/* Live event stream — tool_call rows are expandable to show args
              and result preview inline. tool_result events are folded into
              their matching tool_call row, so they're hidden here. */}
          <section>
            <div className="text-xs uppercase tracking-wide text-gray-500 mb-1 flex items-center gap-1">
              <Radio size={12} /> timeline
              {timelineEvents.length > 30 && (
                <button
                  type="button"
                  className="ml-auto normal-case text-[10px] text-sky-700 hover:underline"
                  onClick={(e) => { e.stopPropagation(); setShowAll((v) => !v) }}
                >
                  {showAll ? 'show last 30' : `show all ${timelineEvents.length}`}
                </button>
              )}
            </div>
            <div className="bg-white border rounded max-h-96 overflow-y-auto">
              {visibleEvents.map((e, i) => {
                if (e.type === 'tool_call') {
                  const ref = state.callIndex?.get(e.callId)
                  const agent = ref ? state.agents.find((a) => a.id === ref.agentId) : null
                  const entry = agent?.toolHistory?.[ref.idx]
                  if (entry) return <ToolCallRow key={i} entry={entry} showAgent={true} />
                }
                return (
                  <div key={i} className="flex gap-2 px-2 py-0.5 border-b border-gray-100 last:border-0 font-mono text-[11px]">
                    <span className="text-gray-400 shrink-0">{fmtClock(e.ts)}</span>
                    <span className={`${eventColor(e.type)} shrink-0`}>{e.type}</span>
                    <span className="text-gray-700 truncate">{friendlyEvent(e)}</span>
                  </div>
                )
              })}
              {visibleEvents.length === 0 && (
                <div className="px-2 py-2 text-gray-400 italic text-[11px]">no events yet…</div>
              )}
            </div>
          </section>
        </div>
      )}
    </div>
  )
}

export default PiCodingRunLiveCard
