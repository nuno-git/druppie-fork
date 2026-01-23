/**
 * Event utility functions for workflow events display
 */

import {
  Zap,
  Brain,
  Clock,
  Hammer,
  Bot,
  XCircle,
  HelpCircle,
  FileCode,
  GitBranch,
  Play,
  AlertTriangle,
  CheckCircle,
  Loader2,
} from 'lucide-react'

// Icon mapping for workflow events
export const getEventIcon = (eventType, status) => {
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
export const getStatusColors = (status) => {
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

export const getIconBgColor = (status) => {
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
export const EVENT_CATEGORIES = {
  agent: ['agent_started', 'agent_completed', 'agent_error', 'agent_failed', 'agent_question'],
  tool: ['tool_call', 'tool_executing', 'tool_completed', 'mcp_tool'],
  llm: ['llm_generating', 'llm_calling', 'llm_call', 'llm_response'],
  workflow: ['workflow_started', 'workflow_completed', 'workflow_failed', 'step_started', 'step_completed'],
  approval: ['approval_required', 'question_pending'],
  result: ['files_created', 'git_pushed', 'build_complete', 'app_running', 'workspace_initialized'],
}

export const getEventCategory = (eventType) => {
  for (const [category, types] of Object.entries(EVENT_CATEGORIES)) {
    if (types.some(t => eventType?.includes(t) || eventType === t)) {
      return category
    }
  }
  return 'info'
}

export const getCategoryStyles = (category, status) => {
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

// Format event title for display
export const formatEventTitle = (event) => {
  const type = event.event_type || event.type || ''
  const title = event.title || ''
  const data = event.data || {}

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
    // Show model name for transparency
    const modelName = data.model ? ` [${data.model}]` : ''
    return agentName ? `${agentName} calling LLM${iteration}${modelName}` : `Calling LLM${iteration}${modelName}`
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

  if (title) return title
  if (type) {
    return type.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
  }
  return 'Processing'
}

// Get detailed description for an event
export const getEventDescription = (event) => {
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
    const parts = []
    // Show model/provider for transparency
    if (data.model) {
      const provider = data.provider ? ` (${data.provider})` : ''
      parts.push(`Model: ${data.model}${provider}`)
    }
    parts.push(data.has_tool_calls ? 'Tool calls made' : 'No tool calls')
    if (data.duration_ms) {
      parts.push(`Duration: ${data.duration_ms}ms`)
    }
    if (data.tokens) {
      parts.push(`Tokens: ${data.tokens}`)
    }
    return parts.join('. ')
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

// Process workflow events to mark "working" events as complete
export const processWorkflowEvents = (events) => {
  if (!events || events.length === 0) return events

  return events.map((event, index) => {
    if (event.status === 'working' && index < events.length - 1) {
      const subsequentEvents = events.slice(index + 1)
      const hasSubsequent = subsequentEvents.length > 0

      if (hasSubsequent) {
        let newStatus = 'success'
        if (event.event_type === 'task_executing' || event.event_type === 'executing') {
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
