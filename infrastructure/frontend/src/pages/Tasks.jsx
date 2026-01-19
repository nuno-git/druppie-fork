/**
 * Tasks (Approvals) Page
 */

import React, { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { CheckCircle, XCircle, Clock, Shield, AlertTriangle } from 'lucide-react'
import { getTasks, approveTask, rejectTask } from '../services/api'
import { useAuth } from '../App'
import { hasRole } from '../services/keycloak'

const TaskCard = ({ task, onApprove, onReject }) => {
  const [rejectReason, setRejectReason] = useState('')
  const [showReject, setShowReject] = useState(false)
  const { user } = useAuth()

  const canApprove = hasRole(task.required_role)

  return (
    <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
      <div className="flex items-start justify-between mb-4">
        <div>
          <h3 className="font-semibold text-lg">{task.name}</h3>
          <p className="text-gray-500 text-sm mt-1">{task.description}</p>
        </div>
        <span className="px-3 py-1 bg-yellow-100 text-yellow-700 text-sm rounded-full flex items-center">
          <Clock className="w-4 h-4 mr-1" />
          Pending
        </span>
      </div>

      {/* Task Details */}
      <div className="grid grid-cols-2 gap-4 mb-4 text-sm">
        <div>
          <span className="text-gray-500">Plan:</span>
          <span className="ml-2 font-medium">{task.plan?.name || task.plan_id}</span>
        </div>
        <div>
          <span className="text-gray-500">MCP Tool:</span>
          <span className="ml-2 font-mono text-blue-600">{task.mcp_tool || 'N/A'}</span>
        </div>
        <div>
          <span className="text-gray-500">Required Role:</span>
          <span className="ml-2">
            <span
              className={`px-2 py-0.5 rounded text-xs ${
                canApprove ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-700'
              }`}
            >
              {task.required_role}
            </span>
          </span>
        </div>
        <div>
          <span className="text-gray-500">Created:</span>
          <span className="ml-2">{new Date(task.created_at).toLocaleString()}</span>
        </div>
      </div>

      {/* MCP Arguments */}
      {task.mcp_arguments && Object.keys(task.mcp_arguments).length > 0 && (
        <div className="mb-4">
          <p className="text-sm text-gray-500 mb-2">Arguments:</p>
          <pre className="bg-gray-50 p-3 rounded-lg text-sm overflow-x-auto">
            {JSON.stringify(task.mcp_arguments, null, 2)}
          </pre>
        </div>
      )}

      {/* Actions */}
      {canApprove ? (
        <div className="flex flex-col space-y-3">
          {!showReject ? (
            <div className="flex space-x-3">
              <button
                onClick={() => onApprove(task.id)}
                className="flex-1 px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 flex items-center justify-center"
              >
                <CheckCircle className="w-5 h-5 mr-2" />
                Approve
              </button>
              <button
                onClick={() => setShowReject(true)}
                className="flex-1 px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 flex items-center justify-center"
              >
                <XCircle className="w-5 h-5 mr-2" />
                Reject
              </button>
            </div>
          ) : (
            <div className="space-y-3">
              <textarea
                value={rejectReason}
                onChange={(e) => setRejectReason(e.target.value)}
                placeholder="Enter rejection reason..."
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-red-500 focus:border-transparent"
                rows={3}
              />
              <div className="flex space-x-3">
                <button
                  onClick={() => setShowReject(false)}
                  className="flex-1 px-4 py-2 border border-gray-300 rounded-lg hover:bg-gray-50"
                >
                  Cancel
                </button>
                <button
                  onClick={() => {
                    if (rejectReason.trim()) {
                      onReject(task.id, rejectReason)
                    }
                  }}
                  disabled={!rejectReason.trim()}
                  className="flex-1 px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  Confirm Rejection
                </button>
              </div>
            </div>
          )}
        </div>
      ) : (
        <div className="flex items-center p-3 bg-gray-50 rounded-lg text-gray-600">
          <Shield className="w-5 h-5 mr-2" />
          You need the "{task.required_role}" role to approve this task.
        </div>
      )}
    </div>
  )
}

const Tasks = () => {
  const { user } = useAuth()
  const queryClient = useQueryClient()

  const { data: tasks = [], isLoading, error } = useQuery({
    queryKey: ['tasks'],
    queryFn: getTasks,
    refetchInterval: 10000,
  })

  const approveMutation = useMutation({
    mutationFn: ({ taskId, comment }) => approveTask(taskId, comment),
    onSuccess: () => {
      queryClient.invalidateQueries(['tasks'])
      queryClient.invalidateQueries(['plans'])
    },
  })

  const rejectMutation = useMutation({
    mutationFn: ({ taskId, reason }) => rejectTask(taskId, reason),
    onSuccess: () => {
      queryClient.invalidateQueries(['tasks'])
      queryClient.invalidateQueries(['plans'])
    },
  })

  const handleApprove = (taskId) => {
    approveMutation.mutate({ taskId, comment: '' })
  }

  const handleReject = (taskId, reason) => {
    rejectMutation.mutate({ taskId, reason })
  }

  // Group tasks by required role
  const tasksByRole = tasks.reduce((acc, task) => {
    const role = task.required_role || 'other'
    if (!acc[role]) acc[role] = []
    acc[role].push(task)
    return acc
  }, {})

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-2xl font-bold">Pending Approvals</h1>
          <p className="text-gray-500 mt-1">
            Review and approve tasks based on your role permissions.
          </p>
        </div>
        <div className="flex items-center space-x-2">
          <span className="text-sm text-gray-500">Your roles:</span>
          {user?.roles?.slice(0, 3).map((role) => (
            <span
              key={role}
              className="px-2 py-1 bg-blue-100 text-blue-700 text-xs rounded-full"
            >
              {role}
            </span>
          ))}
        </div>
      </div>

      {isLoading ? (
        <div className="text-center py-12">
          <div className="w-8 h-8 border-4 border-blue-600 border-t-transparent rounded-full animate-spin mx-auto mb-4" />
          <p className="text-gray-500">Loading tasks...</p>
        </div>
      ) : error ? (
        <div className="text-center py-12">
          <AlertTriangle className="w-12 h-12 text-red-500 mx-auto mb-4" />
          <p className="text-red-500">Error loading tasks: {error.message}</p>
        </div>
      ) : tasks.length === 0 ? (
        <div className="text-center py-12 bg-white rounded-xl border border-gray-200">
          <CheckCircle className="w-12 h-12 text-green-500 mx-auto mb-4" />
          <h3 className="text-lg font-medium">All caught up!</h3>
          <p className="text-gray-500">No pending approvals at the moment.</p>
        </div>
      ) : (
        <div className="space-y-8">
          {Object.entries(tasksByRole).map(([role, roleTasks]) => (
            <div key={role}>
              <h2 className="text-lg font-semibold mb-4 flex items-center">
                <Shield
                  className={`w-5 h-5 mr-2 ${
                    hasRole(role) ? 'text-green-500' : 'text-gray-400'
                  }`}
                />
                {role}
                <span className="ml-2 px-2 py-0.5 bg-gray-100 text-gray-600 text-sm rounded-full">
                  {roleTasks.length}
                </span>
                {hasRole(role) && (
                  <span className="ml-2 text-sm text-green-600">(You can approve)</span>
                )}
              </h2>
              <div className="grid gap-4">
                {roleTasks.map((task) => (
                  <TaskCard
                    key={task.id}
                    task={task}
                    onApprove={handleApprove}
                    onReject={handleReject}
                  />
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export default Tasks
