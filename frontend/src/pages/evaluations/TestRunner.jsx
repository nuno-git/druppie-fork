/**
 * TestRunner — Test selection, run controls, live progress display
 *
 * Includes: TestSelectorModal, SeedSection, UnitTestsSection,
 * and the run controls / progress bar shown on the main list view.
 */

import { useState, useEffect } from 'react'
import {
  FlaskConical,
  Loader2,
  AlertCircle,
  Play,
  CheckCircle2,
  XCircle,
  ChevronDown,
  ChevronUp,
  ChevronRight,
  X,
  Info,
} from 'lucide-react'
import {
  getAvailableSetups,
  seedSessions,
  runUnitTests,
} from '../../services/api'
import { formatDuration } from './helpers'

// ---- Full-screen Test Selector Modal ----

export const TestSelectorModal = ({
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
  inputValues,
  setInputValues,
  judgeEnabled,
  setJudgeEnabled,
}) => {
  const [expandedTests, setExpandedTests] = useState(new Set())

  const toggleTest = (name) => {
    const next = new Set(selectedTests)
    if (next.has(name)) {
      next.delete(name)
    } else {
      next.add(name)
      // Auto-expand manual tests so the input form is visible
      const test = tests.find((t) => t.name === name)
      if (test?.manual_input) {
        setExpandedTests((prev) => new Set([...prev, name]))
      }
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
      setInputValues({})
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
              {tests.filter((t) => {
                if (modeFilter === 'all') return true
                if (modeFilter === 'manual') return t.manual_input
                if (modeFilter === 'tool') return t.type === 'tool'
                if (modeFilter === 'agent') return t.type === 'agent' && !t.manual_input
                return t.type === modeFilter && !t.manual_input
              }).map((test) => {
                const checked = selectAll || selectedTests.has(test.name)
                const expanded = expandedTests.has(test.name)
                const testType = test.type
                const modeBg = {
                  agent: 'bg-blue-100 text-blue-700',
                  tool: 'bg-amber-100 text-amber-700',
                  live: 'bg-blue-100 text-blue-700',
                  replay: 'bg-amber-100 text-amber-700',
                  record_only: 'bg-gray-200 text-gray-700',
                }[testType] || 'bg-gray-100 text-gray-600'
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
                              {testType === 'record_only' ? 'record' : testType}
                            </span>
                            {test.manual_input && (
                              <span className="px-1.5 py-0.5 rounded text-[10px] font-semibold uppercase bg-amber-100 text-amber-700">
                                manual
                              </span>
                            )}
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
                            Agents: {test.agents?.join(', ') || 'all'}
                          </span>
                          {test.setup?.length > 0 && (
                            <span>
                              Setup: {test.setup.join(', ')}
                            </span>
                          )}
                          {test.setup?.length === 0 && (
                            <span>Setup: (none)</span>
                          )}
                        </div>

                        {/* Expanded details */}
                        {expanded && (
                          <div className="mt-3 pt-3 border-t border-gray-100 space-y-2">
                            {/* Manual input form */}
                            {test.manual_input && test.inputs?.length > 0 && (
                              <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 space-y-3">
                                <div className="flex items-center gap-2 text-xs font-semibold text-amber-700 uppercase">
                                  <FlaskConical className="w-3.5 h-3.5" />
                                  Manual Input Required
                                </div>
                                {test.inputs.map((inp) => (
                                  <div key={inp.name}>
                                    <label className="block text-xs font-medium text-gray-700 mb-1">
                                      {inp.label || inp.name}
                                      {inp.required && <span className="text-red-500 ml-0.5">*</span>}
                                    </label>
                                    {inp.type === 'textarea' ? (
                                      <textarea
                                        value={inputValues[`${test.name}:${inp.name}`] ?? inp.default ?? ''}
                                        onChange={(e) => setInputValues((prev) => ({
                                          ...prev,
                                          [`${test.name}:${inp.name}`]: e.target.value,
                                        }))}
                                        rows={4}
                                        className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm focus:ring-1 focus:ring-indigo-500 focus:border-indigo-500"
                                        placeholder={inp.default || ''}
                                      />
                                    ) : inp.type === 'select' ? (
                                      <select
                                        value={inputValues[`${test.name}:${inp.name}`] ?? inp.default ?? ''}
                                        onChange={(e) => setInputValues((prev) => ({
                                          ...prev,
                                          [`${test.name}:${inp.name}`]: e.target.value,
                                        }))}
                                        className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm focus:ring-1 focus:ring-indigo-500 focus:border-indigo-500"
                                      >
                                        {(inp.options || []).map((opt) => (
                                          <option key={opt} value={opt}>{opt}</option>
                                        ))}
                                      </select>
                                    ) : (
                                      <input
                                        type="text"
                                        value={inputValues[`${test.name}:${inp.name}`] ?? inp.default ?? ''}
                                        onChange={(e) => setInputValues((prev) => ({
                                          ...prev,
                                          [`${test.name}:${inp.name}`]: e.target.value,
                                        }))}
                                        className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm focus:ring-1 focus:ring-indigo-500 focus:border-indigo-500"
                                        placeholder={inp.default || ''}
                                      />
                                    )}
                                  </div>
                                ))}
                              </div>
                            )}

                            {test.checks && test.checks.length > 0 && (
                              <div>
                                <span className="text-xs font-semibold text-gray-600 uppercase">Checks:</span>
                                {test.checks.map((ev, idx) => (
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
            {['all', 'agent', 'tool', 'manual'].map((m) => (
              <button
                key={m}
                onClick={() => setModeFilter(m)}
                className={`px-3 py-1.5 rounded-full text-xs font-medium transition-colors ${
                  modeFilter === m
                    ? 'bg-indigo-600 text-white'
                    : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                }`}
              >
                {m === 'all' ? 'All' : m === 'agent' ? 'Agent' : m === 'tool' ? 'Tool' : 'Manual'}
              </button>
            ))}
          </div>
          <div className="flex items-center gap-3">
            {(() => {
              const hasAgent = selectAll
                ? tests.some((t) => t.type === 'agent')
                : tests.some((t) => selectedTests.has(t.name) && t.type === 'agent')
              return hasAgent ? (
                <label className="flex items-center gap-1.5 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={judgeEnabled}
                    onChange={(e) => setJudgeEnabled(e.target.checked)}
                    className="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500 w-3.5 h-3.5"
                  />
                  <span className="text-xs text-gray-600">LLM Judge</span>
                </label>
              ) : null
            })()}
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

// ---- Running Progress Display ----

export const RunProgress = ({ runMessage, runProgress }) => {
  return (
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
  )
}

// ---- Seed Section ----

export const SeedSection = () => {
  const [setups, setSetups] = useState([])
  const [loading, setLoading] = useState(true)
  const [seeding, setSeeding] = useState(false)
  const [selectedSetups, setSelectedSetups] = useState(new Set())
  const [seedUser, setSeedUser] = useState('__random__')
  const [result, setResult] = useState(null)
  const [expanded, setExpanded] = useState(false)

  useEffect(() => {
    const load = async () => {
      try {
        const data = await getAvailableSetups()
        setSetups(data || [])
      } catch (err) {
        console.error('Failed to load setups:', err)
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [])

  const toggleSetup = (id) => {
    setSelectedSetups((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const handleSeed = async () => {
    if (selectedSetups.size === 0) return
    setSeeding(true)
    setResult(null)
    try {
      const res = await seedSessions([...selectedSetups], seedUser)
      setResult(res)
      setSelectedSetups(new Set())
    } catch (err) {
      setResult({ error: err.message })
    } finally {
      setSeeding(false)
    }
  }

  const statusColor = {
    completed: 'bg-green-100 text-green-700',
    failed: 'bg-red-100 text-red-700',
    active: 'bg-blue-100 text-blue-700',
    paused_approval: 'bg-yellow-100 text-yellow-700',
  }

  return (
    <div className="bg-white rounded-xl shadow-sm border border-gray-200">
      <div
        className="flex items-center justify-between px-6 py-4 cursor-pointer hover:bg-gray-50 transition-colors"
        onClick={() => setExpanded(!expanded)}
      >
        <div className="flex items-center gap-2">
          <Play className="w-4 h-4 text-emerald-600" />
          <h2 className="text-lg font-semibold text-gray-900">Seed Setup</h2>
          <span className="text-xs text-gray-400">({setups.length} sessions)</span>
        </div>
        {expanded ? <ChevronUp className="w-4 h-4 text-gray-400" /> : <ChevronDown className="w-4 h-4 text-gray-400" />}
      </div>

      {expanded && (
        <div className="px-6 pb-4 border-t border-gray-100">
          <p className="text-xs text-gray-500 mt-3 mb-3">
            Seed sessions into the database as a specific user. Use this to set up world state for manual testing.
          </p>

          {/* User selector */}
          <div className="flex items-center gap-3 mb-3">
            <label className="text-xs font-medium text-gray-600">Seed as user:</label>
            <select
              value={seedUser}
              onChange={(e) => setSeedUser(e.target.value)}
              className="text-xs border border-gray-300 rounded px-2 py-1"
            >
              <option value="__random__">New random user</option>
              <option value="admin">admin</option>
              <option value="architect">architect</option>
              <option value="developer">developer</option>
              <option value="analyst">analyst</option>
              <option value="normal_user">normal_user</option>
            </select>
            <button
              onClick={handleSeed}
              disabled={seeding || selectedSetups.size === 0}
              className="flex items-center gap-1.5 px-3 py-1 bg-emerald-600 text-white rounded text-xs font-medium hover:bg-emerald-700 disabled:opacity-50 transition-colors"
            >
              {seeding ? <Loader2 className="w-3 h-3 animate-spin" /> : <Play className="w-3 h-3" />}
              Seed {selectedSetups.size > 0 ? `(${selectedSetups.size})` : ''}
            </button>
          </div>

          {/* Result banner */}
          {result && (
            <div className={`mb-3 px-3 py-2 rounded text-xs ${result.error ? 'bg-red-50 text-red-700' : 'bg-green-50 text-green-700'}`}>
              {result.error ? (
                <span>Error: {result.error}</span>
              ) : (
                <span>Seeded {result.seeded?.filter((s) => s.status === 'seeded').length} session(s) as <strong>{result.user || seedUser}</strong></span>
              )}
            </div>
          )}

          {/* Session list */}
          {loading ? (
            <div className="flex items-center gap-2 py-4 text-gray-400 text-sm">
              <Loader2 className="w-4 h-4 animate-spin" />Loading...
            </div>
          ) : (
            <div className="space-y-1 max-h-64 overflow-y-auto">
              {setups.map((s) => (
                <label
                  key={s.id}
                  className="flex items-center gap-3 px-3 py-2 rounded hover:bg-gray-50 cursor-pointer transition-colors"
                >
                  <input
                    type="checkbox"
                    checked={selectedSetups.has(s.id)}
                    onChange={() => toggleSetup(s.id)}
                    className="rounded border-gray-300 text-emerald-600 focus:ring-emerald-500 w-3.5 h-3.5"
                  />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className={`px-1.5 py-0.5 rounded text-[10px] font-semibold ${statusColor[s.status] || 'bg-gray-100 text-gray-600'}`}>
                        {s.status}
                      </span>
                      <span className="text-xs font-medium text-gray-800 truncate">{s.id}</span>
                    </div>
                    <div className="flex items-center gap-2 mt-0.5">
                      <span className="text-[10px] text-gray-400 truncate">{s.title}</span>
                      {s.project_name && (
                        <span className="text-[10px] text-gray-400">project: {s.project_name}</span>
                      )}
                      {s.intent && (
                        <span className="text-[10px] text-indigo-400">{s.intent}</span>
                      )}
                    </div>
                  </div>
                  <span className="text-[10px] text-gray-400 flex-shrink-0">{s.num_agents} agents</span>
                </label>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ---- Unit Tests Section ----

export const UnitTestsSection = () => {
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
