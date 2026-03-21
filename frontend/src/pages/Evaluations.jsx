/**
 * Admin Evaluations Page
 *
 * Browse benchmark runs, drill into evaluation results, and trigger new benchmarks.
 * Three views: runs list -> run detail -> result detail.
 */

import { useState, useEffect } from 'react'
import {
  FlaskConical,
  ArrowLeft,
  Loader2,
  AlertCircle,
  Trash2,
  Play,
  CheckCircle2,
  XCircle,
  ChevronLeft,
  ChevronRight,
  RefreshCw,
} from 'lucide-react'
import {
  getBenchmarkRuns,
  getBenchmarkRun,
  getEvaluationResult,
  triggerBenchmark,
  deleteBenchmarkRun,
} from '../services/api'

// ---- Helpers ----

const formatDate = (dateStr) => {
  if (!dateStr) return '-'
  try {
    return new Date(dateStr).toLocaleString()
  } catch {
    return dateStr
  }
}

const truncate = (str, maxLen = 80) => {
  if (str === null || str === undefined) return '-'
  const s = String(str)
  return s.length > maxLen ? s.substring(0, maxLen) + '...' : s
}

const StatusBadge = ({ value }) => {
  if (!value) return <span className="text-gray-400">-</span>
  const colors = {
    running: 'bg-blue-100 text-blue-700',
    completed: 'bg-green-100 text-green-700',
    failed: 'bg-red-100 text-red-700',
    pending: 'bg-yellow-100 text-yellow-700',
  }
  const colorClass = colors[value] || 'bg-gray-100 text-gray-700'
  return (
    <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${colorClass}`}>
      {value}
    </span>
  )
}

const ScoreDisplay = ({ result }) => {
  if (!result) return <span className="text-gray-400">-</span>

  const scoreType = result.score_type || 'binary'
  const score = result.score

  if (score === null || score === undefined) {
    return <span className="text-gray-400">-</span>
  }

  if (scoreType === 'binary') {
    return score >= 1 ? (
      <CheckCircle2 className="w-5 h-5 text-green-500" />
    ) : (
      <XCircle className="w-5 h-5 text-red-500" />
    )
  }

  // Graded score
  const maxScore = result.max_score || 5
  return (
    <span className="font-mono text-sm font-medium">
      <span className={score >= maxScore * 0.7 ? 'text-green-600' : score >= maxScore * 0.4 ? 'text-yellow-600' : 'text-red-600'}>
        {score}
      </span>
      <span className="text-gray-400">/{maxScore}</span>
    </span>
  )
}

// ---- Trigger Benchmark Form ----

const TriggerBenchmarkForm = ({ onTriggered }) => {
  const [open, setOpen] = useState(false)
  const [scenarioName, setScenarioName] = useState('')
  const [judgeModel, setJudgeModel] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState(null)

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (!scenarioName.trim()) return
    setSubmitting(true)
    setError(null)
    try {
      await triggerBenchmark(scenarioName.trim(), judgeModel.trim() || null)
      setScenarioName('')
      setJudgeModel('')
      setOpen(false)
      if (onTriggered) onTriggered()
    } catch (err) {
      setError(err.message)
    } finally {
      setSubmitting(false)
    }
  }

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 text-sm"
      >
        <Play className="w-4 h-4" />
        Trigger Benchmark
      </button>
    )
  }

  return (
    <form onSubmit={handleSubmit} className="flex items-end gap-3 p-3 bg-gray-50 rounded-lg border">
      <div>
        <label className="block text-xs font-medium text-gray-600 mb-1">Scenario Name</label>
        <input
          type="text"
          value={scenarioName}
          onChange={(e) => setScenarioName(e.target.value)}
          placeholder="e.g. todo-app-basic"
          className="px-3 py-1.5 border rounded text-sm w-56 focus:outline-none focus:ring-2 focus:ring-blue-500"
          required
        />
      </div>
      <div>
        <label className="block text-xs font-medium text-gray-600 mb-1">Judge Model (optional)</label>
        <input
          type="text"
          value={judgeModel}
          onChange={(e) => setJudgeModel(e.target.value)}
          placeholder="e.g. gpt-4o"
          className="px-3 py-1.5 border rounded text-sm w-40 focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
      </div>
      <button
        type="submit"
        disabled={submitting}
        className="px-4 py-1.5 bg-blue-600 text-white rounded text-sm hover:bg-blue-700 disabled:opacity-50 flex items-center gap-1"
      >
        {submitting && <Loader2 className="w-3 h-3 animate-spin" />}
        Run
      </button>
      <button
        type="button"
        onClick={() => setOpen(false)}
        className="px-3 py-1.5 bg-gray-200 text-gray-700 rounded text-sm hover:bg-gray-300"
      >
        Cancel
      </button>
      {error && <span className="text-red-500 text-xs">{error}</span>}
    </form>
  )
}

// ---- Runs List View ----

const RunsList = ({ onSelectRun }) => {
  const [runs, setRuns] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [page, setPage] = useState(1)
  const [totalPages, setTotalPages] = useState(1)

  const fetchRuns = async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await getBenchmarkRuns(page, 20)
      setRuns(data.items || [])
      setTotalPages(data.total_pages || 1)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchRuns()
  }, [page])

  const handleDelete = async (e, runId) => {
    e.stopPropagation()
    if (!window.confirm('Delete this benchmark run and all its results?')) return
    try {
      await deleteBenchmarkRun(runId)
      fetchRuns()
    } catch (err) {
      alert('Failed to delete: ' + err.message)
    }
  }

  if (loading) {
    return (
      <div className="p-8 flex items-center justify-center">
        <Loader2 className="w-6 h-6 animate-spin text-blue-500" />
        <span className="ml-2 text-gray-600">Loading benchmark runs...</span>
      </div>
    )
  }

  if (error) {
    return (
      <div className="p-8 text-center text-red-500">
        <AlertCircle className="w-8 h-8 mx-auto mb-2" />
        <p>{error}</p>
        <button onClick={fetchRuns} className="mt-2 px-4 py-2 bg-blue-500 text-white rounded text-sm">
          Retry
        </button>
      </div>
    )
  }

  return (
    <div className="bg-white rounded-lg border overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="border-b border-gray-100 bg-gray-50">
            <tr>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Name</th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Type</th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Git Branch</th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Judge Model</th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Started</th>
              <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Status</th>
              <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase">Actions</th>
            </tr>
          </thead>
          <tbody>
            {runs.length === 0 ? (
              <tr>
                <td colSpan={7} className="px-4 py-8 text-center text-gray-500">
                  No benchmark runs found. Trigger a benchmark to get started.
                </td>
              </tr>
            ) : (
              runs.map((run) => (
                <tr
                  key={run.id}
                  onClick={() => onSelectRun(run.id)}
                  className="border-b border-gray-50 hover:bg-blue-50/50 cursor-pointer transition-colors"
                >
                  <td className="px-4 py-3 font-medium">{run.name || run.scenario_name || truncate(run.id, 12)}</td>
                  <td className="px-4 py-3 text-gray-600">{run.run_type || '-'}</td>
                  <td className="px-4 py-3">
                    {run.git_branch ? (
                      <code className="text-xs bg-gray-100 px-1.5 py-0.5 rounded">{run.git_branch}</code>
                    ) : (
                      <span className="text-gray-400">-</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-gray-600 text-xs font-mono">{run.judge_model || '-'}</td>
                  <td className="px-4 py-3 text-gray-500 text-xs">{formatDate(run.started_at || run.created_at)}</td>
                  <td className="px-4 py-3"><StatusBadge value={run.status} /></td>
                  <td className="px-4 py-3 text-right">
                    <button
                      onClick={(e) => handleDelete(e, run.id)}
                      className="p-1.5 text-gray-400 hover:text-red-500 hover:bg-red-50 rounded transition-colors"
                      title="Delete run"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between px-4 py-3 border-t border-gray-100">
          <span className="text-sm text-gray-600">Page {page} of {totalPages}</span>
          <div className="flex items-center gap-1">
            <button
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page === 1}
              className="p-1 rounded hover:bg-gray-200 disabled:opacity-30"
            >
              <ChevronLeft className="w-4 h-4" />
            </button>
            <span className="px-3 text-sm">{page}</span>
            <button
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              disabled={page === totalPages}
              className="p-1 rounded hover:bg-gray-200 disabled:opacity-30"
            >
              <ChevronRight className="w-4 h-4" />
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

// ---- Run Detail View ----

const RunDetail = ({ runId, onBack, onSelectResult }) => {
  const [run, setRun] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    const fetch = async () => {
      setLoading(true)
      setError(null)
      try {
        const data = await getBenchmarkRun(runId)
        setRun(data)
      } catch (err) {
        setError(err.message)
      } finally {
        setLoading(false)
      }
    }
    fetch()
  }, [runId])

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

  const results = run.results || []

  return (
    <div className="space-y-4">
      {/* Run info card */}
      <div className="bg-white rounded-lg border p-4">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div>
            <div className="text-xs text-gray-500 uppercase font-medium">Name</div>
            <div className="text-sm font-medium mt-0.5">{run.name || run.scenario_name || '-'}</div>
          </div>
          <div>
            <div className="text-xs text-gray-500 uppercase font-medium">Type</div>
            <div className="text-sm mt-0.5">{run.run_type || '-'}</div>
          </div>
          <div>
            <div className="text-xs text-gray-500 uppercase font-medium">Judge Model</div>
            <div className="text-sm font-mono mt-0.5">{run.judge_model || '-'}</div>
          </div>
          <div>
            <div className="text-xs text-gray-500 uppercase font-medium">Status</div>
            <div className="mt-0.5"><StatusBadge value={run.status} /></div>
          </div>
          <div>
            <div className="text-xs text-gray-500 uppercase font-medium">Git Branch</div>
            <div className="text-sm mt-0.5">
              {run.git_branch ? (
                <code className="text-xs bg-gray-100 px-1.5 py-0.5 rounded">{run.git_branch}</code>
              ) : '-'}
            </div>
          </div>
          <div>
            <div className="text-xs text-gray-500 uppercase font-medium">Git Commit</div>
            <div className="text-sm font-mono mt-0.5">{run.git_commit ? truncate(run.git_commit, 8) : '-'}</div>
          </div>
          <div>
            <div className="text-xs text-gray-500 uppercase font-medium">Started</div>
            <div className="text-xs text-gray-600 mt-0.5">{formatDate(run.started_at || run.created_at)}</div>
          </div>
          <div>
            <div className="text-xs text-gray-500 uppercase font-medium">Completed</div>
            <div className="text-xs text-gray-600 mt-0.5">{formatDate(run.completed_at)}</div>
          </div>
        </div>
      </div>

      {/* Evaluation results table */}
      <div className="bg-white rounded-lg border overflow-hidden">
        <div className="px-4 py-3 border-b border-gray-100 bg-gray-50">
          <h3 className="font-semibold text-sm">Evaluation Results ({results.length})</h3>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="border-b border-gray-100">
              <tr>
                <th className="px-4 py-2.5 text-left text-xs font-medium text-gray-500 uppercase">Agent</th>
                <th className="px-4 py-2.5 text-left text-xs font-medium text-gray-500 uppercase">Evaluation</th>
                <th className="px-4 py-2.5 text-center text-xs font-medium text-gray-500 uppercase">Score</th>
                <th className="px-4 py-2.5 text-left text-xs font-medium text-gray-500 uppercase">Reasoning</th>
              </tr>
            </thead>
            <tbody>
              {results.length === 0 ? (
                <tr>
                  <td colSpan={4} className="px-4 py-8 text-center text-gray-500">
                    No evaluation results yet.
                  </td>
                </tr>
              ) : (
                results.map((r) => (
                  <tr
                    key={r.id}
                    onClick={() => onSelectResult(r.id)}
                    className="border-b border-gray-50 hover:bg-blue-50/50 cursor-pointer transition-colors"
                  >
                    <td className="px-4 py-2.5 font-medium">{r.agent_id || '-'}</td>
                    <td className="px-4 py-2.5 text-gray-600">{r.evaluation_name || r.rubric_name || '-'}</td>
                    <td className="px-4 py-2.5 text-center"><ScoreDisplay result={r} /></td>
                    <td className="px-4 py-2.5 text-gray-500 text-xs">{truncate(r.reasoning, 100)}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}

// ---- Result Detail View ----

const ResultDetail = ({ resultId, onBack }) => {
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    const fetch = async () => {
      setLoading(true)
      setError(null)
      try {
        const data = await getEvaluationResult(resultId)
        setResult(data)
      } catch (err) {
        setError(err.message)
      } finally {
        setLoading(false)
      }
    }
    fetch()
  }, [resultId])

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

  if (!result) return null

  const fields = [
    ['ID', result.id],
    ['Agent', result.agent_id],
    ['Evaluation Name', result.evaluation_name || result.rubric_name],
    ['Score Type', result.score_type],
    ['Score', result.score],
    ['Max Score', result.max_score],
    ['Session ID', result.session_id],
    ['Benchmark Run ID', result.benchmark_run_id],
    ['Created', formatDate(result.created_at)],
  ]

  return (
    <div className="space-y-4">
      {/* Score header */}
      <div className="bg-white rounded-lg border p-4 flex items-center justify-between">
        <div>
          <h3 className="text-lg font-semibold">{result.evaluation_name || result.rubric_name || 'Evaluation Result'}</h3>
          <p className="text-sm text-gray-500 mt-0.5">Agent: {result.agent_id || '-'}</p>
        </div>
        <div className="text-2xl">
          <ScoreDisplay result={result} />
        </div>
      </div>

      {/* Metadata */}
      <div className="bg-white rounded-lg border overflow-hidden">
        <div className="px-4 py-3 border-b border-gray-100 bg-gray-50">
          <h3 className="font-semibold text-sm">Metadata</h3>
        </div>
        <table className="w-full text-sm">
          <tbody>
            {fields.map(([label, value]) => (
              <tr key={label} className="border-b last:border-0">
                <td className="px-4 py-2 font-medium text-gray-600 bg-gray-50 w-40">{label}</td>
                <td className="px-4 py-2 font-mono text-xs">{value !== null && value !== undefined ? String(value) : '-'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Reasoning */}
      {result.reasoning && (
        <div className="bg-white rounded-lg border overflow-hidden">
          <div className="px-4 py-3 border-b border-gray-100 bg-gray-50">
            <h3 className="font-semibold text-sm">Reasoning</h3>
          </div>
          <div className="p-4">
            <pre className="text-sm whitespace-pre-wrap text-gray-700 bg-gray-50 p-3 rounded border">
              {result.reasoning}
            </pre>
          </div>
        </div>
      )}

      {/* Judge Prompt */}
      {result.judge_prompt && (
        <div className="bg-white rounded-lg border overflow-hidden">
          <div className="px-4 py-3 border-b border-gray-100 bg-gray-50">
            <h3 className="font-semibold text-sm">Judge Prompt</h3>
          </div>
          <div className="p-4">
            <pre className="text-xs whitespace-pre-wrap text-gray-600 bg-gray-50 p-3 rounded border max-h-96 overflow-auto">
              {result.judge_prompt}
            </pre>
          </div>
        </div>
      )}

      {/* Judge Response */}
      {result.judge_response && (
        <div className="bg-white rounded-lg border overflow-hidden">
          <div className="px-4 py-3 border-b border-gray-100 bg-gray-50">
            <h3 className="font-semibold text-sm">Judge Response</h3>
          </div>
          <div className="p-4">
            <pre className="text-xs whitespace-pre-wrap text-gray-600 bg-gray-50 p-3 rounded border max-h-96 overflow-auto">
              {typeof result.judge_response === 'object'
                ? JSON.stringify(result.judge_response, null, 2)
                : result.judge_response}
            </pre>
          </div>
        </div>
      )}

      {/* Extra metadata */}
      {result.metadata && Object.keys(result.metadata).length > 0 && (
        <div className="bg-white rounded-lg border overflow-hidden">
          <div className="px-4 py-3 border-b border-gray-100 bg-gray-50">
            <h3 className="font-semibold text-sm">Extra Metadata</h3>
          </div>
          <div className="p-4">
            <pre className="text-xs whitespace-pre-wrap text-gray-600 bg-gray-50 p-3 rounded border max-h-60 overflow-auto">
              {JSON.stringify(result.metadata, null, 2)}
            </pre>
          </div>
        </div>
      )}
    </div>
  )
}

// ---- Main Component ----

export default function Evaluations() {
  const [view, setView] = useState('list')       // 'list' | 'run' | 'result'
  const [selectedRunId, setSelectedRunId] = useState(null)
  const [selectedResultId, setSelectedResultId] = useState(null)
  const [refreshKey, setRefreshKey] = useState(0)

  const handleSelectRun = (runId) => {
    setSelectedRunId(runId)
    setView('run')
  }

  const handleSelectResult = (resultId) => {
    setSelectedResultId(resultId)
    setView('result')
  }

  const handleBackToList = () => {
    setView('list')
    setSelectedRunId(null)
  }

  const handleBackToRun = () => {
    setView('run')
    setSelectedResultId(null)
  }

  const handleTriggered = () => {
    setRefreshKey((k) => k + 1)
    setView('list')
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          {view !== 'list' && (
            <button
              onClick={view === 'result' ? handleBackToRun : handleBackToList}
              className="flex items-center gap-1 px-3 py-1.5 text-sm bg-gray-100 hover:bg-gray-200 rounded transition-colors"
            >
              <ArrowLeft className="w-4 h-4" />
              Back
            </button>
          )}
          <FlaskConical className="w-6 h-6 text-purple-600" />
          <h1 className="text-2xl font-bold">
            {view === 'list' && 'Evaluations'}
            {view === 'run' && 'Benchmark Run'}
            {view === 'result' && 'Evaluation Result'}
          </h1>
        </div>
        {view === 'list' && (
          <div className="flex items-center gap-2">
            <button
              onClick={() => setRefreshKey((k) => k + 1)}
              className="p-2 hover:bg-gray-200 rounded transition-colors"
              title="Refresh"
            >
              <RefreshCw className="w-4 h-4" />
            </button>
            <TriggerBenchmarkForm onTriggered={handleTriggered} />
          </div>
        )}
      </div>

      {/* Content */}
      {view === 'list' && <RunsList key={refreshKey} onSelectRun={handleSelectRun} />}
      {view === 'run' && (
        <RunDetail
          runId={selectedRunId}
          onBack={handleBackToList}
          onSelectResult={handleSelectResult}
        />
      )}
      {view === 'result' && (
        <ResultDetail resultId={selectedResultId} onBack={handleBackToRun} />
      )}
    </div>
  )
}
