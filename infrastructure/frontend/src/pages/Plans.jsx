/**
 * Plans Page
 */

import React from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link, useSearchParams } from 'react-router-dom'
import { FileText, Clock, CheckCircle, XCircle, Play, AlertCircle } from 'lucide-react'
import { getPlans, getPlan } from '../services/api'

const StatusBadge = ({ status }) => {
  const config = {
    pending: { icon: Clock, bg: 'bg-gray-100', text: 'text-gray-700' },
    pending_approval: { icon: AlertCircle, bg: 'bg-yellow-100', text: 'text-yellow-700' },
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
  const { data: plan, isLoading, error } = useQuery({
    queryKey: ['plan', planId],
    queryFn: () => getPlan(planId),
    enabled: !!planId,
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

  return (
    <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
      <div className="flex items-start justify-between mb-6">
        <div>
          <h2 className="text-xl font-bold">{plan.name}</h2>
          <p className="text-gray-500 mt-1">{plan.description}</p>
        </div>
        <StatusBadge status={plan.status} />
      </div>

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

      {/* Result */}
      {plan.result && (
        <div className="mt-6">
          <h3 className="font-semibold mb-3">Result</h3>
          <pre className="bg-gray-50 p-4 rounded-lg text-sm overflow-x-auto">
            {JSON.stringify(plan.result, null, 2)}
          </pre>
        </div>
      )}
    </div>
  )
}

const Plans = () => {
  const [searchParams, setSearchParams] = useSearchParams()
  const selectedPlanId = searchParams.get('id')

  const { data: plans = [], isLoading, error } = useQuery({
    queryKey: ['plans'],
    queryFn: getPlans,
    refetchInterval: 10000,
  })

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Execution Plans</h1>
        <p className="text-gray-500 mt-1">View and manage your governance execution plans.</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Plan List */}
        <div className="lg:col-span-1">
          <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-4">
            <h2 className="font-semibold mb-4">All Plans</h2>

            {isLoading ? (
              <div className="text-center py-8">
                <div className="w-6 h-6 border-4 border-blue-600 border-t-transparent rounded-full animate-spin mx-auto" />
              </div>
            ) : error ? (
              <div className="text-red-500 text-center py-8">Error loading plans</div>
            ) : plans.length === 0 ? (
              <div className="text-gray-500 text-center py-8">
                <FileText className="w-12 h-12 mx-auto mb-2 opacity-50" />
                <p>No plans yet</p>
                <Link to="/chat" className="text-blue-600 hover:underline text-sm">
                  Start a chat to create one
                </Link>
              </div>
            ) : (
              <div className="space-y-2 max-h-[600px] overflow-y-auto">
                {plans.map((plan) => (
                  <button
                    key={plan.id}
                    onClick={() => setSearchParams({ id: plan.id })}
                    className={`w-full text-left p-3 rounded-lg transition-colors ${
                      selectedPlanId === plan.id
                        ? 'bg-blue-50 border border-blue-200'
                        : 'hover:bg-gray-50 border border-transparent'
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
            <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-12 text-center">
              <FileText className="w-16 h-16 text-gray-300 mx-auto mb-4" />
              <p className="text-gray-500">Select a plan to view details</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

export default Plans
