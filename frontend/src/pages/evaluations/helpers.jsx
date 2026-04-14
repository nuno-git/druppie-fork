import { CheckCircle2, XCircle } from 'lucide-react'

export const formatDate = (dateStr) => {
  if (!dateStr) return '-'
  try {
    return new Date(dateStr).toLocaleString()
  } catch {
    return dateStr
  }
}

export const formatDuration = (ms) => {
  if (ms === null || ms === undefined) return '-'
  if (ms < 1000) return `${ms}ms`
  const secs = (ms / 1000).toFixed(1)
  return `${secs}s`
}

export const StatusBadge = ({ value }) => {
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

export const ResultsBanner = ({ result, onDismiss }) => {
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
