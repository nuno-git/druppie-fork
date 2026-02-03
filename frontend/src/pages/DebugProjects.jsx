/**
 * DebugProjects - Debug page for Projects & Deployments API
 *
 * Access at /debug-projects
 *
 * Uses:
 * Projects API:
 * - GET /api/projects - List projects (paginated)
 * - GET /api/projects/{project_id} - Get project detail
 * - DELETE /api/projects/{project_id} - Delete/archive project
 *
 * Deployments API (Docker MCP Bridge):
 * - GET /api/deployments - List running deployments
 * - POST /api/deployments/{container_name}/stop - Stop a deployment
 * - GET /api/deployments/{container_name}/logs - Get container logs
 * - GET /api/deployments/{container_name} - Inspect a deployment
 */

import React, { useState, useEffect } from 'react'
import { getToken } from '../services/keycloak'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

// Simple fetch wrapper with auth
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

    // Handle 204 No Content
    if (response.status === 204) {
      console.log('Response: 204 No Content')
      return { ok: true, status: 204, data: null }
    }

    const data = await response.json()
    console.log('Response:', data)
    return { ok: response.ok, status: response.status, data }
  } catch (err) {
    console.error('Error:', err)
    return { ok: false, error: err.message }
  }
}

// Collapsible section component
const Collapsible = ({ title, children, defaultOpen = false }) => {
  const [isOpen, setIsOpen] = useState(defaultOpen)
  return (
    <div className="border rounded-lg overflow-hidden mb-2">
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="w-full text-left px-3 py-2 bg-gray-100 hover:bg-gray-200 flex items-center gap-2 font-medium"
      >
        <span className="text-gray-500">{isOpen ? '▼' : '▶'}</span>
        <span className="flex-1">{title}</span>
      </button>
      {isOpen && <div className="p-3 border-t bg-white">{children}</div>}
    </div>
  )
}

// Result display component
const ResultBox = ({ result, title = 'Response' }) => {
  if (!result) return null

  return (
    <div className={`mt-3 p-2 rounded text-sm ${result.ok ? 'bg-green-50' : 'bg-red-50'}`}>
      <div className="font-medium mb-1">
        {result.ok ? `✓ ${title}` : `✗ Error (${result.status || 'network'})`}
      </div>
      <pre className="text-xs overflow-auto max-h-60 bg-white p-2 rounded border">
        {JSON.stringify(result.data || result.error, null, 2)}
      </pre>
    </div>
  )
}

// =============================================================================
// PROJECTS SECTION
// =============================================================================

const ProjectsSection = () => {
  const [projects, setProjects] = useState(null)
  const [loading, setLoading] = useState(false)
  const [page, setPage] = useState(1)
  const [limit, setLimit] = useState(10)

  // Get project detail state
  const [projectId, setProjectId] = useState('')
  const [projectDetail, setProjectDetail] = useState(null)
  const [detailLoading, setDetailLoading] = useState(false)

  // Delete project state
  const [deleteId, setDeleteId] = useState('')
  const [deleteResult, setDeleteResult] = useState(null)
  const [deleteLoading, setDeleteLoading] = useState(false)

  const loadProjects = async () => {
    setLoading(true)
    const response = await apiFetch(`/api/projects?page=${page}&limit=${limit}`)
    setProjects(response)
    setLoading(false)
  }

  const getProjectDetail = async () => {
    if (!projectId.trim()) return
    setDetailLoading(true)
    setProjectDetail(null)
    const response = await apiFetch(`/api/projects/${projectId}`)
    setProjectDetail(response)
    setDetailLoading(false)
  }

  const deleteProject = async () => {
    if (!deleteId.trim()) return
    if (!confirm(`Are you sure you want to delete project ${deleteId}?`)) return

    setDeleteLoading(true)
    setDeleteResult(null)
    const response = await apiFetch(`/api/projects/${deleteId}`, { method: 'DELETE' })
    setDeleteResult(response)
    setDeleteLoading(false)
  }

  useEffect(() => {
    loadProjects()
  }, [])

  return (
    <div className="space-y-4">
      {/* List Projects */}
      <Collapsible title="GET /api/projects - List Projects" defaultOpen={true}>
        <div className="space-y-3">
          <div className="flex gap-4 items-end">
            <div>
              <label className="text-xs text-gray-500 block">Page:</label>
              <input
                type="number"
                value={page}
                onChange={(e) => setPage(parseInt(e.target.value) || 1)}
                className="w-20 px-2 py-1 border rounded text-sm"
                min="1"
              />
            </div>
            <div>
              <label className="text-xs text-gray-500 block">Limit:</label>
              <input
                type="number"
                value={limit}
                onChange={(e) => setLimit(parseInt(e.target.value) || 10)}
                className="w-20 px-2 py-1 border rounded text-sm"
                min="1"
                max="100"
              />
            </div>
            <button
              onClick={loadProjects}
              disabled={loading}
              className="px-4 py-1.5 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50 text-sm"
            >
              {loading ? 'Loading...' : 'Fetch Projects'}
            </button>
          </div>

          <ResultBox result={projects} title="Projects List" />

          {/* Quick project cards */}
          {projects?.ok && projects.data?.items?.length > 0 && (
            <div className="mt-3">
              <div className="text-sm font-medium mb-2">Quick View ({projects.data.total} total):</div>
              <div className="grid gap-2">
                {projects.data.items.map((project) => (
                  <div
                    key={project.id}
                    className="p-2 bg-gray-50 rounded border text-sm flex justify-between items-center"
                  >
                    <div>
                      <span className="font-medium">{project.name}</span>
                      <span className="text-gray-500 ml-2 text-xs">{project.id}</span>
                    </div>
                    <div className="flex gap-2">
                      <button
                        onClick={() => {
                          setProjectId(project.id)
                          getProjectDetail()
                        }}
                        className="px-2 py-0.5 bg-blue-100 text-blue-700 rounded text-xs hover:bg-blue-200"
                      >
                        Detail
                      </button>
                      <button
                        onClick={() => setDeleteId(project.id)}
                        className="px-2 py-0.5 bg-red-100 text-red-700 rounded text-xs hover:bg-red-200"
                      >
                        Select for Delete
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </Collapsible>

      {/* Get Project Detail */}
      <Collapsible title="GET /api/projects/{project_id} - Project Detail">
        <div className="space-y-3">
          <div className="flex gap-4 items-end">
            <div className="flex-1">
              <label className="text-xs text-gray-500 block">Project ID (UUID):</label>
              <input
                type="text"
                value={projectId}
                onChange={(e) => setProjectId(e.target.value)}
                className="w-full px-2 py-1 border rounded text-sm font-mono"
                placeholder="e.g., 550e8400-e29b-41d4-a716-446655440000"
              />
            </div>
            <button
              onClick={getProjectDetail}
              disabled={detailLoading || !projectId.trim()}
              className="px-4 py-1.5 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50 text-sm"
            >
              {detailLoading ? 'Loading...' : 'Get Detail'}
            </button>
          </div>

          <ResultBox result={projectDetail} title="Project Detail" />
        </div>
      </Collapsible>

      {/* Delete Project */}
      <Collapsible title="DELETE /api/projects/{project_id} - Delete Project">
        <div className="space-y-3">
          <div className="p-2 bg-yellow-50 text-yellow-800 rounded text-xs">
            Warning: This archives the project. Use with caution!
          </div>
          <div className="flex gap-4 items-end">
            <div className="flex-1">
              <label className="text-xs text-gray-500 block">Project ID (UUID):</label>
              <input
                type="text"
                value={deleteId}
                onChange={(e) => setDeleteId(e.target.value)}
                className="w-full px-2 py-1 border rounded text-sm font-mono"
                placeholder="e.g., 550e8400-e29b-41d4-a716-446655440000"
              />
            </div>
            <button
              onClick={deleteProject}
              disabled={deleteLoading || !deleteId.trim()}
              className="px-4 py-1.5 bg-red-600 text-white rounded hover:bg-red-700 disabled:opacity-50 text-sm"
            >
              {deleteLoading ? 'Deleting...' : 'Delete Project'}
            </button>
          </div>

          <ResultBox result={deleteResult} title="Delete Result" />
        </div>
      </Collapsible>
    </div>
  )
}

// =============================================================================
// DEPLOYMENTS SECTION
// =============================================================================

const DeploymentsSection = () => {
  const [deployments, setDeployments] = useState(null)
  const [loading, setLoading] = useState(false)
  const [projectIdFilter, setProjectIdFilter] = useState('')
  const [sessionIdFilter, setSessionIdFilter] = useState('')
  const [allContainers, setAllContainers] = useState(false)

  // Stop deployment state
  const [stopName, setStopName] = useState('')
  const [removeOnStop, setRemoveOnStop] = useState(true)
  const [stopResult, setStopResult] = useState(null)
  const [stopLoading, setStopLoading] = useState(false)

  // Get logs state
  const [logsName, setLogsName] = useState('')
  const [tailLines, setTailLines] = useState(100)
  const [logsResult, setLogsResult] = useState(null)
  const [logsLoading, setLogsLoading] = useState(false)

  // Inspect state
  const [inspectName, setInspectName] = useState('')
  const [inspectResult, setInspectResult] = useState(null)
  const [inspectLoading, setInspectLoading] = useState(false)

  const loadDeployments = async () => {
    setLoading(true)
    let url = `/api/deployments?all_containers=${allContainers}`
    if (projectIdFilter.trim()) url += `&project_id=${projectIdFilter}`
    if (sessionIdFilter.trim()) url += `&session_id=${sessionIdFilter}`

    const response = await apiFetch(url)
    setDeployments(response)
    setLoading(false)
  }

  const stopDeployment = async () => {
    if (!stopName.trim()) return
    if (!confirm(`Are you sure you want to stop container "${stopName}"?`)) return

    setStopLoading(true)
    setStopResult(null)
    const response = await apiFetch(`/api/deployments/${stopName}/stop?remove=${removeOnStop}`, {
      method: 'POST',
    })
    setStopResult(response)
    setStopLoading(false)

    // Refresh list after stopping
    if (response.ok) loadDeployments()
  }

  const getLogs = async () => {
    if (!logsName.trim()) return

    setLogsLoading(true)
    setLogsResult(null)
    const response = await apiFetch(`/api/deployments/${logsName}/logs?tail=${tailLines}`)
    setLogsResult(response)
    setLogsLoading(false)
  }

  const inspectDeployment = async () => {
    if (!inspectName.trim()) return

    setInspectLoading(true)
    setInspectResult(null)
    const response = await apiFetch(`/api/deployments/${inspectName}`)
    setInspectResult(response)
    setInspectLoading(false)
  }

  useEffect(() => {
    loadDeployments()
  }, [])

  return (
    <div className="space-y-4">
      {/* List Deployments */}
      <Collapsible title="GET /api/deployments - List Deployments" defaultOpen={true}>
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="text-xs text-gray-500 block">Filter by Project ID:</label>
              <input
                type="text"
                value={projectIdFilter}
                onChange={(e) => setProjectIdFilter(e.target.value)}
                className="w-full px-2 py-1 border rounded text-sm font-mono"
                placeholder="Optional UUID"
              />
            </div>
            <div>
              <label className="text-xs text-gray-500 block">Filter by Session ID:</label>
              <input
                type="text"
                value={sessionIdFilter}
                onChange={(e) => setSessionIdFilter(e.target.value)}
                className="w-full px-2 py-1 border rounded text-sm font-mono"
                placeholder="Optional UUID"
              />
            </div>
          </div>

          <div className="flex gap-4 items-center">
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={allContainers}
                onChange={(e) => setAllContainers(e.target.checked)}
              />
              Include stopped containers
            </label>
            <button
              onClick={loadDeployments}
              disabled={loading}
              className="px-4 py-1.5 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50 text-sm"
            >
              {loading ? 'Loading...' : 'Fetch Deployments'}
            </button>
          </div>

          <ResultBox result={deployments} title="Deployments List" />

          {/* Quick deployment cards */}
          {deployments?.ok && deployments.data?.items?.length > 0 && (
            <div className="mt-3">
              <div className="text-sm font-medium mb-2">Running Deployments ({deployments.data.count}):</div>
              <div className="grid gap-2">
                {deployments.data.items.map((deployment) => (
                  <div
                    key={deployment.container_id}
                    className="p-2 bg-gray-50 rounded border text-sm"
                  >
                    <div className="flex justify-between items-start">
                      <div>
                        <div className="font-medium">{deployment.container_name}</div>
                        <div className="text-xs text-gray-500">
                          Image: {deployment.image} | Status:
                          <span className={deployment.status.includes('Up') ? 'text-green-600' : 'text-yellow-600'}>
                            {' '}{deployment.status}
                          </span>
                        </div>
                        {deployment.app_url && (
                          <div className="text-xs">
                            URL: <a href={deployment.app_url} target="_blank" rel="noopener noreferrer" className="text-blue-600 hover:underline">{deployment.app_url}</a>
                          </div>
                        )}
                        {deployment.project_id && (
                          <div className="text-xs text-gray-400">Project: {deployment.project_id}</div>
                        )}
                      </div>
                      <div className="flex gap-1">
                        <button
                          onClick={() => {
                            setLogsName(deployment.container_name)
                          }}
                          className="px-2 py-0.5 bg-gray-100 text-gray-700 rounded text-xs hover:bg-gray-200"
                        >
                          Logs
                        </button>
                        <button
                          onClick={() => {
                            setInspectName(deployment.container_name)
                          }}
                          className="px-2 py-0.5 bg-blue-100 text-blue-700 rounded text-xs hover:bg-blue-200"
                        >
                          Inspect
                        </button>
                        <button
                          onClick={() => {
                            setStopName(deployment.container_name)
                          }}
                          className="px-2 py-0.5 bg-red-100 text-red-700 rounded text-xs hover:bg-red-200"
                        >
                          Stop
                        </button>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </Collapsible>

      {/* Stop Deployment */}
      <Collapsible title="POST /api/deployments/{container_name}/stop - Stop Deployment">
        <div className="space-y-3">
          <div className="p-2 bg-yellow-50 text-yellow-800 rounded text-xs">
            Warning: This will stop (and optionally remove) the container!
          </div>
          <div className="flex gap-4 items-end">
            <div className="flex-1">
              <label className="text-xs text-gray-500 block">Container Name:</label>
              <input
                type="text"
                value={stopName}
                onChange={(e) => setStopName(e.target.value)}
                className="w-full px-2 py-1 border rounded text-sm font-mono"
                placeholder="e.g., my-app-container"
              />
            </div>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={removeOnStop}
                onChange={(e) => setRemoveOnStop(e.target.checked)}
              />
              Remove after stop
            </label>
            <button
              onClick={stopDeployment}
              disabled={stopLoading || !stopName.trim()}
              className="px-4 py-1.5 bg-red-600 text-white rounded hover:bg-red-700 disabled:opacity-50 text-sm"
            >
              {stopLoading ? 'Stopping...' : 'Stop Container'}
            </button>
          </div>

          <ResultBox result={stopResult} title="Stop Result" />
        </div>
      </Collapsible>

      {/* Get Logs */}
      <Collapsible title="GET /api/deployments/{container_name}/logs - Get Logs">
        <div className="space-y-3">
          <div className="flex gap-4 items-end">
            <div className="flex-1">
              <label className="text-xs text-gray-500 block">Container Name:</label>
              <input
                type="text"
                value={logsName}
                onChange={(e) => setLogsName(e.target.value)}
                className="w-full px-2 py-1 border rounded text-sm font-mono"
                placeholder="e.g., my-app-container"
              />
            </div>
            <div>
              <label className="text-xs text-gray-500 block">Tail Lines:</label>
              <input
                type="number"
                value={tailLines}
                onChange={(e) => setTailLines(parseInt(e.target.value) || 100)}
                className="w-24 px-2 py-1 border rounded text-sm"
                min="1"
                max="1000"
              />
            </div>
            <button
              onClick={getLogs}
              disabled={logsLoading || !logsName.trim()}
              className="px-4 py-1.5 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50 text-sm"
            >
              {logsLoading ? 'Loading...' : 'Get Logs'}
            </button>
          </div>

          {logsResult && (
            <div className={`mt-3 p-2 rounded text-sm ${logsResult.ok ? 'bg-green-50' : 'bg-red-50'}`}>
              <div className="font-medium mb-1">
                {logsResult.ok ? '✓ Logs' : `✗ Error (${logsResult.status || 'network'})`}
              </div>
              {logsResult.ok && logsResult.data?.logs ? (
                <pre className="text-xs overflow-auto max-h-80 bg-black text-green-400 p-2 rounded font-mono whitespace-pre-wrap">
                  {logsResult.data.logs || '(no logs)'}
                </pre>
              ) : (
                <pre className="text-xs overflow-auto max-h-60 bg-white p-2 rounded border">
                  {JSON.stringify(logsResult.data || logsResult.error, null, 2)}
                </pre>
              )}
            </div>
          )}
        </div>
      </Collapsible>

      {/* Inspect Deployment */}
      <Collapsible title="GET /api/deployments/{container_name} - Inspect Deployment">
        <div className="space-y-3">
          <div className="flex gap-4 items-end">
            <div className="flex-1">
              <label className="text-xs text-gray-500 block">Container Name:</label>
              <input
                type="text"
                value={inspectName}
                onChange={(e) => setInspectName(e.target.value)}
                className="w-full px-2 py-1 border rounded text-sm font-mono"
                placeholder="e.g., my-app-container"
              />
            </div>
            <button
              onClick={inspectDeployment}
              disabled={inspectLoading || !inspectName.trim()}
              className="px-4 py-1.5 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50 text-sm"
            >
              {inspectLoading ? 'Loading...' : 'Inspect'}
            </button>
          </div>

          <ResultBox result={inspectResult} title="Container Details" />
        </div>
      </Collapsible>
    </div>
  )
}

// =============================================================================
// MAIN PAGE
// =============================================================================

export default function DebugProjects() {
  const [activeTab, setActiveTab] = useState('projects')

  return (
    <div className="p-6 max-w-4xl mx-auto">
      <div className="mb-6">
        <h1 className="text-2xl font-bold">Projects & Deployments API Test</h1>
        <p className="text-gray-600">
          Test Projects and Deployments (Docker MCP Bridge) APIs
        </p>
      </div>

      <div className="mb-4 p-3 bg-blue-50 text-blue-800 rounded text-sm">
        <strong>Note:</strong> This page directly calls the Projects and Deployments APIs with your
        authenticated user. Admin users see all data; regular users see only their own.
      </div>

      {/* Tab Navigation */}
      <div className="flex gap-2 mb-6 border-b">
        <button
          onClick={() => setActiveTab('projects')}
          className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px ${
            activeTab === 'projects'
              ? 'border-blue-600 text-blue-600'
              : 'border-transparent text-gray-500 hover:text-gray-700'
          }`}
        >
          Projects API
        </button>
        <button
          onClick={() => setActiveTab('deployments')}
          className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px ${
            activeTab === 'deployments'
              ? 'border-blue-600 text-blue-600'
              : 'border-transparent text-gray-500 hover:text-gray-700'
          }`}
        >
          Deployments API (Docker)
        </button>
      </div>

      {/* API Info */}
      <div className="mb-6 text-sm text-gray-500">
        <strong>Endpoints:</strong>
        {activeTab === 'projects' ? (
          <ul className="list-disc ml-5 mt-1">
            <li>GET /api/projects - List projects (paginated)</li>
            <li>GET /api/projects/{'{project_id}'} - Get project detail</li>
            <li>DELETE /api/projects/{'{project_id}'} - Delete/archive project</li>
          </ul>
        ) : (
          <ul className="list-disc ml-5 mt-1">
            <li>GET /api/deployments - List running deployments</li>
            <li>POST /api/deployments/{'{container_name}'}/stop - Stop deployment</li>
            <li>GET /api/deployments/{'{container_name}'}/logs - Get container logs</li>
            <li>GET /api/deployments/{'{container_name}'} - Inspect container</li>
          </ul>
        )}
      </div>

      {/* Tab Content */}
      {activeTab === 'projects' ? <ProjectsSection /> : <DeploymentsSection />}
    </div>
  )
}
