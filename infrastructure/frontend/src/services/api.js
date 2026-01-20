/**
 * API Service for Druppie Backend
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
    const error = await response.json().catch(() => ({ error: 'Unknown error' }))
    throw new Error(error.error || `Request failed: ${response.status}`)
  }

  return response.json()
}

// User
export const getUser = () => request('/api/user')

// Plans
export const getPlans = () => request('/api/plans')
export const getPlan = (planId) => request(`/api/plans/${planId}`)
export const createPlan = (data) =>
  request('/api/plans', { method: 'POST', body: JSON.stringify(data) })
export const executePlan = (planId) =>
  request(`/api/plans/${planId}/execute`, { method: 'POST' })

// Tasks (Approvals)
export const getTasks = () => request('/api/tasks')
export const getTask = (taskId) => request(`/api/tasks/${taskId}`)
export const approveTask = (taskId, comment = '') =>
  request(`/api/tasks/${taskId}/approve`, {
    method: 'POST',
    body: JSON.stringify({ comment }),
  })
export const rejectTask = (taskId, reason) =>
  request(`/api/tasks/${taskId}/reject`, {
    method: 'POST',
    body: JSON.stringify({ reason }),
  })

// MCP Permissions
export const getMCPPermissions = () => request('/api/mcp/permissions')
export const checkMCPPermission = (tool) =>
  request('/api/mcp/check', { method: 'POST', body: JSON.stringify({ tool }) })

// Chat
export const sendChat = (message, planId = null) =>
  request('/api/chat', {
    method: 'POST',
    body: JSON.stringify({ message, plan_id: planId }),
  })

// Workspace
export const getWorkspaceFiles = (planId = null) =>
  request(`/api/workspace${planId ? `?plan_id=${planId}` : ''}`)
export const getWorkspaceFile = (path, planId = null) => {
  const params = new URLSearchParams({ path })
  if (planId) params.append('plan_id', planId)
  return request(`/api/workspace/file?${params.toString()}`)
}
export const getWorkspaceDownloadUrl = (path, planId = null) => {
  const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'
  const params = new URLSearchParams({ path })
  if (planId) params.append('plan_id', planId)
  return `${API_URL}/api/workspace/download?${params.toString()}`
}

// Projects
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
  request(`/api/apps/${projectId}/status`)

// Running Apps
export const getRunningApps = () => request('/api/apps/running')

// MCP Registry
export const getMCPRegistry = () => request('/api/mcp/registry')
export const getMCPTools = () => request('/api/mcp/tools')
export const getMCPTool = (toolId) => request(`/api/mcp/tools/${toolId}`)
export const getMCPServers = () => request('/api/mcp/servers')

// Health
export const getHealth = () => request('/health')
export const getStatus = () => request('/api/status')
