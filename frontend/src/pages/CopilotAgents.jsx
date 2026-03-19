/**
 * Copilot Agents Page - View ATK agents deployed to M365 Copilot
 */

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Bot,
  ChevronRight,
  ChevronDown,
  Clock,
  AlertCircle,
  Share2,
  CheckCircle,
  XCircle,
  Loader2,
} from 'lucide-react'

import { getAtkAgents, getAtkAgent } from '../services/api'
import PageHeader from '../components/shared/PageHeader'
import EmptyState from '../components/shared/EmptyState'

const statusConfig = {
  scaffolded: { label: 'Scaffolded', color: 'bg-gray-100 text-gray-700', dot: 'bg-gray-400' },
  provisioned: { label: 'Provisioned', color: 'bg-blue-100 text-blue-700', dot: 'bg-blue-500' },
  deployed: { label: 'Deployed', color: 'bg-green-100 text-green-700', dot: 'bg-green-500' },
  shared: { label: 'Shared', color: 'bg-purple-100 text-purple-700', dot: 'bg-purple-500' },
  uninstalled: { label: 'Uninstalled', color: 'bg-gray-100 text-gray-500', dot: 'bg-gray-400' },
  failed: { label: 'Failed', color: 'bg-red-100 text-red-700', dot: 'bg-red-500' },
}

const StatusBadge = ({ status }) => {
  const config = statusConfig[status] || statusConfig.scaffolded
  return (
    <span className={`inline-flex items-center px-2 py-1 rounded-full text-xs font-medium ${config.color}`}>
      <span className={`w-2 h-2 rounded-full mr-1.5 ${config.dot}`} />
      {config.label}
    </span>
  )
}

const AgentDetail = ({ agentId }) => {
  const { data: agent, isLoading, isError } = useQuery({
    queryKey: ['atk-agent', agentId],
    queryFn: () => getAtkAgent(agentId),
  })

  if (isLoading) {
    return (
      <div className="p-4 flex items-center justify-center text-gray-400">
        <Loader2 className="w-5 h-5 animate-spin mr-2" />
        Loading details...
      </div>
    )
  }

  if (isError || !agent) {
    return (
      <div className="p-4 text-red-500 text-sm">
        Failed to load agent details.
      </div>
    )
  }

  return (
    <div className="p-4 bg-gray-50/50 border-t border-gray-100 space-y-4">
      {/* M365 App ID */}
      {agent.m365_app_id && (
        <div>
          <span className="text-xs font-medium text-gray-500 uppercase tracking-wider">M365 App ID</span>
          <p className="text-sm text-gray-700 font-mono mt-0.5">{agent.m365_app_id}</p>
        </div>
      )}

      {/* Shares */}
      {agent.shares && agent.shares.length > 0 && (
        <div>
          <span className="text-xs font-medium text-gray-500 uppercase tracking-wider flex items-center">
            <Share2 className="w-3 h-3 mr-1" />
            Shared with ({agent.shares.length})
          </span>
          <ul className="mt-1 space-y-1">
            {agent.shares.map((share) => (
              <li key={share.id} className="text-sm text-gray-700 flex items-center">
                <span className="font-mono">{share.email}</span>
                <span className="text-gray-400 text-xs ml-2">({share.scope})</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Deployment History */}
      {agent.deployment_logs && agent.deployment_logs.length > 0 && (
        <div>
          <span className="text-xs font-medium text-gray-500 uppercase tracking-wider flex items-center">
            <Clock className="w-3 h-3 mr-1" />
            Deployment History ({agent.deployment_logs.length})
          </span>
          <div className="mt-1 space-y-1.5">
            {agent.deployment_logs.map((log) => (
              <div key={log.id} className="flex items-center text-sm">
                {log.status === 'success' ? (
                  <CheckCircle className="w-3.5 h-3.5 text-green-500 mr-1.5 flex-shrink-0" />
                ) : (
                  <XCircle className="w-3.5 h-3.5 text-red-500 mr-1.5 flex-shrink-0" />
                )}
                <span className="font-medium text-gray-700 capitalize">{log.action}</span>
                {log.environment && (
                  <span className="text-gray-400 text-xs ml-1.5">({log.environment})</span>
                )}
                <span className="text-gray-400 text-xs ml-auto">
                  {new Date(log.performed_at).toLocaleString()}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

const AgentCard = ({ agent }) => {
  const [expanded, setExpanded] = useState(false)

  return (
    <div className="bg-white rounded-xl border border-gray-100 overflow-hidden hover:border-gray-200 transition-colors">
      {/* Header row */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full p-4 flex items-center text-left hover:bg-gray-50/50 transition-colors"
      >
        <Bot className="w-5 h-5 text-blue-500 mr-3 flex-shrink-0" />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <h3 className="font-semibold text-gray-900 truncate">{agent.name}</h3>
            <StatusBadge status={agent.status} />
          </div>
          {agent.description && (
            <p className="text-sm text-gray-500 mt-0.5 line-clamp-1">{agent.description}</p>
          )}
        </div>
        <div className="flex items-center gap-3 ml-3">
          <span className="text-xs text-gray-400">{agent.environment}</span>
          <span className="text-xs text-gray-400">
            {new Date(agent.created_at).toLocaleDateString()}
          </span>
          {expanded ? (
            <ChevronDown className="w-4 h-4 text-gray-400" />
          ) : (
            <ChevronRight className="w-4 h-4 text-gray-400" />
          )}
        </div>
      </button>

      {/* Expandable detail */}
      {expanded && <AgentDetail agentId={agent.id} />}
    </div>
  )
}

const CopilotAgents = () => {
  const {
    data: agentsData,
    isLoading,
    isError,
    error,
    refetch,
  } = useQuery({
    queryKey: ['atk-agents'],
    queryFn: () => getAtkAgents(),
  })

  const agents = agentsData?.items ?? []

  return (
    <div className="space-y-6">
      <PageHeader title="Copilot Agents" subtitle="Declarative agents deployed to M365 Copilot via ATK CLI.">
        {!isLoading && <span className="text-sm text-gray-500">{agents.length} agents</span>}
      </PageHeader>

      {/* Loading */}
      {isLoading && (
        <div className="flex items-center justify-center h-64 text-gray-400">
          <Loader2 className="w-8 h-8 animate-spin" />
        </div>
      )}

      {/* Error */}
      {isError && (
        <div className="flex flex-col items-center justify-center h-64 text-red-500">
          <AlertCircle className="w-12 h-12 mb-2" />
          <p className="text-lg font-medium">Failed to load agents</p>
          <p className="text-sm text-red-400">{error?.message || 'An unexpected error occurred'}</p>
          <button
            onClick={() => refetch()}
            className="mt-4 px-4 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600 transition-colors"
          >
            Retry
          </button>
        </div>
      )}

      {/* Agent List */}
      {!isLoading && !isError && (
        <div className="space-y-3">
          {agents.map((agent) => (
            <AgentCard key={agent.id} agent={agent} />
          ))}

          {agents.length === 0 && (
            <EmptyState
              icon={Bot}
              title="No Copilot agents yet"
              description="Start a conversation in Chat to deploy your first agent to M365 Copilot."
              actionLabel="Go to Chat"
              actionTo="/chat"
            />
          )}
        </div>
      )}
    </div>
  )
}

export default CopilotAgents
