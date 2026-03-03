/**
 * DependencyInstallCard - Informational card displaying dependency installations.
 *
 * Pure display component (no mutations).
 * Props: { installs: Array } where each element is the raw MCP install_test_dependencies result:
 * { success, framework, installed_count, failed_count, results: [{ dependency, success, output, error }] }
 */

import { useState } from 'react'
import {
  Package,
  CheckCircle,
  XCircle,
  ChevronDown,
  ChevronRight,
} from 'lucide-react'

const DependencyInstallCard = ({ installs }) => {
  const [isExpanded, setIsExpanded] = useState(false)

  if (!installs?.length) return null

  // Aggregate across all install calls
  let totalInstalled = 0
  let totalFailed = 0
  let allSuccess = true
  const allResults = []

  for (const install of installs) {
    totalInstalled += install.installed_count || 0
    totalFailed += install.failed_count || 0
    if (!install.success) allSuccess = false
    if (install.results) allResults.push(...install.results)
  }

  const frameworks = [...new Set(installs.map((i) => i.framework).filter(Boolean))]

  return (
    <div className={`rounded-xl border bg-gray-50 border-gray-200 border-l-4 ${allSuccess ? 'border-l-blue-400' : 'border-l-amber-400'} transition-all`}>
      {/* Header */}
      <div className="px-4 pt-3 pb-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Package className={`w-4 h-4 ${allSuccess ? 'text-blue-500' : 'text-amber-500'}`} />
            <span className="text-sm font-medium text-gray-800">
              Dependencies Installed
            </span>
          </div>
          {allResults.length > 0 && (
            <button
              onClick={() => setIsExpanded(!isExpanded)}
              className="flex items-center gap-1 text-xs text-gray-400 hover:text-gray-600 transition-colors"
            >
              {isExpanded ? (
                <ChevronDown className="w-3.5 h-3.5" />
              ) : (
                <ChevronRight className="w-3.5 h-3.5" />
              )}
              {isExpanded ? 'Collapse' : 'Details'}
            </button>
          )}
        </div>

        {/* Summary line */}
        <div className="mt-1.5 flex items-center gap-1 text-xs text-gray-500 flex-wrap">
          {frameworks.length > 0 && (
            <>
              <span className="font-medium text-gray-700">{frameworks.join(', ')}</span>
              <span className="text-gray-300 mx-0.5">|</span>
            </>
          )}
          <span>{totalInstalled} installed</span>
          {totalFailed > 0 && (
            <>
              <span className="text-gray-300">&middot;</span>
              <span className="text-red-500">{totalFailed} failed</span>
            </>
          )}
        </div>
      </div>

      {/* Expanded: per-dependency list */}
      {isExpanded && allResults.length > 0 && (
        <div className="px-4 pb-3 border-t border-gray-200">
          <div className="divide-y divide-gray-100">
            {allResults.map((dep, i) => (
              <div key={i} className="py-2 flex items-center gap-2">
                {dep.success ? (
                  <CheckCircle className="w-3.5 h-3.5 text-green-500 flex-shrink-0" />
                ) : (
                  <XCircle className="w-3.5 h-3.5 text-red-500 flex-shrink-0" />
                )}
                <span className="text-xs font-mono text-gray-700">
                  {dep.dependency}
                </span>
                {dep.error && (
                  <span className="text-xs text-red-500 truncate">
                    {dep.error}
                  </span>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

export default DependencyInstallCard
