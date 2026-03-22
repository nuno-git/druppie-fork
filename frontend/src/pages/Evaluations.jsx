/**
 * Admin Tests Page
 *
 * Two-section layout:
 * 1. Available Tests -- YAML test definitions that can be run
 * 2. Test Results -- past test run results with detail view
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
  Tag,
  Clock,
  Filter,
  MessageSquare,
  FileText,
  Users,
} from 'lucide-react'
import {
  getAvailableTests,
  getTestRuns,
  getTestRun,
  getTags,
  deleteTestUsers,
  runTests,
  getRunStatus,
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

const formatDuration = (ms) => {
  if (ms === null || ms === undefined) return '-'
  if (ms < 1000) return `${ms}ms`
  const secs = (ms / 1000).toFixed(1)
  return `${secs}s`
}

const StatusBadge = ({ value }) => {
  if (!value) return <span className="text-gray-400">-</span>
  const colors = {
    running: 'bg-blue-100 text-blue-700',
    completed: 'bg-green-100 text-green-700',
    failed: 'bg-red-100 text-red-700',
    pending: 'bg-yellow-100 text-yellow-700',
    passed: 'bg-green-100 text-green-700',
    error: 'bg-orange-100 text-orange-700',
  }
  const colorClass = colors[value] || 'bg-gray-100 text-gray-700'
  return (
    <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${colorClass}`}>
      {value}
    </span>
  )
}

// ---- Results Banner ----

const ResultsBanner = ({ result, onDismiss }) => {
  if (!result) return null

  const allPassed = result.passed === result.total
  const bgColor = allPassed ? 'bg-green-50 border-green-200' : 'bg-red-50 border-red-200'
  const textColor = allPassed ? 'text-green-800' : 'text-red-800'
  const Icon = allPassed ? CheckCircle2 : XCircle

  return (
    <div className={`flex items-center justify-between px-4 py-3 rounded-lg border ${bgColor}`}>
      <div className="flex items-center gap-3">
        <Icon className={`w-5 h-5 ${allPassed ? 'text-green-600' : 'text-red-600'}`} />
        <span className={`font-medium ${textColor}`}>
          {result.passed}/{result.total} passed
        </span>
        {result.results && result.results.length > 0 && (
          <span className="text-sm text-gray-500">
            ({result.results.map((r) => r.test_name).join(', ')})
          </span>
        )}
      </div>
      <button
        onClick={onDismiss}
        className="text-gray-400 hover:text-gray-600 text-sm"
      >
        Dismiss
      </button>
    </div>
  )
}

// ---- Available Tests Section ----

const AvailableTests = ({ onRunSingle, isRunning, runningSingle }) => {
  const [tests, setTests] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    const fetch = async () => {
      setLoading(true)
      setError(null)
      try {
        const data = await getAvailableTests()
        setTests(data || [])
      } catch (err) {
        setError(err.message)
      } finally {
        setLoading(false)
      }
    }
    fetch()
  }, [])

  if (loading) {
    return (
      <div className="p-4 flex items-center justify-center">
        <Loader2 className="w-4 h-4 animate-spin text-blue-500" />
        <span className="ml-2 text-sm text-gray-600">Loading test definitions...</span>
      </div>
    )
  }

  if (error) {
    return (
      <div className="p-4 text-center text-red-500 text-sm">
        <AlertCircle className="w-5 h-5 mx-auto mb-1" />
        <p>{error}</p>
      </div>
    )
  }

  if (tests.length === 0) {
    return (
      <div className="p-4 text-center text-gray-500 text-sm">
        No test definitions found in testing/tests/
      </div>
    )
  }

  return (
    <div className="divide-y divide-gray-100">
      {tests.map((test) => (
        <div
          key={test.name}
          className="flex items-center justify-between px-4 py-3 hover:bg-gray-50 transition-colors"
        >
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <FileText className="w-4 h-4 text-purple-500 flex-shrink-0" />
              <span className="font-medium text-sm">{test.name}</span>
            </div>
            <p className="text-xs text-gray-500 mt-0.5 ml-6 truncate">
              {test.description || test.message}
            </p>
            <div className="flex items-center gap-3 mt-1 ml-6">
              <span className="text-xs text-gray-400">
                agents: [{test.real_agents.join(', ')}]
              </span>
              {test.num_sessions > 0 && (
                <span className="text-xs text-gray-400">
                  {test.num_sessions} session{test.num_sessions !== 1 ? 's' : ''}
                </span>
              )}
            </div>
          </div>
          <button
            onClick={() => onRunSingle(test.name)}
            disabled={isRunning}
            title={`Run ${test.name}`}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-green-50 text-green-700 rounded text-xs font-medium hover:bg-green-100 border border-green-200 disabled:opacity-30 transition-colors flex-shrink-0 ml-3"
          >
            {runningSingle === test.name ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
            ) : (
              <Play className="w-3.5 h-3.5" />
            )}
            Run
          </button>
        </div>
      ))}
    </div>
  )
}

// ---- Test Runs List View ----

const TestRunsList = ({ onSelectRun, refreshKey, onRunSingle, isRunning, runningSingle, runResult, setRunResult, runMessage }) => {
  const [runs, setRuns] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [page, setPage] = useState(1)
  const [totalPages, setTotalPages] = useState(1)
  const [tags, setTags] = useState([])
  const [selectedTag, setSelectedTag] = useState(null)

  const fetchTags = async () => {
    try {
      const data = await getTags()
      setTags(data || [])
    } catch {
      // Tags are optional, don't block on failure
    }
  }

  const fetchRuns = async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await getTestRuns(page, 20, selectedTag)
      setRuns(data.items || [])
      setTotalPages(data.total_pages || 1)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchTags()
  }, [refreshKey])

  useEffect(() => {
    fetchRuns()
  }, [page, selectedTag, refreshKey])

  return (
    <div className="space-y-3">
      {/* Results banner */}
      <ResultsBanner result={runResult} onDismiss={() => setRunResult(null)} />

      {/* Filter bar */}
      {tags.length > 0 && (
        <div className="flex items-center gap-3">
          <Filter className="w-4 h-4 text-gray-400" />
          <select
            value={selectedTag || ''}
            onChange={(e) => {
              setSelectedTag(e.target.value || null)
              setPage(1)
            }}
            className="px-3 py-1.5 border rounded text-sm bg-white focus:outline-none focus:ring-2 focus:ring-purple-500"
          >
            <option value="">All tags</option>
            {tags.map((t) => (
              <option key={t.tag} value={t.tag}>
                {t.tag} ({t.count})
              </option>
            ))}
          </select>
          {selectedTag && (
            <button
              onClick={() => { setSelectedTag(null); setPage(1) }}
              className="text-xs text-gray-500 hover:text-gray-700 underline"
            >
              Clear filter
            </button>
          )}
        </div>
      )}

      {/* Loading state */}
      {loading && (
        <div className="p-8 flex items-center justify-center">
          <Loader2 className="w-6 h-6 animate-spin text-blue-500" />
          <span className="ml-2 text-gray-600">Loading test runs...</span>
        </div>
      )}

      {/* Error state */}
      {error && !loading && (
        <div className="p-8 text-center text-red-500">
          <AlertCircle className="w-8 h-8 mx-auto mb-2" />
          <p>{error}</p>
          <button onClick={fetchRuns} className="mt-2 px-4 py-2 bg-blue-500 text-white rounded text-sm">
            Retry
          </button>
        </div>
      )}

      {/* Table */}
      {!loading && !error && (
        <div className="bg-white rounded-lg border overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="border-b border-gray-100 bg-gray-50">
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Test Name</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Status</th>
                  <th className="px-4 py-3 text-center text-xs font-medium text-gray-500 uppercase">Assertions</th>
                  <th className="px-4 py-3 text-center text-xs font-medium text-gray-500 uppercase">Judge</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Duration</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Tags</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Date</th>
                  <th className="px-4 py-3 text-center text-xs font-medium text-gray-500 uppercase w-12"></th>
                </tr>
              </thead>
              <tbody>
                {runs.length === 0 ? (
                  <tr>
                    <td colSpan={8} className="px-4 py-8 text-center text-gray-500">
                      No test runs found.{selectedTag ? ' Try clearing the tag filter.' : ' Run tests above to see results here.'}
                    </td>
                  </tr>
                ) : (
                  runs.map((run) => (
                    <tr
                      key={run.id}
                      onClick={() => onSelectRun(run.id)}
                      className="border-b border-gray-50 hover:bg-purple-50/50 cursor-pointer transition-colors"
                    >
                      <td className="px-4 py-3 font-medium">{run.test_name || '-'}</td>
                      <td className="px-4 py-3"><StatusBadge value={run.status} /></td>
                      <td className="px-4 py-3 text-center">
                        {run.assertions_total != null ? (
                          <span className={`font-mono text-xs font-medium ${
                            run.assertions_passed === run.assertions_total ? 'text-green-600' : 'text-red-600'
                          }`}>
                            {run.assertions_passed}/{run.assertions_total}
                          </span>
                        ) : (
                          <span className="text-gray-400">-</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-center">
                        {run.judge_checks_total != null ? (
                          <span className={`font-mono text-xs font-medium ${
                            run.judge_checks_passed === run.judge_checks_total ? 'text-green-600' : 'text-red-600'
                          }`}>
                            {run.judge_checks_passed}/{run.judge_checks_total}
                          </span>
                        ) : (
                          <span className="text-gray-400">-</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-gray-500 text-xs">
                        <span className="flex items-center gap-1">
                          <Clock className="w-3 h-3" />
                          {formatDuration(run.duration_ms)}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex flex-wrap gap-1">
                          {(run.tags || []).map((tag) => (
                            <span
                              key={tag}
                              className="inline-flex items-center gap-0.5 px-1.5 py-0.5 bg-purple-50 text-purple-700 rounded text-xs"
                            >
                              <Tag className="w-2.5 h-2.5" />
                              {tag}
                            </span>
                          ))}
                          {(!run.tags || run.tags.length === 0) && (
                            <span className="text-gray-400 text-xs">-</span>
                          )}
                        </div>
                      </td>
                      <td className="px-4 py-3 text-gray-500 text-xs">{formatDate(run.created_at)}</td>
                      <td className="px-4 py-3 text-center">
                        <button
                          onClick={(e) => { e.stopPropagation(); onRunSingle(run.test_name) }}
                          disabled={isRunning}
                          title="Re-run this test"
                          className="p-1 rounded hover:bg-indigo-100 text-gray-400 hover:text-indigo-600 disabled:opacity-30 transition-colors"
                        >
                          {runningSingle === run.test_name ? (
                            <Loader2 className="w-4 h-4 animate-spin" />
                          ) : (
                            <Play className="w-4 h-4" />
                          )}
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
      )}
    </div>
  )
}

// ---- Test Run Detail View ----

const TestRunDetail = ({ testRunId, onBack }) => {
  const [run, setRun] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    const fetch = async () => {
      setLoading(true)
      setError(null)
      try {
        const data = await getTestRun(testRunId)
        setRun(data)
      } catch (err) {
        setError(err.message)
      } finally {
        setLoading(false)
      }
    }
    fetch()
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

  const fields = [
    ['Test Name', run.test_name],
    ['Description', run.test_description],
    ['Status', run.status],
    ['Test User', run.test_user],
    ['HITL Profile', run.hitl_profile],
    ['Judge Profile', run.judge_profile],
    ['Sessions Seeded', run.sessions_seeded],
    ['Assertions', run.assertions_total != null ? `${run.assertions_passed}/${run.assertions_total}` : null],
    ['Judge Checks', run.judge_checks_total != null ? `${run.judge_checks_passed}/${run.judge_checks_total}` : null],
    ['Duration', formatDuration(run.duration_ms)],
    ['Benchmark Run ID', run.benchmark_run_id],
    ['Created', formatDate(run.created_at)],
  ]

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
          {run.assertions_total != null && (
            <div className="mt-2">
              <span className={`text-2xl font-bold font-mono ${
                run.assertions_passed === run.assertions_total ? 'text-green-600' : 'text-red-600'
              }`}>
                {run.assertions_passed}/{run.assertions_total}
              </span>
              <span className="text-xs text-gray-500 ml-1">assertions</span>
            </div>
          )}
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

      {/* Metadata table */}
      <div className="bg-white rounded-lg border overflow-hidden">
        <div className="px-4 py-3 border-b border-gray-100 bg-gray-50">
          <h3 className="font-semibold text-sm">Details</h3>
        </div>
        <table className="w-full text-sm">
          <tbody>
            {fields.map(([label, value]) => (
              <tr key={label} className="border-b last:border-0">
                <td className="px-4 py-2 font-medium text-gray-600 bg-gray-50 w-44">{label}</td>
                <td className="px-4 py-2 font-mono text-xs">{value !== null && value !== undefined ? String(value) : '-'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ===========================================================================
// MAIN COMPONENT
// ===========================================================================

export default function Evaluations() {
  const [view, setView] = useState('list')
  const [selectedTestRunId, setSelectedTestRunId] = useState(null)
  const [refreshKey, setRefreshKey] = useState(0)

  // Shared run state (lifted up so both sections can use it)
  const [runningAll, setRunningAll] = useState(false)
  const [runningTag, setRunningTag] = useState(null)
  const [runningSingle, setRunningSingle] = useState(null)
  const [runResult, setRunResult] = useState(null)
  const [runMessage, setRunMessage] = useState(null)
  const [phases, setPhases] = useState({ execute: true, judge: true })
  const [deletingUsers, setDeletingUsers] = useState(false)
  const [tags, setTags] = useState([])

  const isRunning = runningAll || runningTag || runningSingle

  const activePhaseLabels = [
    'Seed',
    phases.execute && 'Execute',
    phases.judge && 'Judge',
  ].filter(Boolean)
  const phaseDescription = activePhaseLabels.join(' \u2192 ')

  // Fetch tags for "Run by tag" buttons
  useEffect(() => {
    const fetchTags = async () => {
      try {
        const data = await getTags()
        setTags(data || [])
      } catch {
        // ignore
      }
    }
    fetchTags()
  }, [refreshKey])

  // Poll for background test run completion
  const pollRunStatus = (runId, clearRunning) => {
    const pollInterval = setInterval(async () => {
      try {
        const status = await getRunStatus(runId)
        if (status.status === 'completed') {
          clearInterval(pollInterval)
          clearRunning()
          setRunMessage(null)
          setRunResult(status.results)
          setRefreshKey((k) => k + 1)
        } else if (status.status === 'error') {
          clearInterval(pollInterval)
          clearRunning()
          setRunMessage(null)
          alert('Test run failed: ' + status.message)
        } else {
          setRunMessage(status.message || 'Running tests...')
        }
      } catch {
        clearInterval(pollInterval)
        clearRunning()
        setRunMessage(null)
        alert('Failed to check test run status')
      }
    }, 2000)
  }

  const handleRunAllTests = async () => {
    setRunningAll(true)
    setRunResult(null)
    setRunMessage('Starting tests...')
    try {
      const { run_id } = await runTests({ run_all: true, ...phases })
      pollRunStatus(run_id, () => setRunningAll(false))
    } catch (err) {
      setRunningAll(false)
      setRunMessage(null)
      alert('Failed to run tests: ' + err.message)
    }
  }

  const handleRunByTag = async (tag) => {
    setRunningTag(tag)
    setRunResult(null)
    setRunMessage('Starting tests...')
    try {
      const { run_id } = await runTests({ tag, ...phases })
      pollRunStatus(run_id, () => setRunningTag(null))
    } catch (err) {
      setRunningTag(null)
      setRunMessage(null)
      alert('Failed to run tests: ' + err.message)
    }
  }

  const handleRunSingle = async (testName) => {
    setRunningSingle(testName)
    setRunResult(null)
    setRunMessage('Starting tests...')
    try {
      const { run_id } = await runTests({ test_name: testName, ...phases })
      pollRunStatus(run_id, () => setRunningSingle(null))
    } catch (err) {
      setRunningSingle(null)
      setRunMessage(null)
      alert('Failed to run test: ' + err.message)
    }
  }

  const handleDeleteTestUsers = async () => {
    if (!window.confirm('Delete ALL test users (t-*) and their sessions, projects, and data? This cannot be undone.')) return
    setDeletingUsers(true)
    try {
      const result = await deleteTestUsers()
      alert(result.message || 'Test users deleted.')
      setRefreshKey((k) => k + 1)
    } catch (err) {
      alert('Failed to delete test users: ' + err.message)
    } finally {
      setDeletingUsers(false)
    }
  }

  const handleSelectTestRun = (testRunId) => {
    setSelectedTestRunId(testRunId)
    setView('detail')
  }

  const handleBackToList = () => {
    setView('list')
    setSelectedTestRunId(null)
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          {view !== 'list' && (
            <button
              onClick={handleBackToList}
              className="flex items-center gap-1 px-3 py-1.5 text-sm bg-gray-100 hover:bg-gray-200 rounded transition-colors"
            >
              <ArrowLeft className="w-4 h-4" />
              Back
            </button>
          )}
          <FlaskConical className="w-6 h-6 text-purple-600" />
          <h1 className="text-2xl font-bold">{view === 'detail' ? 'Test Run Detail' : 'Tests'}</h1>
        </div>
        {view === 'list' && (
          <button
            onClick={() => setRefreshKey((k) => k + 1)}
            className="p-2 hover:bg-gray-200 rounded transition-colors"
            title="Refresh"
          >
            <RefreshCw className="w-4 h-4" />
          </button>
        )}
      </div>

      {/* Content */}
      {view === 'list' && (
        <div className="space-y-6">
          {/* ============ SECTION 1: Available Tests ============ */}
          <div className="bg-white rounded-lg border overflow-hidden">
            <div className="px-4 py-3 border-b border-gray-100 bg-gray-50 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <FileText className="w-4 h-4 text-purple-600" />
                <h2 className="font-semibold text-sm">Available Tests</h2>
              </div>
            </div>

            <AvailableTests
              onRunSingle={handleRunSingle}
              isRunning={isRunning}
              runningSingle={runningSingle}
            />

            {/* Controls bar */}
            <div className="px-4 py-3 border-t border-gray-100 bg-gray-50 space-y-3">
              {/* Phase toggles */}
              <div className="flex items-center gap-6">
                <span className="text-xs font-medium text-gray-500 uppercase">Phases:</span>
                <label className="flex items-center gap-1.5 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={phases.execute}
                    onChange={e => setPhases(p => ({ ...p, execute: e.target.checked }))}
                    className="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500 w-3.5 h-3.5"
                  />
                  <span className="text-xs">Execute Agents</span>
                </label>
                <label className="flex items-center gap-1.5 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={phases.judge}
                    onChange={e => setPhases(p => ({ ...p, judge: e.target.checked }))}
                    className="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500 w-3.5 h-3.5"
                  />
                  <span className="text-xs">LLM Judge</span>
                </label>
              </div>

              {/* Action buttons */}
              <div className="flex items-center justify-between flex-wrap gap-2">
                <div className="flex items-center gap-2">
                  <button
                    onClick={handleRunAllTests}
                    disabled={isRunning}
                    className="flex items-center gap-1.5 px-3 py-1.5 bg-green-600 text-white rounded text-xs font-medium hover:bg-green-700 disabled:opacity-50 transition-colors"
                  >
                    {runningAll ? (
                      <Loader2 className="w-3.5 h-3.5 animate-spin" />
                    ) : (
                      <Play className="w-3.5 h-3.5" />
                    )}
                    {runningAll ? 'Running...' : 'Run All Tests'}
                  </button>

                  {tags.length > 0 && tags.map((t) => (
                    <button
                      key={t.tag}
                      onClick={() => handleRunByTag(t.tag)}
                      disabled={isRunning}
                      className="inline-flex items-center gap-1 px-2 py-1.5 bg-purple-50 text-purple-700 rounded text-xs font-medium hover:bg-purple-100 border border-purple-200 disabled:opacity-50 transition-colors"
                    >
                      {runningTag === t.tag ? (
                        <Loader2 className="w-3 h-3 animate-spin" />
                      ) : (
                        <Play className="w-3 h-3" />
                      )}
                      {t.tag}
                    </button>
                  ))}
                </div>

                <button
                  onClick={handleDeleteTestUsers}
                  disabled={deletingUsers || isRunning}
                  className="flex items-center gap-1 px-2 py-1.5 bg-red-50 text-red-600 rounded text-xs hover:bg-red-100 border border-red-200 disabled:opacity-50 transition-colors"
                >
                  {deletingUsers ? <Loader2 className="w-3 h-3 animate-spin" /> : <Trash2 className="w-3 h-3" />}
                  Delete Test Users
                </button>
              </div>
            </div>
          </div>

          {/* Running spinner */}
          {isRunning && (
            <div className="flex items-center gap-3 px-4 py-3 bg-blue-50 border border-blue-200 rounded-lg">
              <Loader2 className="w-5 h-5 animate-spin text-blue-600" />
              <span className="text-blue-800 font-medium text-sm">
                {runMessage || `Running${runningSingle ? ` "${runningSingle}"` : ' tests'}...`} ({phaseDescription})
              </span>
            </div>
          )}

          {/* ============ SECTION 2: Test Results ============ */}
          <div className="bg-white rounded-lg border overflow-hidden">
            <div className="px-4 py-3 border-b border-gray-100 bg-gray-50 flex items-center gap-2">
              <Clock className="w-4 h-4 text-gray-500" />
              <h2 className="font-semibold text-sm">Test Results (past runs)</h2>
            </div>

            <div className="p-3">
              <TestRunsList
                key={refreshKey}
                refreshKey={refreshKey}
                onSelectRun={handleSelectTestRun}
                onRunSingle={handleRunSingle}
                isRunning={isRunning}
                runningSingle={runningSingle}
                runResult={runResult}
                setRunResult={setRunResult}
                runMessage={runMessage}
              />
            </div>
          </div>
        </div>
      )}
      {view === 'detail' && (
        <TestRunDetail testRunId={selectedTestRunId} onBack={handleBackToList} />
      )}
    </div>
  )
}
