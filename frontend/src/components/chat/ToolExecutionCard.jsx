/**
 * ToolExecutionCard - Displays tool execution with approval status
 * Shows agent info, tool details, parameters (expanded by default), and approval status
 * Enhanced with clearer status badges and tool-specific icons
 */

import React, { useState } from 'react'
import {
  ChevronDown,
  ChevronRight,
  Clock,
  CheckCircle,
  XCircle,
  Hammer,
  Code,
  FileCode,
  Terminal,
  GitBranch,
  Shield,
} from 'lucide-react'
import { getAgentConfig, getAgentMessageColors } from '../../utils/agentConfig'

// Get icon based on tool type
const getToolIcon = (toolName) => {
  if (!toolName) return Hammer
  if (toolName.includes('write_file') || toolName.includes('batch_write')) return FileCode
  if (toolName.includes('run_command') || toolName.includes('run_tests')) return Terminal
  if (toolName.includes('commit') || toolName.includes('git')) return GitBranch
  return Hammer
}

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
  // Show parameters expanded by default for better visibility
  const [expanded, setExpanded] = useState(true)

  // Get agent configuration and colors
  const agentConfig = getAgentConfig(agentId || 'developer')
  const AgentIcon = agentConfig.icon
  const colors = getAgentMessageColors(agentConfig.color)

  // Parse tool name to get server and tool parts
  const [server, tool] = toolName?.includes(':') ? toolName.split(':') : ['mcp', toolName]

  // Get appropriate tool icon
  const ToolIcon = getToolIcon(toolName)

  // Format parameters for display
  const paramEntries = Object.entries(parameters || {}).filter(
    ([key]) => !['workspace_id', 'project_id', 'workspace_path', 'session_id'].includes(key)
  )

  // Get status icon and colors
  const getStatusDisplay = () => {
    switch (status) {
      case 'approved':
        return {
          icon: CheckCircle,
          text: `✅ Approved by ${approverUsername || 'user'}`,
          subtext: approvedAt ? new Date(approvedAt).toLocaleString() : null,
          bgColor: 'bg-green-50 border-green-300',
          textColor: 'text-green-800',
          iconColor: 'text-green-500',
          badge: 'APPROVED',
          badgeColor: 'bg-green-100 text-green-700',
        }
      case 'rejected':
        return {
          icon: XCircle,
          text: `🚫 Rejected by ${approverUsername || 'user'}`,
          subtext: rejectionReason || null,
          bgColor: 'bg-red-50 border-red-300',
          textColor: 'text-red-800',
          iconColor: 'text-red-500',
          badge: 'REJECTED',
          badgeColor: 'bg-red-100 text-red-700',
        }
      default:
        return {
          icon: Clock,
          text: '⏳ Waiting for approval',
          subtext: null,
          bgColor: 'bg-amber-50 border-amber-300',
          textColor: 'text-amber-800',
          iconColor: 'text-amber-500 animate-pulse',
          badge: 'PENDING',
          badgeColor: 'bg-amber-100 text-amber-700 animate-pulse',
        }
    }
  }

  const statusDisplay = getStatusDisplay()
  const StatusIcon = statusDisplay.icon

  return (
    <div className="flex justify-start mb-4">
      <div className={`max-w-[90%] rounded-2xl px-4 py-3 rounded-bl-none shadow-sm border-2 ${colors.bg} ${colors.border}`}>
        <div className="flex items-start space-x-3">
          {/* Agent Icon */}
          <div className={`w-9 h-9 rounded-full flex items-center justify-center flex-shrink-0 ${colors.bg} border-2 ${colors.border}`}>
            <AgentIcon className={`w-5 h-5 ${colors.accent}`} />
          </div>

          <div className="flex-1 min-w-0">
            {/* Header with agent name and status badge */}
            <div className="flex items-center justify-between mb-2 flex-wrap gap-2">
              <div className={`text-xs font-semibold ${colors.accent} flex items-center gap-2`}>
                <span>{agentConfig.name} Agent</span>
                <Shield className="w-3 h-3" />
                <span className="font-normal text-gray-500">Tool Execution</span>
              </div>
              <span className={`text-xs font-bold px-2 py-0.5 rounded-full ${statusDisplay.badgeColor}`}>
                {statusDisplay.badge}
              </span>
            </div>

            {/* Tool Name with icon */}
            <div className="flex items-center gap-2 mb-3 px-3 py-2 bg-white rounded-lg border border-gray-200">
              <ToolIcon className="w-5 h-5 text-purple-600" />
              <span className="font-mono text-sm font-medium text-gray-800">
                <span className="text-gray-500">{server}:</span>
                <span className="text-purple-700 font-bold">{tool}</span>
              </span>
            </div>

            {/* Parameters - Collapsible */}
            {paramEntries.length > 0 && (
              <div className="mb-3">
                <button
                  onClick={() => setExpanded(!expanded)}
                  className="flex items-center gap-1 text-xs text-gray-600 hover:text-gray-800 transition-colors focus:outline-none"
                >
                  {expanded ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
                  <Code className="w-3 h-3" />
                  {expanded ? 'Hide' : 'Show'} arguments ({paramEntries.length})
                </button>

                {expanded && (
                  <div className="mt-2 bg-white rounded-lg border border-gray-200 p-3 text-xs font-mono overflow-x-auto max-h-64 overflow-y-auto">
                    {paramEntries.map(([key, value]) => (
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
                )}
              </div>
            )}

            {/* Status Box */}
            <div className={`rounded-lg border-2 px-3 py-2 ${statusDisplay.bgColor}`}>
              <div className="flex items-center gap-2 flex-wrap">
                <StatusIcon className={`w-5 h-5 ${statusDisplay.iconColor}`} />
                <span className={`text-sm font-semibold ${statusDisplay.textColor}`}>
                  {statusDisplay.text}
                </span>
                {approverRole && status !== 'pending' && (
                  <span className={`text-xs px-2 py-0.5 rounded-full border ${
                    status === 'approved' ? 'bg-green-100 border-green-300 text-green-700' :
                    status === 'rejected' ? 'bg-red-100 border-red-300 text-red-700' :
                    'bg-amber-100 border-amber-300 text-amber-700'
                  }`}>
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
