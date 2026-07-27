import React from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { FileText, CheckSquare, AlertCircle, TrendingUp, Zap, MessageSquare, Activity } from 'lucide-react'
import { getPlans, getTasks, getStatus, getProjects } from '../services/api'
import { useAuth } from '../App'
import { formatTokens, formatCost, calculateCost } from '../utils/tokenUtils'
import PageHeader from '../components/shared/PageHeader'
import EmptyState from '../components/shared/EmptyState'
import { SkeletonStatCard, SkeletonListItem } from '../components/shared/Skeleton'

const statusConfig = {
  completed: { dot: 'bg-emerald-500', bg: 'bg-emerald-50', text: 'text-emerald-700' },
  active: { dot: 'bg-blue-500', bg: 'bg-blue-50', text: 'text-blue-700' },
  running: { dot: 'bg-blue-500', bg: 'bg-blue-50', text: 'text-blue-700' },
  paused_approval: { dot: 'bg-amber-500', bg: 'bg-amber-50', text: 'text-amber-700' },
  paused_hitl: { dot: 'bg-amber-500', bg: 'bg-amber-50', text: 'text-amber-700' },
  paused_sandbox: { dot: 'bg-amber-500', bg: 'bg-amber-50', text: 'text-amber-700' },
  failed: { dot: 'bg-red-500', bg: 'bg-red-50', text: 'text-red-700' },
  paused_crashed: { dot: 'bg-red-500', bg: 'bg-red-50', text: 'text-red-700' },
}

const StatCard = ({ title, value, subtitle, icon: Icon, gradient, link }) => {
  const content = (
    <div className="flex items-center justify-between gap-4">
      <div className="min-w-0">
        <p className="text-sm text-gray-500 font-medium">{title}</p>
        <p className="text-2xl font-bold text-gray-900 mt-0.5 tabular-nums">{value}</p>
        {subtitle && <p className="text-sm text-emerald-600 font-medium mt-0.5">{subtitle}</p>}
      </div>
      <div className={`w-11 h-11 rounded-xl flex items-center justify-center flex-shrink-0 bg-gradient-to-br ${gradient} shadow-sm`}>
        <Icon className="w-5 h-5 text-white" />
      </div>
    </div>
  )
  if (link) {
    return (
      <Link to={link} className="group bg-white rounded-xl border border-gray-200/60 p-5 transition-all hover:shadow-md hover:border-gray-300/80">
        {content}
      </Link>
    )
  }
  return (
    <div className="bg-white rounded-xl border border-gray-200/60 p-5 shadow-sm">
      {content}
    </div>
  )
}

const StatusBadge = ({ status }) => {
  const config = statusConfig[status] || { dot: 'bg-gray-400', bg: 'bg-gray-100', text: 'text-gray-600' }
  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium ${config.bg} ${config.text}`}>
      <span className={`w-1.5 h-1.5 rounded-full ${config.dot}`} />
      {status}
    </span>
  )
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

  const totalTokens = Array.isArray(projects) ? projects.reduce((sum, p) => sum + (p.token_usage?.total_tokens || 0), 0) : 0
  const totalCost = calculateCost(totalTokens)

  return (
    <div className="space-y-8">
      <PageHeader
        title={`Welcome back, ${user?.firstName || user?.username}`}
        subtitle="Here's what's happening with your governance platform."
      />

      {plansLoading || tasksLoading ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5">
          {Array.from({ length: 4 }).map((_, i) => <SkeletonStatCard key={i} />)}
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5">
          <StatCard
            title="Total Sessions"
            value={plans.length}
            icon={FileText}
            gradient="from-blue-500 to-blue-600"
            link="/chat"
          />
          <StatCard
            title="Completed"
            value={completedPlans}
            icon={TrendingUp}
            gradient="from-emerald-500 to-emerald-600"
            link="/chat"
          />
          <StatCard
            title="Pending Approvals"
            value={pendingTasks}
            icon={CheckSquare}
            gradient="from-violet-500 to-violet-600"
            link="/tasks"
          />
          <StatCard
            title="Total Tokens"
            value={formatTokens(totalTokens) || '0'}
            subtitle={formatCost(totalCost)}
            icon={Zap}
            gradient="from-amber-500 to-amber-600"
          />
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        <div className="bg-white rounded-xl border border-gray-200/60 shadow-sm">
          <div className="flex items-center gap-2 px-6 pt-5 pb-3 border-b border-gray-100">
            <MessageSquare className="w-4 h-4 text-gray-400" />
            <h2 className="text-sm font-semibold text-gray-900">Recent Sessions</h2>
          </div>
          {plansLoading ? (
            <div className="p-5 space-y-2">
              {Array.from({ length: 3 }).map((_, i) => <SkeletonListItem key={i} />)}
            </div>
          ) : plans.length === 0 ? (
            <EmptyState icon={MessageSquare} title="No sessions yet" description="Start a conversation in Chat to get started." actionLabel="Go to Chat" actionTo="/chat" />
          ) : (
            <div className="divide-y divide-gray-50">
              {plans.slice(0, 5).map((plan) => (
                <Link
                  key={plan.id}
                  to={`/chat?session=${plan.id}`}
                  className="flex items-center justify-between px-6 py-3.5 hover:bg-gray-50/60 transition-colors"
                >
                  <div className="min-w-0 flex-1 mr-4">
                    <p className="text-sm font-medium text-gray-900 truncate">{plan.title || 'Untitled session'}</p>
                    <div className="flex items-center gap-3 mt-0.5">
                      {plan.username && (
                        <span className={`text-xs font-medium ${
                          plan.username.startsWith('t-') ? 'text-orange-500' : 'text-blue-500'
                        }`}>
                          {plan.username}
                        </span>
                      )}
                      <span className="text-xs text-gray-400">{new Date(plan.created_at).toLocaleDateString()}</span>
                    </div>
                  </div>
                  <StatusBadge status={plan.status} />
                </Link>
              ))}
            </div>
          )}
        </div>

        <div className="bg-white rounded-xl border border-gray-200/60 shadow-sm">
          <div className="flex items-center gap-2 px-6 pt-5 pb-3 border-b border-gray-100">
            <AlertCircle className="w-4 h-4 text-gray-400" />
            <h2 className="text-sm font-semibold text-gray-900">Pending Approvals</h2>
          </div>
          {tasksLoading ? (
            <div className="p-5 space-y-2">
              {Array.from({ length: 3 }).map((_, i) => <SkeletonListItem key={i} />)}
            </div>
          ) : tasks.length === 0 ? (
            <EmptyState icon={CheckSquare} title="No pending approvals" description="All caught up! Approvals will appear here when agents need your input." />
          ) : (
            <div className="divide-y divide-gray-50">
              {tasks.slice(0, 5).map((task) => {
                const requiredRole = task.required_role ||
                  (task.required_roles?.length > 0 ? task.required_roles[0] : 'admin')
                const toolName = task.mcp_tool || task.tool_name
                const displayName = task.name || toolName?.split(':').pop() || 'Approval'
                return (
                  <Link
                    key={task.id}
                    to="/tasks"
                    className="flex items-center justify-between px-6 py-3.5 hover:bg-gray-50/60 transition-colors"
                  >
                    <div className="min-w-0 flex-1 mr-4">
                      <p className="text-sm font-medium text-gray-900 truncate">{displayName}</p>
                      <p className="text-xs text-gray-500 mt-0.5">
                        Requires <span className="font-medium text-gray-700">{requiredRole}</span>
                      </p>
                    </div>
                    <span className="flex-shrink-0 w-7 h-7 rounded-full bg-amber-50 flex items-center justify-center">
                      <AlertCircle className="w-4 h-4 text-amber-500" />
                    </span>
                  </Link>
                )
              })}
            </div>
          )}
        </div>
      </div>

      <div className="bg-white rounded-xl border border-gray-200/60 shadow-sm px-6 py-4">
        <div className="flex items-center justify-between text-sm">
          <div className="flex items-center gap-3">
            <span className="text-gray-400 font-medium">Roles:</span>
            <div className="flex items-center gap-2">
              {user?.roles?.map((role) => (
                <span key={role} className="inline-flex items-center px-2.5 py-1 bg-gray-100 text-gray-600 rounded-md text-xs font-medium">
                  {role}
                </span>
              ))}
            </div>
          </div>
          <div className="flex items-center gap-5">
            <div className="flex items-center gap-2">
              <Activity className="w-3.5 h-3.5 text-gray-400" />
              <span className="text-gray-400 text-xs font-medium">System Status</span>
            </div>
            <div className="flex items-center gap-3">
              <div className="flex items-center gap-1.5">
                <span className={`w-2 h-2 rounded-full ${status?.keycloak ? 'bg-emerald-500' : 'bg-red-500'}`} />
                <span className="text-gray-500 text-xs">Auth</span>
              </div>
              <div className="flex items-center gap-1.5">
                <span className={`w-2 h-2 rounded-full ${status?.database ? 'bg-emerald-500' : 'bg-red-500'}`} />
                <span className="text-gray-500 text-xs">DB</span>
              </div>
              <div className="flex items-center gap-1.5">
                <span className={`w-2 h-2 rounded-full ${status?.llm ? 'bg-emerald-500' : 'bg-red-500'}`} />
                <span className="text-gray-500 text-xs">LLM</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

export default Dashboard