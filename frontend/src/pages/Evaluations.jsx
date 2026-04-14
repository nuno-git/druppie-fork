/**
 * Admin Tests Page
 *
 * Two-section layout:
 * 1. Run Tests -- full-screen modal selector for choosing tests, phase toggles, run button
 * 2. Test Results -- past test runs grouped by batch with expandable detail
 */

import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import {
  FlaskConical,
  ArrowLeft,
  Loader2,
  Trash2,
  Play,
  ChevronDown,
  RefreshCw,
  Clock,
  BarChart3,
} from 'lucide-react'
import {
  getAvailableTests,
  getActiveRun,
  deleteTestUsers,
  runTests,
} from '../services/api'

import { TestSelectorModal, RunProgress, SeedSection, UnitTestsSection } from './evaluations/TestRunner'
import TestResults from './evaluations/TestResults'
import TestRunDetail from './evaluations/TestRunDetail'
import useTestPolling from './evaluations/useTestPolling'

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
  const [inputValues, setInputValues] = useState({})

  // Shared run state
  const [isRunning, setIsRunning] = useState(false)
  const [runResult, setRunResult] = useState(null)
  const [runMessage, setRunMessage] = useState(null)
  const [modeFilter, setModeFilter] = useState('all') // all, live, record_only, replay, manual
  const [judgeEnabled, setJudgeEnabled] = useState(true)
  const [deletingUsers, setDeletingUsers] = useState(false)
  const [runProgress, setRunProgress] = useState(null) // {current_test, completed_tests, total_tests}

  // Effective selected count for display
  const effectiveCount = selectAll ? availableTests.length : selectedTests.size

  // Polling hook
  const { pollRunStatus } = useTestPolling({
    setIsRunning,
    setRunMessage,
    setRunProgress,
    setRunResult,
    setRefreshKey,
  })

  // Load available tests + check for active run on mount
  useEffect(() => {
    const fetch = async () => {
      setTestsLoading(true)
      setTestsError(null)
      try {
        const [data, activeRun] = await Promise.all([
          getAvailableTests(),
          getActiveRun().catch(() => ({ active: false })),
        ])
        setAvailableTests(data || [])

        // Restore running state if a test is in progress
        if (activeRun.active && activeRun.run_id) {
          setIsRunning(true)
          setRunMessage(activeRun.message || 'Running tests...')
          setRunProgress({
            current_test: activeRun.current_test,
            completed_tests: activeRun.completed_tests || [],
            total_tests: activeRun.total_tests || 0,
          })
          pollRunStatus(activeRun.run_id)
        }
      } catch (err) {
        setTestsError(err.message)
      } finally {
        setTestsLoading(false)
      }
    }
    fetch()
  }, [])

  const handleRun = async () => {
    if (isRunning) return
    if (effectiveCount === 0) return

    setIsRunning(true)
    setRunResult(null)
    setRunMessage('Starting tests...')

    try {
      const options = { execute: true, judge: judgeEnabled }

      if (selectAll) {
        options.run_all = true
      } else if (selectedTests.size === 1) {
        options.test_name = [...selectedTests][0]
      } else {
        options.test_names = [...selectedTests]
      }

      // Collect manual input values for selected tests
      const resolvedInputs = {}
      for (const [key, val] of Object.entries(inputValues)) {
        // Key format: "test-name:input-name" — extract just input-name
        const parts = key.split(':')
        if (parts.length === 2) {
          resolvedInputs[parts[1]] = val
        }
      }
      if (Object.keys(resolvedInputs).length > 0) {
        options.input_values = resolvedInputs
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
                  {['all', 'agent', 'tool', 'manual'].map((m) => (
                    <span key={m} className={`px-2 py-1 rounded ${
                      modeFilter === m ? 'bg-indigo-100 text-indigo-700 font-medium' : 'bg-gray-100 text-gray-400'
                    }`}>
                      {m === 'all' ? 'All' : m === 'agent' ? 'Agent' : m === 'tool' ? 'Tool' : 'Manual'}
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
            <RunProgress runMessage={runMessage} runProgress={runProgress} />
          )}

          {/* ============ SECTION 2: Test Results (grouped by batch) ============ */}
          <div className="bg-white rounded-lg border overflow-hidden">
            <div className="px-4 py-3 border-b border-gray-100 bg-gray-50 flex items-center gap-2">
              <Clock className="w-4 h-4 text-gray-500" />
              <h2 className="font-semibold text-sm">Test Results</h2>
            </div>

            <div className="p-3">
              <TestResults
                key={refreshKey}
                refreshKey={refreshKey}
                onSelectRun={handleSelectTestRun}
                isRunning={isRunning}
                runResult={runResult}
                setRunResult={setRunResult}
              />
            </div>
          </div>

          {/* ============ SECTION 3: Seed Setup ============ */}
          <SeedSection />

          {/* ============ SECTION 4: Unit Tests ============ */}
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
          inputValues={inputValues}
          setInputValues={setInputValues}
          judgeEnabled={judgeEnabled}
          setJudgeEnabled={setJudgeEnabled}
          onRun={handleRun}
          onClose={() => setShowSelector(false)}
          isRunning={isRunning}
        />
      )}
    </div>
  )
}
