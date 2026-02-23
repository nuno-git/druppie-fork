/**
 * Plans Page
 */

import React from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Link, useSearchParams } from 'react-router-dom'
import { FileText, Clock, CheckCircle, XCircle, Play, AlertCircle, ExternalLink, GitBranch, Box, StopCircle } from 'lucide-react'
import { getPlans, getPlan, buildProject, runProject, stopProject, getProjectStatus } from '../services/api'
import PageHeader from '../components/shared/PageHeader'
import { SkeletonListItem, SkeletonCard } from '../components/shared/Skeleton'
import EmptyState from '../components/shared/EmptyState'

const StatusBadge = ({ status }) => {
  const config = {
    pending: { icon: Clock, bg: 'bg-gray-100', text: 'text-gray-700' },
    pending_approval: { icon: AlertCircle, bg: 'bg-blue-100', text: 'text-blue-700' },
    running: { icon: Play, bg: 'bg-blue-100', text: 'text-blue-700' },
    completed: { icon: CheckCircle, bg: 'bg-green-100', text: 'text-green-700' },
    failed: { icon: XCircle, bg: 'bg-red-100', text: 'text-red-700' },
  }

  const { icon: Icon, bg, text } = config[status] || config.pending

  return (
    <span className={`px-2 py-1 rounded-full text-xs flex items-center ${bg} ${text}`}>
      <Icon className="w-3 h-3 mr-1" />
      {status}
    </span>
  )
}

const PlanDetail = ({ planId }) => {
  const queryClient = useQueryClient()

  const { data: plan, isLoading, error } = useQuery({
    queryKey: ['plan', planId],
    queryFn: () => getPlan(planId),
    enabled: !!planId,
    refetchInterval: 5000,
  })

  const { data: projectStatus } = useQuery({
    queryKey: ['projectStatus', planId],
    queryFn: () => getProjectStatus(planId),
    enabled: !!planId,
    refetchInterval: 5000,
  })

  const buildMutation = useMutation({
    mutationFn: () => buildProject(planId),
    onSuccess: () => queryClient.invalidateQueries(['projectStatus', planId]),
  })

  const runMutation = useMutation({
    mutationFn: () => runProject(planId),
    onSuccess: () => {
      queryClient.invalidateQueries(['projectStatus', planId])
      queryClient.invalidateQueries(['plan', planId])
    },
  })

  const stopMutation = useMutation({
    mutationFn: () => stopProject(planId),
    onSuccess: () => queryClient.invalidateQueries(['projectStatus', planId]),
  })

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <div className="w-8 h-8 border-4 border-blue-600 border-t-transparent rounded-full animate-spin" />
      </div>
    )
  }

  if (error) {
    return (
      <div className="text-center py-12">
        <XCircle className="w-12 h-12 text-red-500 mx-auto mb-4" />
        <p className="text-red-500">Error loading plan: {error.message}</p>
      </div>
    )
  }

  if (!plan) return null

  const repoUrl = plan.result?.repo_url
  const appUrl = plan.result?.app_url || projectStatus?.url
  const isRunning = projectStatus?.status === 'running'
  const isBuilt = projectStatus?.status === 'built' || projectStatus?.status === 'running'

  return (
    <div className="bg-white rounded-xl border border-gray-100 p-6">
      <div className="flex items-start justify-between mb-6">
        <div>
          <h2 className="text-xl font-bold">{plan.name}</h2>
          <p className="text-gray-500 mt-1">{plan.description}</p>
        </div>
        <StatusBadge status={plan.status} />
      </div>

      {/* Project Links */}
      {(repoUrl || appUrl) && (
        <div className="bg-gray-50 p-4 rounded-lg mb-6">
          <h3 className="text-sm font-medium text-gray-500 mb-3 flex items-center">
            <Box className="w-4 h-4 mr-2 text-gray-400" />
            Project Links
          </h3>
          <div className="flex flex-wrap gap-3">
            {repoUrl && (
              <a
                href={repoUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center px-4 py-2 bg-white rounded-lg border border-gray-100 hover:border-gray-200 transition-colors"
              >
                <GitBranch className="w-4 h-4 mr-2 text-gray-600" />
                <span className="font-medium">View Repository</span>
                <ExternalLink className="w-3 h-3 ml-2 text-gray-400" />
              </a>
            )}
            {appUrl && (
              <a
                href={appUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center px-4 py-2 bg-green-500 text-white rounded-lg hover:bg-green-600 transition-colors"
              >
                <Play className="w-4 h-4 mr-2" />
                <span className="font-medium">Open App</span>
                <ExternalLink className="w-3 h-3 ml-2" />
              </a>
            )}
          </div>
        </div>
      )}

      {/* Build & Run Controls */}
      {plan.status === 'completed' && (
        <div className="bg-gray-50 p-4 rounded-lg mb-6">
          <h3 className="font-semibold mb-3 flex items-center">
            <Box className="w-4 h-4 mr-2" />
            Build & Deploy
          </h3>
          <div className="flex flex-wrap items-center gap-3">
            {projectStatus && (
              <span className={`px-3 py-1 rounded-full text-sm ${
                isRunning ? 'bg-green-100 text-green-700' :
                isBuilt ? 'bg-blue-100 text-blue-700' :
                'bg-gray-100 text-gray-700'
              }`}>
                Status: {projectStatus.status || 'not built'}
              </span>
            )}
            {!isBuilt && (
              <button
                onClick={() => buildMutation.mutate()}
                disabled={buildMutation.isPending}
                className="flex items-center px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50"
              >
                {buildMutation.isPending ? (
                  <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin mr-2" />
                ) : (
                  <Box className="w-4 h-4 mr-2" />
                )}
                Build
              </button>
            )}
            {isBuilt && !isRunning && (
              <button
                onClick={() => runMutation.mutate()}
                disabled={runMutation.isPending}
                className="flex items-center px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:opacity-50"
              >
                {runMutation.isPending ? (
                  <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin mr-2" />
                ) : (
                  <Play className="w-4 h-4 mr-2" />
                )}
                Run
              </button>
            )}
            {isRunning && (
              <button
                onClick={() => stopMutation.mutate()}
                disabled={stopMutation.isPending}
                className="flex items-center px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:opacity-50"
              >
                {stopMutation.isPending ? (
                  <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin mr-2" />
                ) : (
                  <StopCircle className="w-4 h-4 mr-2" />
                )}
                Stop
              </button>
            )}
          </div>
          {buildMutation.error && (
            <p className="text-red-500 text-sm mt-2">Build error: {buildMutation.error.message}</p>
          )}
          {runMutation.error && (
            <p className="text-red-500 text-sm mt-2">Run error: {runMutation.error.message}</p>
          )}
        </div>
      )}

      {/* Plan Info */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6 text-sm">
        <div>
          <span className="text-gray-500">Type:</span>
          <span className="ml-2 font-medium">{plan.plan_type}</span>
        </div>
        <div>
          <span className="text-gray-500">Created:</span>
          <span className="ml-2">{new Date(plan.created_at).toLocaleString()}</span>
        </div>
        {plan.completed_at && (
          <div>
            <span className="text-gray-500">Completed:</span>
            <span className="ml-2">{new Date(plan.completed_at).toLocaleString()}</span>
          </div>
        )}
        <div>
          <span className="text-gray-500">Workflow:</span>
          <span className="ml-2 font-mono text-blue-600">{plan.workflow_id || 'N/A'}</span>
        </div>
      </div>

      {/* Tasks */}
      {plan.tasks && plan.tasks.length > 0 && (
        <div>
          <h3 className="font-semibold mb-3">Tasks ({plan.tasks.length})</h3>
          <div className="space-y-2">
            {plan.tasks.map((task, index) => (
              <div
                key={task.id}
                className="flex items-center justify-between p-3 bg-gray-50 rounded-lg"
              >
                <div className="flex items-center space-x-3">
                  <span className="w-6 h-6 rounded-full bg-gray-200 flex items-center justify-center text-xs">
                    {index + 1}
                  </span>
                  <div>
                    <p className="font-medium">{task.name}</p>
                    {task.mcp_tool && (
                      <p className="text-sm text-gray-500 font-mono">{task.mcp_tool}</p>
                    )}
                  </div>
                </div>
                <div className="flex items-center space-x-2">
                  {task.required_role && (
                    <span className="px-2 py-0.5 bg-purple-100 text-purple-700 text-xs rounded">
                      {task.required_role}
                    </span>
                  )}
                  <StatusBadge status={task.status} />
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Result (simplified, hiding URLs since we show them above) */}
      {plan.result && Object.keys(plan.result).filter(k => k !== 'repo_url' && k !== 'app_url').length > 0 && (
        <div className="mt-6">
          <h3 className="font-semibold mb-3">Result</h3>
          <pre className="bg-gray-50 p-4 rounded-lg text-sm overflow-x-auto">
            {JSON.stringify(
              Object.fromEntries(
                Object.entries(plan.result).filter(([k]) => k !== 'repo_url' && k !== 'app_url')
              ),
              null,
              2
            )}
          </pre>
        </div>
      )}
    </div>
  )
}

const Plans = () => {
  const [searchParams, setSearchParams] = useSearchParams()
  const selectedPlanId = searchParams.get('id')

  const { data: plans = [], isLoading, error, refetch } = useQuery({
    queryKey: ['plans'],
    queryFn: () => getPlans(),
    refetchInterval: 10000,
  })

  return (
    <div className="space-y-6">
      <PageHeader title="Execution Plans" subtitle="View and manage your governance execution plans." />

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Plan List */}
        <div className="lg:col-span-1">
          <div className="bg-white rounded-xl border border-gray-100 p-4">
            <h2 className="text-sm font-medium text-gray-400 uppercase tracking-wide mb-4">All Plans</h2>

            {isLoading ? (
              <div className="space-y-3">
                {Array.from({ length: 4 }).map((_, i) => <SkeletonListItem key={i} />)}
              </div>
            ) : error ? (
              <div className="text-center py-8">
                <AlertCircle className="w-8 h-8 text-red-400 mx-auto mb-2" />
                <p className="text-sm text-red-600 mb-3">{error.message || 'Failed to load plans'}</p>
                <button onClick={() => refetch()} className="text-sm text-blue-600 hover:text-blue-700 font-medium">
                  Try again
                </button>
              </div>
            ) : plans.length === 0 ? (
              <EmptyState
                icon={FileText}
                title="No plans yet"
                description="Start a conversation in Chat to create your first execution plan."
                actionLabel="Go to Chat"
                actionTo="/chat"
              />
            ) : (
              <div className="space-y-2 max-h-[600px] overflow-y-auto">
                {plans.map((plan) => (
                  <button
                    key={plan.id}
                    onClick={() => setSearchParams({ id: plan.id })}
                    className={`w-full text-left p-3 rounded-lg transition-all ${
                      selectedPlanId === plan.id
                        ? 'bg-blue-50 border border-blue-200'
                        : 'hover:bg-gray-50 border border-transparent hover:border-gray-100'
                    }`}
                  >
                    <div className="flex items-center justify-between mb-1">
                      <span className="font-medium text-sm truncate pr-2">{plan.name}</span>
                      <StatusBadge status={plan.status} />
                    </div>
                    <p className="text-xs text-gray-500">
                      {new Date(plan.created_at).toLocaleDateString()}
                    </p>
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Plan Detail */}
        <div className="lg:col-span-2">
          {selectedPlanId ? (
            <PlanDetail planId={selectedPlanId} />
          ) : (
            <div className="bg-white rounded-xl border border-gray-100">
              <EmptyState
                icon={FileText}
                title="No plan selected"
                description="Select a plan from the list to view its details."
              />
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

export default Plans
