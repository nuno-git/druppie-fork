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

// Summary stats component
const TraceSummary = ({ trace }) => {
  // Calculate stats from trace
  const events = trace.events || []

  const countByType = (type) =>
    events.filter((e) => (e.type || e.event_type || '').includes(type)).length

  const countByStatus = (status) =>
    events.filter((e) => e.status === status).length

  const totalDuration = events.reduce((sum, e) => sum + (e.duration_ms || 0), 0)

  const stats = [
    { label: 'Total Events', value: events.length, icon: Hash, color: 'text-gray-600' },
    { label: 'Agent Calls', value: countByType('agent'), icon: Bot, color: 'text-purple-600' },
    { label: 'LLM Calls', value: countByType('llm'), icon: Brain, color: 'text-blue-600' },
    { label: 'Tool Calls', value: countByType('tool'), icon: Hammer, color: 'text-orange-600' },
    { label: 'Successful', value: countByStatus('success') + countByStatus('completed'), icon: CheckCircle, color: 'text-green-600' },
    { label: 'Failed', value: countByStatus('error') + countByStatus('failed'), icon: XCircle, color: 'text-red-600' },
    { label: 'Total Duration', value: formatDuration(totalDuration), icon: Timer, color: 'text-cyan-600' },
  ]

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-4 mb-6">
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
        setTrace(data)
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
    </div>
  )
}

export default Debug
