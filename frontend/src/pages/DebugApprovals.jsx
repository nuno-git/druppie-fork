/**
 * DebugApprovals - Debug page for viewing and managing pending approvals
 *
 * Access at /debug-approvals
 *
 * Uses:
 * - GET /api/approvals - list pending approvals
 * - POST /api/approvals/{id}/approve - approve
 * - POST /api/approvals/{id}/reject - reject (with reason)
 */

import React, { useState, useEffect } from 'react'
import { RefreshCw, CheckCircle, XCircle, Clock, Shield, AlertCircle } from 'lucide-react'
import { getToken } from '../services/keycloak'
import PageHeader from '../components/shared/PageHeader'
import { SkeletonTaskCard } from '../components/shared/Skeleton'
import EmptyState from '../components/shared/EmptyState'

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

  console.log(`API ${options.method || 'GET'} ${endpoint}`)

  try {
    const response = await fetch(`${API_URL}${endpoint}`, { ...options, headers })
    const data = await response.json()
    console.log('Response:', data)
    return { ok: response.ok, status: response.status, data }
  } catch (err) {
    console.error('Error:', err)
    return { ok: false, error: err.message }
  }
}

// Status badge
const StatusBadge = ({ status }) => {
  const config = {
    pending: { bg: 'bg-blue-100 text-blue-700', icon: Clock },
    approved: { bg: 'bg-green-100 text-green-800', icon: CheckCircle },
    rejected: { bg: 'bg-red-100 text-red-800', icon: XCircle },
  }
  const { bg, icon: Icon } = config[status] || { bg: 'bg-gray-100 text-gray-700', icon: Clock }
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${bg}`}>
      <Icon className="w-3 h-3" />
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
    <div className="border border-gray-100 rounded-lg p-4 bg-white">
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
      <div className="text-xs text-gray-400 mb-3 flex flex-wrap items-center gap-4">
        <span>ID: {approval.id}</span>
        <span>Session: {approval.session_id?.slice(0, 8)}...</span>
        <span>Required role: <strong>{approval.required_role}</strong></span>
        <span>Created: {new Date(approval.created_at).toLocaleString()}</span>
      </div>

      {/* Actions */}
      {approval.status === 'pending' && (
        <div className="flex items-center gap-2">
          {!showRejectInput ? (
            <>
              <button
                onClick={() => onApprove(approval.id)}
                disabled={loading}
                className="flex items-center gap-1.5 px-3 py-1.5 text-sm bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:opacity-50 transition-colors"
              >
                {loading ? 'Processing...' : 'Approve'}
              </button>
              <button
                onClick={() => setShowRejectInput(true)}
                disabled={loading}
                className="px-3 py-1.5 text-sm text-gray-500 hover:text-red-600 hover:bg-red-50 rounded-lg transition-colors disabled:opacity-50"
              >
                Reject
              </button>
            </>
          ) : (
            <div className="flex items-center gap-2 flex-1">
              <input
                type="text"
                value={rejectReason}
                onChange={(e) => setRejectReason(e.target.value)}
                placeholder="Reason for rejection..."
                className="flex-1 px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-red-500 focus:border-transparent"
                autoFocus
              />
              <button
                onClick={handleReject}
                disabled={loading}
                className="px-3 py-1.5 text-sm bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:opacity-50 transition-colors"
              >
                Confirm Reject
              </button>
              <button
                onClick={() => setShowRejectInput(false)}
                className="px-3 py-1.5 text-sm text-gray-500 hover:text-gray-700 rounded-lg transition-colors"
              >
                Cancel
              </button>
            </div>
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

export default function DebugApprovals() {
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
    <div className="space-y-6">
      <PageHeader title="Debug Approvals" subtitle="Inspect and manage pending approvals via the API.">
        <button
          onClick={fetchApprovals}
          disabled={loading}
          className="inline-flex items-center gap-2 px-4 py-2 text-sm bg-white border border-gray-200 rounded-lg hover:bg-gray-50 transition-colors disabled:opacity-50"
        >
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </PageHeader>

      <div className="p-3 bg-blue-50 text-blue-800 rounded-lg text-sm border border-blue-100">
        <strong>API Endpoints:</strong> GET /api/approvals, POST /api/approvals/:id/approve, POST /api/approvals/:id/reject
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
        <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
          <AlertCircle className="w-5 h-5 text-blue-500" />
          Pending Approvals
          {pendingApprovals.length > 0 && (
            <span className="bg-blue-100 text-blue-700 px-2 py-0.5 rounded-full text-sm">
              {pendingApprovals.length}
            </span>
          )}
        </h2>

        {pendingApprovals.length === 0 ? (
          <div className="bg-white rounded-xl border border-gray-100">
            <EmptyState
              icon={Shield}
              title="No pending approvals"
              description="Approvals will appear here when agents request tool permissions."
            />
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
          <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
            <CheckCircle className="w-5 h-5 text-green-500" />
            Recently Processed
          </h2>
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
