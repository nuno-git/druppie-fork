/**
 * WorkflowEventMessage - Displays workflow events as chat messages
 * Shows agent start/complete, tool calls, and approvals inline in the chat
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
} from 'lucide-react'
import { getAgentConfig, getAgentMessageColors } from '../../utils/agentConfig'

const WorkflowEventMessage = ({ event }) => {
  const [expanded, setExpanded] = useState(false)

  const eventType = event.type || event.event_type || ''
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
        icon: Play,
        iconColor: 'text-blue-500',
        bgColor: colors?.bg || 'bg-blue-50',
        borderColor: colors?.border || 'border-blue-200',
        showExpand: false,
        isWorking: true,
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
      }
    }

    if (eventType.includes('tool_call') || eventType === 'mcp_tool_call') {
      const toolName = event.tool || event.data?.tool || event.data?.tool_name
      const args = event.args || event.data?.args || event.data?.arguments || {}
      return {
        title: `${agentConfig?.name || agentId || 'Agent'} used ${toolName}`,
        icon: Hammer,
        iconColor: colors?.accent || 'text-gray-600',
        bgColor: colors?.bg || 'bg-gray-50',
        borderColor: colors?.border || 'border-gray-200',
        showExpand: Object.keys(args).length > 0,
        args: args,
        toolName: toolName,
      }
    }

    if (eventType.includes('tool_result') || eventType === 'mcp_tool_result') {
      const success = event.data?.success !== false
      return {
        title: success ? 'Tool completed successfully' : 'Tool execution failed',
        icon: success ? CheckCircle : XCircle,
        iconColor: success ? 'text-green-500' : 'text-red-500',
        bgColor: success ? 'bg-green-50' : 'bg-red-50',
        borderColor: success ? 'border-green-200' : 'border-red-200',
        showExpand: !!(event.data?.result || event.data?.error),
        content: event.data?.result || event.data?.error,
        isError: !success,
      }
    }

    if (eventType.includes('approval_required') || eventType === 'approval_pending') {
      return {
        title: `Approval required: ${event.data?.tool || event.tool || 'action'}`,
        icon: Clock,
        iconColor: 'text-amber-500 animate-pulse',
        bgColor: 'bg-amber-50',
        borderColor: 'border-amber-200',
        showExpand: !!(event.data?.args || event.args),
        args: event.data?.args || event.args,
      }
    }

    if (eventType.includes('approval_granted') || eventType === 'approved') {
      return {
        title: `Approved by ${event.data?.approver || event.approver || 'user'}`,
        icon: CheckCircle,
        iconColor: 'text-green-500',
        bgColor: 'bg-green-50',
        borderColor: 'border-green-200',
        showExpand: false,
      }
    }

    if (eventType.includes('approval_rejected') || eventType === 'rejected') {
      return {
        title: `Rejected by ${event.data?.approver || event.approver || 'user'}`,
        icon: XCircle,
        iconColor: 'text-red-500',
        bgColor: 'bg-red-50',
        borderColor: 'border-red-200',
        showExpand: !!(event.data?.reason),
        content: event.data?.reason,
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

  return (
    <div className="flex justify-start mb-2">
      <div className={`max-w-[90%] rounded-xl px-3 py-2 border ${display.bgColor} ${display.borderColor}`}>
        <div className="flex items-center gap-2">
          {/* Agent icon */}
          {agentConfig && (
            <div className={`w-6 h-6 rounded-full flex items-center justify-center flex-shrink-0 ${colors?.bg || 'bg-gray-100'} border ${colors?.border || 'border-gray-200'}`}>
              <AgentIcon className={`w-3.5 h-3.5 ${colors?.accent || 'text-gray-600'}`} />
            </div>
          )}

          {/* Status icon */}
          <StatusIcon className={`w-4 h-4 ${display.iconColor} flex-shrink-0`} />

          {/* Working spinner for agent_started */}
          {display.isWorking && (
            <Loader2 className="w-4 h-4 text-blue-500 animate-spin flex-shrink-0" />
          )}

          {/* Title */}
          <span className="text-sm text-gray-700 font-medium">{display.title}</span>

          {/* Timestamp */}
          {timestamp && (
            <span className="text-xs text-gray-400 ml-auto">{timestamp}</span>
          )}

          {/* Expand button */}
          {display.showExpand && (
            <button
              onClick={() => setExpanded(!expanded)}
              className="ml-1 p-0.5 text-gray-400 hover:text-gray-600 rounded"
            >
              {expanded ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
            </button>
          )}
        </div>

        {/* Expanded content */}
        {expanded && display.showExpand && (
          <div className="mt-2 pt-2 border-t border-gray-200">
            {/* Tool arguments */}
            {displayArgs && Object.keys(displayArgs).length > 0 && (
              <div className="bg-white rounded-lg border border-gray-200 p-2 text-xs font-mono overflow-x-auto max-h-48 overflow-y-auto">
                {Object.entries(displayArgs).map(([key, value]) => (
                  <div key={key} className="mb-1 last:mb-0">
                    <span className="text-purple-600">{key}</span>
                    <span className="text-gray-500">: </span>
                    <span className="text-gray-800 break-all whitespace-pre-wrap">
                      {typeof value === 'string' && value.length > 500
                        ? `${value.substring(0, 500)}...`
                        : typeof value === 'object'
                          ? JSON.stringify(value, null, 2)
                          : String(value)}
                    </span>
                  </div>
                ))}
              </div>
            )}

            {/* Result/output content */}
            {display.content && (
              <div className={`bg-white rounded-lg border p-2 text-xs overflow-x-auto max-h-48 overflow-y-auto ${display.isError ? 'border-red-200' : 'border-gray-200'}`}>
                <pre className={`whitespace-pre-wrap break-all ${display.isError ? 'text-red-700' : 'text-gray-700'}`}>
                  {typeof display.content === 'object'
                    ? JSON.stringify(display.content, null, 2)
                    : String(display.content).substring(0, 1000)}
                </pre>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

export default WorkflowEventMessage
