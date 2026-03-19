/**
 * TestResultCard - Unified card displaying all test results from an agent run.
 *
 * Props: { testResults: Array } where each element is the raw MCP run_tests result:
 * {success, framework, command, exit_code, stdout, stderr, elapsed_seconds,
 *  results: {total, passed, failed, skipped, failed_tests}, coverage}
 */

import React, { useState } from 'react'
import {
  CheckCircle,
  XCircle,
  ChevronDown,
  ChevronRight,
  Terminal,
} from 'lucide-react'
import { extractTestErrors } from './ChatHelpers'

const formatFramework = (fw) => {
  const map = {
    pytest: 'Pytest', vitest: 'Vitest', jest: 'Jest', playwright: 'Playwright',
    gotest: 'Go Test', go: 'Go Test', shell: 'Shell',
    mocha: 'Mocha', cargo: 'Cargo Test', rspec: 'RSpec',
    maven: 'Maven', gradle: 'Gradle',
  }
  return map[fw?.toLowerCase()] || fw || 'Tests'
}

const formatTime = (sec) => {
  if (sec == null) return null
  return sec >= 60 ? `${(sec / 60).toFixed(1)}m` : `${sec.toFixed(1)}s`
}

/** Strip ANSI escape codes from text (raw stdout/stderr may contain color codes) */
const stripAnsi = (text) => text.replace(/\x1b\[[0-9;]*[a-zA-Z]/g, '')

/** Client-side fallback: parse test counts from stdout/stderr when server-side parsing returned zeros */
const parseResultsFallback = (result) => {
  const res = result.results || {}
  if ((res.total || 0) > 0) return res // Server-side parsing worked

  // If server detected a config error, trust its zero counts — tests didn't actually run
  if (result.config_error) return res

  const output = stripAnsi((result.stdout || '') + '\n' + (result.stderr || ''))
  if (!output.trim()) return res

  let passed = 0, failed = 0, skipped = 0

  // Vitest modern: "Tests  3 passed (3)" or "Tests  1 failed | 2 passed (3)" or "Tests  3 failed (3)"
  const vitest = output.match(/Tests\s+(?:(\d+)\s+failed\s*\|?\s*)?(?:(\d+)\s+skipped\s*\|?\s*)?(?:(\d+)\s+passed\s*)?\((\d+)\)/)
  if (vitest) {
    return {
      ...res,
      failed: parseInt(vitest[1] || '0'),
      skipped: parseInt(vitest[2] || '0'),
      passed: parseInt(vitest[3] || '0'),
      total: parseInt(vitest[4]),
    }
  }

  // Jest: "Tests: 1 failed, 3 passed, 4 total"
  const jest = output.match(/Tests:\s*(?:(\d+)\s+failed,\s*)?(?:(\d+)\s+skipped,\s*)?(?:(\d+)\s+passed,\s*)?(\d+)\s+total/)
  if (jest) {
    return {
      ...res,
      failed: parseInt(jest[1] || '0'),
      skipped: parseInt(jest[2] || '0'),
      passed: parseInt(jest[3] || '0'),
      total: parseInt(jest[4]),
    }
  }

  // Pytest: "1 failed, 3 passed in 0.42s" with === border
  const hasPytestFooter = output.match(/in \d[\d.]*s\s*={3,}/)
  if (hasPytestFooter) {
    const pm = output.match(/(\d+)\s+passed/)
    const fm = output.match(/(\d+)\s+failed/)
    const sm = output.match(/(\d+)\s+skipped/)
    const em = output.match(/(\d+)\s+error/)
    if (pm || fm) {
      const p = parseInt(pm?.[1] || '0')
      const f = parseInt(fm?.[1] || '0') + parseInt(em?.[1] || '0')
      const s = parseInt(sm?.[1] || '0')
      return { ...res, passed: p, failed: f, skipped: s, total: p + f + s }
    }
  }

  // Generic: "N passed", "N failed"
  // Use multiline per-line matching to skip "Test Suites:" lines (those count suites, not tests)
  const lines = output.split('\n').filter(l => !l.match(/Test Suites:/))
  const filteredOutput = lines.join('\n')
  const passedM = filteredOutput.match(/(\d+)\s+(?:passing|passed)/)
  const failedM = filteredOutput.match(/(\d+)\s+(?:failing|failed)/)
  const skippedM = output.match(/(\d+)\s+(?:pending|skipped)/)
  if (passedM || failedM) {
    passed = parseInt(passedM?.[1] || '0')
    failed = parseInt(failedM?.[1] || '0')
    skipped = parseInt(skippedM?.[1] || '0')
    return { ...res, passed, failed, skipped, total: passed + failed + skipped }
  }

  return res
}

/** Single run section inside the expanded area */
const TestRunSection = ({ result }) => {
  const [showOutput, setShowOutput] = useState(false)

  const r = parseResultsFallback(result)
  const passed = r.passed || 0
  const failed = r.failed || 0
  const total = r.total || 0
  const failedNames = r.failed_tests || []
  const isPass = result.exit_code === 0 && failed === 0
  const errors = extractTestErrors(result.stdout, result.stderr, result.framework, failedNames)

  // Detect if we couldn't parse any test data
  const noCounts = total === 0 && passed === 0 && failed === 0
  const hasOutput = result.stdout || result.stderr

  return (
    <div className="py-2">
      {/* Run header */}
      <div className="flex items-center gap-2 text-xs">
        <span className="font-medium text-gray-700 bg-gray-100 px-1.5 py-0.5 rounded">
          {formatFramework(result.framework)}
        </span>
        {formatTime(result.elapsed_seconds) && (
          <span className="text-gray-400">({formatTime(result.elapsed_seconds)})</span>
        )}
        {isPass ? (
          <CheckCircle className="w-3.5 h-3.5 text-green-500" />
        ) : (
          <XCircle className="w-3.5 h-3.5 text-red-400" />
        )}
        {noCounts ? (
          <span className="text-amber-600 italic">
            {result.config_error ? result.config_error
              : !hasOutput ? 'No test output'
              : result.exit_code === 5 && result.framework === 'pytest' ? 'No tests collected'
              : result.exit_code > 1 ? `Framework error (exit ${result.exit_code})`
              : result.exit_code === 1 ? 'Tests failed (counts unavailable)'
              : 'Unable to parse results'}
          </span>
        ) : (
          <span className="text-gray-500">{passed}/{total} passed</span>
        )}
      </div>

      {/* Failed tests with error excerpts */}
      {failedNames.length > 0 && (
        <div className="mt-1.5 ml-2 space-y-1.5">
          {failedNames.map((name, i) => (
            <div key={i} className="text-xs">
              <div className="flex items-center gap-1 text-red-500 font-medium font-mono">
                <XCircle className="w-3 h-3 flex-shrink-0" />
                {name}
              </div>
              {errors[name] && (
                <pre className="ml-4 mt-0.5 text-gray-500 font-mono whitespace-pre-wrap leading-relaxed">
                  {errors[name]}
                </pre>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Collapsible raw output */}
      {(result.stdout || result.stderr) && (
        <div className="mt-2">
          <button
            onClick={() => setShowOutput(!showOutput)}
            className="flex items-center gap-1 text-xs text-gray-400 hover:text-gray-600 transition-colors"
          >
            {showOutput ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
            <Terminal className="w-3 h-3" />
            {showOutput ? 'Hide output' : 'Show full output'}
          </button>
          {showOutput && (
            <pre className="mt-1 p-2 bg-gray-900 rounded text-xs text-gray-300 font-mono whitespace-pre-wrap overflow-x-auto max-h-64 overflow-y-auto">
              {result.stdout}{result.stderr ? '\n--- stderr ---\n' + result.stderr : ''}
            </pre>
          )}
        </div>
      )}
    </div>
  )
}

const TestResultCard = ({ testResults, isRunning }) => {
  const [isExpanded, setIsExpanded] = useState(false)

  // Show loading state if running with no results yet
  if (isRunning && (!testResults || testResults.length === 0)) {
    return (
      <div className="rounded-xl border bg-gray-50 border-gray-200 border-l-4 border-l-blue-400 transition-all">
        <div className="px-4 py-3">
          <div className="flex items-center gap-2">
            <div className="w-4 h-4 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
            <span className="text-sm font-medium text-gray-800">Running tests...</span>
          </div>
        </div>
      </div>
    )
  }

  if (!testResults?.length) return null

  // Use the LAST test run as the primary result (reflects final state after fixes)
  const lastRun = testResults[testResults.length - 1]
  const lastRes = parseResultsFallback(lastRun)
  const totalPassed = lastRes.passed || 0
  const totalFailed = lastRes.failed || 0
  const totalSkipped = lastRes.skipped || 0
  const totalTests = lastRes.total || 0
  const coveragePercent = lastRun.coverage?.overall_percent ?? null

  // Detect various failure modes
  const noCounts = totalTests === 0 && totalPassed === 0 && totalFailed === 0
  const testRunFailed = noCounts && lastRun.exit_code !== 0
  const allPass = lastRun.exit_code === 0 && totalFailed === 0 && !testRunFailed

  const iterations = testResults.length
  const hasOutput = lastRun.stdout || lastRun.stderr

  // Build inline summary parts
  const summaryParts = []
  if (testRunFailed && lastRun.config_error) {
    summaryParts.push(lastRun.config_error)
  } else if (testRunFailed && !hasOutput) {
    summaryParts.push('No test output')
  } else if (testRunFailed && lastRun.exit_code === 5 && lastRun.framework === 'pytest') {
    summaryParts.push('No tests collected')
  } else if (testRunFailed && lastRun.exit_code > 1) {
    summaryParts.push(`Framework error (exit ${lastRun.exit_code})`)
  } else if (testRunFailed) {
    summaryParts.push('Test run failed')
  } else if (noCounts && hasOutput && lastRun.exit_code === 0) {
    summaryParts.push('Unable to parse counts (likely passed)')
  } else if (noCounts && hasOutput) {
    summaryParts.push('Unable to parse counts')
  } else if (noCounts) {
    summaryParts.push('No test output')
  } else {
    // Normal case: we have counts
    summaryParts.push(`${totalPassed} passed`)
    if (totalFailed > 0) summaryParts.push(`${totalFailed} failed`)
    if (totalSkipped > 0) summaryParts.push(`${totalSkipped} skipped`)
  }
  if (coveragePercent != null && coveragePercent > 0) summaryParts.push(`${coveragePercent.toFixed(0)}% cov`)
  if (iterations > 1) summaryParts.push(`${iterations} iterations`)
  if (lastRun.elapsed_seconds) summaryParts.push(formatTime(lastRun.elapsed_seconds))

  return (
    <div className={`rounded-xl border bg-gray-50 border-gray-200 border-l-4 ${allPass ? 'border-l-green-500' : 'border-l-red-400'} transition-all`}>
      {/* Header */}
      <div className="px-4 pt-3 pb-1">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            {allPass ? (
              <CheckCircle className="w-4 h-4 text-green-500" />
            ) : (
              <XCircle className="w-4 h-4 text-red-400" />
            )}
            <span className="text-sm font-medium text-gray-800">Test Results</span>
          </div>
          <button
            onClick={() => setIsExpanded(!isExpanded)}
            className="flex items-center gap-1 text-xs text-gray-400 hover:text-gray-600 transition-colors"
          >
            {isExpanded ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
            {isExpanded ? 'Collapse' : 'Details'}
          </button>
        </div>

        {/* Ratio bar */}
        <div className="mt-2 h-1.5 bg-gray-200 rounded-full overflow-hidden flex">
          {totalTests > 0 && totalPassed > 0 && (
            <div className="h-full bg-green-500" style={{ width: `${(totalPassed / totalTests) * 100}%` }} />
          )}
          {totalTests > 0 && totalFailed > 0 && (
            <div className="h-full bg-red-400" style={{ width: `${(totalFailed / totalTests) * 100}%` }} />
          )}
        </div>

        {/* Inline summary */}
        <div className="mt-1.5 pb-2 flex items-center gap-1 text-xs text-gray-500 flex-wrap">
          {!noCounts && (
            <>
              <span className="font-medium text-gray-700">{totalPassed}/{totalTests}</span>
              <span className="text-gray-300 mx-0.5">|</span>
            </>
          )}
          {summaryParts.map((part, i) => (
            <span key={i} className="flex items-center gap-1">
              {i > 0 && <span className="text-gray-300">&middot;</span>}
              {part}
            </span>
          ))}
        </div>
      </div>

      {/* Expanded: per-run details */}
      {isExpanded && (
        <div className="px-4 pb-3 border-t border-gray-200">
          <div className="divide-y divide-gray-100">
            {testResults.map((result, i) => (
              <TestRunSection key={i} result={result} />
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

export default TestResultCard
