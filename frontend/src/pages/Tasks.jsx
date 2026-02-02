/**
 * Tasks (Approvals) Page
 */

import React, { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { CheckCircle, XCircle, Clock, Shield, AlertTriangle, AlertCircle, Loader2, MessageSquare, Bot, ExternalLink, ChevronDown, ChevronRight, History, User, FileCode, FilePlus, Terminal, GitBranch, Code } from 'lucide-react'
import { getTasks, approveTask, rejectTask, getApprovalHistory } from '../services/api'
import { useAuth } from '../App'
import { hasRole } from '../services/keycloak'
import { useToast } from '../components/Toast'

// Helper to get human-readable tool description
const getToolDescription = (toolName) => {
  const toolDescriptions = {
    'run_command': 'Execute a shell command in the workspace',
    'coding:run_command': 'Execute a shell command in the workspace',
    'write_file': 'Write content to a file in the workspace',
    'coding:write_file': 'Write content to a file in the workspace',
    'delete_file': 'Delete a file from the workspace',
    'coding:delete_file': 'Delete a file from the workspace',
    'commit_and_push': 'Commit changes and push to Git repository',
    'coding:commit_and_push': 'Commit changes and push to Git repository',
    'merge_to_main': 'Merge current branch to main branch',
    'coding:merge_to_main': 'Merge current branch to main branch',
    'build': 'Build a Docker image',
    'docker:build': 'Build a Docker image',
    'run': 'Run a Docker container',
    'docker:run': 'Run a Docker container',
    'stop': 'Stop a running Docker container',
    'docker:stop': 'Stop a running Docker container',
    'remove': 'Remove a Docker container',
    'docker:remove': 'Remove a Docker container',
    'exec_command': 'Execute command inside a Docker container',
    'docker:exec_command': 'Execute command inside a Docker container',
  }
  return toolDescriptions[toolName] || `Execute ${toolName}`
}

// Helper to get danger level badge
const getDangerLevelBadge = (level) => {
  const levels = {
    low: { bg: 'bg-green-100', text: 'text-green-700', label: 'Low Risk' },
    medium: { bg: 'bg-yellow-100', text: 'text-yellow-700', label: 'Medium Risk' },
    high: { bg: 'bg-orange-100', text: 'text-orange-700', label: 'High Risk' },
    critical: { bg: 'bg-red-100', text: 'text-red-700', label: 'Critical' },
  }
  return levels[level] || levels.low
}

// Helper to detect language from file path for syntax highlighting hint
const getLanguageFromPath = (path) => {
  if (!path) return 'text'
  const ext = path.split('.').pop()?.toLowerCase()
  const langMap = {
    js: 'javascript', jsx: 'javascript', ts: 'typescript', tsx: 'typescript',
    py: 'python', rb: 'ruby', go: 'go', rs: 'rust', java: 'java',
    c: 'c', cpp: 'cpp', h: 'c', hpp: 'cpp', cs: 'csharp', php: 'php',
    swift: 'swift', kt: 'kotlin', scala: 'scala', sh: 'bash', bash: 'bash',
    yml: 'yaml', yaml: 'yaml', json: 'json', xml: 'xml', html: 'html',
    css: 'css', scss: 'scss', sql: 'sql', md: 'markdown', dockerfile: 'dockerfile',
  }
  return langMap[ext] || 'text'
}

// Helper to get tool icon and label
const getToolInfo = (toolName) => {
  const tools = {
    'write_file': { icon: FilePlus, label: 'Write File', color: 'text-blue-600' },
    'coding:write_file': { icon: FilePlus, label: 'Write File', color: 'text-blue-600' },
    'batch_write_files': { icon: FileCode, label: 'Write Files', color: 'text-blue-600' },
    'coding:batch_write_files': { icon: FileCode, label: 'Write Files', color: 'text-blue-600' },
    'run_command': { icon: Terminal, label: 'Run Command', color: 'text-orange-600' },
    'coding:run_command': { icon: Terminal, label: 'Run Command', color: 'text-orange-600' },
    'commit_and_push': { icon: GitBranch, label: 'Git Commit', color: 'text-green-600' },
    'coding:commit_and_push': { icon: GitBranch, label: 'Git Commit', color: 'text-green-600' },
  }
  return tools[toolName] || { icon: Code, label: toolName?.split(':').pop() || 'Tool', color: 'text-gray-600' }
}

// Helper to format agent display name
const formatAgentName = (agentId) => {
  if (!agentId) return null
  // Remove common suffixes like '_agent' and format nicely
  return agentId
    .replace(/_agent$/i, '')
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase())
}

const TaskCard = ({ task, onApprove, onReject }) => {
  const [rejectReason, setRejectReason] = useState('')
  const [showReject, setShowReject] = useState(false)
  const [showDetails, setShowDetails] = useState(false)
  const [showCodePreview, setShowCodePreview] = useState(false)
  const { user } = useAuth()

  // Extract arguments for content preview
  const args = task.mcp_arguments || task.arguments || {}
  const filePath = args.path || args.file_path
  const newContent = args.content
  const batchFiles = args.files
  const command = args.command
  const commitMessage = args.message || args.commit_message
  const isBatchWrite = !!batchFiles && Object.keys(batchFiles).length > 0

  // Normalize: derive required_role from required_roles array if not present
  const requiredRoles = task.required_roles || (task.required_role ? [task.required_role] : ['admin'])
  const requiredRole = task.required_role || (requiredRoles.length > 0 ? requiredRoles[0] : 'admin')

  // Check if user has any of the required roles
  const canApprove = requiredRoles.some(role => hasRole(role))

  // MULTI approval state
  const isMultiApproval = task.approval_type === 'multi'
  const requiredApprovals = task.required_approvals || 2
  const currentApprovals = task.current_approvals || 0
  const approvedByRoles = task.approved_by_roles || []
  const remainingRoles = requiredRoles.filter(role => !approvedByRoles.includes(role))

  // Get tool info
  const toolName = task.mcp_tool || task.tool_name || null
  const isWorkflowStep = task.approval_type === 'workflow_step'
  const toolDescription = toolName ? getToolDescription(toolName) : (isWorkflowStep ? 'Approve workflow checkpoint to proceed to next phase' : 'Approval required')
  const dangerLevel = task.danger_level || 'medium'
  const dangerBadge = getDangerLevelBadge(dangerLevel)

  return (
    <div className={`bg-white rounded-xl shadow-sm border p-6 ${isMultiApproval ? 'border-orange-200' : 'border-gray-200'}`}>
      {/* Header with approval type and status */}
      <div className="flex items-start justify-between mb-4">
        <div className="flex-1">
          {isMultiApproval && (
            <div className="flex items-center gap-2 mb-2">
              <span className="text-orange-600 font-semibold text-sm">Multi-Approval Required</span>
              <span className="px-2 py-0.5 bg-orange-100 text-orange-700 text-xs rounded-full">
                {currentApprovals} of {requiredApprovals} approvals
              </span>
            </div>
          )}
          <div className="flex items-center gap-2 flex-wrap">
            <h3 className="font-semibold text-lg">
              {task.name || (isWorkflowStep ? 'Workflow Checkpoint Approval' : `Approve ${toolName || 'action'}`)}
            </h3>
            {task.agent_id && (
              <span className="inline-flex items-center gap-1 px-2 py-0.5 bg-purple-100 text-purple-600 text-xs rounded-full">
                <Bot className="w-3 h-3" />
                {formatAgentName(task.agent_id)}
              </span>
            )}
          </div>
          <p className="text-gray-500 text-sm mt-1">{task.description || toolDescription}</p>
        </div>
        <div className="flex flex-col items-end gap-2">
          <span className="px-3 py-1 bg-yellow-100 text-yellow-700 text-sm rounded-full flex items-center">
            <Clock className="w-4 h-4 mr-1" />
            Pending
          </span>
          <span className={`px-2 py-0.5 ${dangerBadge.bg} ${dangerBadge.text} text-xs rounded-full`}>
            {dangerBadge.label}
          </span>
        </div>
      </div>

      {/* What needs approval - clear explanation */}
      <div className="mb-4 p-4 bg-blue-50 rounded-lg border border-blue-200">
        <h4 className="font-medium text-blue-900 mb-2 flex items-center gap-2">
          <AlertTriangle className="w-4 h-4" />
          What needs your approval:
        </h4>
        <div className="space-y-2">
          {/* Tool info - only show for MCP tool approvals, not workflow steps */}
          {toolName && !isWorkflowStep && (
            <div className="flex items-start gap-2">
              <span className="text-blue-700 font-medium">Tool:</span>
              {(() => {
                const info = getToolInfo(toolName)
                const Icon = info.icon
                return (
                  <span className="flex items-center gap-2">
                    <Icon className={`w-4 h-4 ${info.color}`} />
                    <span className="font-medium">{info.label}</span>
                    <code className="bg-blue-100 px-2 py-0.5 rounded text-blue-800 font-mono text-sm">{toolName}</code>
                  </span>
                )
              })()}
            </div>
          )}
          {/* Workflow step approval - show phase context */}
          {isWorkflowStep && (
            <div className="flex items-start gap-2">
              <span className="text-blue-700 font-medium">Type:</span>
              <span className="flex items-center gap-2">
                <Shield className="w-4 h-4 text-blue-600" />
                <span className="font-medium">Workflow Checkpoint</span>
              </span>
            </div>
          )}
          <div className="text-blue-700">
            <span className="font-medium">Action:</span> {toolDescription}
          </div>

          {/* Command preview for run_command */}
          {command && (
            <div className="mt-3">
              <div className="flex items-center gap-2 text-sm font-medium text-gray-700 mb-2">
                <Terminal className="w-4 h-4 text-orange-600" />
                Command to execute:
              </div>
              <div className="bg-gray-900 rounded-lg p-3 overflow-x-auto">
                <code className="text-green-400 text-sm font-mono whitespace-pre-wrap">
                  $ {command}
                </code>
              </div>
            </div>
          )}

          {/* Commit message preview for commit_and_push */}
          {commitMessage && (
            <div className="mt-3">
              <div className="flex items-center gap-2 text-sm font-medium text-gray-700 mb-2">
                <GitBranch className="w-4 h-4 text-green-600" />
                Commit message:
              </div>
              <div className="bg-white rounded-lg p-3 border border-gray-200">
                <p className="text-sm text-gray-700 whitespace-pre-wrap">{commitMessage}</p>
              </div>
            </div>
          )}

          {/* Code preview for write_file operations */}
          {(newContent || isBatchWrite) && (
            <div className="mt-3">
              <button
                onClick={() => setShowCodePreview(!showCodePreview)}
                className="flex items-center gap-2 text-blue-600 hover:text-blue-800 text-sm font-medium focus:outline-none focus:ring-2 focus:ring-blue-500 rounded"
                aria-expanded={showCodePreview}
              >
                <FileCode className="w-4 h-4" />
                {showCodePreview ? 'Hide' : 'View'} code to be written
                {isBatchWrite && ` (${Object.keys(batchFiles).length} files)`}
                {showCodePreview ? (
                  <ChevronDown className="w-4 h-4 transform rotate-180" />
                ) : (
                  <ChevronDown className="w-4 h-4" />
                )}
              </button>

              {showCodePreview && (
                <div className="mt-2 space-y-3">
                  {/* Single file write */}
                  {newContent && !isBatchWrite && (
                    <div className="bg-gray-900 rounded-lg border border-gray-700 overflow-hidden">
                      <div className="flex items-center justify-between px-3 py-2 bg-gray-800 border-b border-gray-700">
                        <div className="flex items-center gap-2">
                          <FileCode className="w-4 h-4 text-gray-400" />
                          <span className="text-sm text-gray-300 font-mono">{filePath || 'file'}</span>
                        </div>
                        <span className="text-xs text-gray-500">{getLanguageFromPath(filePath)}</span>
                      </div>
                      <div className="max-h-96 overflow-auto">
                        <pre className="p-4 text-sm text-gray-100 whitespace-pre-wrap font-mono leading-relaxed">
                          {newContent}
                        </pre>
                      </div>
                      <div className="px-3 py-1.5 bg-gray-800 border-t border-gray-700 text-xs text-gray-500">
                        {newContent?.split('\n').length || 0} lines
                      </div>
                    </div>
                  )}

                  {/* Batch file write */}
                  {isBatchWrite && Object.entries(batchFiles).map(([path, content]) => (
                    <div key={path} className="bg-gray-900 rounded-lg border border-gray-700 overflow-hidden">
                      <div className="flex items-center justify-between px-3 py-2 bg-gray-800 border-b border-gray-700">
                        <div className="flex items-center gap-2">
                          <FileCode className="w-4 h-4 text-gray-400" />
                          <span className="text-sm text-gray-300 font-mono">{path}</span>
                        </div>
                        <span className="text-xs text-gray-500">{getLanguageFromPath(path)}</span>
                      </div>
                      <div className="max-h-64 overflow-auto">
                        <pre className="p-4 text-sm text-gray-100 whitespace-pre-wrap font-mono leading-relaxed">
                          {content}
                        </pre>
                      </div>
                      <div className="px-3 py-1.5 bg-gray-800 border-t border-gray-700 text-xs text-gray-500">
                        {content?.split('\n').length || 0} lines
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Raw arguments fallback for other tools */}
          {!command && !commitMessage && !newContent && !isBatchWrite && task.mcp_arguments && Object.keys(task.mcp_arguments).length > 0 && (
            <div className="mt-2">
              <button
                onClick={() => setShowDetails(!showDetails)}
                className="text-blue-600 hover:text-blue-800 text-sm flex items-center gap-1 focus:outline-none focus:ring-2 focus:ring-blue-500 rounded"
                aria-expanded={showDetails}
                aria-label={showDetails ? 'Hide tool arguments' : 'Show tool arguments'}
              >
                <span aria-hidden="true">{showDetails ? '▼' : '▶'}</span> View arguments
              </button>
              {showDetails && (
                <pre className="mt-2 bg-blue-100 p-3 rounded text-sm overflow-x-auto text-blue-900 font-mono">
                  {JSON.stringify(task.mcp_arguments, null, 2)}
                </pre>
              )}
            </div>
          )}
        </div>
      </div>

      {/* MULTI approval progress */}
      {isMultiApproval && (
        <div className="mb-4 p-3 bg-orange-50 rounded-lg">
          {/* Progress bar */}
          <div className="w-full bg-gray-200 rounded-full h-2 mb-3">
            <div
              className="bg-orange-500 h-2 rounded-full transition-all"
              style={{ width: `${(currentApprovals / requiredApprovals) * 100}%` }}
            />
          </div>

          {/* Approved by */}
          {approvedByRoles.length > 0 && (
            <div className="mb-2">
              <span className="text-sm text-gray-600">Approved by: </span>
              {approvedByRoles.map(role => (
                <span key={role} className="inline-flex items-center px-2 py-0.5 bg-green-100 text-green-700 text-xs rounded-full mr-1">
                  <CheckCircle className="w-3 h-3 mr-1" />
                  {role}
                </span>
              ))}
            </div>
          )}

          {/* Still needed */}
          {remainingRoles.length > 0 && (
            <div>
              <span className="text-sm text-gray-600">Still needed: </span>
              {remainingRoles.map(role => (
                <span key={role} className="inline-flex items-center px-2 py-0.5 bg-gray-100 text-gray-600 text-xs rounded-full mr-1">
                  {role}
                </span>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Context info - simplified */}
      <div className="grid grid-cols-2 gap-4 mb-4 text-sm bg-gray-50 rounded-lg p-3">
        <div>
          <span className="text-gray-500">Session:</span>
          <span className="ml-2 font-medium font-mono text-xs">{task.session_id ? task.session_id.substring(0, 8) + '...' : 'N/A'}</span>
          {task.session_id && (
            <Link
              to={`/chat?session=${task.session_id}`}
              className="ml-2 inline-flex items-center gap-1 text-xs text-blue-600 hover:text-blue-800 hover:underline"
              aria-label="View conversation for this approval"
            >
              <ExternalLink className="w-3 h-3" />
              View Conversation
            </Link>
          )}
        </div>
        <div>
          <span className="text-gray-500">Created:</span>
          <span className="ml-2">{new Date(task.created_at).toLocaleString()}</span>
        </div>
        {task.agent_id && (
          <div>
            <span className="text-gray-500">Requested by:</span>
            <span className="ml-2 inline-flex items-center gap-1">
              <Bot className="w-3.5 h-3.5 text-purple-500" />
              <span className="font-medium text-purple-700">{formatAgentName(task.agent_id)}</span>
            </span>
          </div>
        )}
        <div>
          <span className="text-gray-500">Required Role:</span>
          <span className="ml-2">
            <span
              className={`px-2 py-0.5 rounded text-xs ${
                canApprove ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-700'
              }`}
            >
              {requiredRoles.join(', ')}
            </span>
            {canApprove && <span className="ml-1 text-green-600">(you can approve)</span>}
          </span>
        </div>
      </div>

      {/* Actions */}
      {canApprove ? (
        <div className="flex flex-col space-y-3">
          {!showReject ? (
            <div className="flex space-x-3" role="group" aria-label="Task approval actions">
              <button
                onClick={() => onApprove(task.id)}
                className={`flex-1 px-4 py-2 text-white rounded-lg flex items-center justify-center focus:outline-none focus:ring-2 focus:ring-offset-2 ${
                  isMultiApproval ? 'bg-orange-500 hover:bg-orange-600 focus:ring-orange-500' : 'bg-green-600 hover:bg-green-700 focus:ring-green-500'
                }`}
                aria-label={isMultiApproval ? `Add approval ${currentApprovals + 1} of ${requiredApprovals}` : 'Approve task'}
              >
                <CheckCircle className="w-5 h-5 mr-2" aria-hidden="true" />
                {isMultiApproval ? `Add Approval (${currentApprovals + 1}/${requiredApprovals})` : 'Approve'}
              </button>
              <button
                onClick={() => setShowReject(true)}
                className="flex-1 px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 flex items-center justify-center focus:outline-none focus:ring-2 focus:ring-red-500 focus:ring-offset-2"
                aria-label="Reject task"
              >
                <XCircle className="w-5 h-5 mr-2" aria-hidden="true" />
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
              <div className="flex space-x-3" role="group" aria-label="Rejection actions">
                <button
                  onClick={() => setShowReject(false)}
                  className="flex-1 px-4 py-2 border border-gray-300 rounded-lg hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-gray-500 focus:ring-offset-2"
                  aria-label="Cancel rejection"
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
                  className="flex-1 px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:opacity-50 disabled:cursor-not-allowed focus:outline-none focus:ring-2 focus:ring-red-500 focus:ring-offset-2"
                  aria-label="Confirm task rejection"
                >
                  Confirm Rejection
                </button>
              </div>
            </div>
          )}
        </div>
      ) : (
        <div className="space-y-3">
          {/* Prominent waiting state */}
          <div className="flex items-center gap-3 p-4 bg-blue-50 rounded-lg border border-blue-200">
            <div className="p-2 bg-blue-100 rounded-full">
              <Clock className="w-5 h-5 text-blue-600 animate-pulse" />
            </div>
            <div className="flex-1">
              <div className="font-medium text-blue-800">Waiting for Approval</div>
              <p className="text-sm text-blue-600 mt-0.5">
                This task requires approval from: <span className="font-semibold">{requiredRoles.join(' or ')}</span>
              </p>
            </div>
          </div>
          <div className="flex items-center p-3 bg-gray-50 rounded-lg text-gray-600">
            <Shield className="w-5 h-5 mr-2" />
            {requiredRoles.length > 1
              ? `You need one of these roles to approve: ${requiredRoles.join(', ')}`
              : `You need the "${requiredRole}" role to approve this task.`
            }
          </div>
        </div>
      )}
    </div>
  )
}

const Tasks = () => {
  const { user } = useAuth()
  const queryClient = useQueryClient()
  const toast = useToast()
  const [showHistory, setShowHistory] = useState(false)

  const { data: tasksResponse, isLoading, isError, error, refetch: refetchTasks } = useQuery({
    queryKey: ['tasks'],
    queryFn: getTasks,
    refetchInterval: 1000,
  })

  // Fetch approval history (completed approvals)
  const { data: historyResponse, isLoading: historyLoading } = useQuery({
    queryKey: ['approvalHistory'],
    queryFn: () => getApprovalHistory(1, 20),
    enabled: showHistory, // Only fetch when history section is expanded
    staleTime: 30000, // Consider data fresh for 30 seconds
  })

  // Extract tasks array from paginated response
  const tasks = tasksResponse?.items || []

  const approveMutation = useMutation({
    mutationFn: ({ taskId, comment }) => approveTask(taskId, comment),
    onSuccess: () => {
      queryClient.invalidateQueries(['tasks'])
      queryClient.invalidateQueries(['plans'])
      toast.success('Approval Granted', 'The task has been approved successfully.')
    },
    onError: (err) => {
      toast.error('Approval Failed', err.message || 'Failed to approve the task. Please try again.')
    },
  })

  const rejectMutation = useMutation({
    mutationFn: ({ taskId, reason }) => rejectTask(taskId, reason),
    onSuccess: () => {
      queryClient.invalidateQueries(['tasks'])
      queryClient.invalidateQueries(['plans'])
      toast.success('Task Rejected', 'The task has been rejected.')
    },
    onError: (err) => {
      toast.error('Rejection Failed', err.message || 'Failed to reject the task. Please try again.')
    },
  })

  const handleApprove = (taskId) => {
    approveMutation.mutate({ taskId, comment: '' })
  }

  const handleReject = (taskId, reason) => {
    rejectMutation.mutate({ taskId, reason })
  }

  // Group tasks by required role (use first role from required_roles array)
  const tasksByRole = tasks.reduce((acc, task) => {
    const roles = task.required_roles || (task.required_role ? [task.required_role] : ['admin'])
    const role = roles[0] || 'other'
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

      {/* Approval Tasks Section */}
      {isLoading ? (
        <div className="flex items-center justify-center h-64">
          <Loader2 className="w-8 h-8 animate-spin text-blue-500" />
          <span className="ml-2 text-gray-600">Loading tasks...</span>
        </div>
      ) : isError ? (
        <div className="flex flex-col items-center justify-center h-64 text-red-500">
          <AlertCircle className="w-12 h-12 mb-2" />
          <p className="text-lg font-medium">Failed to load tasks</p>
          <p className="text-sm text-red-400">{error?.message || 'An unexpected error occurred'}</p>
          <button
            onClick={() => refetchTasks()}
            className="mt-4 px-4 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600 transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2"
            aria-label="Retry loading tasks"
          >
            Retry
          </button>
        </div>
      ) : tasks.length === 0 ? (
        <div className="text-center py-12 bg-white rounded-xl border border-gray-200">
          <CheckCircle className="w-12 h-12 text-green-500 mx-auto mb-4" />
          <h3 className="text-lg font-medium">No pending approvals</h3>
          <p className="text-gray-500">All approval requests have been handled.</p>
        </div>
      ) : (
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

      {/* Approval History Section */}
      <div className="mt-8 border-t pt-6">
        <button
          onClick={() => setShowHistory(!showHistory)}
          className="flex items-center gap-2 text-lg font-semibold text-gray-700 hover:text-gray-900 transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500 rounded"
          aria-expanded={showHistory}
          aria-controls="approval-history"
        >
          {showHistory ? (
            <ChevronDown className="w-5 h-5" />
          ) : (
            <ChevronRight className="w-5 h-5" />
          )}
          <History className="w-5 h-5 text-blue-500" />
          Approval History
        </button>

        {showHistory && (
          <div id="approval-history" className="mt-4">
            {historyLoading ? (
              <div className="flex items-center justify-center h-32 bg-white rounded-xl border border-gray-200">
                <Loader2 className="w-6 h-6 animate-spin text-blue-500" />
                <span className="ml-2 text-gray-600">Loading history...</span>
              </div>
            ) : historyResponse?.items?.length > 0 ? (
              <div className="space-y-3">
                {historyResponse.items.map((approval) => (
                  <div
                    key={approval.id}
                    className="bg-white rounded-lg border border-gray-200 p-4 hover:border-gray-300 transition-colors"
                  >
                    <div className="flex items-start justify-between">
                      <div className="flex-1">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="font-medium">{approval.tool_name || (approval.approval_type === 'workflow_step' ? 'Step Approval' : 'Unknown tool')}</span>
                          <span className={`px-2 py-0.5 ${
                            approval.status === 'approved'
                              ? 'bg-green-100 text-green-700'
                              : approval.status === 'rejected'
                              ? 'bg-red-100 text-red-700'
                              : 'bg-gray-100 text-gray-700'
                          } text-xs rounded-full flex items-center`}>
                            {approval.status === 'approved' ? (
                              <><CheckCircle className="w-3 h-3 mr-1" />Approved</>
                            ) : approval.status === 'rejected' ? (
                              <><XCircle className="w-3 h-3 mr-1" />Rejected</>
                            ) : (
                              <>{approval.status}</>
                            )}
                          </span>
                          {approval.agent_id && (
                            <span className="px-2 py-0.5 bg-purple-100 text-purple-600 text-xs rounded-full flex items-center">
                              <Bot className="w-3 h-3 mr-1" />
                              {formatAgentName(approval.agent_id)}
                            </span>
                          )}
                        </div>
                        {approval.description && (
                          <p className="text-gray-500 text-sm mt-1 line-clamp-2">{approval.description}</p>
                        )}
                        <div className="flex items-center gap-4 mt-2 text-xs text-gray-500 flex-wrap">
                          {(approval.approved_by || approval.rejected_by) && (
                            <span className="flex items-center gap-1">
                              <User className="w-3 h-3" />
                              {approval.status === 'approved' ? 'Approved' : 'Rejected'} by: {
                                approval.approved_by_username ||
                                approval.rejected_by_username ||
                                (approval.approved_by || approval.rejected_by)?.substring(0, 8) + '...'
                              }
                            </span>
                          )}
                          {approval.created_at && (
                            <span className="flex items-center gap-1">
                              <Clock className="w-3 h-3" />
                              {new Date(approval.created_at).toLocaleString()}
                            </span>
                          )}
                        </div>
                        {/* Session links for context */}
                        {approval.session_id && (
                          <div className="flex items-center gap-3 mt-2">
                            <Link
                              to={`/chat?session=${approval.session_id}`}
                              className="inline-flex items-center gap-1 text-xs text-blue-600 hover:text-blue-800 hover:underline"
                            >
                              <MessageSquare className="w-3 h-3" />
                              View Conversation
                            </Link>
                            <Link
                              to={`/debug/${approval.session_id}`}
                              className="inline-flex items-center gap-1 text-xs text-indigo-600 hover:text-indigo-800 hover:underline"
                            >
                              <ExternalLink className="w-3 h-3" />
                              Debug Trace
                            </Link>
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="text-center py-8 bg-white rounded-xl border border-gray-200">
                <History className="w-8 h-8 text-gray-400 mx-auto mb-2" />
                <p className="text-gray-500 text-sm">No approval history found.</p>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

export default Tasks
