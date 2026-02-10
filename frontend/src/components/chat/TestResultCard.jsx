/**
 * TestResultCard - Displays test results from TDD workflows
 */

import React, { useState } from 'react'
import {
  CheckCircle,
  XCircle,
  AlertTriangle,
  ChevronDown,
  ChevronRight,
  BarChart3,
  FileText,
  RefreshCw,
  Clock,
  Percent,
} from 'lucide-react'

const TestResultCard = ({ testResult, defaultExpanded = false }) => {
  const [isExpanded, setIsExpanded] = useState(defaultExpanded)
  
  // Parse test result data
  const verdict = testResult?.verdict || testResult?.status || 'UNKNOWN'
  const summary = testResult?.summary || {}
  const coverage = testResult?.coverage
  const retryCount = testResult?.retry_count || 0
  const maxRetries = testResult?.max_retries || 3
  const feedback = testResult?.feedback || ''
  const framework = testResult?.framework || testResult?.data?.framework || 'unknown'
  const duration = testResult?.duration_ms || testResult?.data?.duration_ms
  
  // Determine status colors
  const getStatusColors = () => {
    if (verdict === 'PASS' || verdict === 'success') {
      return {
        bg: 'bg-green-50',
        border: 'border-green-200',
        text: 'text-green-800',
        iconBg: 'bg-green-100',
        iconText: 'text-green-600',
        badge: 'bg-green-100 text-green-700',
      }
    } else if (verdict === 'FAIL' || verdict === 'error') {
      return {
        bg: 'bg-red-50',
        border: 'border-red-200',
        text: 'text-red-800',
        iconBg: 'bg-red-100',
        iconText: 'text-red-600',
        badge: 'bg-red-100 text-red-700',
      }
    } else {
      return {
        bg: 'bg-yellow-50',
        border: 'border-yellow-200',
        text: 'text-yellow-800',
        iconBg: 'bg-yellow-100',
        iconText: 'text-yellow-600',
        badge: 'bg-yellow-100 text-yellow-700',
      }
    }
  }
  
  const getVerdictIcon = () => {
    if (verdict === 'PASS' || verdict === 'success') {
      return <CheckCircle className="w-5 h-5" />
    } else if (verdict === 'FAIL' || verdict === 'error') {
      return <XCircle className="w-5 h-5" />
    } else {
      return <AlertTriangle className="w-5 h-5" />
    }
  }
  
  const getCoverageColor = (coverageValue) => {
    if (coverageValue >= 80) return 'text-green-600'
    if (coverageValue >= 60) return 'text-yellow-600'
    return 'text-red-600'
  }
  
  const getCoverageIcon = (coverageValue) => {
    if (coverageValue >= 80) return <CheckCircle className="w-4 h-4" />
    if (coverageValue >= 60) return <AlertTriangle className="w-4 h-4" />
    return <XCircle className="w-4 h-4" />
  }
  
  const formatFrameworkName = (fw) => {
    const frameworkMap = {
      pytest: 'Pytest',
      vitest: 'Vitest',
      jest: 'Jest',
      playwright: 'Playwright',
      gotest: 'Go Test',
      unknown: 'Unknown',
    }
    return frameworkMap[fw.toLowerCase()] || fw
  }
  
  const styles = getStatusColors()
  const totalTests = summary.total || 0
  const passedTests = summary.passed || 0
  const failedTests = summary.failed || 0
  const passedPercentage = totalTests > 0 ? Math.round((passedTests / totalTests) * 100) : 0
  
  return (
    <div className={`flex flex-col gap-3 p-4 rounded-lg border ${styles.bg} ${styles.border} ${styles.text} mb-3 transition-all`}>
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className={`p-2 rounded-full ${styles.iconBg} ${styles.iconText}`}>
            {getVerdictIcon()}
          </div>
          <div>
            <div className="flex items-center gap-2 flex-wrap">
              <span className={`text-xs uppercase font-semibold px-2 py-1 rounded ${styles.badge}`}>
                Test Result
              </span>
              <span className="font-semibold text-sm">
                {verdict === 'PASS' ? 'All Tests Passed' : 
                 verdict === 'FAIL' ? 'Tests Failed' : 
                 'Test Result'}
              </span>
              {framework !== 'unknown' && (
                <span className="text-xs bg-gray-100 text-gray-700 px-2 py-1 rounded-full font-medium">
                  {formatFrameworkName(framework)}
                </span>
              )}
            </div>
            <div className="text-xs opacity-80 mt-1">
              {retryCount > 0 ? `Attempt ${retryCount} of ${maxRetries}` : 'Initial test run'}
            </div>
          </div>
        </div>
        
        <button
          onClick={() => setIsExpanded(!isExpanded)}
          className="text-xs text-gray-500 hover:text-gray-700 flex items-center gap-1"
        >
          {isExpanded ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
          {isExpanded ? 'Hide' : 'Show'} details
        </button>
      </div>
      
      {/* Summary Stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div className="bg-white rounded p-3 border border-gray-200">
          <div className="flex items-center gap-2 mb-1">
            <BarChart3 className="w-4 h-4 text-blue-500" />
            <span className="text-xs font-medium text-gray-600">Total Tests</span>
          </div>
          <div className="text-xl font-bold">{totalTests}</div>
        </div>
        
        <div className="bg-white rounded p-3 border border-gray-200">
          <div className="flex items-center gap-2 mb-1">
            <CheckCircle className="w-4 h-4 text-green-500" />
            <span className="text-xs font-medium text-gray-600">Passed</span>
          </div>
          <div className="text-xl font-bold text-green-600">{passedTests}</div>
          <div className="text-xs text-gray-500 mt-1">{passedPercentage}%</div>
        </div>
        
        <div className="bg-white rounded p-3 border border-gray-200">
          <div className="flex items-center gap-2 mb-1">
            <XCircle className="w-4 h-4 text-red-500" />
            <span className="text-xs font-medium text-gray-600">Failed</span>
          </div>
          <div className="text-xl font-bold text-red-600">{failedTests}</div>
          <div className="text-xs text-gray-500 mt-1">
            {totalTests > 0 ? Math.round((failedTests / totalTests) * 100) : 0}%
          </div>
        </div>
        
        {coverage !== undefined && (
          <div className="bg-white rounded p-3 border border-gray-200">
            <div className="flex items-center gap-2 mb-1">
              <Percent className="w-4 h-4 text-purple-500" />
              <span className="text-xs font-medium text-gray-600">Coverage</span>
            </div>
            <div className={`text-xl font-bold ${getCoverageColor(coverage)}`}>
              {coverage.toFixed(1)}%
            </div>
            <div className="flex items-center gap-1 text-xs text-gray-500 mt-1">
              {getCoverageIcon(coverage)}
              <span>{coverage >= 80 ? 'Good' : coverage >= 60 ? 'Fair' : 'Poor'}</span>
            </div>
          </div>
        )}
      </div>
      
      {/* Duration and Retry Info */}
      <div className="flex items-center gap-4 text-xs">
        {duration && (
          <div className="flex items-center gap-1 text-gray-600">
            <Clock className="w-3 h-3" />
            <span>Duration: {duration}ms</span>
          </div>
        )}
        
        {retryCount > 0 && (
          <div className="flex items-center gap-1 text-gray-600">
            <RefreshCw className="w-3 h-3" />
            <span>Retry: {retryCount}/{maxRetries}</span>
          </div>
        )}
      </div>
      
      {/* Expanded Content */}
      {isExpanded && (
        <div className="space-y-3 pt-3 border-t border-gray-200">
          {/* Feedback Section */}
          {feedback && (
            <div className="bg-gray-50 rounded p-3">
              <div className="flex items-center gap-2 mb-2">
                <FileText className="w-4 h-4 text-gray-600" />
                <span className="text-xs font-medium text-gray-700">Tester Feedback</span>
              </div>
              <div className="text-sm text-gray-700 whitespace-pre-wrap bg-white p-3 rounded border border-gray-200">
                {feedback}
              </div>
            </div>
          )}
          
          {/* Test Details */}
          <div className="bg-gray-50 rounded p-3">
            <div className="flex items-center gap-2 mb-2">
              <BarChart3 className="w-4 h-4 text-gray-600" />
              <span className="text-xs font-medium text-gray-700">Test Details</span>
            </div>
            <div className="space-y-2">
              <div className="flex justify-between text-sm">
                <span className="text-gray-600">Test Framework:</span>
                <span className="font-medium">{formatFrameworkName(framework)}</span>
              </div>
              <div className="flex justify-between text-sm">
                <span className="text-gray-600">Verdict:</span>
                <span className={`font-medium ${verdict === 'PASS' ? 'text-green-600' : 'text-red-600'}`}>
                  {verdict}
                </span>
              </div>
              <div className="flex justify-between text-sm">
                <span className="text-gray-600">Should Retry:</span>
                <span className="font-medium">
                  {testResult?.should_retry ? 'Yes' : 'No'}
                </span>
              </div>
              {testResult?.next_action && (
                <div className="flex justify-between text-sm">
                  <span className="text-gray-600">Next Action:</span>
                  <span className="font-medium text-blue-600">
                    {testResult.next_action}
                  </span>
                </div>
              )}
            </div>
          </div>
          
          {/* Raw Data (for debugging) */}
          {process.env.NODE_ENV === 'development' && (
            <div className="bg-gray-900 rounded p-3">
              <div className="text-xs text-gray-400 uppercase mb-2">Raw Test Data</div>
              <pre className="text-xs text-green-400 font-mono whitespace-pre-wrap overflow-x-auto">
                {JSON.stringify(testResult, null, 2)}
              </pre>
            </div>
          )}
        </div>
      )}
      
      {/* Action Buttons */}
      <div className="flex items-center gap-2 pt-2 border-t border-gray-200">
        {verdict === 'FAIL' && testResult?.should_retry && (
          <button className="text-xs bg-orange-100 text-orange-700 hover:bg-orange-200 px-3 py-1.5 rounded font-medium flex items-center gap-1">
            <RefreshCw className="w-3 h-3" />
            Retry Builder
          </button>
        )}
        
        {verdict === 'PASS' && coverage !== undefined && coverage < 80 && (
          <button className="text-xs bg-yellow-100 text-yellow-700 hover:bg-yellow-200 px-3 py-1.5 rounded font-medium flex items-center gap-1">
            <AlertTriangle className="w-3 h-3" />
            Improve Coverage
          </button>
        )}
        
        <button className="text-xs bg-gray-100 text-gray-700 hover:bg-gray-200 px-3 py-1.5 rounded font-medium ml-auto">
          View Logs
        </button>
      </div>
    </div>
  )
}

export default TestResultCard