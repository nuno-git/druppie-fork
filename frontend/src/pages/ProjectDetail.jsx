/**
 * Project Detail Page
 *
 * APIs used:
 * - GET /api/projects/{id} - Project info (name, repo_url, token_usage, sessions)
 * - GET /api/deployments?project_id={id} - Running containers (Docker MCP bridge)
 * - POST /api/deployments/{container_name}/stop - Stop a deployment
 * - GET /api/deployments/{container_name}/logs - Container logs
 */

import { useState } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  ArrowLeft,
  GitBranch,
  MessageSquare,
  ExternalLink,
  Copy,
  CheckCircle,
  Loader2,
  AlertCircle,
  Play,
  Square,
  Server,
  RefreshCw,
  Calendar,
  Zap,
  FileText,
  Container,
} from 'lucide-react'

import {
  getProject,
  getDeployments,
  stopDeployment,
  getDeploymentLogs,
} from '../services/api'
import { useToast } from '../components/Toast'
import SharedCopyButton from '../components/shared/CopyButton'
import { SkeletonCard } from '../components/shared/Skeleton'

const formatTokens = (count) => {
  if (!count) return '0'
  if (count >= 1000000) return `${(count / 1000000).toFixed(1)}M`
  if (count >= 1000) return `${(count / 1000).toFixed(1)}K`
  return count.toString()
}

const TABS = {
  OVERVIEW: 'overview',
  CONVERSATIONS: 'conversations',
}

const CopyButton = SharedCopyButton

// Deployment card with status, app URL, logs, stop
const DeploymentCard = ({ deployment, onStop, isStopping, onViewLogs }) => {
  const isUp = deployment.status?.includes('Up')

  return (
    <div className="bg-gray-50/70 rounded-lg p-4 border border-gray-100">
      <div className="flex items-start justify-between">
        <div className="min-w-0 flex-1">
          <div className="flex items-center">
            <span className="font-medium text-gray-900 font-mono text-sm truncate">
              {deployment.container_name}
            </span>
            <span className={`ml-2 inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${
              isUp ? 'bg-green-100 text-green-700' : 'bg-yellow-100 text-yellow-700'
            }`}>
              {isUp && <span className="w-1.5 h-1.5 bg-green-500 rounded-full mr-1 animate-pulse" />}
              {deployment.status}
            </span>
          </div>
          <div className="mt-1 text-xs text-gray-500">
            Image: {deployment.image}
            {deployment.ports && <> | Ports: {deployment.ports}</>}
          </div>
          {deployment.app_url && (
            <div className="mt-2">
              <a
                href={deployment.app_url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center px-2.5 py-1 bg-green-50 text-green-700 text-sm rounded border border-green-200 hover:bg-green-100 transition-colors"
              >
                <Play className="w-3 h-3 mr-1.5" />
                {deployment.app_url}
                <ExternalLink className="w-3 h-3 ml-1.5 opacity-50" />
              </a>
            </div>
          )}
        </div>
        <div className="flex items-center space-x-1 ml-3">
          <button
            onClick={() => onViewLogs(deployment.container_name)}
            className="px-2.5 py-1.5 text-xs bg-gray-100 text-gray-700 rounded hover:bg-gray-200 transition-colors"
            aria-label="View logs"
          >
            <FileText className="w-3.5 h-3.5 inline mr-1" />
            Logs
          </button>
          <button
            onClick={() => onStop(deployment.container_name)}
            disabled={isStopping}
            className="px-2.5 py-1.5 text-xs bg-red-50 text-red-700 rounded hover:bg-red-100 disabled:opacity-50 transition-colors"
            aria-label="Stop container"
          >
            {isStopping ? (
              <Loader2 className="w-3.5 h-3.5 inline animate-spin" />
            ) : (
              <Square className="w-3.5 h-3.5 inline mr-1" />
            )}
            Stop
          </button>
        </div>
      </div>
    </div>
  )
}

// Logs modal
const LogsPanel = ({ containerName, onClose }) => {
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['deploymentLogs', containerName],
    queryFn: () => getDeploymentLogs(containerName, 200),
    enabled: !!containerName,
  })

  return (
    <div className="bg-white rounded-xl border border-gray-100 overflow-hidden">
      <div className="flex items-center justify-between px-4 py-3 bg-gray-50 border-b border-gray-200">
        <h4 className="text-sm font-medium text-gray-900 flex items-center">
          <FileText className="w-4 h-4 mr-2 text-gray-500" />
          Logs: <code className="ml-1 text-xs bg-gray-200 px-1.5 py-0.5 rounded">{containerName}</code>
        </h4>
        <div className="flex items-center space-x-2">
          <button
            onClick={() => refetch()}
            className="p-1.5 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded transition-colors"
            aria-label="Refresh logs"
          >
            <RefreshCw className="w-3.5 h-3.5" />
          </button>
          <button
            onClick={onClose}
            className="px-2 py-1 text-xs text-gray-500 hover:text-gray-700 hover:bg-gray-100 rounded transition-colors"
          >
            Close
          </button>
        </div>
      </div>
      <div className="max-h-80 overflow-auto">
        {isLoading ? (
          <div className="flex items-center justify-center py-8 text-gray-500">
            <Loader2 className="w-5 h-5 animate-spin mr-2" />
            Loading logs...
          </div>
        ) : error ? (
          <div className="p-4 text-sm text-red-500">Failed to load logs: {error.message}</div>
        ) : (
          <pre className="p-4 text-xs font-mono text-green-400 bg-gray-900 whitespace-pre-wrap leading-relaxed">
            {data?.logs || '(no logs)'}
          </pre>
        )}
      </div>
    </div>
  )
}

// Overview Tab
const OverviewTab = ({ project, deployments, onStop, stoppingName, onViewLogs, logsContainer, onCloseLogs }) => {
  const repoUrl = project?.repo_url
  const hasDeployments = deployments?.length > 0

  return (
    <div className="space-y-6">
      {/* Project Info */}
      <div className="bg-white rounded-xl p-6 border border-gray-100">
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <div>
            <span className="text-xs text-gray-500 uppercase tracking-wide">Created</span>
            <p className="text-gray-900 flex items-center mt-1">
              <Calendar className="w-4 h-4 mr-1.5 text-gray-400" />
              {project?.created_at ? new Date(project.created_at).toLocaleDateString() : 'N/A'}
            </p>
          </div>
          {project?.token_usage?.total_tokens > 0 && (
            <div>
              <span className="text-xs text-gray-500 uppercase tracking-wide">Token Usage</span>
              <p className="text-yellow-600 flex items-center font-medium mt-1" title={`Prompt: ${formatTokens(project.token_usage.prompt_tokens)} | Completion: ${formatTokens(project.token_usage.completion_tokens)}`}>
                <Zap className="w-4 h-4 mr-1.5 text-yellow-500" />
                {formatTokens(project.token_usage.total_tokens)}
                <span className="text-gray-400 text-xs ml-1.5 font-normal">
                  ({project.session_count} sessions)
                </span>
              </p>
            </div>
          )}
          {repoUrl && (
            <div>
              <span className="text-xs text-gray-500 uppercase tracking-wide">Repository</span>
              <div className="flex items-center mt-1">
                <GitBranch className="w-4 h-4 mr-1.5 text-gray-400 flex-shrink-0" />
                <a
                  href={repoUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-blue-600 hover:text-blue-800 hover:underline text-sm truncate"
                >
                  {project.repo_name || repoUrl}
                </a>
                <CopyButton text={repoUrl} label="repo URL" />
                <a
                  href={repoUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="p-1 text-gray-400 hover:text-blue-600 rounded transition-colors"
                >
                  <ExternalLink className="w-3.5 h-3.5" />
                </a>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Deployments */}
      <div className="bg-white rounded-xl p-6 border border-gray-100">
        <h3 className="text-sm font-medium text-gray-400 uppercase tracking-wide mb-4 flex items-center">
          <Container className="w-4 h-4 mr-2 text-gray-400" />
          Deployments
          {hasDeployments && (
            <span className="ml-2 px-2 py-0.5 bg-green-100 text-green-700 text-xs rounded-full font-medium">
              {deployments.length} running
            </span>
          )}
        </h3>

        {hasDeployments ? (
          <div className="space-y-3">
            {deployments.map((dep) => (
              <DeploymentCard
                key={dep.container_id}
                deployment={dep}
                onStop={onStop}
                isStopping={stoppingName === dep.container_name}
                onViewLogs={onViewLogs}
              />
            ))}
          </div>
        ) : (
          <div className="text-center py-8 text-gray-400">
            <Server className="w-10 h-10 mx-auto mb-2 opacity-30" />
            <p className="text-sm">No running deployments</p>
          </div>
        )}
      </div>

      {/* Logs Panel */}
      {logsContainer && (
        <LogsPanel containerName={logsContainer} onClose={onCloseLogs} />
      )}
    </div>
  )
}

// Conversations Tab
const ConversationsTab = ({ sessions }) => {
  const getStatusColor = (status) => {
    switch (status) {
      case 'completed': return 'bg-green-500'
      case 'active': return 'bg-yellow-500'
      case 'paused_approval': return 'bg-blue-500'
      case 'paused_hitl': return 'bg-blue-500'
      case 'paused_sandbox': return 'bg-blue-500'
      case 'paused_crashed': return 'bg-red-500'
      case 'failed': return 'bg-red-500'
      default: return 'bg-gray-500'
    }
  }

  return (
    <div className="bg-white rounded-xl p-6 border border-gray-100">
      <h3 className="text-sm font-medium text-gray-400 uppercase tracking-wide mb-4 flex items-center">
        <MessageSquare className="w-4 h-4 mr-2 text-gray-400" />
        Linked Conversations
        {sessions?.length > 0 && (
          <span className="ml-2 px-2 py-0.5 bg-gray-100 text-gray-500 text-xs rounded-full font-medium normal-case tracking-normal">
            {sessions.length}
          </span>
        )}
      </h3>

      {sessions?.length > 0 ? (
        <div className="space-y-3">
          {sessions.map((session) => (
            <Link
              key={session.id}
              to={`/chat?session=${session.id}`}
              className="block bg-gray-50/50 rounded-lg p-4 border border-gray-100 hover:border-gray-200 hover:bg-gray-50 transition-colors"
            >
              <div className="flex items-start justify-between">
                <div className="flex-1 min-w-0">
                  <p className="text-gray-900 truncate font-medium">
                    {session.title || 'Conversation'}
                  </p>
                  <div className="flex items-center mt-2 text-sm text-gray-500 space-x-4">
                    <span className="flex items-center">
                      <span className={`w-2 h-2 rounded-full mr-1.5 ${getStatusColor(session.status)}`} />
                      {session.status}
                    </span>
                    <span className="flex items-center">
                      <Calendar className="w-3 h-3 mr-1" />
                      {session.updated_at ? new Date(session.updated_at).toLocaleDateString() : 'N/A'}
                    </span>
                    {session.token_usage?.total_tokens > 0 && (
                      <span className="flex items-center text-yellow-600">
                        <Zap className="w-3 h-3 mr-1" />
                        {formatTokens(session.token_usage.total_tokens)}
                      </span>
                    )}
                  </div>
                </div>
                <ExternalLink className="w-4 h-4 text-gray-400 ml-4 flex-shrink-0" />
              </div>
            </Link>
          ))}
        </div>
      ) : (
        <div className="text-center py-8 text-gray-500">
          <MessageSquare className="w-12 h-12 mx-auto mb-3 opacity-30" />
          <p>No conversations linked to this project</p>
        </div>
      )}
    </div>
  )
}

// Main Component
const ProjectDetail = () => {
  const { projectId } = useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const toast = useToast()
  const [activeTab, setActiveTab] = useState(TABS.OVERVIEW)
  const [stoppingName, setStoppingName] = useState(null)
  const [logsContainer, setLogsContainer] = useState(null)

  // Project detail
  const { data: project, isLoading, error } = useQuery({
    queryKey: ['project', projectId],
    queryFn: () => getProject(projectId),
  })

  // Deployments from Docker MCP bridge
  const { data: deploymentsData } = useQuery({
    queryKey: ['deployments', projectId],
    queryFn: () => getDeployments(projectId),
    refetchInterval: 10000,
  })

  const deployments = deploymentsData?.items ?? []
  const hasRunning = deployments.some((d) => d.status?.includes('Up'))

  const stopMutation = useMutation({
    mutationFn: stopDeployment,
    onMutate: (name) => setStoppingName(name),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['deployments', projectId] })
      setStoppingName(null)
    },
    onError: (err) => {
      setStoppingName(null)
      toast.error('Stop Failed', `Could not stop container: ${err.message}`)
    },
  })

  const tabs = [
    { id: TABS.OVERVIEW, label: 'Overview', icon: Server },
    { id: TABS.CONVERSATIONS, label: 'Conversations', icon: MessageSquare },
  ]

  if (isLoading) {
    return (
      <div className="space-y-6">
        <div className="flex items-center gap-4">
          <div className="animate-pulse bg-gray-200 w-9 h-9 rounded-lg" />
          <div className="animate-pulse bg-gray-200 h-7 w-48 rounded" />
        </div>
        <SkeletonCard lines={4} />
        <SkeletonCard lines={3} />
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center h-96 text-red-500">
        <AlertCircle className="w-12 h-12 mb-2" />
        <p className="text-lg font-medium">Failed to load project</p>
        <p className="text-sm text-red-400">{error?.message || 'An unexpected error occurred'}</p>
        <button
          onClick={() => navigate('/projects')}
          className="mt-4 px-4 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600 transition-colors"
        >
          Back to Projects
        </button>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center space-x-4">
          <button
            onClick={() => navigate('/projects')}
            className="p-2 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-lg transition-colors"
            aria-label="Back to projects"
          >
            <ArrowLeft className="w-5 h-5" />
          </button>
          <h1 className="text-2xl font-bold text-gray-900">{project?.name}</h1>
        </div>
        {hasRunning && (
          <span className="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium bg-green-100 text-green-700">
            <span className="w-2 h-2 bg-green-500 rounded-full mr-1.5 animate-pulse" />
            Running
          </span>
        )}
      </div>

      {/* Tabs */}
      <div className="border-b border-gray-100">
        <nav className="flex space-x-1" aria-label="Tabs">
          {tabs.map((tab) => {
            const Icon = tab.icon
            return (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`px-4 py-2.5 text-sm font-medium rounded-t-lg transition-colors flex items-center ${
                  activeTab === tab.id
                    ? 'text-gray-900 border-b-2 border-gray-900'
                    : 'text-gray-400 hover:text-gray-600'
                }`}
              >
                <Icon className="w-4 h-4 mr-2" />
                {tab.label}
              </button>
            )
          })}
        </nav>
      </div>

      {/* Tab Content */}
      <div>
        {activeTab === TABS.OVERVIEW && (
          <OverviewTab
            project={project}
            deployments={deployments}
            onStop={(name) => stopMutation.mutate(name)}
            stoppingName={stoppingName}
            onViewLogs={(name) => setLogsContainer(name)}
            logsContainer={logsContainer}
            onCloseLogs={() => setLogsContainer(null)}
          />
        )}
        {activeTab === TABS.CONVERSATIONS && <ConversationsTab sessions={project?.sessions} />}
      </div>
    </div>
  )
}

export default ProjectDetail
