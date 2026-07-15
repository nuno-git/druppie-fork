import { useState, useRef, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Database, ChevronDown, Check, X, Link2, Loader2, GitBranch, Plug } from 'lucide-react'
import { getDataSources } from '../../services/api'

const AUTH_LABELS = {
  obo: 'Entra ID (user)',
  connection_string: 'Connection string',
  key: 'Access key',
  public: 'Public',
}

const StatusDot = ({ accessible }) => (
  <div className={`mt-0.5 flex-shrink-0 w-4 h-4 rounded-full flex items-center justify-center ${
    accessible ? 'bg-green-100 text-green-600' : 'bg-red-100 text-red-500'
  }`}>
    {accessible
      ? <Check className="w-2.5 h-2.5" strokeWidth={3} />
      : <X className="w-2.5 h-2.5" strokeWidth={3} />}
  </div>
)

const DataSourcesMenu = () => {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)

  const { data, isLoading } = useQuery({
    queryKey: ['datasources'],
    queryFn: getDataSources,
    staleTime: 60_000,
    enabled: open,
  })

  useEffect(() => {
    if (!open) return
    const close = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false) }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [open])

  const sources = data?.sources || []
  const entraLinked = data?.entra_linked
  const entraConfigured = data?.entra_configured
  const devops = data?.services?.devops

  return (
    <div className="relative inline-block" ref={ref}>
      <button
        onClick={(e) => { e.stopPropagation(); setOpen(!open) }}
        className="flex items-center gap-1.5 px-2.5 py-1 text-xs rounded-md transition-colors border text-gray-500 hover:text-gray-700 hover:bg-gray-50 border-gray-200"
        title="Connected services"
      >
        <Plug className="w-3.5 h-3.5" />
        Services
        <ChevronDown className={`w-3 h-3 transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>

      {open && (
        <div className="absolute top-full mt-1 right-0 w-72 rounded-lg shadow-lg z-50 bg-white border border-gray-200">
          <div className="px-3 py-2 border-b border-gray-100">
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Connected Services</span>
              {isLoading && <Loader2 className="w-3.5 h-3.5 text-gray-400 animate-spin" />}
            </div>
            {entraConfigured && (
              <div className={`mt-1.5 flex items-center gap-1.5 text-xs ${entraLinked ? 'text-green-600' : 'text-amber-600'}`}>
                <Link2 className="w-3 h-3" />
                {entraLinked ? 'Microsoft account linked' : 'Microsoft account not linked'}
              </div>
            )}
          </div>

          {/* Azure DevOps */}
          {devops?.configured && (
            <>
              <div className="px-3 pt-2 pb-1">
                <div className="flex items-center gap-1.5 text-xs font-semibold text-gray-400 uppercase tracking-wide">
                  <GitBranch className="w-3 h-3" />
                  Azure DevOps
                </div>
              </div>
              <div className="px-3 py-2 flex items-start gap-2.5 hover:bg-gray-50">
                <StatusDot accessible={devops.accessible} />
                <div className="min-w-0 flex-1">
                  <div className="text-sm font-medium text-gray-800">Backlog & Work Items</div>
                  <div className="text-xs text-gray-400 mt-0.5">
                    {AUTH_LABELS[devops.auth_type] || devops.auth_type}
                  </div>
                </div>
              </div>
            </>
          )}

          {/* Data Sources */}
          {(sources.length > 0 || (!isLoading && !devops?.configured)) && (
            <div className="px-3 pt-2 pb-1 border-t border-gray-100">
              <div className="flex items-center gap-1.5 text-xs font-semibold text-gray-400 uppercase tracking-wide">
                <Database className="w-3 h-3" />
                Data Sources
              </div>
            </div>
          )}

          {sources.length === 0 && !isLoading && !devops?.configured && (
            <div className="px-3 py-4 text-xs text-gray-400 text-center">No services configured</div>
          )}

          <div className="py-1 max-h-64 overflow-y-auto">
            {sources.map((src) => {
              const isObo = src.auth_type === 'obo'
              const accessible = isObo ? entraLinked : true

              return (
                <div key={src.source_id} className="px-3 py-2 flex items-start gap-2.5 hover:bg-gray-50">
                  <StatusDot accessible={accessible} />
                  <div className="min-w-0 flex-1">
                    <div className="text-sm font-medium text-gray-800 truncate">{src.name}</div>
                    {src.detail && (
                      <div className="text-xs text-gray-500 font-mono truncate">{src.detail}</div>
                    )}
                    <div className="text-xs text-gray-400 mt-0.5">
                      {AUTH_LABELS[src.auth_type] || src.auth_type}
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}

export default DataSourcesMenu
