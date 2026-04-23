/**
 * PiCodingRunCard - expandable card for a single execute_coding_task_pi run.
 *
 * The tool's result shape (from druppie/agents/execute_coding_task_pi.py):
 *   {
 *     success, run_id, pi_coding_run_id,
 *     summary: RunSummary,        // see pi_agent/src/journal.ts
 *     pr_url, branch,
 *     commits: [{ phase, sha, message }],
 *     phases:  [{ phase, iteration, durationMs, subagents }],
 *   }
 *
 * Distinct from SandboxEventCard (legacy execute_coding_task) — the legacy
 * card assumes a control-plane events stream; this one renders the compact
 * RunSummary that pi_agent emits at close().
 */

import { useState } from 'react'
import {
  CheckCircle2,
  XCircle,
  ChevronDown,
  ChevronRight,
  GitBranch,
  GitCommit,
  ExternalLink,
  Clock,
  Layers,
  Bot,
  AlertTriangle,
} from 'lucide-react'

const fmtMs = (ms) => {
  if (ms == null) return '—'
  if (ms < 1000) return `${ms}ms`
  const s = ms / 1000
  if (s < 60) return `${s.toFixed(1)}s`
  const m = Math.floor(s / 60)
  return `${m}m ${Math.round(s % 60)}s`
}

const fmtNum = (n) => (n == null ? '—' : n.toLocaleString('en-US'))

const phaseColor = {
  analyze: 'bg-sky-100 text-sky-800',
  plan: 'bg-indigo-100 text-indigo-800',
  build: 'bg-emerald-100 text-emerald-800',
  verify: 'bg-amber-100 text-amber-800',
  'pr-author': 'bg-violet-100 text-violet-800',
}

const PiCodingRunCard = ({ piResult }) => {
  const [expanded, setExpanded] = useState(false)
  if (!piResult) return null

  const summary = piResult.summary || {}
  const success = !!piResult.success
  const phases = summary.phases || piResult.phases || []
  const commits = summary.commits || piResult.commits || []
  const agents = summary.agents || []
  const prUrl = piResult.pr_url || summary.pr?.url
  const branch = piResult.branch || summary.push?.branch || '—'
  const totalTokens = agents.reduce(
    (acc, a) => ({ in: acc.in + (a.tokensInput || 0), out: acc.out + (a.tokensOutput || 0) }),
    { in: 0, out: 0 },
  )

  return (
    <div className="border rounded-lg bg-white overflow-hidden">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-3 px-3 py-2 hover:bg-gray-50 text-left"
      >
        {expanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
        {success ? (
          <CheckCircle2 size={16} className="text-emerald-600" />
        ) : (
          <XCircle size={16} className="text-rose-600" />
        )}
        <span className="font-medium text-sm">pi coding run</span>
        <span className="text-xs text-gray-500 flex items-center gap-1">
          <GitBranch size={12} /> {branch}
        </span>
        <span className="text-xs text-gray-500 flex items-center gap-1">
          <GitCommit size={12} /> {commits.length}
        </span>
        <span className="text-xs text-gray-500 flex items-center gap-1">
          <Clock size={12} /> {fmtMs(summary.durationMs)}
        </span>
        {prUrl && (
          <a
            href={prUrl}
            target="_blank"
            rel="noreferrer"
            onClick={(e) => e.stopPropagation()}
            className="ml-auto text-xs text-sky-700 hover:underline flex items-center gap-1"
          >
            PR <ExternalLink size={12} />
          </a>
        )}
      </button>

      {expanded && (
        <div className="px-3 py-3 border-t bg-gray-50 space-y-4 text-sm">
          {/* Phase timeline */}
          {phases.length > 0 && (
            <section>
              <div className="text-xs uppercase tracking-wide text-gray-500 mb-2 flex items-center gap-1">
                <Layers size={12} /> phases
              </div>
              <div className="flex flex-wrap gap-2">
                {phases.map((p, i) => (
                  <div
                    key={i}
                    className={`px-2 py-1 rounded text-xs ${phaseColor[p.phase] || 'bg-gray-100 text-gray-700'}`}
                  >
                    {p.phase}
                    {p.iteration > 1 && <span className="opacity-60"> ×{p.iteration}</span>}
                    <span className="opacity-60"> · {fmtMs(p.durationMs)}</span>
                  </div>
                ))}
              </div>
            </section>
          )}

          {/* Agents */}
          {agents.length > 0 && (
            <section>
              <div className="text-xs uppercase tracking-wide text-gray-500 mb-2 flex items-center gap-1">
                <Bot size={12} /> agents
              </div>
              <table className="w-full text-xs">
                <thead className="text-gray-500">
                  <tr>
                    <th className="text-left font-normal">agent</th>
                    <th className="text-right font-normal">turns</th>
                    <th className="text-right font-normal">tools</th>
                    <th className="text-right font-normal">tok in</th>
                    <th className="text-right font-normal">tok out</th>
                    <th className="text-right font-normal">elapsed</th>
                  </tr>
                </thead>
                <tbody>
                  {agents.map((a) => (
                    <tr key={a.id} className="border-t border-gray-200">
                      <td className="py-1">
                        {a.success === false && (
                          <AlertTriangle size={12} className="inline text-amber-600 mr-1" />
                        )}
                        {a.name}
                      </td>
                      <td className="text-right">{a.turns}</td>
                      <td className="text-right">{a.toolCalls}</td>
                      <td className="text-right">{fmtNum(a.tokensInput)}</td>
                      <td className="text-right">{fmtNum(a.tokensOutput)}</td>
                      <td className="text-right">{fmtMs(a.durationMs)}</td>
                    </tr>
                  ))}
                  <tr className="border-t border-gray-300 font-medium">
                    <td className="py-1">total</td>
                    <td></td>
                    <td></td>
                    <td className="text-right">{fmtNum(totalTokens.in)}</td>
                    <td className="text-right">{fmtNum(totalTokens.out)}</td>
                    <td></td>
                  </tr>
                </tbody>
              </table>
            </section>
          )}

          {/* Commits */}
          {commits.length > 0 && (
            <section>
              <div className="text-xs uppercase tracking-wide text-gray-500 mb-2 flex items-center gap-1">
                <GitCommit size={12} /> commits ({commits.length})
              </div>
              <ul className="space-y-1">
                {commits.map((c, i) => (
                  <li key={i} className="flex items-start gap-2 text-xs">
                    <span className="font-mono text-gray-500">{(c.sha || '').slice(0, 7)}</span>
                    <span
                      className={`px-1.5 rounded text-[10px] ${phaseColor[c.phase] || 'bg-gray-100 text-gray-700'}`}
                    >
                      {c.phase}
                    </span>
                    <span className="flex-1">{c.message}</span>
                  </li>
                ))}
              </ul>
            </section>
          )}

          {/* Errors */}
          {summary.errors?.length > 0 && (
            <section>
              <div className="text-xs uppercase tracking-wide text-rose-700 mb-1 flex items-center gap-1">
                <AlertTriangle size={12} /> errors
              </div>
              <ul className="list-disc pl-5 text-xs text-rose-800 space-y-0.5">
                {summary.errors.map((e, i) => (
                  <li key={i}>{e}</li>
                ))}
              </ul>
            </section>
          )}
        </div>
      )}
    </div>
  )
}

export default PiCodingRunCard
