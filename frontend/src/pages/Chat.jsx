/**
 * Chat Page - Main interface for Druppie governance
 * Shows workflow events and conversation history sidebar
 */

import React, { useState, useRef, useEffect } from 'react'
import { useSearchParams, useNavigate } from 'react-router-dom'
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
  FolderOpen,
} from 'lucide-react'
import { sendChat, getSessions, getPlan, answerQuestion, approveTask, rejectTask, submitHITLResponse, getProject } from '../services/api'
import { useAuth } from '../App'
import {
  initSocket,
  joinPlanRoom,
  joinApprovalsRoom,
  onTaskApproved,
  onTaskRejected,
  onPlanUpdated,
  onWorkflowEvent,
  onHITLQuestion,
  onApprovalRequired,
  onHITLProgress,
  disconnectSocket,
} from '../services/socket'
import { useToast } from '../components/Toast'

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

// Event type categorization for visual distinction
const EVENT_CATEGORIES = {
  agent: ['agent_started', 'agent_completed', 'agent_error', 'agent_failed', 'agent_question'],
  tool: ['tool_call', 'tool_executing', 'tool_completed', 'mcp_tool'],
  llm: ['llm_generating', 'llm_calling', 'llm_call', 'llm_response'],
  workflow: ['workflow_started', 'workflow_completed', 'workflow_failed', 'step_started', 'step_completed'],
  approval: ['approval_required', 'question_pending'],
  result: ['files_created', 'git_pushed', 'build_complete', 'app_running', 'workspace_initialized'],
}

const getEventCategory = (eventType) => {
  for (const [category, types] of Object.entries(EVENT_CATEGORIES)) {
    if (types.some(t => eventType?.includes(t) || eventType === t)) {
      return category
    }
  }
  return 'info'
}

const getCategoryStyles = (category, status) => {
  if (status === 'error') {
    return {
      bg: 'bg-red-50',
      border: 'border-red-200',
      text: 'text-red-800',
      iconBg: 'bg-red-100',
      iconText: 'text-red-600',
      badge: 'bg-red-100 text-red-700',
    }
  }
  const styles = {
    agent: {
      bg: 'bg-purple-50',
      border: 'border-purple-200',
      text: 'text-purple-800',
      iconBg: 'bg-purple-100',
      iconText: 'text-purple-600',
      badge: 'bg-purple-100 text-purple-700',
    },
    tool: {
      bg: 'bg-orange-50',
      border: 'border-orange-200',
      text: 'text-orange-800',
      iconBg: 'bg-orange-100',
      iconText: 'text-orange-600',
      badge: 'bg-orange-100 text-orange-700',
    },
    llm: {
      bg: 'bg-indigo-50',
      border: 'border-indigo-200',
      text: 'text-indigo-800',
      iconBg: 'bg-indigo-100',
      iconText: 'text-indigo-600',
      badge: 'bg-indigo-100 text-indigo-700',
    },
    workflow: {
      bg: 'bg-blue-50',
      border: 'border-blue-200',
      text: 'text-blue-800',
      iconBg: 'bg-blue-100',
      iconText: 'text-blue-600',
      badge: 'bg-blue-100 text-blue-700',
    },
    approval: {
      bg: 'bg-amber-50',
      border: 'border-amber-200',
      text: 'text-amber-800',
      iconBg: 'bg-amber-100',
      iconText: 'text-amber-600',
      badge: 'bg-amber-100 text-amber-700',
    },
    result: {
      bg: 'bg-green-50',
      border: 'border-green-200',
      text: 'text-green-800',
      iconBg: 'bg-green-100',
      iconText: 'text-green-600',
      badge: 'bg-green-100 text-green-700',
    },
    info: {
      bg: 'bg-gray-50',
      border: 'border-gray-200',
      text: 'text-gray-800',
      iconBg: 'bg-gray-100',
      iconText: 'text-gray-600',
      badge: 'bg-gray-100 text-gray-700',
    },
  }
  return styles[category] || styles.info
}

// Enhanced Workflow Event Component with category-based styling
const WorkflowEvent = ({ event, defaultExpanded = false }) => {
  const [isExpanded, setIsExpanded] = useState(defaultExpanded)
  const eventType = event.event_type || event.type || ''
  const category = getEventCategory(eventType)
  const styles = getCategoryStyles(category, event.status)
  const displayTitle = event.title || formatEventTitle({ ...event, event_type: eventType })
  const displayDescription = event.description || getEventDescription({ ...event, event_type: eventType })
  const hasToolArgs = event.data?.args || event.data?.arguments || event.data?.args_preview
  const hasToolResult = event.data?.result || event.data?.output
  const hasExpandableContent = hasToolArgs || hasToolResult || (event.data?.error && event.data.error.length > 50)
  const isToolEvent = category === 'tool'

  const formatArgs = (args) => {
    if (!args) return null
    if (typeof args === 'string') return args.length > 100 ? args.substring(0, 100) + '...' : args
    try {
      const str = JSON.stringify(args, null, 2)
      return str.length > 200 ? str.substring(0, 200) + '...' : str
    } catch {
      return String(args)
    }
  }

  return (
    <div className={`flex items-start gap-2 p-2.5 rounded-lg border ${styles.bg} ${styles.border} ${styles.text} mb-1.5 transition-all`}>
      <div className={`p-1.5 rounded-full ${styles.iconBg} ${styles.iconText} flex-shrink-0`}>
        {getEventIcon(eventType, event.status)}
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className={`text-[10px] uppercase font-semibold px-1.5 py-0.5 rounded ${styles.badge}`}>
            {category}
          </span>
          <span className="font-medium text-sm">{displayTitle}</span>
          {event.data?.agent_id && (
            <span className="text-xs bg-purple-100 text-purple-700 px-1.5 py-0.5 rounded-full font-medium">
              {event.data.agent_id.replace('_agent', '')}
            </span>
          )}
          {event.data?.duration_ms && (
            <span className="text-xs text-gray-500 font-mono">{event.data.duration_ms}ms</span>
          )}
          {event.status === 'success' && <CheckCircle className="w-3.5 h-3.5 text-green-500" />}
          {event.status === 'error' && <XCircle className="w-3.5 h-3.5 text-red-500" />}
        </div>
        {displayDescription && <div className="text-xs opacity-80 mt-1">{displayDescription}</div>}
        {isToolEvent && (event.data?.tool || event.data?.tool_name) && (
          <div className="flex items-center gap-2 mt-1.5">
            <span className="inline-flex items-center gap-1 bg-orange-200 text-orange-800 px-2 py-0.5 rounded text-xs font-mono">
              <Hammer className="w-3 h-3" />
              {event.data.tool || event.data.tool_name}
            </span>
            {hasExpandableContent && (
              <button onClick={() => setIsExpanded(!isExpanded)} className="text-xs text-gray-500 hover:text-gray-700 flex items-center gap-1">
                {isExpanded ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
                {isExpanded ? 'Hide' : 'Show'} details
              </button>
            )}
          </div>
        )}
        {isExpanded && hasExpandableContent && (
          <div className="mt-2 space-y-2">
            {hasToolArgs && (
              <div className="bg-gray-900 rounded p-2 text-xs">
                <div className="text-gray-400 text-[10px] uppercase mb-1">Arguments</div>
                <pre className="text-green-400 font-mono whitespace-pre-wrap overflow-x-auto">
                  {formatArgs(event.data?.args || event.data?.arguments || event.data?.args_preview)}
                </pre>
              </div>
            )}
            {hasToolResult && (
              <div className={`rounded p-2 text-xs ${event.status === 'error' ? 'bg-red-900' : 'bg-gray-900'}`}>
                <div className={`text-[10px] uppercase mb-1 ${event.status === 'error' ? 'text-red-400' : 'text-gray-400'}`}>
                  {event.status === 'error' ? 'Error' : 'Result'}
                </div>
                <pre className={`font-mono whitespace-pre-wrap overflow-x-auto ${event.status === 'error' ? 'text-red-400' : 'text-blue-400'}`}>
                  {formatArgs(event.data?.result || event.data?.output)}
                </pre>
              </div>
            )}
            {event.data?.error && !hasToolResult && (
              <div className="bg-red-900 rounded p-2 text-xs">
                <div className="text-red-400 text-[10px] uppercase mb-1">Error</div>
                <pre className="text-red-300 font-mono whitespace-pre-wrap overflow-x-auto">{event.data.error}</pre>
              </div>
            )}
          </div>
        )}
        {event.data?.tool_calls && event.data.tool_calls.length > 0 && (
          <div className="text-xs mt-1.5 flex flex-wrap gap-1">
            <span className="text-gray-500 mr-1">Tools:</span>
            {event.data.tool_calls.map((tc, i) => (
              <span key={i} className="inline-flex items-center gap-1 bg-orange-100 text-orange-700 px-1.5 py-0.5 rounded font-mono">
                <Hammer className="w-2.5 h-2.5" />
                {typeof tc === 'string' ? tc : tc.name || tc}
              </span>
            ))}
          </div>
        )}
        {event.data?.repo_url && (
          <a href={event.data.repo_url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-xs mt-1.5 text-blue-600 hover:underline font-medium">
            <ExternalLink className="w-3 h-3" />
            View Repository
          </a>
        )}
        {event.data?.url && (
          <a href={event.data.url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-xs mt-1.5 text-green-600 hover:underline font-medium">
            <ExternalLink className="w-3 h-3" />
            Open App
          </a>
        )}
        {event.data?.features && event.data.features.length > 0 && (
          <div className="text-xs mt-1 opacity-70">Features: {event.data.features.join(', ')}</div>
        )}
      </div>
    </div>
  )
}

// Agent name formatting and icons
const AGENT_CONFIG = {
  router: { name: 'Router', icon: Brain, color: 'purple', description: 'Intent analysis' },
  router_agent: { name: 'Router', icon: Brain, color: 'purple', description: 'Intent analysis' },
  planner: { name: 'Planner', icon: Clock, color: 'blue', description: 'Execution planning' },
  planner_agent: { name: 'Planner', icon: Clock, color: 'blue', description: 'Execution planning' },
  developer: { name: 'Developer', icon: FileCode, color: 'green', description: 'Code generation' },
  developer_agent: { name: 'Developer', icon: FileCode, color: 'green', description: 'Code generation' },
  code_generator: { name: 'Code Generator', icon: FileCode, color: 'green', description: 'Code generation' },
  code_generator_agent: { name: 'Code Generator', icon: FileCode, color: 'green', description: 'Code generation' },
  devops: { name: 'DevOps', icon: Hammer, color: 'orange', description: 'Build & deploy' },
  devops_agent: { name: 'DevOps', icon: Hammer, color: 'orange', description: 'Build & deploy' },
  git_agent: { name: 'Git', icon: GitBranch, color: 'gray', description: 'Version control' },
  reviewer: { name: 'Reviewer', icon: CheckCircle, color: 'teal', description: 'Code review' },
  reviewer_agent: { name: 'Reviewer', icon: CheckCircle, color: 'teal', description: 'Code review' },
}

const getAgentConfig = (agentId) => {
  return AGENT_CONFIG[agentId] || {
    name: agentId.replace('_agent', '').replace(/_/g, ' '),
    icon: Bot,
    color: 'gray',
    description: 'AI Agent',
  }
}

const getAgentColorClasses = (color) => {
  const colors = {
    purple: 'bg-purple-100 text-purple-700 border-purple-200',
    blue: 'bg-blue-100 text-blue-700 border-blue-200',
    green: 'bg-green-100 text-green-700 border-green-200',
    orange: 'bg-orange-100 text-orange-700 border-orange-200',
    gray: 'bg-gray-100 text-gray-700 border-gray-200',
    teal: 'bg-teal-100 text-teal-700 border-teal-200',
  }
  return colors[color] || colors.gray
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
const WorkflowTimeline = ({ events, isExpanded, onToggle, isWorking = false }) => {
  if (!events || events.length === 0) return null

  // Process events to update statuses
  const processedEvents = processWorkflowEvents(events)

  // Count LLM calls, tools, and agents
  const llmCalls = processedEvents.filter(e => e.event_type === 'llm_response' || e.event_type === 'llm_call').length
  const toolCalls = processedEvents.filter(e => e.event_type?.includes('tool_') || e.event_type === 'mcp_tool').length
  const agentsRun = [...new Set(processedEvents.filter(e => e.data?.agent_id).map(e => e.data.agent_id))].length
  const hasErrors = processedEvents.some(e => e.status === 'error')

  // Get the current active agent (from the last agent_started event without a corresponding completed)
  const activeAgentEvent = processedEvents.filter(e => e.event_type === 'agent_started').pop()
  const activeAgent = activeAgentEvent?.data?.agent_id

  return (
    <div className={`mt-3 border-t pt-3 ${isWorking ? 'border-blue-200 bg-blue-50/50 -mx-4 px-4 py-3 rounded-lg' : 'border-gray-100'}`}>
      {/* Working indicator header when active */}
      {isWorking && activeAgent && (
        <div className="flex items-center gap-3 mb-3 pb-3 border-b border-blue-200">
          <div className="relative">
            <div className="w-10 h-10 rounded-full bg-gradient-to-br from-blue-500 to-purple-600 flex items-center justify-center">
              <Loader2 className="w-5 h-5 text-white animate-spin" />
            </div>
            <span className="absolute -bottom-1 -right-1 w-4 h-4 bg-green-500 rounded-full border-2 border-white animate-pulse" />
          </div>
          <div>
            <div className="text-sm font-semibold text-blue-900 flex items-center gap-2">
              <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${getAgentColorClasses(getAgentConfig(activeAgent).color)}`}>
                {getAgentConfig(activeAgent).name}
              </span>
              is working...
            </div>
            <div className="text-xs text-blue-600">{getAgentConfig(activeAgent).description}</div>
          </div>
        </div>
      )}

      <button
        onClick={onToggle}
        className={`flex items-center gap-2 text-sm mb-2 w-full focus:outline-none focus:ring-2 focus:ring-blue-500 rounded ${
          isWorking ? 'text-blue-700 hover:text-blue-900' : 'text-gray-600 hover:text-gray-800'
        }`}
        aria-expanded={isExpanded}
        aria-label={isExpanded ? 'Collapse execution log' : 'Expand execution log'}
      >
        {isExpanded ? <ChevronDown className="w-4 h-4" aria-hidden="true" /> : <ChevronRight className="w-4 h-4" aria-hidden="true" />}
        <span className="font-medium">Execution Log</span>
        <div className="flex items-center gap-2 ml-auto flex-wrap">
          {agentsRun > 0 && (
            <span className="text-xs bg-purple-100 text-purple-700 px-2 py-0.5 rounded-full flex items-center gap-1">
              <Bot className="w-3 h-3" />
              {agentsRun}
            </span>
          )}
          {llmCalls > 0 && (
            <span className="text-xs bg-indigo-100 text-indigo-700 px-2 py-0.5 rounded-full flex items-center gap-1">
              <Brain className="w-3 h-3" />
              {llmCalls}
            </span>
          )}
          {toolCalls > 0 && (
            <span className="text-xs bg-orange-100 text-orange-700 px-2 py-0.5 rounded-full flex items-center gap-1">
              <Hammer className="w-3 h-3" />
              {toolCalls}
            </span>
          )}
          {hasErrors && (
            <span className="text-xs bg-red-100 text-red-700 px-2 py-0.5 rounded-full flex items-center gap-1">
              <XCircle className="w-3 h-3" />
              errors
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
      </div>
    </div>
  )
}

// Inline Approval Card Component - allows approve/reject directly in chat
const ApprovalCard = ({ approval, onApprove, onReject, isProcessing, currentUserId }) => {
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
  const approvedByIds = approval.approved_by_ids || []
  const requiredRoles = approval.required_roles || [approval.required_role]
  const remainingRoles = requiredRoles.filter(r => !approvedByRoles.includes(r))
  const progressPercent = Math.round((currentApprovals / requiredApprovals) * 100)

  // Check if current user has already approved
  const userHasApproved = currentUserId && approvedByIds.includes(currentUserId)

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

          {/* Action buttons or "You have approved" message */}
          {userHasApproved ? (
            <div className="flex items-center gap-2 p-3 bg-green-50 rounded-lg border border-green-200">
              <CheckCircle className="w-5 h-5 text-green-600" />
              <span className="text-sm text-green-800 font-medium">
                You have approved this task. Waiting for {requiredApprovals - currentApprovals} more approval(s) from other roles.
              </span>
            </div>
          ) : (
            <div className="flex items-center gap-2" role="group" aria-label="Approval actions">
              <button
                onClick={() => onApprove(approval.task_id)}
                disabled={isProcessing || showRejectInput}
                className="flex items-center gap-2 px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors focus:outline-none focus:ring-2 focus:ring-green-500 focus:ring-offset-2"
                aria-label={isMultiApproval ? `Add approval ${currentApprovals + 1} of ${requiredApprovals}` : 'Approve task'}
              >
                {isProcessing ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" aria-hidden="true" />
                    Processing...
                  </>
                ) : (
                  <>
                    <CheckCircle className="w-4 h-4" aria-hidden="true" />
                    {isMultiApproval ? `Add Approval (${currentApprovals + 1}/${requiredApprovals})` : 'Approve'}
                  </>
                )}
              </button>
              <button
                onClick={handleReject}
                disabled={isProcessing}
                className={`flex items-center gap-2 px-4 py-2 rounded-lg transition-colors focus:outline-none focus:ring-2 focus:ring-red-500 focus:ring-offset-2 ${
                  showRejectInput
                    ? 'bg-red-600 text-white hover:bg-red-700'
                    : 'bg-white text-red-600 border border-red-200 hover:bg-red-50'
                } disabled:opacity-50 disabled:cursor-not-allowed`}
                aria-label={showRejectInput ? 'Confirm task rejection' : 'Reject task'}
              >
                <XCircle className="w-4 h-4" aria-hidden="true" />
                {showRejectInput ? 'Confirm Reject' : 'Reject'}
              </button>
              {showRejectInput && (
                <button
                  onClick={() => {
                    setShowRejectInput(false)
                    setRejectReason('')
                  }}
                  className="px-3 py-2 text-gray-600 hover:text-gray-800 text-sm focus:outline-none focus:ring-2 focus:ring-gray-500 rounded"
                  aria-label="Cancel rejection"
                >
                  Cancel
                </button>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// Agent Attribution Header - Shows prominently which agents contributed to the response
const AgentAttributionHeader = ({ events }) => {
  if (!events || events.length === 0) return null

  // Extract unique agents from events
  const agents = [...new Set(events
    .filter(e => e.data?.agent_id)
    .map(e => e.data.agent_id)
  )]

  // Also check for specific event types that indicate agent work
  const hasRouter = events.some(e =>
    e.event_type === 'router_analyzing' ||
    e.event_type === 'intent_detected' ||
    e.data?.agent_id?.includes('router')
  )
  const hasPlanner = events.some(e =>
    e.event_type === 'plan_ready' ||
    e.event_type === 'plan_creating' ||
    e.data?.agent_id?.includes('planner')
  )
  const hasCodeGen = events.some(e =>
    e.event_type === 'llm_generating' ||
    e.event_type === 'files_created' ||
    e.data?.agent_id?.includes('developer') ||
    e.data?.agent_id?.includes('code_generator')
  )

  // Add inferred agents if not already present
  if (hasRouter && !agents.some(a => a.includes('router'))) {
    agents.unshift('router_agent')
  }
  if (hasPlanner && !agents.some(a => a.includes('planner'))) {
    agents.push('planner_agent')
  }
  if (hasCodeGen && !agents.some(a => a.includes('developer') || a.includes('code'))) {
    agents.push('developer_agent')
  }

  if (agents.length === 0) return null

  return (
    <div className="flex items-center gap-2 mb-2 flex-wrap">
      <span className="text-xs text-gray-500 font-medium">Powered by:</span>
      {agents.slice(0, 4).map(agentId => {
        const config = getAgentConfig(agentId)
        const AgentIcon = config.icon
        const colorClasses = getAgentColorClasses(config.color)

        return (
          <span
            key={agentId}
            className={`inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium rounded-full border ${colorClasses}`}
            title={config.description}
          >
            <AgentIcon className="w-3.5 h-3.5" />
            {config.name}
          </span>
        )
      })}
      {agents.length > 4 && (
        <span className="text-xs text-gray-400">+{agents.length - 4} more</span>
      )}
    </div>
  )
}

const Message = ({ message, onAnswerQuestion, isAnsweringQuestion, onApproveTask, onRejectTask, isApprovingTask, currentUserId }) => {
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
            {/* Agent attribution header - prominent display of which agents contributed */}
            {!isUser && message.workflowEvents && message.workflowEvents.length > 0 && (
              <AgentAttributionHeader events={message.workflowEvents} />
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
                  currentUserId={currentUserId}
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

// Format event title for display
const formatEventTitle = (event) => {
  const type = event.event_type || event.type || ''
  const title = event.title || ''
  const data = event.data || {}

  // Create descriptive titles based on event type
  if (type === 'router_analyzing' || type.includes('intent')) {
    return 'Analyzing your request'
  }
  if (type === 'plan_creating' || type === 'plan_ready') {
    return 'Creating execution plan'
  }
  if (type === 'agent_started' && data.agent_id) {
    const agentName = data.agent_id.replace('_agent', '').replace(/_/g, ' ')
    return `Starting ${agentName} agent`
  }
  if (type === 'agent_completed' && data.agent_id) {
    const agentName = data.agent_id.replace('_agent', '').replace(/_/g, ' ')
    return `${agentName} agent completed`
  }
  if (type === 'agent_error' || type === 'agent_failed') {
    const agentName = (data.agent_id || 'agent').replace('_agent', '').replace(/_/g, ' ')
    return `${agentName} agent error`
  }
  if (type === 'llm_generating' || type === 'llm_calling' || type === 'llm_call') {
    const agentName = data.agent_id ? data.agent_id.replace('_agent', '').replace(/_/g, ' ') : ''
    const iteration = data.iteration !== undefined ? ` (iteration ${data.iteration + 1})` : ''
    return agentName ? `${agentName} calling LLM${iteration}` : `Calling LLM${iteration}`
  }
  if (type === 'llm_response') {
    const duration = data.duration_ms ? ` (${data.duration_ms}ms)` : ''
    return `LLM response received${duration}`
  }
  if (type === 'tool_call') {
    const toolName = data.tool_name || data.tool || 'tool'
    const agentName = data.agent_id ? data.agent_id.replace('_agent', '').replace(/_/g, ' ') : ''
    return agentName ? `${agentName}: calling ${toolName}` : `Calling ${toolName}`
  }
  if (type === 'tool_executing' && (data.tool || data.tool_name)) {
    return `Running ${data.tool || data.tool_name}`
  }
  if (type === 'tool_completed') {
    return `Tool completed: ${data.tool_name || data.tool || 'tool'}`
  }
  if (type === 'files_created') {
    const count = data.file_count || data.files?.length || 0
    return count > 0 ? `Created ${count} files` : 'Created files'
  }
  if (type === 'git_pushed' || title.toLowerCase().includes('git')) {
    return 'Pushed to Git repository'
  }
  if (type === 'build_complete' || title.toLowerCase().includes('build')) {
    return 'Build completed'
  }
  if (type === 'app_running') {
    return 'Application started'
  }
  if (type === 'workspace_initialized') {
    const branch = data.branch ? ` on branch ${data.branch}` : ''
    return `Workspace initialized${branch}`
  }
  if (type === 'approval_required') {
    const tool = data.tool || data.tool_name || 'action'
    return `Approval required for ${tool}`
  }
  if (type === 'step_started') {
    return data.step_type ? `Starting ${data.step_type}` : 'Starting step'
  }
  if (type === 'step_completed') {
    return 'Step completed'
  }

  // Fall back to the title or generate from type
  if (title) return title
  if (type) {
    // Convert snake_case to Title Case
    return type.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
  }
  return 'Processing'
}

// Get detailed description for an event
const getEventDescription = (event) => {
  const type = event.event_type || event.type || ''
  const data = event.data || {}

  if (type === 'agent_started') {
    return data.prompt_preview ? `Processing: "${data.prompt_preview}..."` : 'Agent started processing'
  }
  if (type === 'agent_completed') {
    const iterations = data.iterations ? `in ${data.iterations} iteration(s)` : ''
    return `Agent completed successfully ${iterations}`.trim()
  }
  if (type === 'agent_error') {
    return data.error || 'An error occurred'
  }
  if (type === 'llm_call') {
    const duration = data.duration_ms ? `Duration: ${data.duration_ms}ms` : ''
    const hasTools = data.has_tool_calls ? 'Tool calls made' : 'No tool calls'
    return `${hasTools}. ${duration}`.trim()
  }
  if (type === 'tool_call') {
    const args = data.args_preview || ''
    return args ? `Arguments: ${args}` : 'Tool called'
  }
  if (type === 'workspace_initialized') {
    return data.workspace_id ? `Workspace: ${data.workspace_id.substring(0, 8)}...` : 'Workspace ready'
  }
  if (type === 'approval_required') {
    const roles = data.required_roles?.join(', ') || 'authorized user'
    return `Requires approval from: ${roles}`
  }

  return event.description || ''
}

// Typing indicator with real-time workflow steps and active agent display
const TypingIndicator = ({ currentStep, liveEvents = [] }) => {
  // Process live events to show completed and current steps
  const processedEvents = liveEvents.map((event, index) => {
    const isLast = index === liveEvents.length - 1
    const category = getEventCategory(event.event_type || event.type || '')
    return {
      ...event,
      displayTitle: formatEventTitle(event),
      isComplete: !isLast || event.status === 'success',
      isCurrent: isLast && event.status !== 'success',
      category,
    }
  })

  // Deduplicate consecutive similar events
  const uniqueEvents = processedEvents.reduce((acc, event) => {
    const lastEvent = acc[acc.length - 1]
    if (!lastEvent || lastEvent.displayTitle !== event.displayTitle) {
      acc.push(event)
    } else if (event.isComplete && !lastEvent.isComplete) {
      acc[acc.length - 1] = { ...lastEvent, isComplete: true, isCurrent: false }
    }
    return acc
  }, [])

  // Keep last 8 events for display
  const displayEvents = uniqueEvents.slice(-8)

  // Find the current active agent
  const activeAgentEvent = liveEvents.filter(e => e.event_type === 'agent_started' || e.data?.agent_id).pop()
  const activeAgent = activeAgentEvent?.data?.agent_id
  const agentConfig = activeAgent ? getAgentConfig(activeAgent) : null
  const AgentIcon = agentConfig?.icon || Bot

  // Count stats
  const toolCalls = liveEvents.filter(e => e.event_type?.includes('tool_')).length
  const llmCalls = liveEvents.filter(e => e.event_type?.includes('llm_')).length

  return (
    <div className="flex justify-start mb-4">
      <div className="bg-white border-2 border-blue-200 rounded-2xl rounded-bl-none px-5 py-4 shadow-lg min-w-[380px] max-w-[480px]">
        {/* Prominent Working Header */}
        <div className="flex items-center gap-4 mb-4 pb-4 border-b border-gray-100">
          <div className="relative">
            <div className={`w-12 h-12 rounded-full flex items-center justify-center ${
              agentConfig ? getAgentColorClasses(agentConfig.color).replace('border-', 'bg-').split(' ')[0] : 'bg-gradient-to-br from-blue-500 to-purple-600'
            }`}>
              {agentConfig ? (
                <AgentIcon className="w-6 h-6" />
              ) : (
                <Loader2 className="w-6 h-6 text-white animate-spin" />
              )}
            </div>
            <span className="absolute -bottom-1 -right-1 w-4 h-4 bg-green-500 rounded-full border-2 border-white flex items-center justify-center">
              <Loader2 className="w-2.5 h-2.5 text-white animate-spin" />
            </span>
          </div>
          <div className="flex-1">
            <div className="flex items-center gap-2">
              {agentConfig && (
                <span className={`px-2.5 py-1 rounded-full text-xs font-semibold ${getAgentColorClasses(agentConfig.color)}`}>
                  {agentConfig.name}
                </span>
              )}
              <span className="text-sm font-semibold text-gray-800">
                {agentConfig ? 'is working...' : 'Processing...'}
              </span>
            </div>
            <div className="text-xs text-gray-500 mt-0.5">
              {agentConfig?.description || currentStep || 'Analyzing your request'}
            </div>
            {/* Mini stats */}
            {(toolCalls > 0 || llmCalls > 0) && (
              <div className="flex gap-2 mt-2">
                {llmCalls > 0 && (
                  <span className="text-[10px] bg-indigo-100 text-indigo-700 px-1.5 py-0.5 rounded flex items-center gap-1">
                    <Brain className="w-2.5 h-2.5" /> {llmCalls} LLM
                  </span>
                )}
                {toolCalls > 0 && (
                  <span className="text-[10px] bg-orange-100 text-orange-700 px-1.5 py-0.5 rounded flex items-center gap-1">
                    <Hammer className="w-2.5 h-2.5" /> {toolCalls} tools
                  </span>
                )}
              </div>
            )}
          </div>
        </div>

        {/* Live progress steps with category colors */}
        {displayEvents.length > 0 ? (
          <div className="space-y-2 pl-3 border-l-2 border-blue-200 ml-1 max-h-64 overflow-y-auto">
            {displayEvents.map((event, idx) => {
              const catStyles = getCategoryStyles(event.category, event.status)
              return (
                <div
                  key={idx}
                  className={`flex items-center gap-2 text-sm transition-all duration-300 ${
                    event.isCurrent ? 'text-blue-700 font-medium' : event.isComplete ? 'text-gray-600' : 'text-gray-400'
                  }`}
                >
                  {event.isCurrent ? (
                    <Loader2 className="w-4 h-4 animate-spin text-blue-500 flex-shrink-0" />
                  ) : event.isComplete ? (
                    <CheckCircle className="w-4 h-4 text-green-500 flex-shrink-0" />
                  ) : (
                    <div className="w-4 h-4 rounded-full border-2 border-gray-300 flex-shrink-0" />
                  )}
                  <span className={`text-[10px] uppercase font-semibold px-1 py-0.5 rounded ${catStyles.badge}`}>
                    {event.category}
                  </span>
                  <span className="truncate flex-1">{event.displayTitle}</span>
                </div>
              )
            })}
          </div>
        ) : (
          /* Fallback: Generic progress steps when no live events */
          <div className="flex items-center justify-between px-2 pt-2">
            {[
              { id: 'analyzing', label: 'Analyzing', icon: Brain, color: 'purple' },
              { id: 'planning', label: 'Planning', icon: Clock, color: 'blue' },
              { id: 'executing', label: 'Executing', icon: Zap, color: 'green' },
            ].map((step, idx) => {
              const StepIcon = step.icon
              const stepLower = (currentStep || '').toLowerCase()
              let isActive = false
              let isComplete = false

              if (stepLower.includes('analyz') || stepLower.includes('router')) {
                isActive = idx === 0
              } else if (stepLower.includes('plan')) {
                isComplete = idx === 0
                isActive = idx === 1
              } else if (stepLower.includes('execut') || stepLower.includes('generat') || stepLower.includes('develop')) {
                isComplete = idx < 2
                isActive = idx === 2
              }

              return (
                <div key={step.id} className="flex items-center">
                  <div className="flex flex-col items-center">
                    <div
                      className={`w-10 h-10 rounded-full flex items-center justify-center transition-all ${
                        isActive
                          ? `bg-${step.color}-500 text-white shadow-lg shadow-${step.color}-200`
                          : isComplete
                          ? 'bg-green-500 text-white'
                          : 'bg-gray-200 text-gray-400'
                      }`}
                    >
                      {isComplete ? (
                        <CheckCircle className="w-5 h-5" />
                      ) : isActive ? (
                        <Loader2 className="w-5 h-5 animate-spin" />
                      ) : (
                        <StepIcon className="w-5 h-5" />
                      )}
                    </div>
                    <span className={`text-xs mt-1.5 font-medium ${isActive ? `text-${step.color}-600` : isComplete ? 'text-green-600' : 'text-gray-400'}`}>
                      {step.label}
                    </span>
                  </div>
                  {idx < 2 && (
                    <div className={`w-10 h-0.5 mx-2 rounded ${isComplete ? 'bg-green-500' : 'bg-gray-200'}`} />
                  )}
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}

// Conversation History Sidebar Item
const ConversationItem = ({ session, isActive, onClick, onDebug }) => {
  const getStatusColor = (status) => {
    switch (status) {
      case 'completed':
        return 'bg-green-500'
      case 'active':
      case 'running':
        return 'bg-blue-500'
      case 'paused':
      case 'pending_approval':
        return 'bg-yellow-500'
      case 'failed':
        return 'bg-red-500'
      default:
        return 'bg-gray-400'
    }
  }

  // Use preview from new API format, or fall back to name for legacy format
  const preview = session.preview || session.name?.replace(/^Chat:\s*/i, '').slice(0, 50) || 'No message'
  const date = session.created_at ? new Date(session.created_at).toLocaleDateString() : ''

  return (
    <div
      className={`group w-full text-left p-3 rounded-lg transition-all ${
        isActive
          ? 'bg-blue-50 border border-blue-200'
          : 'hover:bg-gray-50 border border-transparent'
      }`}
    >
      <button onClick={onClick} className="w-full text-left">
        <div className="flex items-start gap-2">
          <MessageSquare className={`w-4 h-4 mt-0.5 flex-shrink-0 ${isActive ? 'text-blue-600' : 'text-gray-400'}`} />
          <div className="flex-1 min-w-0">
            <div className={`text-sm font-medium truncate ${isActive ? 'text-blue-900' : 'text-gray-800'}`}>
              {preview.length > 40 ? `${preview.slice(0, 40)}...` : preview}
            </div>
            <div className="flex items-center gap-2 mt-1">
              <span className={`w-2 h-2 rounded-full ${getStatusColor(session.status)}`} />
              <span className="text-xs text-gray-500">{date}</span>
              {session.project_name && (
                <span className="text-xs bg-purple-100 text-purple-700 px-1.5 py-0.5 rounded truncate max-w-[80px]">
                  {session.project_name}
                </span>
              )}
            </div>
          </div>
        </div>
      </button>
      {/* Debug link - visible on hover */}
      <div className="flex justify-end mt-1 opacity-0 group-hover:opacity-100 transition-opacity">
        <button
          onClick={(e) => {
            e.stopPropagation()
            onDebug(session.id)
          }}
          className="text-xs text-gray-500 hover:text-orange-600 flex items-center gap-1 focus:outline-none focus:ring-2 focus:ring-orange-500 rounded"
          aria-label="View debug trace for this session"
        >
          <Bug className="w-3 h-3" aria-hidden="true" />
          Debug
        </button>
      </div>
    </div>
  )
}

// Conversation History Sidebar
const ConversationSidebar = ({ sessions, activeSessionId, onSelectSession, onNewChat, onDebugSession, isCollapsed, onToggleCollapse }) => {
  // Extract sessions array from paginated response or use directly if already an array
  const sessionList = Array.isArray(sessions) ? sessions : (sessions?.sessions || [])
  const totalSessions = Array.isArray(sessions) ? sessions.length : (sessions?.total || 0)

  if (isCollapsed) {
    return (
      <div className="w-12 bg-white border-r border-gray-200 flex flex-col h-full">
        {/* Collapsed header with expand button */}
        <div className="p-2 border-b border-gray-200">
          <button
            onClick={onToggleCollapse}
            className="w-8 h-8 flex items-center justify-center bg-gray-100 hover:bg-gray-200 rounded-lg transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500"
            aria-label="Expand sidebar"
            aria-expanded="false"
          >
            <ChevronRight className="w-4 h-4 text-gray-600" aria-hidden="true" />
          </button>
        </div>
        {/* Collapsed new chat button */}
        <div className="p-2">
          <button
            onClick={onNewChat}
            className="w-8 h-8 flex items-center justify-center bg-gradient-to-r from-blue-600 to-purple-600 text-white rounded-lg hover:from-blue-700 hover:to-purple-700 transition-all shadow-md focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2"
            aria-label="Start new chat"
          >
            <Plus className="w-4 h-4" aria-hidden="true" />
          </button>
        </div>
        {/* Collapsed session indicators */}
        <div className="flex-1 overflow-y-auto p-2 space-y-2">
          {sessionList.slice(0, 10).map((session) => (
            <button
              key={session.id}
              onClick={() => onSelectSession(session)}
              className={`w-8 h-8 flex items-center justify-center rounded-lg transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500 ${
                session.id === activeSessionId
                  ? 'bg-blue-100 border border-blue-300'
                  : 'bg-gray-50 hover:bg-gray-100'
              }`}
              aria-label={`Select session: ${session.preview || 'Session'}`}
              aria-current={session.id === activeSessionId ? 'true' : undefined}
            >
              <MessageSquare className={`w-4 h-4 ${session.id === activeSessionId ? 'text-blue-600' : 'text-gray-400'}`} aria-hidden="true" />
            </button>
          ))}
        </div>
      </div>
    )
  }

  return (
    <div className="w-72 bg-white border-r border-gray-200 flex flex-col h-full">
      {/* Header with collapse button */}
      <div className="p-4 border-b border-gray-200">
        <div className="flex items-center gap-2 mb-3">
          <button
            onClick={onToggleCollapse}
            className="p-1.5 hover:bg-gray-100 rounded-lg transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500"
            aria-label="Collapse sidebar"
            aria-expanded="true"
          >
            <ChevronDown className="w-4 h-4 text-gray-500 rotate-90" aria-hidden="true" />
          </button>
          <span className="text-sm font-medium text-gray-700">Session History</span>
          {totalSessions > 0 && (
            <span className="text-xs bg-gray-100 text-gray-600 px-2 py-0.5 rounded-full ml-auto">
              {totalSessions}
            </span>
          )}
        </div>
        <button
          onClick={onNewChat}
          className="w-full flex items-center justify-center gap-2 px-4 py-2.5 bg-gradient-to-r from-blue-600 to-purple-600 text-white rounded-lg hover:from-blue-700 hover:to-purple-700 transition-all shadow-md focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2"
        >
          <Plus className="w-4 h-4" aria-hidden="true" />
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
          {sessionList.length > 0 ? (
            sessionList.map((session) => (
              <ConversationItem
                key={session.id}
                session={session}
                isActive={session.id === activeSessionId}
                onClick={() => onSelectSession(session)}
                onDebug={onDebugSession}
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

// Enhanced Debug Panel - Shows agents, workflows, MCP tools, and detailed execution info
const DebugPanel = ({ isOpen, onClose, apiCalls, workflowEvents, llmCalls: llmCallsProp, workspaceInfo }) => {
  const [copiedIndex, setCopiedIndex] = useState(null)
  const [expandedItems, setExpandedItems] = useState({})
  const [allCopied, setAllCopied] = useState(false)
  const [activeTab, setActiveTab] = useState('overview')

  const copyToClipboard = (text, index) => {
    navigator.clipboard.writeText(text)
    setCopiedIndex(index)
    setTimeout(() => setCopiedIndex(null), 2000)
  }

  const copyAllToClipboard = () => {
    const fullData = JSON.stringify({ apiCalls, workflowEvents, llmCalls: llmCallsProp, workspaceInfo }, null, 2)
    navigator.clipboard.writeText(fullData)
    setAllCopied(true)
    setTimeout(() => setAllCopied(false), 2000)
  }

  const toggleExpand = (index) => {
    setExpandedItems(prev => ({ ...prev, [index]: !prev[index] }))
  }

  if (!isOpen) return null

  // Process data for different views
  // Use provided llmCalls prop if available, otherwise fall back to filtering from apiCalls
  const llmCalls = llmCallsProp?.length > 0 ? llmCallsProp : (apiCalls?.filter(c => c.type === 'llm') || [])
  const httpCalls = apiCalls?.filter(c => c.type === 'api') || []
  const events = workflowEvents || []

  // Extract agents from events and LLM calls
  const agentExecutions = []
  const agentMap = new Map()

  // Helper to get event type (supports both type and event_type)
  const getEventType = (event) => event.event_type || event.type || ''

  events.forEach(event => {
    const eventType = getEventType(event)
    if (eventType === 'agent_started' || event.data?.agent_id) {
      const agentId = event.data?.agent_id || event.agent_id
      if (agentId && !agentMap.has(agentId)) {
        agentMap.set(agentId, {
          id: agentId,
          startTime: event.timestamp,
          events: [],
          toolCalls: [],
          llmCalls: [],
          status: 'running'
        })
      }
      if (agentId && agentMap.has(agentId)) {
        agentMap.get(agentId).events.push(event)
      }
    }
    if (eventType === 'agent_completed') {
      const agentId = event.data?.agent_id
      if (agentId && agentMap.has(agentId)) {
        agentMap.get(agentId).status = 'completed'
        agentMap.get(agentId).endTime = event.timestamp
      }
    }
    if (eventType === 'agent_error' || eventType === 'agent_failed') {
      const agentId = event.data?.agent_id
      if (agentId && agentMap.has(agentId)) {
        agentMap.get(agentId).status = 'error'
        agentMap.get(agentId).error = event.data?.error
      }
    }
  })

  // Add LLM calls to agents
  llmCalls.forEach(call => {
    if (call.agent_id && agentMap.has(call.agent_id)) {
      agentMap.get(call.agent_id).llmCalls.push(call)
    }
  })

  const agents = Array.from(agentMap.values())

  // Extract MCP tool calls from events
  const toolCalls = events.filter(e => {
    const type = getEventType(e)
    return type === 'tool_call' ||
      type === 'tool_executing' ||
      type === 'tool_completed' ||
      type === 'mcp_tool' ||
      e.data?.tool_name ||
      e.data?.tool
  }).map(e => ({
    name: e.data?.tool_name || e.data?.tool || e.title,
    args: e.data?.args_preview || e.data?.arguments,
    agent: e.data?.agent_id,
    timestamp: e.timestamp,
    status: e.status || 'completed',
    result: e.data?.result
  }))

  // Tab definitions
  const tabs = [
    { id: 'overview', label: 'Overview', icon: Zap },
    { id: 'agents', label: `Agents (${agents.length})`, icon: Bot },
    { id: 'tools', label: `Tools (${toolCalls.length})`, icon: Hammer },
    { id: 'events', label: `Events (${events.length})`, icon: Clock },
    { id: 'llm', label: `LLM (${llmCalls.length})`, icon: Brain },
  ]

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="bg-white rounded-xl shadow-2xl w-[95vw] max-w-6xl max-h-[90vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-orange-100 rounded-lg">
              <Bug className="w-5 h-5 text-orange-600" />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-gray-900">Execution Debug Panel</h2>
              <p className="text-sm text-gray-500">
                {agents.length} agents, {toolCalls.length} tool calls, {llmCalls.length} LLM calls
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={copyAllToClipboard}
              className="flex items-center gap-1 px-3 py-1.5 text-xs bg-blue-100 text-blue-700 hover:bg-blue-200 rounded-lg transition-colors"
            >
              {allCopied ? <><Check className="w-3 h-3" /> Copied!</> : <><Copy className="w-3 h-3" /> Export All</>}
            </button>
            <button
              onClick={onClose}
              className="p-2 hover:bg-gray-100 rounded-lg transition-colors ml-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
              aria-label="Close debug panel"
            >
              <X className="w-5 h-5 text-gray-500" aria-hidden="true" />
            </button>
          </div>
        </div>

        {/* Tabs */}
        <div className="flex border-b border-gray-200 px-4">
          {tabs.map(tab => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`flex items-center gap-2 px-4 py-3 text-sm font-medium border-b-2 transition-colors ${
                activeTab === tab.id
                  ? 'border-blue-500 text-blue-600'
                  : 'border-transparent text-gray-500 hover:text-gray-700'
              }`}
            >
              <tab.icon className="w-4 h-4" />
              {tab.label}
            </button>
          ))}
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-4">
          {/* Overview Tab */}
          {activeTab === 'overview' && (
            <div className="space-y-4">
              {/* Workspace Info */}
              {workspaceInfo && (
                <div className="bg-gradient-to-r from-blue-50 to-purple-50 rounded-lg border border-blue-200 p-4">
                  <h3 className="font-semibold text-gray-900 mb-3 flex items-center gap-2">
                    <GitBranch className="w-5 h-5 text-blue-600" />
                    Workspace Info
                  </h3>
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                    {workspaceInfo.workspace_id && (
                      <div>
                        <div className="text-xs text-gray-500 uppercase">Workspace ID</div>
                        <div className="font-mono text-sm">{workspaceInfo.workspace_id?.substring(0, 8)}...</div>
                      </div>
                    )}
                    {workspaceInfo.project_id && (
                      <div>
                        <div className="text-xs text-gray-500 uppercase">Project ID</div>
                        <div className="font-mono text-sm">{workspaceInfo.project_id?.substring(0, 8)}...</div>
                      </div>
                    )}
                    {workspaceInfo.branch && (
                      <div>
                        <div className="text-xs text-gray-500 uppercase">Branch</div>
                        <div className="font-mono text-sm flex items-center gap-1">
                          <GitBranch className="w-3 h-3" />
                          {workspaceInfo.branch}
                        </div>
                      </div>
                    )}
                    {workspaceInfo.workspace_path && (
                      <div>
                        <div className="text-xs text-gray-500 uppercase">Path</div>
                        <div className="font-mono text-sm truncate">{workspaceInfo.workspace_path}</div>
                      </div>
                    )}
                  </div>
                </div>
              )}

              {/* Stats Cards */}
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <div className="bg-purple-50 rounded-lg p-4 border border-purple-200">
                  <div className="flex items-center gap-2 mb-2">
                    <Bot className="w-5 h-5 text-purple-600" />
                    <span className="text-sm font-medium text-purple-900">Agents</span>
                  </div>
                  <div className="text-2xl font-bold text-purple-700">{agents.length}</div>
                  <div className="text-xs text-purple-600 mt-1">
                    {agents.filter(a => a.status === 'completed').length} completed
                  </div>
                </div>
                <div className="bg-orange-50 rounded-lg p-4 border border-orange-200">
                  <div className="flex items-center gap-2 mb-2">
                    <Hammer className="w-5 h-5 text-orange-600" />
                    <span className="text-sm font-medium text-orange-900">Tool Calls</span>
                  </div>
                  <div className="text-2xl font-bold text-orange-700">{toolCalls.length}</div>
                  <div className="text-xs text-orange-600 mt-1">MCP operations</div>
                </div>
                <div className="bg-blue-50 rounded-lg p-4 border border-blue-200">
                  <div className="flex items-center gap-2 mb-2">
                    <Brain className="w-5 h-5 text-blue-600" />
                    <span className="text-sm font-medium text-blue-900">LLM Calls</span>
                  </div>
                  <div className="text-2xl font-bold text-blue-700">{llmCalls.length}</div>
                  <div className="text-xs text-blue-600 mt-1">
                    {llmCalls.reduce((acc, c) => acc + (c.usage?.total_tokens || 0), 0)} tokens
                  </div>
                </div>
                <div className="bg-green-50 rounded-lg p-4 border border-green-200">
                  <div className="flex items-center gap-2 mb-2">
                    <Clock className="w-5 h-5 text-green-600" />
                    <span className="text-sm font-medium text-green-900">Events</span>
                  </div>
                  <div className="text-2xl font-bold text-green-700">{events.length}</div>
                  <div className="text-xs text-green-600 mt-1">workflow events</div>
                </div>
              </div>

              {/* Execution Flow */}
              <div className="bg-gray-50 rounded-lg border border-gray-200 p-4">
                <h3 className="font-semibold text-gray-900 mb-3">Execution Flow</h3>
                <div className="space-y-2">
                  {agents.map((agent, idx) => (
                    <div key={idx} className="flex items-center gap-3 bg-white rounded-lg p-3 border">
                      <div className={`p-2 rounded-full ${
                        agent.status === 'completed' ? 'bg-green-100' :
                        agent.status === 'error' ? 'bg-red-100' : 'bg-blue-100'
                      }`}>
                        <Bot className={`w-4 h-4 ${
                          agent.status === 'completed' ? 'text-green-600' :
                          agent.status === 'error' ? 'text-red-600' : 'text-blue-600'
                        }`} />
                      </div>
                      <div className="flex-1">
                        <div className="font-medium text-gray-900">{agent.id}</div>
                        <div className="text-xs text-gray-500">
                          {agent.llmCalls.length} LLM calls, {agent.events.filter(e => e.data?.tool).length} tools
                        </div>
                      </div>
                      <div className={`px-2 py-1 rounded text-xs font-medium ${
                        agent.status === 'completed' ? 'bg-green-100 text-green-700' :
                        agent.status === 'error' ? 'bg-red-100 text-red-700' : 'bg-blue-100 text-blue-700'
                      }`}>
                        {agent.status}
                      </div>
                    </div>
                  ))}
                  {agents.length === 0 && (
                    <div className="text-center py-8 text-gray-500">
                      <Bot className="w-8 h-8 mx-auto mb-2 opacity-30" />
                      <p>No agents have run yet</p>
                    </div>
                  )}
                </div>
              </div>
            </div>
          )}

          {/* Agents Tab */}
          {activeTab === 'agents' && (
            <div className="space-y-4">
              {agents.length > 0 ? agents.map((agent, idx) => (
                <div key={idx} className="bg-white rounded-lg border border-gray-200 overflow-hidden">
                  <div
                    className={`flex items-center justify-between p-4 cursor-pointer ${
                      agent.status === 'completed' ? 'bg-green-50' :
                      agent.status === 'error' ? 'bg-red-50' : 'bg-blue-50'
                    }`}
                    onClick={() => toggleExpand(`agent-${idx}`)}
                  >
                    <div className="flex items-center gap-3">
                      <Bot className={`w-5 h-5 ${
                        agent.status === 'completed' ? 'text-green-600' :
                        agent.status === 'error' ? 'text-red-600' : 'text-blue-600'
                      }`} />
                      <div>
                        <div className="font-semibold text-gray-900">{agent.id}</div>
                        <div className="text-xs text-gray-500">
                          {agent.llmCalls.length} LLM iterations, {agent.events.length} events
                        </div>
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className={`px-2 py-1 rounded text-xs font-medium ${
                        agent.status === 'completed' ? 'bg-green-100 text-green-700' :
                        agent.status === 'error' ? 'bg-red-100 text-red-700' : 'bg-blue-100 text-blue-700'
                      }`}>
                        {agent.status}
                      </span>
                      {expandedItems[`agent-${idx}`] ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
                    </div>
                  </div>
                  {expandedItems[`agent-${idx}`] && (
                    <div className="p-4 border-t border-gray-200 space-y-3">
                      {/* Agent LLM Calls */}
                      {agent.llmCalls.map((call, callIdx) => (
                        <div key={callIdx} className="bg-purple-50 rounded-lg p-3 border border-purple-200">
                          <div className="flex items-center gap-2 mb-2">
                            <Brain className="w-4 h-4 text-purple-600" />
                            <span className="text-sm font-medium text-purple-900">Iteration {call.iteration || callIdx + 1}</span>
                            {call.tool_calls?.length > 0 && (
                              <span className="bg-orange-100 text-orange-700 px-2 py-0.5 rounded text-xs">
                                {call.tool_calls.length} tools
                              </span>
                            )}
                          </div>
                          {call.tool_calls?.length > 0 && (
                            <div className="flex flex-wrap gap-1 mt-2">
                              {call.tool_calls.map((tc, tcIdx) => (
                                <span key={tcIdx} className="bg-orange-200 text-orange-800 px-2 py-0.5 rounded text-xs font-mono">
                                  {tc.name || tc}
                                </span>
                              ))}
                            </div>
                          )}
                        </div>
                      ))}
                      {/* Agent Events */}
                      <div className="text-xs text-gray-500 mt-2">
                        <strong>Events:</strong> {agent.events.map(e => e.type).join(' → ')}
                      </div>
                    </div>
                  )}
                </div>
              )) : (
                <div className="text-center py-12 text-gray-500">
                  <Bot className="w-12 h-12 mx-auto mb-4 opacity-30" />
                  <p className="font-medium">No agents have run yet</p>
                  <p className="text-sm mt-1">Agents will appear here as they execute</p>
                </div>
              )}
            </div>
          )}

          {/* Tools Tab */}
          {activeTab === 'tools' && (
            <div className="space-y-2">
              {toolCalls.length > 0 ? toolCalls.map((tool, idx) => (
                <div key={idx} className="bg-orange-50 rounded-lg border border-orange-200 p-3">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <Hammer className="w-4 h-4 text-orange-600" />
                      <span className="font-mono text-sm font-medium text-orange-900">{tool.name}</span>
                      {tool.agent && (
                        <span className="bg-purple-100 text-purple-700 px-2 py-0.5 rounded text-xs">
                          {tool.agent}
                        </span>
                      )}
                    </div>
                    <span className={`px-2 py-0.5 rounded text-xs ${
                      tool.status === 'success' || tool.status === 'completed'
                        ? 'bg-green-100 text-green-700'
                        : 'bg-gray-100 text-gray-700'
                    }`}>
                      {tool.status}
                    </span>
                  </div>
                  {tool.args && (
                    <div className="mt-2 text-xs text-gray-600 font-mono bg-white rounded p-2 border">
                      {typeof tool.args === 'string' ? tool.args : JSON.stringify(tool.args, null, 2)}
                    </div>
                  )}
                  {tool.timestamp && (
                    <div className="text-xs text-gray-400 mt-1">
                      {new Date(tool.timestamp).toLocaleTimeString()}
                    </div>
                  )}
                </div>
              )) : (
                <div className="text-center py-12 text-gray-500">
                  <Hammer className="w-12 h-12 mx-auto mb-4 opacity-30" />
                  <p className="font-medium">No tool calls yet</p>
                  <p className="text-sm mt-1">MCP tool calls will appear here</p>
                </div>
              )}
            </div>
          )}

          {/* Events Tab */}
          {activeTab === 'events' && (
            <div className="space-y-2">
              {events.length > 0 ? events.map((event, idx) => (
                <div key={idx} className={`rounded-lg border p-3 ${getStatusColors(event.status)}`}>
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <div className={`p-1 rounded-full ${getIconBgColor(event.status)}`}>
                        {getEventIcon(event.type, event.status)}
                      </div>
                      <div>
                        <span className="font-medium text-sm">{event.title || event.type}</span>
                        {event.data?.agent_id && (
                          <span className="ml-2 bg-purple-100 text-purple-700 px-1.5 py-0.5 rounded text-xs">
                            {event.data.agent_id}
                          </span>
                        )}
                      </div>
                    </div>
                    <span className="text-xs text-gray-500">
                      {event.timestamp ? new Date(event.timestamp).toLocaleTimeString() : ''}
                    </span>
                  </div>
                  {event.description && (
                    <div className="text-xs opacity-80 mt-1 ml-8">{event.description}</div>
                  )}
                  {event.data && Object.keys(event.data).length > 0 && (
                    <details className="mt-2 ml-8">
                      <summary className="text-xs text-gray-500 cursor-pointer">Show data</summary>
                      <pre className="text-xs bg-gray-900 text-green-400 p-2 rounded mt-1 overflow-x-auto">
                        {JSON.stringify(event.data, null, 2)}
                      </pre>
                    </details>
                  )}
                </div>
              )) : (
                <div className="text-center py-12 text-gray-500">
                  <Clock className="w-12 h-12 mx-auto mb-4 opacity-30" />
                  <p className="font-medium">No events yet</p>
                  <p className="text-sm mt-1">Workflow events will appear here</p>
                </div>
              )}
            </div>
          )}

          {/* LLM Tab */}
          {activeTab === 'llm' && (
            <div className="space-y-4">
              {llmCalls.length > 0 ? llmCalls.map((call, idx) => (
                <div key={idx} className="bg-purple-50 rounded-lg border border-purple-200 overflow-hidden">
                  <div
                    className="flex items-center justify-between p-4 bg-purple-100 cursor-pointer"
                    onClick={() => toggleExpand(`llm-${idx}`)}
                  >
                    <div className="flex items-center gap-3">
                      <Brain className="w-5 h-5 text-purple-600" />
                      <div>
                        <span className="font-medium text-purple-900">{call.agent_id || 'LLM Call'}</span>
                        <span className="text-xs text-purple-600 ml-2">iter {call.iteration || idx + 1}</span>
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      {call.usage?.total_tokens && (
                        <span className="text-xs bg-blue-100 text-blue-700 px-2 py-0.5 rounded">
                          {call.usage.total_tokens} tokens
                        </span>
                      )}
                      {call.duration_ms && (
                        <span className="text-xs text-purple-600">{call.duration_ms}ms</span>
                      )}
                      {expandedItems[`llm-${idx}`] ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
                    </div>
                  </div>
                  {expandedItems[`llm-${idx}`] && (
                    <div className="p-4 space-y-3">
                      {/* Tool Calls */}
                      {call.tool_calls?.length > 0 && (
                        <div>
                          <div className="text-xs font-medium text-orange-600 uppercase mb-2">Tool Calls</div>
                          <div className="flex flex-wrap gap-1">
                            {call.tool_calls.map((tc, tcIdx) => (
                              <span key={tcIdx} className="bg-orange-200 text-orange-800 px-2 py-1 rounded text-xs font-mono">
                                {tc.name || tc}
                              </span>
                            ))}
                          </div>
                        </div>
                      )}
                      {/* Messages */}
                      {call.request?.messages && (
                        <details>
                          <summary className="text-xs font-medium text-purple-600 uppercase cursor-pointer">
                            Messages ({call.request.messages.length})
                          </summary>
                          <div className="mt-2 space-y-2">
                            {call.request.messages.map((msg, msgIdx) => (
                              <div key={msgIdx} className={`p-2 rounded text-xs ${
                                msg.role === 'system' ? 'bg-blue-900 text-blue-100' :
                                msg.role === 'user' ? 'bg-gray-800 text-gray-100' :
                                'bg-green-900 text-green-100'
                              }`}>
                                <div className="font-bold uppercase mb-1 opacity-70">{msg.role}</div>
                                <pre className="whitespace-pre-wrap overflow-x-auto max-h-32">{msg.content}</pre>
                              </div>
                            ))}
                          </div>
                        </details>
                      )}
                      {/* Response */}
                      {call.response && (
                        <details>
                          <summary className="text-xs font-medium text-green-600 uppercase cursor-pointer">Response</summary>
                          <pre className="mt-2 text-xs bg-gray-900 text-green-400 p-2 rounded overflow-x-auto max-h-48">
                            {typeof call.response === 'string' ? call.response : JSON.stringify(call.response, null, 2)}
                          </pre>
                        </details>
                      )}
                    </div>
                  )}
                </div>
              )) : (
                <div className="text-center py-12 text-gray-500">
                  <Brain className="w-12 h-12 mx-auto mb-4 opacity-30" />
                  <p className="font-medium">No LLM calls yet</p>
                  <p className="text-sm mt-1">LLM calls will appear here</p>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-6 py-3 border-t border-gray-200 bg-gray-50">
          <p className="text-xs text-gray-500 text-center">
            {agents.length} agent(s), {toolCalls.length} tool call(s), {llmCalls.length} LLM call(s), {events.length} event(s)
          </p>
        </div>
      </div>
    </div>
  )
}

const Chat = () => {
  const { user } = useAuth()
  const toast = useToast()
  const [searchParams, setSearchParams] = useSearchParams()
  const navigate = useNavigate()
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [currentPlanId, setCurrentPlanId] = useState(null)
  const [currentStep, setCurrentStep] = useState(null)
  const [debugPanelOpen, setDebugPanelOpen] = useState(false)
  const [apiCalls, setApiCalls] = useState([])
  const [liveWorkflowEvents, setLiveWorkflowEvents] = useState([])
  const [debugWorkflowEvents, setDebugWorkflowEvents] = useState([]) // Persisted events for debug panel
  const [debugLLMCalls, setDebugLLMCalls] = useState([]) // LLM calls for debug panel
  const [workspaceInfo, setWorkspaceInfo] = useState(null)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const [initialSessionLoaded, setInitialSessionLoaded] = useState(false)
  const [currentProject, setCurrentProject] = useState(null) // Project info for current session
  const messagesEndRef = useRef(null)
  const queryClient = useQueryClient()

  // Fetch session history with pagination
  const { data: sessionsData } = useQuery({
    queryKey: ['sessions'],
    queryFn: () => getSessions(1, 20),
    refetchInterval: 30000,
  })

  // Load session from URL parameter on initial load
  useEffect(() => {
    if (initialSessionLoaded) return

    const sessionIdFromUrl = searchParams.get('session')
    if (!sessionIdFromUrl) {
      setInitialSessionLoaded(true)
      return
    }

    // Load the session directly by ID
    const loadSessionFromUrl = async () => {
      try {
        const fullSession = await getPlan(sessionIdFromUrl)
        if (fullSession) {
          setCurrentPlanId(sessionIdFromUrl)
          setInitialSessionLoaded(true)

          // Load project info if session has a project
          if (fullSession.project) {
            // Session API already returns project info
            setCurrentProject(fullSession.project)
          } else if (fullSession.project_id) {
            // Fetch project info if only ID is available
            try {
              const projectInfo = await getProject(fullSession.project_id)
              setCurrentProject(projectInfo)
            } catch (err) {
              console.error('Error fetching project info:', err)
              setCurrentProject(null)
            }
          } else {
            setCurrentProject(null)
          }

          // Load persisted workflow events and LLM calls
          const workflowEvents = fullSession.result?.workflow_events || []
          const llmCalls = fullSession.result?.llm_calls || []

          const normalizedEvents = workflowEvents.map(event => ({
            ...event,
            event_type: event.type || event.event_type,
            title: event.title || formatEventTitle({ ...event, event_type: event.type }),
            description: event.data?.description || event.description || '',
            status: event.status || 'info',
            data: event.data || event,
          }))
          setDebugWorkflowEvents(normalizedEvents)
          setDebugLLMCalls(llmCalls)
          setApiCalls(llmCalls.map(call => ({ type: 'llm', ...call })))

          // Build pending approvals from tasks
          let pendingApprovals = []
          if (fullSession.tasks) {
            pendingApprovals = fullSession.tasks
              .filter(task => task.status === 'pending_approval')
              .map(task => ({
                task_id: task.id,
                task_name: task.name,
                mcp_tool: task.mcp_tool,
                required_role: task.required_role,
                approval_type: task.approval_type,
                required_roles: task.required_roles,
                required_approvals: task.required_approvals || 1,
                current_approvals: task.approvals?.filter(a => a.decision === 'approved').length || 0,
                approved_by_roles: task.approvals?.filter(a => a.decision === 'approved').map(a => a.role) || [],
                approved_by_ids: task.approvals?.filter(a => a.decision === 'approved').map(a => a.approved_by || a.approver_id) || [],
              }))
          }

          // Reconstruct messages from session
          const reconstructedMessages = []
          const userMessage = fullSession.description || fullSession.preview
          if (userMessage) {
            reconstructedMessages.push({
              role: 'user',
              content: userMessage,
            })
          }

          const resultMessage = fullSession.result?.response || `Session - Status: ${fullSession.status}`
          reconstructedMessages.push({
            role: 'assistant',
            content: resultMessage,
            planId: sessionIdFromUrl,
            status: fullSession.status,
            workflowEvents: workflowEvents,
            pendingApprovals: pendingApprovals,
          })

          setMessages(reconstructedMessages.length > 0 ? reconstructedMessages : [
            {
              role: 'assistant',
              content: `Continuing conversation...`,
              planId: sessionIdFromUrl,
            }
          ])
        }
      } catch (err) {
        console.error('Error loading session from URL:', err)
        // Don't clear the URL parameter - preserve the session ID for retry/debugging
        // The session may be temporarily unavailable or loading
        setInitialSessionLoaded(true)
      }
    }

    loadSessionFromUrl()
  }, [searchParams, initialSessionLoaded])

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

  // Initialize WebSocket connection and join approval rooms
  useEffect(() => {
    if (!user?.roles) return

    // Initialize socket connection
    initSocket()

    // Join approval rooms for user's roles
    joinApprovalsRoom(user.roles)

    // Cleanup on unmount
    return () => {
      disconnectSocket()
    }
  }, [user?.roles])

  // Join plan room when currentPlanId changes
  useEffect(() => {
    if (currentPlanId) {
      joinPlanRoom(currentPlanId)
    }
  }, [currentPlanId])

  // Listen for real-time workflow events during processing
  useEffect(() => {
    const handleWorkflowEvent = (data) => {
      // Only process events for the current session (or if no session yet, any event)
      // Backend sends session_id, not plan_id
      const eventSessionId = data.session_id || data.plan_id
      if (eventSessionId && currentPlanId && eventSessionId !== currentPlanId) {
        return
      }

      const event = data.event
      if (!event) return

      // Update current step description - prefer title from event data
      const stepTitle = event.title || event.data?.description || formatEventTitle(event)
      if (stepTitle) {
        setCurrentStep(stepTitle)
      }

      // Add to live events list with proper formatting
      const formattedEvent = {
        ...event,
        event_type: event.type,
        title: stepTitle,
        description: event.data?.description || event.description,
        status: event.status || (event.type?.includes('completed') || event.type?.includes('success') ? 'success' : 'working'),
        data: event.data || event,
      }
      setLiveWorkflowEvents((prev) => [...prev, formattedEvent])
    }

    // Subscribe to workflow events
    const unsubscribe = onWorkflowEvent(handleWorkflowEvent)

    return () => {
      unsubscribe()
    }
  }, [currentPlanId])

  // Listen for real-time approval updates
  useEffect(() => {
    // Handler for task_approved events
    const handleTaskApproved = (task) => {
      // Get the latest approval (most recent one)
      const approvals = task.approvals || []
      const latestApproval = approvals[approvals.length - 1]
      const approverRole = latestApproval?.approver_role || latestApproval?.role || 'unknown'
      const approverId = latestApproval?.approved_by || latestApproval?.approver_id

      // Show toast notification only if it's from another user
      if (approverId && approverId !== user?.id) {
        if (task.status === 'approved') {
          toast.success(
            'Task Fully Approved',
            `"${task.name}" has been approved and will now execute.`
          )
        } else {
          toast.info(
            'New Approval Received',
            `A ${approverRole} has approved "${task.name}".`
          )
        }
      }

      // Update messages to refresh approval cards
      setMessages((prev) =>
        prev.map((msg) => {
          if (!msg.pendingApprovals) return msg

          // Update the approval in the message
          const updatedApprovals = msg.pendingApprovals.map((approval) => {
            if (approval.task_id === task.id) {
              // Get updated approval info from task
              const approvedApprovals = approvals.filter(a => a.decision === 'approved')
              return {
                ...approval,
                current_approvals: approvedApprovals.length,
                approved_by_roles: approvedApprovals.map(a => a.approver_role || a.role).filter(Boolean),
                approved_by_ids: approvedApprovals.map(a => a.approved_by || a.approver_id).filter(Boolean),
                status: task.status,
              }
            }
            return approval
          })

          // Remove fully approved tasks
          const stillPendingApprovals = updatedApprovals.filter(
            (a) => a.status !== 'approved' && a.status !== 'rejected'
          )

          return {
            ...msg,
            pendingApprovals: stillPendingApprovals,
          }
        })
      )

      // Invalidate plans query to refresh sidebar
      queryClient.invalidateQueries({ queryKey: ['sessions'] })
    }

    // Handler for task_rejected events
    const handleTaskRejected = (task) => {
      // Get rejection info
      const rejectionApproval = (task.approvals || []).find(a => a.decision === 'rejected')
      const rejectorRole = rejectionApproval?.approver_role || rejectionApproval?.role || 'someone'
      const rejectorId = rejectionApproval?.approved_by || rejectionApproval?.approver_id

      // Show toast notification only if it's from another user
      if (rejectorId && rejectorId !== user?.id) {
        toast.warning(
          'Task Rejected',
          `"${task.name}" has been rejected by a ${rejectorRole}.`
        )
      }

      // Remove rejected task from pending approvals
      setMessages((prev) =>
        prev.map((msg) => {
          if (!msg.pendingApprovals) return msg

          return {
            ...msg,
            pendingApprovals: msg.pendingApprovals.filter(
              (approval) => approval.task_id !== task.id
            ),
          }
        })
      )

      // Invalidate plans query to refresh sidebar
      queryClient.invalidateQueries({ queryKey: ['sessions'] })
    }

    // Subscribe to events
    const unsubApproved = onTaskApproved(handleTaskApproved)
    const unsubRejected = onTaskRejected(handleTaskRejected)

    return () => {
      unsubApproved()
      unsubRejected()
    }
  }, [queryClient, user?.id, toast])

  // Listen for HITL MCP events (questions and approvals from microservices)
  useEffect(() => {
    // Handler for HITL questions from MCP microservices
    const handleHITLQuestion = (data) => {
      // Add question to the current message or create a new one
      const questionData = {
        id: data.request_id,
        question: data.question,
        input_type: data.input_type,
        choices: data.choices || [],
        allow_other: data.allow_other !== false,
        context: data.context,
        session_id: data.session_id || currentPlanId,
      }

      // Update messages to show the question
      setMessages((prev) => {
        const lastMsg = prev[prev.length - 1]
        if (lastMsg && !lastMsg.role === 'user') {
          // Append question to the last assistant message
          return prev.map((msg, idx) => {
            if (idx === prev.length - 1) {
              return {
                ...msg,
                pendingQuestions: [...(msg.pendingQuestions || []), questionData],
              }
            }
            return msg
          })
        } else {
          // Add a new assistant message with the question
          return [
            ...prev,
            {
              role: 'assistant',
              content: '',
              pendingQuestions: [questionData],
              timestamp: new Date().toISOString(),
            },
          ]
        }
      })

      toast.info('Question from Agent', data.question)
    }

    // Handler for MCP approval required events
    const handleApprovalRequired = (data) => {
      const approvalData = {
        task_id: data.approval_id,
        task_name: `${data.tool}`,
        mcp_tool: data.tool,
        required_roles: data.required_roles || ['developer'],
        danger_level: data.danger_level || 'medium',
        approval_type: data.required_roles?.length > 1 ? 'multi' : 'self',
        current_approvals: 0,
        required_approvals: 1,
        approved_by_roles: [],
        approved_by_ids: [],
        args: data.args,
      }

      // Update messages to show the approval request
      setMessages((prev) => {
        const lastMsg = prev[prev.length - 1]
        if (lastMsg && lastMsg.role !== 'user') {
          return prev.map((msg, idx) => {
            if (idx === prev.length - 1) {
              return {
                ...msg,
                pendingApprovals: [...(msg.pendingApprovals || []), approvalData],
              }
            }
            return msg
          })
        } else {
          return [
            ...prev,
            {
              role: 'assistant',
              content: `I need approval to run: ${data.tool}`,
              pendingApprovals: [approvalData],
              timestamp: new Date().toISOString(),
            },
          ]
        }
      })

      toast.warning('Approval Required', `Agent wants to run: ${data.tool}`)
    }

    // Handler for progress updates
    const handleHITLProgress = (data) => {
      // Add progress event to workflow events
      setLiveWorkflowEvents((prev) => [
        ...prev,
        {
          event_type: 'progress',
          title: data.step || 'Progress Update',
          description: data.message,
          status: 'working',
          data: { percent: data.percent },
        },
      ])
    }

    const unsubQuestion = onHITLQuestion(handleHITLQuestion)
    const unsubApproval = onApprovalRequired(handleApprovalRequired)
    const unsubProgress = onHITLProgress(handleHITLProgress)

    return () => {
      unsubQuestion()
      unsubApproval()
      unsubProgress()
    }
  }, [currentPlanId, toast])

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  useEffect(() => {
    scrollToBottom()
  }, [messages])

  const chatMutation = useMutation({
    mutationFn: async ({ message, conversationHistory, sessionId }) => {
      // Track the API call start time
      const startTime = Date.now()

      // Use the pre-generated sessionId for consistency with WebSocket room
      const effectiveSessionId = sessionId || currentPlanId

      const requestData = {
        message,
        session_id: effectiveSessionId,
        conversation_history: conversationHistory.length > 0 ? conversationHistory : null,
      }

      try {
        const response = await sendChat(message, effectiveSessionId, requestData.conversation_history)

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
      // Normalize workflow events from API response to have consistent structure
      const normalizedEvents = (data.workflow_events || []).map(event => ({
        ...event,
        event_type: event.type || event.event_type,
        title: event.title || formatEventTitle({ ...event, event_type: event.type }),
        description: event.data?.description || event.description || '',
        status: event.status || (event.type?.includes('completed') || event.type?.includes('success') ? 'success' : 'info'),
        data: event.data || event,
      }))

      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: data.response,
          planId: data.plan_id,
          pendingApprovals: data.pending_approvals,
          pendingQuestions: data.pending_questions || [],
          status: data.status,
          workflowEvents: normalizedEvents,
        },
      ])
      setCurrentPlanId(data.plan_id)
      setCurrentStep(null)

      // Store events for debug panel (combine live events with API response events)
      const combinedEvents = [...liveWorkflowEvents, ...normalizedEvents]
      setDebugWorkflowEvents(combinedEvents)
      setDebugLLMCalls(data.llm_calls || [])
      setLiveWorkflowEvents([]) // Clear live events after storing

      // Update workspace info if available
      if (data.workspace_id || data.project_id || data.branch) {
        setWorkspaceInfo({
          workspace_id: data.workspace_id,
          project_id: data.project_id,
          branch: data.branch,
          workspace_path: data.workspace_path,
        })
      }
      queryClient.invalidateQueries({ queryKey: ['projects'] })
      queryClient.invalidateQueries({ queryKey: ['sessions'] })
      queryClient.invalidateQueries({ queryKey: ['tasks'] })
      queryClient.invalidateQueries({ queryKey: ['questions'] })
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
      // Store what we have for debugging even on error
      setDebugWorkflowEvents([...liveWorkflowEvents])
      setLiveWorkflowEvents([])
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
      queryClient.invalidateQueries({ queryKey: ['tasks'] })
      queryClient.invalidateQueries({ queryKey: ['sessions'] })
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
      queryClient.invalidateQueries({ queryKey: ['tasks'] })
      queryClient.invalidateQueries({ queryKey: ['sessions'] })
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

      queryClient.invalidateQueries({ queryKey: ['questions'] })
      queryClient.invalidateQueries({ queryKey: ['sessions'] })
      queryClient.invalidateQueries({ queryKey: ['projects'] })
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

  const handleAnswerQuestion = async (questionId, answer, selected = null) => {
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
      return [...updated, { role: 'user', content: selected || answer }]
    })

    // Show processing indicator
    setCurrentStep('Processing your answer...')
    setLiveWorkflowEvents([]) // Clear live events for new processing
    setDebugWorkflowEvents([])
    setDebugLLMCalls([])

    // Check if this is a HITL MCP request (UUID format request_id)
    const isHITLRequest = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(questionId)

    if (isHITLRequest) {
      // Use HITL MCP response endpoint
      try {
        await submitHITLResponse(questionId, answer, selected)
        setCurrentStep(null)
      } catch (error) {
        console.error('HITL response error:', error)
        toast.error('Error', 'Failed to submit answer')
        setCurrentStep(null)
      }
    } else {
      // Use legacy question answer API
      answerMutation.mutate({ questionId, answer })
    }
  }

  const handleSubmit = (e) => {
    e.preventDefault()
    if (!input.trim() || chatMutation.isPending) return

    const userMessage = input.trim()
    setInput('')
    setCurrentStep('Processing your request...')
    setLiveWorkflowEvents([]) // Clear live events for new request
    setDebugWorkflowEvents([])
    setDebugLLMCalls([])

    // Generate or use existing session ID for real-time events
    // IMPORTANT: We need the session ID BEFORE the API call to receive WebSocket events
    const sessionId = currentPlanId || crypto.randomUUID()

    // Join the session room BEFORE making the API call to receive events
    // This ensures we receive all workflow events emitted during processing
    joinPlanRoom(sessionId)

    // If this is a new session, set it immediately so event handlers work
    if (!currentPlanId) {
      setCurrentPlanId(sessionId)
    }

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
    chatMutation.mutate({ message: userMessage, conversationHistory, sessionId })
  }

  const handleNewChat = () => {
    setCurrentPlanId(null)
    setApiCalls([]) // Clear debug data for new chat
    setLiveWorkflowEvents([]) // Clear live events for new chat
    setDebugWorkflowEvents([]) // Clear debug events for new chat
    setDebugLLMCalls([]) // Clear debug LLM calls for new chat
    setWorkspaceInfo(null) // Clear workspace info for new chat
    setCurrentProject(null) // Clear project info for new chat
    setSearchParams({}) // Clear URL parameter for new chat
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

  const handleSelectPlan = async (session) => {
    setCurrentPlanId(session.id)
    setLiveWorkflowEvents([]) // Clear live events when selecting session
    setSearchParams({ session: session.id }) // Update URL for deep linking

    // Fetch full session details (needed for workflow_events, llm_calls, pending approvals)
    let fullSession = session
    let pendingApprovals = []
    try {
      fullSession = await getPlan(session.id)
      if (fullSession.tasks) {
        pendingApprovals = fullSession.tasks
          .filter(task => task.status === 'pending_approval')
          .map(task => ({
            task_id: task.id,
            task_name: task.name,
            mcp_tool: task.mcp_tool,
            required_role: task.required_role,
            approval_type: task.approval_type,
            required_roles: task.required_roles,
            required_approvals: task.required_approvals || 1,
            current_approvals: task.approvals?.filter(a => a.decision === 'approved').length || 0,
            approved_by_roles: task.approvals?.filter(a => a.decision === 'approved').map(a => a.role) || [],
            approved_by_ids: task.approvals?.filter(a => a.decision === 'approved').map(a => a.approved_by || a.approver_id) || [],
          }))
      }

      // Load project info if session has a project
      if (fullSession.project) {
        // Session API already returns project info
        setCurrentProject(fullSession.project)
      } else if (fullSession.project_id) {
        // Fetch project info if only ID is available
        try {
          const projectInfo = await getProject(fullSession.project_id)
          setCurrentProject(projectInfo)
        } catch (projectErr) {
          console.error('Error fetching project info:', projectErr)
          setCurrentProject(null)
        }
      } else {
        setCurrentProject(null)
      }
    } catch (err) {
      console.error('Error fetching session details:', err)
      setCurrentProject(null)
    }

    // Load persisted workflow events and LLM calls from full session result
    const workflowEvents = fullSession.result?.workflow_events || []
    const llmCalls = fullSession.result?.llm_calls || []

    // Load into debug panel with normalized events
    const normalizedEvents = workflowEvents.map(event => ({
      ...event,
      event_type: event.type || event.event_type,
      title: event.title || formatEventTitle({ ...event, event_type: event.type }),
      description: event.data?.description || event.description || '',
      status: event.status || 'info',
      data: event.data || event,
    }))
    setDebugWorkflowEvents(normalizedEvents)
    setDebugLLMCalls(llmCalls)
    setApiCalls(llmCalls.map(call => ({ type: 'llm', ...call })))

    // Reconstruct messages from session
    const reconstructedMessages = []

    // Add the original user message (use preview from sidebar data or description from full data)
    const userMessage = fullSession.description || session.preview
    if (userMessage) {
      reconstructedMessages.push({
        role: 'user',
        content: userMessage,
      })
    }

    // Add a response based on session result with workflow events and pending approvals
    const resultMessage = fullSession.result?.response || `Session - Status: ${fullSession.status || session.status}`
    reconstructedMessages.push({
      role: 'assistant',
      content: resultMessage,
      planId: session.id,
      status: fullSession.status || session.status,
      workflowEvents: workflowEvents, // Include persisted workflow events
      pendingApprovals: pendingApprovals, // Include current pending approvals
    })

    setMessages(reconstructedMessages.length > 0 ? reconstructedMessages : [
      {
        role: 'assistant',
        content: `Continuing conversation...`,
        planId: session.id,
      }
    ])
  }

  const suggestions = [
    'Create a todo app with Flask',
    'Build a simple calculator',
    'Make a notes app with React',
    'Create a weather dashboard',
  ]

  // Handle opening debug panel for a specific session
  const handleDebugSession = (sessionId) => {
    // Navigate to the Debug page with the session ID
    // For now, just open the debug panel after selecting the session
    const session = sessionsData?.sessions?.find(s => s.id === sessionId)
    if (session) {
      handleSelectPlan(session)
      setTimeout(() => setDebugPanelOpen(true), 100)
    }
  }

  return (
    <div className="flex h-[calc(100vh-10rem)] -mx-4 sm:-mx-6 lg:-mx-8">
      {/* Collapsible Session History Sidebar */}
      <ConversationSidebar
        sessions={sessionsData}
        activeSessionId={currentPlanId}
        onSelectSession={handleSelectPlan}
        onNewChat={handleNewChat}
        onDebugSession={handleDebugSession}
        isCollapsed={sidebarCollapsed}
        onToggleCollapse={() => setSidebarCollapsed(!sidebarCollapsed)}
      />

      {/* Main Chat Area */}
      <div className="flex-1 flex flex-col bg-gray-50">
        {/* Header with Project Context and Debug Button */}
        <div className="flex items-center justify-between px-4 py-2 border-b border-gray-200 bg-white">
          <div className="flex items-center gap-4">
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
            {/* Project Context */}
            {currentProject && (
              <div className="flex items-center gap-2 px-3 py-1.5 bg-purple-50 rounded-lg border border-purple-200">
                <FolderOpen className="w-4 h-4 text-purple-600" />
                <span className="text-sm font-medium text-purple-900">{currentProject.name}</span>
                <button
                  onClick={() => navigate(`/projects/${currentProject.id}`)}
                  className="ml-1 flex items-center gap-1 text-xs text-purple-600 hover:text-purple-800 hover:underline focus:outline-none focus:ring-2 focus:ring-purple-500 rounded"
                  aria-label={`View project: ${currentProject.name}`}
                >
                  <ExternalLink className="w-3 h-3" />
                  View Project
                </button>
              </div>
            )}
          </div>
          <button
            onClick={() => setDebugPanelOpen(true)}
            className="flex items-center gap-2 px-3 py-1.5 text-sm text-gray-600 hover:text-gray-800 hover:bg-gray-100 rounded-lg transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500"
            aria-label="Open debug panel"
          >
            <Bug className="w-4 h-4" aria-hidden="true" />
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
              currentUserId={user?.id}
            />
          ))}

          {chatMutation.isPending && (
            <TypingIndicator currentStep={currentStep} liveEvents={liveWorkflowEvents} />
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
              className="px-6 py-3 bg-gradient-to-r from-blue-600 to-purple-600 text-white rounded-xl hover:from-blue-700 hover:to-purple-700 disabled:opacity-50 disabled:cursor-not-allowed transition-all shadow-md hover:shadow-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2"
              aria-label="Send message"
            >
              <Send className="w-5 h-5" aria-hidden="true" />
              <span className="sr-only">Send message</span>
            </button>
          </div>
        </form>
      </div>

      {/* Debug Panel - shows live events during execution, persisted events after */}
      <DebugPanel
        isOpen={debugPanelOpen}
        onClose={() => setDebugPanelOpen(false)}
        apiCalls={apiCalls}
        workflowEvents={liveWorkflowEvents.length > 0 ? liveWorkflowEvents : debugWorkflowEvents}
        llmCalls={debugLLMCalls}
        workspaceInfo={workspaceInfo}
      />
    </div>
  )
}

export default Chat
