/**
 * Dashboard Page
 */

import React from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { FileText, CheckSquare, Clock, AlertCircle, TrendingUp } from 'lucide-react'
import { getPlans, getTasks, getStatus } from '../services/api'
import { useAuth } from '../App'

const StatCard = ({ title, value, icon: Icon, color, link }) => (
  <Link
    to={link}
    className="bg-white rounded-xl shadow-sm border border-gray-200 p-6 hover:shadow-md transition-shadow"
  >
    <div className="flex items-center justify-between">
      <div>
        <p className="text-sm text-gray-500">{title}</p>
        <p className="text-3xl font-bold mt-1">{value}</p>
      </div>
      <div className={`w-12 h-12 rounded-lg flex items-center justify-center ${color}`}>
        <Icon className="w-6 h-6 text-white" />
      </div>
    </div>
  </Link>
)

const Dashboard = () => {
  const { user } = useAuth()

  const { data: plansResponse, isLoading: plansLoading } = useQuery({
    queryKey: ['plans'],
    queryFn: getPlans,
  })

  const { data: tasksResponse, isLoading: tasksLoading } = useQuery({
    queryKey: ['tasks'],
    queryFn: getTasks,
  })

  // Extract arrays from paginated responses
  const plans = plansResponse?.sessions || []
  const tasks = tasksResponse?.approvals || []

  const { data: status } = useQuery({
    queryKey: ['status'],
    queryFn: getStatus,
    refetchInterval: 30000,
  })

  const completedPlans = plans.filter((p) => p.status === 'completed').length
  const runningPlans = plans.filter((p) => p.status === 'running').length
  const pendingTasks = tasks.length

  return (
    <div className="space-y-8">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold">Welcome back, {user?.firstName || user?.username}</h1>
        <p className="text-gray-500 mt-1">Here's what's happening with your governance platform.</p>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        <StatCard
          title="Total Plans"
          value={plansLoading ? '...' : plans.length}
          icon={FileText}
          color="bg-blue-500"
          link="/plans"
        />
        <StatCard
          title="Completed"
          value={plansLoading ? '...' : completedPlans}
          icon={TrendingUp}
          color="bg-green-500"
          link="/plans"
        />
        <StatCard
          title="Running"
          value={plansLoading ? '...' : runningPlans}
          icon={Clock}
          color="bg-yellow-500"
          link="/plans"
        />
        <StatCard
          title="Pending Approvals"
          value={tasksLoading ? '...' : pendingTasks}
          icon={CheckSquare}
          color="bg-purple-500"
          link="/tasks"
        />
      </div>

      {/* Recent Activity */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Recent Plans */}
        <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
          <h2 className="text-lg font-semibold mb-4">Recent Plans</h2>
          {plansLoading ? (
            <div className="text-gray-500">Loading...</div>
          ) : plans.length === 0 ? (
            <div className="text-gray-500">No plans yet. Start a conversation in Chat!</div>
          ) : (
            <div className="space-y-3">
              {plans.slice(0, 5).map((plan) => (
                <Link
                  key={plan.id}
                  to={`/plans?id=${plan.id}`}
                  className="flex items-center justify-between p-3 rounded-lg hover:bg-gray-50"
                >
                  <div>
                    <p className="font-medium">{plan.name}</p>
                    <p className="text-sm text-gray-500">
                      {new Date(plan.created_at).toLocaleDateString()}
                    </p>
                  </div>
                  <span
                    className={`px-2 py-1 text-xs rounded-full ${
                      plan.status === 'completed'
                        ? 'bg-green-100 text-green-700'
                        : plan.status === 'running'
                        ? 'bg-yellow-100 text-yellow-700'
                        : plan.status === 'failed'
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
        <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
          <h2 className="text-lg font-semibold mb-4">Pending Approvals</h2>
          {tasksLoading ? (
            <div className="text-gray-500">Loading...</div>
          ) : tasks.length === 0 ? (
            <div className="text-gray-500">No pending approvals.</div>
          ) : (
            <div className="space-y-3">
              {tasks.slice(0, 5).map((task) => (
                <Link
                  key={task.id}
                  to={`/tasks?id=${task.id}`}
                  className="flex items-center justify-between p-3 rounded-lg hover:bg-gray-50"
                >
                  <div>
                    <p className="font-medium">{task.name}</p>
                    <p className="text-sm text-gray-500">
                      Requires: <span className="font-medium">{task.required_role}</span>
                    </p>
                  </div>
                  <AlertCircle className="w-5 h-5 text-yellow-500" />
                </Link>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* User Roles */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
        <h2 className="text-lg font-semibold mb-4">Your Roles & Permissions</h2>
        <div className="flex flex-wrap gap-2">
          {user?.roles?.map((role) => (
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
              {role}
            </span>
          ))}
        </div>
      </div>

      {/* System Status */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
        <h2 className="text-lg font-semibold mb-4">System Status</h2>
        <div className="grid grid-cols-3 gap-4">
          <div className="flex items-center space-x-2">
            <div
              className={`w-3 h-3 rounded-full ${
                status?.keycloak ? 'bg-green-500' : 'bg-red-500'
              }`}
            />
            <span className="text-sm">Keycloak</span>
          </div>
          <div className="flex items-center space-x-2">
            <div
              className={`w-3 h-3 rounded-full ${
                status?.database ? 'bg-green-500' : 'bg-red-500'
              }`}
            />
            <span className="text-sm">Database</span>
          </div>
          <div className="flex items-center space-x-2">
            <div
              className={`w-3 h-3 rounded-full ${status?.llm ? 'bg-green-500' : 'bg-red-500'}`}
            />
            <span className="text-sm">LLM</span>
          </div>
        </div>
      </div>
    </div>
  )
}

export default Dashboard
