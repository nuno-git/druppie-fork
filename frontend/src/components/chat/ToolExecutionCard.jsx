/**
 * ToolExecutionCard - Displays tool execution with approval status
 * Shows agent info, tool details, parameters (collapsible), and approval status
 */

import React, { useState } from 'react'
import { ChevronDown, ChevronRight, Clock, CheckCircle, XCircle, Hammer, Code } from 'lucide-react'
import { getAgentConfig, getAgentMessageColors } from '../../utils/agentConfig'

const ToolExecutionCard = ({
  agentId,
  toolName,
  parameters = {},
  status = 'pending', // 'pending' | 'approved' | 'rejected'
  approverUsername,
  approverRole,
  approvedAt,
  rejectionReason,
}) => {
  const [expanded, setExpanded] = useState(false)

  // Get agent configuration and colors
  const agentConfig = getAgentConfig(agentId || 'developer')
  const AgentIcon = agentConfig.icon
  const colors = getAgentMessageColors(agentConfig.color)

  // Parse tool name to get server and tool parts
  const [server, tool] = toolName?.includes(':') ? toolName.split(':') : ['mcp', toolName]

  // Format parameters for display
  const paramEntries = Object.entries(parameters || {}).filter(
    ([key]) => !['workspace_id', 'project_id', 'workspace_path'].includes(key)
  )

  // Get status icon and colors
  const getStatusDisplay = () => {
    switch (status) {
      case 'approved':
        return {
          icon: CheckCircle,
          text: `Approved by ${approverUsername || 'user'}`,
          subtext: approvedAt ? new Date(approvedAt).toLocaleString() : null,
          bgColor: 'bg-green-50 border-green-200',
          textColor: 'text-green-700',
          iconColor: 'text-green-500',
        }
      case 'rejected':
        return {
          icon: XCircle,
          text: `Rejected by ${approverUsername || 'user'}`,
          subtext: rejectionReason || null,
          bgColor: 'bg-red-50 border-red-200',
          textColor: 'text-red-700',
          iconColor: 'text-red-500',
        }
      default:
        return {
          icon: Clock,
          text: 'Waiting for approval',
          subtext: null,
          bgColor: 'bg-amber-50 border-amber-200',
          textColor: 'text-amber-700',
          iconColor: 'text-amber-500 animate-pulse',
        }
    }
  }

  const statusDisplay = getStatusDisplay()
  const StatusIcon = statusDisplay.icon

  return (
    <div className="flex justify-start mb-4">
      <div className={`max-w-[85%] rounded-2xl px-4 py-3 rounded-bl-none shadow-sm border ${colors.bg} ${colors.border}`}>
        <div className="flex items-start space-x-3">
          {/* Agent Icon */}
          <div className={`w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0 ${colors.bg} border ${colors.border}`}>
            <AgentIcon className={`w-5 h-5 ${colors.accent}`} />
          </div>

          <div className="flex-1 min-w-0">
            {/* Agent Name Header - same style as HITL */}
            <div className={`text-xs font-semibold mb-2 ${colors.accent} flex items-center gap-2`}>
              <span>{agentConfig.name} Agent</span>
              <Hammer className="w-3 h-3" />
              <span className="font-normal text-gray-500">used tool:</span>
            </div>

          {/* Tool Name */}
          <div className="flex items-center gap-2 mb-2">
            <Code className={`w-4 h-4 ${colors.accent}`} />
            <span className={`font-mono text-sm font-medium ${colors.text}`}>
              {server}:<span className="font-bold">{tool}</span>
            </span>
          </div>

          {/* Parameters - Collapsible */}
          {paramEntries.length > 0 && (
            <div className="mb-3">
              <button
                onClick={() => setExpanded(!expanded)}
                className={`flex items-center gap-1 text-xs ${colors.accent} hover:underline focus:outline-none`}
              >
                {expanded ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
                {expanded ? 'Hide' : 'Show'} parameters ({paramEntries.length})
              </button>

              {expanded && (
                <div className="mt-2 bg-white rounded-lg border border-gray-200 p-3 text-xs font-mono overflow-x-auto max-h-48 overflow-y-auto">
                  {paramEntries.map(([key, value]) => (
                    <div key={key} className="mb-1 last:mb-0">
                      <span className="text-purple-600">{key}</span>
                      <span className="text-gray-500">: </span>
                      <span className="text-gray-800 break-all">
                        {typeof value === 'string' && value.length > 200
                          ? `${value.substring(0, 200)}...`
                          : typeof value === 'object'
                            ? JSON.stringify(value, null, 2)
                            : String(value)}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Status Box */}
          <div className={`rounded-lg border px-3 py-2 ${statusDisplay.bgColor}`}>
            <div className="flex items-center gap-2">
              <StatusIcon className={`w-4 h-4 ${statusDisplay.iconColor}`} />
              <span className={`text-sm font-medium ${statusDisplay.textColor}`}>
                {statusDisplay.text}
              </span>
              {approverRole && status !== 'pending' && (
                <span className={`text-xs px-2 py-0.5 rounded-full ${statusDisplay.bgColor} ${statusDisplay.textColor}`}>
                  {approverRole}
                </span>
              )}
            </div>
            {statusDisplay.subtext && (
              <div className={`text-xs mt-1 ${statusDisplay.textColor} opacity-80`}>
                {statusDisplay.subtext}
              </div>
            )}
          </div>
        </div>
        </div>
      </div>
    </div>
  )
}

export default ToolExecutionCard
