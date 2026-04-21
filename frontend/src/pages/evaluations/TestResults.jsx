/**
 * TestResults — Test batch list with expandable batch detail rows.
 * Displays past test runs grouped by batch, with pagination and tag filtering.
 */

import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import {
  Loader2,
  AlertCircle,
  CheckCircle2,
  XCircle,
  ChevronLeft,
  ChevronRight,
  ChevronDown,
  ChevronUp,
  Tag,
  Clock,
  Filter,
  BarChart3,
} from 'lucide-react'
import { getTestBatches, getTags } from '../../services/api'
import { formatDate, formatDuration, StatusBadge, ResultsBanner } from './helpers'

const TestResults = ({ refreshKey, onSelectRun, isRunning, runResult, setRunResult }) => {
  const [batches, setBatches] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [page, setPage] = useState(1)
  const [totalPages, setTotalPages] = useState(1)
  const [tags, setTags] = useState([])
  const [selectedTag, setSelectedTag] = useState(null)
  const [expandedBatches, setExpandedBatches] = useState(new Set())
  const [initialExpanded, setInitialExpanded] = useState(false)
  const [retryKey, setRetryKey] = useState(0)

  const fetchTags = async () => {
    try {
      const data = await getTags()
      setTags(data || [])
    } catch {
      // Tags are optional
    }
  }

  useEffect(() => {
    fetchTags()
  }, [refreshKey])

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    getTestBatches(page, 10, selectedTag)
      .then(data => {
        if (cancelled) return
        setBatches(data.items || [])
        setTotalPages(data.total_pages || 1)
        // Auto-expand the most recent batch on first load
        if (!initialExpanded && data.items?.length > 0) {
          setExpandedBatches(new Set([data.items[0].batch_id]))
          setInitialExpanded(true)
        }
      })
      .catch(err => { if (!cancelled) setError(err.message) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [page, selectedTag, refreshKey, retryKey])

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
          <button onClick={() => setRetryKey((k) => k + 1)} className="mt-2 px-4 py-2 bg-blue-500 text-white rounded text-sm">
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
                  <div
                    role="button"
                    tabIndex={0}
                    onClick={() => toggleBatch(batch.batch_id)}
                    onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') toggleBatch(batch.batch_id) }}
                    className={`w-full flex items-center justify-between px-4 py-3 ${headerBg} hover:opacity-90 transition-colors cursor-pointer`}
                  >
                    <div className="flex items-center gap-3">
                      <Icon className={`w-5 h-5 ${allPassed ? 'text-green-600' : 'text-red-600'}`} />
                      <span className="font-medium text-sm">
                        {batch.test_count === 1
                          ? batch.runs?.[0]?.test_name || 'Test Run'
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
                  </div>

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

export default TestResults
