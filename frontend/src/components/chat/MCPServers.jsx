import React, { useState } from 'react'
import { Globe, CheckCircle, XCircle, AlertCircle, ChevronDown, ChevronUp } from 'lucide-react'
import { getMCPServers } from '../../services/api'

const MCPServers = () => {
  const [servers, setServers] = useState([])
  const [loading, setLoading] = useState(true)
  const [expanded, setExpanded] = useState(false)

  React.useEffect(() => {
    const fetchServers = async () => {
      try {
        const data = await getMCPServers()
        setServers(data)
      } catch (error) {
        console.error('Failed to fetch MCP servers:', error)
      } finally {
        setLoading(false)
      }
    }
    fetchServers()
    const interval = setInterval(fetchServers, 30000)
    return () => clearInterval(interval)
  }, [])

  const getStatusIcon = (status) => {
    switch (status) {
      case 'healthy':
        return <CheckCircle className="w-4 h-4 text-green-500" />
      case 'unhealthy':
        return <XCircle className="w-4 h-4 text-red-500" />
      default:
        return <AlertCircle className="w-4 h-4 text-yellow-500" />
    }
  }

  if (loading) {
    return (
      <div className="px-4 py-2 bg-gray-50 border-t border-gray-200">
        <div className="flex items-center gap-2 text-sm text-gray-500">
          <Globe className="w-4 h-4 animate-spin" />
          Loading MCP servers...
        </div>
      </div>
    )
  }

  return (
    <div className="px-4 py-2 bg-gray-50 border-t border-gray-200">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-2 w-full text-left"
      >
        <Globe className="w-4 h-4 text-blue-600" />
        <span className="text-sm font-medium text-gray-700">MCP Servers</span>
        <span className="text-xs text-gray-500">({servers.length})</span>
        {expanded ? (
          <ChevronUp className="w-4 h-4 text-gray-500 ml-auto" />
        ) : (
          <ChevronDown className="w-4 h-4 text-gray-500 ml-auto" />
        )}
      </button>

      {expanded && (
        <div className="mt-2 space-y-1">
          {servers.map((server) => (
            <div
              key={server.id}
              className="flex items-center justify-between px-3 py-2 bg-white rounded-lg border border-gray-200"
            >
              <div className="flex items-center gap-3">
                {getStatusIcon(server.status)}
                <div>
                  <div className="text-sm font-medium text-gray-900">{server.name}</div>
                  <div className="text-xs text-gray-500">{server.description}</div>
                </div>
              </div>
              <span className="text-xs text-gray-400">{server.status}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export default MCPServers
