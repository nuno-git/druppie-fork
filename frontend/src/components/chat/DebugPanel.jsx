import { useState, useMemo } from 'react'
import { ChevronDown, ChevronRight, Copy, Check, Bot, Wrench, Brain, X } from 'lucide-react'

/**
 * Simplified Debug Panel - Single overview with expandable agents
 */
export default function DebugPanel({
  isOpen,
  onClose,
  sessionId,
  workflowEvents = [],
  llmCalls = [],
  workspaceInfo,
}) {
  const [expandedAgents, setExpandedAgents] = useState(new Set())
  const [expandedLLMCalls, setExpandedLLMCalls] = useState(new Set())
  const [copied, setCopied] = useState(false)

  // Build agent data from events and LLM calls
  const agents = useMemo(() => {
    const agentMap = new Map()

    // Process events
    workflowEvents.forEach(event => {
      const eventType = event.event_type || event.type || ''
      const agentId = event.agent_id || event.data?.agent_id

      if ((eventType.includes('agent_start') || eventType.includes('agent_started')) && agentId) {
        if (!agentMap.has(agentId)) {
          agentMap.set(agentId, {
            id: agentId,
            status: 'running',
            startTime: event.timestamp,
            llmCalls: [],
            toolCalls: [],
          })
        }
      }
      if ((eventType.includes('agent_complete') || eventType.includes('agent_completed')) && agentId && agentMap.has(agentId)) {
        agentMap.get(agentId).status = 'completed'
        agentMap.get(agentId).endTime = event.timestamp
      }
      if (eventType === 'agent_paused' && agentId && agentMap.has(agentId)) {
        agentMap.get(agentId).status = 'paused'
      }
      if ((eventType === 'agent_error' || eventType === 'agent_failed') && agentId && agentMap.has(agentId)) {
        agentMap.get(agentId).status = 'error'
        agentMap.get(agentId).error = event.error || event.data?.error
      }
    })

    // Add LLM calls to agents
    llmCalls.forEach(call => {
      const agentId = call.agent_id
      if (agentId) {
        if (!agentMap.has(agentId)) {
          agentMap.set(agentId, {
            id: agentId,
            status: 'completed',
            llmCalls: [],
            toolCalls: [],
          })
        }
        agentMap.get(agentId).llmCalls.push(call)

        // Extract tool calls from LLM response
        const toolCalls = call.response?.tool_calls || call.tool_calls || []
        toolCalls.forEach(tc => {
          agentMap.get(agentId).toolCalls.push({
            name: tc.function?.name || tc.name,
            args: tc.function?.arguments || tc.arguments,
          })
        })
      }
    })

    return Array.from(agentMap.values())
  }, [workflowEvents, llmCalls])

  // Calculate totals
  const totalTokens = llmCalls.reduce((sum, c) => sum + (c.usage?.total_tokens || c.total_tokens || 0), 0)
  const totalDuration = llmCalls.reduce((sum, c) => sum + (c.duration_ms || 0), 0)

  const toggleAgent = (agentId) => {
    const newSet = new Set(expandedAgents)
    if (newSet.has(agentId)) {
      newSet.delete(agentId)
    } else {
      newSet.add(agentId)
    }
    setExpandedAgents(newSet)
  }

  const toggleLLMCall = (key) => {
    const newSet = new Set(expandedLLMCalls)
    if (newSet.has(key)) {
      newSet.delete(key)
    } else {
      newSet.add(key)
    }
    setExpandedLLMCalls(newSet)
  }

  const copyTrace = () => {
    const text = generateTraceText()
    navigator.clipboard.writeText(text)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  const generateTraceText = () => {
    let text = `EXECUTION TRACE\n${'='.repeat(60)}\n\n`
    text += `Session: ${sessionId}\n`
    text += `Total Tokens: ${totalTokens}\n`
    text += `Total Duration: ${(totalDuration / 1000).toFixed(1)}s\n\n`

    agents.forEach((agent, idx) => {
      text += `[${idx + 1}] ${agent.id.toUpperCase()} - ${agent.status}\n`
      agent.llmCalls.forEach((call, i) => {
        text += `  LLM Call ${i + 1}: ${call.model} (${call.usage?.total_tokens || call.total_tokens || 0} tokens, ${call.duration_ms}ms)\n`
        if (call.response?.content) {
          text += `  Response: ${call.response.content.substring(0, 200)}...\n`
        }
      })
      if (agent.toolCalls.length > 0) {
        text += `  Tools: ${agent.toolCalls.map(t => t.name).join(', ')}\n`
      }
      text += '\n'
    })

    return text
  }

  const getStatusColor = (status) => {
    switch (status) {
      case 'completed': return 'text-green-600 bg-green-50'
      case 'running': return 'text-blue-600 bg-blue-50'
      case 'paused': return 'text-yellow-600 bg-yellow-50'
      case 'error': return 'text-red-600 bg-red-50'
      default: return 'text-gray-600 bg-gray-50'
    }
  }

  if (!isOpen) return null

  return (
    <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-lg shadow-xl max-w-3xl w-full max-h-[80vh] overflow-hidden flex flex-col">
        {/* Header */}
        <div className="px-4 py-3 bg-gray-50 border-b flex items-center justify-between">
          <div className="flex items-center gap-4">
            <h3 className="font-medium text-gray-900">Execution Trace</h3>
            <span className="text-sm text-gray-500">{totalTokens} tokens</span>
            <span className="text-sm text-gray-500">{(totalDuration / 1000).toFixed(1)}s</span>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={copyTrace}
              className="flex items-center gap-1 text-sm text-gray-600 hover:text-gray-900 px-2 py-1 rounded hover:bg-gray-100"
            >
              {copied ? <Check className="w-4 h-4" /> : <Copy className="w-4 h-4" />}
              {copied ? 'Copied' : 'Copy'}
            </button>
            <button
              onClick={onClose}
              className="p-1 text-gray-500 hover:text-gray-700 hover:bg-gray-100 rounded"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto">
          {/* Workspace Info */}
          {workspaceInfo && (
            <div className="px-4 py-2 bg-blue-50 border-b text-sm text-blue-800">
              Workspace: {workspaceInfo.workspace_id?.substring(0, 8)}...
            </div>
          )}

          {/* Agents List */}
          <div className="divide-y divide-gray-100">
            {agents.length === 0 ? (
              <div className="p-8 text-center text-gray-500">
                <Bot className="w-12 h-12 mx-auto mb-3 text-gray-300" />
                <p>No agents executed yet</p>
                <p className="text-sm mt-1">Start a conversation to see execution trace</p>
              </div>
            ) : (
              agents.map((agent) => (
                <div key={agent.id}>
                  {/* Agent Header */}
                  <div
                    className="flex items-center justify-between p-3 cursor-pointer hover:bg-gray-50"
                    onClick={() => toggleAgent(agent.id)}
                  >
                    <div className="flex items-center gap-3">
                      {expandedAgents.has(agent.id) ? (
                        <ChevronDown className="w-4 h-4 text-gray-400" />
                      ) : (
                        <ChevronRight className="w-4 h-4 text-gray-400" />
                      )}
                      <Bot className="w-5 h-5 text-indigo-600" />
                      <span className="font-medium text-gray-900 capitalize">{agent.id}</span>
                      <span className={`text-xs px-2 py-0.5 rounded ${getStatusColor(agent.status)}`}>
                        {agent.status}
                      </span>
                    </div>
                    <div className="flex items-center gap-3 text-sm text-gray-500">
                      {agent.llmCalls.length > 0 && (
                        <span className="flex items-center gap-1">
                          <Brain className="w-4 h-4" />
                          {agent.llmCalls.length}
                        </span>
                      )}
                      {agent.toolCalls.length > 0 && (
                        <span className="flex items-center gap-1">
                          <Wrench className="w-4 h-4" />
                          {agent.toolCalls.length}
                        </span>
                      )}
                    </div>
                  </div>

                  {/* Agent Details (expanded) */}
                  {expandedAgents.has(agent.id) && (
                    <div className="px-4 pb-4 space-y-3 bg-gray-50">
                      {/* Tool Calls Summary */}
                      {agent.toolCalls.length > 0 && (
                        <div className="mt-2">
                          <div className="text-xs font-medium text-gray-500 uppercase mb-2">Tools Used</div>
                          <div className="flex flex-wrap gap-2">
                            {agent.toolCalls.map((tool, i) => (
                              <span key={i} className="px-2 py-1 bg-orange-100 text-orange-800 text-xs rounded font-mono">
                                {tool.name}
                              </span>
                            ))}
                          </div>
                        </div>
                      )}

                      {/* LLM Calls */}
                      {agent.llmCalls.map((call, idx) => {
                        const callKey = `${agent.id}-${idx}`
                        const isExpanded = expandedLLMCalls.has(callKey)

                        return (
                          <div key={idx} className="bg-white rounded border border-gray-200">
                            <div
                              className="flex items-center justify-between p-3 cursor-pointer hover:bg-gray-50"
                              onClick={(e) => { e.stopPropagation(); toggleLLMCall(callKey) }}
                            >
                              <div className="flex items-center gap-2">
                                {isExpanded ? (
                                  <ChevronDown className="w-4 h-4 text-gray-400" />
                                ) : (
                                  <ChevronRight className="w-4 h-4 text-gray-400" />
                                )}
                                <span className="text-sm font-medium text-gray-700">
                                  {call.model || 'LLM Call'} #{idx + 1}
                                </span>
                              </div>
                              <div className="flex items-center gap-3 text-xs text-gray-500">
                                <span>{call.usage?.total_tokens || call.total_tokens || 0} tokens</span>
                                <span>{call.duration_ms}ms</span>
                              </div>
                            </div>

                            {isExpanded && (
                              <div className="border-t border-gray-100 p-3 space-y-3">
                                {/* Response Content */}
                                {(call.response?.content || call.content) && (
                                  <div>
                                    <div className="text-xs font-medium text-gray-500 uppercase mb-1">Response</div>
                                    <pre className="text-xs bg-gray-100 p-2 rounded overflow-auto max-h-40 whitespace-pre-wrap">
                                      {call.response?.content || call.content}
                                    </pre>
                                  </div>
                                )}

                                {/* Tool Calls from this LLM call */}
                                {(call.response?.tool_calls?.length > 0 || call.tool_calls?.length > 0) && (
                                  <div>
                                    <div className="text-xs font-medium text-gray-500 uppercase mb-1">Tool Calls</div>
                                    {(call.response?.tool_calls || call.tool_calls || []).map((tc, i) => (
                                      <div key={i} className="bg-orange-50 p-2 rounded mb-1 text-xs">
                                        <span className="font-mono font-medium text-orange-800">
                                          {tc.function?.name || tc.name}
                                        </span>
                                        {(tc.function?.arguments || tc.arguments) && (
                                          <pre className="mt-1 text-gray-600 overflow-auto max-h-20">
                                            {typeof (tc.function?.arguments || tc.arguments) === 'string'
                                              ? (tc.function?.arguments || tc.arguments).substring(0, 300)
                                              : JSON.stringify(tc.function?.arguments || tc.arguments, null, 2).substring(0, 300)}
                                          </pre>
                                        )}
                                      </div>
                                    ))}
                                  </div>
                                )}

                                {/* Token breakdown */}
                                <div className="flex gap-4 text-xs text-gray-500">
                                  <span>Prompt: {call.usage?.prompt_tokens || call.prompt_tokens || 0}</span>
                                  <span>Completion: {call.usage?.completion_tokens || call.completion_tokens || 0}</span>
                                </div>
                              </div>
                            )}
                          </div>
                        )
                      })}
                    </div>
                  )}
                </div>
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
