/**
 * Chat Page - Main interface for Druppie governance
 * Shows workflow events and conversation history sidebar
 */

import React, { useState, useRef, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Send,
  Bot,
  User,
  AlertCircle,
  CheckCircle,
  Loader2,
  Brain,
  GitBranch,
  FileCode,
  Hammer,
  Play,
  Zap,
  Clock,
  AlertTriangle,
  XCircle,
  ChevronDown,
  ChevronRight,
  ExternalLink,
  Plus,
  MessageSquare,
  History,
  Trash2,
  HelpCircle,
  Bug,
  Copy,
  Check,
  X,
} from 'lucide-react'
import { sendChat, getPlans, answerQuestion, approveTask, rejectTask } from '../services/api'
import { useAuth } from '../App'

// Icon mapping for workflow events
const getEventIcon = (eventType, status) => {
  const iconProps = { className: 'w-4 h-4' }

  if (status === 'working') {
    return <Loader2 {...iconProps} className="w-4 h-4 animate-spin" />
  }

  switch (eventType) {
    case 'workflow_started':
      return <Zap {...iconProps} />
    case 'router_analyzing':
    case 'intent_detected':
      return <Brain {...iconProps} />
    case 'plan_creating':
    case 'plan_ready':
    case 'task_created':
    case 'task_executing':
    case 'task_completed':
      return <Clock {...iconProps} />
    case 'mcp_tool':
      return <Hammer {...iconProps} />
    case 'llm_generating':
    case 'llm_calling':
    case 'llm_response':
      return <Brain {...iconProps} />
    case 'agent_started':
    case 'agent_completed':
      return <Bot {...iconProps} />
    case 'agent_failed':
    case 'agent_error':
      return <XCircle {...iconProps} />
    case 'agent_question':
      return <HelpCircle {...iconProps} />
    case 'tool_executing':
    case 'tool_completed':
      return <Hammer {...iconProps} />
    case 'files_created':
      return <FileCode {...iconProps} />
    case 'git_pushed':
      return <GitBranch {...iconProps} />
    case 'build_complete':
      return <Hammer {...iconProps} />
    case 'app_running':
      return <Play {...iconProps} />
    case 'approval_required':
      return <AlertTriangle {...iconProps} />
    case 'question_pending':
      return <HelpCircle {...iconProps} />
    case 'workflow_completed':
      return <CheckCircle {...iconProps} />
    case 'workflow_failed':
    case 'task_failed':
      return <XCircle {...iconProps} />
    default:
      return <Zap {...iconProps} />
  }
}

// Status color mapping
const getStatusColors = (status) => {
  switch (status) {
    case 'success':
      return 'bg-green-50 border-green-200 text-green-800'
    case 'error':
      return 'bg-red-50 border-red-200 text-red-800'
    case 'warning':
      return 'bg-yellow-50 border-yellow-200 text-yellow-800'
    case 'working':
      return 'bg-blue-50 border-blue-200 text-blue-800'
    default:
      return 'bg-gray-50 border-gray-200 text-gray-800'
  }
}

const getIconBgColor = (status) => {
  switch (status) {
    case 'success':
      return 'bg-green-100 text-green-600'
    case 'error':
      return 'bg-red-100 text-red-600'
    case 'warning':
      return 'bg-yellow-100 text-yellow-600'
    case 'working':
      return 'bg-blue-100 text-blue-600'
    default:
      return 'bg-gray-100 text-gray-600'
  }
}

// Workflow Event Component
const WorkflowEvent = ({ event }) => {
  const colors = getStatusColors(event.status)
  const iconBg = getIconBgColor(event.status)

  // Check if this is an agent/LLM event for compact display
  const isAgentEvent = event.event_type?.includes('agent_') || event.event_type?.includes('llm_') || event.event_type?.includes('tool_')

  return (
    <div className={`flex items-start gap-2 p-2 rounded-lg border ${colors} mb-1 ${isAgentEvent ? 'text-xs' : ''}`}>
      <div className={`p-1 rounded-full ${iconBg} flex-shrink-0`}>
        {getEventIcon(event.event_type, event.status)}
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="font-medium text-sm">{event.title}</span>
          {event.data?.agent_id && (
            <span className="text-xs bg-purple-100 text-purple-600 px-1.5 py-0.5 rounded">
              {event.data.agent_id}
            </span>
          )}
          {event.data?.duration_ms && (
            <span className="text-xs text-gray-500">
              {event.data.duration_ms}ms
            </span>
          )}
        </div>
        <div className="text-xs opacity-80 mt-0.5 truncate">{event.description}</div>
        {event.data?.tool_calls && event.data.tool_calls.length > 0 && (
          <div className="text-xs mt-1 flex flex-wrap gap-1">
            {event.data.tool_calls.map((tc, i) => (
              <span key={i} className="bg-blue-100 text-blue-700 px-1.5 py-0.5 rounded">
                {tc}
              </span>
            ))}
          </div>
        )}
        {event.data?.tool && (
          <div className="text-xs mt-1">
            <span className="bg-orange-100 text-orange-700 px-1.5 py-0.5 rounded">
              {event.data.tool}
            </span>
          </div>
        )}
        {event.data?.repo_url && (
          <a
            href={event.data.repo_url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 text-xs mt-1 text-blue-600 hover:underline"
          >
            <ExternalLink className="w-3 h-3" />
            View Repository
          </a>
        )}
        {event.data?.url && (
          <a
            href={event.data.url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 text-xs mt-1 text-green-600 hover:underline"
          >
            <ExternalLink className="w-3 h-3" />
            Open App
          </a>
        )}
        {event.data?.features && event.data.features.length > 0 && (
          <div className="text-xs mt-1 opacity-70">
            Features: {event.data.features.join(', ')}
          </div>
        )}
      </div>
    </div>
  )
}

// Process workflow events to mark "working" events as complete if there are subsequent events
const processWorkflowEvents = (events) => {
  if (!events || events.length === 0) return events

  return events.map((event, index) => {
    // If this event has "working" status and there's a subsequent event, mark it as complete
    if (event.status === 'working' && index < events.length - 1) {
      // Check if any subsequent event indicates this step completed
      const subsequentEvents = events.slice(index + 1)
      const hasSubsequent = subsequentEvents.length > 0

      if (hasSubsequent) {
        // Determine appropriate status based on event type
        let newStatus = 'success'
        if (event.event_type === 'task_executing' || event.event_type === 'executing') {
          // Check if there's a failed event
          const hasFailed = subsequentEvents.some(e =>
            e.event_type?.includes('failed') || e.status === 'error'
          )
          newStatus = hasFailed ? 'error' : 'success'
        }
        return { ...event, status: newStatus }
      }
    }
    return event
  })
}

// Workflow Events Timeline (collapsible) - Shows agent/LLM activity live
const WorkflowTimeline = ({ events, isExpanded, onToggle }) => {
  if (!events || events.length === 0) return null

  // Process events to update statuses
  const processedEvents = processWorkflowEvents(events)

  // Group events by agent for a cleaner view
  const agentEvents = processedEvents.filter(e =>
    e.event_type?.includes('agent_') || e.event_type?.includes('llm_') || e.event_type?.includes('tool_')
  )
  const otherEvents = processedEvents.filter(e =>
    !e.event_type?.includes('agent_') && !e.event_type?.includes('llm_') && !e.event_type?.includes('tool_')
  )

  // Count LLM calls and agents
  const llmCalls = processedEvents.filter(e => e.event_type === 'llm_response').length
  const agentsRun = [...new Set(processedEvents.filter(e => e.data?.agent_id).map(e => e.data.agent_id))].length

  return (
    <div className="mt-3 border-t border-gray-100 pt-3">
      <button
        onClick={onToggle}
        className="flex items-center gap-2 text-sm text-gray-600 hover:text-gray-800 mb-2 w-full"
      >
        {isExpanded ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
        <span className="font-medium">Execution Log</span>
        <div className="flex items-center gap-2 ml-auto">
          {agentsRun > 0 && (
            <span className="text-xs bg-purple-100 text-purple-700 px-2 py-0.5 rounded-full flex items-center gap-1">
              <Bot className="w-3 h-3" />
              {agentsRun} agent(s)
            </span>
          )}
          {llmCalls > 0 && (
            <span className="text-xs bg-blue-100 text-blue-700 px-2 py-0.5 rounded-full flex items-center gap-1">
              <Brain className="w-3 h-3" />
              {llmCalls} LLM call(s)
            </span>
          )}
          <span className="text-xs bg-gray-100 px-2 py-0.5 rounded-full">{processedEvents.length} events</span>
        </div>
      </button>

      {isExpanded && (
        <div className="space-y-1 pl-2 border-l-2 border-blue-200 ml-2 max-h-96 overflow-y-auto">
          {processedEvents.map((event, index) => (
            <WorkflowEvent key={index} event={event} />
          ))}
        </div>
      )}
    </div>
  )
}

// Question Card Component - displays a question from an agent
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
    <div className="mt-3 bg-purple-50 rounded-lg border border-purple-200 p-4">
      <div className="flex items-start gap-3">
        <div className="p-2 bg-purple-100 rounded-full">
          <HelpCircle className="w-5 h-5 text-purple-600" />
        </div>
        <div className="flex-1">
          <div className="text-sm font-medium text-purple-900 mb-1">
            Agent needs your input
          </div>
          <div className="text-purple-800 font-medium mb-2">
            {question.question}
          </div>
          {question.context && (
            <div className="text-sm text-purple-600 mb-3">
              {question.context}
            </div>
          )}

          {/* Options as clickable buttons */}
          {hasOptions && (
            <div className="space-y-2 mb-3">
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
          <div className="mb-3">
            <input
              type="text"
              value={customAnswer}
              onChange={(e) => {
                setCustomAnswer(e.target.value)
                setSelectedOption(null)
              }}
              placeholder={hasOptions ? "Or type a custom answer..." : "Type your answer..."}
              className="w-full px-3 py-2 border border-purple-200 rounded-lg focus:ring-2 focus:ring-purple-500 focus:border-transparent text-sm"
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
      </div>
    </div>
  )
}

// Inline Approval Card Component - allows approve/reject directly in chat
const ApprovalCard = ({ approval, onApprove, onReject, isProcessing }) => {
  const [showRejectInput, setShowRejectInput] = useState(false)
  const [rejectReason, setRejectReason] = useState('')

  const handleReject = () => {
    if (showRejectInput && rejectReason.trim()) {
      onReject(approval.task_id, rejectReason)
      setShowRejectInput(false)
      setRejectReason('')
    } else {
      setShowRejectInput(true)
    }
  }

  const isMultiApproval = approval.approval_type === 'multi'
  const requiredApprovals = approval.required_approvals || 1
  const currentApprovals = approval.current_approvals || 0
  const approvedByRoles = approval.approved_by_roles || []
  const requiredRoles = approval.required_roles || [approval.required_role]
  const remainingRoles = requiredRoles.filter(r => !approvedByRoles.includes(r))
  const progressPercent = Math.round((currentApprovals / requiredApprovals) * 100)

  return (
    <div className="mt-3 bg-amber-50 rounded-lg border border-amber-200 p-4">
      <div className="flex items-start gap-3">
        <div className="p-2 bg-amber-100 rounded-full">
          <AlertTriangle className="w-5 h-5 text-amber-600" />
        </div>
        <div className="flex-1">
          <div className="flex items-center justify-between mb-1">
            <div className="text-sm font-medium text-amber-900">
              {isMultiApproval ? 'Multi-Approval Required' : 'Approval Required'}
            </div>
            {isMultiApproval && (
              <span className="text-xs bg-amber-200 text-amber-800 px-2 py-0.5 rounded-full">
                {currentApprovals} of {requiredApprovals} approvals
              </span>
            )}
          </div>
          <div className="text-amber-800 font-medium mb-2">
            {approval.task_name}
          </div>

          {/* MULTI approval progress */}
          {isMultiApproval && (
            <div className="mb-3">
              {/* Progress bar */}
              <div className="w-full bg-amber-200 rounded-full h-2 mb-2">
                <div
                  className="bg-green-500 h-2 rounded-full transition-all duration-300"
                  style={{ width: `${progressPercent}%` }}
                />
              </div>

              {/* Approved roles */}
              {approvedByRoles.length > 0 && (
                <div className="flex flex-wrap gap-1 mb-2">
                  <span className="text-xs text-amber-700">Approved by:</span>
                  {approvedByRoles.map(role => (
                    <span key={role} className="inline-flex items-center gap-1 px-2 py-0.5 bg-green-100 text-green-700 text-xs rounded-full">
                      <CheckCircle className="w-3 h-3" />
                      {role}
                    </span>
                  ))}
                </div>
              )}

              {/* Remaining roles */}
              {remainingRoles.length > 0 && (
                <div className="flex flex-wrap gap-1">
                  <span className="text-xs text-amber-700">Still needed:</span>
                  {remainingRoles.map(role => (
                    <span key={role} className="px-2 py-0.5 bg-amber-100 text-amber-700 text-xs rounded-full">
                      {role}
                    </span>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Single approval role display */}
          {!isMultiApproval && (
            <div className="text-sm text-amber-700 mb-3">
              This action requires approval from <span className="font-semibold">{approval.required_role}</span> role.
            </div>
          )}

          {approval.mcp_tool && (
            <div className="text-sm text-amber-700 mb-3">
              MCP Tool: <code className="bg-amber-100 px-1 rounded">{approval.mcp_tool}</code>
            </div>
          )}

          {/* Reject reason input */}
          {showRejectInput && (
            <div className="mb-3">
              <input
                type="text"
                value={rejectReason}
                onChange={(e) => setRejectReason(e.target.value)}
                placeholder="Enter reason for rejection..."
                className="w-full px-3 py-2 border border-amber-200 rounded-lg focus:ring-2 focus:ring-amber-500 focus:border-transparent text-sm"
                autoFocus
              />
            </div>
          )}

          {/* Action buttons */}
          <div className="flex items-center gap-2">
            <button
              onClick={() => onApprove(approval.task_id)}
              disabled={isProcessing || showRejectInput}
              className="flex items-center gap-2 px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {isProcessing ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  Processing...
                </>
              ) : (
                <>
                  <CheckCircle className="w-4 h-4" />
                  {isMultiApproval ? `Add Approval (${currentApprovals + 1}/${requiredApprovals})` : 'Approve'}
                </>
              )}
            </button>
            <button
              onClick={handleReject}
              disabled={isProcessing}
              className={`flex items-center gap-2 px-4 py-2 rounded-lg transition-colors ${
                showRejectInput
                  ? 'bg-red-600 text-white hover:bg-red-700'
                  : 'bg-white text-red-600 border border-red-200 hover:bg-red-50'
              } disabled:opacity-50 disabled:cursor-not-allowed`}
            >
              <XCircle className="w-4 h-4" />
              {showRejectInput ? 'Confirm Reject' : 'Reject'}
            </button>
            {showRejectInput && (
              <button
                onClick={() => {
                  setShowRejectInput(false)
                  setRejectReason('')
                }}
                className="px-3 py-2 text-gray-600 hover:text-gray-800 text-sm"
              >
                Cancel
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

const Message = ({ message, onAnswerQuestion, isAnsweringQuestion, onApproveTask, onRejectTask, isApprovingTask }) => {
  const isUser = message.role === 'user'
  const [eventsExpanded, setEventsExpanded] = useState(true)

  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'} mb-4`}>
      <div
        className={`max-w-[85%] rounded-2xl px-4 py-3 ${
          isUser
            ? 'bg-blue-600 text-white rounded-br-none'
            : 'bg-white border border-gray-200 rounded-bl-none shadow-sm'
        }`}
      >
        <div className="flex items-start space-x-2">
          {!isUser && (
            <div className="w-8 h-8 rounded-full bg-gradient-to-br from-blue-500 to-purple-600 flex items-center justify-center flex-shrink-0">
              <Bot className="w-5 h-5 text-white" />
            </div>
          )}
          <div className="flex-1 min-w-0">
            {/* Agent attribution badges */}
            {!isUser && message.workflowEvents && message.workflowEvents.length > 0 && (
              <div className="flex items-center gap-2 mb-2 flex-wrap">
                {[...new Set(message.workflowEvents
                  .filter(e => e.data?.agent_id)
                  .map(e => e.data.agent_id)
                )].map(agentId => (
                  <span
                    key={agentId}
                    className="inline-flex items-center gap-1 px-2 py-0.5 bg-purple-100 text-purple-700 text-xs rounded-full"
                  >
                    <Bot className="w-3 h-3" />
                    {agentId.replace('_agent', '').replace(/_/g, ' ')}
                  </span>
                ))}
              </div>
            )}

            {/* Main content */}
            {message.content && (
              <div className="whitespace-pre-wrap text-sm">{message.content}</div>
            )}

            {/* Workflow Events Timeline */}
            {!isUser && message.workflowEvents && message.workflowEvents.length > 0 && (
              <WorkflowTimeline
                events={message.workflowEvents}
                isExpanded={eventsExpanded}
                onToggle={() => setEventsExpanded(!eventsExpanded)}
              />
            )}

            {/* Pending Approvals - Inline approval cards */}
            {message.pendingApprovals && message.pendingApprovals.length > 0 && (
              message.pendingApprovals.map((approval, i) => (
                <ApprovalCard
                  key={approval.task_id || i}
                  approval={approval}
                  onApprove={onApproveTask}
                  onReject={onRejectTask}
                  isProcessing={isApprovingTask}
                />
              ))
            )}

            {/* Pending Questions */}
            {message.pendingQuestions && message.pendingQuestions.length > 0 && (
              message.pendingQuestions.map((question) => (
                <QuestionCard
                  key={question.id}
                  question={question}
                  onAnswer={onAnswerQuestion}
                  isAnswering={isAnsweringQuestion}
                />
              ))
            )}
          </div>
          {isUser && (
            <div className="w-8 h-8 rounded-full bg-blue-500 flex items-center justify-center flex-shrink-0">
              <User className="w-5 h-5 text-white" />
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// Typing indicator with workflow step
const TypingIndicator = ({ currentStep }) => {
  // Define workflow steps for visual progress
  const workflowSteps = [
    { id: 'analyzing', label: 'Analyzing', icon: Brain },
    { id: 'planning', label: 'Planning', icon: Clock },
    { id: 'executing', label: 'Executing', icon: Zap },
  ]

  // Determine current step from message
  const getCurrentStepIndex = () => {
    const step = (currentStep || '').toLowerCase()
    if (step.includes('analyz') || step.includes('router') || step.includes('intent')) return 0
    if (step.includes('plan') || step.includes('creat')) return 1
    if (step.includes('execut') || step.includes('generat') || step.includes('build') || step.includes('answer')) return 2
    return 0
  }

  const currentStepIndex = getCurrentStepIndex()

  return (
    <div className="flex justify-start mb-4">
      <div className="bg-white border border-gray-200 rounded-2xl rounded-bl-none px-4 py-4 shadow-sm min-w-[300px]">
        <div className="flex items-center space-x-3 mb-3">
          <div className="w-8 h-8 rounded-full bg-gradient-to-br from-blue-500 to-purple-600 flex items-center justify-center">
            <Loader2 className="w-5 h-5 text-white animate-spin" />
          </div>
          <div className="flex-1">
            <div className="text-sm font-medium text-gray-800">
              {currentStep || 'Processing...'}
            </div>
          </div>
        </div>

        {/* Progress steps */}
        <div className="flex items-center justify-between px-2">
          {workflowSteps.map((step, idx) => {
            const StepIcon = step.icon
            const isActive = idx === currentStepIndex
            const isComplete = idx < currentStepIndex

            return (
              <div key={step.id} className="flex items-center">
                <div className="flex flex-col items-center">
                  <div
                    className={`w-8 h-8 rounded-full flex items-center justify-center transition-all ${
                      isActive
                        ? 'bg-blue-500 text-white animate-pulse'
                        : isComplete
                        ? 'bg-green-500 text-white'
                        : 'bg-gray-200 text-gray-400'
                    }`}
                  >
                    {isComplete ? (
                      <CheckCircle className="w-4 h-4" />
                    ) : (
                      <StepIcon className={`w-4 h-4 ${isActive ? 'animate-pulse' : ''}`} />
                    )}
                  </div>
                  <span className={`text-xs mt-1 ${isActive ? 'text-blue-600 font-medium' : 'text-gray-500'}`}>
                    {step.label}
                  </span>
                </div>
                {idx < workflowSteps.length - 1 && (
                  <div
                    className={`w-12 h-0.5 mx-1 ${
                      isComplete ? 'bg-green-500' : 'bg-gray-200'
                    }`}
                  />
                )}
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

// Conversation History Sidebar Item
const ConversationItem = ({ plan, isActive, onClick }) => {
  const getStatusColor = (status) => {
    switch (status) {
      case 'completed':
        return 'bg-green-500'
      case 'running':
        return 'bg-blue-500'
      case 'pending_approval':
        return 'bg-yellow-500'
      case 'failed':
        return 'bg-red-500'
      default:
        return 'bg-gray-400'
    }
  }

  // Extract a cleaner title from the plan name
  const title = plan.name?.replace(/^Chat:\s*/i, '').slice(0, 40) || 'Untitled'
  const date = new Date(plan.created_at).toLocaleDateString()

  return (
    <button
      onClick={onClick}
      className={`w-full text-left p-3 rounded-lg transition-all ${
        isActive
          ? 'bg-blue-50 border border-blue-200'
          : 'hover:bg-gray-50 border border-transparent'
      }`}
    >
      <div className="flex items-start gap-2">
        <MessageSquare className={`w-4 h-4 mt-0.5 flex-shrink-0 ${isActive ? 'text-blue-600' : 'text-gray-400'}`} />
        <div className="flex-1 min-w-0">
          <div className={`text-sm font-medium truncate ${isActive ? 'text-blue-900' : 'text-gray-800'}`}>
            {title}...
          </div>
          <div className="flex items-center gap-2 mt-1">
            <span className={`w-2 h-2 rounded-full ${getStatusColor(plan.status)}`} />
            <span className="text-xs text-gray-500">{date}</span>
          </div>
        </div>
      </div>
    </button>
  )
}

// Conversation History Sidebar
const ConversationSidebar = ({ plans, activePlanId, onSelectPlan, onNewChat }) => {
  return (
    <div className="w-72 bg-white border-r border-gray-200 flex flex-col h-full">
      {/* Header */}
      <div className="p-4 border-b border-gray-200">
        <button
          onClick={onNewChat}
          className="w-full flex items-center justify-center gap-2 px-4 py-2.5 bg-gradient-to-r from-blue-600 to-purple-600 text-white rounded-lg hover:from-blue-700 hover:to-purple-700 transition-all shadow-md"
        >
          <Plus className="w-4 h-4" />
          New Chat
        </button>
      </div>

      {/* Conversation List */}
      <div className="flex-1 overflow-y-auto p-2">
        <div className="flex items-center gap-2 px-2 py-2 text-xs font-medium text-gray-500 uppercase">
          <History className="w-3 h-3" />
          Recent Conversations
        </div>
        <div className="space-y-1">
          {plans?.length > 0 ? (
            plans.map((plan) => (
              <ConversationItem
                key={plan.id}
                plan={plan}
                isActive={plan.id === activePlanId}
                onClick={() => onSelectPlan(plan)}
              />
            ))
          ) : (
            <div className="text-center py-8 text-gray-500 text-sm">
              <MessageSquare className="w-8 h-8 mx-auto mb-2 opacity-30" />
              <p>No conversations yet</p>
              <p className="text-xs mt-1">Start a new chat!</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// Debug Panel - Shows API and LLM calls for debugging
const DebugPanel = ({ isOpen, onClose, apiCalls }) => {
  const [copiedIndex, setCopiedIndex] = useState(null)
  const [expandedCalls, setExpandedCalls] = useState({})
  const [allCopied, setAllCopied] = useState(false)

  const copyToClipboard = (text, index) => {
    navigator.clipboard.writeText(text)
    setCopiedIndex(index)
    setTimeout(() => setCopiedIndex(null), 2000)
  }

  const copyAllToClipboard = () => {
    const fullData = JSON.stringify(apiCalls, null, 2)
    navigator.clipboard.writeText(fullData)
    setAllCopied(true)
    setTimeout(() => setAllCopied(false), 2000)
  }

  const toggleExpand = (index) => {
    setExpandedCalls(prev => ({ ...prev, [index]: !prev[index] }))
  }

  const expandAll = () => {
    const allExpanded = {}
    apiCalls?.forEach((_, index) => { allExpanded[index] = true })
    setExpandedCalls(allExpanded)
  }

  const collapseAll = () => {
    setExpandedCalls({})
  }

  if (!isOpen) return null

  const llmCalls = apiCalls?.filter(c => c.type === 'llm') || []
  const httpCalls = apiCalls?.filter(c => c.type === 'api') || []

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="bg-white rounded-xl shadow-2xl w-[95vw] max-w-5xl max-h-[90vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-orange-100 rounded-lg">
              <Bug className="w-5 h-5 text-orange-600" />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-gray-900">Debug Panel</h2>
              <p className="text-sm text-gray-500">
                {llmCalls.length} LLM call(s), {httpCalls.length} API call(s)
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {/* Action buttons */}
            <button
              onClick={expandAll}
              className="px-3 py-1.5 text-xs text-gray-600 hover:text-gray-800 hover:bg-gray-100 rounded-lg transition-colors"
            >
              Expand All
            </button>
            <button
              onClick={collapseAll}
              className="px-3 py-1.5 text-xs text-gray-600 hover:text-gray-800 hover:bg-gray-100 rounded-lg transition-colors"
            >
              Collapse All
            </button>
            <button
              onClick={copyAllToClipboard}
              className="flex items-center gap-1 px-3 py-1.5 text-xs bg-blue-100 text-blue-700 hover:bg-blue-200 rounded-lg transition-colors"
            >
              {allCopied ? (
                <><Check className="w-3 h-3" /> Copied All!</>
              ) : (
                <><Copy className="w-3 h-3" /> Copy All</>
              )}
            </button>
            <button
              onClick={onClose}
              className="p-2 hover:bg-gray-100 rounded-lg transition-colors ml-2"
            >
              <X className="w-5 h-5 text-gray-500" />
            </button>
          </div>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {apiCalls && apiCalls.length > 0 ? (
            apiCalls.map((call, index) => (
              <div key={index} className={`rounded-lg border overflow-hidden ${
                call.type === 'llm' ? 'bg-purple-50 border-purple-200' : 'bg-gray-50 border-gray-200'
              }`}>
                {/* Call Header */}
                <div className={`flex items-center justify-between px-4 py-3 border-b cursor-pointer ${
                  call.type === 'llm' ? 'bg-purple-100 border-purple-200' : 'bg-gray-100 border-gray-200'
                }`} onClick={() => toggleExpand(index)}>
                  <div className="flex items-center gap-3">
                    {call.type === 'llm' ? (
                      <>
                        <span className="px-2 py-1 rounded text-xs font-bold bg-purple-600 text-white">
                          LLM
                        </span>
                        <div>
                          <span className="text-sm font-medium text-purple-900">{call.name || 'LLM Call'}</span>
                          <span className="text-xs text-purple-600 ml-2">({call.model})</span>
                        </div>
                      </>
                    ) : (
                      <>
                        <span className={`px-2 py-1 rounded text-xs font-bold ${
                          call.method === 'POST' ? 'bg-green-600 text-white' :
                          call.method === 'GET' ? 'bg-blue-600 text-white' :
                          'bg-gray-600 text-white'
                        }`}>
                          {call.method || 'POST'}
                        </span>
                        <code className="text-sm text-gray-700">{call.endpoint || '/api/chat'}</code>
                      </>
                    )}
                  </div>
                  <div className="flex items-center gap-3">
                    {call.duration_ms && (
                      <span className="text-xs text-gray-500">{call.duration_ms}ms</span>
                    )}
                    <span className={`text-xs px-2 py-1 rounded ${
                      call.status === 'success' ? 'bg-green-100 text-green-700' :
                      call.status === 'error' ? 'bg-red-100 text-red-700' :
                      'bg-yellow-100 text-yellow-700'
                    }`}>
                      {call.status || 'completed'}
                    </span>
                    <span className="text-xs text-gray-500">
                      {call.timestamp ? new Date(call.timestamp).toLocaleTimeString() : ''}
                    </span>
                    {expandedCalls[index] ? (
                      <ChevronDown className="w-4 h-4 text-gray-400" />
                    ) : (
                      <ChevronRight className="w-4 h-4 text-gray-400" />
                    )}
                  </div>
                </div>

                {/* Expanded Content */}
                {expandedCalls[index] && (
                  <div className="p-4 space-y-4">
                    {/* LLM-specific: Show Messages */}
                    {call.type === 'llm' && call.request?.messages && (
                      <div>
                        <div className="flex items-center justify-between mb-2">
                          <span className="text-xs font-medium text-purple-600 uppercase">Messages (Prompt)</span>
                          <button
                            onClick={() => copyToClipboard(JSON.stringify(call.request.messages, null, 2), `msg-${index}`)}
                            className="flex items-center gap-1 text-xs text-gray-500 hover:text-gray-700"
                          >
                            {copiedIndex === `msg-${index}` ? (
                              <><Check className="w-3 h-3 text-green-500" /> Copied!</>
                            ) : (
                              <><Copy className="w-3 h-3" /> Copy</>
                            )}
                          </button>
                        </div>
                        <div className="space-y-2">
                          {call.request.messages.map((msg, msgIdx) => (
                            <div key={msgIdx} className={`p-3 rounded-lg ${
                              msg.role === 'system' ? 'bg-blue-900 text-blue-100' :
                              msg.role === 'user' ? 'bg-gray-800 text-gray-100' :
                              'bg-green-900 text-green-100'
                            }`}>
                              <div className="text-xs font-bold uppercase mb-1 opacity-70">{msg.role}</div>
                              <pre className="text-xs whitespace-pre-wrap overflow-x-auto max-h-64">{msg.content}</pre>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* LLM-specific: Show Agent Info and Tool Calls */}
                    {call.type === 'llm' && (call.agent_id || call.tool_calls?.length > 0 || call.usage) && (
                      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-4">
                        {/* Agent Info */}
                        {call.agent_id && (
                          <div className="bg-purple-100 rounded-lg p-3">
                            <span className="text-xs font-medium text-purple-600 uppercase block mb-1">Agent</span>
                            <div className="flex items-center gap-2">
                              <Bot className="w-4 h-4 text-purple-600" />
                              <span className="text-sm font-medium text-purple-900">{call.agent_id}</span>
                              {call.iteration && (
                                <span className="text-xs bg-purple-200 text-purple-700 px-1.5 py-0.5 rounded">
                                  iter {call.iteration}
                                </span>
                              )}
                            </div>
                          </div>
                        )}

                        {/* Token Usage */}
                        {call.usage && (
                          <div className="bg-blue-100 rounded-lg p-3">
                            <span className="text-xs font-medium text-blue-600 uppercase block mb-1">Token Usage</span>
                            <div className="text-sm space-y-1">
                              <div className="flex justify-between">
                                <span className="text-blue-600">Prompt:</span>
                                <span className="font-mono text-blue-900">{call.usage.prompt_tokens || 0}</span>
                              </div>
                              <div className="flex justify-between">
                                <span className="text-blue-600">Completion:</span>
                                <span className="font-mono text-blue-900">{call.usage.completion_tokens || 0}</span>
                              </div>
                              <div className="flex justify-between border-t border-blue-200 pt-1">
                                <span className="text-blue-600 font-medium">Total:</span>
                                <span className="font-mono font-medium text-blue-900">{call.usage.total_tokens || 0}</span>
                              </div>
                            </div>
                          </div>
                        )}

                        {/* Tool Calls */}
                        {call.tool_calls?.length > 0 && (
                          <div className="bg-orange-100 rounded-lg p-3">
                            <span className="text-xs font-medium text-orange-600 uppercase block mb-1">Tool Calls</span>
                            <div className="space-y-1">
                              {call.tool_calls.map((tc, tcIdx) => (
                                <div key={tcIdx} className="flex items-center gap-2">
                                  <Hammer className="w-3 h-3 text-orange-600" />
                                  <span className="text-sm font-mono text-orange-900">{tc.name || tc}</span>
                                </div>
                              ))}
                            </div>
                          </div>
                        )}
                      </div>
                    )}

                    {/* LLM-specific: Show Agent Parsed Data (structured output from done() tool) */}
                    {call.type === 'llm' && call.parsed_data && Object.keys(call.parsed_data).length > 0 && (
                      <div>
                        <div className="flex items-center justify-between mb-2">
                          <span className="text-xs font-medium text-green-600 uppercase">
                            Agent Output (done() data) {call.agent_summary && `- ${call.agent_summary.substring(0, 50)}`}
                          </span>
                          <button
                            onClick={() => copyToClipboard(JSON.stringify(call.parsed_data, null, 2), `parsed-${index}`)}
                            className="flex items-center gap-1 text-xs text-gray-500 hover:text-gray-700"
                          >
                            {copiedIndex === `parsed-${index}` ? (
                              <><Check className="w-3 h-3 text-green-500" /> Copied!</>
                            ) : (
                              <><Copy className="w-3 h-3" /> Copy</>
                            )}
                          </button>
                        </div>
                        <pre className="text-xs bg-green-900 text-green-200 p-3 rounded-lg overflow-x-auto max-h-96 whitespace-pre-wrap">
                          {JSON.stringify(call.parsed_data, null, 2)}
                        </pre>
                      </div>
                    )}

                    {/* LLM-specific: Show Parsed/Cleaned Response */}
                    {call.type === 'llm' && call.response && (
                      <div>
                        <div className="flex items-center justify-between mb-2">
                          <span className="text-xs font-medium text-purple-600 uppercase">LLM Response Content</span>
                          <button
                            onClick={() => copyToClipboard(typeof call.response === 'string' ? call.response : JSON.stringify(call.response, null, 2), `llmres-${index}`)}
                            className="flex items-center gap-1 text-xs text-gray-500 hover:text-gray-700"
                          >
                            {copiedIndex === `llmres-${index}` ? (
                              <><Check className="w-3 h-3 text-green-500" /> Copied!</>
                            ) : (
                              <><Copy className="w-3 h-3" /> Copy</>
                            )}
                          </button>
                        </div>
                        <pre className="text-xs bg-gray-900 text-green-400 p-3 rounded-lg overflow-x-auto max-h-64 whitespace-pre-wrap">
                          {typeof call.response === 'string' ? call.response : JSON.stringify(call.response, null, 2)}
                        </pre>
                      </div>
                    )}

                    {/* LLM-specific: Show Raw Unclean Content */}
                    {call.type === 'llm' && call.response_raw && (
                      <div>
                        <div className="flex items-center justify-between mb-2">
                          <span className="text-xs font-medium text-orange-600 uppercase">Raw LLM Output (unclean, includes think tags)</span>
                          <button
                            onClick={() => copyToClipboard(call.response_raw, `rawcontent-${index}`)}
                            className="flex items-center gap-1 text-xs text-gray-500 hover:text-gray-700"
                          >
                            {copiedIndex === `rawcontent-${index}` ? (
                              <><Check className="w-3 h-3 text-green-500" /> Copied!</>
                            ) : (
                              <><Copy className="w-3 h-3" /> Copy</>
                            )}
                          </button>
                        </div>
                        <pre className="text-xs bg-gray-800 text-orange-300 p-3 rounded-lg overflow-x-auto max-h-96 whitespace-pre-wrap">
                          {call.response_raw}
                        </pre>
                      </div>
                    )}

                    {/* LLM-specific: Show Full API Response Object */}
                    {call.type === 'llm' && call.raw_response && (
                      <div>
                        <div className="flex items-center justify-between mb-2">
                          <span className="text-xs font-medium text-yellow-600 uppercase">Full API Response Object</span>
                          <button
                            onClick={() => copyToClipboard(JSON.stringify(call.raw_response, null, 2), `raw-${index}`)}
                            className="flex items-center gap-1 text-xs text-gray-500 hover:text-gray-700"
                          >
                            {copiedIndex === `raw-${index}` ? (
                              <><Check className="w-3 h-3 text-green-500" /> Copied!</>
                            ) : (
                              <><Copy className="w-3 h-3" /> Copy</>
                            )}
                          </button>
                        </div>
                        <pre className="text-xs bg-gray-900 text-yellow-400 p-3 rounded-lg overflow-x-auto max-h-48">
                          {JSON.stringify(call.raw_response, null, 2)}
                        </pre>
                      </div>
                    )}

                    {/* HTTP API calls: Request */}
                    {call.type === 'api' && call.request && (
                      <div>
                        <div className="flex items-center justify-between mb-2">
                          <span className="text-xs font-medium text-gray-500 uppercase">Request</span>
                          <button
                            onClick={() => copyToClipboard(JSON.stringify(call.request, null, 2), `req-${index}`)}
                            className="flex items-center gap-1 text-xs text-gray-500 hover:text-gray-700"
                          >
                            {copiedIndex === `req-${index}` ? (
                              <><Check className="w-3 h-3 text-green-500" /> Copied!</>
                            ) : (
                              <><Copy className="w-3 h-3" /> Copy</>
                            )}
                          </button>
                        </div>
                        <pre className="text-xs bg-gray-900 text-green-400 p-3 rounded-lg overflow-x-auto">
                          {JSON.stringify(call.request, null, 2)}
                        </pre>
                      </div>
                    )}

                    {/* HTTP API calls: Response */}
                    {call.type === 'api' && call.response && (
                      <div>
                        <div className="flex items-center justify-between mb-2">
                          <span className="text-xs font-medium text-gray-500 uppercase">Response</span>
                          <button
                            onClick={() => copyToClipboard(JSON.stringify(call.response, null, 2), `res-${index}`)}
                            className="flex items-center gap-1 text-xs text-gray-500 hover:text-gray-700"
                          >
                            {copiedIndex === `res-${index}` ? (
                              <><Check className="w-3 h-3 text-green-500" /> Copied!</>
                            ) : (
                              <><Copy className="w-3 h-3" /> Copy</>
                            )}
                          </button>
                        </div>
                        <pre className="text-xs bg-gray-900 text-green-400 p-3 rounded-lg overflow-x-auto max-h-64">
                          {JSON.stringify(call.response, null, 2)}
                        </pre>
                      </div>
                    )}

                    {/* Usage stats for LLM calls */}
                    {call.type === 'llm' && call.usage && (
                      <div className="flex items-center gap-4 text-xs text-purple-600">
                        <span>Tokens: {call.usage.total_tokens || 'N/A'}</span>
                        <span>Prompt: {call.usage.prompt_tokens || 'N/A'}</span>
                        <span>Completion: {call.usage.completion_tokens || 'N/A'}</span>
                      </div>
                    )}

                    {/* Error display */}
                    {call.error && (
                      <div className="p-3 bg-red-50 border border-red-200 rounded-lg">
                        <span className="text-xs font-medium text-red-600 uppercase">Error</span>
                        <pre className="text-xs text-red-700 mt-1">{call.error}</pre>
                      </div>
                    )}
                  </div>
                )}
              </div>
            ))
          ) : (
            <div className="text-center py-12 text-gray-500">
              <Bug className="w-12 h-12 mx-auto mb-4 opacity-30" />
              <p className="font-medium">No API calls yet</p>
              <p className="text-sm mt-1">Send a message to see API and LLM calls here</p>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-6 py-3 border-t border-gray-200 bg-gray-50">
          <p className="text-xs text-gray-500 text-center">
            {llmCalls.length} LLM call(s), {httpCalls.length} HTTP call(s) in this session
          </p>
        </div>
      </div>
    </div>
  )
}

const Chat = () => {
  const { user } = useAuth()
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [currentPlanId, setCurrentPlanId] = useState(null)
  const [currentStep, setCurrentStep] = useState(null)
  const [debugPanelOpen, setDebugPanelOpen] = useState(false)
  const [apiCalls, setApiCalls] = useState([])
  const messagesEndRef = useRef(null)
  const queryClient = useQueryClient()

  // Fetch conversation history (plans)
  const { data: plans = [] } = useQuery({
    queryKey: ['plans'],
    queryFn: getPlans,
    refetchInterval: 30000,
  })

  // Initialize with welcome message
  useEffect(() => {
    if (messages.length === 0 && !currentPlanId) {
      setMessages([
        {
          role: 'assistant',
          content: `Hello ${user?.firstName || user?.username}! I'm Druppie, your AI governance assistant.

I can help you:
• Create applications (just describe what you want!)
• Manage code deployments
• Check compliance and permissions

What would you like to build today?`,
        },
      ])
    }
  }, [user, currentPlanId])

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  useEffect(() => {
    scrollToBottom()
  }, [messages])

  const chatMutation = useMutation({
    mutationFn: async ({ message, conversationHistory }) => {
      // Track the API call start time
      const startTime = Date.now()

      const requestData = {
        message,
        plan_id: currentPlanId,
        conversation_history: conversationHistory.length > 0 ? conversationHistory : null,
      }

      try {
        const response = await sendChat(message, currentPlanId, requestData.conversation_history)

        // Log API call for debugging (frontend call + backend LLM calls)
        const apiCallRecord = {
          type: 'api',
          method: 'POST',
          endpoint: '/api/chat',
          timestamp: new Date().toISOString(),
          duration: Date.now() - startTime,
          status: 'success',
          request: requestData,
          response: { ...response, llm_calls: undefined }, // Exclude llm_calls from response display
        }

        // Add the API call and any LLM calls from the backend
        setApiCalls((prev) => [
          ...prev,
          apiCallRecord,
          ...(response.llm_calls || []).map(call => ({
            type: 'llm',
            ...call,
          })),
        ])

        return response
      } catch (error) {
        // Log failed API call
        setApiCalls((prev) => [
          ...prev,
          {
            type: 'api',
            method: 'POST',
            endpoint: '/api/chat',
            timestamp: new Date().toISOString(),
            duration: Date.now() - startTime,
            status: 'error',
            request: requestData,
            response: { error: error.message },
          },
        ])
        throw error
      }
    },
    onSuccess: (data) => {
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: data.response,
          planId: data.plan_id,
          pendingApprovals: data.pending_approvals,
          pendingQuestions: data.pending_questions || [],
          status: data.status,
          workflowEvents: data.workflow_events || [],
        },
      ])
      setCurrentPlanId(data.plan_id)
      setCurrentStep(null)
      queryClient.invalidateQueries(['projects'])
      queryClient.invalidateQueries(['plans'])
      queryClient.invalidateQueries(['tasks'])
      queryClient.invalidateQueries(['questions'])
    },
    onError: (error) => {
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: `Error: ${error.message}`,
        },
      ])
      setCurrentStep(null)
    },
  })

  // Mutation for approving tasks inline
  const approveMutation = useMutation({
    mutationFn: (taskId) => approveTask(taskId),
    onSuccess: (data, taskId) => {
      const isFullyApproved = !data.approvals_required ||
        (data.approvals_received >= data.approvals_required)

      // Always remove the approval card after user approves (can't approve twice)
      setMessages((prev) => prev.map(msg => {
        if (msg.pendingApprovals) {
          return {
            ...msg,
            pendingApprovals: msg.pendingApprovals.filter(a => a.task_id !== taskId),
          }
        }
        return msg
      }))

      // Show appropriate message based on approval status
      if (isFullyApproved) {
        setMessages((prev) => [
          ...prev,
          {
            role: 'assistant',
            content: `✅ Task fully approved! The action will now proceed.`,
          },
        ])
      } else {
        // MULTI approval - still needs more approvals from other roles
        const remaining = data.approvals_required - data.approvals_received
        setMessages((prev) => [
          ...prev,
          {
            role: 'assistant',
            content: `✅ Your approval has been recorded (${data.approvals_received}/${data.approvals_required}). Waiting for ${remaining} more approval(s) from other roles before the action can proceed.`,
          },
        ])
      }

      // Invalidate queries to refresh data
      queryClient.invalidateQueries(['tasks'])
      queryClient.invalidateQueries(['plans'])
    },
    onError: (error) => {
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: `❌ Error approving task: ${error.message}`,
        },
      ])
    },
  })

  // Mutation for rejecting tasks inline
  const rejectMutation = useMutation({
    mutationFn: ({ taskId, reason }) => rejectTask(taskId, reason),
    onSuccess: (data, { taskId }) => {
      // Remove the rejected task from pending approvals in messages
      setMessages((prev) => prev.map(msg => {
        if (msg.pendingApprovals) {
          return {
            ...msg,
            pendingApprovals: msg.pendingApprovals.filter(a => a.task_id !== taskId),
          }
        }
        return msg
      }))

      // Add rejection message
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: `🚫 Task rejected. The action has been cancelled.`,
        },
      ])

      // Invalidate queries
      queryClient.invalidateQueries(['tasks'])
      queryClient.invalidateQueries(['plans'])
    },
    onError: (error) => {
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: `❌ Error rejecting task: ${error.message}`,
        },
      ])
    },
  })

  const handleApproveTask = (taskId) => {
    approveMutation.mutate(taskId)
  }

  const handleRejectTask = (taskId, reason) => {
    rejectMutation.mutate({ taskId, reason })
  }

  // Mutation for answering questions
  const answerMutation = useMutation({
    mutationFn: ({ questionId, answer }) => answerQuestion(questionId, answer),
    onSuccess: (data, variables) => {
      // If backend continued the conversation (status: answered_and_continued), add the response
      if (data.status === 'answered_and_continued' && data.response) {
        setMessages((prev) => [
          ...prev,
          {
            role: 'assistant',
            content: data.response,
            planId: data.plan_id,
            pendingApprovals: data.pending_approvals,
            pendingQuestions: data.pending_questions || [],
            workflowEvents: data.workflow_events || [],
          },
        ])

        // Add LLM calls to debug panel
        if (data.llm_calls && data.llm_calls.length > 0) {
          setApiCalls((prevCalls) => [
            ...prevCalls,
            ...data.llm_calls.map(call => ({ type: 'llm', ...call })),
          ])
        }
      }

      queryClient.invalidateQueries(['questions'])
      queryClient.invalidateQueries(['plans'])
      queryClient.invalidateQueries(['projects'])
      setCurrentStep(null)
    },
    onError: (error, variables) => {
      // On error, restore the question and remove the optimistic user message
      setMessages((prev) => {
        // Find the original question from context (stored in variables)
        const restoredMessages = prev.filter(msg => msg.role !== 'user' || msg.content !== variables.answer)
        return [
          ...restoredMessages,
          {
            role: 'assistant',
            content: `Error answering question: ${error.message}`,
          },
        ]
      })
      setCurrentStep(null)
    },
  })

  const handleAnswerQuestion = (questionId, answer) => {
    // Optimistic update: immediately show feedback
    setMessages((prev) => {
      // Remove the question from pendingQuestions
      const updated = prev.map(msg => {
        if (msg.pendingQuestions) {
          return {
            ...msg,
            pendingQuestions: msg.pendingQuestions.filter(q => q.id !== questionId),
          }
        }
        return msg
      })
      // Add the user's answer as a message
      return [...updated, { role: 'user', content: answer }]
    })

    // Show processing indicator
    setCurrentStep('Processing your answer...')

    // Make the API call
    answerMutation.mutate({ questionId, answer })
  }

  const handleSubmit = (e) => {
    e.preventDefault()
    if (!input.trim() || chatMutation.isPending) return

    const userMessage = input.trim()
    setInput('')
    setCurrentStep('Processing your request...')

    // Build conversation history from CURRENT messages BEFORE adding the new one
    // This ensures we capture previous exchanges, not the message being sent
    const conversationHistory = messages
      .filter((msg, idx) => idx > 0) // Skip the initial welcome message
      .map((msg) => ({
        role: msg.role,
        content: msg.content?.substring(0, 500), // Truncate long messages
        // Include key results for assistant messages
        ...(msg.role === 'assistant' && msg.workflowEvents?.length > 0 && {
          result_summary: msg.workflowEvents
            .filter(e => e.status === 'success' && e.data)
            .slice(-3) // Last 3 successful events
            .map(e => `${e.title}: ${e.description?.substring(0, 100)}`)
            .join('; ')
        }),
      }))

    setMessages((prev) => [...prev, { role: 'user', content: userMessage }])
    chatMutation.mutate({ message: userMessage, conversationHistory })
  }

  const handleNewChat = () => {
    setCurrentPlanId(null)
    setApiCalls([]) // Clear debug data for new chat
    setMessages([
      {
        role: 'assistant',
        content: `Hello ${user?.firstName || user?.username}! I'm Druppie, your AI governance assistant.

I can help you:
• Create applications (just describe what you want!)
• Manage code deployments
• Check compliance and permissions

What would you like to build today?`,
      },
    ])
  }

  const handleSelectPlan = (plan) => {
    setCurrentPlanId(plan.id)

    // Load persisted workflow events and LLM calls from plan.result
    const workflowEvents = plan.result?.workflow_events || []
    const llmCalls = plan.result?.llm_calls || []

    // Load LLM calls into debug panel (mark them as 'llm' type)
    setApiCalls(llmCalls.map(call => ({ type: 'llm', ...call })))

    // Reconstruct messages from plan
    const reconstructedMessages = []

    // Add the original user message
    if (plan.description) {
      reconstructedMessages.push({
        role: 'user',
        content: plan.description,
      })
    }

    // Add a response based on plan result with workflow events
    const resultMessage = plan.result?.response || `Plan "${plan.name}" - Status: ${plan.status}`
    reconstructedMessages.push({
      role: 'assistant',
      content: resultMessage,
      planId: plan.id,
      status: plan.status,
      workflowEvents: workflowEvents, // Include persisted workflow events
    })

    setMessages(reconstructedMessages.length > 0 ? reconstructedMessages : [
      {
        role: 'assistant',
        content: `Continuing conversation: ${plan.name}`,
        planId: plan.id,
      }
    ])
  }

  const suggestions = [
    'Create a todo app with Flask',
    'Build a simple calculator',
    'Make a notes app with React',
    'Create a weather dashboard',
  ]

  return (
    <div className="flex h-[calc(100vh-10rem)] -mx-4 sm:-mx-6 lg:-mx-8">
      {/* Sidebar */}
      <ConversationSidebar
        plans={plans}
        activePlanId={currentPlanId}
        onSelectPlan={handleSelectPlan}
        onNewChat={handleNewChat}
      />

      {/* Main Chat Area */}
      <div className="flex-1 flex flex-col bg-gray-50">
        {/* Header with Debug Button */}
        <div className="flex items-center justify-between px-4 py-2 border-b border-gray-200 bg-white">
          <div className="text-sm text-gray-600">
            {currentPlanId ? (
              <span className="flex items-center gap-2">
                <span className="w-2 h-2 rounded-full bg-green-500"></span>
                Active Conversation
              </span>
            ) : (
              <span>New Conversation</span>
            )}
          </div>
          <button
            onClick={() => setDebugPanelOpen(true)}
            className="flex items-center gap-2 px-3 py-1.5 text-sm text-gray-600 hover:text-gray-800 hover:bg-gray-100 rounded-lg transition-colors"
            title="Open Debug Panel"
          >
            <Bug className="w-4 h-4" />
            Debug
            {apiCalls.length > 0 && (
              <span className="bg-orange-100 text-orange-700 text-xs px-1.5 py-0.5 rounded-full">
                {apiCalls.length}
              </span>
            )}
          </button>
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto p-4 space-y-2">
          {messages.map((message, index) => (
            <Message
              key={index}
              message={message}
              onAnswerQuestion={handleAnswerQuestion}
              isAnsweringQuestion={answerMutation.isPending}
              onApproveTask={handleApproveTask}
              onRejectTask={handleRejectTask}
              isApprovingTask={approveMutation.isPending || rejectMutation.isPending}
            />
          ))}

          {chatMutation.isPending && (
            <TypingIndicator currentStep={currentStep} />
          )}

          <div ref={messagesEndRef} />
        </div>

        {/* Suggestions (show only at start) */}
        {messages.length <= 1 && !currentPlanId && (
          <div className="px-4 pb-4">
            <p className="text-sm text-gray-500 mb-2">Try one of these:</p>
            <div className="flex flex-wrap gap-2">
              {suggestions.map((suggestion, index) => (
                <button
                  key={index}
                  onClick={() => setInput(suggestion)}
                  className="px-3 py-1.5 bg-white hover:bg-gray-100 rounded-full text-sm text-gray-700 transition-colors border border-gray-200 shadow-sm"
                >
                  {suggestion}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Input */}
        <form onSubmit={handleSubmit} className="p-4 border-t border-gray-200 bg-white">
          <div className="flex space-x-3">
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Describe what you want to build..."
              className="flex-1 px-4 py-3 border border-gray-300 rounded-xl focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-all"
              disabled={chatMutation.isPending}
            />
            <button
              type="submit"
              disabled={!input.trim() || chatMutation.isPending}
              className="px-6 py-3 bg-gradient-to-r from-blue-600 to-purple-600 text-white rounded-xl hover:from-blue-700 hover:to-purple-700 disabled:opacity-50 disabled:cursor-not-allowed transition-all shadow-md hover:shadow-lg"
            >
              <Send className="w-5 h-5" />
            </button>
          </div>
        </form>
      </div>

      {/* Debug Panel */}
      <DebugPanel
        isOpen={debugPanelOpen}
        onClose={() => setDebugPanelOpen(false)}
        apiCalls={apiCalls}
      />
    </div>
  )
}

export default Chat
