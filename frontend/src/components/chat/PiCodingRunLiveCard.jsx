/**
 * PiCodingRunLiveCard — unified live + final view of an execute_coding_task_pi
 * run. Polls /api/pi-agent-runs/by-tool-call/{toolCallId} every ~1.5s while
 * the run is active, stops on terminal state. Same component renders
 * executing, succeeded, and failed runs — the timeline/agent tree stays
 * visible after completion so you can go back and see exactly what happened
 * in the sandbox, long after the call has returned to the caller agent.
 *
 * The caller agent only receives the summarised result (for explore: just
 * the final answer; for tdd: branch + PR + commits). All the sandbox detail
 * lives here so it doesn't pollute the caller's context.
 *
 * Event shape from pi_agent/src/journal.ts — see JournalEvent. Tool-call
 * detail: each tool_call event carries `args`; the matching tool_result
 * (paired by callId) carries `preview` + `ok` + `durationMs`.
 */

import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  ChevronDown,
  ChevronRight,
  Loader2,
  Clock,
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
// tool-call history), sandbox state, commits, errors, narratives.
// Single pass so the render stays cheap even for long runs.
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
          state: 'running', startedAt: e.ts, endedAt: null,
          phase: currentPhase?.phase, phaseIteration: currentPhase?.iteration,
          iteration: e.iteration ?? null,
          // Parent-agent linkage (router → explorer): set by pi_agent when a
          // custom tool like spawn_parallel_explorers fans out subagents. The
          // UI uses these to nest children under the tool_call that spawned
          // them rather than render everything as top-level.
          parentAgentId: e.parentAgentId ?? null,
          parentToolCallId: e.parentToolCallId ?? null,
          explorerSlug: e.explorerSlug ?? null,
          role: e.role ?? null,
          turns: 0, toolCalls: 0, retries: 0,
          toolHistory: [],
          narrative: null,
        })
        break
      case 'subagent_end': {
        const a = agents.get(e.id)
        if (a) {
          a.state = e.success ? 'done' : 'failed'
          a.endedAt = e.ts
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
        narratives.push({ agent: e.agent, iteration: e.iteration, chars: e.chars, text: e.text })
        break
      default:
        break
    }
  }

  const allAgents = [...agents.values()]

  // Attach each narrative back to the agent that produced it, so the UI can
  // render it in the owning SubagentBlock / child row. Matching is based on
  // pi_agent's narrative key convention (see recordNarrative call sites):
  //   "router/attempt-N"  → agent id router-N
  //   "explorer/<slug>"    → explorer agent with matching explorerSlug + iteration
  //   "builder/<stepId>"   → builder agent with matching stepId
  //   "<name>"             → top-level agent by name + iteration (analyst, planner, verifier)
  for (const n of narratives) {
    const [head, rest] = (n.agent || '').split('/', 2)
    let match = null
    if (head === 'router' && rest) {
      const m = rest.match(/attempt-(\d+)/)
      if (m) match = allAgents.find((a) => a.name === 'router' && a.id === `router-${m[1]}`)
    } else if (head === 'explorer' && rest) {
      match = allAgents.find((a) => a.name === 'explorer' && a.explorerSlug === rest)
    } else if (head === 'builder' && rest) {
      match = allAgents.find((a) => a.name === 'builder' && a.stepId === rest)
    } else if (head) {
      match = allAgents.find((a) => a.name === head)
    }
    if (match && !match.narrative) match.narrative = n.text
  }

  // Primary = not spawned as a child of another agent. Children are those
  // with parentAgentId set (e.g. explorers under a router tool call).
  const primary = allAgents.filter((a) => !a.parentAgentId)
  const childrenByParentCallId = new Map()
  for (const a of allAgents) {
    if (a.parentToolCallId) {
      const list = childrenByParentCallId.get(a.parentToolCallId) ?? []
      list.push(a)
      childrenByParentCallId.set(a.parentToolCallId, list)
    }
  }

  const active = allAgents.filter((a) => a.state === 'running')
  const done = allAgents.filter((a) => a.state !== 'running')
  return { currentPhase, phases, agents: allAgents, primary, childrenByParentCallId, active, done, sandbox, commits, errors, narratives, push, pr, callIndex }
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
// an accordion for args + result preview + any subagents this tool call
// spawned (e.g. spawn_parallel_explorers → N explorer agents). Children
// come directly from the journal's parentToolCallId linkage, so "what
// the router's tool spawned" lines up 1:1 with the orchestrator's actual
// calls — no guessing.
const ToolCallRow = ({ entry, showAgent = true, childAgents = [] }) => {
  const [open, setOpen] = useState(false)
  const hasArgs = entry.args && (typeof entry.args !== 'object' || Object.keys(entry.args).length > 0)
  const previewIsEmpty = entry.preview === '' || entry.preview == null
  const hasPreview = entry.preview != null && entry.preview.length > 0
  const hasChildren = childAgents && childAgents.length > 0
  // Every completed tool call is expandable — so you can always see its
  // status, even when there were no args and no result text. A completed
  // call with no output renders an explicit "(no output)" in the result
  // section, distinct from an un-completed (pending/abandoned) call.
  const clickable = hasArgs || hasPreview || hasChildren || entry.done === true
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
        {hasChildren && (
          <span className="text-[10px] px-1.5 py-0.5 rounded bg-indigo-50 text-indigo-700 shrink-0">
            {childAgents.length} subagent{childAgents.length > 1 ? 's' : ''}
          </span>
        )}
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
          {hasChildren && (
            <div>
              <div className="text-[10px] uppercase tracking-wide text-gray-500 mb-0.5">
                {childAgents.length} subagent{childAgents.length > 1 ? 's' : ''} spawned by this call{childAgents.length > 1 ? ' — parallel' : ''}
              </div>
              {/* Stack vertically so each subagent has full width. The
                  violet left stripe marks them as siblings of one parallel
                  spawn; the index prefix makes the ordering explicit. */}
              <div className="pl-3 border-l-4 border-violet-400 space-y-1">
                {childAgents.map((c, i) => (
                  <ChildAgentCard key={c.id} agent={c} index={i + 1} siblingCount={childAgents.length} />
                ))}
              </div>
            </div>
          )}
          {/* Always show a result section for completed tool calls.
              Distinguishes three cases explicitly:
                (a) has output → render it verbatim.
                (b) completed with empty stdout → "(no output — tool
                    succeeded silently, e.g. mkdir/cd/rm)".
                (c) not completed → shown in the outer status icon (spinner).
              Previously (b) looked the same as (c) because we just omitted
              the whole section. */}
          {entry.done === true ? (
            <div>
              <div className="text-[10px] uppercase tracking-wide text-gray-500 mb-0.5">
                result {entry.ok === false && <span className="text-rose-700">· error</span>}
              </div>
              {hasPreview ? (
                <pre className="font-mono text-[11px] whitespace-pre-wrap break-words bg-white border rounded p-2 max-h-96 overflow-y-auto">
                  {entry.preview}
                </pre>
              ) : (
                <div className="font-mono text-[11px] italic text-gray-500 bg-white border rounded p-2">
                  (no output — tool succeeded silently)
                </div>
              )}
            </div>
          ) : (
            <div>
              <div className="text-[10px] uppercase tracking-wide text-gray-500 mb-0.5">
                result
              </div>
              <div className="font-mono text-[11px] italic text-amber-700 bg-amber-50 border border-amber-200 rounded p-2">
                no tool_result event recorded — the session likely aborted before
                this tool finished (max-turns, consecutive errors, or crash).
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// One full-width row for a subagent spawned by a parent's tool call (e.g.
// an explorer spawned by router's spawn_parallel_explorers). Shows status,
// slug, numbered index, quick stats; expands to reveal the subagent's
// final assistant output AND its full tool-call history (args + results).
const ChildAgentCard = ({ agent, index, siblingCount }) => {
  const [open, setOpen] = useState(false)
  const [toolsOpen, setToolsOpen] = useState(false)
  const running = agent.state === 'running'
  const failed = agent.state === 'failed'
  const borderClass = failed ? 'border-rose-200' : running ? 'border-sky-200' : 'border-emerald-200'
  const tools = agent.toolHistory || []
  return (
    <div className={`border rounded bg-white ${borderClass}`}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-2 px-2 py-1 text-left hover:bg-gray-50 text-[11px]"
      >
        <span className="text-[10px] font-mono text-violet-700 bg-violet-50 rounded px-1 shrink-0 min-w-[2ch] text-center">
          {index}{siblingCount > 1 ? `/${siblingCount}` : ''}
        </span>
        {running ? <Loader2 size={11} className="animate-spin text-sky-600 shrink-0" /> :
          failed ? <X size={11} className="text-rose-600 shrink-0" /> :
          <Check size={11} className="text-emerald-600 shrink-0" />}
        <span className="font-mono font-medium truncate">{agent.explorerSlug || agent.id}</span>
        {agent.explorerSlug && (
          <span className="text-gray-400 text-[10px] truncate">({agent.id})</span>
        )}
        <span className="ml-auto text-gray-500 shrink-0">{agent.turns}t · {agent.toolCalls}tc · {fmtMs(agent.durationMs)}</span>
      </button>
      {open && (
        <div className="border-t border-gray-100 bg-gray-50 text-[11px]">
          {/* Final assistant output */}
          <div className="p-2">
            <div className="text-[10px] uppercase tracking-wide text-gray-500 mb-0.5">
              final output
            </div>
            {agent.narrative ? (
              <pre className="whitespace-pre-wrap break-words bg-white border rounded p-2 max-h-96 overflow-y-auto font-mono">
                {agent.narrative}
              </pre>
            ) : (
              <span className="text-gray-400 italic">no output yet</span>
            )}
            {agent.error && <div className="mt-1 text-rose-700">error: {agent.error}</div>}
          </div>
          {/* Tool-call history — per-subagent, collapsed by default so the
              final output leads the view. Click the "tool calls (N)" header
              to expand the list; each row is then individually expandable
              to reveal its args + result preview. */}
          {tools.length > 0 && (
            <div className="border-t border-gray-100">
              <button
                type="button"
                onClick={() => setToolsOpen((v) => !v)}
                className="w-full flex items-center gap-1 px-2 py-1 text-left hover:bg-gray-100 text-[10px] uppercase tracking-wide text-gray-500"
              >
                {toolsOpen ? <ChevronDown size={10} /> : <ChevronRight size={10} />}
                tool calls ({tools.length})
              </button>
              {toolsOpen && (
                <div className="bg-white border-t border-gray-100">
                  {tools.map((t) => (
                    <ToolCallRow key={t.callId || t.ts} entry={t} showAgent={false} />
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// Block for one primary agent (analyst / planner / builder / verifier /
// router). Expands to reveal the agent's tool-call history with any
// subagents spawned by those calls nested inline, plus the agent's own
// narrative (the end-of-turn text it produced).
const AgentBlock = ({ agent, childrenByParentCallId }) => {
  const [open, setOpen] = useState(false)
  const isRunning = agent.state === 'running'
  const tools = agent.toolHistory || []
  const hasNarrative = !!(agent.narrative && agent.narrative.trim())
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
        {agent.stepId && <span className="text-[10px] px-1 rounded bg-gray-100 text-gray-700">{agent.stepId}</span>}
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
              <ToolCallRow
                key={t.callId || t.ts}
                entry={t}
                showAgent={false}
                childAgents={t.callId ? (childrenByParentCallId?.get(t.callId) ?? []) : []}
              />
            ))
          )}
          {hasNarrative && (
            <details className="border-t border-gray-100">
              <summary className="px-3 py-1 text-[11px] cursor-pointer hover:bg-gray-100 text-gray-600">
                final output ({agent.narrative.length} chars)
              </summary>
              <pre className="font-mono text-[11px] whitespace-pre-wrap break-words bg-white m-2 border rounded p-2 max-h-96 overflow-y-auto">
                {agent.narrative}
              </pre>
            </details>
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
        {state.commits.length > 0 && (
          <span className="text-xs text-gray-500 flex items-center gap-1">
            <GitCommit size={12} /> {state.commits.length}
          </span>
        )}
        {state.currentPhase && (
          <span className={`text-xs px-2 py-0.5 rounded ${phaseColor[state.currentPhase.phase] || 'bg-gray-100 text-gray-700'}`}>
            {state.currentPhase.phase}
            {state.currentPhase.iteration > 1 && <span className="opacity-60"> ×{state.currentPhase.iteration}</span>}
          </span>
        )}
        {data.pr_url && (
          <a
            href={data.pr_url}
            target="_blank"
            rel="noreferrer"
            onClick={(e) => e.stopPropagation()}
            className="text-xs text-sky-700 hover:underline flex items-center gap-1"
          >
            PR{data.pr_number ? ` #${data.pr_number}` : ''}
          </a>
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

          {/* Primary agents only at the top level. Children (explorers
              spawned by a router via spawn_parallel_explorers) are nested
              inside the parent's corresponding tool_call row, keeping the
              UI structure aligned with what the agent actually did. */}
          {state.primary.length > 0 && (
            <section>
              <div className="text-xs uppercase tracking-wide text-gray-500 mb-1 flex items-center gap-1">
                <Bot size={12} /> agents ({state.primary.filter((a) => a.state === 'running').length} active / {state.primary.length} total)
              </div>
              <div className="space-y-1">
                {state.primary.map((a) => (
                  <AgentBlock key={a.id} agent={a} childrenByParentCallId={state.childrenByParentCallId} />
                ))}
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
