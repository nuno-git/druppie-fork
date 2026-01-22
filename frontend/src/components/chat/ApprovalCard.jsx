/**
 * ApprovalCard - Inline approval/reject UI for tasks requiring authorization
 */

import React, { useState, useEffect } from 'react'
import {
  AlertTriangle,
  CheckCircle,
  XCircle,
  Loader2,
  FileText,
  Eye,
  ChevronDown,
  ChevronUp,
} from 'lucide-react'
import { getWorkspaceFile } from '../../services/api'

const ApprovalCard = ({ approval, onApprove, onReject, isProcessing, currentUserId, sessionId }) => {
  const [showRejectInput, setShowRejectInput] = useState(false)
  const [rejectReason, setRejectReason] = useState('')
  const [showFilePreview, setShowFilePreview] = useState(false)
  const [fileContent, setFileContent] = useState(null)
  const [fileLoading, setFileLoading] = useState(false)
  const [fileError, setFileError] = useState(null)

  // Extract file_path from approval context
  const filePath = approval.context?.file_path || approval.arguments?.file_path
  const contextDescription = approval.context?.description

  // Load file content when preview is toggled
  useEffect(() => {
    if (showFilePreview && filePath && !fileContent && !fileLoading) {
      loadFileContent()
    }
  }, [showFilePreview, filePath])

  const loadFileContent = async () => {
    if (!filePath || !sessionId) return

    setFileLoading(true)
    setFileError(null)

    try {
      const response = await getWorkspaceFile(filePath, sessionId)
      setFileContent(response.content)
    } catch (err) {
      console.error('Failed to load file:', err)
      setFileError(err.message || 'Failed to load file')
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

          {approval.mcp_tool && (
            <div className="text-sm text-amber-700 mb-3">
              MCP Tool: <code className="bg-amber-100 px-1 rounded">{approval.mcp_tool}</code>
            </div>
          )}

          {/* File preview section */}
          {filePath && (
            <div className="mb-3">
              <button
                onClick={() => setShowFilePreview(!showFilePreview)}
                className="flex items-center gap-2 text-sm text-blue-600 hover:text-blue-800 transition-colors"
              >
                <FileText className="w-4 h-4" />
                <span>View {filePath}</span>
                {showFilePreview ? (
                  <ChevronUp className="w-4 h-4" />
                ) : (
                  <ChevronDown className="w-4 h-4" />
                )}
              </button>

              {showFilePreview && (
                <div className="mt-2 bg-gray-50 rounded-lg border border-gray-200 overflow-hidden">
                  {fileLoading ? (
                    <div className="flex items-center justify-center py-8">
                      <Loader2 className="w-6 h-6 animate-spin text-gray-400" />
                      <span className="ml-2 text-sm text-gray-500">Loading file...</span>
                    </div>
                  ) : fileError ? (
                    <div className="p-4 text-red-600 text-sm">
                      <AlertTriangle className="w-4 h-4 inline mr-2" />
                      {fileError}
                    </div>
                  ) : fileContent ? (
                    <div className="max-h-96 overflow-auto">
                      <pre className="p-4 text-sm text-gray-700 whitespace-pre-wrap font-mono">
                        {fileContent}
                      </pre>
                    </div>
                  ) : (
                    <div className="p-4 text-gray-500 text-sm">
                      No content available
                    </div>
                  )}
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

export default ApprovalCard
