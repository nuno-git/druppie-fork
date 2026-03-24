/**
 * Admin Tests Page
 *
 * Two-section layout:
 * 1. Run Tests -- full-screen modal selector for choosing tests, phase toggles, run button
 * 2. Test Results -- past test runs grouped by batch with expandable detail
 */

import { useState, useEffect, useRef } from 'react'
import { Link } from 'react-router-dom'
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
  ChevronDown,
  ChevronUp,
  RefreshCw,
  Tag,
  Clock,
  Filter,
  MessageSquare,
  X,
  Info,
  BarChart3,
} from 'lucide-react'
import {
  getAvailableTests,
  getTestBatches,
  getTestRun,
  getTestRunAssertions,
  getTags,
  deleteTestUsers,
  runTests,
  getRunStatus,
  runUnitTests,
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

// ---- Full-screen Test Selector Modal ----

const TestSelectorModal = ({
  tests,
  loading,
  error,
  selectAll,
  setSelectAll,
  selectedTests,
  setSelectedTests,
  modeFilter,
  setModeFilter,
  onRun,
  onClose,
  isRunning,
}) => {
  const [expandedTests, setExpandedTests] = useState(new Set())

  const toggleTest = (name) => {
    const next = new Set(selectedTests)
    if (next.has(name)) {
      next.delete(name)
    } else {
      next.add(name)
    }
    if (next.size === tests.length) {
      setSelectAll(true)
      setSelectedTests(new Set())
    } else {
      setSelectAll(false)
      setSelectedTests(next)
    }
  }

  const toggleAll = () => {
    if (selectAll) {
      setSelectAll(false)
      setSelectedTests(new Set())
    } else {
      setSelectAll(true)
      setSelectedTests(new Set())
    }
  }

  const toggleExpanded = (name) => {
    const next = new Set(expandedTests)
    if (next.has(name)) {
      next.delete(name)
    } else {
      next.add(name)
    }
    setExpandedTests(next)
  }

  const effectiveCount = selectAll ? tests.length : selectedTests.size
  const canRun = !isRunning && effectiveCount > 0 && !loading && !error

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-3xl max-h-[90vh] flex flex-col mx-4">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200">
          <h2 className="text-lg font-bold flex items-center gap-2">
            <FlaskConical className="w-5 h-5 text-purple-600" />
            Select Tests
          </h2>
          <button
            onClick={onClose}
            className="p-1 hover:bg-gray-100 rounded transition-colors"
          >
            <X className="w-5 h-5 text-gray-500" />
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto px-6 py-4 space-y-3">
          {loading && (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="w-6 h-6 animate-spin text-blue-500" />
              <span className="ml-2 text-gray-600">Loading tests...</span>
            </div>
          )}

          {error && (
            <div className="text-center py-12 text-red-500">
              <AlertCircle className="w-8 h-8 mx-auto mb-2" />
              <p>{error}</p>
            </div>
          )}

          {!loading && !error && (
            <>
              {/* Select All */}
              <label className="flex items-center gap-3 px-4 py-3 bg-gray-50 rounded-lg cursor-pointer hover:bg-gray-100 transition-colors">
                <input
                  type="checkbox"
                  checked={selectAll}
                  onChange={toggleAll}
                  className="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500 w-4 h-4"
                />
                <span className="font-semibold text-sm">Select All ({tests.length} tests)</span>
              </label>

              {/* Individual tests */}
              {tests.filter((t) => modeFilter === 'all' || t.mode === modeFilter).map((test) => {
                const checked = selectAll || selectedTests.has(test.name)
                const expanded = expandedTests.has(test.name)
                const modeBg = {
                  live: 'bg-blue-100 text-blue-700',
                  replay: 'bg-amber-100 text-amber-700',
                  record_only: 'bg-gray-200 text-gray-700',
                }[test.mode] || 'bg-gray-100 text-gray-600'
                return (
                  <div
                    key={test.name}
                    className="border rounded-lg overflow-hidden"
                  >
                    <div className="flex items-start gap-3 px-4 py-3 hover:bg-gray-50 transition-colors">
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => toggleTest(test.name)}
                        className="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500 w-4 h-4 mt-0.5 flex-shrink-0"
                      />
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-2">
                            <span className={`px-1.5 py-0.5 rounded text-[10px] font-semibold uppercase ${modeBg}`}>
                              {test.mode === 'record_only' ? 'record' : test.mode}
                            </span>
                            <span className="font-medium text-sm">{test.name}</span>
                          </div>
                          <button
                            onClick={() => toggleExpanded(test.name)}
                            className="flex items-center gap-1 text-xs text-gray-500 hover:text-gray-700 ml-2 flex-shrink-0"
                          >
                            {expanded ? (
                              <>
                                <ChevronUp className="w-3 h-3" />
                                hide
                              </>
                            ) : (
                              <>
                                <Info className="w-3 h-3" />
                                details
                              </>
                            )}
                          </button>
                        </div>
                        {test.message && (
                          <p className="text-xs text-gray-500 mt-0.5 italic">
                            &quot;{test.message}&quot;
                          </p>
                        )}
                        <div className="flex items-center gap-3 mt-1 text-xs text-gray-500">
                          <span>
                            Agents: {test.real_agents?.join(', ') || 'all'}
                          </span>
                          {test.sessions?.length > 0 && (
                            <span>
                              Sessions: {test.sessions.join(', ')}
                            </span>
                          )}
                          {test.sessions?.length === 0 && (
                            <span>Sessions: (none)</span>
                          )}
                        </div>

                        {/* Expanded details */}
                        {expanded && (
                          <div className="mt-3 pt-3 border-t border-gray-100 space-y-2">
                            {test.evals && test.evals.length > 0 && (
                              <div>
                                <span className="text-xs font-semibold text-gray-600 uppercase">Evals:</span>
                                {test.evals.map((ev, idx) => (
                                  <div key={idx} className="ml-3 mt-1">
                                    <span className="text-xs font-medium text-purple-700">{ev.name}</span>
                                    {ev.expected && Object.keys(ev.expected).length > 0 && (
                                      <div className="ml-3 text-xs text-gray-500">
                                        Expected: {Object.entries(ev.expected).map(([k, v]) => (
                                          <span key={k} className="inline-flex items-center gap-0.5 mr-2">
                                            <span className="font-mono">{k}</span>=<span className="font-mono text-gray-700">{typeof v === 'string' ? v : JSON.stringify(v)}</span>
                                          </span>
                                        ))}
                                      </div>
                                    )}
                                  </div>
                                ))}
                              </div>
                            )}
                            <div className="flex items-center gap-4 text-xs text-gray-500">
                              <span>HITL: <span className="font-medium text-gray-700">{test.hitl || 'default'}</span></span>
                              <span>Judge: <span className="font-medium text-gray-700">{test.judge || 'default'}</span></span>
                            </div>
                            {test.description && (
                              <p className="text-xs text-gray-500">{test.description}</p>
                            )}
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                )
              })}
            </>
          )}
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t border-gray-200 flex items-center justify-between">
          <div className="flex items-center gap-1">
            {['all', 'live', 'record_only', 'replay'].map((m) => (
              <button
                key={m}
                onClick={() => setModeFilter(m)}
                className={`px-3 py-1.5 rounded-full text-xs font-medium transition-colors ${
                  modeFilter === m
                    ? 'bg-indigo-600 text-white'
                    : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                }`}
              >
                {m === 'all' ? 'All' : m === 'record_only' ? 'Record Only' : m === 'live' ? 'Live' : 'Replay'}
              </button>
            ))}
          </div>
          <div className="flex items-center gap-3">
            <span className="text-sm text-gray-500">
              {effectiveCount} test{effectiveCount !== 1 ? 's' : ''} selected
            </span>
            <button
              onClick={() => { onRun(); onClose() }}
              disabled={!canRun}
              className="flex items-center gap-1.5 px-5 py-2 bg-green-600 text-white rounded-lg text-sm font-medium hover:bg-green-700 disabled:opacity-50 transition-colors"
            >
              {isRunning ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <Play className="w-4 h-4" />
              )}
              Run
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

// ---- Batch Results List ----

const BatchResultsList = ({ refreshKey, onSelectRun, isRunning, runResult, setRunResult }) => {
  const [batches, setBatches] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [page, setPage] = useState(1)
  const [totalPages, setTotalPages] = useState(1)
  const [tags, setTags] = useState([])
  const [selectedTag, setSelectedTag] = useState(null)
  const [expandedBatches, setExpandedBatches] = useState(new Set())

  const fetchTags = async () => {
    try {
      const data = await getTags()
      setTags(data || [])
    } catch {
      // Tags are optional
    }
  }

  const fetchBatches = async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await getTestBatches(page, 10, selectedTag)
      setBatches(data.items || [])
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
    fetchBatches()
  }, [page, selectedTag, refreshKey])

  const toggleBatch = (batchId) => {
    const next = new Set(expandedBatches)
    if (next.has(batchId)) {
      next.delete(batchId)
    } else {
      next.add(batchId)
    }
    setExpandedBatches(next)
  }

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
          <span className="ml-2 text-gray-600">Loading test results...</span>
        </div>
      )}

      {/* Error state */}
      {error && !loading && (
        <div className="p-8 text-center text-red-500">
          <AlertCircle className="w-8 h-8 mx-auto mb-2" />
          <p>{error}</p>
          <button onClick={fetchBatches} className="mt-2 px-4 py-2 bg-blue-500 text-white rounded text-sm">
            Retry
          </button>
        </div>
      )}

      {/* Batch list */}
      {!loading && !error && (
        <div className="space-y-2">
          {batches.length === 0 ? (
            <div className="bg-white rounded-lg border p-8 text-center text-gray-500">
              No test runs found.{selectedTag ? ' Try clearing the tag filter.' : ' Run tests above to see results here.'}
            </div>
          ) : (
            batches.map((batch) => {
              const expanded = expandedBatches.has(batch.batch_id)
              const allPassed = batch.passed === batch.test_count
              const borderColor = allPassed ? 'border-green-200' : 'border-red-200'
              const headerBg = allPassed ? 'bg-green-50' : 'bg-red-50'
              const Icon = allPassed ? CheckCircle2 : XCircle

              return (
                <div key={batch.batch_id} className={`bg-white rounded-lg border ${borderColor} overflow-hidden`}>
                  {/* Batch header */}
                  <button
                    onClick={() => toggleBatch(batch.batch_id)}
                    className={`w-full flex items-center justify-between px-4 py-3 ${headerBg} hover:opacity-90 transition-colors`}
                  >
                    <div className="flex items-center gap-3">
                      <Icon className={`w-5 h-5 ${allPassed ? 'text-green-600' : 'text-red-600'}`} />
                      <span className="font-medium text-sm">
                        {batch.test_count === 1
                          ? batch.runs[0]?.test_name || 'Test Run'
                          : `${batch.test_count} tests`
                        }
                      </span>
                      <span className={`font-mono text-xs font-semibold ${allPassed ? 'text-green-700' : 'text-red-700'}`}>
                        {batch.passed}/{batch.test_count} passed
                      </span>
                    </div>
                    <div className="flex items-center gap-3">
                      <Link
                        to={`/admin/tests/batch/${batch.batch_id}`}
                        onClick={(e) => e.stopPropagation()}
                        className="flex items-center gap-1 text-xs text-indigo-600 hover:text-indigo-800 hover:underline"
                      >
                        <BarChart3 className="w-3 h-3" />
                        Detail
                      </Link>
                      <span className="text-xs text-gray-500 flex items-center gap-1">
                        <Clock className="w-3 h-3" />
                        {formatDuration(batch.total_duration_ms)}
                      </span>
                      <span className="text-xs text-gray-500">
                        {formatDate(batch.started_at)}
                      </span>
                      {expanded ? (
                        <ChevronUp className="w-4 h-4 text-gray-400" />
                      ) : (
                        <ChevronDown className="w-4 h-4 text-gray-400" />
                      )}
                    </div>
                  </button>

                  {/* Expanded: individual test runs */}
                  {expanded && (
                    <div className="border-t border-gray-100">
                      <table className="w-full text-sm">
                        <thead className="bg-gray-50 border-b border-gray-100">
                          <tr>
                            <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Test Name</th>
                            <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Status</th>
                            <th className="px-4 py-2 text-center text-xs font-medium text-gray-500 uppercase">Assertions</th>
                            <th className="px-4 py-2 text-center text-xs font-medium text-gray-500 uppercase">Judge</th>
                            <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Duration</th>
                            <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 uppercase">Tags</th>
                          </tr>
                        </thead>
                        <tbody>
                          {batch.runs.map((run) => (
                            <tr
                              key={run.id}
                              onClick={() => onSelectRun(run.id)}
                              className="border-b border-gray-50 hover:bg-purple-50/50 cursor-pointer transition-colors"
                            >
                              <td className="px-4 py-2.5 font-medium">{run.test_name || '-'}</td>
                              <td className="px-4 py-2.5"><StatusBadge value={run.status} /></td>
                              <td className="px-4 py-2.5 text-center">
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
                              <td className="px-4 py-2.5 text-center">
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
                              <td className="px-4 py-2.5 text-gray-500 text-xs">
                                <span className="flex items-center gap-1">
                                  <Clock className="w-3 h-3" />
                                  {formatDuration(run.duration_ms)}
                                </span>
                              </td>
                              <td className="px-4 py-2.5">
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
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              )
            })
          )}

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="flex items-center justify-between px-4 py-3">
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
  const [assertionResults, setAssertionResults] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    const fetchData = async () => {
      setLoading(true)
      setError(null)
      try {
        const [data, assertions] = await Promise.all([
          getTestRun(testRunId),
          getTestRunAssertions(testRunId).catch(() => []),
        ])
        setRun(data)
        setAssertionResults(assertions || [])
      } catch (err) {
        setError(err.message)
      } finally {
        setLoading(false)
      }
    }
    fetchData()
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

  const modeLabel = run.mode || 'live'
  const modeBg = {
    live: 'bg-blue-100 text-blue-700',
    replay: 'bg-amber-100 text-amber-700',
    record_only: 'bg-gray-100 text-gray-700',
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
        <div className="bg-white rounded-lg border overflow-hidden">
          <div className="px-4 py-3 border-b border-gray-100 bg-gray-50">
            <h3 className="font-semibold text-sm">Judge Checks ({judgeChecks.filter(j => j.passed).length}/{judgeChecks.length} passed)</h3>
          </div>
          <div className="divide-y">
            {judgeChecks.map((jr, i) => (
              <div key={i} className="px-4 py-3 flex items-start gap-3">
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
                    <p className="text-sm text-gray-400 mt-1 italic">{jr.judge_reasoning}</p>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
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

// ---- Unit Tests Section ----

const UnitTestsSection = () => {
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [expandedFiles, setExpandedFiles] = useState(new Set())

  const handleRun = async () => {
    setLoading(true)
    setError(null)
    setResult(null)
    try {
      const data = await runUnitTests()
      setResult(data)
      // Auto-expand files with failures
      if (data.tests) {
        const failedFiles = new Set()
        data.tests.forEach((t) => {
          if (t.status === 'failed' || t.status === 'error') {
            const file = t.name.split('::')[0]
            failedFiles.add(file)
          }
        })
        setExpandedFiles(failedFiles)
      }
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  // Group tests by file
  const groupedTests = {}
  if (result?.tests) {
    result.tests.forEach((t) => {
      const parts = t.name.split('::')
      const file = parts[0] || t.name
      if (!groupedTests[file]) groupedTests[file] = []
      groupedTests[file].push({ ...t, shortName: parts.slice(1).join('::') || t.name })
    })
  }

  const toggleFile = (file) => {
    const next = new Set(expandedFiles)
    if (next.has(file)) {
      next.delete(file)
    } else {
      next.add(file)
    }
    setExpandedFiles(next)
  }

  const fileStatusColors = {
    allPass: 'text-green-600',
    hasFail: 'text-red-600',
  }

  return (
    <div className="bg-white rounded-lg border overflow-hidden">
      <div className="px-4 py-3 border-b border-gray-100 bg-gray-50 flex items-center justify-between rounded-t-lg">
        <div className="flex items-center gap-2">
          <FlaskConical className="w-4 h-4 text-blue-600" />
          <h2 className="font-semibold text-sm">Unit Tests (Framework)</h2>
        </div>
        <button
          onClick={handleRun}
          disabled={loading}
          className="flex items-center gap-1.5 px-3 py-1.5 bg-blue-600 text-white rounded-lg text-xs font-medium hover:bg-blue-700 disabled:opacity-50 transition-colors"
        >
          {loading ? (
            <Loader2 className="w-3.5 h-3.5 animate-spin" />
          ) : (
            <Play className="w-3.5 h-3.5" />
          )}
          {loading ? 'Running...' : 'Run'}
        </button>
      </div>

      <div className="p-4">
        {/* Loading state */}
        {loading && (
          <div className="flex items-center gap-3 py-6 justify-center">
            <Loader2 className="w-5 h-5 animate-spin text-blue-500" />
            <span className="text-sm text-gray-600">Running pytest...</span>
          </div>
        )}

        {/* Error state */}
        {error && !loading && (
          <div className="text-center py-4 text-red-500">
            <AlertCircle className="w-6 h-6 mx-auto mb-1" />
            <p className="text-sm">{error}</p>
          </div>
        )}

        {/* Results */}
        {result && !loading && (
          <div className="space-y-3">
            {/* Summary bar */}
            <div className={`flex items-center justify-between px-4 py-3 rounded-lg border ${
              result.status === 'passed' ? 'bg-green-50 border-green-200' : 'bg-red-50 border-red-200'
            }`}>
              <div className="flex items-center gap-3">
                {result.status === 'passed' ? (
                  <CheckCircle2 className="w-5 h-5 text-green-600" />
                ) : (
                  <XCircle className="w-5 h-5 text-red-600" />
                )}
                <span className={`font-medium text-sm ${
                  result.status === 'passed' ? 'text-green-800' : 'text-red-800'
                }`}>
                  {result.summary || `${result.passed} passed, ${result.failed} failed, ${result.skipped} skipped`}
                </span>
              </div>
              <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${
                result.status === 'passed'
                  ? 'bg-green-100 text-green-700'
                  : result.status === 'failed'
                    ? 'bg-red-100 text-red-700'
                    : 'bg-orange-100 text-orange-700'
              }`}>
                {result.status}
              </span>
            </div>

            {/* Grouped test list */}
            {Object.keys(groupedTests).length > 0 && (
              <div className="space-y-1">
                {Object.entries(groupedTests).map(([file, tests]) => {
                  const allPass = tests.every((t) => t.status === 'passed' || t.status === 'skipped')
                  const failCount = tests.filter((t) => t.status === 'failed' || t.status === 'error').length
                  const expanded = expandedFiles.has(file)
                  const fileName = file.split('/').pop()

                  return (
                    <div key={file} className="border rounded-lg overflow-hidden">
                      <button
                        onClick={() => toggleFile(file)}
                        className="w-full flex items-center justify-between px-3 py-2 hover:bg-gray-50 transition-colors text-left"
                      >
                        <div className="flex items-center gap-2">
                          {expanded ? (
                            <ChevronDown className="w-3.5 h-3.5 text-gray-400" />
                          ) : (
                            <ChevronRight className="w-3.5 h-3.5 text-gray-400" />
                          )}
                          <span className="text-sm font-medium">{fileName}</span>
                          <span className="text-xs text-gray-400">({tests.length} tests)</span>
                        </div>
                        <span className={`text-xs font-medium ${allPass ? fileStatusColors.allPass : fileStatusColors.hasFail}`}>
                          {allPass ? 'all pass' : `${failCount} failed`}
                        </span>
                      </button>

                      {expanded && (
                        <div className="border-t border-gray-100 bg-gray-50/50">
                          {tests.map((test, idx) => (
                            <div
                              key={idx}
                              className="flex items-center justify-between px-4 py-1.5 text-xs border-b border-gray-100 last:border-0"
                            >
                              <span className="font-mono text-gray-700 truncate mr-2">{test.shortName}</span>
                              <span className={`px-1.5 py-0.5 rounded text-xs font-medium flex-shrink-0 ${
                                test.status === 'passed' ? 'bg-green-100 text-green-700' :
                                test.status === 'failed' ? 'bg-red-100 text-red-700' :
                                test.status === 'skipped' ? 'bg-yellow-100 text-yellow-700' :
                                'bg-orange-100 text-orange-700'
                              }`}>
                                {test.status}
                              </span>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            )}

            {/* Error output for failures */}
            {result.errors && (
              <details className="mt-2">
                <summary className="text-xs text-red-600 cursor-pointer font-medium">Error Output</summary>
                <pre className="mt-1 p-3 bg-red-50 border border-red-200 rounded text-xs text-red-800 overflow-x-auto whitespace-pre-wrap max-h-60 overflow-y-auto">
                  {result.errors}
                </pre>
              </details>
            )}
          </div>
        )}

        {/* Empty state */}
        {!result && !loading && !error && (
          <p className="text-sm text-gray-400 text-center py-4">
            Click Run to execute pytest unit tests.
          </p>
        )}
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

  // Available tests (loaded once)
  const [availableTests, setAvailableTests] = useState([])
  const [testsLoading, setTestsLoading] = useState(true)
  const [testsError, setTestsError] = useState(null)

  // Test selector modal state
  const [showSelector, setShowSelector] = useState(false)
  const [selectAll, setSelectAll] = useState(true)
  const [selectedTests, setSelectedTests] = useState(new Set())

  // Shared run state
  const [isRunning, setIsRunning] = useState(false)
  const [runResult, setRunResult] = useState(null)
  const [runMessage, setRunMessage] = useState(null)
  const [modeFilter, setModeFilter] = useState('all') // all, live, record_only, replay
  const [deletingUsers, setDeletingUsers] = useState(false)

  // Effective selected count for display
  const effectiveCount = selectAll ? availableTests.length : selectedTests.size

  // Load available tests
  useEffect(() => {
    const fetch = async () => {
      setTestsLoading(true)
      setTestsError(null)
      try {
        const data = await getAvailableTests()
        setAvailableTests(data || [])
      } catch (err) {
        setTestsError(err.message)
      } finally {
        setTestsLoading(false)
      }
    }
    fetch()
  }, [])

  const [runProgress, setRunProgress] = useState(null) // {current_test, completed_tests, total_tests}

  // Poll for background test run completion
  const pollRunStatus = (runId) => {
    const pollInterval = setInterval(async () => {
      try {
        const status = await getRunStatus(runId)
        if (status.status === 'completed') {
          clearInterval(pollInterval)
          setIsRunning(false)
          setRunMessage(null)
          setRunProgress(null)
          setRunResult(status.results)
          setRefreshKey((k) => k + 1)
        } else if (status.status === 'error') {
          clearInterval(pollInterval)
          setIsRunning(false)
          setRunMessage(null)
          setRunProgress(null)
          alert('Test run failed: ' + status.message)
        } else {
          setRunMessage(status.message || 'Running tests...')
          setRunProgress({
            current_test: status.current_test,
            completed_tests: status.completed_tests || [],
            total_tests: status.total_tests || 0,
          })
        }
      } catch {
        clearInterval(pollInterval)
        setIsRunning(false)
        setRunMessage(null)
        setRunProgress(null)
        alert('Failed to check test run status')
      }
    }, 1500)
  }

  const handleRun = async () => {
    if (isRunning) return
    if (effectiveCount === 0) return

    setIsRunning(true)
    setRunResult(null)
    setRunMessage('Starting tests...')

    try {
      const options = { execute: true, judge: true }

      if (selectAll) {
        options.run_all = true
      } else if (selectedTests.size === 1) {
        options.test_name = [...selectedTests][0]
      } else {
        options.test_names = [...selectedTests]
      }

      const response = await runTests(options)
      const { run_id } = response
      pollRunStatus(run_id)
    } catch (err) {
      setIsRunning(false)
      setRunMessage(null)
      setRunProgress(null)
      const msg = err.status === 409
        ? 'A test run is already in progress. Please wait for it to finish.'
        : 'Failed to run tests: ' + err.message
      alert(msg)
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

  // Build a description of what will run
  const runDescription = selectAll
    ? 'all tests'
    : selectedTests.size === 1
      ? `"${[...selectedTests][0]}"`
      : `${selectedTests.size} tests`

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
        <div className="flex items-center gap-2">
          {view === 'list' && (
            <Link
              to="/admin/tests/analytics"
              className="flex items-center gap-1.5 px-3 py-1.5 text-sm bg-indigo-50 text-indigo-700 border border-indigo-200 rounded-lg hover:bg-indigo-100 transition-colors"
            >
              <BarChart3 className="w-4 h-4" />
              Analytics
            </Link>
          )}
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
      </div>

      {/* Content */}
      {view === 'list' && (
        <div className="space-y-6">
          {/* ============ SECTION 1: Run Tests ============ */}
          <div className="bg-white rounded-lg border overflow-visible">
            <div className="px-4 py-3 border-b border-gray-100 bg-gray-50 flex items-center justify-between rounded-t-lg">
              <div className="flex items-center gap-2">
                <Play className="w-4 h-4 text-purple-600" />
                <h2 className="font-semibold text-sm">Run Tests</h2>
              </div>
              <button
                onClick={handleDeleteTestUsers}
                disabled={deletingUsers || isRunning}
                className="flex items-center gap-1 px-2 py-1 bg-red-50 text-red-600 rounded text-xs hover:bg-red-100 border border-red-200 disabled:opacity-50 transition-colors"
              >
                {deletingUsers ? <Loader2 className="w-3 h-3 animate-spin" /> : <Trash2 className="w-3 h-3" />}
                Delete Test Users
              </button>
            </div>

            <div className="px-4 py-4">
              <div className="flex items-center gap-4">
                {/* Select tests button */}
                <button
                  onClick={() => setShowSelector(true)}
                  disabled={isRunning}
                  className="flex items-center gap-2 px-4 py-2 bg-purple-50 text-purple-700 border border-purple-200 rounded-lg text-sm font-medium hover:bg-purple-100 disabled:opacity-50 transition-colors"
                >
                  <FlaskConical className="w-4 h-4" />
                  {testsLoading ? 'Loading...' : testsError ? 'Error' : selectAll ? `All tests (${availableTests.length})` : `${selectedTests.size} test${selectedTests.size !== 1 ? 's' : ''} selected`}
                  <ChevronDown className="w-4 h-4" />
                </button>

                {/* Mode filter indicator */}
                <div className="flex items-center gap-1 text-xs">
                  {['all', 'live', 'record_only', 'replay'].map((m) => (
                    <span key={m} className={`px-2 py-1 rounded ${
                      modeFilter === m ? 'bg-indigo-100 text-indigo-700 font-medium' : 'bg-gray-100 text-gray-400'
                    }`}>
                      {m === 'all' ? 'All' : m === 'record_only' ? 'Record' : m === 'live' ? 'Live' : 'Replay'}
                    </span>
                  ))}
                </div>

                {/* Run button */}
                <button
                  onClick={handleRun}
                  disabled={isRunning || effectiveCount === 0}
                  className="flex items-center gap-1.5 px-4 py-2 bg-green-600 text-white rounded-lg text-sm font-medium hover:bg-green-700 disabled:opacity-50 transition-colors ml-auto"
                >
                  {isRunning ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : (
                    <Play className="w-4 h-4" />
                  )}
                  {isRunning ? 'Running...' : 'Run'}
                </button>
              </div>
            </div>
          </div>

          {/* Running progress */}
          {isRunning && (
            <div className="bg-blue-50 border border-blue-200 rounded-lg overflow-hidden">
              <div className="flex items-center gap-3 px-4 py-3">
                <Loader2 className="w-5 h-5 animate-spin text-blue-600 shrink-0" />
                <div className="flex-1 min-w-0">
                  <span className="text-blue-800 font-medium text-sm">
                    {runMessage || 'Starting tests...'}
                  </span>
                  {runProgress && runProgress.total_tests > 0 && (
                    <div className="w-full bg-blue-200 rounded-full h-1.5 mt-2">
                      <div
                        className="bg-blue-600 h-1.5 rounded-full transition-all duration-300"
                        style={{ width: `${(runProgress.completed_tests.length / runProgress.total_tests) * 100}%` }}
                      />
                    </div>
                  )}
                </div>
              </div>
              {/* Completed tests so far */}
              {runProgress && runProgress.completed_tests.length > 0 && (
                <div className="border-t border-blue-200 px-4 py-2 space-y-1">
                  {runProgress.completed_tests.map((t, i) => (
                    <div key={i} className="flex items-center gap-2 text-xs">
                      {t.status === 'passed' ? (
                        <CheckCircle2 className="w-3.5 h-3.5 text-green-500" />
                      ) : (
                        <XCircle className="w-3.5 h-3.5 text-red-500" />
                      )}
                      <span className="text-gray-700">{t.test_name}</span>
                      <span className="text-gray-400">{formatDuration(t.duration_ms)}</span>
                    </div>
                  ))}
                  {runProgress.current_test && (
                    <div className="flex items-center gap-2 text-xs">
                      <Loader2 className="w-3.5 h-3.5 animate-spin text-blue-500" />
                      <span className="text-blue-700 font-medium">{runProgress.current_test}</span>
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

          {/* ============ SECTION 2: Test Results (grouped by batch) ============ */}
          <div className="bg-white rounded-lg border overflow-hidden">
            <div className="px-4 py-3 border-b border-gray-100 bg-gray-50 flex items-center gap-2">
              <Clock className="w-4 h-4 text-gray-500" />
              <h2 className="font-semibold text-sm">Test Results</h2>
            </div>

            <div className="p-3">
              <BatchResultsList
                key={refreshKey}
                refreshKey={refreshKey}
                onSelectRun={handleSelectTestRun}
                isRunning={isRunning}
                runResult={runResult}
                setRunResult={setRunResult}
              />
            </div>
          </div>

          {/* ============ SECTION 3: Unit Tests ============ */}
          <UnitTestsSection />
        </div>
      )}
      {view === 'detail' && (
        <TestRunDetail testRunId={selectedTestRunId} onBack={handleBackToList} />
      )}

      {/* Full-screen test selector modal */}
      {showSelector && (
        <TestSelectorModal
          tests={availableTests}
          loading={testsLoading}
          error={testsError}
          selectAll={selectAll}
          setSelectAll={setSelectAll}
          selectedTests={selectedTests}
          setSelectedTests={setSelectedTests}
          modeFilter={modeFilter}
          setModeFilter={setModeFilter}
          onRun={handleRun}
          onClose={() => setShowSelector(false)}
          isRunning={isRunning}
        />
      )}
    </div>
  )
}
