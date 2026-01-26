/**
 * Settings Page - Admin Configuration
 */

import React from 'react'
import { useQuery } from '@tanstack/react-query'
import { User, Server, Bot, Info, Shield, CheckCircle, XCircle, RefreshCw, Cpu, Thermometer, Zap } from 'lucide-react'
import { getMCPServers, getMCPTools, getStatus, getAgents } from '../services/api'
import { useAuth } from '../App'

const SectionCard = ({ title, icon: Icon, children }) => (
  <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
    <div className="flex items-center space-x-2 mb-4">
      <Icon className="w-5 h-5 text-gray-600" />
      <h2 className="text-lg font-semibold">{title}</h2>
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

const Settings = () => {
  const { user } = useAuth()

  const {
    data: mcpServers = [],
    isLoading: mcpLoading,
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
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold">Settings</h1>
        <p className="text-gray-500 mt-1">System configuration and status information.</p>
      </div>

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

      {/* MCP Servers */}
      <SectionCard title="MCP Servers" icon={Server}>
        <div className="flex items-center justify-between mb-4">
          <p className="text-gray-500 text-sm">
            Model Context Protocol servers provide tools for agents to interact with the system.
          </p>
          <button
            onClick={() => refetchMCPs()}
            className="text-blue-600 hover:text-blue-700 text-sm flex items-center"
          >
            <RefreshCw className={`w-4 h-4 mr-1 ${mcpLoading ? 'animate-spin' : ''}`} />
            Refresh
          </button>
        </div>

        {mcpLoading ? (
          <div className="text-gray-500">Loading MCP servers...</div>
        ) : mcpServers.length === 0 ? (
          <div className="text-gray-500">No MCP servers configured.</div>
        ) : (
          <div className="space-y-4">
            {mcpServers.map((server) => (
              <div
                key={server.name}
                className="border rounded-lg p-4 hover:bg-gray-50 transition-colors"
              >
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center space-x-2">
                    <Server className="w-4 h-4 text-gray-600" />
                    <span className="font-medium">{server.name}</span>
                  </div>
                  <StatusBadge status={server.status || true} />
                </div>
                <p className="text-sm text-gray-500 mb-3">{server.description}</p>

                {/* Tools for this server */}
                {toolsByServer[server.name] && toolsByServer[server.name].length > 0 && (
                  <div className="mt-3 pt-3 border-t">
                    <p className="text-xs text-gray-400 mb-2">Available Tools</p>
                    <div className="flex flex-wrap gap-1">
                      {toolsByServer[server.name].map((tool) => (
                        <span
                          key={tool.name}
                          className="px-2 py-0.5 bg-gray-100 text-gray-600 rounded text-xs"
                          title={tool.description}
                        >
                          {tool.name}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </SectionCard>

      {/* Agents */}
      <SectionCard title="Configured Agents" icon={Bot}>
        <div className="flex items-center justify-between mb-4">
          <p className="text-gray-500 text-sm">
            Agents are AI assistants with specific capabilities. Model info shown for transparency.
          </p>
          <button
            onClick={() => refetchAgents()}
            className="text-blue-600 hover:text-blue-700 text-sm flex items-center"
          >
            <RefreshCw className={`w-4 h-4 mr-1 ${agentsLoading ? 'animate-spin' : ''}`} />
            Refresh
          </button>
        </div>

        {agentsLoading ? (
          <div className="text-gray-500">Loading agents...</div>
        ) : agentsList.length === 0 ? (
          <div className="text-gray-500">No agents configured.</div>
        ) : (
          <div className="space-y-4">
            {agentsList.map((agent) => {
              const categoryColors = {
                system: { bg: 'bg-blue-100', text: 'text-blue-700', icon: 'text-blue-600' },
                execution: { bg: 'bg-green-100', text: 'text-green-700', icon: 'text-green-600' },
                quality: { bg: 'bg-orange-100', text: 'text-orange-700', icon: 'text-orange-600' },
                deployment: { bg: 'bg-purple-100', text: 'text-purple-700', icon: 'text-purple-600' },
              }
              const colors = categoryColors[agent.category] || categoryColors.execution

              return (
                <div key={agent.id} className="border rounded-lg p-4 hover:bg-gray-50 transition-colors">
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center space-x-2">
                      <Bot className={`w-4 h-4 ${colors.icon}`} />
                      <span className="font-medium">{agent.name}</span>
                    </div>
                    <span className={`px-2 py-0.5 ${colors.bg} ${colors.text} rounded text-xs capitalize`}>
                      {agent.category}
                    </span>
                  </div>
                  <p className="text-sm text-gray-500 mb-3">{agent.description}</p>

                  {/* Model Info (Transparency) */}
                  {agent.model && (
                    <div className="flex flex-wrap gap-2 mb-3 p-2 bg-yellow-50 border border-yellow-200 rounded">
                      <span className="flex items-center text-xs text-yellow-800" title="LLM Model">
                        <Cpu className="w-3 h-3 mr-1" />
                        {agent.model}
                      </span>
                      {agent.temperature !== null && (
                        <span className="flex items-center text-xs text-yellow-700" title="Temperature">
                          <Thermometer className="w-3 h-3 mr-1" />
                          temp: {agent.temperature}
                        </span>
                      )}
                      {agent.max_tokens && (
                        <span className="flex items-center text-xs text-yellow-700" title="Max Tokens">
                          <Zap className="w-3 h-3 mr-1" />
                          max: {agent.max_tokens}
                        </span>
                      )}
                    </div>
                  )}

                  {/* MCP Tools */}
                  {agent.mcps && agent.mcps.length > 0 && (
                    <div className="mt-2">
                      <p className="text-xs text-gray-400 mb-1">MCP Access</p>
                      <div className="flex flex-wrap gap-1">
                        {agent.mcps.map((mcp) => (
                          <span
                            key={mcp}
                            className="px-2 py-0.5 bg-gray-100 text-gray-600 rounded text-xs"
                          >
                            {mcp}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </SectionCard>
    </div>
  )
}

export default Settings
