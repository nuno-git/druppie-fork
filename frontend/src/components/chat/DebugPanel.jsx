/**
 * DebugPanel - Shows agents, workflows, MCP tools, and execution info
 * Now supports per-message execution logs for full conversation history debugging
 */

import React, { useState } from 'react'
import { Link } from 'react-router-dom'
import {
  X,
  Copy,
  Check,
  Bot,
  Brain,
  Hammer,
  Clock,
  Zap,
  GitBranch,
  ChevronDown,
  ChevronRight,
  Bug,
  MessageSquare,
  User,
  ExternalLink,
} from 'lucide-react'
import { getStatusColors, getIconBgColor, getEventIcon } from '../../utils/eventUtils'

const DebugPanel = ({ isOpen, onClose, sessionId, apiCalls, workflowEvents, llmCalls: llmCallsProp, workspaceInfo, messages = [] }) => {
  const [copiedIndex, setCopiedIndex] = useState(null)
  const [expandedItems, setExpandedItems] = useState({})
  const [allCopied, setAllCopied] = useState(false)
  const [activeTab, setActiveTab] = useState('overview')

  const copyToClipboard = (text, index) => {
    navigator.clipboard.writeText(text)
    setCopiedIndex(index)
    setTimeout(() => setCopiedIndex(null), 2000)
  }

  const copyAllToClipboard = () => {
    const fullData = JSON.stringify({ apiCalls, workflowEvents, llmCalls: llmCallsProp, workspaceInfo }, null, 2)
    navigator.clipboard.writeText(fullData)
    setAllCopied(true)
    setTimeout(() => setAllCopied(false), 2000)
  }

  // Generate readable text format for copy
  const generateExecutionText = () => {
    const lines = []
    lines.push('='.repeat(60))
    lines.push('EXECUTION TRACE')
    lines.push('='.repeat(60))
    lines.push('')

    // Workspace info
    if (workspaceInfo) {
      lines.push('WORKSPACE:')
      if (workspaceInfo.workspace_id) lines.push(`  Workspace ID: ${workspaceInfo.workspace_id}`)
      if (workspaceInfo.project_id) lines.push(`  Project ID: ${workspaceInfo.project_id}`)
      if (workspaceInfo.branch) lines.push(`  Branch: ${workspaceInfo.branch}`)
      if (workspaceInfo.workspace_path) lines.push(`  Path: ${workspaceInfo.workspace_path}`)
      lines.push('')
    }

    // Summary
    lines.push('SUMMARY:')
    lines.push(`  Agents: ${agents.length}`)
    lines.push(`  Tool Calls: ${toolCalls.length}`)
    lines.push(`  LLM Calls: ${llmCalls.length}`)
    lines.push(`  Total Events: ${events.length}`)
    const totalTokens = llmCalls.reduce((acc, c) => acc + (c.usage?.total_tokens || 0), 0)
    if (totalTokens > 0) lines.push(`  Total Tokens: ${totalTokens}`)
    lines.push('')

    // Agents
    if (agents.length > 0) {
      lines.push('-'.repeat(60))
      lines.push('AGENTS:')
      lines.push('-'.repeat(60))
      agents.forEach((agent, i) => {
        lines.push(`\n[${i + 1}] Agent: ${agent.id}`)
        lines.push(`    Status: ${agent.status}`)
        lines.push(`    LLM Calls: ${agent.llmCalls.length}`)
        if (agent.error) lines.push(`    Error: ${agent.error}`)
      })
      lines.push('')
    }

    // Tool Calls
    if (toolCalls.length > 0) {
      lines.push('-'.repeat(60))
      lines.push('TOOL CALLS:')
      lines.push('-'.repeat(60))
      toolCalls.forEach((tool, i) => {
        lines.push(`\n[${i + 1}] ${tool.name}`)
        if (tool.agent) lines.push(`    Agent: ${tool.agent}`)
        lines.push(`    Status: ${tool.status}`)
        if (tool.args) {
          const argsStr = typeof tool.args === 'string' ? tool.args : JSON.stringify(tool.args, null, 2)
          lines.push(`    Args: ${argsStr.substring(0, 500)}${argsStr.length > 500 ? '...' : ''}`)
        }
        if (tool.timestamp) lines.push(`    Time: ${new Date(tool.timestamp).toLocaleString()}`)
      })
      lines.push('')
    }

    // LLM Calls
    if (llmCalls.length > 0) {
      lines.push('-'.repeat(60))
      lines.push('LLM CALLS:')
      lines.push('-'.repeat(60))
      llmCalls.forEach((call, i) => {
        lines.push(`\n[${i + 1}] ${call.agent_id || 'LLM'} - Iteration ${call.iteration || i + 1}`)
        if (call.model) lines.push(`    Model: ${call.model}`)
        if (call.provider) lines.push(`    Provider: ${call.provider}`)
        if (call.duration_ms) lines.push(`    Duration: ${call.duration_ms}ms`)
        if (call.usage?.total_tokens) {
          lines.push(`    Tokens: ${call.usage.prompt_tokens || 0} prompt + ${call.usage.completion_tokens || 0} completion = ${call.usage.total_tokens}`)
        }
        if (call.response?.tool_calls?.length > 0) {
          const toolNames = call.response.tool_calls.map(tc => tc.name || tc.function?.name || 'tool').join(', ')
          lines.push(`    Tool Calls: ${toolNames}`)
        }
      })
      lines.push('')
    }

    // Events Timeline
    if (events.length > 0) {
      lines.push('-'.repeat(60))
      lines.push('EVENTS TIMELINE:')
      lines.push('-'.repeat(60))
      events.forEach((event, i) => {
        const eventType = event.event_type || event.type || 'unknown'
        const time = event.timestamp ? new Date(event.timestamp).toLocaleTimeString() : ''
        const agent = event.data?.agent_id || ''
        lines.push(`[${i + 1}] ${time} ${eventType}${agent ? ` (${agent})` : ''}`)
        if (event.description) lines.push(`    ${event.description}`)
      })
    }

    lines.push('')
    lines.push('='.repeat(60))
    lines.push(`Generated: ${new Date().toLocaleString()}`)
    lines.push('='.repeat(60))

    return lines.join('\n')
  }

  const copyAsText = () => {
    const text = generateExecutionText()
    navigator.clipboard.writeText(text)
    setAllCopied(true)
    setTimeout(() => setAllCopied(false), 2000)
  }

  const toggleExpand = (index) => {
    setExpandedItems(prev => ({ ...prev, [index]: !prev[index] }))
  }

  if (!isOpen) return null

  // Process data for different views
  const llmCalls = llmCallsProp?.length > 0 ? llmCallsProp : (apiCalls?.filter(c => c.type === 'llm') || [])
  const events = workflowEvents || []

  // Extract agents from events and LLM calls
  const agentMap = new Map()
  const getEventType = (event) => event.event_type || event.type || ''

  events.forEach(event => {
    const eventType = getEventType(event)
    if (eventType === 'agent_started' || event.data?.agent_id) {
      const agentId = event.data?.agent_id || event.agent_id
      if (agentId && !agentMap.has(agentId)) {
        agentMap.set(agentId, {
          id: agentId,
          startTime: event.timestamp,
          events: [],
          toolCalls: [],
          llmCalls: [],
          status: 'running'
        })
      }
      if (agentId && agentMap.has(agentId)) {
        agentMap.get(agentId).events.push(event)
      }
    }
    if (eventType === 'agent_completed') {
      const agentId = event.data?.agent_id
      if (agentId && agentMap.has(agentId)) {
        agentMap.get(agentId).status = 'completed'
        agentMap.get(agentId).endTime = event.timestamp
      }
    }
    if (eventType === 'agent_error' || eventType === 'agent_failed') {
      const agentId = event.data?.agent_id
      if (agentId && agentMap.has(agentId)) {
        agentMap.get(agentId).status = 'error'
        agentMap.get(agentId).error = event.data?.error
      }
    }
  })

  // Add LLM calls to agents
  llmCalls.forEach(call => {
    if (call.agent_id && agentMap.has(call.agent_id)) {
      agentMap.get(call.agent_id).llmCalls.push(call)
    }
  })

  const agents = Array.from(agentMap.values())

  // Extract MCP tool calls from events
  const toolCalls = events.filter(e => {
    const type = getEventType(e)
    return type === 'tool_call' || type === 'tool_executing' || type === 'tool_completed' ||
      type === 'mcp_tool' || e.data?.tool_name || e.data?.tool
  }).map(e => ({
    name: e.data?.tool_name || e.data?.tool || e.title,
    args: e.data?.args_preview || e.data?.arguments,
    agent: e.data?.agent_id,
    timestamp: e.timestamp,
    status: e.status || 'completed',
    result: e.data?.result
  }))

  // Process messages for per-message view
  const assistantMessages = messages.filter(m => m.role === 'assistant' && m.content)
  const messagesWithEvents = assistantMessages.filter(m => m.workflowEvents?.length > 0 || m.llmCalls?.length > 0)

  // Tab definitions
  const tabs = [
    { id: 'overview', label: 'Overview', icon: Zap },
    { id: 'messages', label: `Messages (${messagesWithEvents.length})`, icon: MessageSquare },
    { id: 'agents', label: `Agents (${agents.length})`, icon: Bot },
    { id: 'tools', label: `Tools (${toolCalls.length})`, icon: Hammer },
    { id: 'events', label: `Events (${events.length})`, icon: Clock },
    { id: 'llm', label: `LLM (${llmCalls.length})`, icon: Brain },
  ]

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="bg-white rounded-xl shadow-2xl w-[95vw] max-w-6xl max-h-[90vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-orange-100 rounded-lg">
              <Bug className="w-5 h-5 text-orange-600" />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-gray-900">Execution Debug Panel</h2>
              <p className="text-sm text-gray-500">
                {agents.length} agents, {toolCalls.length} tool calls, {llmCalls.length} LLM calls
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {sessionId && (
              <Link
                to={`/debug/${sessionId}`}
                className="flex items-center gap-1 px-3 py-1.5 text-xs bg-purple-100 text-purple-700 hover:bg-purple-200 rounded-lg transition-colors"
                title="Open full debug page with raw LLM calls"
              >
                <ExternalLink className="w-3 h-3" />
                Full Debug Page
              </Link>
            )}
            <button
              onClick={copyAsText}
              className="flex items-center gap-1 px-3 py-1.5 text-xs bg-green-100 text-green-700 hover:bg-green-200 rounded-lg transition-colors"
              title="Copy execution trace as readable text"
            >
              {allCopied ? <><Check className="w-3 h-3" /> Copied!</> : <><Copy className="w-3 h-3" /> Copy as Text</>}
            </button>
            <button
              onClick={copyAllToClipboard}
              className="flex items-center gap-1 px-3 py-1.5 text-xs bg-blue-100 text-blue-700 hover:bg-blue-200 rounded-lg transition-colors"
              title="Export all data as JSON"
            >
              <Copy className="w-3 h-3" /> Export JSON
            </button>
            <button
              onClick={onClose}
              className="p-2 hover:bg-gray-100 rounded-lg transition-colors ml-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
              aria-label="Close debug panel"
            >
              <X className="w-5 h-5 text-gray-500" aria-hidden="true" />
            </button>
          </div>
        </div>

        {/* Tabs */}
        <div className="flex border-b border-gray-200 px-4">
          {tabs.map(tab => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`flex items-center gap-2 px-4 py-3 text-sm font-medium border-b-2 transition-colors ${
                activeTab === tab.id
                  ? 'border-blue-500 text-blue-600'
                  : 'border-transparent text-gray-500 hover:text-gray-700'
              }`}
            >
              <tab.icon className="w-4 h-4" />
              {tab.label}
            </button>
          ))}
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-4">
          {/* Overview Tab */}
          {activeTab === 'overview' && (
            <div className="space-y-4">
              {/* Workspace Info */}
              {workspaceInfo && (
                <div className="bg-gradient-to-r from-blue-50 to-purple-50 rounded-lg border border-blue-200 p-4">
                  <h3 className="font-semibold text-gray-900 mb-3 flex items-center gap-2">
                    <GitBranch className="w-5 h-5 text-blue-600" />
                    Workspace Info
                  </h3>
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                    {workspaceInfo.workspace_id && (
                      <div>
                        <div className="text-xs text-gray-500 uppercase">Workspace ID</div>
                        <div className="font-mono text-sm">{workspaceInfo.workspace_id?.substring(0, 8)}...</div>
                      </div>
                    )}
                    {workspaceInfo.project_id && (
                      <div>
                        <div className="text-xs text-gray-500 uppercase">Project ID</div>
                        <div className="font-mono text-sm">{workspaceInfo.project_id?.substring(0, 8)}...</div>
                      </div>
                    )}
                    {workspaceInfo.branch && (
                      <div>
                        <div className="text-xs text-gray-500 uppercase">Branch</div>
                        <div className="font-mono text-sm flex items-center gap-1">
                          <GitBranch className="w-3 h-3" />
                          {workspaceInfo.branch}
                        </div>
                      </div>
                    )}
                    {workspaceInfo.workspace_path && (
                      <div>
                        <div className="text-xs text-gray-500 uppercase">Path</div>
                        <div className="font-mono text-sm truncate">{workspaceInfo.workspace_path}</div>
                      </div>
                    )}
                  </div>
                </div>
              )}

              {/* Stats Cards */}
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <StatCard icon={Bot} label="Agents" value={agents.length} color="purple" detail={`${agents.filter(a => a.status === 'completed').length} completed`} />
                <StatCard icon={Hammer} label="Tool Calls" value={toolCalls.length} color="orange" detail="MCP operations" />
                <StatCard icon={Brain} label="LLM Calls" value={llmCalls.length} color="blue" detail={`${llmCalls.reduce((acc, c) => acc + (c.usage?.total_tokens || 0), 0)} tokens`} />
                <StatCard icon={Clock} label="Events" value={events.length} color="green" detail="workflow events" />
              </div>

              {/* Execution Flow */}
              <div className="bg-gray-50 rounded-lg border border-gray-200 p-4">
                <h3 className="font-semibold text-gray-900 mb-3">Execution Flow</h3>
                <div className="space-y-2">
                  {agents.map((agent, idx) => (
                    <AgentFlowItem key={idx} agent={agent} />
                  ))}
                  {agents.length === 0 && <EmptyState icon={Bot} message="No agents have run yet" />}
                </div>
              </div>
            </div>
          )}

          {/* Messages Tab - Per-message execution logs */}
          {activeTab === 'messages' && (
            <div className="space-y-4">
              {messages.length > 0 ? messages.map((msg, idx) => (
                <MessageDebugCard
                  key={idx}
                  message={msg}
                  index={idx}
                  isExpanded={expandedItems[`msg-${idx}`]}
                  onToggle={() => toggleExpand(`msg-${idx}`)}
                />
              )) : <EmptyState icon={MessageSquare} message="No messages yet" subtext="Send a message to see execution details" />}
            </div>
          )}

          {/* Agents Tab */}
          {activeTab === 'agents' && (
            <div className="space-y-4">
              {agents.length > 0 ? agents.map((agent, idx) => (
                <AgentCard key={idx} agent={agent} isExpanded={expandedItems[`agent-${idx}`]} onToggle={() => toggleExpand(`agent-${idx}`)} />
              )) : <EmptyState icon={Bot} message="No agents have run yet" subtext="Agents will appear here as they execute" />}
            </div>
          )}

          {/* Tools Tab */}
          {activeTab === 'tools' && (
            <div className="space-y-2">
              {toolCalls.length > 0 ? toolCalls.map((tool, idx) => (
                <ToolCallItem key={idx} tool={tool} />
              )) : <EmptyState icon={Hammer} message="No tool calls yet" subtext="MCP tool calls will appear here" />}
            </div>
          )}

          {/* Events Tab */}
          {activeTab === 'events' && (
            <div className="space-y-2">
              {events.length > 0 ? events.map((event, idx) => (
                <EventItem key={idx} event={event} />
              )) : <EmptyState icon={Clock} message="No events yet" subtext="Workflow events will appear here" />}
            </div>
          )}

          {/* LLM Tab */}
          {activeTab === 'llm' && (
            <div className="space-y-4">
              {llmCalls.length > 0 ? llmCalls.map((call, idx) => (
                <LLMCallCard key={idx} call={call} idx={idx} isExpanded={expandedItems[`llm-${idx}`]} onToggle={() => toggleExpand(`llm-${idx}`)} />
              )) : <EmptyState icon={Brain} message="No LLM calls yet" subtext="LLM calls will appear here" />}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-6 py-3 border-t border-gray-200 bg-gray-50">
          <p className="text-xs text-gray-500 text-center">
            {agents.length} agent(s), {toolCalls.length} tool call(s), {llmCalls.length} LLM call(s), {events.length} event(s)
          </p>
        </div>
      </div>
    </div>
  )
}

// Helper components
const StatCard = ({ icon: Icon, label, value, color, detail }) => (
  <div className={`bg-${color}-50 rounded-lg p-4 border border-${color}-200`}>
    <div className="flex items-center gap-2 mb-2">
      <Icon className={`w-5 h-5 text-${color}-600`} />
      <span className={`text-sm font-medium text-${color}-900`}>{label}</span>
    </div>
    <div className={`text-2xl font-bold text-${color}-700`}>{value}</div>
    <div className={`text-xs text-${color}-600 mt-1`}>{detail}</div>
  </div>
)

const EmptyState = ({ icon: Icon, message, subtext }) => (
  <div className="text-center py-12 text-gray-500">
    <Icon className="w-12 h-12 mx-auto mb-4 opacity-30" />
    <p className="font-medium">{message}</p>
    {subtext && <p className="text-sm mt-1">{subtext}</p>}
  </div>
)

const AgentFlowItem = ({ agent }) => (
  <div className="flex items-center gap-3 bg-white rounded-lg p-3 border">
    <div className={`p-2 rounded-full ${agent.status === 'completed' ? 'bg-green-100' : agent.status === 'error' ? 'bg-red-100' : 'bg-blue-100'}`}>
      <Bot className={`w-4 h-4 ${agent.status === 'completed' ? 'text-green-600' : agent.status === 'error' ? 'text-red-600' : 'text-blue-600'}`} />
    </div>
    <div className="flex-1">
      <div className="font-medium text-gray-900">{agent.id}</div>
      <div className="text-xs text-gray-500">{agent.llmCalls.length} LLM calls, {agent.events.filter(e => e.data?.tool).length} tools</div>
    </div>
    <div className={`px-2 py-1 rounded text-xs font-medium ${agent.status === 'completed' ? 'bg-green-100 text-green-700' : agent.status === 'error' ? 'bg-red-100 text-red-700' : 'bg-blue-100 text-blue-700'}`}>
      {agent.status}
    </div>
  </div>
)

const AgentCard = ({ agent, isExpanded, onToggle }) => (
  <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
    <div className={`flex items-center justify-between p-4 cursor-pointer ${agent.status === 'completed' ? 'bg-green-50' : agent.status === 'error' ? 'bg-red-50' : 'bg-blue-50'}`} onClick={onToggle}>
      <div className="flex items-center gap-3">
        <Bot className={`w-5 h-5 ${agent.status === 'completed' ? 'text-green-600' : agent.status === 'error' ? 'text-red-600' : 'text-blue-600'}`} />
        <div>
          <div className="font-semibold text-gray-900">{agent.id}</div>
          <div className="text-xs text-gray-500">{agent.llmCalls.length} LLM iterations, {agent.events.length} events</div>
        </div>
      </div>
      <div className="flex items-center gap-2">
        <span className={`px-2 py-1 rounded text-xs font-medium ${agent.status === 'completed' ? 'bg-green-100 text-green-700' : agent.status === 'error' ? 'bg-red-100 text-red-700' : 'bg-blue-100 text-blue-700'}`}>
          {agent.status}
        </span>
        {isExpanded ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
      </div>
    </div>
    {isExpanded && (
      <div className="p-4 border-t border-gray-200 space-y-3">
        {agent.llmCalls.map((call, callIdx) => (
          <div key={callIdx} className="bg-purple-50 rounded-lg p-3 border border-purple-200">
            <div className="flex items-center gap-2 mb-2">
              <Brain className="w-4 h-4 text-purple-600" />
              <span className="text-sm font-medium text-purple-900">Iteration {call.iteration || callIdx + 1}</span>
              {call.tool_calls?.length > 0 && <span className="bg-orange-100 text-orange-700 px-2 py-0.5 rounded text-xs">{call.tool_calls.length} tools</span>}
            </div>
            {call.tool_calls?.length > 0 && (
              <div className="flex flex-wrap gap-1 mt-2">
                {call.tool_calls.map((tc, tcIdx) => (
                  <span key={tcIdx} className="bg-orange-200 text-orange-800 px-2 py-0.5 rounded text-xs font-mono">{tc.name || tc}</span>
                ))}
              </div>
            )}
          </div>
        ))}
        <div className="text-xs text-gray-500 mt-2">
          <strong>Events:</strong> {agent.events.map(e => e.type).join(' -> ')}
        </div>
      </div>
    )}
  </div>
)

const ToolCallItem = ({ tool }) => (
  <div className="bg-orange-50 rounded-lg border border-orange-200 p-3">
    <div className="flex items-center justify-between">
      <div className="flex items-center gap-2">
        <Hammer className="w-4 h-4 text-orange-600" />
        <span className="font-mono text-sm font-medium text-orange-900">{tool.name}</span>
        {tool.agent && <span className="bg-purple-100 text-purple-700 px-2 py-0.5 rounded text-xs">{tool.agent}</span>}
      </div>
      <span className={`px-2 py-0.5 rounded text-xs ${tool.status === 'success' || tool.status === 'completed' ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-700'}`}>
        {tool.status}
      </span>
    </div>
    {tool.args && <div className="mt-2 text-xs text-gray-600 font-mono bg-white rounded p-2 border">{typeof tool.args === 'string' ? tool.args : JSON.stringify(tool.args, null, 2)}</div>}
    {tool.timestamp && <div className="text-xs text-gray-400 mt-1">{new Date(tool.timestamp).toLocaleTimeString()}</div>}
  </div>
)

const EventItem = ({ event }) => (
  <div className={`rounded-lg border p-3 ${getStatusColors(event.status)}`}>
    <div className="flex items-center justify-between">
      <div className="flex items-center gap-2">
        <div className={`p-1 rounded-full ${getIconBgColor(event.status)}`}>{getEventIcon(event.type, event.status)}</div>
        <div>
          <span className="font-medium text-sm">{event.title || event.type}</span>
          {event.data?.agent_id && <span className="ml-2 bg-purple-100 text-purple-700 px-1.5 py-0.5 rounded text-xs">{event.data.agent_id}</span>}
        </div>
      </div>
      <span className="text-xs text-gray-500">{event.timestamp ? new Date(event.timestamp).toLocaleTimeString() : ''}</span>
    </div>
    {event.description && <div className="text-xs opacity-80 mt-1 ml-8">{event.description}</div>}
  </div>
)

const MessageDebugCard = ({ message, index, isExpanded, onToggle }) => {
  const isUser = message.role === 'user'
  const events = message.workflowEvents || []
  const llmCalls = message.llmCalls || []

  // Extract agents from events
  const agentsInMessage = new Set()
  events.forEach(e => {
    const agentId = e.data?.agent_id || e.agent_id
    if (agentId) agentsInMessage.add(agentId)
  })

  // Extract tool calls from events
  const toolCallsInMessage = events.filter(e => {
    const type = e.event_type || e.type || ''
    return type.includes('tool_') || e.data?.tool_name || e.data?.tool
  })

  return (
    <div className={`rounded-lg border overflow-hidden ${isUser ? 'bg-blue-50 border-blue-200' : 'bg-gray-50 border-gray-200'}`}>
      <div
        className={`flex items-center justify-between p-4 cursor-pointer ${isUser ? 'bg-blue-100' : 'bg-gray-100'}`}
        onClick={onToggle}
      >
        <div className="flex items-center gap-3">
          {isUser ? (
            <User className="w-5 h-5 text-blue-600" />
          ) : (
            <Bot className="w-5 h-5 text-purple-600" />
          )}
          <div className="flex-1">
            <div className="font-medium text-gray-900 truncate max-w-md">
              {message.content?.substring(0, 60)}{message.content?.length > 60 ? '...' : ''}
            </div>
            <div className="text-xs text-gray-500 flex items-center gap-2">
              <span>#{index + 1}</span>
              {message.timestamp && (
                <span>{new Date(message.timestamp).toLocaleTimeString()}</span>
              )}
              {!isUser && events.length > 0 && (
                <span className="bg-green-100 text-green-700 px-1.5 py-0.5 rounded">
                  {events.length} events
                </span>
              )}
              {!isUser && llmCalls.length > 0 && (
                <span className="bg-purple-100 text-purple-700 px-1.5 py-0.5 rounded">
                  {llmCalls.length} LLM calls
                </span>
              )}
              {!isUser && agentsInMessage.size > 0 && (
                <span className="bg-blue-100 text-blue-700 px-1.5 py-0.5 rounded">
                  {Array.from(agentsInMessage).join(', ')}
                </span>
              )}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {isExpanded ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
        </div>
      </div>

      {isExpanded && (
        <div className="p-4 border-t border-gray-200 space-y-4">
          {/* Full message content */}
          <div className="bg-white rounded-lg p-3 border">
            <div className="text-xs font-medium text-gray-500 uppercase mb-2">Message Content</div>
            <div className="text-sm text-gray-700 whitespace-pre-wrap">{message.content}</div>
          </div>

          {/* Agents used */}
          {agentsInMessage.size > 0 && (
            <div>
              <div className="text-xs font-medium text-blue-600 uppercase mb-2">Agents Used</div>
              <div className="flex flex-wrap gap-2">
                {Array.from(agentsInMessage).map((agentId, i) => (
                  <span key={i} className="bg-blue-100 text-blue-800 px-2 py-1 rounded text-sm font-medium flex items-center gap-1">
                    <Bot className="w-3 h-3" />
                    {agentId}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Tool calls */}
          {toolCallsInMessage.length > 0 && (
            <div>
              <div className="text-xs font-medium text-orange-600 uppercase mb-2">Tool Calls</div>
              <div className="space-y-2">
                {toolCallsInMessage.map((tool, i) => (
                  <div key={i} className="bg-orange-50 rounded-lg border border-orange-200 p-2">
                    <div className="flex items-center gap-2">
                      <Hammer className="w-4 h-4 text-orange-600" />
                      <span className="font-mono text-sm text-orange-900">
                        {tool.data?.tool_name || tool.data?.tool || tool.title}
                      </span>
                      {tool.data?.agent_id && (
                        <span className="bg-purple-100 text-purple-700 px-1.5 py-0.5 rounded text-xs">
                          {tool.data.agent_id}
                        </span>
                      )}
                    </div>
                    {tool.data?.args_preview && (
                      <div className="text-xs text-gray-600 mt-1 font-mono">{tool.data.args_preview}</div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* LLM Calls */}
          {llmCalls.length > 0 && (
            <div>
              <div className="text-xs font-medium text-purple-600 uppercase mb-2">LLM Calls</div>
              <div className="space-y-2">
                {llmCalls.map((call, i) => (
                  <div key={i} className="bg-purple-50 rounded-lg border border-purple-200 p-2">
                    <div className="flex items-center justify-between flex-wrap gap-2">
                      <div className="flex items-center gap-2">
                        <Brain className="w-4 h-4 text-purple-600" />
                        <span className="text-sm font-medium text-purple-900">
                          {call.agent_id || 'LLM'} - Iteration {call.iteration || i + 1}
                        </span>
                      </div>
                      <div className="flex items-center gap-2 text-xs flex-wrap">
                        {/* Model transparency */}
                        {call.model && (
                          <span className="bg-indigo-200 text-indigo-800 px-1.5 py-0.5 rounded font-medium">
                            {call.model}
                          </span>
                        )}
                        {call.duration_ms && (
                          <span className="text-purple-600">{call.duration_ms}ms</span>
                        )}
                        {call.usage?.total_tokens && (
                          <span className="bg-blue-100 text-blue-700 px-1.5 py-0.5 rounded">
                            {call.usage.total_tokens} tokens
                          </span>
                        )}
                      </div>
                    </div>
                    {call.response?.tool_calls?.length > 0 && (
                      <div className="flex flex-wrap gap-1 mt-2">
                        {call.response.tool_calls.map((tc, j) => (
                          <span key={j} className="bg-orange-200 text-orange-800 px-1.5 py-0.5 rounded text-xs font-mono">
                            {tc.name || tc.function?.name || 'tool'}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* All workflow events */}
          {events.length > 0 && (
            <div>
              <div className="text-xs font-medium text-green-600 uppercase mb-2">All Workflow Events</div>
              <div className="space-y-1 max-h-48 overflow-y-auto">
                {events.map((event, i) => (
                  <div key={i} className={`rounded p-2 text-sm ${getStatusColors(event.status)}`}>
                    <div className="flex items-center gap-2">
                      <div className={`p-0.5 rounded-full ${getIconBgColor(event.status)}`}>
                        {getEventIcon(event.event_type || event.type, event.status)}
                      </div>
                      <span className="font-medium">{event.title || event.event_type || event.type}</span>
                      {event.timestamp && (
                        <span className="text-xs text-gray-500">
                          {new Date(event.timestamp).toLocaleTimeString()}
                        </span>
                      )}
                    </div>
                    {event.description && (
                      <div className="text-xs opacity-80 ml-6 mt-1">{event.description}</div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Show empty state for user messages or assistant messages without events */}
          {isUser && (
            <div className="text-center text-gray-500 text-sm py-4">
              User messages don't have execution logs
            </div>
          )}
          {!isUser && events.length === 0 && llmCalls.length === 0 && (
            <div className="text-center text-gray-500 text-sm py-4">
              No execution data available for this message
            </div>
          )}
        </div>
      )}
    </div>
  )
}

const LLMCallCard = ({ call, idx, isExpanded, onToggle }) => {
  // Extract data - handle both old format (tool_calls at top level) and new format (response.tool_calls)
  const responseToolCalls = call.response?.tool_calls || call.tool_calls || []
  const responseContent = call.response?.content || null
  const messages = call.messages || []
  const tools = call.tools || []

  return (
    <div className="bg-purple-50 rounded-lg border border-purple-200 overflow-hidden">
      <div className="flex items-center justify-between p-4 bg-purple-100 cursor-pointer" onClick={onToggle}>
        <div className="flex items-center gap-3">
          <Brain className="w-5 h-5 text-purple-600" />
          <div>
            <span className="font-medium text-purple-900">{call.agent_id || 'LLM Call'}</span>
            <span className="text-xs text-purple-600 ml-2">iter {call.iteration || idx + 1}</span>
          </div>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          {/* Model transparency */}
          {call.model && (
            <span className="text-xs bg-indigo-200 text-indigo-800 px-2 py-0.5 rounded font-medium">
              {call.model}
            </span>
          )}
          {call.provider && (
            <span className="text-xs bg-gray-200 text-gray-700 px-2 py-0.5 rounded">
              {call.provider}
            </span>
          )}
          {messages.length > 0 && (
            <span className="text-xs bg-blue-100 text-blue-700 px-2 py-0.5 rounded">
              {messages.length} msgs
            </span>
          )}
          {tools.length > 0 && (
            <span className="text-xs bg-orange-100 text-orange-700 px-2 py-0.5 rounded">
              {tools.length} tools
            </span>
          )}
          {call.usage?.total_tokens && <span className="text-xs bg-green-100 text-green-700 px-2 py-0.5 rounded">{call.usage.total_tokens} tokens</span>}
          {call.duration_ms && <span className="text-xs text-purple-600">{call.duration_ms}ms</span>}
          {isExpanded ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
        </div>
      </div>
      {isExpanded && (
        <div className="p-4 space-y-4">
          {/* Request Messages */}
          {messages.length > 0 && (
            <details className="group">
              <summary className="text-xs font-medium text-blue-600 uppercase cursor-pointer flex items-center gap-2">
                <ChevronRight className="w-3 h-3 group-open:rotate-90 transition-transform" />
                Request Messages ({messages.length})
              </summary>
              <div className="mt-2 space-y-2 max-h-64 overflow-y-auto">
                {messages.map((msg, msgIdx) => (
                  <div key={msgIdx} className={`p-2 rounded border text-xs ${
                    msg.role === 'system' ? 'bg-gray-100 border-gray-300' :
                    msg.role === 'user' ? 'bg-blue-50 border-blue-200' :
                    msg.role === 'assistant' ? 'bg-purple-50 border-purple-200' :
                    'bg-orange-50 border-orange-200'
                  }`}>
                    <div className="font-medium mb-1 capitalize">{msg.role}</div>
                    <div className="whitespace-pre-wrap font-mono text-gray-700 max-h-32 overflow-y-auto">
                      {typeof msg.content === 'string'
                        ? msg.content.substring(0, 1000) + (msg.content.length > 1000 ? '...' : '')
                        : JSON.stringify(msg.content, null, 2)}
                    </div>
                    {msg.tool_calls && msg.tool_calls.length > 0 && (
                      <div className="mt-2 pt-2 border-t border-gray-200">
                        <div className="text-orange-600 font-medium">Tool Calls:</div>
                        {msg.tool_calls.map((tc, tcIdx) => (
                          <div key={tcIdx} className="mt-1 bg-orange-100 p-1 rounded">
                            <span className="font-mono">{tc.function?.name || tc.name}</span>
                            {tc.function?.arguments && (
                              <pre className="text-xs mt-1 overflow-x-auto">{
                                typeof tc.function.arguments === 'string'
                                  ? tc.function.arguments.substring(0, 500)
                                  : JSON.stringify(tc.function.arguments, null, 2).substring(0, 500)
                              }</pre>
                            )}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </details>
          )}

          {/* Tools Provided */}
          {tools.length > 0 && (
            <details className="group">
              <summary className="text-xs font-medium text-orange-600 uppercase cursor-pointer flex items-center gap-2">
                <ChevronRight className="w-3 h-3 group-open:rotate-90 transition-transform" />
                Tools Provided ({tools.length})
              </summary>
              <div className="mt-2 flex flex-wrap gap-2">
                {tools.map((tool, toolIdx) => (
                  <div key={toolIdx} className="bg-orange-100 border border-orange-300 rounded p-2 text-xs">
                    <div className="font-mono font-medium text-orange-800">
                      {tool.function?.name || tool.name || 'tool'}
                    </div>
                    {(tool.function?.description || tool.description) && (
                      <div className="text-gray-600 mt-1 max-w-xs truncate">
                        {tool.function?.description || tool.description}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </details>
          )}

          {/* Response Content */}
          {responseContent && (
            <details className="group" open>
              <summary className="text-xs font-medium text-green-600 uppercase cursor-pointer flex items-center gap-2">
                <ChevronRight className="w-3 h-3 group-open:rotate-90 transition-transform" />
                Response Content
              </summary>
              <div className="mt-2 bg-green-50 border border-green-200 rounded p-3">
                <pre className="text-xs text-gray-800 whitespace-pre-wrap font-mono max-h-48 overflow-y-auto">
                  {responseContent}
                </pre>
              </div>
            </details>
          )}

          {/* Response Tool Calls */}
          {responseToolCalls.length > 0 && (
            <details className="group" open>
              <summary className="text-xs font-medium text-orange-600 uppercase cursor-pointer flex items-center gap-2">
                <ChevronRight className="w-3 h-3 group-open:rotate-90 transition-transform" />
                Response Tool Calls ({responseToolCalls.length})
              </summary>
              <div className="mt-2 space-y-2">
                {responseToolCalls.map((tc, tcIdx) => (
                  <div key={tcIdx} className="bg-orange-50 border border-orange-300 rounded p-2">
                    <div className="font-mono font-medium text-orange-800 text-sm">
                      {tc.function?.name || tc.name || 'tool'}
                    </div>
                    {(tc.function?.arguments || tc.arguments) && (
                      <pre className="mt-1 text-xs bg-white p-2 rounded border overflow-x-auto max-h-32">
                        {typeof (tc.function?.arguments || tc.arguments) === 'string'
                          ? tc.function?.arguments || tc.arguments
                          : JSON.stringify(tc.function?.arguments || tc.arguments, null, 2)}
                      </pre>
                    )}
                  </div>
                ))}
              </div>
            </details>
          )}

          {/* Token usage breakdown */}
          {call.usage && (
            <div className="flex items-center gap-4 text-xs text-gray-600 pt-2 border-t">
              <span>Prompt: {call.usage.prompt_tokens || 0}</span>
              <span>Completion: {call.usage.completion_tokens || 0}</span>
              <span className="font-medium">Total: {call.usage.total_tokens || 0}</span>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export default DebugPanel
