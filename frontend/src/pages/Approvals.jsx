/**
 * Approvals - Simple page for viewing and managing pending approvals
 *
 * Uses:
 * - GET /api/approvals - list pending approvals
 * - POST /api/approvals/{id}/approve - approve
 * - POST /api/approvals/{id}/reject - reject
 */

import React, { useState, useEffect } from 'react'
import { getToken } from '../services/keycloak'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

// Simple fetch wrapper
const apiFetch = async (endpoint, options = {}) => {
  const token = getToken()
  const headers = {
    'Content-Type': 'application/json',
    ...options.headers,
  }
  if (token) {
    headers['Authorization'] = `Bearer ${token}`
  }

  try {
    const response = await fetch(`${API_URL}${endpoint}`, { ...options, headers })
    const data = await response.json()
    return { ok: response.ok, status: response.status, data }
  } catch (err) {
    return { ok: false, error: err.message }
  }
}

// Status badge
const StatusBadge = ({ status }) => {
  const colors = {
    pending: 'bg-yellow-100 text-yellow-800',
    approved: 'bg-green-100 text-green-800',
    rejected: 'bg-red-100 text-red-800',
  }
  return (
    <span className={`px-2 py-0.5 rounded text-xs font-medium ${colors[status] || 'bg-gray-100'}`}>
      {status}
    </span>
  )
}

// Single approval card
const ApprovalCard = ({ approval, onApprove, onReject, loading }) => {
  const [rejectReason, setRejectReason] = useState('')
  const [showRejectInput, setShowRejectInput] = useState(false)

  const handleReject = () => {
    if (showRejectInput) {
      onReject(approval.id, rejectReason || 'Rejected by user')
      setShowRejectInput(false)
      setRejectReason('')
    } else {
      setShowRejectInput(true)
    }
  }

  return (
    <div className="border rounded-lg p-4 bg-white shadow-sm">
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <span className="font-semibold text-purple-600">{approval.agent_id || 'agent'}</span>
          <span className="text-gray-400">wants to call</span>
          <code className="bg-gray-100 px-2 py-0.5 rounded text-sm">
            {approval.mcp_server}:{approval.tool_name}
          </code>
        </div>
        <StatusBadge status={approval.status} />
      </div>

      {/* Tool arguments */}
      <div className="mb-3">
        <div className="text-sm text-gray-500 mb-1">Arguments:</div>
        <pre className="bg-gray-50 p-2 rounded text-xs overflow-auto max-h-32">
          {JSON.stringify(approval.arguments, null, 2)}
        </pre>
      </div>

      {/* Metadata */}
      <div className="text-xs text-gray-400 mb-3 flex items-center gap-4">
        <span>ID: {approval.id}</span>
        <span>Session: {approval.session_id?.slice(0, 8)}...</span>
        <span>Required role: <strong>{approval.required_role}</strong></span>
        <span>Created: {new Date(approval.created_at).toLocaleString()}</span>
      </div>

      {/* Actions */}
      {approval.status === 'pending' && (
        <div className="flex items-center gap-2">
          <button
            onClick={() => onApprove(approval.id)}
            disabled={loading}
            className="px-4 py-2 bg-green-600 text-white rounded hover:bg-green-700 disabled:opacity-50 text-sm font-medium"
          >
            {loading ? 'Processing...' : 'Approve'}
          </button>

          {showRejectInput ? (
            <div className="flex items-center gap-2 flex-1">
              <input
                type="text"
                value={rejectReason}
                onChange={(e) => setRejectReason(e.target.value)}
                placeholder="Reason for rejection..."
                className="flex-1 px-3 py-2 border rounded text-sm focus:outline-none focus:ring-2 focus:ring-red-500"
                autoFocus
              />
              <button
                onClick={handleReject}
                disabled={loading}
                className="px-4 py-2 bg-red-600 text-white rounded hover:bg-red-700 disabled:opacity-50 text-sm font-medium"
              >
                Confirm Reject
              </button>
              <button
                onClick={() => setShowRejectInput(false)}
                className="px-3 py-2 text-gray-500 hover:text-gray-700 text-sm"
              >
                Cancel
              </button>
            </div>
          ) : (
            <button
              onClick={handleReject}
              disabled={loading}
              className="px-4 py-2 bg-red-100 text-red-700 rounded hover:bg-red-200 disabled:opacity-50 text-sm font-medium"
            >
              Reject
            </button>
          )}
        </div>
      )}

      {/* Result for processed approvals */}
      {approval.status === 'approved' && approval.approved_by && (
        <div className="text-sm text-green-600">
          Approved by {approval.approved_by} at {new Date(approval.decided_at).toLocaleString()}
        </div>
      )}
      {approval.status === 'rejected' && (
        <div className="text-sm text-red-600">
          Rejected: {approval.rejection_reason || 'No reason provided'}
        </div>
      )}
    </div>
  )
}

export default function Approvals() {
  const [approvals, setApprovals] = useState(null)
  const [loading, setLoading] = useState(false)
  const [actionLoading, setActionLoading] = useState({})
  const [lastAction, setLastAction] = useState(null)

  // Fetch approvals on mount and set up polling
  useEffect(() => {
    fetchApprovals()
    const interval = setInterval(fetchApprovals, 5000) // Poll every 5 seconds
    return () => clearInterval(interval)
  }, [])

  const fetchApprovals = async () => {
    if (loading) return
    setLoading(true)
    const result = await apiFetch('/api/approvals')
    setApprovals(result)
    setLoading(false)
  }

  const handleApprove = async (approvalId) => {
    setActionLoading(l => ({ ...l, [approvalId]: true }))
    const result = await apiFetch(`/api/approvals/${approvalId}/approve`, {
      method: 'POST',
      body: JSON.stringify({}),
    })
    setLastAction({ type: 'approve', approvalId, result })
    setActionLoading(l => ({ ...l, [approvalId]: false }))

    // Refresh list
    fetchApprovals()
  }

  const handleReject = async (approvalId, reason) => {
    setActionLoading(l => ({ ...l, [approvalId]: true }))
    const result = await apiFetch(`/api/approvals/${approvalId}/reject`, {
      method: 'POST',
      body: JSON.stringify({ reason }),
    })
    setLastAction({ type: 'reject', approvalId, result })
    setActionLoading(l => ({ ...l, [approvalId]: false }))

    // Refresh list
    fetchApprovals()
  }

  const pendingApprovals = approvals?.data?.items?.filter(a => a.status === 'pending') || []
  const processedApprovals = approvals?.data?.items?.filter(a => a.status !== 'pending') || []

  return (
    <div className="p-6 max-w-4xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold">Approvals</h1>
        <button
          onClick={fetchApprovals}
          disabled={loading}
          className="px-4 py-2 bg-gray-200 rounded hover:bg-gray-300 text-sm"
        >
          {loading ? 'Refreshing...' : 'Refresh'}
        </button>
      </div>

      {/* Last action result */}
      {lastAction && (
        <div className={`mb-4 p-3 rounded ${lastAction.result?.ok ? 'bg-green-50 text-green-800' : 'bg-red-50 text-red-800'}`}>
          {lastAction.result?.ok
            ? `Successfully ${lastAction.type}d approval ${lastAction.approvalId.slice(0, 8)}...`
            : `Failed to ${lastAction.type}: ${lastAction.result?.data?.detail || 'Unknown error'}`
          }
          <button
            onClick={() => setLastAction(null)}
            className="ml-2 text-sm underline"
          >
            Dismiss
          </button>
        </div>
      )}

      {/* Error state */}
      {approvals && !approvals.ok && (
        <div className="bg-red-50 text-red-800 p-4 rounded mb-4">
          Error fetching approvals: {approvals.error || approvals.data?.detail || 'Unknown error'}
        </div>
      )}

      {/* Pending approvals */}
      <div className="mb-8">
        <h2 className="text-lg font-semibold mb-3 flex items-center gap-2">
          Pending Approvals
          {pendingApprovals.length > 0 && (
            <span className="bg-yellow-100 text-yellow-800 px-2 py-0.5 rounded-full text-sm">
              {pendingApprovals.length}
            </span>
          )}
        </h2>

        {pendingApprovals.length === 0 ? (
          <div className="text-gray-500 italic p-4 bg-gray-50 rounded">
            No pending approvals
          </div>
        ) : (
          <div className="space-y-3">
            {pendingApprovals.map(approval => (
              <ApprovalCard
                key={approval.id}
                approval={approval}
                onApprove={handleApprove}
                onReject={handleReject}
                loading={actionLoading[approval.id]}
              />
            ))}
          </div>
        )}
      </div>

      {/* Recently processed */}
      {processedApprovals.length > 0 && (
        <div>
          <h2 className="text-lg font-semibold mb-3">Recently Processed</h2>
          <div className="space-y-3 opacity-75">
            {processedApprovals.slice(0, 5).map(approval => (
              <ApprovalCard
                key={approval.id}
                approval={approval}
                onApprove={handleApprove}
                onReject={handleReject}
                loading={false}
              />
            ))}
          </div>
        </div>
      )}

      {/* Debug: Raw response */}
      <details className="mt-8">
        <summary className="cursor-pointer text-sm text-gray-500 hover:text-gray-700">
          Show raw API response
        </summary>
        <pre className="mt-2 bg-gray-100 p-3 rounded text-xs overflow-auto max-h-60">
          {JSON.stringify(approvals, null, 2)}
        </pre>
      </details>
    </div>
  )
}
