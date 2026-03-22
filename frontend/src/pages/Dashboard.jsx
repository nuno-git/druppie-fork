/**
 * Dashboard Page
 */

import React from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { FileText, CheckSquare, AlertCircle, TrendingUp, Zap, MessageSquare } from 'lucide-react'
import { getPlans, getTasks, getStatus, getProjects } from '../services/api'
import { useAuth } from '../App'
import { formatTokens, formatCost, calculateCost } from '../utils/tokenUtils'
import PageHeader from '../components/shared/PageHeader'
import EmptyState from '../components/shared/EmptyState'
import { SkeletonStatCard, SkeletonListItem } from '../components/shared/Skeleton'

const StatCard = ({ title, value, subtitle, icon: Icon, color, link }) => {
  const content = (
    <div className="flex items-center justify-between">
      <div>
        <p className="text-sm text-gray-400 font-medium">{title}</p>
        <p className="text-3xl font-semibold mt-1">{value}</p>
        {subtitle && <p className="text-xs text-green-600 mt-0.5">{subtitle}</p>}
      </div>
      <div className={`w-10 h-10 rounded-lg flex items-center justify-center ${color} bg-opacity-10`}>
        <Icon className={`w-5 h-5 ${color.replace('bg-', 'text-')}`} />
      </div>
    </div>
  )
  const className = "bg-white rounded-xl border border-gray-100 p-6 transition-all"
  if (link) {
    return <Link to={link} className={`${className} hover:border-gray-200 hover:bg-gray-50/50`}>{content}</Link>
  }
  return <div className={className}>{content}</div>
}

const Dashboard = () => {
  const { user } = useAuth()

  const { data: plansResponse, isLoading: plansLoading } = useQuery({
    queryKey: ['plans'],
    queryFn: () => getPlans(),
  })

  const { data: tasksResponse, isLoading: tasksLoading } = useQuery({
    queryKey: ['tasks'],
    queryFn: getTasks,
  })

  // Extract arrays from paginated responses
  const plans = plansResponse?.items || []
  const tasks = tasksResponse?.items || []

  const { data: status } = useQuery({
    queryKey: ['status'],
    queryFn: getStatus,
    refetchInterval: 30000,
  })

  const { data: projectsResponse } = useQuery({
    queryKey: ['projects'],
    queryFn: getProjects,
  })

  const projects = Array.isArray(projectsResponse) ? projectsResponse : (projectsResponse?.items || [])

  const completedPlans = plans.filter((p) => p.status === 'completed').length
  const pendingTasks = tasks.length

  // Calculate total token usage across all projects
  const totalTokens = Array.isArray(projects) ? projects.reduce((sum, p) => sum + (p.token_usage?.total_tokens || 0), 0) : 0
  const totalCost = calculateCost(totalTokens)

  return (
    <div className="space-y-8">
      <PageHeader
        title={`Welcome back, ${user?.firstName || user?.username}`}
        subtitle="Here's what's happening with your governance platform."
      />

      {/* Stats */}
      {plansLoading || tasksLoading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
          {Array.from({ length: 4 }).map((_, i) => <SkeletonStatCard key={i} />)}
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
          <StatCard
            title="Total Sessions"
            value={plans.length}
            icon={FileText}
            color="bg-blue-500"
            link="/chat"
          />
          <StatCard
            title="Completed"
            value={completedPlans}
            icon={TrendingUp}
            color="bg-green-500"
            link="/chat"
          />
          <StatCard
            title="Pending Approvals"
            value={pendingTasks}
            icon={CheckSquare}
            color="bg-purple-500"
            link="/tasks"
          />
          <StatCard
            title="Total Tokens"
            value={formatTokens(totalTokens) || '0'}
            subtitle={formatCost(totalCost)}
            icon={Zap}
            color="bg-yellow-500"
          />
        </div>
      )}

      {/* Recent Activity */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Recent Plans */}
        <div className="bg-white rounded-xl border border-gray-100 p-6">
          <h2 className="text-sm font-medium text-gray-400 uppercase tracking-wide mb-4">Recent Sessions</h2>
          {plansLoading ? (
            <div className="space-y-3">
              {Array.from({ length: 3 }).map((_, i) => <SkeletonListItem key={i} />)}
            </div>
          ) : plans.length === 0 ? (
            <EmptyState icon={MessageSquare} title="No sessions yet" description="Start a conversation in Chat to get started." actionLabel="Go to Chat" actionTo="/chat" />
          ) : (
            <div className="space-y-3">
              {plans.slice(0, 5).map((plan) => (
                <Link
                  key={plan.id}
                  to={`/chat?session=${plan.id}`}
                  className="flex items-center justify-between p-3 rounded-lg hover:bg-gray-50 transition-colors"
                >
                  <div className="min-w-0 flex-1 mr-3">
                    <p className="font-medium truncate">{plan.title || 'Untitled session'}</p>
                    <div className="flex items-center gap-2 text-sm text-gray-500">
                      {plan.username && (
                        <span className={`text-xs font-medium ${
                          plan.username.startsWith('t-') ? 'text-orange-500' : 'text-blue-400'
                        }`}>
                          {plan.username}
                        </span>
                      )}
                      <span>{new Date(plan.created_at).toLocaleDateString()}</span>
                    </div>
                  </div>
                  <span
                    className={`flex-shrink-0 px-2 py-1 text-xs rounded-full ${
                      plan.status === 'completed'
                        ? 'bg-green-100 text-green-700'
                        : plan.status === 'active' || plan.status === 'running'
                        ? 'bg-blue-100 text-blue-700'
                        : plan.status === 'paused_approval' || plan.status === 'paused_hitl' || plan.status === 'paused_sandbox'
                        ? 'bg-amber-100 text-amber-700'
                        : plan.status === 'failed' || plan.status === 'paused_crashed'
                        ? 'bg-red-100 text-red-700'
                        : 'bg-gray-100 text-gray-700'
                    }`}
                  >
                    {plan.status}
                  </span>
                </Link>
              ))}
            </div>
          )}
        </div>

        {/* Pending Approvals */}
        <div className="bg-white rounded-xl border border-gray-100 p-6">
          <h2 className="text-sm font-medium text-gray-400 uppercase tracking-wide mb-4">Pending Approvals</h2>
          {tasksLoading ? (
            <div className="space-y-3">
              {Array.from({ length: 3 }).map((_, i) => <SkeletonListItem key={i} />)}
            </div>
          ) : tasks.length === 0 ? (
            <EmptyState icon={CheckSquare} title="No pending approvals" description="All caught up! Approvals will appear here when agents need your input." />
          ) : (
            <div className="space-y-3">
              {tasks.slice(0, 5).map((task) => {
                const requiredRole = task.required_role ||
                  (task.required_roles?.length > 0 ? task.required_roles[0] : 'admin')
                const toolName = task.mcp_tool || task.tool_name
                const displayName = task.name || toolName?.split(':').pop() || 'Approval'
                return (
                  <Link
                    key={task.id}
                    to="/tasks"
                    className="flex items-center justify-between p-3 rounded-lg hover:bg-gray-50 transition-colors"
                  >
                    <div className="min-w-0 flex-1 mr-3">
                      <p className="font-medium truncate">{displayName}</p>
                      <p className="text-sm text-gray-500">
                        Requires: <span className="font-medium">{requiredRole}</span>
                      </p>
                    </div>
                    <AlertCircle className="w-5 h-5 text-yellow-500 flex-shrink-0" />
                  </Link>
                )
              })}
            </div>
          )}
        </div>
      </div>

      {/* Footer — roles + system status in one compact row */}
      <div className="flex items-center justify-between text-sm text-gray-400 pt-2">
        <div className="flex items-center gap-2">
          <span>Roles:</span>
          {user?.roles?.map((role) => (
            <span key={role} className="text-gray-500">{role}</span>
          ))}
        </div>
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-1.5">
            <div className={`w-1.5 h-1.5 rounded-full ${status?.keycloak ? 'bg-green-500' : 'bg-red-500'}`} />
            <span>Auth</span>
          </div>
          <div className="flex items-center gap-1.5">
            <div className={`w-1.5 h-1.5 rounded-full ${status?.database ? 'bg-green-500' : 'bg-red-500'}`} />
            <span>DB</span>
          </div>
          <div className="flex items-center gap-1.5">
            <div className={`w-1.5 h-1.5 rounded-full ${status?.llm ? 'bg-green-500' : 'bg-red-500'}`} />
            <span>LLM</span>
          </div>
        </div>
      </div>
    </div>
  )
}

export default Dashboard
