/**
 * Tasks (Approvals) Page
 */

import React, { useState, useEffect, useCallback } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { CheckCircle, XCircle, Clock, Shield, AlertTriangle, AlertCircle, HelpCircle, Send, Loader2, MessageSquare, Wifi, WifiOff, Bot } from 'lucide-react'
import { getTasks, approveTask, rejectTask, getQuestions, answerQuestion } from '../services/api'
import { useAuth } from '../App'
import { hasRole } from '../services/keycloak'
import { useToast } from '../components/Toast'
import { initSocket, onApprovalRequired, onApprovalStatusChanged, isSocketConnected, joinApprovalsRoom } from '../services/socket'

// Helper to get human-readable tool description
const getToolDescription = (toolName) => {
  const toolDescriptions = {
    'run_command': 'Execute a shell command in the workspace',
    'coding:run_command': 'Execute a shell command in the workspace',
    'write_file': 'Write content to a file in the workspace',
    'coding:write_file': 'Write content to a file in the workspace',
    'delete_file': 'Delete a file from the workspace',
    'coding:delete_file': 'Delete a file from the workspace',
    'commit_and_push': 'Commit changes and push to Git repository',
    'coding:commit_and_push': 'Commit changes and push to Git repository',
    'merge_to_main': 'Merge current branch to main branch',
    'coding:merge_to_main': 'Merge current branch to main branch',
    'build': 'Build a Docker image',
    'docker:build': 'Build a Docker image',
    'run': 'Run a Docker container',
    'docker:run': 'Run a Docker container',
    'stop': 'Stop a running Docker container',
    'docker:stop': 'Stop a running Docker container',
    'remove': 'Remove a Docker container',
    'docker:remove': 'Remove a Docker container',
    'exec_command': 'Execute command inside a Docker container',
    'docker:exec_command': 'Execute command inside a Docker container',
  }
  return toolDescriptions[toolName] || `Execute ${toolName}`
}

// Helper to get danger level badge
const getDangerLevelBadge = (level) => {
  const levels = {
    low: { bg: 'bg-green-100', text: 'text-green-700', label: 'Low Risk' },
    medium: { bg: 'bg-yellow-100', text: 'text-yellow-700', label: 'Medium Risk' },
    high: { bg: 'bg-orange-100', text: 'text-orange-700', label: 'High Risk' },
    critical: { bg: 'bg-red-100', text: 'text-red-700', label: 'Critical' },
  }
  return levels[level] || levels.low
}

// Helper to format agent display name
const formatAgentName = (agentId) => {
  if (!agentId) return null
  // Remove common suffixes like '_agent' and format nicely
  return agentId
    .replace(/_agent$/i, '')
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase())
}

const TaskCard = ({ task, onApprove, onReject }) => {
  const [rejectReason, setRejectReason] = useState('')
  const [showReject, setShowReject] = useState(false)
  const [showDetails, setShowDetails] = useState(false)
  const { user } = useAuth()

  // For MULTI approval, check if user has any of the required roles
  const canApprove = task.approval_type === 'multi' && task.required_roles
    ? task.required_roles.some(role => hasRole(role))
    : hasRole(task.required_role)

  // MULTI approval state
  const isMultiApproval = task.approval_type === 'multi'
  const requiredApprovals = task.required_approvals || 2
  const currentApprovals = task.current_approvals || 0
  const approvedByRoles = task.approved_by_roles || []
  const remainingRoles = isMultiApproval && task.required_roles
    ? task.required_roles.filter(role => !approvedByRoles.includes(role))
    : []

  // Get tool info
  const toolName = task.mcp_tool || task.tool_name || 'unknown'
  const toolDescription = getToolDescription(toolName)
  const dangerLevel = task.danger_level || 'medium'
  const dangerBadge = getDangerLevelBadge(dangerLevel)

  return (
    <div className={`bg-white rounded-xl shadow-sm border p-6 ${isMultiApproval ? 'border-orange-200' : 'border-gray-200'}`}>
      {/* Header with approval type and status */}
      <div className="flex items-start justify-between mb-4">
        <div className="flex-1">
          {isMultiApproval && (
            <div className="flex items-center gap-2 mb-2">
              <span className="text-orange-600 font-semibold text-sm">Multi-Approval Required</span>
              <span className="px-2 py-0.5 bg-orange-100 text-orange-700 text-xs rounded-full">
                {currentApprovals} of {requiredApprovals} approvals
              </span>
            </div>
          )}
          <div className="flex items-center gap-2 flex-wrap">
            <h3 className="font-semibold text-lg">{task.name || `Approve ${toolName}`}</h3>
            {task.agent_id && (
              <span className="inline-flex items-center gap-1 px-2 py-0.5 bg-purple-100 text-purple-600 text-xs rounded-full">
                <Bot className="w-3 h-3" />
                {formatAgentName(task.agent_id)}
              </span>
            )}
          </div>
          <p className="text-gray-500 text-sm mt-1">{task.description || toolDescription}</p>
        </div>
        <div className="flex flex-col items-end gap-2">
          <span className="px-3 py-1 bg-yellow-100 text-yellow-700 text-sm rounded-full flex items-center">
            <Clock className="w-4 h-4 mr-1" />
            Pending
          </span>
          <span className={`px-2 py-0.5 ${dangerBadge.bg} ${dangerBadge.text} text-xs rounded-full`}>
            {dangerBadge.label}
          </span>
        </div>
      </div>

      {/* What needs approval - clear explanation */}
      <div className="mb-4 p-4 bg-blue-50 rounded-lg border border-blue-200">
        <h4 className="font-medium text-blue-900 mb-2 flex items-center gap-2">
          <AlertTriangle className="w-4 h-4" />
          What needs your approval:
        </h4>
        <div className="space-y-2">
          <div className="flex items-start gap-2">
            <span className="text-blue-700 font-medium">Tool:</span>
            <code className="bg-blue-100 px-2 py-0.5 rounded text-blue-800 font-mono text-sm">{toolName}</code>
          </div>
          <div className="text-blue-700">
            <span className="font-medium">Action:</span> {toolDescription}
          </div>
          {task.mcp_arguments && Object.keys(task.mcp_arguments).length > 0 && (
            <div className="mt-2">
              <button
                onClick={() => setShowDetails(!showDetails)}
                className="text-blue-600 hover:text-blue-800 text-sm flex items-center gap-1 focus:outline-none focus:ring-2 focus:ring-blue-500 rounded"
                aria-expanded={showDetails}
                aria-label={showDetails ? 'Hide tool arguments' : 'Show tool arguments'}
              >
                <span aria-hidden="true">{showDetails ? '▼' : '▶'}</span> View arguments
              </button>
              {showDetails && (
                <pre className="mt-2 bg-blue-100 p-3 rounded text-sm overflow-x-auto text-blue-900 font-mono">
                  {JSON.stringify(task.mcp_arguments, null, 2)}
                </pre>
              )}
            </div>
          )}
        </div>
      </div>

      {/* MULTI approval progress */}
      {isMultiApproval && (
        <div className="mb-4 p-3 bg-orange-50 rounded-lg">
          {/* Progress bar */}
          <div className="w-full bg-gray-200 rounded-full h-2 mb-3">
            <div
              className="bg-orange-500 h-2 rounded-full transition-all"
              style={{ width: `${(currentApprovals / requiredApprovals) * 100}%` }}
            />
          </div>

          {/* Approved by */}
          {approvedByRoles.length > 0 && (
            <div className="mb-2">
              <span className="text-sm text-gray-600">Approved by: </span>
              {approvedByRoles.map(role => (
                <span key={role} className="inline-flex items-center px-2 py-0.5 bg-green-100 text-green-700 text-xs rounded-full mr-1">
                  <CheckCircle className="w-3 h-3 mr-1" />
                  {role}
                </span>
              ))}
            </div>
          )}

          {/* Still needed */}
          {remainingRoles.length > 0 && (
            <div>
              <span className="text-sm text-gray-600">Still needed: </span>
              {remainingRoles.map(role => (
                <span key={role} className="inline-flex items-center px-2 py-0.5 bg-gray-100 text-gray-600 text-xs rounded-full mr-1">
                  {role}
                </span>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Context info - simplified */}
      <div className="grid grid-cols-2 gap-4 mb-4 text-sm bg-gray-50 rounded-lg p-3">
        <div>
          <span className="text-gray-500">Session:</span>
          <span className="ml-2 font-medium font-mono text-xs">{task.session_id ? task.session_id.substring(0, 8) + '...' : 'N/A'}</span>
        </div>
        <div>
          <span className="text-gray-500">Created:</span>
          <span className="ml-2">{new Date(task.created_at).toLocaleString()}</span>
        </div>
        {task.agent_id && (
          <div>
            <span className="text-gray-500">Requested by:</span>
            <span className="ml-2 inline-flex items-center gap-1">
              <Bot className="w-3.5 h-3.5 text-purple-500" />
              <span className="font-medium text-purple-700">{formatAgentName(task.agent_id)}</span>
            </span>
          </div>
        )}
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
            {canApprove && <span className="ml-1 text-green-600">(you can approve)</span>}
          </span>
        </div>
      </div>

      {/* Actions */}
      {canApprove ? (
        <div className="flex flex-col space-y-3">
          {!showReject ? (
            <div className="flex space-x-3" role="group" aria-label="Task approval actions">
              <button
                onClick={() => onApprove(task.id)}
                className={`flex-1 px-4 py-2 text-white rounded-lg flex items-center justify-center focus:outline-none focus:ring-2 focus:ring-offset-2 ${
                  isMultiApproval ? 'bg-orange-500 hover:bg-orange-600 focus:ring-orange-500' : 'bg-green-600 hover:bg-green-700 focus:ring-green-500'
                }`}
                aria-label={isMultiApproval ? `Add approval ${currentApprovals + 1} of ${requiredApprovals}` : 'Approve task'}
              >
                <CheckCircle className="w-5 h-5 mr-2" aria-hidden="true" />
                {isMultiApproval ? `Add Approval (${currentApprovals + 1}/${requiredApprovals})` : 'Approve'}
              </button>
              <button
                onClick={() => setShowReject(true)}
                className="flex-1 px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 flex items-center justify-center focus:outline-none focus:ring-2 focus:ring-red-500 focus:ring-offset-2"
                aria-label="Reject task"
              >
                <XCircle className="w-5 h-5 mr-2" aria-hidden="true" />
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
              <div className="flex space-x-3" role="group" aria-label="Rejection actions">
                <button
                  onClick={() => setShowReject(false)}
                  className="flex-1 px-4 py-2 border border-gray-300 rounded-lg hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-gray-500 focus:ring-offset-2"
                  aria-label="Cancel rejection"
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
                  className="flex-1 px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:opacity-50 disabled:cursor-not-allowed focus:outline-none focus:ring-2 focus:ring-red-500 focus:ring-offset-2"
                  aria-label="Confirm task rejection"
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
          {task.approval_type === 'multi' && task.required_roles
            ? `You need one of these roles to approve: ${task.required_roles.join(', ')}`
            : `You need the "${task.required_role}" role to approve this task.`
          }
        </div>
      )}
    </div>
  )
}

// Question Card Component for the Tasks page
const QuestionCard = ({ question, onAnswer, isAnswering }) => {
  const [selectedOption, setSelectedOption] = useState(null)
  const [customAnswer, setCustomAnswer] = useState('')
  const hasOptions = question.options && question.options.length > 0

  const handleSubmit = () => {
    const answer = selectedOption || customAnswer
    if (answer.trim()) {
      onAnswer(question.id, answer)
    }
  }

  return (
    <div className="bg-white rounded-xl shadow-sm border border-purple-200 p-6">
      <div className="flex items-start justify-between mb-4">
        <div>
          <div className="flex items-center gap-2 mb-2">
            <HelpCircle className="w-5 h-5 text-purple-600" />
            <h3 className="font-semibold text-lg text-purple-900">Agent Question</h3>
          </div>
          <p className="text-purple-800 font-medium">{question.question}</p>
          {question.context && (
            <p className="text-purple-600 text-sm mt-1">{question.context}</p>
          )}
        </div>
        <span className="px-3 py-1 bg-purple-100 text-purple-700 text-sm rounded-full flex items-center">
          <Clock className="w-4 h-4 mr-1" />
          Waiting
        </span>
      </div>

      {/* Session info */}
      {question.session_id && (
        <div className="mb-4 text-sm">
          <span className="text-gray-500">Session:</span>
          <span className="ml-2 font-medium font-mono text-xs">{question.session_id.substring(0, 8)}...</span>
        </div>
      )}

      {/* Options as clickable buttons */}
      {hasOptions && (
        <div className="space-y-2 mb-4">
          {question.options.map((option, index) => (
            <button
              key={index}
              onClick={() => {
                setSelectedOption(option)
                setCustomAnswer('')
              }}
              className={`w-full text-left px-4 py-2 rounded-lg border transition-colors ${
                selectedOption === option
                  ? 'bg-purple-600 text-white border-purple-600'
                  : 'bg-white text-purple-800 border-purple-200 hover:border-purple-400'
              }`}
            >
              {option}
            </button>
          ))}
        </div>
      )}

      {/* Custom answer input */}
      <div className="mb-4">
        <input
          type="text"
          value={customAnswer}
          onChange={(e) => {
            setCustomAnswer(e.target.value)
            setSelectedOption(null)
          }}
          placeholder={hasOptions ? "Or type a custom answer..." : "Type your answer..."}
          className="w-full px-3 py-2 border border-purple-200 rounded-lg focus:ring-2 focus:ring-purple-500 focus:border-transparent"
        />
      </div>

      {/* Submit button */}
      <button
        onClick={handleSubmit}
        disabled={isAnswering || (!selectedOption && !customAnswer.trim())}
        className="flex items-center gap-2 px-4 py-2 bg-purple-600 text-white rounded-lg hover:bg-purple-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors focus:outline-none focus:ring-2 focus:ring-purple-500 focus:ring-offset-2"
        aria-label="Submit answer"
      >
        {isAnswering ? (
          <>
            <Loader2 className="w-4 h-4 animate-spin" aria-hidden="true" />
            Submitting...
          </>
        ) : (
          <>
            <Send className="w-4 h-4" aria-hidden="true" />
            Submit Answer
          </>
        )}
      </button>
    </div>
  )
}

const Tasks = () => {
  const { user } = useAuth()
  const queryClient = useQueryClient()
  const toast = useToast()
  const [isConnected, setIsConnected] = useState(false)

  const { data: tasksResponse, isLoading, isError, error, refetch: refetchTasks } = useQuery({
    queryKey: ['tasks'],
    queryFn: getTasks,
    refetchInterval: 10000,
  })

  // Extract tasks array from paginated response
  const tasks = tasksResponse?.approvals || []

  const { data: questions = [], isLoading: questionsLoading, isError: questionsError, error: questionsErrorData, refetch: refetchQuestions } = useQuery({
    queryKey: ['questions'],
    queryFn: () => getQuestions(),
    refetchInterval: 10000,
  })

  const approveMutation = useMutation({
    mutationFn: ({ taskId, comment }) => approveTask(taskId, comment),
    onSuccess: () => {
      queryClient.invalidateQueries(['tasks'])
      queryClient.invalidateQueries(['plans'])
      toast.success('Approval Granted', 'The task has been approved successfully.')
    },
    onError: (err) => {
      toast.error('Approval Failed', err.message || 'Failed to approve the task. Please try again.')
    },
  })

  const rejectMutation = useMutation({
    mutationFn: ({ taskId, reason }) => rejectTask(taskId, reason),
    onSuccess: () => {
      queryClient.invalidateQueries(['tasks'])
      queryClient.invalidateQueries(['plans'])
      toast.success('Task Rejected', 'The task has been rejected.')
    },
    onError: (err) => {
      toast.error('Rejection Failed', err.message || 'Failed to reject the task. Please try again.')
    },
  })

  const answerMutation = useMutation({
    mutationFn: ({ questionId, answer }) => answerQuestion(questionId, answer),
    onSuccess: () => {
      queryClient.invalidateQueries(['questions'])
      queryClient.invalidateQueries(['plans'])
      toast.success('Answer Submitted', 'Your answer has been sent to the agent.')
    },
    onError: (err) => {
      toast.error('Submission Failed', err.message || 'Failed to submit your answer. Please try again.')
    },
  })

  // Refetch callback for WebSocket events
  const refetchAll = useCallback(() => {
    refetchTasks()
    refetchQuestions()
  }, [refetchTasks, refetchQuestions])

  // WebSocket connection for real-time updates
  useEffect(() => {
    // Initialize socket connection
    const socket = initSocket()

    // Check initial connection status
    const checkConnection = () => {
      setIsConnected(isSocketConnected())
    }
    checkConnection()

    // Join approvals room for user's roles
    if (user?.roles) {
      joinApprovalsRoom(user.roles)
    }

    // Handle new approval required events
    const handleApprovalRequired = (data) => {
      const toolName = data.tool || data.mcp_tool || 'Unknown tool'
      toast.info('New Approval Required', `Action requested: ${toolName}`)
      refetchAll()
    }

    // Handle approval status changed events
    const handleApprovalStatusChanged = (data) => {
      const toolName = data.tool || data.mcp_tool || 'Unknown tool'
      const status = data.status || 'updated'
      if (status === 'approved') {
        toast.success('Approval Granted', `${toolName} was approved`)
      } else if (status === 'rejected') {
        toast.warning('Approval Rejected', `${toolName} was rejected`)
      } else {
        toast.info('Approval Updated', `${toolName}: ${status}`)
      }
      refetchAll()
    }

    // Subscribe to events
    const unsubApprovalRequired = onApprovalRequired(handleApprovalRequired)
    const unsubStatusChanged = onApprovalStatusChanged(handleApprovalStatusChanged)

    // Periodically check connection status
    const connectionInterval = setInterval(checkConnection, 3000)

    // Cleanup on unmount
    return () => {
      unsubApprovalRequired()
      unsubStatusChanged()
      clearInterval(connectionInterval)
    }
  }, [user?.roles, toast, refetchAll])

  const handleApprove = (taskId) => {
    approveMutation.mutate({ taskId, comment: '' })
  }

  const handleReject = (taskId, reason) => {
    rejectMutation.mutate({ taskId, reason })
  }

  const handleAnswerQuestion = (questionId, answer) => {
    answerMutation.mutate({ questionId, answer })
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
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold">Pending Approvals</h1>
            {/* Live connection indicator */}
            <span
              className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium ${
                isConnected
                  ? 'bg-green-100 text-green-700'
                  : 'bg-gray-100 text-gray-500'
              }`}
              role="status"
              aria-live="polite"
              aria-label={isConnected ? 'Connected to real-time updates' : 'Disconnected from real-time updates'}
            >
              {isConnected ? (
                <>
                  <Wifi className="w-3 h-3" />
                  <span className="relative flex h-2 w-2">
                    <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75"></span>
                    <span className="relative inline-flex rounded-full h-2 w-2 bg-green-500"></span>
                  </span>
                  Live
                </>
              ) : (
                <>
                  <WifiOff className="w-3 h-3" />
                  Offline
                </>
              )}
            </span>
          </div>
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

      {/* Pending Questions Section */}
      {questions.length > 0 && (
        <div className="space-y-4">
          <h2 className="text-lg font-semibold flex items-center">
            <MessageSquare className="w-5 h-5 mr-2 text-purple-500" />
            Pending Questions
            <span className="ml-2 px-2 py-0.5 bg-purple-100 text-purple-600 text-sm rounded-full">
              {questions.length}
            </span>
          </h2>
          <div className="grid gap-4">
            {questions.map((question) => (
              <QuestionCard
                key={question.id}
                question={question}
                onAnswer={handleAnswerQuestion}
                isAnswering={answerMutation.isPending}
              />
            ))}
          </div>
        </div>
      )}

      {/* Loading State for Questions */}
      {questionsLoading && (
        <div className="flex items-center justify-center h-32">
          <Loader2 className="w-6 h-6 animate-spin text-purple-500" />
          <span className="ml-2 text-gray-600">Loading questions...</span>
        </div>
      )}

      {/* Error State for Questions */}
      {questionsError && !questionsLoading && (
        <div className="flex flex-col items-center justify-center h-32 text-red-500 bg-white rounded-xl border border-red-200 p-4">
          <AlertCircle className="w-8 h-8 mb-2" />
          <p className="font-medium">Failed to load questions</p>
          <p className="text-sm text-red-400">{questionsErrorData?.message || 'An unexpected error occurred'}</p>
          <button
            onClick={() => refetchQuestions()}
            className="mt-3 px-4 py-2 bg-purple-500 text-white rounded-lg hover:bg-purple-600 transition-colors text-sm focus:outline-none focus:ring-2 focus:ring-purple-500 focus:ring-offset-2"
            aria-label="Retry loading questions"
          >
            Retry
          </button>
        </div>
      )}

      {/* Approval Tasks Section */}
      {isLoading ? (
        <div className="flex items-center justify-center h-64">
          <Loader2 className="w-8 h-8 animate-spin text-blue-500" />
          <span className="ml-2 text-gray-600">Loading tasks...</span>
        </div>
      ) : isError ? (
        <div className="flex flex-col items-center justify-center h-64 text-red-500">
          <AlertCircle className="w-12 h-12 mb-2" />
          <p className="text-lg font-medium">Failed to load tasks</p>
          <p className="text-sm text-red-400">{error?.message || 'An unexpected error occurred'}</p>
          <button
            onClick={() => refetchTasks()}
            className="mt-4 px-4 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600 transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2"
            aria-label="Retry loading tasks"
          >
            Retry
          </button>
        </div>
      ) : tasks.length === 0 && questions.length === 0 ? (
        <div className="text-center py-12 bg-white rounded-xl border border-gray-200">
          <CheckCircle className="w-12 h-12 text-green-500 mx-auto mb-4" />
          <h3 className="text-lg font-medium">All caught up!</h3>
          <p className="text-gray-500">No pending approvals or questions at the moment.</p>
        </div>
      ) : tasks.length > 0 && (
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
