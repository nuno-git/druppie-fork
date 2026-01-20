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
} from 'lucide-react'
import { sendChat, getPlans } from '../services/api'
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
    case 'task_created':
    case 'task_executing':
    case 'task_completed':
      return <Clock {...iconProps} />
    case 'mcp_tool':
      return <Hammer {...iconProps} />
    case 'llm_generating':
      return <Brain {...iconProps} />
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

  return (
    <div className={`flex items-start gap-3 p-3 rounded-lg border ${colors} mb-2`}>
      <div className={`p-1.5 rounded-full ${iconBg} flex-shrink-0`}>
        {getEventIcon(event.event_type, event.status)}
      </div>
      <div className="flex-1 min-w-0">
        <div className="font-medium text-sm">{event.title}</div>
        <div className="text-xs opacity-80 mt-0.5">{event.description}</div>
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

// Workflow Events Timeline (collapsible)
const WorkflowTimeline = ({ events, isExpanded, onToggle }) => {
  if (!events || events.length === 0) return null

  return (
    <div className="mt-3 border-t border-gray-100 pt-3">
      <button
        onClick={onToggle}
        className="flex items-center gap-2 text-sm text-gray-600 hover:text-gray-800 mb-2"
      >
        {isExpanded ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
        <span className="font-medium">Workflow Details</span>
        <span className="text-xs bg-gray-100 px-2 py-0.5 rounded-full">{events.length} steps</span>
      </button>

      {isExpanded && (
        <div className="space-y-1 pl-2 border-l-2 border-gray-200 ml-2">
          {events.map((event, index) => (
            <WorkflowEvent key={index} event={event} />
          ))}
        </div>
      )}
    </div>
  )
}

const Message = ({ message }) => {
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
            {/* Main content */}
            <div className="whitespace-pre-wrap text-sm">{message.content}</div>

            {/* Workflow Events Timeline */}
            {!isUser && message.workflowEvents && message.workflowEvents.length > 0 && (
              <WorkflowTimeline
                events={message.workflowEvents}
                isExpanded={eventsExpanded}
                onToggle={() => setEventsExpanded(!eventsExpanded)}
              />
            )}

            {/* Pending Approvals */}
            {message.pendingApprovals && message.pendingApprovals.length > 0 && (
              <div className="mt-3 p-3 bg-yellow-50 rounded-lg border border-yellow-200">
                <div className="flex items-center text-yellow-700 mb-2">
                  <AlertCircle className="w-4 h-4 mr-2" />
                  <span className="font-medium text-sm">Pending Approvals</span>
                </div>
                <ul className="text-sm text-yellow-800 space-y-1">
                  {message.pendingApprovals.map((approval, i) => (
                    <li key={i} className="flex items-center">
                      <span className="w-2 h-2 rounded-full bg-yellow-500 mr-2" />
                      {approval.task_name} - requires{' '}
                      <span className="font-medium ml-1">{approval.required_role}</span>
                    </li>
                  ))}
                </ul>
              </div>
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
  return (
    <div className="flex justify-start mb-4">
      <div className="bg-white border border-gray-200 rounded-2xl rounded-bl-none px-4 py-3 shadow-sm">
        <div className="flex items-center space-x-3">
          <div className="w-8 h-8 rounded-full bg-gradient-to-br from-blue-500 to-purple-600 flex items-center justify-center">
            <Loader2 className="w-5 h-5 text-white animate-spin" />
          </div>
          <div>
            <div className="text-sm text-gray-600">
              {currentStep || 'Thinking...'}
            </div>
            <div className="flex space-x-1 mt-1">
              <span className="w-2 h-2 bg-blue-400 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
              <span className="w-2 h-2 bg-blue-400 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
              <span className="w-2 h-2 bg-blue-400 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
            </div>
          </div>
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

const Chat = () => {
  const { user } = useAuth()
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [currentPlanId, setCurrentPlanId] = useState(null)
  const [currentStep, setCurrentStep] = useState(null)
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
    mutationFn: (message) => sendChat(message, currentPlanId),
    onSuccess: (data) => {
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: data.response,
          planId: data.plan_id,
          pendingApprovals: data.pending_approvals,
          status: data.status,
          workflowEvents: data.workflow_events || [],
        },
      ])
      setCurrentPlanId(data.plan_id)
      setCurrentStep(null)
      queryClient.invalidateQueries(['projects'])
      queryClient.invalidateQueries(['plans'])
      queryClient.invalidateQueries(['tasks'])
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

  const handleSubmit = (e) => {
    e.preventDefault()
    if (!input.trim() || chatMutation.isPending) return

    const userMessage = input.trim()
    setInput('')
    setCurrentStep('Processing your request...')

    setMessages((prev) => [...prev, { role: 'user', content: userMessage }])
    chatMutation.mutate(userMessage)
  }

  const handleNewChat = () => {
    setCurrentPlanId(null)
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
    // Reconstruct messages from plan
    const reconstructedMessages = []

    // Add the original user message
    if (plan.description) {
      reconstructedMessages.push({
        role: 'user',
        content: plan.description,
      })
    }

    // Add a response based on plan result
    const resultMessage = plan.result?.response || `Plan "${plan.name}" - Status: ${plan.status}`
    reconstructedMessages.push({
      role: 'assistant',
      content: resultMessage,
      planId: plan.id,
      status: plan.status,
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
        {/* Messages */}
        <div className="flex-1 overflow-y-auto p-4 space-y-2">
          {messages.map((message, index) => (
            <Message key={index} message={message} />
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
    </div>
  )
}

export default Chat
