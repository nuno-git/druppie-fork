import { useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { RefreshCw, FileText, X } from 'lucide-react'
import { getDeploymentLogs } from '../../services/api'

const LogsDrawer = ({ containerName, onClose }) => {
  const { data, isLoading, refetch, isFetching } = useQuery({
    queryKey: ['deployment-logs', containerName],
    queryFn: () => getDeploymentLogs(containerName, 300),
    enabled: !!containerName,
  })

  useEffect(() => {
    if (!containerName) return
    const handleKeyDown = (e) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [containerName, onClose])

  if (!containerName) return null

  return (
    <div className="fixed inset-0 z-40 flex">
      <div className="flex-1 bg-black/30" onClick={onClose} />
      <div className="w-[720px] max-w-[90vw] bg-white h-full flex flex-col border-l border-gray-200 shadow-xl">
        <div className="flex items-center justify-between px-4 py-3 border-b border-gray-200">
          <div className="flex items-center gap-2">
            <FileText className="w-4 h-4 text-gray-600" />
            <span className="font-medium text-sm">{containerName}</span>
            <span className="text-xs text-gray-500">last 300 lines</span>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => refetch()}
              className="p-1.5 text-gray-500 hover:text-gray-700 hover:bg-gray-100 rounded"
              title="Refresh"
            >
              <RefreshCw className={`w-4 h-4 ${isFetching ? 'animate-spin' : ''}`} />
            </button>
            <button
              onClick={onClose}
              className="p-1.5 text-gray-500 hover:text-gray-700 hover:bg-gray-100 rounded"
              title="Close (Esc)"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>
        <pre className="flex-1 overflow-auto p-4 text-xs font-mono bg-gray-900 text-gray-100 whitespace-pre-wrap">
{isLoading ? 'Loading…' : (data?.logs || '(no logs)')}
        </pre>
      </div>
    </div>
  )
}

export default LogsDrawer
