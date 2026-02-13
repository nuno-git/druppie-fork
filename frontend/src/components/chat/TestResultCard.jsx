/**
 * TestResultCard - Displays test results from the testing MCP run_tests tool.
 *
 * Accepts the raw MCP result format:
 * {success, framework, command, exit_code, stdout, stderr, elapsed_seconds,
 *  results: {total, passed, failed, skipped, failed_tests}, coverage}
 */

import React, { useState } from 'react'
import {
  CheckCircle,
  XCircle,
  AlertTriangle,
  ChevronDown,
  ChevronRight,
  BarChart3,
  Terminal,
  Clock,
  Percent,
} from 'lucide-react'

const TestResultCard = ({ testResult, defaultExpanded = false }) => {
  const [isExpanded, setIsExpanded] = useState(defaultExpanded)

  if (!testResult) return null

  // Handle both MCP format and legacy format
  const results = testResult.results || {}
  const totalTests = results.total || 0
  const passedTests = results.passed || 0
  const failedTests = results.failed || 0
  const skippedTests = results.skipped || 0
  const failedTestNames = results.failed_tests || []

  const framework = testResult.framework || 'unknown'
  const command = testResult.command || ''
  const exitCode = testResult.exit_code
  const elapsedSec = testResult.elapsed_seconds
  const stdout = testResult.stdout || ''
  const stderr = testResult.stderr || ''

  // Coverage from MCP
  const coverageData = testResult.coverage
  const coveragePercent = coverageData?.overall_percent

  // Determine verdict from exit code and results
  const isPass = testResult.success && exitCode === 0 && failedTests === 0
  const verdict = isPass ? 'PASS' : 'FAIL'

  const passedPercentage = totalTests > 0 ? Math.round((passedTests / totalTests) * 100) : 0

  const styles = isPass
    ? { bg: 'bg-green-50', border: 'border-green-200', text: 'text-green-800', iconBg: 'bg-green-100', iconText: 'text-green-600', badge: 'bg-green-100 text-green-700' }
    : { bg: 'bg-red-50', border: 'border-red-200', text: 'text-red-800', iconBg: 'bg-red-100', iconText: 'text-red-600', badge: 'bg-red-100 text-red-700' }

  const formatFramework = (fw) => {
    const map = { pytest: 'Pytest', vitest: 'Vitest', jest: 'Jest', playwright: 'Playwright', gotest: 'Go Test', shell: 'Shell', unknown: 'Unknown' }
    return map[fw?.toLowerCase()] || fw
  }

  const getCoverageColor = (v) => v >= 80 ? 'text-green-600' : v >= 60 ? 'text-yellow-600' : 'text-red-600'

  return (
    <div className={`flex flex-col gap-3 p-4 rounded-lg border ${styles.bg} ${styles.border} ${styles.text} mb-3 transition-all`}>
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className={`p-2 rounded-full ${styles.iconBg} ${styles.iconText}`}>
            {isPass ? <CheckCircle className="w-5 h-5" /> : <XCircle className="w-5 h-5" />}
          </div>
          <div>
            <div className="flex items-center gap-2 flex-wrap">
              <span className={`text-xs uppercase font-semibold px-2 py-1 rounded ${styles.badge}`}>
                {verdict}
              </span>
              <span className="font-semibold text-sm">
                {isPass ? 'All Tests Passed' : `${failedTests} Test${failedTests !== 1 ? 's' : ''} Failed`}
              </span>
              {framework !== 'unknown' && (
                <span className="text-xs bg-gray-100 text-gray-700 px-2 py-1 rounded-full font-medium">
                  {formatFramework(framework)}
                </span>
              )}
            </div>
            {command && (
              <div className="text-xs opacity-70 mt-1 font-mono">{command}</div>
            )}
          </div>
        </div>

        <button
          onClick={() => setIsExpanded(!isExpanded)}
          className="text-xs text-gray-500 hover:text-gray-700 flex items-center gap-1"
        >
          {isExpanded ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
          {isExpanded ? 'Hide' : 'Details'}
        </button>
      </div>

      {/* Summary Stats */}
      <div className={`grid gap-3 ${coveragePercent !== undefined && coveragePercent !== null ? 'grid-cols-2 md:grid-cols-4' : 'grid-cols-3'}`}>
        <div className="bg-white rounded p-3 border border-gray-200">
          <div className="flex items-center gap-2 mb-1">
            <BarChart3 className="w-4 h-4 text-blue-500" />
            <span className="text-xs font-medium text-gray-600">Total</span>
          </div>
          <div className="text-xl font-bold">{totalTests}</div>
        </div>

        <div className="bg-white rounded p-3 border border-gray-200">
          <div className="flex items-center gap-2 mb-1">
            <CheckCircle className="w-4 h-4 text-green-500" />
            <span className="text-xs font-medium text-gray-600">Passed</span>
          </div>
          <div className="text-xl font-bold text-green-600">{passedTests}</div>
          {totalTests > 0 && <div className="text-xs text-gray-500 mt-1">{passedPercentage}%</div>}
        </div>

        <div className="bg-white rounded p-3 border border-gray-200">
          <div className="flex items-center gap-2 mb-1">
            <XCircle className="w-4 h-4 text-red-500" />
            <span className="text-xs font-medium text-gray-600">Failed</span>
          </div>
          <div className="text-xl font-bold text-red-600">{failedTests}</div>
          {skippedTests > 0 && <div className="text-xs text-gray-500 mt-1">{skippedTests} skipped</div>}
        </div>

        {coveragePercent !== undefined && coveragePercent !== null && (
          <div className="bg-white rounded p-3 border border-gray-200">
            <div className="flex items-center gap-2 mb-1">
              <Percent className="w-4 h-4 text-purple-500" />
              <span className="text-xs font-medium text-gray-600">Coverage</span>
            </div>
            <div className={`text-xl font-bold ${getCoverageColor(coveragePercent)}`}>
              {coveragePercent.toFixed(1)}%
            </div>
          </div>
        )}
      </div>

      {/* Duration */}
      {elapsedSec && (
        <div className="flex items-center gap-1 text-xs text-gray-600">
          <Clock className="w-3 h-3" />
          <span>{elapsedSec.toFixed(2)}s</span>
        </div>
      )}

      {/* Expanded Content */}
      {isExpanded && (
        <div className="space-y-3 pt-3 border-t border-gray-200">
          {/* Failed test names */}
          {failedTestNames.length > 0 && (
            <div className="bg-red-50 rounded p-3 border border-red-200">
              <div className="text-xs font-medium text-red-700 mb-2">Failed Tests</div>
              <ul className="space-y-1">
                {failedTestNames.map((name, i) => (
                  <li key={i} className="text-xs font-mono text-red-800 flex items-center gap-1">
                    <XCircle className="w-3 h-3 flex-shrink-0" />
                    {name}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Test output */}
          {(stdout || stderr) && (
            <div className="bg-gray-900 rounded p-3">
              <div className="flex items-center gap-2 mb-2">
                <Terminal className="w-4 h-4 text-gray-400" />
                <span className="text-xs font-medium text-gray-400">Test Output</span>
                {exitCode !== undefined && (
                  <span className={`text-xs ml-auto ${exitCode === 0 ? 'text-green-400' : 'text-red-400'}`}>
                    exit code: {exitCode}
                  </span>
                )}
              </div>
              <pre className="text-xs text-gray-300 font-mono whitespace-pre-wrap overflow-x-auto max-h-64 overflow-y-auto">
                {stdout}{stderr ? '\n--- stderr ---\n' + stderr : ''}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export default TestResultCard
