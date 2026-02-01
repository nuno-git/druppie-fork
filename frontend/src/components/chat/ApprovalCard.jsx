/**
 * ApprovalCard - Inline approval/reject UI for tasks requiring authorization
 *
 * Shows code/file content for write operations so users can review what will be changed.
 * For users without the required role, shows a "waiting for approval" state with
 * a contact popup to find users who can approve.
 */

import React, { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import {
  AlertTriangle,
  CheckCircle,
  XCircle,
  Loader2,
  FileText,
  FilePlus,
  FileCode,
  Eye,
  ChevronDown,
  ChevronUp,
  Code,
  Terminal,
  GitBranch,
  MessageSquare,
  ExternalLink,
  Mail,
  Users,
  X,
  Clock,
} from 'lucide-react'
import { getWorkspaceFile, getUsersByRole } from '../../services/api'

// Helper to detect language from file path
const getLanguageFromPath = (path) => {
  if (!path) return 'text'
  const ext = path.split('.').pop()?.toLowerCase()
  const langMap = {
    js: 'javascript',
    jsx: 'javascript',
    ts: 'typescript',
    tsx: 'typescript',
    py: 'python',
    rb: 'ruby',
    go: 'go',
    rs: 'rust',
    java: 'java',
    c: 'c',
    cpp: 'cpp',
    h: 'c',
    hpp: 'cpp',
    cs: 'csharp',
    php: 'php',
    swift: 'swift',
    kt: 'kotlin',
    scala: 'scala',
    sh: 'bash',
    bash: 'bash',
    zsh: 'bash',
    yml: 'yaml',
    yaml: 'yaml',
    json: 'json',
    xml: 'xml',
    html: 'html',
    css: 'css',
    scss: 'scss',
    less: 'less',
    sql: 'sql',
    md: 'markdown',
    dockerfile: 'dockerfile',
    toml: 'toml',
    ini: 'ini',
    cfg: 'ini',
    conf: 'ini',
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
  return tools[toolName] || { icon: Code, label: toolName, color: 'text-gray-600' }
}

const ApprovalCard = ({ approval, onApprove, onReject, isProcessing, currentUserId, sessionId, userRoles = [], chatInline = false }) => {
  const [showRejectInput, setShowRejectInput] = useState(false)
  const [rejectReason, setRejectReason] = useState('')
  const [showNewContent, setShowNewContent] = useState(false)
  const [showExistingContent, setShowExistingContent] = useState(false)
  const [existingContent, setExistingContent] = useState(null)
  const [fileLoading, setFileLoading] = useState(false)
  const [fileError, setFileError] = useState(null)
  // Contact modal state
  const [showContactModal, setShowContactModal] = useState(false)
  const [contactUsers, setContactUsers] = useState([])
  const [contactLoading, setContactLoading] = useState(false)

  // Extract arguments from approval (mcp_arguments for chat view, arguments for API)
  const args = approval.mcp_arguments || approval.arguments || {}

  // Extract file path and content for write operations
  const filePath = args.path || args.file_path || approval.context?.file_path
  const newContent = args.content
  const contextDescription = approval.context?.description

  // For batch_write_files, files is a dict of {path: content}
  const batchFiles = args.files
  const isBatchWrite = !!batchFiles && Object.keys(batchFiles).length > 0

  // For run_command
  const command = args.command

  // For commit_and_push
  const commitMessage = args.message || args.commit_message

  // Get tool info for display
  const toolName = approval.mcp_tool || approval.tool_name
  const toolInfo = getToolInfo(toolName)
  const ToolIcon = toolInfo.icon

  // Determine if this is a write operation that has content to show
  const isWriteOperation = toolName?.includes('write_file') || isBatchWrite
  const hasContentToShow = isWriteOperation && (newContent || isBatchWrite)

  // Load existing file content when comparison is requested
  useEffect(() => {
    if (showExistingContent && filePath && existingContent === null && !fileLoading) {
      loadExistingContent()
    }
  }, [showExistingContent, filePath])

  // Load contact users when modal is opened
  const loadContactUsers = async (role) => {
    setContactLoading(true)
    try {
      const response = await getUsersByRole(role)
      setContactUsers(response.users || [])
    } catch (err) {
      console.error('Failed to load users by role:', err)
      setContactUsers([])
    } finally {
      setContactLoading(false)
    }
  }

  const loadExistingContent = async () => {
    if (!filePath || !sessionId) return

    setFileLoading(true)
    setFileError(null)

    try {
      const response = await getWorkspaceFile(filePath, sessionId)
      setExistingContent(response.content)
    } catch (err) {
      console.error('Failed to load existing file:', err)
      // File might not exist yet - that's OK for new files
      if (err.message?.includes('404') || err.message?.includes('not found')) {
        setExistingContent('[New file - does not exist yet]')
      } else {
        setFileError(err.message || 'Failed to load file')
      }
    } finally {
      setFileLoading(false)
    }
  }

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
  // Normalize: derive requiredRoles from required_roles array or required_role string
  const requiredRoles = approval.required_roles || (approval.required_role ? [approval.required_role] : ['admin'])
  const requiredRole = approval.required_role || (requiredRoles.length > 0 ? requiredRoles[0] : 'admin')
  const remainingRoles = requiredRoles.filter(r => !approvedByRoles.includes(r))
  const progressPercent = Math.round((currentApprovals / requiredApprovals) * 100)

  // Check if current user has already approved
  const userHasApproved = currentUserId && approvedByIds.includes(currentUserId)

  // Check if current user can approve based on their roles
  // User can approve if they have admin role OR any of the required roles
  const userCanApprove = userRoles.includes('admin') || requiredRoles.some((r) => userRoles.includes(r))

  // Handler to open contact modal
  const handleOpenContactModal = () => {
    setShowContactModal(true)
    // Load users for the first required role
    const roleToQuery = requiredRoles[0] || 'admin'
    loadContactUsers(roleToQuery)
  }

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
              This action requires approval from <span className="font-semibold">{requiredRoles.join(' or ')}</span> role.
            </div>
          )}

          {/* Tool info badge */}
          {toolName && (
            <div className="flex items-center gap-2 text-sm text-amber-700 mb-3">
              <ToolIcon className={`w-4 h-4 ${toolInfo.color}`} />
              <span className="font-medium">{toolInfo.label}</span>
              <code className="bg-amber-100 px-1 rounded text-xs">{toolName}</code>
            </div>
          )}

          {/* Command preview for run_command */}
          {command && (
            <div className="mb-3">
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
            <div className="mb-3">
              <div className="flex items-center gap-2 text-sm font-medium text-gray-700 mb-2">
                <GitBranch className="w-4 h-4 text-green-600" />
                Commit message:
              </div>
              <div className="bg-gray-50 rounded-lg p-3 border border-gray-200">
                <p className="text-sm text-gray-700 whitespace-pre-wrap">{commitMessage}</p>
              </div>
            </div>
          )}

          {/* NEW: Content preview for write_file operations */}
          {hasContentToShow && !isBatchWrite && (
            <div className="mb-3">
              <button
                onClick={() => setShowNewContent(!showNewContent)}
                className="flex items-center gap-2 text-sm text-blue-600 hover:text-blue-800 transition-colors font-medium"
              >
                <FilePlus className="w-4 h-4" />
                <span>View code to be written: {filePath}</span>
                {showNewContent ? (
                  <ChevronUp className="w-4 h-4" />
                ) : (
                  <ChevronDown className="w-4 h-4" />
                )}
              </button>

              {showNewContent && (
                <div className="mt-2 bg-gray-900 rounded-lg border border-gray-700 overflow-hidden">
                  {/* File path header */}
                  <div className="flex items-center justify-between px-3 py-2 bg-gray-800 border-b border-gray-700">
                    <div className="flex items-center gap-2">
                      <FileCode className="w-4 h-4 text-gray-400" />
                      <span className="text-sm text-gray-300 font-mono">{filePath}</span>
                    </div>
                    <span className="text-xs text-gray-500">{getLanguageFromPath(filePath)}</span>
                  </div>
                  {/* Code content */}
                  <div className="max-h-96 overflow-auto">
                    <pre className="p-4 text-sm text-gray-100 whitespace-pre-wrap font-mono leading-relaxed">
                      {newContent}
                    </pre>
                  </div>
                  {/* Line count footer */}
                  <div className="px-3 py-1.5 bg-gray-800 border-t border-gray-700 text-xs text-gray-500">
                    {newContent?.split('\n').length || 0} lines
                  </div>
                </div>
              )}

              {/* Compare with existing file */}
              {filePath && showNewContent && (
                <div className="mt-2">
                  <button
                    onClick={() => setShowExistingContent(!showExistingContent)}
                    className="flex items-center gap-2 text-xs text-gray-500 hover:text-gray-700 transition-colors"
                  >
                    <Eye className="w-3 h-3" />
                    <span>{showExistingContent ? 'Hide' : 'Show'} current file content</span>
                  </button>

                  {showExistingContent && (
                    <div className="mt-2 bg-gray-50 rounded-lg border border-gray-200 overflow-hidden">
                      <div className="px-3 py-2 bg-gray-100 border-b border-gray-200 text-sm font-medium text-gray-600">
                        Current content (before change)
                      </div>
                      {fileLoading ? (
                        <div className="flex items-center justify-center py-8">
                          <Loader2 className="w-6 h-6 animate-spin text-gray-400" />
                          <span className="ml-2 text-sm text-gray-500">Loading...</span>
                        </div>
                      ) : fileError ? (
                        <div className="p-4 text-red-600 text-sm">
                          <AlertTriangle className="w-4 h-4 inline mr-2" />
                          {fileError}
                        </div>
                      ) : existingContent ? (
                        <div className="max-h-48 overflow-auto">
                          <pre className="p-4 text-sm text-gray-600 whitespace-pre-wrap font-mono">
                            {existingContent}
                          </pre>
                        </div>
                      ) : null}
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

          {/* Batch write files preview */}
          {isBatchWrite && (
            <div className="mb-3">
              <button
                onClick={() => setShowNewContent(!showNewContent)}
                className="flex items-center gap-2 text-sm text-blue-600 hover:text-blue-800 transition-colors font-medium"
              >
                <FileCode className="w-4 h-4" />
                <span>View {Object.keys(batchFiles).length} files to be written</span>
                {showNewContent ? (
                  <ChevronUp className="w-4 h-4" />
                ) : (
                  <ChevronDown className="w-4 h-4" />
                )}
              </button>

              {showNewContent && (
                <div className="mt-2 space-y-3">
                  {Object.entries(batchFiles).map(([path, content]) => (
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

          {/* Context description */}
          {contextDescription && (
            <div className="text-sm text-amber-700 mb-3 italic">
              {contextDescription}
            </div>
          )}

          {/* View full conversation link (hidden when already on chat page) */}
          {sessionId && !chatInline && (
            <div className="mb-3 pt-2 border-t border-amber-200">
              <Link
                to={`/chat?session=${sessionId}`}
                className="inline-flex items-center gap-2 text-sm text-blue-600 hover:text-blue-800 transition-colors"
              >
                <MessageSquare className="w-4 h-4" />
                <span>View full conversation history</span>
                <ExternalLink className="w-3 h-3" />
              </Link>
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

          {/* Action buttons or waiting message */}
          {userHasApproved ? (
            <div className="flex items-center gap-2 p-3 bg-green-50 rounded-lg border border-green-200">
              <CheckCircle className="w-5 h-5 text-green-600" />
              <span className="text-sm text-green-800 font-medium">
                You have approved this task. Waiting for {requiredApprovals - currentApprovals} more approval(s) from other roles.
              </span>
            </div>
          ) : !userCanApprove ? (
            /* User cannot approve - show waiting state */
            <div className="space-y-3">
              <div className="flex items-center gap-2 p-3 bg-blue-50 rounded-lg border border-blue-200">
                <Clock className="w-5 h-5 text-blue-600" />
                <div className="flex-1">
                  <span className="text-sm text-blue-800 font-medium">
                    Waiting for approval from: <span className="font-bold">{requiredRoles.join(' or ')}</span>
                  </span>
                  <p className="text-xs text-blue-600 mt-0.5">
                    You don't have the required role to approve this action.
                  </p>
                </div>
              </div>
              {!chatInline && (
                <button
                  onClick={handleOpenContactModal}
                  className="flex items-center gap-2 px-4 py-2 text-blue-600 border border-blue-200 rounded-lg hover:bg-blue-50 transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2"
                >
                  <Users className="w-4 h-4" />
                  <span>Contact {requiredRoles[0] || 'approvers'}</span>
                </button>
              )}
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

      {/* Contact Modal */}
      {showContactModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black bg-opacity-50">
          <div className="bg-white rounded-lg shadow-xl w-full max-w-md mx-4 overflow-hidden">
            <div className="flex items-center justify-between px-4 py-3 border-b border-gray-200 bg-gray-50">
              <h3 className="font-semibold text-gray-900 flex items-center gap-2">
                <Users className="w-5 h-5 text-blue-600" />
                Contact Approvers
              </h3>
              <button
                onClick={() => setShowContactModal(false)}
                className="text-gray-400 hover:text-gray-600 transition-colors p-1 rounded-full hover:bg-gray-200"
                aria-label="Close modal"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
            <div className="p-4">
              <p className="text-sm text-gray-600 mb-4">
                Users with <span className="font-semibold">{requiredRoles.join(' or ')}</span> role who can approve this action:
              </p>
              {contactLoading ? (
                <div className="flex items-center justify-center py-8">
                  <Loader2 className="w-6 h-6 animate-spin text-blue-600" />
                  <span className="ml-2 text-sm text-gray-500">Loading...</span>
                </div>
              ) : contactUsers.length === 0 ? (
                <div className="text-center py-8 text-gray-500">
                  <Users className="w-8 h-8 mx-auto mb-2 text-gray-400" />
                  <p className="text-sm">No users found with this role.</p>
                </div>
              ) : (
                <ul className="space-y-3">
                  {contactUsers.map((u) => (
                    <li
                      key={u.id}
                      className="flex items-center justify-between p-3 bg-gray-50 rounded-lg border border-gray-200"
                    >
                      <div>
                        <div className="font-medium text-gray-900">
                          {u.display_name || u.username}
                        </div>
                        <div className="text-xs text-gray-500">@{u.username}</div>
                      </div>
                      {u.email ? (
                        <a
                          href={`mailto:${u.email}?subject=Approval%20Request&body=Hi%2C%0A%0AI%20need%20your%20approval%20for%20a%20task%20in%20Druppie.%0A%0ATask%3A%20${encodeURIComponent(approval.task_name)}%0A%0APlease%20check%20the%20Approvals%20page%20to%20review%20and%20approve.%0A%0AThanks!`}
                          className="flex items-center gap-2 px-3 py-1.5 text-sm text-blue-600 bg-blue-50 rounded-lg hover:bg-blue-100 transition-colors"
                        >
                          <Mail className="w-4 h-4" />
                          Email
                        </a>
                      ) : (
                        <span className="text-xs text-gray-400 italic">No email</span>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </div>
            <div className="px-4 py-3 border-t border-gray-200 bg-gray-50 flex justify-end">
              <button
                onClick={() => setShowContactModal(false)}
                className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default ApprovalCard
