/**
 * API Service for Druppie Backend (New FastAPI)
 *
 * Updated to work with the new druppie/ backend architecture.
 * Sessions replace Plans, and endpoints use the new API structure.
 */

import { getToken } from './keycloak'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

const request = async (endpoint, options = {}) => {
  const token = getToken()

  const headers = {
    'Content-Type': 'application/json',
    ...options.headers,
  }

  if (token) {
    headers['Authorization'] = `Bearer ${token}`
  }

  const response = await fetch(`${API_URL}${endpoint}`, {
    ...options,
    headers,
  })

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Unknown error' }))
    throw new Error(error.detail || error.error || `Request failed: ${response.status}`)
  }

  return response.json()
}

// ============ User ============
export const getUser = () => request('/api/user')

// ============ Chat (Main Entry Point) ============
export const sendChat = (message, sessionId = null, conversationHistory = null) =>
  request('/api/chat', {
    method: 'POST',
    body: JSON.stringify({
      message,
      session_id: sessionId || undefined,
      conversation_history: conversationHistory || [],
    }),
  })

// ============ Sessions (replaces Plans) ============
// Paginated sessions for sidebar (new format with preview & project_name)
export const getSessions = (page = 1, limit = 20) =>
  request(`/api/sessions?page=${page}&limit=${limit}`)
export const getSession = (sessionId) => request(`/api/sessions/${sessionId}`)
export const resumeSession = (sessionId, answer = null) =>
  request(`/api/sessions/${sessionId}/resume`, {
    method: 'POST',
    body: JSON.stringify({ answer }),
  })

// Legacy plan endpoints (mapped to sessions/list for backwards compatibility)
export const getPlans = () => request('/api/sessions/list')
export const getPlan = (planId) => request(`/api/sessions/${planId}`)
export const createPlan = (data) =>
  request('/api/sessions', { method: 'POST', body: JSON.stringify(data) })

// ============ Approvals ============
export const getApprovals = () => request('/api/approvals')
export const getApproval = (approvalId) => request(`/api/approvals/${approvalId}`)
export const approveApproval = (approvalId, comment = '') =>
  request(`/api/approvals/${approvalId}/approve`, {
    method: 'POST',
    body: JSON.stringify({ comment }),
  })
export const rejectApproval = (approvalId, reason) =>
  request(`/api/approvals/${approvalId}/reject`, {
    method: 'POST',
    body: JSON.stringify({ reason }),
  })

// Legacy task endpoints (mapped to approvals for backwards compatibility)
export const getTasks = () => request('/api/approvals')
export const getTask = (taskId) => request(`/api/approvals/${taskId}`)
export const approveTask = (taskId, comment = '') =>
  request(`/api/approvals/${taskId}/approve`, {
    method: 'POST',
    body: JSON.stringify({ comment }),
  })
export const rejectTask = (taskId, reason) =>
  request(`/api/approvals/${taskId}/reject`, {
    method: 'POST',
    body: JSON.stringify({ reason }),
  })

// ============ MCP Registry ============
export const getMCPs = () => request('/api/mcps')
export const getMCPTools = () => request('/api/mcps/tools')
export const getMCPServers = () => request('/api/mcps/servers')
export const getMCPTool = (toolId) => request(`/api/mcps/tools/${toolId}`)

// Legacy MCP endpoints
export const getMCPRegistry = () => request('/api/mcps')
export const getMCPPermissions = () => request('/api/mcps')
export const checkMCPPermission = (tool) =>
  request('/api/mcps/check', { method: 'POST', body: JSON.stringify({ tool }) })

// ============ Questions (HITL - Human in the Loop) ============
export const getQuestions = (sessionId = null) =>
  request(`/api/questions${sessionId ? `?session_id=${sessionId}` : ''}`)
export const getQuestion = (questionId) => request(`/api/questions/${questionId}`)
export const answerQuestion = (questionId, answer) =>
  request(`/api/questions/${questionId}/answer`, {
    method: 'POST',
    body: JSON.stringify({ answer }),
  })
export const cancelQuestion = (questionId) =>
  request(`/api/questions/${questionId}/cancel`, { method: 'POST' })

// ============ HITL MCP Response (for microservices) ============
export const submitHITLResponse = (requestId, answer, selected = null) =>
  request('/api/hitl/response', {
    method: 'POST',
    body: JSON.stringify({
      request_id: requestId,
      answer,
      selected,
    }),
  })

// ============ Workspace ============
export const getWorkspaceFiles = (sessionId = null) =>
  request(`/api/workspace${sessionId ? `?session_id=${sessionId}` : ''}`)
export const getWorkspaceFile = (path, sessionId = null) => {
  const params = new URLSearchParams({ path })
  if (sessionId) params.append('session_id', sessionId)
  return request(`/api/workspace/file?${params.toString()}`)
}
export const getWorkspaceDownloadUrl = (path, sessionId = null) => {
  const params = new URLSearchParams({ path })
  if (sessionId) params.append('session_id', sessionId)
  return `${API_URL}/api/workspace/download?${params.toString()}`
}

// ============ Projects ============
export const getProjects = () => request('/api/projects')
export const getProject = (projectId) => request(`/api/projects/${projectId}`)
export const buildProject = (projectId) =>
  request(`/api/projects/${projectId}/build`, { method: 'POST' })
export const runProject = (projectId) =>
  request(`/api/projects/${projectId}/run`, { method: 'POST' })
export const stopProject = (projectId) =>
  request(`/api/projects/${projectId}/stop`, { method: 'POST' })
export const deleteProject = (projectId) =>
  request(`/api/projects/${projectId}`, { method: 'DELETE' })
export const getProjectStatus = (projectId) =>
  request(`/api/projects/${projectId}/status`)

// ============ Running Apps ============
export const getRunningApps = () => request('/api/apps/running')

// ============ Health ============
export const getHealth = () => request('/health')
export const getStatus = () => request('/api/status')
