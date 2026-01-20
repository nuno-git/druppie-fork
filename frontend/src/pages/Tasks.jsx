/**
 * Tasks (Approvals) Page
 */

import React, { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { CheckCircle, XCircle, Clock, Shield, AlertTriangle, HelpCircle, Send, Loader2, MessageSquare } from 'lucide-react'
import { getTasks, approveTask, rejectTask, getQuestions, answerQuestion } from '../services/api'
import { useAuth } from '../App'
import { hasRole } from '../services/keycloak'

const TaskCard = ({ task, onApprove, onReject }) => {
  const [rejectReason, setRejectReason] = useState('')
  const [showReject, setShowReject] = useState(false)
  const { user } = useAuth()

  // For MULTI approval, check if user has any of the required roles
  const canApprove = task.approval_type === 'multi' && task.required_roles
    ? task.required_roles.some(role => hasRole(role))
    : hasRole(task.required_role)

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

      {/* Plan info */}
      {question.plan && (
        <div className="mb-4 text-sm">
          <span className="text-gray-500">Conversation:</span>
          <span className="ml-2 font-medium">{question.plan.name}</span>
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
        className="flex items-center gap-2 px-4 py-2 bg-purple-600 text-white rounded-lg hover:bg-purple-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
      >
        {isAnswering ? (
          <>
            <Loader2 className="w-4 h-4 animate-spin" />
            Submitting...
          </>
        ) : (
          <>
            <Send className="w-4 h-4" />
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

  const { data: tasks = [], isLoading, error } = useQuery({
    queryKey: ['tasks'],
    queryFn: getTasks,
    refetchInterval: 10000,
  })

  const { data: questions = [], isLoading: questionsLoading } = useQuery({
    queryKey: ['questions'],
    queryFn: () => getQuestions(),
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

  const answerMutation = useMutation({
    mutationFn: ({ questionId, answer }) => answerQuestion(questionId, answer),
    onSuccess: () => {
      queryClient.invalidateQueries(['questions'])
      queryClient.invalidateQueries(['plans'])
    },
  })

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

      {/* Approval Tasks Section */}
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
