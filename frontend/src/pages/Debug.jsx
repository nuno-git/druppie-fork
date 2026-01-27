/**
 * Debug Page - Execution Trace Viewer
 * Displays detailed execution traces for a session with expandable tree view
 */

import React, { useState, useEffect } from 'react'
import { useParams, Link } from 'react-router-dom'
import {
  Bot,
  Hammer,
  Brain,
  Clock,
  ChevronDown,
  ChevronRight,
  AlertCircle,
  CheckCircle,
  XCircle,
  Loader2,
  ArrowLeft,
  Activity,
  Zap,
  FileCode,
  Terminal,
  Database,
  Timer,
  Hash,
  Copy,
  Check,
} from 'lucide-react'
import { useAuth } from '../App'
import { getToken } from '../services/keycloak'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

// Fetch session trace
const getSessionTrace = async (sessionId) => {
  const token = getToken()
  const headers = {
    'Content-Type': 'application/json',
  }
  if (token) {
    headers['Authorization'] = `Bearer ${token}`
  }

  const response = await fetch(`${API_URL}/api/sessions/${sessionId}/trace`, { headers })
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Unknown error' }))
    throw new Error(error.detail || `Request failed: ${response.status}`)
  }
  return response.json()
}

// Icon mapping for trace event types
const getEventTypeIcon = (eventType) => {
  const iconProps = { className: 'w-4 h-4' }

  switch (eventType) {
    case 'agent':
    case 'agent_started':
    case 'agent_completed':
      return <Bot {...iconProps} />
    case 'tool':
    case 'tool_executing':
    case 'tool_completed':
    case 'mcp_tool':
      return <Hammer {...iconProps} />
    case 'llm':
    case 'llm_calling':
    case 'llm_response':
      return <Brain {...iconProps} />
    case 'workflow':
    case 'workflow_started':
    case 'workflow_completed':
      return <Zap {...iconProps} />
    case 'task':
    case 'task_executing':
    case 'task_completed':
      return <Activity {...iconProps} />
    case 'file':
    case 'file_created':
    case 'file_modified':
      return <FileCode {...iconProps} />
    case 'command':
    case 'run_command':
      return <Terminal {...iconProps} />
    case 'database':
    case 'db_query':
      return <Database {...iconProps} />
    default:
      return <Clock {...iconProps} />
  }
}

// Status badge component
const StatusBadge = ({ status }) => {
  const statusConfig = {
    success: { bg: 'bg-green-100', text: 'text-green-700', icon: CheckCircle },
    completed: { bg: 'bg-green-100', text: 'text-green-700', icon: CheckCircle },
    error: { bg: 'bg-red-100', text: 'text-red-700', icon: XCircle },
    failed: { bg: 'bg-red-100', text: 'text-red-700', icon: XCircle },
    running: { bg: 'bg-blue-100', text: 'text-blue-700', icon: Loader2 },
    working: { bg: 'bg-blue-100', text: 'text-blue-700', icon: Loader2 },
    pending: { bg: 'bg-yellow-100', text: 'text-yellow-700', icon: Clock },
    warning: { bg: 'bg-yellow-100', text: 'text-yellow-700', icon: AlertCircle },
  }

  const config = statusConfig[status] || { bg: 'bg-gray-100', text: 'text-gray-700', icon: Clock }
  const Icon = config.icon

  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${config.bg} ${config.text}`}>
      <Icon className={`w-3 h-3 ${status === 'running' || status === 'working' ? 'animate-spin' : ''}`} />
      {status}
    </span>
  )
}

// Duration formatter
const formatDuration = (ms) => {
  if (!ms && ms !== 0) return '-'
  if (ms < 1000) return `${ms}ms`
  if (ms < 60000) return `${(ms / 1000).toFixed(2)}s`
  const minutes = Math.floor(ms / 60000)
  const seconds = ((ms % 60000) / 1000).toFixed(1)
  return `${minutes}m ${seconds}s`
}

// Timestamp formatter
const formatTimestamp = (timestamp) => {
  if (!timestamp) return '-'
  const date = new Date(timestamp)
  return date.toLocaleTimeString('en-US', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    fractionalSecondDigits: 3,
  })
}

// JSON viewer component for expandable details
const JsonViewer = ({ data, label }) => {
  const [isExpanded, setIsExpanded] = useState(false)
  const [copied, setCopied] = useState(false)

  if (!data || (typeof data === 'object' && Object.keys(data).length === 0)) {
    return null
  }

  const jsonString = typeof data === 'string' ? data : JSON.stringify(data, null, 2)

  const handleCopy = async (e) => {
    e.stopPropagation()
    try {
      await navigator.clipboard.writeText(jsonString)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch (err) {
      console.error('Failed to copy to clipboard:', err)
    }
  }

  return (
    <div className="mt-2">
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="flex items-center gap-1 text-xs text-gray-500 hover:text-gray-700"
      >
        {isExpanded ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
        <span className="font-medium">{label}</span>
      </button>
      {isExpanded && (
        <div className="mt-1 relative">
          <button
            onClick={handleCopy}
            className="absolute top-2 right-2 p-1 rounded bg-gray-700 hover:bg-gray-600 text-gray-300"
            title="Copy to clipboard"
          >
            {copied ? <Check className="w-3 h-3" /> : <Copy className="w-3 h-3" />}
          </button>
          <pre className="bg-gray-800 text-gray-100 p-3 rounded-lg text-xs overflow-x-auto max-h-64 overflow-y-auto">
            {jsonString}
          </pre>
        </div>
      )}
    </div>
  )
}

// Copy button component for reuse
const CopyButton = ({ text, label = "Copy" }) => {
  const [copied, setCopied] = useState(false)

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch (err) {
      console.error('Failed to copy:', err)
    }
  }

  return (
    <button
      onClick={handleCopy}
      className="flex items-center gap-1 px-2 py-1 text-xs bg-gray-700 hover:bg-gray-600 text-gray-200 rounded transition-colors"
      title={label}
    >
      {copied ? <Check className="w-3 h-3" /> : <Copy className="w-3 h-3" />}
      <span>{copied ? 'Copied!' : label}</span>
    </button>
  )
}

// Raw LLM Call viewer component
const RawLLMCallViewer = ({ call, index }) => {
  const [isExpanded, setIsExpanded] = useState(false)
  const [activeSection, setActiveSection] = useState('messages')

  const fullRequestJson = JSON.stringify({
    messages: call.messages,
    tools: call.tools,
  }, null, 2)

  const fullResponseJson = JSON.stringify(call.response, null, 2)

  const fullCallJson = JSON.stringify(call, null, 2)

  return (
    <div className="border-l-4 border-l-blue-400 bg-blue-50 rounded-r-lg mb-4 overflow-hidden">
      {/* Header */}
      <div
        className="flex items-center justify-between p-4 bg-blue-100 cursor-pointer hover:bg-blue-200 transition-colors"
        onClick={() => setIsExpanded(!isExpanded)}
      >
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-full bg-white shadow-sm">
            <Brain className="w-5 h-5 text-blue-600" />
          </div>
          <div>
            <div className="font-semibold text-gray-900">
              LLM Call #{index + 1}
              {call.agent_id && <span className="ml-2 text-blue-600">({call.agent_id})</span>}
            </div>
            <div className="text-xs text-gray-600 flex items-center gap-3 flex-wrap">
              {/* Model transparency - show which model was used */}
              {call.model && (
                <span className="bg-indigo-200 text-indigo-800 px-1.5 py-0.5 rounded font-medium">
                  {call.model}
                  {call.provider && <span className="opacity-75 ml-1">({call.provider})</span>}
                </span>
              )}
              {call.iteration !== undefined && <span>Iteration {call.iteration}</span>}
              {call.duration_ms && (
                <span className="flex items-center gap-1">
                  <Timer className="w-3 h-3" />
                  {formatDuration(call.duration_ms)}
                </span>
              )}
              {call.usage?.total_tokens && (
                <span className="bg-blue-200 text-blue-800 px-1.5 py-0.5 rounded">
                  {call.usage.total_tokens} tokens
                </span>
              )}
              <span className="text-gray-500">
                {call.messages?.length || 0} messages, {call.tools?.length || 0} tools
              </span>
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <CopyButton text={fullCallJson} label="Copy All" />
          {isExpanded ? <ChevronDown className="w-5 h-5 text-gray-500" /> : <ChevronRight className="w-5 h-5 text-gray-500" />}
        </div>
      </div>

      {/* Expanded content */}
      {isExpanded && (
        <div className="p-4 space-y-4">
          {/* Section tabs */}
          <div className="flex gap-2 border-b border-blue-200 pb-2">
            {['messages', 'tools', 'response', 'usage'].map((section) => (
              <button
                key={section}
                onClick={() => setActiveSection(section)}
                className={`px-3 py-1.5 text-xs font-medium rounded-t transition-colors ${
                  activeSection === section
                    ? 'bg-white text-blue-700 border border-b-0 border-blue-200'
                    : 'text-gray-600 hover:text-gray-900'
                }`}
              >
                {section.charAt(0).toUpperCase() + section.slice(1)}
                {section === 'messages' && call.messages?.length > 0 && ` (${call.messages.length})`}
                {section === 'tools' && call.tools?.length > 0 && ` (${call.tools.length})`}
              </button>
            ))}
          </div>

          {/* Messages section - Full request */}
          {activeSection === 'messages' && (
            <div>
              <div className="flex items-center justify-between mb-2">
                <h4 className="text-sm font-semibold text-gray-700">Input Messages (Request)</h4>
                <CopyButton text={JSON.stringify(call.messages, null, 2)} label="Copy Messages" />
              </div>
              {call.messages?.length > 0 ? (
                <div className="space-y-2 max-h-96 overflow-y-auto">
                  {call.messages.map((msg, msgIdx) => (
                    <div
                      key={msgIdx}
                      className={`rounded-lg p-3 ${
                        msg.role === 'system' ? 'bg-purple-100 border border-purple-200' :
                        msg.role === 'user' ? 'bg-green-100 border border-green-200' :
                        msg.role === 'assistant' ? 'bg-blue-100 border border-blue-200' :
                        msg.role === 'tool' ? 'bg-orange-100 border border-orange-200' :
                        'bg-gray-100 border border-gray-200'
                      }`}
                    >
                      <div className="flex items-center justify-between mb-1">
                        <span className={`text-xs font-semibold uppercase ${
                          msg.role === 'system' ? 'text-purple-700' :
                          msg.role === 'user' ? 'text-green-700' :
                          msg.role === 'assistant' ? 'text-blue-700' :
                          msg.role === 'tool' ? 'text-orange-700' :
                          'text-gray-700'
                        }`}>
                          {msg.role}
                        </span>
                        <CopyButton text={JSON.stringify(msg, null, 2)} label="Copy" />
                      </div>
                      <pre className="text-xs text-gray-800 whitespace-pre-wrap break-words max-h-48 overflow-y-auto">
                        {typeof msg.content === 'string' ? msg.content : JSON.stringify(msg.content, null, 2)}
                      </pre>
                      {msg.tool_calls && (
                        <div className="mt-2 pt-2 border-t border-gray-200">
                          <span className="text-xs font-medium text-orange-600">Tool Calls:</span>
                          <pre className="text-xs text-gray-700 mt-1">
                            {JSON.stringify(msg.tool_calls, null, 2)}
                          </pre>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-gray-500 text-sm">No messages in this call</p>
              )}
            </div>
          )}

          {/* Tools section */}
          {activeSection === 'tools' && (
            <div>
              <div className="flex items-center justify-between mb-2">
                <h4 className="text-sm font-semibold text-gray-700">Available Tools (Schema)</h4>
                <CopyButton text={JSON.stringify(call.tools, null, 2)} label="Copy Tools" />
              </div>
              {call.tools?.length > 0 ? (
                <div className="space-y-2 max-h-96 overflow-y-auto">
                  {call.tools.map((tool, toolIdx) => (
                    <div key={toolIdx} className="bg-orange-50 border border-orange-200 rounded-lg p-3">
                      <div className="flex items-center justify-between mb-1">
                        <span className="font-mono text-sm font-medium text-orange-800">
                          {tool.function?.name || tool.name || `Tool ${toolIdx + 1}`}
                        </span>
                        <CopyButton text={JSON.stringify(tool, null, 2)} label="Copy" />
                      </div>
                      {(tool.function?.description || tool.description) && (
                        <p className="text-xs text-gray-600 mb-2">
                          {tool.function?.description || tool.description}
                        </p>
                      )}
                      {(tool.function?.parameters || tool.parameters) && (
                        <details className="text-xs">
                          <summary className="cursor-pointer text-orange-600 font-medium">Parameters</summary>
                          <pre className="mt-1 bg-gray-800 text-gray-100 p-2 rounded text-xs overflow-x-auto">
                            {JSON.stringify(tool.function?.parameters || tool.parameters, null, 2)}
                          </pre>
                        </details>
                      )}
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-gray-500 text-sm">No tools provided in this call</p>
              )}
            </div>
          )}

          {/* Response section */}
          {activeSection === 'response' && (
            <div>
              <div className="flex items-center justify-between mb-2">
                <h4 className="text-sm font-semibold text-gray-700">LLM Response</h4>
                <CopyButton text={fullResponseJson} label="Copy Response" />
              </div>
              {call.response ? (
                <div className="space-y-3">
                  {/* Content */}
                  {call.response.content && (
                    <div className="bg-green-50 border border-green-200 rounded-lg p-3">
                      <div className="flex items-center justify-between mb-1">
                        <span className="text-xs font-semibold text-green-700 uppercase">Content</span>
                        <CopyButton text={call.response.content} label="Copy" />
                      </div>
                      <pre className="text-xs text-gray-800 whitespace-pre-wrap break-words max-h-64 overflow-y-auto">
                        {call.response.content}
                      </pre>
                    </div>
                  )}
                  {/* Tool calls */}
                  {call.response.tool_calls?.length > 0 && (
                    <div className="bg-orange-50 border border-orange-200 rounded-lg p-3">
                      <div className="flex items-center justify-between mb-2">
                        <span className="text-xs font-semibold text-orange-700 uppercase">
                          Tool Calls ({call.response.tool_calls.length})
                        </span>
                        <CopyButton text={JSON.stringify(call.response.tool_calls, null, 2)} label="Copy" />
                      </div>
                      <div className="space-y-2">
                        {call.response.tool_calls.map((tc, tcIdx) => (
                          <div key={tcIdx} className="bg-white rounded p-2 border border-orange-100">
                            <div className="flex items-center justify-between">
                              <span className="font-mono text-sm text-orange-800 font-medium">
                                {tc.name || tc.function?.name}
                              </span>
                              <CopyButton text={JSON.stringify(tc, null, 2)} label="Copy" />
                            </div>
                            {(tc.args || tc.function?.arguments) && (
                              <pre className="mt-1 text-xs bg-gray-100 p-2 rounded overflow-x-auto">
                                {typeof (tc.args || tc.function?.arguments) === 'string'
                                  ? tc.args || tc.function?.arguments
                                  : JSON.stringify(tc.args || tc.function?.arguments, null, 2)}
                              </pre>
                            )}
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              ) : (
                <p className="text-gray-500 text-sm">No response data</p>
              )}
            </div>
          )}

          {/* Usage section */}
          {activeSection === 'usage' && (
            <div>
              <div className="flex items-center justify-between mb-2">
                <h4 className="text-sm font-semibold text-gray-700">Token Usage</h4>
                <CopyButton text={JSON.stringify(call.usage, null, 2)} label="Copy Usage" />
              </div>
              {/* Model transparency */}
              {call.model && (
                <div className="mb-4 p-3 bg-indigo-50 border border-indigo-200 rounded-lg">
                  <div className="text-xs text-gray-500 uppercase tracking-wide mb-1">Model Used</div>
                  <div className="text-lg font-semibold text-indigo-700">
                    {call.model}
                    {call.provider && (
                      <span className="text-sm font-normal text-indigo-500 ml-2">via {call.provider}</span>
                    )}
                  </div>
                </div>
              )}
              {call.usage ? (
                <div className="grid grid-cols-3 gap-4">
                  <div className="bg-blue-50 border border-blue-200 rounded-lg p-3 text-center">
                    <div className="text-2xl font-bold text-blue-700">{call.usage.prompt_tokens || 0}</div>
                    <div className="text-xs text-gray-600">Prompt Tokens</div>
                  </div>
                  <div className="bg-green-50 border border-green-200 rounded-lg p-3 text-center">
                    <div className="text-2xl font-bold text-green-700">{call.usage.completion_tokens || 0}</div>
                    <div className="text-xs text-gray-600">Completion Tokens</div>
                  </div>
                  <div className="bg-purple-50 border border-purple-200 rounded-lg p-3 text-center">
                    <div className="text-2xl font-bold text-purple-700">{call.usage.total_tokens || 0}</div>
                    <div className="text-xs text-gray-600">Total Tokens</div>
                  </div>
                </div>
              ) : (
                <p className="text-gray-500 text-sm">No usage data</p>
              )}
            </div>
          )}

          {/* Raw JSON view */}
          <details className="mt-4">
            <summary className="cursor-pointer text-xs text-gray-500 hover:text-gray-700 font-medium">
              View Raw JSON
            </summary>
            <div className="mt-2 relative">
              <CopyButton text={fullCallJson} label="Copy All" />
              <pre className="bg-gray-800 text-gray-100 p-3 rounded-lg text-xs overflow-x-auto max-h-64 overflow-y-auto mt-2">
                {fullCallJson}
              </pre>
            </div>
          </details>
        </div>
      )}
    </div>
  )
}

// Single trace event component
const TraceEvent = ({ event, depth = 0 }) => {
  const [isExpanded, setIsExpanded] = useState(depth < 2)
  const hasChildren = event.children && event.children.length > 0
  const hasDetails = event.inputs || event.outputs || event.error || event.metadata

  const eventType = event.type || event.event_type || 'unknown'
  const status = event.status || (event.error ? 'error' : 'success')

  // Type-specific colors
  const typeColors = {
    agent: 'border-l-purple-400 bg-purple-50',
    llm: 'border-l-blue-400 bg-blue-50',
    tool: 'border-l-orange-400 bg-orange-50',
    workflow: 'border-l-green-400 bg-green-50',
    task: 'border-l-cyan-400 bg-cyan-50',
    file: 'border-l-yellow-400 bg-yellow-50',
    command: 'border-l-pink-400 bg-pink-50',
  }

  const baseType = eventType.split('_')[0]
  const colorClass = typeColors[baseType] || 'border-l-gray-400 bg-gray-50'

  return (
    <div className="mb-2">
      <div
        className={`border-l-4 rounded-r-lg p-3 ${colorClass} hover:shadow-sm transition-shadow cursor-pointer`}
        onClick={() => hasChildren && setIsExpanded(!isExpanded)}
        style={{ marginLeft: `${depth * 16}px` }}
      >
        <div className="flex items-start gap-3">
          {/* Expand/collapse indicator */}
          <div className="flex-shrink-0 w-5 h-5 flex items-center justify-center">
            {hasChildren ? (
              isExpanded ? (
                <ChevronDown className="w-4 h-4 text-gray-500" />
              ) : (
                <ChevronRight className="w-4 h-4 text-gray-500" />
              )
            ) : (
              <div className="w-4 h-4" />
            )}
          </div>

          {/* Event type icon */}
          <div className="flex-shrink-0 p-1.5 rounded-full bg-white shadow-sm">
            {getEventTypeIcon(eventType)}
          </div>

          {/* Event content */}
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              {/* Event name/title */}
              <span className="font-medium text-gray-900">
                {event.name || event.title || eventType}
              </span>

              {/* Type badge */}
              <span className="text-xs px-1.5 py-0.5 rounded bg-white text-gray-600 border border-gray-200">
                {eventType}
              </span>

              {/* Status badge */}
              <StatusBadge status={status} />

              {/* Duration */}
              {event.duration_ms !== undefined && (
                <span className="flex items-center gap-1 text-xs text-gray-500">
                  <Timer className="w-3 h-3" />
                  {formatDuration(event.duration_ms)}
                </span>
              )}
            </div>

            {/* Description or message */}
            {(event.description || event.message) && (
              <p className="text-sm text-gray-600 mt-1 truncate">
                {event.description || event.message}
              </p>
            )}

            {/* Agent ID */}
            {event.agent_id && (
              <span className="inline-flex items-center gap-1 text-xs bg-purple-100 text-purple-700 px-1.5 py-0.5 rounded mt-1">
                <Bot className="w-3 h-3" />
                {event.agent_id}
              </span>
            )}

            {/* Tool name */}
            {(event.tool || event.tool_name) && (
              <span className="inline-flex items-center gap-1 text-xs bg-orange-100 text-orange-700 px-1.5 py-0.5 rounded mt-1 ml-1">
                <Hammer className="w-3 h-3" />
                {event.tool || event.tool_name}
              </span>
            )}

            {/* Timestamp */}
            {event.timestamp && (
              <span className="flex items-center gap-1 text-xs text-gray-400 mt-1">
                <Clock className="w-3 h-3" />
                {formatTimestamp(event.timestamp)}
              </span>
            )}

            {/* Expandable details */}
            {hasDetails && (
              <div className="mt-2 space-y-1" onClick={(e) => e.stopPropagation()}>
                <JsonViewer data={event.inputs} label="Inputs" />
                <JsonViewer data={event.outputs} label="Outputs" />
                <JsonViewer data={event.error} label="Error" />
                <JsonViewer data={event.metadata} label="Metadata" />
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Children events */}
      {hasChildren && isExpanded && (
        <div className="mt-1">
          {event.children.map((child, index) => (
            <TraceEvent key={child.id || index} event={child} depth={depth + 1} />
          ))}
        </div>
      )}
    </div>
  )
}

// Format token count with K suffix for large numbers
const formatTokens = (count) => {
  if (!count) return '0'
  if (count >= 1000000) return `${(count / 1000000).toFixed(1)}M`
  if (count >= 1000) return `${(count / 1000).toFixed(1)}K`
  return count.toString()
}

// Calculate and format cost from tokens ($0.40 per million tokens for DeepInfra)
const formatCost = (tokens) => {
  if (!tokens) return null
  const cost = (tokens / 1000000) * 0.40
  if (cost < 0.01) return '<$0.01'
  return `$${cost.toFixed(2)}`
}

// Summary stats component
const TraceSummary = ({ trace }) => {
  // Calculate stats from trace
  const events = trace.events || []
  const summary = trace.summary || {}

  const countByType = (type) =>
    events.filter((e) => (e.type || e.event_type || '').includes(type)).length

  const countByStatus = (status) =>
    events.filter((e) => {
      const eventStatus = e.status || (e.error ? 'error' : 'success')
      return eventStatus === status
    }).length

  const totalDuration = events.reduce((sum, e) => sum + (e.duration_ms || 0), 0)

  // Use summary token counts if available, otherwise calculate from events
  const totalTokens = summary.total_tokens || 0

  const stats = [
    { label: 'Total Events', value: events.length, icon: Hash, color: 'text-gray-600' },
    { label: 'Agent Calls', value: countByType('agent'), icon: Bot, color: 'text-purple-600' },
    { label: 'LLM Calls', value: countByType('llm'), icon: Brain, color: 'text-blue-600' },
    { label: 'Tool Calls', value: countByType('tool'), icon: Hammer, color: 'text-orange-600' },
    { label: 'Total Tokens', value: formatTokens(totalTokens), icon: Zap, color: 'text-yellow-600' },
    { label: 'Successful', value: countByStatus('success') + countByStatus('completed'), icon: CheckCircle, color: 'text-green-600' },
    { label: 'Duration', value: formatDuration(totalDuration), icon: Timer, color: 'text-cyan-600' },
  ]

  // Per-agent token breakdown for transparency
  const tokensByAgent = summary.tokens_by_agent || {}
  const hasAgentBreakdown = Object.keys(tokensByAgent).length > 0

  return (
    <div className="space-y-4 mb-6">
      {/* Main stats grid */}
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-4">
        {stats.map(({ label, value, icon: Icon, color }) => (
          <div key={label} className="bg-white rounded-lg border border-gray-200 p-4">
            <div className="flex items-center gap-2 mb-1">
              <Icon className={`w-4 h-4 ${color}`} />
              <span className="text-xs text-gray-500 uppercase tracking-wide">{label}</span>
            </div>
            <div className="text-2xl font-bold text-gray-900">{value}</div>
          </div>
        ))}
      </div>

      {/* Per-agent token breakdown */}
      {hasAgentBreakdown && (
        <div className="bg-white rounded-lg border border-gray-200 p-4">
          <h3 className="text-sm font-semibold text-gray-700 mb-3 flex items-center gap-2">
            <Bot className="w-4 h-4 text-purple-600" />
            Tokens by Agent
          </h3>
          <div className="flex flex-wrap gap-3">
            {Object.entries(tokensByAgent)
              .sort((a, b) => b[1] - a[1])
              .map(([agent, tokens]) => (
                <div
                  key={agent}
                  className="flex items-center gap-2 bg-gray-50 rounded-lg px-3 py-2"
                >
                  <span className="text-sm font-medium text-gray-700 capitalize">{agent}</span>
                  <span className="text-sm bg-yellow-100 text-yellow-700 px-2 py-0.5 rounded">
                    {formatTokens(tokens)}
                  </span>
                  {formatCost(tokens) && (
                    <span className="text-xs text-gray-500">
                      ({formatCost(tokens)})
                    </span>
                  )}
                </div>
              ))}
          </div>
        </div>
      )}
    </div>
  )
}

// Main Debug component
const Debug = () => {
  const { sessionId } = useParams()
  const { authenticated } = useAuth()
  const [trace, setTrace] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [expandAll, setExpandAll] = useState(false)

  useEffect(() => {
    const fetchTrace = async () => {
      if (!sessionId) return

      setLoading(true)
      setError(null)

      try {
        const data = await getSessionTrace(sessionId)
        // API returns {session_id, status, trace: {events, summary, raw_llm_calls}}
        // Store the full response for access to session_id and status
        setTrace({
          session_id: data.session_id,
          session_status: data.status,
          events: data.trace?.events || [],
          summary: data.trace?.summary || {},
          raw_llm_calls: data.trace?.raw_llm_calls || [],
        })
      } catch (err) {
        console.error('Failed to fetch trace:', err)
        setError(err.message || 'Failed to load execution trace')
      } finally {
        setLoading(false)
      }
    }

    fetchTrace()
  }, [sessionId])

  // Loading state
  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-center">
          <Loader2 className="w-8 h-8 animate-spin text-blue-600 mx-auto mb-2" />
          <p className="text-gray-600">Loading execution trace...</p>
        </div>
      </div>
    )
  }

  // Error state
  if (error) {
    return (
      <div className="max-w-2xl mx-auto">
        <div className="bg-red-50 border border-red-200 rounded-lg p-6 text-center">
          <XCircle className="w-12 h-12 text-red-500 mx-auto mb-3" />
          <h2 className="text-lg font-semibold text-red-800 mb-2">Failed to Load Trace</h2>
          <p className="text-red-600 mb-4">{error}</p>
          <Link
            to={`/chat?session=${sessionId}`}
            className="inline-flex items-center gap-2 px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700"
          >
            <ArrowLeft className="w-4 h-4" />
            Back to Chat
          </Link>
        </div>
      </div>
    )
  }

  // No trace data
  if (!trace || !trace.events || trace.events.length === 0) {
    return (
      <div className="max-w-2xl mx-auto">
        <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-6 text-center">
          <AlertCircle className="w-12 h-12 text-yellow-500 mx-auto mb-3" />
          <h2 className="text-lg font-semibold text-yellow-800 mb-2">No Trace Data</h2>
          <p className="text-yellow-600 mb-4">
            No execution trace found for session: {sessionId}
          </p>
          <Link
            to={`/chat?session=${sessionId}`}
            className="inline-flex items-center gap-2 px-4 py-2 bg-yellow-600 text-white rounded-lg hover:bg-yellow-700"
          >
            <ArrowLeft className="w-4 h-4" />
            Back to Chat
          </Link>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Link
            to={`/chat?session=${sessionId}`}
            className="p-2 rounded-lg hover:bg-gray-100 transition-colors"
            title="Back to Chat"
          >
            <ArrowLeft className="w-5 h-5 text-gray-600" />
          </Link>
          <div>
            <h1 className="text-2xl font-bold text-gray-900 flex items-center gap-2">
              <Activity className="w-6 h-6 text-blue-600" />
              Execution Trace
            </h1>
            <p className="text-sm text-gray-500 mt-1">
              Session: <code className="bg-gray-100 px-2 py-0.5 rounded">{sessionId}</code>
              {trace.session_status && (
                <span className="ml-2">
                  <StatusBadge status={trace.session_status} />
                </span>
              )}
            </p>
          </div>
        </div>

        {/* Controls */}
        <div className="flex items-center gap-2">
          <button
            onClick={() => setExpandAll(!expandAll)}
            className="px-3 py-2 text-sm bg-gray-100 hover:bg-gray-200 rounded-lg transition-colors"
          >
            {expandAll ? 'Collapse All' : 'Expand All'}
          </button>
          <button
            onClick={() => window.location.reload()}
            className="px-3 py-2 text-sm bg-blue-100 text-blue-700 hover:bg-blue-200 rounded-lg transition-colors flex items-center gap-1"
          >
            <Activity className="w-4 h-4" />
            Refresh
          </button>
        </div>
      </div>

      {/* Summary Stats */}
      <TraceSummary trace={trace} />

      {/* Session Info */}
      {(trace.started_at || trace.completed_at || trace.request) && (
        <div className="bg-white rounded-lg border border-gray-200 p-4">
          <h2 className="text-sm font-semibold text-gray-700 mb-3">Session Info</h2>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-sm">
            {trace.started_at && (
              <div>
                <span className="text-gray-500">Started:</span>
                <span className="ml-2 text-gray-900">{new Date(trace.started_at).toLocaleString()}</span>
              </div>
            )}
            {trace.completed_at && (
              <div>
                <span className="text-gray-500">Completed:</span>
                <span className="ml-2 text-gray-900">{new Date(trace.completed_at).toLocaleString()}</span>
              </div>
            )}
            {trace.request && (
              <div className="md:col-span-3">
                <span className="text-gray-500">Request:</span>
                <span className="ml-2 text-gray-900">{trace.request}</span>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Events Timeline */}
      <div className="bg-white rounded-lg border border-gray-200 p-4">
        <h2 className="text-sm font-semibold text-gray-700 mb-4 flex items-center gap-2">
          <Clock className="w-4 h-4" />
          Execution Timeline ({trace.events.length} events)
        </h2>
        <div className="space-y-1">
          {trace.events.map((event, index) => (
            <TraceEvent
              key={event.id || index}
              event={event}
              depth={0}
            />
          ))}
        </div>
      </div>

      {/* Raw LLM Calls Section */}
      {trace.raw_llm_calls && trace.raw_llm_calls.length > 0 && (
        <div className="bg-white rounded-lg border border-gray-200 p-4">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-sm font-semibold text-gray-700 flex items-center gap-2">
              <Brain className="w-4 h-4 text-blue-600" />
              Raw LLM Calls ({trace.raw_llm_calls.length})
            </h2>
            <CopyButton
              text={JSON.stringify(trace.raw_llm_calls, null, 2)}
              label="Copy All LLM Calls"
            />
          </div>
          <p className="text-xs text-gray-500 mb-4">
            Full request/response data for each LLM call. Click to expand and view messages, tools, and responses.
          </p>
          <div className="space-y-2">
            {trace.raw_llm_calls.map((call, index) => (
              <RawLLMCallViewer key={index} call={call} index={index} />
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

export default Debug
