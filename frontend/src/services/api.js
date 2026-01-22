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

export const cancelChat = (sessionId) =>
  request(`/api/chat/${sessionId}/cancel`, { method: 'POST' })

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
    body: JSON.stringify({ approved: true, comment }),
  })
export const rejectApproval = (approvalId, comment = '') =>
  request(`/api/approvals/${approvalId}/approve`, {
    method: 'POST',
    body: JSON.stringify({ approved: false, comment }),
  })

// Legacy task endpoints (mapped to approvals for backwards compatibility)
export const getTasks = () => request('/api/approvals')
export const getTask = (taskId) => request(`/api/approvals/${taskId}`)
export const getApprovalHistory = (limit = 20) =>
  request(`/api/approvals?status=approved&limit=${limit}`)
export const getRejectedApprovals = (limit = 20) =>
  request(`/api/approvals?status=rejected&limit=${limit}`)
export const approveTask = (taskId, comment = '') =>
  request(`/api/approvals/${taskId}/approve`, {
    method: 'POST',
    body: JSON.stringify({ approved: true, comment }),
  })
export const rejectTask = (taskId, comment = '') =>
  request(`/api/approvals/${taskId}/approve`, {
    method: 'POST',
    body: JSON.stringify({ approved: false, comment }),
  })

// ============ MCP Registry ============
export const getMCPs = () => request('/api/mcps')
export const getMCPTools = async () => {
  const response = await request('/api/mcps/tools')
  return response.tools || []
}
export const getMCPServers = async () => {
  const response = await request('/api/mcps/servers')
  return response.servers || []
}
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
export const updateProject = (projectId, data) =>
  request(`/api/projects/${projectId}`, { method: 'PATCH', body: JSON.stringify(data) })

// Project detail endpoints
export const getProjectCommits = (projectId, branch = 'main', limit = 20) =>
  request(`/api/projects/${projectId}/commits?branch=${branch}&limit=${limit}`)
export const getProjectBranches = (projectId) =>
  request(`/api/projects/${projectId}/branches`)
export const getProjectSessions = (projectId, limit = 20) =>
  request(`/api/projects/${projectId}/sessions?limit=${limit}`)
export const getProjectFiles = (projectId, path = '', branch = 'main') =>
  request(`/api/projects/${projectId}/files?path=${encodeURIComponent(path)}&branch=${branch}`)
export const getProjectFile = (projectId, path, branch = 'main') =>
  request(`/api/projects/${projectId}/file?path=${encodeURIComponent(path)}&branch=${branch}`)

// ============ Running Apps ============
export const getRunningApps = () => request('/api/apps/running')

// ============ Agents (Transparency) ============
export const getAgents = async () => {
  const response = await request('/api/agents')
  return response.agents || []
}
export const getAgent = (agentId) => request(`/api/agents/${agentId}`)

// ============ Health ============
export const getHealth = () => request('/health')
export const getStatus = () => request('/api/status')

// ============ Admin Database Viewer ============
export const getAdminStats = () => request('/api/admin/stats')
export const getAdminSessions = (page = 1, limit = 20, status = null, search = null) => {
  const params = new URLSearchParams({ page, limit })
  if (status) params.append('status', status)
  if (search) params.append('search', search)
  return request(`/api/admin/sessions?${params.toString()}`)
}
export const getAdminApprovals = (page = 1, limit = 20, status = null, search = null) => {
  const params = new URLSearchParams({ page, limit })
  if (status) params.append('status', status)
  if (search) params.append('search', search)
  return request(`/api/admin/approvals?${params.toString()}`)
}
export const getAdminProjects = (page = 1, limit = 20, status = null, search = null) => {
  const params = new URLSearchParams({ page, limit })
  if (status) params.append('status', status)
  if (search) params.append('search', search)
  return request(`/api/admin/projects?${params.toString()}`)
}
export const getAdminWorkspaces = (page = 1, limit = 20, search = null) => {
  const params = new URLSearchParams({ page, limit })
  if (search) params.append('search', search)
  return request(`/api/admin/workspaces?${params.toString()}`)
}
export const getAdminHitlQuestions = (page = 1, limit = 20, status = null, search = null) => {
  const params = new URLSearchParams({ page, limit })
  if (status) params.append('status', status)
  if (search) params.append('search', search)
  return request(`/api/admin/hitl-questions?${params.toString()}`)
}
export const getAdminBuilds = (page = 1, limit = 20, status = null, search = null) => {
  const params = new URLSearchParams({ page, limit })
  if (status) params.append('status', status)
  if (search) params.append('search', search)
  return request(`/api/admin/builds?${params.toString()}`)
}
