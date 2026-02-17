/**
 * DebugMCP - Debug page for MCP Bridge API
 *
 * Access at /debug-mcp
 *
 * Uses:
 * - GET /api/mcp/servers - List MCP servers
 * - GET /api/mcp/servers/{server}/tools - List tools for a server
 * - POST /api/mcp/call - Call an MCP tool directly
 */

import React, { useState, useEffect } from 'react'
import { Server, RefreshCw, ChevronDown, ChevronRight, Wrench, Play, AlertCircle, Terminal } from 'lucide-react'
import { getToken } from '../services/keycloak'
import PageHeader from '../components/shared/PageHeader'
import ContainerLogsModal from '../components/shared/ContainerLogsModal'

const MCP_CONTAINER_MAP = {
  coding: 'druppie-mcp-coding',
  docker: 'druppie-mcp-docker',
  filesearch: 'druppie-mcp-filesearch',
  web: 'druppie-mcp-web',
}

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

// Collapsible section
const Collapsible = ({ title, children, defaultOpen = false }) => {
  const [isOpen, setIsOpen] = useState(defaultOpen)
  return (
    <div className="bg-white border border-gray-100 rounded-xl overflow-hidden mb-3">
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="w-full text-left px-4 py-3 hover:bg-gray-50 flex items-center gap-2 font-medium transition-colors"
      >
        {isOpen ? <ChevronDown className="w-4 h-4 text-gray-400" /> : <ChevronRight className="w-4 h-4 text-gray-400" />}
        <span className="flex-1 text-sm">{title}</span>
      </button>
      {isOpen && <div className="px-4 pb-4 border-t border-gray-50">{children}</div>}
    </div>
  )
}

// Tool card with call UI
const ToolCard = ({ server, tool, onCall }) => {
  const [args, setArgs] = useState('{}')
  const [sessionId, setSessionId] = useState('')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState(null)

  const handleCall = async () => {
    setLoading(true)
    setResult(null)

    let parsedArgs = {}
    try {
      parsedArgs = JSON.parse(args)
    } catch (e) {
      setResult({ ok: false, error: 'Invalid JSON in arguments' })
      setLoading(false)
      return
    }

    const response = await apiFetch('/api/mcp/call', {
      method: 'POST',
      body: JSON.stringify({
        server,
        tool: tool.name,
        args: parsedArgs,
        session_id: sessionId || undefined,
      }),
    })

    setResult(response)
    setLoading(false)
  }

  return (
    <div className="border rounded-lg p-3 bg-white mb-2">
      <div className="flex items-center justify-between mb-2">
        <div>
          <code className="text-purple-600 font-semibold">{tool.name}</code>
          {tool.requires_approval && (
            <span className="ml-2 px-2 py-0.5 bg-blue-100 text-blue-700 text-xs rounded">
              Needs: {tool.required_role}
            </span>
          )}
        </div>
      </div>

      <p className="text-sm text-gray-600 mb-3">{tool.description}</p>

      {/* Parameters hint */}
      {tool.parameters?.properties && (
        <div className="text-xs text-gray-400 mb-2">
          Parameters: {Object.keys(tool.parameters.properties).join(', ')}
          {tool.parameters.required?.length > 0 && (
            <span className="text-red-400"> (required: {tool.parameters.required.join(', ')})</span>
          )}
        </div>
      )}

      {/* Args input */}
      <div className="space-y-2">
        <div>
          <label className="text-xs text-gray-500">Arguments (JSON):</label>
          <textarea
            value={args}
            onChange={(e) => setArgs(e.target.value)}
            className="w-full px-2 py-1 border rounded text-sm font-mono h-20"
            placeholder='{"path": "."}'
          />
        </div>

        <div>
          <label className="text-xs text-gray-500">Session ID (optional, for workspace):</label>
          <input
            type="text"
            value={sessionId}
            onChange={(e) => setSessionId(e.target.value)}
            className="w-full px-2 py-1 border rounded text-sm"
            placeholder="e.g., 550e8400-e29b-41d4-a716-446655440000"
          />
        </div>

        <button
          onClick={handleCall}
          disabled={loading}
          className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50 text-sm"
        >
          {loading ? 'Calling...' : `Call ${tool.name}`}
        </button>
      </div>

      {/* Result */}
      {result && (
        <div className={`mt-3 p-2 rounded text-sm ${result.ok ? 'bg-green-50' : 'bg-red-50'}`}>
          <div className="font-medium mb-1">
            {result.ok ? '✓ Success' : '✗ Error'}
          </div>
          <pre className="text-xs overflow-auto max-h-60 bg-white p-2 rounded border">
            {JSON.stringify(result.data, null, 2)}
          </pre>
        </div>
      )}
    </div>
  )
}

// Server card with tools
const ServerCard = ({ server }) => {
  const [tools, setTools] = useState(null)
  const [loading, setLoading] = useState(false)
  const [showLogs, setShowLogs] = useState(false)

  const containerName = MCP_CONTAINER_MAP[server.name] || `druppie-mcp-${server.name}`

  const loadTools = async () => {
    if (tools) return // Already loaded
    setLoading(true)
    const response = await apiFetch(`/api/mcp/servers/${server.name}/tools`)
    setTools(response)
    setLoading(false)
  }

  return (
    <div className="bg-white border border-gray-100 rounded-xl overflow-hidden mb-4">
      <div className="flex items-center gap-3 px-4 py-4">
        <button
          onClick={loadTools}
          className="flex-1 text-left flex items-center gap-3 hover:opacity-80 transition-opacity"
        >
          <div className="w-10 h-10 rounded-lg bg-gray-100 flex items-center justify-center flex-shrink-0">
            <Server className="w-5 h-5 text-gray-500" />
          </div>
          <div className="flex-1">
            <div className="font-semibold text-gray-900">{server.name}</div>
            <div className="text-sm text-gray-500">{server.description}</div>
            <div className="text-xs text-gray-400 font-mono mt-0.5">{server.url}</div>
          </div>
        </button>
        <div className="flex items-center gap-2 flex-shrink-0">
          <button
            onClick={() => setShowLogs(true)}
            className="p-1.5 rounded text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors"
            title={`View ${server.name} logs`}
          >
            <Terminal className="w-4 h-4" />
          </button>
          {server.builtin && (
            <span className="px-2.5 py-1 bg-purple-100 text-purple-700 text-xs rounded-full font-medium">
              Built-in
            </span>
          )}
        </div>
      </div>

      {loading && (
        <div className="p-4 text-gray-500">Loading tools...</div>
      )}

      {tools && (
        <div className="p-4 border-t bg-white">
          {!tools.ok ? (
            <div className="text-red-600">
              Error loading tools: {tools.error || tools.data?.detail}
            </div>
          ) : tools.data?.tools?.length === 0 ? (
            <div className="text-gray-500 italic">No tools available</div>
          ) : (
            <div className="space-y-2">
              {tools.data.tools.map((tool) => (
                <ToolCard
                  key={tool.name}
                  server={server.name}
                  tool={tool}
                />
              ))}
            </div>
          )}
        </div>
      )}

      {showLogs && (
        <ContainerLogsModal
          containerName={containerName}
          onClose={() => setShowLogs(false)}
        />
      )}
    </div>
  )
}

export default function DebugMCP() {
  const [servers, setServers] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    loadServers()
  }, [])

  const loadServers = async () => {
    setLoading(true)
    const response = await apiFetch('/api/mcp/servers')
    setServers(response)
    setLoading(false)
  }

  return (
    <div className="space-y-6">
      <PageHeader title="MCP Bridge Test" subtitle="Test MCP server tools directly via REST API.">
        <button
          onClick={loadServers}
          disabled={loading}
          className="inline-flex items-center gap-2 px-4 py-2 text-sm bg-white border border-gray-200 rounded-lg hover:bg-gray-50 transition-colors disabled:opacity-50"
        >
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </PageHeader>

      <div className="p-3 bg-amber-50 text-amber-800 rounded-lg text-sm border border-amber-100">
        <strong>Note:</strong> This page calls MCP tools directly, bypassing the agent workflow
        and approval system. Use for testing MCP connectivity only.
      </div>

      {/* Error state */}
      {servers && !servers.ok && (
        <div className="bg-red-50 text-red-800 p-4 rounded mb-4">
          Error loading servers: {servers.error || servers.data?.detail}
        </div>
      )}

      {/* Servers list */}
      {servers?.ok && servers.data?.servers && (
        <div>
          <h2 className="text-lg font-semibold mb-3">
            MCP Servers ({servers.data.servers.length})
          </h2>
          {servers.data.servers.map((server) => (
            <ServerCard key={server.name} server={server} />
          ))}
        </div>
      )}

      {/* Debug: Raw response */}
      <details className="mt-8">
        <summary className="cursor-pointer text-sm text-gray-500 hover:text-gray-700">
          Show raw servers response
        </summary>
        <pre className="mt-2 bg-gray-100 p-3 rounded text-xs overflow-auto max-h-60">
          {JSON.stringify(servers, null, 2)}
        </pre>
      </details>
    </div>
  )
}
