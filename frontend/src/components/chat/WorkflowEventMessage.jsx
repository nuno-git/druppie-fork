/**
 * WorkflowEventMessage - Displays workflow events as chat messages
 * Shows agent start/complete, tool calls, and approvals inline in the chat
 * Enhanced with detailed argument display and clearer status indicators
 */

import React, { useState } from 'react'
import {
  ChevronDown,
  ChevronRight,
  Play,
  CheckCircle,
  XCircle,
  Clock,
  Hammer,
  Code,
  AlertTriangle,
  Loader2,
  Pause,
  Shield,
  FileCode,
  Terminal,
  GitBranch,
} from 'lucide-react'
import { getAgentConfig, getAgentMessageColors } from '../../utils/agentConfig'

// Helper to get tool icon based on tool name
const getToolIcon = (toolName) => {
  if (!toolName) return Hammer
  if (toolName.includes('write_file') || toolName.includes('batch_write')) return FileCode
  if (toolName.includes('run_command') || toolName.includes('run_tests')) return Terminal
  if (toolName.includes('commit') || toolName.includes('git')) return GitBranch
  return Hammer
}

const WorkflowEventMessage = ({ event }) => {
  // Auto-expand tool calls to show arguments by default
  const eventType = event.type || event.event_type || ''
  const isToolCall = eventType.includes('tool_call') || eventType === 'mcp_tool_call'
  const [expanded, setExpanded] = useState(isToolCall) // Tool calls expanded by default

  const agentId = event.agent || event.data?.agent_id || event.agent_id
  const agentConfig = agentId ? getAgentConfig(agentId) : null
  const AgentIcon = agentConfig?.icon || Clock
  const colors = agentConfig ? getAgentMessageColors(agentConfig.color) : null

  // Determine event category and styling
  const getEventDisplay = () => {
    // Handle specific agent events (router_started, developer_completed) and generic ones
    if (eventType.includes('_started') || eventType.includes('agent_started') || eventType === 'agent_start') {
      return {
        title: `${agentConfig?.name || agentId || 'Agent'} started working`,
        subtitle: agentConfig?.description || null,
        icon: Play,
        iconColor: 'text-blue-500',
        bgColor: colors?.bg || 'bg-blue-50',
        borderColor: colors?.border || 'border-blue-200',
        showExpand: false,
        isWorking: true,
        badge: 'WORKING',
        badgeColor: 'bg-blue-100 text-blue-700',
      }
    }

    if (eventType.includes('_completed') || eventType.includes('agent_completed') || eventType === 'agent_complete') {
      return {
        title: `${agentConfig?.name || agentId || 'Agent'} finished`,
        icon: CheckCircle,
        iconColor: 'text-green-500',
        bgColor: colors?.bg || 'bg-green-50',
        borderColor: colors?.border || 'border-green-200',
        showExpand: !!(event.result || event.data?.result || event.data?.output),
        content: event.result || event.data?.result || event.data?.output,
        badge: 'DONE',
        badgeColor: 'bg-green-100 text-green-700',
      }
    }

    if (eventType.includes('tool_call') || eventType === 'mcp_tool_call') {
      const toolName = event.tool || event.data?.tool || event.data?.tool_name
      const args = event.args || event.data?.args || event.data?.arguments || {}
      const ToolIcon = getToolIcon(toolName)
      return {
        title: `Tool: ${toolName}`,
        subtitle: `Called by ${agentConfig?.name || agentId || 'Agent'}`,
        icon: ToolIcon,
        iconColor: colors?.accent || 'text-purple-600',
        bgColor: 'bg-purple-50',
        borderColor: 'border-purple-200',
        showExpand: Object.keys(args).length > 0,
        args: args,
        toolName: toolName,
        badge: 'TOOL CALL',
        badgeColor: 'bg-purple-100 text-purple-700',
      }
    }

    if (eventType.includes('tool_result') || eventType === 'mcp_tool_result') {
      const success = event.data?.success !== false
      const toolName = event.tool || event.data?.tool || event.data?.tool_name
      return {
        title: success ? `✓ ${toolName || 'Tool'} completed` : `✗ ${toolName || 'Tool'} failed`,
        icon: success ? CheckCircle : XCircle,
        iconColor: success ? 'text-green-500' : 'text-red-500',
        bgColor: success ? 'bg-green-50' : 'bg-red-50',
        borderColor: success ? 'border-green-200' : 'border-red-200',
        showExpand: !!(event.data?.result || event.data?.error),
        content: event.data?.result || event.data?.error,
        isError: !success,
        badge: success ? 'SUCCESS' : 'FAILED',
        badgeColor: success ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700',
      }
    }

    if (eventType.includes('approval_required') || eventType === 'approval_pending') {
      const toolName = event.data?.tool || event.tool || 'action'
      return {
        title: `⏳ Waiting for approval`,
        subtitle: `Tool: ${toolName}`,
        icon: Shield,
        iconColor: 'text-amber-500',
        bgColor: 'bg-amber-50',
        borderColor: 'border-amber-300',
        showExpand: !!(event.data?.args || event.args),
        args: event.data?.args || event.args,
        isWaiting: true,
        badge: 'NEEDS APPROVAL',
        badgeColor: 'bg-amber-100 text-amber-800 animate-pulse',
      }
    }

    if (eventType.includes('approval_granted') || eventType === 'approved') {
      const approver = event.data?.approver || event.data?.approver_username || event.approver || 'user'
      const role = event.data?.approver_role || event.data?.role || ''
      return {
        title: `✅ Approved by ${approver}`,
        subtitle: role ? `Role: ${role}` : null,
        icon: CheckCircle,
        iconColor: 'text-green-500',
        bgColor: 'bg-green-50',
        borderColor: 'border-green-300',
        showExpand: false,
        badge: 'APPROVED',
        badgeColor: 'bg-green-100 text-green-700',
      }
    }

    if (eventType.includes('approval_rejected') || eventType === 'rejected') {
      const rejector = event.data?.approver || event.data?.approver_username || event.approver || 'user'
      return {
        title: `🚫 Rejected by ${rejector}`,
        subtitle: event.data?.reason ? `Reason: ${event.data.reason}` : null,
        icon: XCircle,
        iconColor: 'text-red-500',
        bgColor: 'bg-red-50',
        borderColor: 'border-red-300',
        showExpand: !!(event.data?.reason),
        content: event.data?.reason,
        badge: 'REJECTED',
        badgeColor: 'bg-red-100 text-red-700',
      }
    }

    if (eventType.includes('error') || eventType.includes('failed')) {
      return {
        title: event.title || 'Error occurred',
        icon: AlertTriangle,
        iconColor: 'text-red-500',
        bgColor: 'bg-red-50',
        borderColor: 'border-red-200',
        showExpand: !!(event.data?.error || event.error),
        content: event.data?.error || event.error,
        isError: true,
        badge: 'ERROR',
        badgeColor: 'bg-red-100 text-red-700',
      }
    }

    // Default display for other events
    return {
      title: event.title || event.description || eventType,
      icon: Clock,
      iconColor: 'text-gray-500',
      bgColor: 'bg-gray-50',
      borderColor: 'border-gray-200',
      showExpand: !!(event.data || event.result),
      content: event.data?.description || event.result,
    }
  }

  const display = getEventDisplay()
  const StatusIcon = display.icon

  // Format timestamp
  const timestamp = event.timestamp ? new Date(event.timestamp).toLocaleTimeString() : ''

  // Filter out internal params for display
  const filterParams = (params) => {
    if (!params || typeof params !== 'object') return {}
    const filtered = {}
    Object.entries(params).forEach(([key, value]) => {
      // Skip internal/uninteresting params
      if (['workspace_id', 'project_id', 'workspace_path', 'session_id'].includes(key)) return
      filtered[key] = value
    })
    return filtered
  }

  const displayArgs = display.args ? filterParams(display.args) : null
  const hasDisplayableArgs = displayArgs && Object.keys(displayArgs).length > 0

  return (
    <div className="flex justify-start mb-3">
      <div className={`max-w-[95%] rounded-xl px-4 py-3 border-2 ${display.bgColor} ${display.borderColor} shadow-sm`}>
        {/* Header row */}
        <div className="flex items-center gap-2 flex-wrap">
          {/* Agent icon */}
          {agentConfig && (
            <div className={`w-7 h-7 rounded-full flex items-center justify-center flex-shrink-0 ${colors?.bg || 'bg-gray-100'} border-2 ${colors?.border || 'border-gray-200'}`}>
              <AgentIcon className={`w-4 h-4 ${colors?.accent || 'text-gray-600'}`} />
            </div>
          )}

          {/* Status icon */}
          <StatusIcon className={`w-5 h-5 ${display.iconColor} flex-shrink-0`} />

          {/* Working spinner for agent_started */}
          {display.isWorking && (
            <Loader2 className="w-4 h-4 text-blue-500 animate-spin flex-shrink-0" />
          )}

          {/* Waiting indicator */}
          {display.isWaiting && (
            <Pause className="w-4 h-4 text-amber-500 flex-shrink-0" />
          )}

          {/* Title */}
          <span className="text-sm text-gray-800 font-semibold">{display.title}</span>

          {/* Badge */}
          {display.badge && (
            <span className={`text-xs font-bold px-2 py-0.5 rounded-full ${display.badgeColor}`}>
              {display.badge}
            </span>
          )}

          {/* Timestamp */}
          {timestamp && (
            <span className="text-xs text-gray-400 ml-auto">{timestamp}</span>
          )}

          {/* Expand button */}
          {display.showExpand && (
            <button
              onClick={() => setExpanded(!expanded)}
              className="ml-1 p-1 text-gray-400 hover:text-gray-600 hover:bg-gray-200 rounded transition-colors"
              title={expanded ? 'Collapse details' : 'Show details'}
            >
              {expanded ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
            </button>
          )}
        </div>

        {/* Subtitle */}
        {display.subtitle && (
          <div className="text-xs text-gray-500 mt-1 ml-9">
            {display.subtitle}
          </div>
        )}

        {/* Expanded content - Tool arguments */}
        {expanded && hasDisplayableArgs && (
          <div className="mt-3 pt-3 border-t border-gray-200">
            <div className="text-xs font-semibold text-gray-600 mb-2 flex items-center gap-1">
              <Code className="w-3 h-3" />
              Arguments:
            </div>
            <div className="bg-white rounded-lg border border-gray-200 p-3 text-xs font-mono overflow-x-auto max-h-64 overflow-y-auto">
              {Object.entries(displayArgs).map(([key, value]) => (
                <div key={key} className="mb-2 last:mb-0">
                  <div className="flex items-start gap-2">
                    <span className="text-purple-600 font-semibold min-w-[80px]">{key}:</span>
                    <span className="text-gray-800 break-all whitespace-pre-wrap flex-1">
                      {typeof value === 'string' && value.length > 300
                        ? (
                          <details className="cursor-pointer">
                            <summary className="text-blue-600 hover:underline">
                              {value.substring(0, 150)}... (click to expand)
                            </summary>
                            <div className="mt-2 p-2 bg-gray-50 rounded border max-h-48 overflow-y-auto">
                              {value}
                            </div>
                          </details>
                        )
                        : typeof value === 'object'
                          ? (
                            <pre className="bg-gray-50 p-2 rounded border overflow-x-auto">
                              {JSON.stringify(value, null, 2)}
                            </pre>
                          )
                          : String(value)}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Result/output content */}
        {expanded && display.content && (
          <div className="mt-3 pt-3 border-t border-gray-200">
            <div className="text-xs font-semibold text-gray-600 mb-2">
              {display.isError ? '❌ Error:' : '📤 Result:'}
            </div>
            <div className={`bg-white rounded-lg border p-3 text-xs overflow-x-auto max-h-48 overflow-y-auto ${display.isError ? 'border-red-200 bg-red-50' : 'border-gray-200'}`}>
              <pre className={`whitespace-pre-wrap break-all ${display.isError ? 'text-red-700' : 'text-gray-700'}`}>
                {typeof display.content === 'object'
                  ? JSON.stringify(display.content, null, 2)
                  : String(display.content).substring(0, 2000)}
              </pre>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

export default WorkflowEventMessage
