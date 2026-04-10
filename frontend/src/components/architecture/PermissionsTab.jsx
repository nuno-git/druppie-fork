import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ChevronDown, ChevronRight, Server, Shield } from 'lucide-react'
import AskArchitectFooter from './AskArchitectFooter'
import { getArchitecturePermissions, getMCPServers } from '../../services/api'

const ServerRow = ({ server }) => {
  const [expanded, setExpanded] = useState(false)
  const isHealthy = server.status === 'healthy'

  return (
    <div className="rounded-lg hover:bg-gray-50/50 transition-colors">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-3 px-3 py-2.5 text-left"
      >
        <div className={`w-2 h-2 rounded-full flex-shrink-0 ${isHealthy ? 'bg-green-500' : 'bg-red-500'}`} />
        <span className="font-medium text-sm text-gray-900 flex-1">{server.name}</span>
        <span className="text-xs text-gray-400">{server.url?.match(/:(\d+)/)?.[0] || ''}</span>
        <span className={`text-xs px-2 py-0.5 rounded-full ${
          isHealthy ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'
        }`}>
          {server.status}
        </span>
        {expanded ? <ChevronDown className="w-3.5 h-3.5 text-gray-400" /> : <ChevronRight className="w-3.5 h-3.5 text-gray-400" />}
      </button>
      {expanded && (
        <div className="px-3 pb-3 pl-8">
          <div className="text-xs text-gray-500 mb-1">URL: {server.url}</div>
          <div className="text-xs text-gray-400">ID: {server.id}</div>
        </div>
      )}
    </div>
  )
}

const PermissionDot = ({ hasAccess, requiresApproval, requiredRole }) => {
  if (!hasAccess) {
    return <span className="text-gray-300" title="Geen toegang">-</span>
  }
  if (requiresApproval) {
    return (
      <span
        className="inline-block w-2.5 h-2.5 rounded-full bg-amber-500 cursor-help"
        title={`Approval vereist${requiredRole ? ` (rol: ${requiredRole})` : ''}`}
      />
    )
  }
  return (
    <span
      className="inline-block w-2.5 h-2.5 rounded-full bg-green-500 cursor-help"
      title="Toegang zonder approval"
    />
  )
}

const PermissionsTab = () => {
  const { data: permData, isLoading: permLoading } = useQuery({
    queryKey: ['architecture-permissions'],
    queryFn: getArchitecturePermissions,
  })

  const { data: mcpData } = useQuery({
    queryKey: ['architecture-mcp-servers'],
    queryFn: getMCPServers,
  })

  const mcpServers = Array.isArray(mcpData) ? mcpData : (mcpData?.servers || [])
  const entries = permData?.entries || []
  const agents = permData?.agents || []
  const servers = permData?.servers || {}

  // Build lookup: `${agent}:${server}:${tool}` -> entry
  const lookup = {}
  entries.forEach(e => {
    lookup[`${e.agent_id}:${e.server}:${e.tool}`] = e
  })

  // Short agent names for table header
  const shortName = (id) => {
    const parts = id.split('_')
    if (parts.length === 1) return id.charAt(0).toUpperCase() + id.slice(1)
    return parts.map(p => p.charAt(0).toUpperCase()).join('')
  }

  return (
    <div className="space-y-8">
      {/* MCP Servers */}
      <div className="bg-white rounded-xl border border-gray-100 p-6">
        <div className="flex items-center space-x-2 mb-4">
          <Server className="w-4 h-4 text-gray-400" />
          <h2 className="text-sm font-medium text-gray-400 uppercase tracking-wide">MCP Servers</h2>
        </div>
        <div className="space-y-0.5">
          {mcpServers.map(server => (
            <ServerRow key={server.id} server={server} />
          ))}
          {mcpServers.length === 0 && (
            <p className="text-sm text-gray-400 py-2">Laden...</p>
          )}
        </div>
      </div>

      {/* Permission Matrix */}
      <div className="bg-white rounded-xl border border-gray-100 p-6">
        <div className="flex items-center space-x-2 mb-4">
          <Shield className="w-4 h-4 text-gray-400" />
          <h2 className="text-sm font-medium text-gray-400 uppercase tracking-wide">Permissie Matrix</h2>
        </div>

        {permLoading ? (
          <div className="animate-pulse space-y-2">
            {Array.from({ length: 5 }).map((_, i) => (
              <div key={i} className="h-8 bg-gray-100 rounded" />
            ))}
          </div>
        ) : agents.length > 0 ? (
          <>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-100">
                    <th className="text-left px-3 py-2 text-xs font-medium text-gray-500 uppercase tracking-wide sticky left-0 bg-white min-w-[140px]">
                      Tool
                    </th>
                    {agents.map(agent => (
                      <th
                        key={agent}
                        className="text-center px-2 py-2 text-xs font-medium text-gray-500 uppercase tracking-wide"
                        title={agent}
                      >
                        {shortName(agent)}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(servers).map(([serverId, tools]) => (
                    <>
                      {/* Server header row */}
                      <tr key={`header-${serverId}`}>
                        <td
                          colSpan={agents.length + 1}
                          className="px-3 py-2 text-xs font-semibold text-gray-700 bg-gray-50/50 uppercase"
                        >
                          {serverId}
                        </td>
                      </tr>
                      {/* Tool rows */}
                      {tools.map(tool => (
                        <tr key={`${serverId}:${tool}`} className="border-b border-gray-50 hover:bg-blue-50/30">
                          <td className="px-3 py-2 text-xs font-mono text-gray-600 sticky left-0 bg-white">
                            {tool}
                          </td>
                          {agents.map(agent => {
                            const entry = lookup[`${agent}:${serverId}:${tool}`]
                            return (
                              <td key={agent} className="text-center px-2 py-2">
                                <PermissionDot
                                  hasAccess={entry?.has_access || false}
                                  requiresApproval={entry?.requires_approval || false}
                                  requiredRole={entry?.required_role}
                                />
                              </td>
                            )
                          })}
                        </tr>
                      ))}
                    </>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Legend */}
            <div className="flex items-center gap-6 mt-4 pt-4 border-t border-gray-100">
              <div className="flex items-center gap-2 text-xs text-gray-500">
                <span className="inline-block w-2.5 h-2.5 rounded-full bg-green-500" />
                Toegang zonder approval
              </div>
              <div className="flex items-center gap-2 text-xs text-gray-500">
                <span className="inline-block w-2.5 h-2.5 rounded-full bg-amber-500" />
                Approval vereist
              </div>
              <div className="flex items-center gap-2 text-xs text-gray-500">
                <span className="text-gray-300">-</span>
                Geen toegang
              </div>
            </div>
          </>
        ) : (
          <p className="text-sm text-gray-400">Geen permissie data beschikbaar.</p>
        )}
      </div>

      <AskArchitectFooter />
    </div>
  )
}

export default PermissionsTab
