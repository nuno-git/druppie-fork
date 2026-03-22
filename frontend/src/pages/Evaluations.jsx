/**
 * Admin Tests Page
 *
 * Two-section layout:
 * 1. Run Tests -- full-screen modal selector for choosing tests, phase toggles, run button
 * 2. Test Results -- past test runs grouped by batch with expandable detail
 */

import { useState, useEffect, useRef } from 'react'
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
} from 'lucide-react'
import {
  getAvailableTests,
  getTestBatches,
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

// ---- Full-screen Test Selector Modal ----

const TestSelectorModal = ({
  tests,
  loading,
  error,
  selectAll,
  setSelectAll,
  selectedTests,
  setSelectedTests,
  phases,
  setPhases,
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
              {tests.map((test) => {
                const checked = selectAll || selectedTests.has(test.name)
                const expanded = expandedTests.has(test.name)
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
                          <span className="font-medium text-sm">{test.name}</span>
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
          <div className="flex items-center gap-4">
            <label className="flex items-center gap-1.5 cursor-pointer">
              <input
                type="checkbox"
                checked={phases.execute}
                onChange={e => setPhases(p => ({ ...p, execute: e.target.checked }))}
                className="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500 w-3.5 h-3.5"
              />
              <span className="text-sm">Execute Agents</span>
            </label>
            <label className="flex items-center gap-1.5 cursor-pointer">
              <input
                type="checkbox"
                checked={phases.judge}
                onChange={e => setPhases(p => ({ ...p, judge: e.target.checked }))}
                className="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500 w-3.5 h-3.5"
              />
              <span className="text-sm">LLM Judge</span>
            </label>
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
    ['Batch ID', run.batch_id],
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
  const [phases, setPhases] = useState({ execute: true, judge: true })
  const [deletingUsers, setDeletingUsers] = useState(false)

  const activePhaseLabels = [
    'Seed',
    phases.execute && 'Execute',
    phases.judge && 'Judge',
  ].filter(Boolean)
  const phaseDescription = activePhaseLabels.join(' \u2192 ')

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

  // Poll for background test run completion
  const pollRunStatus = (runId) => {
    const pollInterval = setInterval(async () => {
      try {
        const status = await getRunStatus(runId)
        if (status.status === 'completed') {
          clearInterval(pollInterval)
          setIsRunning(false)
          setRunMessage(null)
          setRunResult(status.results)
          setRefreshKey((k) => k + 1)
        } else if (status.status === 'error') {
          clearInterval(pollInterval)
          setIsRunning(false)
          setRunMessage(null)
          alert('Test run failed: ' + status.message)
        } else {
          setRunMessage(status.message || 'Running tests...')
        }
      } catch {
        clearInterval(pollInterval)
        setIsRunning(false)
        setRunMessage(null)
        alert('Failed to check test run status')
      }
    }, 2000)
  }

  const handleRun = async () => {
    if (isRunning) return
    if (effectiveCount === 0) return

    setIsRunning(true)
    setRunResult(null)
    setRunMessage('Starting tests...')

    try {
      const options = { ...phases }

      if (selectAll) {
        options.run_all = true
      } else if (selectedTests.size === 1) {
        options.test_name = [...selectedTests][0]
      } else {
        options.test_names = [...selectedTests]
      }

      const { run_id } = await runTests(options)
      pollRunStatus(run_id)
    } catch (err) {
      setIsRunning(false)
      setRunMessage(null)
      alert('Failed to run tests: ' + err.message)
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

                {/* Phase indicators */}
                <div className="flex items-center gap-2 text-xs text-gray-500">
                  <span className="px-2 py-1 bg-gray-100 rounded">Seed</span>
                  <span className="text-gray-300">{'\u2192'}</span>
                  <span className={`px-2 py-1 rounded ${phases.execute ? 'bg-blue-100 text-blue-700' : 'bg-gray-100 text-gray-400'}`}>
                    Execute
                  </span>
                  <span className="text-gray-300">{'\u2192'}</span>
                  <span className={`px-2 py-1 rounded ${phases.judge ? 'bg-blue-100 text-blue-700' : 'bg-gray-100 text-gray-400'}`}>
                    Judge
                  </span>
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

          {/* Running spinner */}
          {isRunning && (
            <div className="flex items-center gap-3 px-4 py-3 bg-blue-50 border border-blue-200 rounded-lg">
              <Loader2 className="w-5 h-5 animate-spin text-blue-600" />
              <span className="text-blue-800 font-medium text-sm">
                {runMessage || `Running ${runDescription}...`} ({phaseDescription})
              </span>
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
          phases={phases}
          setPhases={setPhases}
          onRun={handleRun}
          onClose={() => setShowSelector(false)}
          isRunning={isRunning}
        />
      )}
    </div>
  )
}
