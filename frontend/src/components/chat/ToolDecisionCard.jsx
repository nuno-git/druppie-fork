/**
 * ToolDecisionCard - Renders a tool call decision with all embedded data
 *
 * This component uses the unified ToolCallDecision schema from the backend:
 * - name, arguments: The tool call itself
 * - is_hitl_question, hitl_question: HITL question data if applicable
 * - approval_required, approval: Approval data if applicable
 * - executed, execution_status, execution_result: Execution results
 * - is_done_tool: Whether this is the final done() call
 */

import React, { useState } from 'react'
import {
  ChevronDown,
  ChevronRight,
  CheckCircle,
  XCircle,
  Clock,
  Hammer,
  Shield,
  FileCode,
  Terminal,
  GitBranch,
  MessageCircle,
  Check,
  X,
  Loader2,
  ExternalLink,
  Rocket,
  Package,
} from 'lucide-react'
import { getAgentConfig, getAgentMessageColors } from '../../utils/agentConfig'

// Helper to get tool icon
const getToolIcon = (toolName) => {
  if (!toolName) return Hammer
  if (toolName.includes('docker_run') || toolName.includes('docker:run')) return Rocket
  if (toolName.includes('docker_build') || toolName.includes('docker:build')) return Package
  if (toolName.includes('write_file') || toolName.includes('batch_write')) return FileCode
  if (toolName.includes('run_command') || toolName.includes('run_tests')) return Terminal
  if (toolName.includes('commit') || toolName.includes('git')) return GitBranch
  if (toolName.includes('hitl') || toolName.includes('ask')) return MessageCircle
  return Hammer
}

// Helper to extract deployment URL from docker_run args
const getDeploymentUrl = (toolName, args) => {
  if (!toolName || !args) return null
  if (!toolName.includes('docker_run') && !toolName.includes('docker:run')) return null

  // Extract port mapping to build URL
  const portMapping = args.port_mapping || args.portMapping
  if (portMapping) {
    const hostPort = portMapping.split(':')[0]
    return `http://localhost:${hostPort}`
  }

  // Fallback to container_port
  const containerPort = args.container_port || args.containerPort || 8080
  return `http://localhost:${containerPort}`
}

const ToolDecisionCard = ({
  item,
  onApprove,
  onReject,
  onAnswerQuestion,
  isProcessing,
  isAnswering,
  userRoles = [],
}) => {
  const [expanded, setExpanded] = useState(true)
  const [rejectReason, setRejectReason] = useState('')
  const [showRejectInput, setShowRejectInput] = useState(false)
  const [answer, setAnswer] = useState('')

  const { toolDecision, agent_id, timestamp } = item
  const {
    name: toolName,
    arguments: args,
    is_hitl_question,
    hitl_question,
    approval_required,
    approval,
    executed,
    execution_status,
    execution_result,
    execution_error,
    is_done_tool,
  } = toolDecision

  const agentConfig = agent_id ? getAgentConfig(agent_id) : null
  const colors = agentConfig ? getAgentMessageColors(agentConfig.color) : null
  const AgentIcon = agentConfig?.icon || Clock
  const ToolIcon = getToolIcon(toolName)

  const formatTimestamp = (ts) => ts ? new Date(ts).toLocaleTimeString() : ''

  // Filter internal params from display
  const filterArgs = (params) => {
    if (!params || typeof params !== 'object') return {}
    const filtered = {}
    Object.entries(params).forEach(([key, value]) => {
      if (['workspace_id', 'project_id', 'workspace_path', 'session_id'].includes(key)) return
      filtered[key] = value
    })
    return filtered
  }

  const displayArgs = filterArgs(args)
  const hasDisplayableArgs = Object.keys(displayArgs).length > 0

  // Check if user can approve
  const canApprove = approval && approval.status === 'pending' && (
    userRoles.includes('admin') ||
    (approval.required_roles || []).some(role => userRoles.includes(role))
  )

  // ==========================================================================
  // HITL Question Rendering
  // ==========================================================================
  if (is_hitl_question && hitl_question) {
    const isAnswered = hitl_question.status === 'answered'
    const choices = hitl_question.choices || []
    const hasChoices = choices.length > 0

    const handleSubmitAnswer = () => {
      if (answer.trim() && onAnswerQuestion) {
        onAnswerQuestion(hitl_question.id, answer.trim())
      }
    }

    const handleChoiceSelect = (choiceText) => {
      if (onAnswerQuestion) {
        onAnswerQuestion(hitl_question.id, choiceText, choiceText)
      }
    }

    return (
      <div className="flex justify-start mb-3">
        <div className={`max-w-[95%] rounded-xl px-4 py-3 border-2 ${isAnswered ? 'bg-green-50 border-green-200' : 'bg-amber-50 border-amber-300'}`}>
          {/* Header */}
          <div className="flex items-center gap-2 mb-2">
            {agentConfig && (
              <div className={`w-7 h-7 rounded-full flex items-center justify-center ${colors?.bg || 'bg-gray-100'} border-2 ${colors?.border || 'border-gray-200'}`}>
                <AgentIcon className={`w-4 h-4 ${colors?.accent || 'text-gray-600'}`} />
              </div>
            )}
            <MessageCircle className={`w-5 h-5 ${isAnswered ? 'text-green-500' : 'text-amber-500'}`} />
            <span className="text-sm font-semibold text-gray-800">
              {agentConfig?.name || agent_id || 'Agent'} asked:
            </span>
            <span className={`text-xs font-bold px-2 py-0.5 rounded-full ${isAnswered ? 'bg-green-100 text-green-700' : 'bg-amber-100 text-amber-800'}`}>
              {isAnswered ? 'ANSWERED' : 'WAITING'}
            </span>
            {timestamp && (
              <span className="text-xs text-gray-400 ml-auto">{formatTimestamp(timestamp)}</span>
            )}
          </div>

          {/* Question */}
          <div className="ml-9 text-sm text-gray-700 mb-3 whitespace-pre-wrap">
            {hitl_question.question}
          </div>

          {/* Answer input or display */}
          {isAnswered ? (
            <div className="ml-9 mt-2 p-2 bg-green-100 rounded-lg border border-green-200">
              <span className="text-xs text-green-600 font-semibold">Your answer:</span>
              <div className="text-sm text-green-800">{hitl_question.answer}</div>
            </div>
          ) : hasChoices ? (
            <div className="ml-9 space-y-2">
              {choices.map((choice, idx) => (
                <button
                  key={idx}
                  onClick={() => handleChoiceSelect(choice.text)}
                  disabled={isAnswering}
                  className="w-full text-left px-3 py-2 bg-white border border-gray-200 rounded-lg hover:bg-amber-50 hover:border-amber-300 transition-colors disabled:opacity-50"
                >
                  {choice.text}
                </button>
              ))}
            </div>
          ) : (
            <div className="ml-9">
              <textarea
                value={answer}
                onChange={(e) => setAnswer(e.target.value)}
                placeholder="Type your answer..."
                className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm resize-none focus:ring-2 focus:ring-amber-500 focus:border-transparent"
                rows={2}
                disabled={isAnswering}
              />
              <button
                onClick={handleSubmitAnswer}
                disabled={!answer.trim() || isAnswering}
                className="mt-2 px-4 py-1.5 bg-amber-500 text-white rounded-lg text-sm font-medium hover:bg-amber-600 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {isAnswering ? 'Submitting...' : 'Submit Answer'}
              </button>
            </div>
          )}
        </div>
      </div>
    )
  }

  // ==========================================================================
  // Done Tool (Agent Completion) - Skip, handled by agent_completed
  // ==========================================================================
  if (is_done_tool) {
    return null // Rendered by agent_completed type
  }

  // ==========================================================================
  // Tool Call with Approval
  // ==========================================================================
  const approvalStatus = approval?.status
  const isPending = approvalStatus === 'pending'
  const isApproved = approvalStatus === 'approved'
  const isRejected = approvalStatus === 'rejected'

  // Check if this is a docker_run tool and get deployment URL
  const isDockerRun = toolName && (toolName.includes('docker_run') || toolName.includes('docker:run'))
  const deploymentUrl = getDeploymentUrl(toolName, args)

  // Determine colors based on status
  let bgColor = 'bg-purple-50'
  let borderColor = 'border-purple-200'
  let badge = 'TOOL CALL'
  let badgeColor = 'bg-purple-100 text-purple-700'

  if (approval_required) {
    if (isPending) {
      bgColor = 'bg-amber-50'
      borderColor = 'border-amber-300'
      badge = 'AWAITING APPROVAL'
      badgeColor = 'bg-amber-100 text-amber-800 animate-pulse'
    } else if (isApproved) {
      bgColor = 'bg-green-50'
      borderColor = 'border-green-200'
      badge = `APPROVED${approval.resolved_by_username ? ` by ${approval.resolved_by_username}` : ''}`
      badgeColor = 'bg-green-100 text-green-700'
    } else if (isRejected) {
      bgColor = 'bg-red-50'
      borderColor = 'border-red-200'
      badge = 'REJECTED'
      badgeColor = 'bg-red-100 text-red-700'
    }
  } else if (executed) {
    if (execution_status === 'completed') {
      bgColor = 'bg-green-50'
      borderColor = 'border-green-200'
      badge = 'COMPLETED'
      badgeColor = 'bg-green-100 text-green-700'
    } else if (execution_status === 'failed') {
      bgColor = 'bg-red-50'
      borderColor = 'border-red-200'
      badge = 'FAILED'
      badgeColor = 'bg-red-100 text-red-700'
    }
  }

  const handleApprove = () => {
    if (approval && onApprove) {
      onApprove(approval.id)
    }
  }

  const handleReject = () => {
    if (approval && onReject) {
      onReject(approval.id, rejectReason || 'Rejected by user')
      setShowRejectInput(false)
      setRejectReason('')
    }
  }

  return (
    <div className="flex justify-start mb-3">
      <div className={`max-w-[95%] rounded-xl px-4 py-3 border-2 ${bgColor} ${borderColor} shadow-sm`}>
        {/* Header */}
        <div className="flex items-center gap-2 flex-wrap">
          {agentConfig && (
            <div className={`w-7 h-7 rounded-full flex items-center justify-center ${colors?.bg || 'bg-gray-100'} border-2 ${colors?.border || 'border-gray-200'}`}>
              <AgentIcon className={`w-4 h-4 ${colors?.accent || 'text-gray-600'}`} />
            </div>
          )}
          <ToolIcon className={`w-5 h-5 ${colors?.accent || 'text-purple-600'}`} />
          {isPending && <Loader2 className="w-4 h-4 text-amber-500 animate-spin" />}
          <span className="text-sm font-semibold text-gray-800">Tool: {toolName}</span>
          <span className={`text-xs font-bold px-2 py-0.5 rounded-full ${badgeColor}`}>
            {badge}
          </span>
          {timestamp && (
            <span className="text-xs text-gray-400 ml-auto">{formatTimestamp(timestamp)}</span>
          )}
          {hasDisplayableArgs && (
            <button
              onClick={() => setExpanded(!expanded)}
              className="ml-1 p-1 text-gray-400 hover:text-gray-600 hover:bg-gray-200 rounded transition-colors"
            >
              {expanded ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
            </button>
          )}
        </div>

        {/* Subtitle */}
        <div className="text-xs text-gray-500 mt-1 ml-9">
          Called by {agentConfig?.name || agent_id || 'Agent'}
          {approval_required && isPending && ` • Requires ${(approval.required_roles || ['admin']).join(' or ')} approval`}
        </div>

        {/* Arguments */}
        {expanded && hasDisplayableArgs && (
          <div className="mt-3 pt-3 border-t border-gray-200">
            <div className="text-xs font-semibold text-gray-600 mb-2">Arguments:</div>
            <div className="bg-white rounded-lg border border-gray-200 p-3 text-xs font-mono overflow-x-auto max-h-64 overflow-y-auto">
              {Object.entries(displayArgs).map(([key, value]) => (
                <div key={key} className="mb-2 last:mb-0">
                  <div className="flex items-start gap-2">
                    <span className="text-purple-600 font-semibold min-w-[80px]">{key}:</span>
                    <span className="text-gray-800 break-all whitespace-pre-wrap flex-1">
                      {typeof value === 'string' && value.length > 300 ? (
                        <details className="cursor-pointer">
                          <summary className="text-blue-600 hover:underline">
                            {value.substring(0, 150)}... (click to expand)
                          </summary>
                          <div className="mt-2 p-2 bg-gray-50 rounded border max-h-48 overflow-y-auto">
                            {value}
                          </div>
                        </details>
                      ) : typeof value === 'object' ? (
                        <pre className="bg-gray-50 p-2 rounded border overflow-x-auto">
                          {JSON.stringify(value, null, 2)}
                        </pre>
                      ) : String(value)}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Execution result - collapsible, hide for docker_run success since we show deployment card */}
        {executed && execution_result && !(isDockerRun && !execution_error) && (
          <details className="mt-3 pt-3 border-t border-gray-200">
            <summary className={`text-xs font-semibold cursor-pointer select-none flex items-center gap-1 ${execution_error ? 'text-red-600' : 'text-green-600'}`}>
              <ChevronRight className="w-3 h-3 transform transition-transform details-open:rotate-90" />
              {execution_error ? 'Error' : 'Result'}: {execution_result.length > 50 ? execution_result.substring(0, 50) + '...' : execution_result.substring(0, 50)}
            </summary>
            <div className={`mt-2 bg-white rounded-lg border p-3 text-xs overflow-x-auto max-h-48 overflow-y-auto ${execution_error ? 'border-red-200' : 'border-gray-200'}`}>
              <pre className={`whitespace-pre-wrap break-all ${execution_error ? 'text-red-700' : 'text-gray-700'}`}>
                {execution_result}
              </pre>
            </div>
          </details>
        )}

        {/* Deployment success card for docker_run */}
        {isDockerRun && (isApproved || executed) && !execution_error && deploymentUrl && (
          <div className="mt-3 pt-3 border-t border-green-200">
            <div className="bg-gradient-to-r from-green-50 to-emerald-50 rounded-lg border border-green-200 p-4">
              <div className="flex items-center gap-2 mb-2">
                <Rocket className="w-5 h-5 text-green-600" />
                <span className="text-sm font-bold text-green-800">Deployment Successful!</span>
              </div>
              <div className="text-xs text-gray-600 mb-3">
                Container: <span className="font-mono font-semibold">{args.container_name || args.containerName || 'app'}</span>
              </div>
              <a
                href={deploymentUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-2 px-4 py-2 bg-green-600 text-white rounded-lg text-sm font-medium hover:bg-green-700 transition-colors shadow-sm"
              >
                <ExternalLink className="w-4 h-4" />
                Open Application
              </a>
              <div className="mt-2 text-xs text-gray-500">
                {deploymentUrl}
              </div>
            </div>
          </div>
        )}

        {/* Rejection reason */}
        {isRejected && approval.rejection_reason && (
          <div className="mt-3 pt-3 border-t border-red-200">
            <div className="text-xs font-semibold text-red-600 mb-1">Rejection reason:</div>
            <div className="text-sm text-red-700">{approval.rejection_reason}</div>
          </div>
        )}

        {/* Approval buttons */}
        {approval_required && isPending && canApprove && (
          <div className="mt-4 pt-3 border-t border-amber-200">
            {!showRejectInput ? (
              <div className="flex gap-2">
                <button
                  onClick={handleApprove}
                  disabled={isProcessing}
                  className="flex items-center gap-1 px-4 py-2 bg-green-500 text-white rounded-lg text-sm font-medium hover:bg-green-600 disabled:opacity-50"
                >
                  <Check className="w-4 h-4" />
                  Approve
                </button>
                <button
                  onClick={() => setShowRejectInput(true)}
                  disabled={isProcessing}
                  className="flex items-center gap-1 px-4 py-2 bg-red-500 text-white rounded-lg text-sm font-medium hover:bg-red-600 disabled:opacity-50"
                >
                  <X className="w-4 h-4" />
                  Reject
                </button>
              </div>
            ) : (
              <div className="space-y-2">
                <input
                  type="text"
                  value={rejectReason}
                  onChange={(e) => setRejectReason(e.target.value)}
                  placeholder="Rejection reason (optional)"
                  className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm"
                />
                <div className="flex gap-2">
                  <button
                    onClick={handleReject}
                    disabled={isProcessing}
                    className="px-4 py-2 bg-red-500 text-white rounded-lg text-sm font-medium hover:bg-red-600 disabled:opacity-50"
                  >
                    Confirm Reject
                  </button>
                  <button
                    onClick={() => setShowRejectInput(false)}
                    className="px-4 py-2 bg-gray-200 text-gray-700 rounded-lg text-sm font-medium hover:bg-gray-300"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            )}
          </div>
        )}

        {/* No permission message */}
        {approval_required && isPending && !canApprove && (
          <div className="mt-3 pt-3 border-t border-amber-200">
            <div className="text-xs text-amber-700 bg-amber-100 rounded-lg px-3 py-2">
              Waiting for approval from: {(approval.required_roles || ['admin']).join(' or ')}
              <br />
              <span className="text-amber-600">You don't have the required role to approve this action.</span>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

export default ToolDecisionCard
