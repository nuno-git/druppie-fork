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

  const method = options.method || 'GET'
  const requestBody = options.body ? JSON.parse(options.body) : null

  // console.group(`🌐 API ${method} ${endpoint}`)
  // console.log('Request:', { method, endpoint, body: requestBody })
  // console.time('Duration')

  try {
    const response = await fetch(`${API_URL}${endpoint}`, {
      ...options,
      headers,
    })

    if (!response.ok) {
      const error = await response.json().catch(() => ({ detail: 'Unknown error' }))
      console.error('❌ Error Response:', { status: response.status, error })
      console.timeEnd('Duration')
      console.groupEnd()
      const msg = [error.message, error.detail, error.error].find(v => typeof v === 'string' && v)
        || `Request failed: ${response.status}`
      const err = new Error(msg)
      err.status = response.status
      throw err
    }

    if (response.status === 204) {
      return null
    }

    const data = await response.json()
    // Only log in development mode
    if (import.meta.env.DEV) {
      console.log('✅ Response:', data)
      console.timeEnd('Duration')
      console.groupEnd()
    }
    return data
  } catch (err) {
    // Only log in development mode
    if (import.meta.env.DEV) {
      console.error('❌ Request Failed:', err.message)
      console.timeEnd('Duration')
      console.groupEnd()
    }
    throw err
  }
}

// ============ User ============
export const getUser = () => request('/api/user')

// ============ Chat (Main Entry Point) ============
export const sendChat = async (message, sessionId = null, conversationHistory = null) => {
  // Note: getMCPServers() was previously called here but the result was unused.
  // The backend handles MCP server selection internally.
  return request('/api/chat', {
    method: 'POST',
    body: JSON.stringify({
      message,
      session_id: sessionId || undefined,
      conversation_history: conversationHistory || [],
    }),
  })
}

export const cancelChat = (sessionId) =>
  request(`/api/chat/${sessionId}/cancel`, { method: 'POST' })

// ============ Sessions (replaces Plans) ============
// Paginated sessions for sidebar
export const getSessions = (page = 1, limit = 20) =>
  request(`/api/sessions?page=${page}&limit=${limit}`)

// Get complete session with ALL data (messages, llm_calls, events, approvals, etc.)
export const getSession = (sessionId) => request(`/api/sessions/${sessionId}`)

export const resumeSession = (sessionId) =>
  request(`/api/sessions/${sessionId}/resume`, { method: 'POST' })

export const deleteSession = (sessionId) =>
  request(`/api/sessions/${sessionId}`, { method: 'DELETE' })

export const retryFromRun = (sessionId, agentRunId, plannedPrompt = null) =>
  request(`/api/sessions/${sessionId}/retry-from/${agentRunId}`, {
    method: 'POST',
    body: plannedPrompt !== null ? JSON.stringify({ planned_prompt: plannedPrompt }) : JSON.stringify({}),
  })

// Legacy aliases (use getSession instead - it returns everything)
export const getSessionTrace = (sessionId) => request(`/api/sessions/${sessionId}`)
export const getPlans = (page = 1, limit = 20) => request(`/api/sessions?page=${page}&limit=${limit}`)
export const getPlan = (planId) => request(`/api/sessions/${planId}`)

// ============ Approvals ============
export const getApprovals = () => request('/api/approvals')
export const getApproval = (approvalId) => request(`/api/approvals/${approvalId}`)
export const approveApproval = (approvalId) =>
  request(`/api/approvals/${approvalId}/approve`, {
    method: 'POST',
  })
export const rejectApproval = (approvalId, reason = '') =>
  request(`/api/approvals/${approvalId}/reject`, {
    method: 'POST',
    body: JSON.stringify({ reason }),
  })

// Legacy task endpoints (mapped to approvals for backwards compatibility)
export const getTasks = () => request('/api/approvals')
export const getTask = (taskId) => request(`/api/approvals/${taskId}`)
export const getApprovalHistory = (page = 1, limit = 20) =>
  request(`/api/approvals/history?page=${page}&limit=${limit}`)
export const approveTask = (taskId) =>
  request(`/api/approvals/${taskId}/approve`, {
    method: 'POST',
  })
export const rejectTask = (taskId, reason = '') =>
  request(`/api/approvals/${taskId}/reject`, {
    method: 'POST',
    body: JSON.stringify({ reason }),
  })
export const getUsersByRole = (role) =>
  request(`/api/approvals/users-by-role/${role}`)

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
export const answerQuestion = (questionId, answer, selectedChoices = null) =>
  request(`/api/questions/${questionId}/answer`, {
    method: 'POST',
    body: JSON.stringify({
      answer,
      ...(selectedChoices != null && { selected_choices: selectedChoices }),
    }),
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

// ============ Deployments ============
export const getDeployments = (projectId = null) => {
  const params = new URLSearchParams()
  if (projectId) params.append('project_id', projectId)
  const qs = params.toString()
  return request(`/api/deployments${qs ? `?${qs}` : ''}`)
}
export const stopDeployment = (containerName) =>
  request(`/api/deployments/${containerName}/stop?remove=true`, { method: 'POST' })
export const getDeploymentLogs = (containerName, tail = 100) =>
  request(`/api/deployments/${containerName}/logs?tail=${tail}`)

// ============ Agents (Transparency) ============
export const getAgents = async () => {
  const response = await request('/api/agents')
  return response.agents || []
}
export const getAgent = (agentId) => request(`/api/agents/${agentId}`)

// ============ Sandbox ============
export const getSandboxEvents = async (sessionId, messageId) => {
  const allEvents = []
  let cursor = null
  // Paginate through all events
  while (true) {
    let url = `/api/sandbox-sessions/${sessionId}/events?limit=500`
    if (messageId) url += `&message_id=${messageId}`
    if (cursor) url += `&cursor=${cursor}`
    const data = await request(url)
    const events = data.events || []
    allEvents.push(...events)
    if (!data.hasMore || !data.cursor) break
    cursor = data.cursor
  }
  return { events: allEvents }
}

// ============ ATK Copilot Agents ============
export const getAtkAgents = (page = 1, limit = 20) =>
  request(`/api/atk-agents?page=${page}&limit=${limit}`)
export const getAtkAgent = (agentId) => request(`/api/atk-agents/${agentId}`)

// ============ Health ============
export const getHealth = () => request('/health')
export const getStatus = () => request('/api/status')

// ============ Admin Database Browser ============
export const getAdminStats = () => request('/api/admin/stats')
export const getAdminTables = () => request('/api/admin/tables')
export const getAdminTableData = (tableName, page = 1, limit = 50, options = {}) => {
  const params = new URLSearchParams({ page, limit })
  if (options.orderBy) params.append('order_by', options.orderBy)
  if (options.orderDir) params.append('order_dir', options.orderDir)
  if (options.filterField) params.append('filter_field', options.filterField)
  if (options.filterValue) params.append('filter_value', options.filterValue)
  return request(`/api/admin/table/${tableName}?${params.toString()}`)
}
export const getAdminRecord = (tableName, recordId) =>
  request(`/api/admin/table/${tableName}/${recordId}`)
