/**
 * Settings Page - Admin Configuration
 */

import React, { useState, useEffect, useCallback } from 'react'
import { useQuery } from '@tanstack/react-query'
import { User, Server, Bot, Info, Shield, CheckCircle, XCircle, RefreshCw, Cpu, ChevronDown, ChevronRight, Cloud } from 'lucide-react'
import { getMCPServers, getMCPTools, getStatus, getAgents, getFoundryStatus } from '../services/api'
import { useAuth } from '../App'
import PageHeader from '../components/shared/PageHeader'
import { SkeletonSettingsSection } from '../components/shared/Skeleton'

const SectionCard = ({ title, icon: Icon, children }) => (
  <div className="bg-white rounded-xl border border-gray-100 p-6">
    <div className="flex items-center space-x-2 mb-4">
      <Icon className="w-4 h-4 text-gray-400" />
      <h2 className="text-sm font-medium text-gray-400 uppercase tracking-wide">{title}</h2>
    </div>
    {children}
  </div>
)

const StatusBadge = ({ status }) => {
  const isHealthy = status === true || status === 'healthy' || status === 'running'
  return (
    <span
      className={`inline-flex items-center px-2 py-1 rounded-full text-xs font-medium ${
        isHealthy ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'
      }`}
    >
      {isHealthy ? (
        <CheckCircle className="w-3 h-3 mr-1" />
      ) : (
        <XCircle className="w-3 h-3 mr-1" />
      )}
      {isHealthy ? 'Healthy' : 'Unavailable'}
    </span>
  )
}

// Compact server row — expand to show tools
const ServerRow = ({ server, tools }) => {
  const [expanded, setExpanded] = useState(false)
  const isHealthy = server.status === true || server.status === 'healthy' || !server.status
  const toolCount = tools?.length || 0

  return (
    <div className="rounded-lg hover:bg-gray-50/50 transition-colors">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-3 px-3 py-2.5 text-left"
      >
        <div className={`w-2 h-2 rounded-full flex-shrink-0 ${isHealthy ? 'bg-green-500' : 'bg-red-500'}`} />
        <span className="font-medium text-sm text-gray-900 flex-1">{server.name}</span>
        {toolCount > 0 && (
          <span className="text-xs text-gray-400">{toolCount} tools</span>
        )}
        {toolCount > 0 && (expanded ? <ChevronDown className="w-3.5 h-3.5 text-gray-400" /> : <ChevronRight className="w-3.5 h-3.5 text-gray-400" />)}
      </button>
      {expanded && tools && tools.length > 0 && (
        <div className="px-3 pb-2.5 pl-8">
          <div className="flex flex-wrap gap-1">
            {tools.map((tool) => (
              <span key={tool.name} className="px-2 py-0.5 bg-gray-100 text-gray-500 rounded text-xs" title={tool.description}>
                {tool.name}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

// Compact agent row — expand to show model info + MCPs
const AgentRow = ({ agent }) => {
  const [expanded, setExpanded] = useState(false)
  const categoryColors = {
    system: 'text-blue-600', execution: 'text-green-600',
    quality: 'text-orange-600', deployment: 'text-purple-600',
  }
  const color = categoryColors[agent.category] || 'text-gray-600'

  return (
    <div className="rounded-lg hover:bg-gray-50/50 transition-colors">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-3 px-3 py-2.5 text-left"
      >
        <Bot className={`w-4 h-4 flex-shrink-0 ${color}`} />
        <span className="font-medium text-sm text-gray-900 flex-1">{agent.name}</span>
        <span className="text-xs text-gray-400 capitalize">{agent.category}</span>
        {expanded ? <ChevronDown className="w-3.5 h-3.5 text-gray-400" /> : <ChevronRight className="w-3.5 h-3.5 text-gray-400" />}
      </button>
      {expanded && (
        <div className="px-3 pb-2.5 pl-11 space-y-2">
          <p className="text-xs text-gray-500">{agent.description}</p>
          {agent.model && (
            <div className="flex flex-wrap gap-3 text-xs text-gray-400">
              <span className="flex items-center"><Cpu className="w-3 h-3 mr-1" />{agent.model}</span>
              {agent.temperature !== null && <span>temp: {agent.temperature}</span>}
              {agent.max_tokens && <span>max: {agent.max_tokens}</span>}
            </div>
          )}
          {agent.mcps?.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {agent.mcps.map((mcp) => (
                <span key={mcp} className="px-2 py-0.5 bg-gray-100 text-gray-500 rounded text-xs">{mcp}</span>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

const FoundryStatusSection = () => {
  const [status, setStatus] = useState('loading')
  const [detail, setDetail] = useState(null)
  const [endpoint, setEndpoint] = useState(null)

  const checkStatus = useCallback(async () => {
    try {
      const result = await getFoundryStatus()
      setStatus(result.status)
      setDetail(result.detail || null)
      setEndpoint(result.endpoint || null)
    } catch {
      setStatus('error')
      setDetail('Could not reach backend')
    }
  }, [])

  useEffect(() => { checkStatus() }, [checkStatus])

  return (
    <SectionCard title="Azure AI Foundry" icon={Cloud}>
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <span className="text-sm text-gray-500">Connection Status</span>
          {status === 'loading' ? (
            <span className="text-xs text-gray-400">Checking...</span>
          ) : status === 'configured' ? (
            <span className="inline-flex items-center px-2 py-1 rounded-full text-xs font-medium bg-green-100 text-green-700">
              <CheckCircle className="w-3 h-3 mr-1" />
              Configured
            </span>
          ) : (
            <span className="inline-flex items-center px-2 py-1 rounded-full text-xs font-medium bg-gray-100 text-gray-500">
              <XCircle className="w-3 h-3 mr-1" />
              Not configured
            </span>
          )}
        </div>

        {endpoint && (
          <div className="text-xs text-gray-500 truncate">
            Endpoint: <span className="font-mono">{endpoint}</span>
          </div>
        )}

        {detail && status !== 'configured' && (
          <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-3">
            <p className="text-sm text-yellow-700">{detail}</p>
          </div>
        )}

        <p className="text-xs text-gray-400">
          Agent deployment uses DefaultAzureCredential (az login, managed identity) or FOUNDRY_API_KEY.
        </p>
      </div>
    </SectionCard>
  )
}

const Settings = () => {
  const { user } = useAuth()

  const {
    data: mcpServers = [],
    isLoading: mcpLoading,
    isError: mcpError,
    refetch: refetchMCPs,
  } = useQuery({
    queryKey: ['mcp-servers'],
    queryFn: getMCPServers,
  })

  const { data: mcpTools = [] } = useQuery({
    queryKey: ['mcp-tools'],
    queryFn: getMCPTools,
  })

  const {
    data: status,
    isLoading: statusLoading,
    refetch: refetchStatus,
  } = useQuery({
    queryKey: ['status'],
    queryFn: getStatus,
    refetchInterval: 30000,
  })

  const {
    data: agentsList = [],
    isLoading: agentsLoading,
    isError: agentsError,
    refetch: refetchAgents,
  } = useQuery({
    queryKey: ['agents'],
    queryFn: getAgents,
  })

  // Group tools by server
  const toolsByServer = mcpTools.reduce((acc, tool) => {
    const server = tool.server || 'unknown'
    if (!acc[server]) acc[server] = []
    acc[server].push(tool)
    return acc
  }, {})

  return (
    <div className="space-y-8">
      <PageHeader title="Settings" subtitle="System configuration and status information." />

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* User Profile */}
        <SectionCard title="User Profile" icon={User}>
          <div className="space-y-4">
            <div className="flex items-center space-x-4">
              <div className="w-16 h-16 bg-blue-100 rounded-full flex items-center justify-center">
                <User className="w-8 h-8 text-blue-600" />
              </div>
              <div>
                <p className="font-semibold text-lg">
                  {user?.firstName} {user?.lastName}
                </p>
                <p className="text-gray-500">@{user?.username}</p>
                {user?.email && <p className="text-gray-400 text-sm">{user?.email}</p>}
              </div>
            </div>

            <div className="border-t pt-4">
              <p className="text-sm text-gray-500 mb-2">Assigned Roles</p>
              <div className="flex flex-wrap gap-2">
                {user?.roles?.length > 0 ? (
                  user.roles.map((role) => (
                    <span
                      key={role}
                      className={`px-3 py-1 rounded-full text-sm ${
                        role === 'admin'
                          ? 'bg-purple-100 text-purple-700'
                          : role === 'infra-engineer'
                          ? 'bg-orange-100 text-orange-700'
                          : role === 'architect'
                          ? 'bg-blue-100 text-blue-700'
                          : role === 'developer'
                          ? 'bg-green-100 text-green-700'
                          : role === 'product-owner'
                          ? 'bg-pink-100 text-pink-700'
                          : role === 'compliance-officer'
                          ? 'bg-red-100 text-red-700'
                          : 'bg-gray-100 text-gray-700'
                      }`}
                    >
                      <Shield className="w-3 h-3 inline mr-1" />
                      {role}
                    </span>
                  ))
                ) : (
                  <span className="text-gray-400">No roles assigned</span>
                )}
              </div>
            </div>
          </div>
        </SectionCard>

        {/* System Info */}
        <SectionCard title="System Info" icon={Info}>
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <span className="text-gray-500">Status</span>
              <button
                onClick={() => refetchStatus()}
                className="text-blue-600 hover:text-blue-700 text-sm flex items-center"
              >
                <RefreshCw className={`w-4 h-4 mr-1 ${statusLoading ? 'animate-spin' : ''}`} />
                Refresh
              </button>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div className="p-3 bg-gray-50 rounded-lg">
                <p className="text-sm text-gray-500">Keycloak</p>
                <StatusBadge status={status?.keycloak} />
              </div>
              <div className="p-3 bg-gray-50 rounded-lg">
                <p className="text-sm text-gray-500">Database</p>
                <StatusBadge status={status?.database} />
              </div>
              <div className="p-3 bg-gray-50 rounded-lg">
                <p className="text-sm text-gray-500">LLM Service</p>
                <StatusBadge status={status?.llm} />
              </div>
              <div className="p-3 bg-gray-50 rounded-lg">
                <p className="text-sm text-gray-500">Gitea</p>
                <StatusBadge status={status?.gitea} />
              </div>
            </div>

            <div className="border-t pt-4 space-y-2">
              <div className="flex justify-between text-sm">
                <span className="text-gray-500">Environment</span>
                <span className="font-medium">{status?.environment || 'development'}</span>
              </div>
              <div className="flex justify-between text-sm">
                <span className="text-gray-500">Version</span>
                <span className="font-medium">{status?.version || '2.0.0'}</span>
              </div>
              <div className="flex justify-between text-sm">
                <span className="text-gray-500">LLM Provider</span>
                <span className="font-medium">{status?.llm_provider || 'auto'}</span>
              </div>
              {status?.llm_model && (
                <div className="flex justify-between text-sm">
                  <span className="text-gray-500">LLM Model</span>
                  <span className="font-medium text-xs truncate max-w-[200px]" title={status.llm_model}>{status.llm_model}</span>
                </div>
              )}
            </div>
          </div>
        </SectionCard>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* MCP Servers */}
        <SectionCard title={`MCP Servers (${mcpServers.length})`} icon={Server}>
          {mcpLoading ? (
            <SkeletonSettingsSection />
          ) : mcpError ? (
            <div className="text-center py-4">
              <p className="text-sm text-red-500 mb-2">Failed to load MCP servers</p>
              <button onClick={() => refetchMCPs()} className="text-sm text-blue-600 hover:text-blue-700 font-medium">Retry</button>
            </div>
          ) : mcpServers.length === 0 ? (
            <div className="text-gray-400 text-sm">No MCP servers configured.</div>
          ) : (
            <div className="space-y-1">
              {mcpServers.map((server) => (
                <ServerRow key={server.name} server={server} tools={toolsByServer[server.name]} />
              ))}
            </div>
          )}
        </SectionCard>

        {/* Agents */}
        <SectionCard title={`Agents (${agentsList.length})`} icon={Bot}>
          {agentsLoading ? (
            <SkeletonSettingsSection />
          ) : agentsError ? (
            <div className="text-center py-4">
              <p className="text-sm text-red-500 mb-2">Failed to load agents</p>
              <button onClick={() => refetchAgents()} className="text-sm text-blue-600 hover:text-blue-700 font-medium">Retry</button>
            </div>
          ) : agentsList.length === 0 ? (
            <div className="text-gray-400 text-sm">No agents configured.</div>
          ) : (
            <div className="space-y-1">
              {agentsList.map((agent) => (
                <AgentRow key={agent.id} agent={agent} />
              ))}
            </div>
          )}
        </SectionCard>
      </div>

      {/* Azure AI Foundry Authentication */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <FoundryStatusSection />
      </div>
    </div>
  )
}

export default Settings
