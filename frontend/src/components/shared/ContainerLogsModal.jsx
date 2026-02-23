/**
 * ContainerLogsModal - Terminal-style modal for viewing Docker container logs
 *
 * Reusable across DebugChat (backend logs) and DebugMCP (per-server logs).
 * Uses the existing getDeploymentLogs API and matches the dark modal style from DebugChat.
 */

import { useEffect, useRef, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { X, RefreshCw, Terminal, Loader2 } from 'lucide-react'
import { getDeploymentLogs } from '../../services/api'

const ContainerLogsModal = ({ containerName, onClose }) => {
  const logsEndRef = useRef(null)

  const { data, isLoading, error, refetch, isFetching } = useQuery({
    queryKey: ['containerLogs', containerName],
    queryFn: () => getDeploymentLogs(containerName, 200),
    enabled: !!containerName,
  })

  const lines = useMemo(() => {
    if (!data?.logs) return []
    return data.logs.split('\n')
  }, [data?.logs])

  // Auto-scroll to bottom when logs load
  useEffect(() => {
    if (lines.length > 0) {
      logsEndRef.current?.scrollIntoView({ behavior: 'smooth' })
    }
  }, [lines])

  // Close on Escape
  useEffect(() => {
    const handleKeyDown = (e) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [onClose])

  const gutterWidth = lines.length > 0 ? String(lines.length).length : 1

  return (
    <>
      {/* Backdrop */}
      <div className="fixed inset-0 bg-black/50 z-30" onClick={onClose} />
      {/* Modal — near full-screen for maximum log readability */}
      <div className="fixed inset-4 sm:inset-6 z-40 bg-gray-950 rounded-lg shadow-2xl border border-gray-700 flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-2.5 border-b border-gray-700 bg-gray-800 rounded-t-lg flex-shrink-0">
          <div className="flex items-center gap-2">
            <Terminal className="w-4 h-4 text-gray-400" />
            <span className="text-sm font-medium text-gray-200">Container Logs</span>
            <code className="px-2 py-0.5 text-xs font-medium rounded bg-gray-700 text-gray-400">
              {containerName}
            </code>
            {lines.length > 0 && (
              <span className="text-xs text-gray-500">{lines.length} lines</span>
            )}
          </div>
          <div className="flex items-center gap-1">
            <button
              onClick={() => refetch()}
              disabled={isFetching}
              className="flex items-center gap-1.5 px-2.5 py-1 text-xs text-gray-400 rounded hover:bg-gray-700 transition-colors disabled:opacity-50"
              title="Refresh logs"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${isFetching ? 'animate-spin' : ''}`} />
              <span>Refresh</span>
            </button>
            <button
              onClick={onClose}
              className="p-1 ml-1 rounded text-gray-400 hover:text-gray-200 hover:bg-gray-700 transition-colors"
              title="Close (Esc)"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Log content */}
        <div className="flex-1 overflow-auto">
          {isLoading ? (
            <div className="flex items-center justify-center h-full text-gray-500 gap-2">
              <Loader2 className="w-5 h-5 animate-spin" />
              <span className="text-sm">Loading logs...</span>
            </div>
          ) : error ? (
            <div className="p-4 text-sm text-red-400">Failed to load logs: {error.message}</div>
          ) : lines.length === 0 ? (
            <div className="flex items-center justify-center h-full text-gray-500 text-sm">(no logs)</div>
          ) : (
            <table className="w-full border-collapse">
              <tbody className="font-mono text-[13px] leading-5">
                {lines.map((line, i) => (
                  <tr key={i} className="hover:bg-white/[0.03] group">
                    <td
                      className="sticky left-0 bg-gray-950 group-hover:bg-gray-900 text-gray-600 text-right select-none px-3 py-px border-r border-gray-800 align-top"
                      style={{ minWidth: `${gutterWidth + 2}ch` }}
                    >
                      {i + 1}
                    </td>
                    <td className="text-gray-300 px-3 py-px whitespace-pre-wrap break-words">
                      {line}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <div ref={logsEndRef} />
        </div>
      </div>
    </>
  )
}

export default ContainerLogsModal
