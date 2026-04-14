/**
 * TestRunDetail — Single test run detail view with assertion results
 * and judge checks. Shown when a user clicks into a specific test run.
 */

import { useState, useEffect } from 'react'
import {
  Loader2,
  AlertCircle,
  CheckCircle2,
  XCircle,
  Tag,
  MessageSquare,
} from 'lucide-react'
import { getTestRun, getTestRunAssertions } from '../../services/api'
import { formatDate, formatDuration, StatusBadge } from './helpers'

// ---- Judge Checks Section ----

const JudgeChecksSection = ({ judgeChecks }) => {
  const [expandedRaw, setExpandedRaw] = useState(new Set())

  const toggleRaw = (i) => {
    const next = new Set(expandedRaw)
    if (next.has(i)) next.delete(i)
    else next.add(i)
    setExpandedRaw(next)
  }

  return (
    <div className="bg-white rounded-lg border overflow-hidden">
      <div className="px-4 py-3 border-b border-gray-100 bg-yellow-50">
        <h3 className="font-semibold text-sm">LLM Judge Checks ({judgeChecks.filter(j => j.passed).length}/{judgeChecks.length} passed)</h3>
      </div>
      <div className="divide-y">
        {judgeChecks.map((jr, i) => (
          <div key={i} className="px-4 py-3">
            <div className="flex items-start gap-3">
              {jr.passed ? (
                <CheckCircle2 className="w-5 h-5 text-green-500 mt-0.5 shrink-0" />
              ) : (
                <XCircle className="w-5 h-5 text-red-500 mt-0.5 shrink-0" />
              )}
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="px-1.5 py-0.5 rounded text-xs font-mono bg-yellow-50 text-yellow-700">
                    judge
                  </span>
                  {jr.agent_id && (
                    <span className="text-sm font-medium text-gray-700">{jr.agent_id}</span>
                  )}
                </div>
                {jr.message && (
                  <p className="text-sm text-gray-700 mt-1">{jr.message}</p>
                )}
                {jr.judge_reasoning && (
                  <div className="mt-2 p-2 bg-gray-50 rounded text-sm">
                    <span className="font-medium text-gray-600">Reasoning: </span>
                    <span className="text-gray-500">{jr.judge_reasoning}</span>
                  </div>
                )}
                {(jr.judge_raw_input || jr.judge_raw_output) && (
                  <button
                    onClick={() => toggleRaw(i)}
                    className="mt-2 text-xs text-indigo-600 hover:text-indigo-800 hover:underline"
                  >
                    {expandedRaw.has(i) ? 'Hide' : 'Show'} raw LLM call
                  </button>
                )}
              </div>
            </div>
            {expandedRaw.has(i) && (jr.judge_raw_input || jr.judge_raw_output) && (
              <div className="mt-3 ml-8 space-y-2">
                {jr.judge_raw_input && (
                  <div>
                    <div className="text-xs font-medium text-gray-500 mb-1">Prompt sent to judge:</div>
                    <pre className="text-xs bg-gray-900 text-green-400 p-3 rounded overflow-x-auto max-h-96 overflow-y-auto whitespace-pre-wrap">{jr.judge_raw_input}</pre>
                  </div>
                )}
                {jr.judge_raw_output && (
                  <div>
                    <div className="text-xs font-medium text-gray-500 mb-1">Judge response:</div>
                    <pre className="text-xs bg-gray-900 text-yellow-400 p-3 rounded overflow-x-auto max-h-48 overflow-y-auto whitespace-pre-wrap">{jr.judge_raw_output}</pre>
                  </div>
                )}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

// ---- Main TestRunDetail Component ----

const TestRunDetail = ({ testRunId, onBack }) => {
  const [run, setRun] = useState(null)
  const [assertionResults, setAssertionResults] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    let cancelled = false
    const fetchData = async () => {
      setLoading(true)
      setError(null)
      try {
        const [data, assertions] = await Promise.all([
          getTestRun(testRunId),
          getTestRunAssertions(testRunId).catch(() => []),
        ])
        if (!cancelled) {
          setRun(data)
          setAssertionResults(assertions || [])
        }
      } catch (err) {
        if (!cancelled) setError(err.message)
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    fetchData()
    return () => { cancelled = true }
  }, [testRunId])

  if (loading) {
    return (
      <div className="p-8 flex items-center justify-center">
        <Loader2 className="w-6 h-6 animate-spin text-blue-500" />
      </div>
    )
  }

  if (error) {
    return (
      <div className="p-8 text-center text-red-500">
        <AlertCircle className="w-8 h-8 mx-auto mb-2" />
        <p>{error}</p>
        <button onClick={onBack} className="mt-2 px-4 py-2 bg-gray-200 text-gray-700 rounded text-sm">
          Back
        </button>
      </div>
    )
  }

  if (!run) return null

  // Group assertion results by type
  const assertions = assertionResults.filter((r) => r.assertion_type !== 'judge_check')
  const judgeChecks = assertionResults.filter((r) => r.assertion_type === 'judge_check')

  const modeLabel = run.mode || 'agent'
  const modeBg = {
    agent: 'bg-blue-100 text-blue-700',
    tool: 'bg-amber-100 text-amber-700',
  }[modeLabel] || 'bg-gray-100 text-gray-700'

  return (
    <div className="space-y-4">
      {/* Header card */}
      <div className="bg-white rounded-lg border p-4 flex items-center justify-between">
        <div>
          <h3 className="text-lg font-semibold">{run.test_name || 'Test Run'}</h3>
          {run.test_description && (
            <p className="text-sm text-gray-500 mt-0.5">{run.test_description}</p>
          )}
          <div className="flex items-center gap-2 mt-2">
            <span className={`px-2 py-0.5 rounded text-xs font-medium ${modeBg}`}>
              {modeLabel}
            </span>
            {run.agent_id && (
              <span className="px-2 py-0.5 bg-indigo-50 text-indigo-700 rounded text-xs font-medium">
                agent: {run.agent_id}
              </span>
            )}
            {(run.tags || []).map((tag) => (
              <span
                key={tag}
                className="inline-flex items-center gap-0.5 px-2 py-0.5 bg-purple-50 text-purple-700 rounded text-xs"
              >
                <Tag className="w-3 h-3" />
                {tag}
              </span>
            ))}
          </div>
        </div>
        <div className="text-right space-y-2">
          <StatusBadge value={run.status} />
          <div className="text-sm text-gray-500">{formatDuration(run.duration_ms)}</div>
          {run.session_id && (
            <a
              href={`/chat?session=${run.session_id}`}
              className="inline-flex items-center gap-2 px-4 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 text-sm"
            >
              <MessageSquare size={16} />
              View Session
            </a>
          )}
        </div>
      </div>

      {/* What was tested — Assertions */}
      <div className="bg-white rounded-lg border overflow-hidden">
        <div className="px-4 py-3 border-b border-gray-100 bg-gray-50 flex items-center justify-between">
          <h3 className="font-semibold text-sm">Assertions ({assertions.filter(a => a.passed).length}/{assertions.length} passed)</h3>
        </div>
        {assertions.length === 0 ? (
          <div className="px-4 py-3 text-sm text-gray-400">No assertions recorded</div>
        ) : (
          <div className="divide-y">
            {assertions.map((ar, i) => (
              <div key={i} className="px-4 py-3 flex items-start gap-3">
                {ar.passed ? (
                  <CheckCircle2 className="w-5 h-5 text-green-500 mt-0.5 shrink-0" />
                ) : (
                  <XCircle className="w-5 h-5 text-red-500 mt-0.5 shrink-0" />
                )}
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className={`px-1.5 py-0.5 rounded text-xs font-mono ${
                      ar.assertion_type === 'completed' ? 'bg-blue-50 text-blue-700' :
                      ar.assertion_type === 'tool_called' ? 'bg-purple-50 text-purple-700' :
                      ar.assertion_type === 'verify' ? 'bg-amber-50 text-amber-700' :
                      ar.assertion_type === 'result_valid' ? 'bg-cyan-50 text-cyan-700' :
                      'bg-gray-50 text-gray-700'
                    }`}>
                      {ar.assertion_type}
                    </span>
                    {ar.agent_id && (
                      <span className="text-sm font-medium text-gray-700">{ar.agent_id}</span>
                    )}
                    {ar.tool_name && (
                      <span className="text-sm font-mono text-gray-500">{ar.tool_name}</span>
                    )}
                    {ar.eval_name && (
                      <span className="text-xs text-gray-400">[{ar.eval_name}]</span>
                    )}
                  </div>
                  {ar.message && (
                    <p className="text-sm text-gray-500 mt-1">{ar.message}</p>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Judge Checks */}
      {judgeChecks.length > 0 && (
        <JudgeChecksSection judgeChecks={judgeChecks} />
      )}

      {/* Metadata */}
      <div className="bg-white rounded-lg border overflow-hidden">
        <div className="px-4 py-3 border-b border-gray-100 bg-gray-50">
          <h3 className="font-semibold text-sm">Run Details</h3>
        </div>
        <table className="w-full text-sm">
          <tbody>
            {[
              ['Mode', modeLabel],
              ['Primary Agent', run.agent_id || '-'],
              ['HITL Profile', run.hitl_profile],
              ['Judge Profile', run.judge_profile],
              ['Test User', run.test_user],
              ['Sessions Seeded', run.sessions_seeded],
              ['Duration', formatDuration(run.duration_ms)],
              ['Created', formatDate(run.created_at)],
            ].map(([label, value]) => (
              <tr key={label} className="border-b last:border-0">
                <td className="px-4 py-2 font-medium text-gray-600 bg-gray-50 w-44">{label}</td>
                <td className="px-4 py-2 text-sm">{value !== null && value !== undefined ? String(value) : '-'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

export default TestRunDetail
