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
            <span className="ml-2 px-2 py-0.5 bg-yellow-100 text-yellow-800 text-xs rounded">
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

  const loadTools = async () => {
    if (tools) return // Already loaded
    setLoading(true)
    const response = await apiFetch(`/api/mcp/servers/${server.name}/tools`)
    setTools(response)
    setLoading(false)
  }

  return (
    <div className="border rounded-lg overflow-hidden mb-4">
      <button
        onClick={loadTools}
        className="w-full text-left px-4 py-3 bg-gray-50 hover:bg-gray-100 flex items-center gap-3"
      >
        <span className="text-2xl">{server.builtin ? '🔧' : '🌐'}</span>
        <div className="flex-1">
          <div className="font-semibold text-lg">{server.name}</div>
          <div className="text-sm text-gray-500">{server.description}</div>
          <div className="text-xs text-gray-400">{server.url}</div>
        </div>
        {server.builtin && (
          <span className="px-2 py-1 bg-purple-100 text-purple-700 text-xs rounded">
            Built-in
          </span>
        )}
      </button>

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
    <div className="p-6 max-w-4xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold">MCP Bridge Test Page</h1>
          <p className="text-gray-600">
            Test MCP server tools directly via REST API
          </p>
        </div>
        <button
          onClick={loadServers}
          disabled={loading}
          className="px-4 py-2 bg-gray-200 rounded hover:bg-gray-300 text-sm"
        >
          {loading ? 'Loading...' : 'Refresh'}
        </button>
      </div>

      <div className="mb-4 p-3 bg-blue-50 text-blue-800 rounded text-sm">
        <strong>Note:</strong> This page calls MCP tools directly, bypassing the agent workflow
        and approval system. Use for testing MCP connectivity only.
      </div>

      {/* API Info */}
      <div className="mb-6 text-sm text-gray-500">
        <strong>Endpoints:</strong>
        <ul className="list-disc ml-5 mt-1">
          <li>GET /api/mcp/servers - List servers</li>
          <li>GET /api/mcp/servers/{'{server}'}/tools - List tools</li>
          <li>POST /api/mcp/call - Call a tool</li>
        </ul>
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
